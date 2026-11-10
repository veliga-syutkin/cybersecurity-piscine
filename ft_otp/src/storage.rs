use std::fs::{self, OpenOptions, Permissions};
use std::io::Write;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};

use aes_gcm::aead::{Aead, KeyInit, Payload};
use aes_gcm::{Aes256Gcm, Key, Nonce};
use argon2::Argon2;

use crate::errors::{describe_io, file_error, Error};
use crate::options::Passphrase;

pub const KEY_FILE: &str = "ft_otp.key"; // what -g writes, in the current dir
const MACHINE_ID_PATH: &str = "/etc/machine-id";
const KEY_FILE_RIGHTS: u32 = 0o600; // rw- --- ---: only the owner reads it
const PASSPHRASE_PROMPT: &str = "Passphrase: ";

// The first byte of ft_otp.key: what protects it (see get_secret)
const MODE_MACHINE: u8 = 0;
const MODE_PASSPHRASE: u8 = 1;

/*
  ft_otp.key, byte by byte:
	| mode | salt     | nonce    | encrypted key + tag (16 bytes) |
	| 1    | SALT_LEN | NONCE_LEN| key length + TAG_LEN           |
  The header (mode + salt + nonce) is not secret, but it is authenticated:
  it is given to AES-GCM as "associated data", so changing the mode byte
  (or anything else) makes the decryption fail instead of going wrong.
*/
const MODE_LEN: usize = 1;
const SALT_LEN: usize = 16; // Argon2: a new random salt at each -g
const NONCE_LEN: usize = 12; // AES-GCM: 96-bit nonce, never reused
const TAG_LEN: usize = 16; // AES-GCM: the tag which detects any change
const HEADER_LEN: usize = MODE_LEN + SALT_LEN + NONCE_LEN;
const AES_KEY_LEN: usize = 32; // AES-256

/* The content of /etc/machine-id (a random id made at install time),
without its final '\n'. It is the secret of a key file without -p.
*/
fn machine_id() -> Result<Vec<u8>, Error> {
	let id = fs::read_to_string(MACHINE_ID_PATH)
		.map_err(|e| file_error("read", MACHINE_ID_PATH, &e))?;
	let id = id.trim();
	if id.is_empty() {
		return Err(Error::Fatal(format!("{} is empty", MACHINE_ID_PATH)));
	}
	Ok(id.as_bytes().to_vec())
}

/* The passphrase, asked (hidden: no echo) or as given with -p=x.
An empty one is refused: it would protect nothing.
*/
fn passphrase(source: &Passphrase) -> Result<Vec<u8>, Error> {
	let text = match source {
		Passphrase::Given(text) => text.clone(),
		_ => rpassword::prompt_password(PASSPHRASE_PROMPT).map_err(|e| {
			Error::Fatal(format!("cannot read passphrase: {}", describe_io(&e)))
		})?,
	};
	if text.is_empty() {
		return Err(Error::Fatal("passphrase must not be empty".to_string()));
	}
	Ok(text.into_bytes())
}

/* The secret the AES key is made from, chosen by MODE:
	MODE_MACHINE      /etc/machine-id: nothing to type, but anyone on this
	                  machine can decrypt (the file is useless elsewhere).
	MODE_PASSPHRASE   the passphrase INSTEAD of machine-id: the file can
	                  be used on any machine, by who knows the passphrase.
*/
fn get_secret(mode: u8, source: &Passphrase) -> Result<Vec<u8>, Error> {
	match mode {
		MODE_PASSPHRASE => passphrase(source),
		_ => machine_id(),
	}
}

/* Argon2id(SECRET, SALT) -> the 32 bytes of the AES-256 key.
Argon2id is slow and needs memory on purpose: each guess of a
passphrase costs an attacker the same. Default settings of the crate
(19 MiB, 2 passes), the ones recommended by OWASP.
*/
fn derive_key(secret: &[u8], salt: &[u8]) -> Result<[u8; AES_KEY_LEN], Error> {
	let mut aes_key = [0u8; AES_KEY_LEN];

	Argon2::default()
		.hash_password_into(secret, salt, &mut aes_key)
		.map_err(|e| Error::Fatal(format!("key derivation failed: {}", e)))?;
	Ok(aes_key)
}

/* Writes DATA in PATH with KEY_FILE_RIGHTS (owner only), replacing it if
it exists. mode () only applies when the file is CREATED: set_permissions
also fixes the rights of an old file.
Used for ft_otp.key, and by the bonus for the QR code's SVG (which shows
the key in clear).
*/
pub fn write_private_file(path: &str, data: &[u8]) -> Result<(), Error> {
	let mut file = OpenOptions::new()
		.write(true)
		.create(true)
		.truncate(true)
		.mode(KEY_FILE_RIGHTS)
		.open(path)
		.map_err(|e| file_error("create", path, &e))?;
	fs::set_permissions(path, Permissions::from_mode(KEY_FILE_RIGHTS))
		.map_err(|e| file_error("protect", path, &e))?;
	file.write_all(data).map_err(|e| file_error("write", path, &e))
}

/* -g: encrypts KEY (its bytes) into KEY_FILE.
	1) mode: MODE_PASSPHRASE if -p was given, else MODE_MACHINE
	2) a random salt and nonce (getrandom: the kernel's random source)
	3) AES key = Argon2id(secret, salt)
	4) AES-256-GCM(KEY), the header as associated data
	5) KEY_FILE = header + encrypted key
*/
pub fn save_key(key: &[u8], source: &Passphrase) -> Result<(), Error> {
	let mode = match source {
		Passphrase::Absent => MODE_MACHINE,
		_ => MODE_PASSPHRASE,
	};
	let mut header = [0u8; HEADER_LEN];
	header[0] = mode;
	getrandom::getrandom(&mut header[MODE_LEN..])
		.map_err(|e| Error::Fatal(format!("no random source: {}", e)))?;

	let aes_key = derive_key(&get_secret(mode, source)?, &header[MODE_LEN..MODE_LEN + SALT_LEN])?;
	let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(&aes_key));
	let nonce = Nonce::from_slice(&header[MODE_LEN + SALT_LEN..]);
	let encrypted = cipher
		.encrypt(nonce, Payload { msg: key, aad: &header })
		.map_err(|_| Error::Fatal("encryption failed".to_string()))?;
	write_private_file(KEY_FILE, &[&header[..], &encrypted].concat())
}

/* The message when AES-GCM refuses to decrypt: the tag does not match,
so either the secret is wrong, or the file was changed.
*/
fn decrypt_error(path: &str, mode: u8) -> Error {
	Error::Fatal(match mode {
		MODE_PASSPHRASE => format!("cannot decrypt {}: wrong passphrase or corrupted file", path),
		_ => format!("cannot decrypt {}: corrupted file, or made on another machine", path),
	})
}

/* Whether the key file PATH is protected by a passphrase (its mode byte).
The bonus GUI asks it BEFORE decrypting, to show its passphrase field
(load_key would else prompt on the terminal). Unused by ft_otp.
*/
#[allow(dead_code)]
pub fn needs_passphrase(path: &str) -> Result<bool, Error> {
	let data = fs::read(path).map_err(|e| file_error("read", path, &e))?;
	Ok(data.first() == Some(&MODE_PASSPHRASE))
}

/* -k: reads PATH (made by save_key) and gives back the key's bytes.
The mode byte tells which secret to use: a file made with -p asks for
its passphrase even if -p is not given now. -p on a machine-id file is
ignored. Returns the key, or an error (bad file, wrong secret).
*/
pub fn load_key(path: &str, source: &Passphrase) -> Result<Vec<u8>, Error> {
	let data = fs::read(path).map_err(|e| file_error("read", path, &e))?;
	if data.len() < HEADER_LEN + TAG_LEN
		|| (data[0] != MODE_MACHINE && data[0] != MODE_PASSPHRASE)
	{
		return Err(Error::Fatal(format!("{} is not a valid key file", path)));
	}
	let (header, encrypted) = data.split_at(HEADER_LEN);
	let mode = header[0];

	let aes_key = derive_key(&get_secret(mode, source)?, &header[MODE_LEN..MODE_LEN + SALT_LEN])?;
	let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(&aes_key));
	let nonce = Nonce::from_slice(&header[MODE_LEN + SALT_LEN..]);
	cipher
		.decrypt(nonce, Payload { msg: encrypted, aad: header })
		.map_err(|_| decrypt_error(path, mode))
}

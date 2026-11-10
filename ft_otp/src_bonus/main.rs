// The mandatory part's modules, reused as they are (src/ is not changed by
// the bonus). Some of their functions are only used by ft_otp: allowed.
#[allow(dead_code)]
#[path = "../src/errors.rs"]
mod errors;
#[path = "../src/key.rs"]
mod key;
#[allow(dead_code)]
#[path = "../src/options.rs"]
mod options;
#[path = "../src/storage.rs"]
mod storage;
#[path = "../src/totp.rs"]
mod totp;

mod gui;
mod options_bonus;
mod qr;

use std::env;
use std::process;

use errors::Error;
use options_bonus::{Mode, Options};

const PROGRAM_NAME: &str = "ft_otp_bonus"; // if argv[0] is missing
const EXIT_FAILURE: i32 = 1;
const SEED_LEN: usize = 32; // bytes = 64 hex characters, the subject's minimum

/* The operand of -g / -k / -q: always there, check_options made sure. */
fn operand(options: &Options) -> &str {
	options.operand.as_deref().unwrap_or_default()
}

/* -g: same as the mandatory part. */
fn generate(options: &Options) -> Result<(), Error> {
	let hex = key::read_hex_key(operand(options), options.raw)?;
	let key = key::decode_hex_key(&hex)?;
	storage::save_key(&key, &options.passphrase)?;
	println!("Key was successfully saved in {}.", storage::KEY_FILE);
	Ok(())
}

/* -k: same as the mandatory part. */
fn show(options: &Options) -> Result<(), Error> {
	let key = storage::load_key(operand(options), &options.passphrase)?;
	println!("{}", totp::totp_now(&key)?);
	Ok(())
}

/* -s: the "seed generation" of the subject.
	1) SEED_LEN random bytes, from the kernel (getrandom)
	2) stored encrypted in ft_otp.key, exactly like -g (-p works too)
	3) its QR code, to scan it with a phone
The new key never touches the disk in clear (only with --svg, owner-only).
*/
fn seed(options: &Options) -> Result<(), Error> {
	let mut key = [0u8; SEED_LEN];

	getrandom::getrandom(&mut key)
		.map_err(|e| Error::Fatal(format!("no random source: {}", e)))?;
	storage::save_key(&key, &options.passphrase)?;
	println!("Key was successfully saved in {}.", storage::KEY_FILE);
	qr::show_qr(&key, options.svg)
}

/* -q: the QR code of a key already stored (by -g, -s or ft_otp). */
fn show_qr(options: &Options) -> Result<(), Error> {
	let key = storage::load_key(operand(options), &options.passphrase)?;
	qr::show_qr(&key, options.svg)
}

fn run(args: &[String]) -> Result<(), Error> {
	let options = options_bonus::parse_options(args)?;

	match options.mode {
		Mode::Generate => generate(&options),
		Mode::Show => show(&options),
		Mode::Seed => seed(&options),
		Mode::Qr => show_qr(&options),
		Mode::Gui => gui::run_gui(options.operand.as_deref()),
	}
}

/* Same as ft_otp's main, with the bonus usage. */
fn main() {
	let args: Vec<String> = env::args().collect();
	let program = args.first().map_or(PROGRAM_NAME, |name| name.as_str());

	if let Err(error) = run(args.get(1..).unwrap_or(&[])) {
		errors::report(program, &error);
		if let Error::Usage(_) = error {
			options_bonus::print_usage(program);
		}
		process::exit(EXIT_FAILURE);
	}
}

use std::env;
use std::io::{self, Write};

use qrcode::render::svg;
use qrcode::{Color, QrCode};

use crate::errors::{describe_io, Error};
use crate::storage;
use crate::totp::{DIGITS, TIME_STEP};

// Base32 (RFC 4648): what otpauth:// URIs use for the secret
const BASE32_ALPHABET: &[u8; 32] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
const BITS_PER_BYTE: u32 = 8;
const BITS_PER_CHAR: u32 = 5; // 2^5 = 32 letters
const CHAR_MASK: u32 = 0x1f; // the 5 lowest bits

// otpauth:// URI (Google Authenticator's "Key Uri Format")
const ISSUER: &str = "ft_otp";
const DEFAULT_USER: &str = "user"; // if $USER is not set
const URI_SAFE: &[u8] = b"-._~"; // with letters and digits: never escaped

// Drawing
const QUIET_ZONE: isize = 4; // white margin a scanner needs (ISO 18004)
const SVG_FILE: &str = "ft_otp_qr.svg";
const SVG_MIN_SIZE: u32 = 256; // pixels
const ANSI_RESET: &str = "\x1b[0m";
const ANSI_FG_BLACK: u8 = 30;
const ANSI_FG_WHITE: u8 = 97;
const ANSI_BG_BLACK: u8 = 40;
const ANSI_BG_WHITE: u8 = 107;
const UPPER_HALF_BLOCK: char = '▀'; // its top is the text color, its bottom the background

/*
  Base32, by hand: the same idea as hex (4 bits per digit), with 5 bits
  per character. Bytes are pushed in BUFFER 8 bits at a time, and taken
  out 5 bits at a time, from the left (big-endian, like everything here):
	"f" = 0x66 = 01100 110(00)  ->  M (12), Y (24)  ->  "MY"
  The last bits are padded with zeros on the right. No '=' padding: the
  otpauth:// format leaves it out.
*/
pub fn base32(data: &[u8]) -> String {
	let mut text = String::new();
	let mut buffer: u32 = 0; // bits waiting to be encoded (the lowest ones)
	let mut bits: u32 = 0; // how many of them

	for &byte in data {
		buffer = buffer << BITS_PER_BYTE | byte as u32;
		bits += BITS_PER_BYTE;
		while bits >= BITS_PER_CHAR {
			bits -= BITS_PER_CHAR;
			text.push(BASE32_ALPHABET[(buffer >> bits & CHAR_MASK) as usize] as char);
		}
		buffer &= (1 << bits) - 1; // drops what was encoded
	}
	if bits > 0 {
		let last = buffer << (BITS_PER_CHAR - bits) & CHAR_MASK;
		text.push(BASE32_ALPHABET[last as usize] as char);
	}
	text
}

/* Percent-encoding for the URI: letters, digits and URI_SAFE stay, any
other byte becomes %XX ("jean pierre" -> "jean%20pierre").
*/
fn uri_escape(text: &str) -> String {
	text.bytes()
		.map(|b| match b.is_ascii_alphanumeric() || URI_SAFE.contains(&b) {
			true => (b as char).to_string(),
			false => format!("%{:02X}", b),
		})
		.collect()
}

/* What the QR code contains, read by Google Authenticator & co:
otpauth://totp/ft_otp:USER?secret=BASE32&issuer=ft_otp&algorithm=SHA1&digits=6&period=30
The settings are the ones of totp.rs, so the phone computes our codes.
*/
fn otpauth_uri(key: &[u8]) -> String {
	let user = env::var("USER").unwrap_or_else(|_| DEFAULT_USER.to_string());

	format!(
		"otpauth://totp/{issuer}:{user}?secret={secret}&issuer={issuer}\
		&algorithm=SHA1&digits={digits}&period={period}",
		issuer = ISSUER,
		user = uri_escape(&user),
		secret = base32(key),
		digits = DIGITS,
		period = TIME_STEP,
	)
}

/* Draws CODE in the terminal, two rows of modules per line: each
UPPER_HALF_BLOCK gets the top module as text color and the bottom one as
background. The colors are forced (black on white) with ANSI codes, so
it scans the same on a dark or a light terminal.
The drawing is built first, then written at once: println! would panic
if stdout is closed early ("| head"), write_all returns an error instead.
*/
fn print_terminal(code: &QrCode) -> Result<(), Error> {
	let width = code.width() as isize;
	let colors = code.to_colors();
	let is_dark = |x: isize, y: isize| {
		x >= 0 && y >= 0 && x < width && y < width
			&& colors[(y * width + x) as usize] == Color::Dark
	};
	let mut drawing = String::new();

	for y in (-QUIET_ZONE..width + QUIET_ZONE).step_by(2) {
		for x in -QUIET_ZONE..width + QUIET_ZONE {
			let fg = if is_dark(x, y) { ANSI_FG_BLACK } else { ANSI_FG_WHITE };
			let bg = if is_dark(x, y + 1) { ANSI_BG_BLACK } else { ANSI_BG_WHITE };
			drawing.push_str(&format!("\x1b[{};{}m{}", fg, bg, UPPER_HALF_BLOCK));
		}
		drawing.push_str(ANSI_RESET);
		drawing.push('\n');
	}
	io::stdout()
		.write_all(drawing.as_bytes())
		.map_err(|e| Error::Fatal(format!("cannot print the QR code: {}", describe_io(&e))))
}

/* The QR code of KEY (its otpauth:// URI), for the terminal, the SVG
file and the GUI window.
*/
pub fn qr_code(key: &[u8]) -> Result<QrCode, Error> {
	QrCode::new(otpauth_uri(key).as_bytes())
		.map_err(|e| Error::Fatal(format!("cannot make the QR code: {}", e)))
}

/* Shows the QR code of KEY in the terminal, and with --svg (SVG) also
writes it in SVG_FILE. The QR code holds the key IN CLEAR: the SVG is
written owner-only, like ft_otp.key.
*/
pub fn show_qr(key: &[u8], svg: bool) -> Result<(), Error> {
	let code = qr_code(key)?;

	print_terminal(&code)?;
	if svg {
		let image = code
			.render::<svg::Color>()
			.min_dimensions(SVG_MIN_SIZE, SVG_MIN_SIZE)
			.build();
		storage::write_private_file(SVG_FILE, image.as_bytes())?;
		println!("QR code saved in {}.", SVG_FILE);
	}
	Ok(())
}

#[cfg(test)]
mod tests {
	use super::*;

	/* RFC 4648, section 10 (without the '=' padding). */
	#[test]
	fn rfc4648_base32_vectors() {
		let expected = [
			("", ""),
			("f", "MY"),
			("fo", "MZXQ"),
			("foo", "MZXW6"),
			("foob", "MZXW6YQ"),
			("fooba", "MZXW6YTB"),
			("foobar", "MZXW6YTBOI"),
		];
		for (data, text) in expected {
			assert_eq!(base32(data.as_bytes()), text);
		}
	}

	/* The RFC 4226 test key, in the format Google Authenticator reads. */
	#[test]
	fn otpauth_uri_format() {
		env::set_var("USER", "jean pierre");
		assert_eq!(
			otpauth_uri(b"12345678901234567890"),
			"otpauth://totp/ft_otp:jean%20pierre?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ\
			&issuer=ft_otp&algorithm=SHA1&digits=6&period=30"
		);
	}

	#[test]
	fn uri_escapes_unsafe_bytes() {
		assert_eq!(uri_escape("jean pierre"), "jean%20pierre");
		assert_eq!(uri_escape("a-b_c.d~e"), "a-b_c.d~e");
	}
}

use std::fs;

use crate::errors::{file_error, Error};

const MIN_HEX_LEN: usize = 64; // "at least 64 hexadecimal characters"
const HEX_PER_BYTE: usize = 2; // one byte = two hex digits: "3f" -> 0x3F
const HIGH_NIBBLE_SHIFT: u32 = 4; // the first digit is the high half

/* Gets the hex text of the key for -g:
	-r       OPERAND is the key itself.
	no -r    OPERAND is a file, the key is its content. Leading and trailing
	         whitespace is cut (the '\n' left by "echo"), like
	         "oathtool --totp $(cat key.hex)" does through the shell.
Bytes which are not UTF-8 become '?'-like characters, so they are then
refused by decode_hex_key as "not hexadecimal".
*/
pub fn read_hex_key(operand: &str, raw: bool) -> Result<String, Error> {
	if raw {
		return Ok(operand.to_string());
	}
	let content = fs::read(operand).map_err(|e| file_error("read", operand, &e))?;
	Ok(String::from_utf8_lossy(&content).trim().to_string())
}

/* The value of one hex digit: '0'-'9' -> 0-9, 'a'-'f' / 'A'-'F' -> 10-15.
Only called on digits already checked by decode_hex_key.
*/
fn hex_value(digit: u8) -> u8 {
	match digit {
		b'0'..=b'9' => digit - b'0',
		b'a'..=b'f' => digit - b'a' + 10,
		_ => digit - b'A' + 10,
	}
}

/* Checks HEX, then turns it into the bytes HMAC needs (64 chars -> 32
bytes). Checks, in this order (the first failure is reported):
	1) only hexadecimal characters
	2) at least MIN_HEX_LEN of them
	3) an even number: an odd one would leave half a byte. It is refused,
	   never padded: padding would silently change the key (and the codes).
Each pair of digits makes one byte: "3f" -> 3 << 4 | 15 = 0x3F.
*/
pub fn decode_hex_key(hex: &str) -> Result<Vec<u8>, Error> {
	if !hex.bytes().all(|c| c.is_ascii_hexdigit()) {
		return Err(Error::Fatal(
			"key must contain only hexadecimal characters".to_string(),
		));
	}
	if hex.len() < MIN_HEX_LEN {
		return Err(Error::Fatal(format!(
			"key must be at least {} hexadecimal characters",
			MIN_HEX_LEN
		)));
	}
	if hex.len() % HEX_PER_BYTE != 0 {
		return Err(Error::Fatal(
			"key must have an even number of hexadecimal characters".to_string(),
		));
	}
	Ok(hex
		.as_bytes()
		.chunks(HEX_PER_BYTE)
		.map(|pair| hex_value(pair[0]) << HIGH_NIBBLE_SHIFT | hex_value(pair[1]))
		.collect())
}

#[cfg(test)]
mod tests {
	use super::*;

	fn message(result: Result<Vec<u8>, Error>) -> String {
		match result {
			Err(Error::Fatal(message)) | Err(Error::Usage(message)) => message,
			Ok(_) => "ok".to_string(),
		}
	}

	#[test]
	fn decodes_pairs_big_digit_first() {
		let hex = "3f".repeat(32);
		assert_eq!(decode_hex_key(&hex).ok(), Some(vec![0x3f; 32]));
		let hex = "A0".repeat(32);
		assert_eq!(decode_hex_key(&hex).ok(), Some(vec![0xa0; 32]));
	}

	#[test]
	fn checks_in_order_chars_length_parity() {
		// the subject's example: wrong characters AND too short AND odd
		assert!(message(decode_hex_key("NEVER GONNA GIVE YOU UP")).contains("only"));
		assert!(message(decode_hex_key(&"a".repeat(33))).contains("at least"));
		assert!(message(decode_hex_key(&"a".repeat(65))).contains("even"));
		assert_eq!(message(decode_hex_key(&"a".repeat(128))), "ok");
	}
}

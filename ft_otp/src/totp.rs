use std::time::{SystemTime, UNIX_EPOCH};

use hmac::{Hmac, Mac};
use sha1::Sha1;

use crate::errors::Error;

const T0: u64 = 0; // RFC 6238: time the counter starts from (Unix epoch)
pub const TIME_STEP: u64 = 30; // RFC 6238: a new code every 30 seconds
pub const DIGITS: usize = 6; // "must always contain the same format, i.e. 6 digits"
const MODULO: u32 = 1_000_000; // 10^DIGITS: keeps the last 6 digits
const OFFSET_MASK: u8 = 0x0f; // low 4 bits of the last byte: offset 0..15
const SIGN_MASK: u32 = 0x7fff_ffff; // drops the top bit: never "negative"

/*
  HOTP (RFC 4226): HOTP(K, C) = Truncate(HMAC-SHA1(K, C)) mod 10^6
  KEY      the secret, as BYTES (not its hex text).
  COUNTER  sent to HMAC as 8 bytes, big-endian (biggest byte first):
	         counter 1 -> 00 00 00 00 00 00 00 01. to_be_bytes does it,
	         whatever the CPU's own order is (x86 is little-endian).
  Dynamic truncation (RFC 4226, 5.3), on the 20 bytes of HMAC-SHA1:
	1) offset = last byte & 0x0F
	2) the 4 bytes from offset, glued big-endian into one u32
	3) & 0x7FFFFFFF: the top bit is dropped
	4) mod 10^6
  RFC 4226, 5.4: hash ends with 0x5a -> offset 10 -> 50 ef 7f 19
	-> 0x50ef7f19 = 1357872921 -> 872921.
*/
pub fn hotp(key: &[u8], counter: u64) -> u32 {
	let mut mac = Hmac::<Sha1>::new_from_slice(key)
		.expect("HMAC accepts keys of any length");
	mac.update(&counter.to_be_bytes());
	let hash = mac.finalize().into_bytes();

	let offset = (hash[hash.len() - 1] & OFFSET_MASK) as usize;
	let binary = (hash[offset] as u32) << 24
		| (hash[offset + 1] as u32) << 16
		| (hash[offset + 2] as u32) << 8
		| (hash[offset + 3] as u32);
	(binary & SIGN_MASK) % MODULO
}

/* The TOTP counter (RFC 6238): how many TIME_STEP have passed since T0.
Both sides read their clock, so nobody has to store a counter.
*/
fn time_counter(unix_time: u64) -> u64 {
	(unix_time - T0) / TIME_STEP
}

/* The code of KEY for now, as text: always DIGITS digits, the zeros on
the left kept (12345 -> "012345").
Fails only if the clock is set before 1970.
*/
pub fn totp_now(key: &[u8]) -> Result<String, Error> {
	let now = SystemTime::now()
		.duration_since(UNIX_EPOCH)
		.map_err(|_| Error::Fatal("system clock is before 1970".to_string()))?;
	let code = hotp(key, time_counter(now.as_secs()));
	Ok(format!("{:0width$}", code, width = DIGITS))
}

#[cfg(test)]
mod tests {
	use super::*;

	const RFC_KEY: &[u8] = b"12345678901234567890";

	/* RFC 4226, appendix D: counters 0 to 9. */
	#[test]
	fn rfc4226_hotp_vectors() {
		let expected = [
			755224, 287082, 359152, 969429, 338314,
			254676, 287922, 162583, 399871, 520489,
		];
		for (counter, code) in expected.iter().enumerate() {
			assert_eq!(hotp(RFC_KEY, counter as u64), *code);
		}
	}

	/* RFC 6238, appendix B (SHA-1 column). The RFC gives 8 digits: the
	last 6 are ours, since both are the same number mod 10^8 or mod 10^6.
	*/
	#[test]
	fn rfc6238_totp_vectors() {
		let expected = [
			(59, 287082),          // 94287082
			(1111111109, 81804),   // 07081804
			(1111111111, 50471),   // 14050471
			(1234567890, 5924),    // 89005924
			(2000000000, 279037),  // 69279037
			(20000000000, 353130), // 65353130
		];
		for (time, code) in expected {
			assert_eq!(hotp(RFC_KEY, time_counter(time)), code);
		}
	}

	#[test]
	fn code_keeps_leading_zeros() {
		assert_eq!(format!("{:0width$}", 5924, width = DIGITS), "005924");
	}
}

use std::io;

/*
  Every way ft_otp can fail, carrying the message to print.
	Usage   the command line is wrong: message, then the usage lines.
	Fatal   anything else (bad key, unreadable file...): message only.
  Messages have no final period: report adds it, like the subject's
  "./ft_otp: error: key must be 64 hexadecimal characters."
*/
pub enum Error {
	Usage(String),
	Fatal(String),
}

/* Prints "PROGRAM: error: MESSAGE." on stderr. PROGRAM is argv[0], as
typed by the user ("./ft_otp"). The usage lines of a usage error are
printed by main: ft_otp and ft_otp_bonus do not have the same.
*/
pub fn report(program: &str, error: &Error) {
	let (Error::Usage(message) | Error::Fatal(message)) = error;

	eprintln!("{}: error: {}.", program, message);
}

/* The two ways to call ft_otp, on stderr.
[-p | -p=x]: optional, and its value must be glued with '=' (see options.rs).
*/
pub fn print_usage(program: &str) {
	eprintln!(
		"usage: {} -g <file> | -g -r <hex_key>  [-p | -p=<passphrase>]",
		program
	);
	eprintln!(
		"       {} -k <ft_otp.key>             [-p | -p=<passphrase>]",
		program
	);
}

/* Our strerror: io::Error prints "No such file or directory (os error 2)",
the " (os error N)" part is cut so messages look like the C tools'.
*/
pub fn describe_io(error: &io::Error) -> String {
	let text = error.to_string();

	match text.find(" (os error") {
		Some(end) => text[..end].to_string(),
		None => text,
	}
}

/* Shortcut for "cannot <ACTION> <PATH>: <errno text>", the message of
every failed file operation. Returns it as a Fatal error, so it can be
used as: fs::read(path).map_err(|e| file_error("read", path, &e))?
*/
pub fn file_error(action: &str, path: &str, error: &io::Error) -> Error {
	Error::Fatal(format!("cannot {} {}: {}", action, path, describe_io(error)))
}

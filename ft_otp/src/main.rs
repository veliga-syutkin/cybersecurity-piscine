mod errors;
mod key;
mod options;
mod storage;
mod totp;

use std::env;
use std::process;

use errors::Error;
use options::{Mode, Options};

const PROGRAM_NAME: &str = "ft_otp"; // if argv[0] is missing
const EXIT_FAILURE: i32 = 1;

/* -g: hex text (file or -r) -> checked bytes -> encrypted ft_otp.key. */
fn generate(options: &Options) -> Result<(), Error> {
	let hex = key::read_hex_key(&options.operand, options.raw)?;
	let key = key::decode_hex_key(&hex)?;
	storage::save_key(&key, &options.passphrase)?;
	println!("Key was successfully saved in {}.", storage::KEY_FILE);
	Ok(())
}

/* -k: encrypted key file -> key bytes -> the code of now, on stdout. */
fn show(options: &Options) -> Result<(), Error> {
	let key = storage::load_key(&options.operand, &options.passphrase)?;
	println!("{}", totp::totp_now(&key)?);
	Ok(())
}

fn run(args: &[String]) -> Result<(), Error> {
	let options = options::parse_options(args)?;

	match options.mode {
		Mode::Generate => generate(&options),
		Mode::Show => show(&options),
	}
}

/* Any error comes back up to here, is printed once (errors::report, plus
the usage lines for a usage error), and ends ft_otp with EXIT_FAILURE.
Success: exit code 0.
*/
fn main() {
	let args: Vec<String> = env::args().collect();
	let program = args.first().map_or(PROGRAM_NAME, |name| name.as_str());

	if let Err(error) = run(args.get(1..).unwrap_or(&[])) {
		errors::report(program, &error);
		if let Error::Usage(_) = error {
			errors::print_usage(program);
		}
		process::exit(EXIT_FAILURE);
	}
}

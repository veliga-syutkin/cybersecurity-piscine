use crate::errors::Error;

const OPT_GENERATE: &str = "-g";
const OPT_SHOW: &str = "-k";
const OPT_RAW: &str = "-r";
const OPT_PASSPHRASE: &str = "-p";
const OPT_PASSPHRASE_LONG: &str = "--passphrase";
const OPERANDS_EXPECTED: usize = 1; // the file (or raw key) of -g / -k

/* What to do: -g stores a key, -k shows a code. */
#[derive(PartialEq, Clone, Copy)]
pub enum Mode {
	Generate,
	Show,
}

/*
  Where the passphrase comes from:
	Absent      no -p: the key file is protected by /etc/machine-id.
	Prompt      "-p" alone: asked on the terminal, hidden.
	Given(x)    "-p=x" or "--passphrase=x": taken as is (visible in the
	            shell history and in ps: documented in the README).
*/
pub enum Passphrase {
	Absent,
	Prompt,
	Given(String),
}

/*
  Everything the command line asked for (see parse_options):
	mode        -g or -k
	raw         -r: the operand of -g is the hex key itself, not a file
	passphrase  see Passphrase
	operand     the only non-option argument: file, raw key, or key file
*/
pub struct Options {
	pub mode: Mode,
	pub raw: bool,
	pub passphrase: Passphrase,
	pub operand: String,
}

/* Records -g or -k in MODE. Giving the same one twice is harmless,
giving both is a usage error.
*/
fn set_mode(mode: &mut Option<Mode>, wanted: Mode) -> Result<(), Error> {
	match mode {
		Some(current) if *current != wanted => Err(Error::Usage(
			"-g and -k cannot be used together".to_string(),
		)),
		_ => {
			*mode = Some(wanted);
			Ok(())
		}
	}
}

/* "-p=x" or "--passphrase=x" -> Some("x"), anything else -> None.
The value MUST be glued with '=': "-p x" would be ambiguous with the
operand of -g / -k ("-g -p key.hex": passphrase or file?).
*/
pub fn glued_passphrase(arg: &str) -> Option<&str> {
	for option in [OPT_PASSPHRASE, OPT_PASSPHRASE_LONG] {
		if let Some(rest) = arg.strip_prefix(option) {
			if let Some(value) = rest.strip_prefix('=') {
				return Some(value);
			}
		}
	}
	None
}

/* Checks what parse_options collected, once every argument is read:
exactly one of -g / -k, exactly one operand, -r only with -g.
*/
fn check_options(
	mode: Option<Mode>,
	raw: bool,
	operands: Vec<&String>,
) -> Result<(Mode, String), Error> {
	let mode = match mode {
		Some(mode) => mode,
		None => return Err(Error::Usage("-g or -k is required".to_string())),
	};
	if raw && mode == Mode::Show {
		return Err(Error::Usage("-r can only be used with -g".to_string()));
	}
	if operands.len() != OPERANDS_EXPECTED {
		return Err(Error::Usage(format!(
			"expected exactly one argument, got {}",
			operands.len()
		)));
	}
	Ok((mode, operands[0].clone()))
}

/* Reads ARGS (argv without argv[0]) into an Options.
Options can come in any order ("-g -r KEY" = "-r -g KEY" = "-g KEY -r"):
-g, -k, -r and -p are flags, and the only argument which is not an option
is the operand. Anything else starting with '-' is an unknown option.
Returns the Options, or a usage error.
*/
pub fn parse_options(args: &[String]) -> Result<Options, Error> {
	let mut mode = None;
	let mut raw = false;
	let mut passphrase = Passphrase::Absent;
	let mut operands = Vec::new();

	if args.is_empty() {
		return Err(Error::Usage("no option given".to_string()));
	}
	for arg in args {
		match arg.as_str() {
			OPT_GENERATE => set_mode(&mut mode, Mode::Generate)?,
			OPT_SHOW => set_mode(&mut mode, Mode::Show)?,
			OPT_RAW => raw = true,
			OPT_PASSPHRASE | OPT_PASSPHRASE_LONG => passphrase = Passphrase::Prompt,
			_ => {
				if let Some(value) = glued_passphrase(arg) {
					passphrase = Passphrase::Given(value.to_string());
				} else if arg.starts_with('-') {
					return Err(Error::Usage(format!("unknown option '{}'", arg)));
				} else {
					operands.push(arg);
				}
			}
		}
	}
	let (mode, operand) = check_options(mode, raw, operands)?;
	Ok(Options { mode, raw, passphrase, operand })
}

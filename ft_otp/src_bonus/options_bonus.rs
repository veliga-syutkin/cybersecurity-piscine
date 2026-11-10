use crate::errors::Error;
use crate::options::{glued_passphrase, Passphrase};

const OPT_GENERATE: &str = "-g";
const OPT_SHOW: &str = "-k";
const OPT_SEED: &str = "-s";
const OPT_QR: &str = "-q";
const OPT_RAW: &str = "-r";
const OPT_SVG: &str = "--svg";
const OPT_GUI: &str = "--gui";
const OPT_PASSPHRASE: &str = "-p";
const OPT_PASSPHRASE_LONG: &str = "--passphrase";

/*
  What to do. -g and -k are the mandatory part, unchanged:
	Generate  -g <file> | -g -r <key>   stores a key
	Show      -k <ft_otp.key>           shows a code
	Seed      -s                        makes a random key, stores it,
	                                    shows its QR code
	Qr        -q <ft_otp.key>           shows the QR code of a stored key
	Gui       --gui [<ft_otp.key>]      opens the window (see gui.rs)
*/
#[derive(PartialEq, Clone, Copy)]
pub enum Mode {
	Generate,
	Show,
	Seed,
	Qr,
	Gui,
}

/*
  Everything the command line asked for (see parse_options):
	mode        see Mode
	raw         -r: the operand of -g is the hex key itself
	svg         --svg: the QR code is also written in an SVG file
	passphrase  see options.rs (-p, -p=x)
	operand     the file (or raw key) of -g, -k, -q; None for -s;
	            optional for --gui
*/
pub struct Options {
	pub mode: Mode,
	pub raw: bool,
	pub svg: bool,
	pub passphrase: Passphrase,
	pub operand: Option<String>,
}

/* Usage of ft_otp_bonus: the mandatory lines, plus -s, -q and --gui. */
pub fn print_usage(program: &str) {
	let pass = "[-p | -p=<passphrase>]";

	eprintln!("usage: {} -g <file> | -g -r <hex_key>  {}", program, pass);
	eprintln!("       {} -k <ft_otp.key>             {}", program, pass);
	eprintln!("       {} -s [--svg]                  {}", program, pass);
	eprintln!("       {} -q <ft_otp.key> [--svg]     {}", program, pass);
	eprintln!("       {} --gui [<ft_otp.key>]", program);
}

/* Records the mode in MODE. The same one twice is harmless, two different
ones is a usage error.
*/
fn set_mode(mode: &mut Option<Mode>, wanted: Mode) -> Result<(), Error> {
	match mode {
		Some(current) if *current != wanted => Err(Error::Usage(
			"-g, -k, -s, -q and --gui cannot be used together".to_string(),
		)),
		_ => {
			*mode = Some(wanted);
			Ok(())
		}
	}
}

/* --gui: no other option (the passphrase is typed in the window), and
at most one operand, the key file to open first.
*/
fn check_gui(
	other_options: bool,
	mut operands: Vec<&String>,
) -> Result<(Mode, Option<String>), Error> {
	if other_options {
		return Err(Error::Usage("--gui cannot be used with other options".to_string()));
	}
	if operands.len() > 1 {
		return Err(Error::Usage("--gui takes at most one argument".to_string()));
	}
	Ok((Mode::Gui, operands.pop().cloned()))
}

/* Checks what parse_options collected: one mode, -r only with -g,
--svg only with -s / -q, no operand for -s, exactly one for -g, -k, -q.
OTHER_OPTIONS: was -r, --svg or -p given (only for --gui).
*/
fn check_options(
	mode: Option<Mode>,
	raw: bool,
	svg: bool,
	other_options: bool,
	mut operands: Vec<&String>,
) -> Result<(Mode, Option<String>), Error> {
	let usage = |message: &str| Err(Error::Usage(message.to_string()));
	let mode = match mode {
		Some(Mode::Gui) => return check_gui(other_options, operands),
		Some(mode) => mode,
		None => return usage("-g, -k, -s, -q or --gui is required"),
	};
	if raw && mode != Mode::Generate {
		return usage("-r can only be used with -g");
	}
	if svg && mode != Mode::Seed && mode != Mode::Qr {
		return usage("--svg can only be used with -s or -q");
	}
	if mode == Mode::Seed {
		return match operands.is_empty() {
			true => Ok((mode, None)),
			false => usage("-s takes no argument"),
		};
	}
	if operands.len() != 1 {
		return usage(&format!("expected exactly one argument, got {}", operands.len()));
	}
	Ok((mode, operands.pop().cloned()))
}

/* Reads ARGS (argv without argv[0]) into an Options, in any order, the
same way as the mandatory part (see options.rs): every option is a flag,
the only argument which is not an option is the operand.
*/
pub fn parse_options(args: &[String]) -> Result<Options, Error> {
	let mut mode = None;
	let (mut raw, mut svg) = (false, false);
	let mut passphrase = Passphrase::Absent;
	let mut operands = Vec::new();

	if args.is_empty() {
		return Err(Error::Usage("no option given".to_string()));
	}
	for arg in args {
		match arg.as_str() {
			OPT_GENERATE => set_mode(&mut mode, Mode::Generate)?,
			OPT_SHOW => set_mode(&mut mode, Mode::Show)?,
			OPT_SEED => set_mode(&mut mode, Mode::Seed)?,
			OPT_QR => set_mode(&mut mode, Mode::Qr)?,
			OPT_GUI => set_mode(&mut mode, Mode::Gui)?,
			OPT_RAW => raw = true,
			OPT_SVG => svg = true,
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
	let other_options = raw || svg || !matches!(passphrase, Passphrase::Absent);
	let (mode, operand) = check_options(mode, raw, svg, other_options, operands)?;
	Ok(Options { mode, raw, svg, passphrase, operand })
}

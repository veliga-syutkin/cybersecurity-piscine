# ft_otp

A TOTP (Time-based One-Time Password, RFC 6238) generator built on HOTP
(RFC 4226), written in Rust. It stores a hexadecimal master key in an encrypted
file and prints a new 6-digit code every 30 seconds, the same codes as
`oathtool --totp` or Google Authenticator.

## Build

```sh
make        # builds with cargo and copies the binary to ./ft_otp
make test   # RFC 4226 / RFC 6238 test vectors and key checks
make compare  # ft_otp next to oathtool, from ./key.hex
make demo  # on a new random key: the subject's example, oathtool's code
           # next to ours, and the bonus QR code of the key
make bonus  # builds ./ft_otp_bonus (QR code, GUI), ./ft_otp is left as it is
            # (first build: a few minutes, ~1 GB in target/, because of eframe)
make test_bonus # the same tests inside ft_otp_bonus, plus base32 / URI
make fclean # removes the binaries, ft_otp.key, ft_otp_qr.svg, target/
            # and .cargo-home/
```

Requires a Rust toolchain (`cargo`) and network access to crates.io on the
first build.

## Usage

```
./ft_otp -g <file> | -g -r <hex_key>  [-p | -p=<passphrase>]
./ft_otp -k <ft_otp.key>             [-p | -p=<passphrase>]
```

```sh
$ ./ft_otp -g key.hex
Key was successfully saved in ft_otp.key.
$ ./ft_otp -k ft_otp.key
836492
$ oathtool --totp $(cat key.hex)
836492
```

| Option | Meaning |
|---|---|
| `-g <file>` | Reads a hex key (at least 64 characters) from `<file>` and saves it, encrypted, in `ft_otp.key`. |
| `-g -r <hex_key>` | Same, but the key is given directly on the command line. |
| `-k <file>` | Decrypts `<file>` and prints the current 6-digit code. |
| `-p` | Protects the key file with a passphrase, asked with hidden input. |
| `-p=<x>`, `--passphrase=<x>` | Same, passphrase given on the command line. |

Options can be given in any order.

### Bonus: `ft_otp_bonus`

```
./ft_otp_bonus -g <file> | -g -r <hex_key>  [-p | -p=<passphrase>]
./ft_otp_bonus -k <ft_otp.key>             [-p | -p=<passphrase>]
./ft_otp_bonus -s [--svg]                  [-p | -p=<passphrase>]
./ft_otp_bonus -q <ft_otp.key> [--svg]     [-p | -p=<passphrase>]
./ft_otp_bonus --gui [<ft_otp.key>]
```

| Option | Meaning |
|---|---|
| `-g`, `-k`, `-r`, `-p` | Same as `ft_otp`. |
| `-s` | Generates a random key (32 bytes), saves it encrypted in `ft_otp.key`, and shows its QR code. |
| `-q <file>` | Shows the QR code of an existing key file. |
| `--svg` | With `-s` / `-q`: also writes the QR code in `ft_otp_qr.svg`. |
| `--gui [<file>]` | Opens a window on `<file>` (default `ft_otp.key`): the current code, the seconds left, Copy and Show QR code buttons. |

Scan the QR code with Google Authenticator (or any TOTP app): the phone,
`./ft_otp -k ft_otp.key` and `oathtool` then show the same code.

```sh
$ ./ft_otp -g key.hex          # the evaluator's key
$ ./ft_otp_bonus -q ft_otp.key # scan it with a phone
```

## Principles

### The idea: a shared secret and a moving value

A static password works forever once it leaks. A one-time password (OTP)
changes all the time: the client (here `ft_otp`, or an authenticator app)
and the server share a **secret key `K`**, and both compute
`code = f(K, moving value)` on their own side. If the codes match, the user
proves they hold `K` without ever sending it. An intercepted code is useless
once the moving value has changed.

`f` must be impossible to predict without `K`, and old codes must not reveal
`K`. Both properties come from **HMAC**.

### HMAC: a hash with a key

A plain hash (SHA-1) has no key: anyone can compute `SHA1(counter)`. HMAC
(RFC 2104) mixes a key into it:

```
HMAC(K, m) = H( (K ⊕ opad) ‖ H( (K ⊕ ipad) ‖ m ) )
```

Without `K` its output cannot be computed or predicted, and changing one bit
of `m` changes the whole result. With SHA-1 the output is always 20 bytes.

### HOTP (RFC 4226): counter-based

```
HOTP(K, C) = Truncate( HMAC-SHA1(K, C) ) mod 10^6
```

- **`K`** is the key's *bytes*: 64 hex characters are 32 bytes (`"3f"` is the
  byte `0x3F`, not the characters `'3'` and `'f'`).
- **`C`** is a counter, encoded on 8 bytes, **big-endian** (most significant
  byte first): counter 1 is `00 00 00 00 00 00 00 01`.
- **Dynamic truncation** turns 20 bytes into one number:
  1. `offset` = low 4 bits of the **last** byte (`& 0x0F`), so 0 to 15;
  2. the 4 bytes starting at `offset`, read as a big-endian integer;
  3. the top bit is cleared (`& 0x7FFFFFFF`), so the number is never read as
     negative;
  4. `mod 10^6`, then left-padded with zeros to 6 digits (`012345`).

  Example from RFC 4226 §5.4:
  ```
  HMAC = 1f 86 98 69 0e 02 ca 16 61 85 50 ef 7f 19 da 8e 94 5b 55 5a
  last byte 0x5a -> offset 0xa = 10
  bytes 10..13 = 50 ef 7f 19 -> 0x50ef7f19 = 1357872921
  mod 10^6 -> 872921
  ```

The weak point of HOTP is the counter: client and server must keep it in
sync, and it drifts each time a code is generated but not used.

### TOTP (RFC 6238): the clock is the counter

TOTP is HOTP with a counter both sides already share, the time:

```
C = floor( (unix_time - T0) / X )      T0 = 0, X = 30 seconds
TOTP(K) = HOTP(K, C)
```

Nothing has to be stored or synchronised except the clocks. The counter
changes every 30 seconds, so does the code. These are the defaults of
`oathtool --totp` and of Google Authenticator (HMAC-SHA1, 6 digits, 30 s),
which is why `ft_otp` gives the same codes.

### Where the security lies

Guessing one of 10^6 codes within 30 seconds is hopeless if the server
limits attempts. The real target is `K`: whoever holds it can compute every
future code. This is why the subject requires `ft_otp.key` to be encrypted
(see *Design choices*).

## How it works in ft_otp

1. **Counter** — `C = floor(unix_time / 30)` (RFC 6238, `T0 = 0`, `X = 30`).
2. **HMAC-SHA1** — `HMAC(K, C)`, where `K` is the key's *bytes* (64 hex
   characters → 32 bytes) and `C` is encoded on 8 bytes, big-endian.
3. **Dynamic truncation** (RFC 4226 §5.3) — `offset = last byte & 0x0F`, the
   4 bytes from `offset` read as a big-endian integer, top bit cleared.
4. **Code** — `mod 10^6`, left-padded with zeros to 6 digits.

Sources: `src/totp.rs` (steps 1-4), `src/key.rs` (hex validation and
decoding), `src/storage.rs` (encrypted key file), `src/options.rs` (command
line), `src/errors.rs` (messages), `src/main.rs` (wiring).

## How the bonus works

### One project, two binaries

`make` builds `ft_otp` from `src/`; `make bonus` builds `ft_otp_bonus` from
`src_bonus/`. The bonus does not copy the mandatory code: its `main.rs`
includes the files of `src/` as its own modules,

```rust
#[path = "../src/totp.rs"]
mod totp;
```

so both binaries compute codes and handle key files with the very same
code. The bonus crates (`qrcode`, `eframe`) are declared `optional` in
`Cargo.toml` and enabled only by the `bonus` feature, which `make bonus`
passes (`--features bonus`): `make` never downloads nor compiles them.

### Seed generation (`-s`)

1. 32 random bytes are read from the kernel (`getrandom`, the
   `getrandom(2)` system call): 64 hex characters, the subject's minimum.
2. They go through `storage::save_key`, exactly like a key given to `-g`:
   encrypted in `ft_otp.key`, with machine-id or a passphrase (`-p`).
3. The QR code of the new key is shown.

The new key only exists in memory and, encrypted, in `ft_otp.key`: it is
never written in clear (except in the SVG, and only with `--svg`).

### What the QR code contains

An authenticator app does not read hex: it reads an `otpauth://` URI
(Google Authenticator's "Key Uri Format"):

```
otpauth://totp/ft_otp:<user>?secret=<base32 key>&issuer=ft_otp&algorithm=SHA1&digits=6&period=30
```

- `totp` and `period=30`: the counter is the time, one step every 30 s;
- `algorithm=SHA1` and `digits=6`: HMAC-SHA1, 6-digit codes;
- `ft_otp:<user>` and `issuer`: the name shown in the app (`$USER`,
  percent-encoded: a space becomes `%20`);
- `secret`: the key, in **base32**.

`digits` and `period` are taken from the constants of `src/totp.rs`, so the
phone is told exactly the settings `ft_otp` uses, and computes the same codes.

### Base32, by hand (`src_bonus/qr.rs`)

Base32 (RFC 4648) writes bytes with 32 symbols, `A`-`Z` then `2`-`7`: each
symbol carries **5 bits** (2^5 = 32), where a hex digit carries 4. Bytes come
in 8 bits at a time and leave 5 bits at a time, from the left:

```
"f"  = 0x66 = 0110 0110
regrouped by 5:  01100 | 110 + 00 (padding with zeros)
                  = 12 |  24
                  =  M |   Y            -> "MY"
```

The code keeps a small bit buffer: push a byte (8 bits in), take 5-bit
groups out while there are at least 5, and at the end pad the last bits
with zeros on the right. The `=` padding of RFC 4648 is left out, as the
`otpauth` format expects. The tests check the RFC 4648 vectors (`"foobar"`
→ `MZXW6YTBOI`) and the full URI of the RFC 4226 test key.

### Drawing the QR code

The `qrcode` crate turns the URI into a grid of black and white squares
("modules"); `ft_otp` only draws that grid.

- **Terminal:** one character is twice as high as wide, so each character
  draws two modules, one above the other, with `▀` (upper half block): its
  text color paints the top module, its background the bottom one. Colors
  are forced with ANSI codes (black on white), so the code scans on dark
  and light terminals alike. A 4-module white margin (the "quiet zone"
  required by ISO 18004) is added around it, or scanners fail.
- **SVG (`--svg`):** rendered by `qrcode` itself into `ft_otp_qr.svg`,
  written with permissions `0600` since it holds the key in clear.
- **Window:** painted as white and black rectangles by egui.

### The graphical interface (`--gui`)

`eframe` opens the window and calls `App::ui` at each frame; egui is an
**immediate mode** GUI: `ui` redraws the whole window from the app's
fields every time, and a button is just `if ui.button("Copy").clicked()`.
No widget keeps its own state, so nothing can get out of sync.

- **Loading a key file** (Load button or Enter), the GUI version of `-k`:
  1. `storage::needs_passphrase` reads the file's mode byte;
  2. if a passphrase is needed and none is typed, the hidden field is shown
     and the GUI waits;
  3. `storage::load_key` decrypts it with machine-id or the typed passphrase
     (passed as `-p=x` would be: the terminal prompt is never used), then
     the passphrase is cleared.
- **The code** is recomputed with `totp::totp_now` at every frame, and the
  seconds left are `30 - (unix_time mod 30)`. The window asks for a new
  frame every 250 ms (`request_repaint_after`), so the code and the bar
  change by themselves, without any timer or thread.
- **Copy** puts the code in the clipboard; **Show QR code** builds the QR
  code of the loaded key and paints it below.

Sources: `src_bonus/main.rs` (wiring), `src_bonus/options_bonus.rs`
(command line), `src_bonus/qr.rs` (base32, URI, terminal and SVG drawing),
`src_bonus/gui.rs` (window).

## Design choices

**Language and build**
- **Rust.** On the school machines the toolchain is system-wide and
  `CARGO_HOME=/opt/rust` is read-only for students, so cargo cannot write its
  crate cache. The Makefile forces `CARGO_HOME` to a project-local
  `.cargo-home/` (git-ignored, removed by `fclean`): `make` works on any
  session and leaves nothing in the evaluator's home.
- **`Cargo.lock` is committed**, following the Rust convention for binaries:
  the evaluator builds the exact same crate versions (`cargo build --locked`).
- `make fclean` also removes `ft_otp.key`, so the project goes back to its
  cloned state.

**Libraries** — the subject forbids TOTP libraries but allows helpers.
- Crypto primitives come from RustCrypto: `hmac` + `sha1` (HMAC-SHA1),
  `aes-gcm`, `argon2`. Also `getrandom` (salt and nonce) and `rpassword`
  (hidden input). The clock is `std::time::SystemTime`.
- **Written by hand:** the whole TOTP/HOTP logic (counter, big-endian
  encoding, dynamic truncation, modulo, zero padding), hex decoding, and
  argument parsing.

**Command line**
- `-g <file>` reads the key from a file, exactly like the subject's example.
  `-g -r <key>` takes it directly, through an explicit flag (no guessing
  whether an argument is a file or a key). File mode is the recommended one:
  a key or passphrase given as an argument stays in the shell history and is
  visible in `ps`.
- Options are accepted in any order; there must be exactly one non-option
  argument.
- The value of `-p` must be glued with `=` (`-p=x`); a bare `-p` always
  prompts. This keeps `-g -p key.hex` unambiguous.
- `-g` and `-k` together, an unknown option, or no argument: an error, the
  usage, exit code 1.

**Key validation** (`-g`)
- In file mode, leading and trailing whitespace (the newline left by `echo`)
  is stripped, consistent with `oathtool --totp $(cat key.hex)`.
- Checked in this order, the first failure is reported:
  1. only hexadecimal characters — `key must contain only hexadecimal characters`
  2. at least 64 characters — `key must be at least 64 hexadecimal characters`
     (the subject says "at least 64"; longer keys are valid HMAC keys)
  3. an even number of characters — `key must have an even number of hexadecimal characters`

  An odd length is refused, never padded: padding would silently change the
  key and produce wrong codes. `oathtool` refuses it too.

**Encrypted key file**
- **Cipher:** AES-256-GCM. It is authenticated: a wrong secret or a modified
  file is detected and reported, instead of producing a wrong key.
- **Encryption key:** derived with Argon2id (crate defaults: 19 MiB, 2 passes)
  and a random salt, from one of two secrets:
  - **default:** `/etc/machine-id`. Nothing to type, so evaluation is
    smooth. The file is useless on another machine, but anyone on the same
    machine can decrypt it: this is a known limitation.
  - **`-p`:** a passphrase, *instead of* machine-id (not combined with it,
    to keep it simple to use and the file portable).
- **File format** (binary): `mode (1 B) | salt (16 B) | nonce (12 B) |
  encrypted key + tag (16 B)`. The mode byte tells `-k` which secret to use:
  a passphrase-protected file asks for its passphrase even without `-p`, and
  `-p` is ignored on a machine-id file. The header is passed to AES-GCM as
  associated data, so changing it (e.g. the mode byte) makes decryption fail.
  The key's bytes are encrypted, not its hex text.
- `ft_otp.key` is created with permissions `0600`, and overwritten by a new
  `-g`, as in the subject's example.
- An empty passphrase is refused.
- With `-g -p`, the passphrase is asked once, without confirmation: a typo
  only means running `-g` again.

**Errors**
- Format: `<argv[0]>: error: <message>.` on stderr, like the subject's
  example. Exit code `0` on success, `1` on any error.

**Bonus: QR code with seed generation**
- **A separate binary, `ft_otp_bonus`**, built by `make bonus` from
  `src_bonus/`. It reuses the modules of `src/` through `#[path]` instead of
  copying them. Its crates are an optional cargo feature (`bonus`): `make`
  never builds them, so a problem with the bonus cannot break `./ft_otp`.
  To be shared, a few items of `src/` were made public or slightly reshaped
  (`write_private_file`, `glued_passphrase`, `DIGITS` / `TIME_STEP`; the usage
  lines are printed by each `main`); the behavior of `ft_otp` is unchanged.
- **`-s`** generates 32 random bytes (64 hex characters, the subject's
  minimum) from the kernel (`getrandom`), stores them encrypted in
  `ft_otp.key` exactly like `-g` (`-p` works too), then shows the QR code.
  The new key never touches the disk in clear.
- **`-q <file>`** shows the QR code of a key already stored, e.g. the
  evaluator's key saved with `ft_otp -g`.
- **QR content:** an `otpauth://` URI, the format read by Google
  Authenticator:
  `otpauth://totp/ft_otp:<user>?secret=<base32>&issuer=ft_otp&algorithm=SHA1&digits=6&period=30`.
  The account name is `$USER` (percent-encoded), so keys of different people
  stay apart in the app. The settings come from the same constants as the
  code generation, so the phone computes exactly our codes.
- **Base32 is written by hand** (RFC 4648 alphabet, no `=` padding, as the
  `otpauth` format expects); tested with the RFC 4648 vectors.
- **Outputs:** the terminal always, drawn with half blocks in forced black
  on white (ANSI colors), so it scans on dark and light terminals. The SVG
  file only with `--svg`, to avoid leaving the key in a file by accident.
- **The QR code shows the key in clear.** `ft_otp_qr.svg` is written with
  permissions `0600`, like `ft_otp.key`, and removed by `make fclean`.
- If stdout is closed early (`| head`), the QR drawing fails with an error
  message instead of a crash.

**Bonus: graphical interface**
- **`--gui [<file>]`, in `ft_otp_bonus`**, with `egui` / `eframe`: an
  "immediate mode" GUI, the whole window is redrawn from the app's state at
  each frame, so there is no widget state to keep in sync. Checked on the
  school machines first: rustc 1.97.1 (eframe 0.35 needs 1.92), X11, a test
  window builds and opens.
- `--gui` takes at most one argument, the key file to open first (default
  `ft_otp.key`), and no other option: the passphrase is typed in the window.
- **The window:** a "Key file" text field with a Load button (no native
  file dialog: it would depend on desktop services that may be missing on
  the school machines), a hidden passphrase field shown only when the
  file's mode byte asks for one, the 6-digit code in large type, a bar with
  the seconds left before the next code, a Copy button and a Show/Hide QR
  code button.
- A key file which needs no passphrase is loaded as soon as the window
  opens. The typed passphrase is forgotten once the file is decrypted.
- The code is recomputed at each frame and the window asks for a new frame
  every 250 ms, so the code and the countdown change by themselves.
- The QR code is painted as rectangles by egui (no image crate), with the
  same `otpauth://` content as in the terminal.
- To know whether to show the passphrase field before decrypting, `src/`
  gained `storage::needs_passphrase` (reads the mode byte; unused by
  `ft_otp`).

## AI usage

This project was built with the help of an AI assistant (Claude, by Anthropic,
used through Claude Code). How it was used, and who did what:

**Done by the AI**

- Explained the theory: HMAC, HOTP, TOTP, dynamic truncation, endianness,
  authenticated encryption and key derivation.
- Diagnosed the read-only `CARGO_HOME` found on the school machines.
- Wrote code **on request**, applying the decisions listed in
  [Design choices](#design-choices) and the author's C coding style (small
  commented functions, named constants, tabs): `Makefile`, `Cargo.toml`,
  all of `src/` (`main.rs`, `options.rs`, `errors.rs`, `key.rs`, `storage.rs`,
  `totp.rs`) and all of `src_bonus/` (`main.rs`, `options_bonus.rs`,
  `qr.rs` with base32, `gui.rs`).
- Wrote the scripts checking that the school machines can build Rust and
  open an `eframe` window.
- Wrote the unit tests (RFC 4226 and RFC 6238 test vectors, key validation
  order, RFC 4648 base32 vectors, `otpauth://` URI format), checked the codes against an independent implementation, and ran
  every error case by hand.
- Wrote this README, and explained each module after writing it.

**Done by the author**

- Every design and behavior decision: all the entries of
  [Design choices](#design-choices) were chosen by the author, from options
  presented with their trade-offs.
- Choice of Rust, checks on the school machines, review and validation of the
  code and documents.
- Tests on a school machine: `make demo` runs, and `oathtool --totp` gives
  the same code as `ft_otp`.

**How it is kept honest**

- Every technical statement about HOTP / TOTP points to RFC 4226 or RFC 6238,
  and the RFC test vectors are part of `make test`.
- Every behavior of the code maps to an entry of *Design choices*.
- The author must be able to explain any line of the project; this section is
  updated whenever the split of the work changes.

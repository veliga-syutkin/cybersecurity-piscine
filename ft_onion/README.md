# ft_onion

A static web page and an SSH access, published as a Tor hidden service
(onion service v3). The page is served by nginx on port 80, SSH listens on
port 4242, and both are reachable **only** through a `xxx.onion` address: no
port is opened on the host, no firewall rule is set.

## Where the required files are

| Required file | Location |
|---------------|----------|
| `index.html`  | [`server/index.html`](server/index.html) |
| `nginx.conf`  | [`server/nginx.conf`](server/nginx.conf) |
| `sshd_config` | [`server/sshd_config`](server/sshd_config) |
| `torrc`       | [`server/torrc`](server/torrc) |

```
ft_onion/
├── Makefile
├── README.md
├── server/          the hidden service (one container)
│   ├── Dockerfile
│   ├── csp_check.sh build-time check of the page's script hash (bonus)
│   ├── entrypoint.sh
│   ├── index.html
│   ├── nginx.conf
│   ├── sshd_config
│   └── torrc
└── client/          a Tor client to test it (second container)
    ├── Dockerfile
    ├── ssh_config
    └── torrc
```

## Requirements

Docker, usable without `sudo` (rootless Docker, as on the school machines,
works), network access to Docker Hub, the Debian mirrors and the Tor network,
and `ssh-keygen` on the host.

## Usage

```sh
make            # builds both images, starts both containers, prints the address
                # (a container already running the current image is kept)
make address    # prints the .onion address again
make curl       # fetches the page through Tor (headers + HTML)
make ssh        # opens an SSH session on port 4242 through Tor
make logs       # follows the server logs (nginx, sshd, tor)
make down       # stops and removes the containers (the address is kept)
make clean      # down + removes the images
make fclean     # clean + deletes the onion keys (new address next time)
                # and the SSH key pair
make re         # fclean + all
```

`make curl` and `make ssh` first wait for both tor instances to be connected
to the Tor network. Even then, the first access after a (re)start can take
a few minutes (about 2 in our tests): the descriptor published by the
previous run still points to introduction points that no longer exist, and
the service has to publish a new one first. Later accesses take a second or
two. This is why `make` does not restart a container that already runs the
current build of its image: only a real change restarts the server.

The page can also be opened in **Tor Browser** with the address printed by
`make`.

## How it works

### Tor in short

Tor hides **who talks to whom**. The client picks relays from a public list
signed by the directory authorities and builds a circuit through three of
them (guard, middle, exit). The message is encrypted once per relay, and each
relay removes one layer: the guard knows the client but not the destination,
the exit knows the destination but not the client.

### Hidden services

A hidden service also hides the **server**: there is no exit relay, the
traffic never leaves the Tor network.

- **The address is the key.** tor generates an ed25519 key pair, and the v3
  address is `base32(public key ‖ checksum ‖ version) + ".onion"` (56
  characters). Whoever reaches this address talks to the holder of the private
  key: no certificate authority, no DNS.
- **Publication.** The service picks a few *introduction points*, keeps a
  circuit open to each, and publishes a signed and encrypted *descriptor*
  listing them on the Tor network.
- **Connection.** The client derives the descriptor's location from the
  address, checks its signature with the key contained in the address, picks
  a *rendezvous point*, and asks the service (through an introduction point)
  to meet it there. Both sides build a circuit to the rendezvous point, and a
  key exchange authenticated by the service's key gives end-to-end
  encryption. Neither side learns the other's IP address.

So the only thing to trust is how you obtained the address. The connection
itself cannot be hijacked without the service's private key.

### Why no port has to be opened

tor only makes **outgoing** connections, to relays. Visitors arrive through
the circuits tor itself opened, and tor hands their streams to local ports
(`HiddenServicePort` in `torrc`):

```
.onion:80    ->  127.0.0.1:80    nginx
.onion:4242  ->  127.0.0.1:4242  sshd
```

nginx and sshd listen on `127.0.0.1` only, inside the container. The
container publishes no port (`docker run` without `-p`, no `EXPOSE`), so the
page and SSH cannot be reached from the host or the Docker network, only
through Tor.

### The server container

`entrypoint.sh` creates `/run/sshd` (normally done by systemd, absent in a
container), checks the three configurations (`nginx -t`, `sshd -t`,
`tor --verify-config`), starts sshd and tor, prints the address, starts
nginx, then watches the three of them: if any one stops, the other two are
stopped and the container exits with status 1 (`make` then starts a new one).
`docker stop` stops them cleanly (status 0). Errors go to `docker logs`.

### The test client

A second container runs a plain Tor client (SOCKS proxy on `127.0.0.1:9050`).
`curl --socks5-hostname` and `ssh` (through `nc -X 5` as `ProxyCommand`) give
the `.onion` name to tor, which resolves it on the Tor network. The client
therefore goes through the real Tor network, like any visitor; it does not
use the Docker network to reach the server.

## How a `.onion` address proves who you're talking to

**The core idea: mixing is easy, unmixing is impossible.**
Imagine a starting color (yellow) that everyone knows. The owner of a service
has a secret: a number of mixing steps, for example 7,000,000. Applying that
many steps to the yellow is easy and gives a final color. But looking at the
final color, there is no way to work out how many steps were applied.

**A `.onion` address is that final color.**
The owner publishes it, everyone can see it, and nobody can recover the secret
number from it. Another useful property: steps add up. 3 steps followed by
4 steps give the same color as 7 steps at once. This is what makes the check
below possible.

**Proof of ownership is a small challenge.**
First, the owner picks a fresh random number of steps, kept secret, and shows
you the color it gives. Then you send a random number as a challenge. The
owner answers with a value computed from the secret, the random steps and
your number. You then check that answer using only public things: the
starting color, the address, the color shown first and your own challenge.
Only someone who knows the secret number can produce an answer that passes.
The random steps hide the secret inside the answer, so checking it never
reveals the secret (without them, the answer would give the secret away: see
the RGB example below).

**The address itself is not secret, and that's fine.**
It is only used to *check* the answer, never to *produce* it. Knowing the
final color doesn't help anyone answer a fresh random challenge.

> This is an analogy. In reality the "mixing steps" are operations on an
> elliptic curve (ed25519), the address is the public key (plus a checksum
> and version byte), and the challenge-response is a Schnorr-style signature.
> The idea is the same: easy in one direction, impossible in the other.

The color-mixing analogy is shown visually in Veritasium's video
[*The Internet Was Weeks Away From Disaster And No One Knew*](https://youtu.be/aoag03mSuXQ?t=771)
(from 12:51).

### The same idea with real RGB numbers (toy example)

Colors are `(R, G, B)` triples. One **mixing step** multiplies the current
color by the starting color, channel by channel, **modulo 251** (the largest
prime below 256: with a prime, every step can be undone by whoever knows the
count, and channel values stay valid, from 1 to 250).

| Name | Meaning | RGB | Hex |
|------|---------|-----|-----|
| `Y` | starting color, public (a yellow) | `(239, 199, 30)` | `#EFC71E` |
| `x` | **secret** number of steps | `123` | |
| `X` | `Y` after 123 steps: **the "address"**, public | `(61, 229, 70)` | `#3DE546` |

**Steps add up.** 50 steps give `(219, 20, 219)`, 73 steps give
`(53, 24, 139)`. Mixing these two results, channel by channel
(`219 × 53 mod 251 = 61`, …), gives `(61, 229, 70)`: the same color as
50 + 73 = 123 steps.

**The challenge, in three messages:**

| # | Who | Sends | Value |
|---|-----|-------|-------|
| 1 | owner | `R` = `Y` after `k = 58` **random, fresh** steps (kept secret) | `(112, 155, 140)` `#709B8C` |
| 2 | you | a random challenge `c` | `9` |
| 3 | owner | `s = k + c × x mod 250` (250 = number of distinct colors in the cycle) | `58 + 9 × 123 mod 250 = 165` |

**Your check, with public values only:**
- `Y` after `s = 165` steps → `(235, 8, 10)`
- `R` mixed with `X` after 9 steps → `(235, 8, 10)`

Both sides match, so the answer was computed by someone who knows `x`.
An impostor who tries `x = 124` answers `s = 174`, and `Y` after 174 steps
is `(81, 39, 68)`: the check fails.

**Why message 1 is needed.** Without the random `k`, the answer would be
`s = c × x mod 250 = 107`, and anyone could divide it by the challenge:
`107 × 9⁻¹ mod 250 = 123`, the secret. The fresh random steps hide the
secret inside the answer.

**Why it is only a toy.** With 251 possible values per channel, trying every
step count from 0 to 249 finds `x = 123` instantly. In ed25519 the "count" is
a number of about 2²⁵² possibilities, and no known method finds it from the
public key. The mixing is *point addition on an elliptic curve* instead of
multiplication modulo 251, but the structure is the same: public start `Y`
(the curve's base point), secret count `x` (the private key), public result
`X` (the public key, inside the `.onion` address), and the three-message
check (a Schnorr signature, the basis of ed25519; in a signature, nobody
sends the challenge: it is a hash of `R` and of the signed message, so
anyone can check it later, without any back-and-forth).

### What this does *not* protect against

The protocol guarantees you are talking to the owner of the address you
typed. It cannot tell you whether that address is the one you *meant* to
visit. A lookalike address (generated by brute force to share the same first
characters) is a perfectly valid address belonging to someone else. Always get
`.onion` addresses from a trusted source: the organization's official HTTPS
site (Onion-Location header), a PGP-signed message, or a bookmark you made
after verifying it once.

## Bonus

### SSH fortification

Everything is in [`server/sshd_config`](server/sshd_config), plus one line
of the Dockerfile and two lines of [`server/torrc`](server/torrc). On top of
the mandatory settings (key only, no root, no password):

| Setting | Why |
|---------|-----|
| `AllowUsers vsyutkin` | only this account can log in, even if another one appears |
| `DisableForwarding yes` (+ explicit `AllowTcpForwarding no`, `AllowAgentForwarding no`, `AllowStreamLocalForwarding no`, `X11Forwarding no`, `PermitTunnel no`) | a logged-in user cannot use the container as a relay (`ssh -L`, `-R`, `-D`, `-W`) |
| `LoginGraceTime 20`, `MaxStartups 3:50:10` | idle or flooding unauthenticated connections are dropped |
| `PerSourcePenalties no` | on by default since OpenSSH 9.8; behind Tor every client is `127.0.0.1`, so one attacker would get everybody blocked |
| ed25519 host key only (RSA and ECDSA keys deleted in the Dockerfile), `HostKeyAlgorithms` / `PubkeyAcceptedAlgorithms ssh-ed25519` | one modern key type, nothing to downgrade to |
| `KexAlgorithms mlkem768x25519-sha256,sntrup761x25519-sha512` | post-quantum hybrid key exchanges only |
| `Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com`, `MACs …-etm@openssh.com` | authenticated encryption only, encrypt-then-MAC |
| `DebianBanner no` | the banner no longer shows the Debian package version |
| `HiddenServiceEnableIntroDoSDefense 1`, `HiddenServicePoWDefensesEnabled 1` (torrc) | flood protection done by Tor (rate limit at the introduction points, proof-of-work puzzles under load), since per-IP tools cannot work here |

Tested through Tor: normal login works and negotiates
`mlkem768x25519-sha256` / `ssh-ed25519` / `chacha20-poly1305`; a weak key
exchange, a weak cipher, or an RSA / ECDSA host key requested by the client
are refused ("no matching … found"); `-L` (connection reset), `-R` ("remote
port forwarding failed") and `-W` ("stdio forwarding failed") are refused and
logged; root is refused ("not listed in AllowUsers"); an idle connection is
closed after 20 s ("Timeout before authentication"); after 6 failed logins,
the real user can still log in.

To check by hand from the client container (`make ssh` first, to copy the
key in):

```sh
docker exec ft_onion_client ssh -p 4242 -o Ciphers=aes128-ctr vsyutkin@<address>   # refused
docker exec ft_onion_client ssh -p 4242 -W 127.0.0.1:80 vsyutkin@<address>       # refused
docker exec ft_onion_client ssh -v -p 4242 vsyutkin@<address> true 2>&1 | grep 'kex:'
```

### Interactive application

The page now includes an interactive version of the
[RGB toy example](#the-same-idea-with-real-rgb-numbers-toy-example): choose
the secret number of steps, run a challenge, and watch the check succeed.
Two checkboxes show the failure cases: an impostor who guesses the secret
(the colors differ), and a run without step 1 (the check passes, but the
page computes the secret back from the answer).

- **Still a single static `index.html`**, served by nginx: the script runs in
  the browser, there is no server-side code, no other server, no framework.
  The colors are drawn on `<canvas>` elements, so the page still has no CSS.
- **Strict content security policy kept**: no `'unsafe-inline'`. The policy
  allows this one inline script by its sha256 hash, and
  [`server/csp_check.sh`](server/csp_check.sh) fails the image build if the
  script and the hash in `nginx.conf` no longer match (otherwise the browser
  would silently block the script).
- **Randomness** comes from `crypto.getRandomValues`, the browser's
  cryptographic generator.
- **Tor Browser**: at the "Safest" security level JavaScript is disabled, and
  a `<noscript>` message asks to switch to "Safer" or "Standard".

## Design choices

**Environment**
- **Docker**, one Debian container for the server (nginx + sshd + tor),
  driven by a Makefile: the evaluator rebuilds the same thing with one
  command. A VM would be heavier, and could not be rebuilt from the
  repository.
- **`debian:trixie-slim`**: tor, nginx and openssh come from the official
  Debian repositories, with their standard paths.
- **A plain `entrypoint.sh`** to start the three services, no supervisord.
- **If one service stops, the container stops** (status 1), instead of
  staying "Up" while, for example, tor is dead and the site unreachable.
  No automatic restart: each restart costs a couple of minutes of
  unavailability, and a broken configuration would restart in a loop.
- `make` does not restart a container that already runs the current build of
  its image.
- **Rootless Docker compatible** (the school machines use it): no host port
  is published and no host directory is mounted in a container, so nothing
  owned by root (or by a sub-UID) is ever created in the project folder.
  Images and volumes live in Docker's own storage and are removed through
  `make clean` / `make fclean`, never with `rm`.

**Network**
- **nginx and sshd listen on `127.0.0.1` only**: tor, in the same container,
  is the only way in.

**Onion keys**
- **Stored in a named Docker volume** mounted on `HiddenServiceDir`: the
  address survives `make down` / `make up` and image rebuilds, and the
  private key never enters the repository. `make fclean` deletes the volume,
  so the next start gets a new address.

**SSH**
- **Key-only login for a non-root user** (`vsyutkin`). `make` creates an
  ed25519 key pair in `ssh/` on the host (owned by the user, git-ignored);
  the public key is given to the image at build time, the private key is sent
  into the client container through stdin by `make ssh`, never stored in an
  image.
- The user's password field is `*` (no password can match), not `!`
  (locked): with `UsePAM no`, sshd refuses any login, keys included, on a
  locked account.
- **`*` and `UsePAM no` is exactly the setup targeted by "SSHole"**
  (CVE-2026-123158, November 2026): on OpenSSH builds linked with **musl**
  (Alpine) and without PAM, a password longer than 256 bytes makes musl's
  `crypt()` fail and return `"*"`, which matches the `*` stored in
  `/etc/shadow`, so any 257 to 1024 character password opens the account.
  This server is not affected, for two independent reasons, both checked in
  the container:
  1. `PasswordAuthentication no` and `KbdInteractiveAuthentication no`
     (`sshd -T`): the server only offers `publickey`, so the password code,
     and `crypt()`, never run.
  2. Debian uses glibc with libxcrypt, whose `crypt()` returns `"*0"` on
     failure, a value chosen so that it can never match a stored password:
     a 300 character password against `*` gives `"*0"`, and the comparison
     fails.

  Either one is enough on its own (defense in depth). It is also one more
  reason for choosing Debian over Alpine.
- `sshd_config` replaces Debian's file entirely, including its
  `Include sshd_config.d/*.conf` line, so no drop-in file can override it.
- Settings: `PermitRootLogin no`, `PasswordAuthentication no`,
  `KbdInteractiveAuthentication no`, `PubkeyAuthentication yes`,
  `MaxAuthTries 3`, `X11Forwarding no`, `UsePAM no`.
- **No `sftp`, so no `scp`** (it uses the SFTP protocol since OpenSSH 9.0):
  less code exposed. This is not a barrier against a logged-in user, who can
  still copy a file through the shell (`ssh host 'cat > file' < file`).
- **Host keys generated in the image** (at the installation of
  openssh-server). Docker's build cache keeps them across rebuilds; they only
  change with `make clean` / `make re`, which also recreate the client, so no
  "host key changed" warning. And the `.onion` address already authenticates
  the server: the host key is a second check, not the only one.

**nginx**
- `nginx.conf` replaces Debian's file entirely (no `sites-enabled/`).
- **No access log.** The IP is always `127.0.0.1`, but a timestamped list of
  visits could still help a traffic correlation attack if the server were
  seized or compromised. The error log stays on.
- `server_tokens off` (no version in headers and error pages) and security
  headers on every response: a content security policy that forbids
  everything except the page's own script, allowed by its hash (see
  [Interactive application](#interactive-application)),
  `X-Frame-Options DENY`, `X-Content-Type-Options nosniff`,
  `Referrer-Policy no-referrer`, `Permissions-Policy`.

**What is deliberately not used**
- **No fail2ban, no per-IP rate limiting**: behind a hidden service, every
  connection comes from `127.0.0.1` (tor). Banning or throttling "the
  attacker's IP" would block every visitor at once.
- **No HTTPS**: the connection to an onion service is already encrypted end
  to end and authenticated by the address.

**Content**
- `index.html` says *Hello Dark Web!*, a nod to *Hello World!*, with one
  sentence on how the page reaches the visitor. No CSS, and no personal
  information.
- **Bonus: both bonuses are done.** The SSH fortification is cheap and each
  line can be justified; the interactive demo supports the explanation of
  the address during the defense.
- The demo's script stays **inside `index.html`** (allowed by its CSP hash)
  rather than in a separate `app.js`, so the site is still "a single
  index.html file".

**Test client**
- A second small container (tor + curl + ssh) started by `make`: HTTP and
  SSH are tested the same way at home and at school, without root and
  without installing anything on the host.

## AI usage

This project was built with the help of an AI assistant (Claude, by Anthropic,
used through Claude Code). How it was used, and who did what:

**Done by the AI**

- Explained the theory: onion routing, hidden services, v3 addresses, how the
  address protects against man-in-the-middle attacks, and why no port has to
  be opened.
- Wrote the script checking that the school machines can run Docker and reach
  the Tor network (`check_docker.sh`, outside this repository).
- Reviewed another project of the author for reusable elements (SSH
  settings, sshd pitfalls in containers, nginx security headers) and for
  those that do not fit behind Tor (fail2ban, per-IP rate limiting).
- Wrote code **on request**, applying the decisions listed in
  [Design choices](#design-choices): `Makefile`, all of `server/`
  (`Dockerfile`, `entrypoint.sh`, `index.html`, `nginx.conf`, `sshd_config`,
  `torrc`) and all of `client/` (`Dockerfile`, `ssh_config`, `torrc`).
- Bonus, on request: the SSH fortification (`sshd_config`, `torrc`,
  `Dockerfile`), the interactive demo inside `index.html`, and
  `csp_check.sh`.
- Tested the setup: page and SSH through Tor, root and password logins
  refused, no access through the container's IP, no published port, same
  address after a restart; for the bonus, every refusal listed in
  [SSH fortification](#ssh-fortification), and the demo's logic in Node.js
  (1000 runs per case, with a stub of the page); the container stopping when
  tor, sshd or nginx is killed, and cleanly on `docker stop`.
- Looked up the "SSHole" vulnerability (CVE-2026-123158) when the author
  asked about it, and checked in the container why this setup is not
  affected.
- Wrote this README, including the RGB toy example (values computed with a
  short script and checked).
- The section *How a `.onion` address proves who you're talking to* (the
  color-mixing analogy) was written by Claude on claude.ai, in the form the
  author asked for; the author added it to this README. Claude Code then
  corrected its *Proof of ownership* paragraph (the random first step was
  missing).

**Done by the author**

- Every design and behavior decision: all the entries of
  [Design choices](#design-choices) were chosen by the author, from options
  presented with their trade-offs, including the text of the page.
- The color-mixing analogy: the author chose to explain the address this way
  and asked for it in that form, and chose the Veritasium video as a
  reference.
- Checks on a school machine (rootless Docker, Tor reachable), review and
  validation of the code and documents.

**How it is kept honest**

- Every behavior of the setup maps to an entry of *Design choices*.
- The author must be able to explain any line of the project; this section is
  updated whenever the split of the work changes.

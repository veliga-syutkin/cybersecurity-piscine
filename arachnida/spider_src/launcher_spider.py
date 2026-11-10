"""Entry point of spider: turns the command line into a validated configuration.

Usage: ./spider [-rlp] [--delay SECONDS] URL

Exit codes:
    0   success
    1   runtime error (e.g. destination directory cannot be created)
    2   usage error (invalid arguments) — also argparse's own code
    130 interrupted by the user (Ctrl-C)
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from crawler import Crawler, RateLimited

PROG = "spider"
DEFAULT_DEPTH = 5
DEFAULT_PATH = "./data/"
DEFAULT_DELAY = 1
ALLOWED_SCHEMES = ("http", "https")

# "scheme:" at the start of a URL, as long as the colon is not followed by a
# digit — so "site.com:8080" is read as host + port, not as a scheme.
SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):(?!\d)")

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


@dataclass(frozen=True)
class Config:
    """Everything the crawler needs, already validated."""

    url: str          # absolute http(s) URL of the start page
    recursive: bool   # follow links or not
    depth: int        # maximum depth (0 = start page only)
    path: Path        # destination directory (exists, is a directory)
    delay: int        # seconds between two pages (0 = no delay)


def warn(message: str) -> None:
    print(f"{PROG}: warning: {message}", file=sys.stderr)


def error(message: str) -> None:
    print(f"{PROG}: error: {message}", file=sys.stderr)


def non_negative_int(text: str) -> int:
    """argparse type: an integer >= 0 (used by -l and --delay)."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: '{text}'")
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Download the images of a website, optionally recursively.",
    )
    parser.add_argument(
        "-r", dest="recursive", action="store_true",
        help="recursively download the images of the linked pages",
    )
    # default=None so that "-l not given" can be told apart from "-l 5".
    parser.add_argument(
        "-l", dest="depth", metavar="N", type=non_negative_int, default=None,
        help=f"maximum depth of the recursion (default: {DEFAULT_DEPTH}; "
             "0 = start page only)",
    )
    parser.add_argument(
        "-p", dest="path", metavar="PATH", default=DEFAULT_PATH,
        help=f"destination directory (default: {DEFAULT_PATH})",
    )
    parser.add_argument(
        "--delay", metavar="SECONDS", type=non_negative_int,
        default=DEFAULT_DELAY,
        help=f"delay between two pages, in seconds (default: {DEFAULT_DELAY}; "
             "0 = no delay)",
    )
    parser.add_argument("url", metavar="URL", help="URL of the start page")
    return parser


def normalize_start_url(raw: str) -> str:
    """Return an absolute http(s) URL, or raise ValueError.

    - no scheme ("site.com/x")    -> "https://" is added
    - protocol-relative ("//...") -> "https:" is added
    - scheme other than http(s)   -> rejected (e.g. file://, ftp://, mailto:)
    - http                        -> accepted with a warning (unencrypted)
    """
    url = raw.strip()
    if not url:
        raise ValueError("empty URL")

    match = SCHEME_RE.match(url)
    if match is None:
        url = ("https:" if url.startswith("//") else "https://") + url
    elif match.group(1).lower() not in ALLOWED_SCHEMES:
        raise ValueError(
            f"unsupported scheme '{match.group(1)}' "
            f"(only {' and '.join(ALLOWED_SCHEMES)} are allowed)"
        )

    parts = urlsplit(url)
    if not parts.hostname:
        raise ValueError(f"no host in URL '{raw}'")
    try:
        parts.port  # raises ValueError on an invalid port
    except ValueError:
        raise ValueError(f"invalid port in URL '{raw}'")

    if parts.scheme.lower() == "http":
        warn(f"'{url}' uses http: the connection is unencrypted, content can "
             "be read or altered in transit")
    return url


def prepare_directory(path: Path) -> None:
    """Create the destination directory if needed; raise OSError on failure."""
    path.mkdir(parents=True, exist_ok=True)  # FileExistsError if it is a file


def parse_config(argv: list[str]) -> Config:
    """Parse and validate the arguments. Exits with EXIT_USAGE on bad usage."""
    parser = build_parser()
    args = parser.parse_args(argv)

    recursive = args.recursive
    if args.depth is not None and not recursive:
        warn("-l given without -r: running as if -r was given")
        recursive = True

    if not recursive:
        depth = 0
    elif args.depth is None:
        depth = DEFAULT_DEPTH
    else:
        depth = args.depth

    try:
        url = normalize_start_url(args.url)
    except ValueError as exc:
        parser.error(str(exc))  # prints usage + message, exits with code 2

    return Config(url=url, recursive=recursive, depth=depth,
                  path=Path(args.path), delay=args.delay)


def run(config: Config) -> int:
    """Run the crawl and turn its outcome into an exit code."""
    crawler = Crawler(config)
    try:
        start_ok = crawler.run()
    except RateLimited as exc:
        print(crawler.summary(), flush=True)
        error(exc.message())
        return EXIT_RUNTIME
    print(crawler.summary(), flush=True)
    if not start_ok:
        error(f"the start page could not be crawled: {config.url}")
        return EXIT_RUNTIME
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    config = parse_config(sys.argv[1:] if argv is None else argv)

    try:
        prepare_directory(config.path)
    except OSError as exc:
        error(f"cannot use '{config.path}' as destination directory: "
              f"{exc.strerror or exc}")
        return EXIT_RUNTIME

    try:
        return run(config)
    except KeyboardInterrupt:
        print(file=sys.stderr)
        error("interrupted by user")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())

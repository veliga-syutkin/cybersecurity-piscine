"""The crawl itself: breadth-first traversal, page fetching, image downloads.

Applies the decisions of the README (Design choices, spider):
    - breadth-first, depth 0 = start page;
    - delay between pages only, none between the images of a page;
    - HTTP 429 stops everything (RateLimited), with Retry-After as a date;
    - an image is kept only if its status is 2xx and its content starts with
      the signature of a supported format; its extension is fixed if needed;
    - same-name files are compared byte for byte (identical -> not saved,
      different -> name_1.ext, name_2.ext, ...); nameless images are saved as
      hidden_imageX.ext.
"""

import filecmp
import os
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

from common.formats import (HEADER_SIZE, detect_format, extension_of,
                            format_from_extension, is_hidden_name)
from html_links import extract_links
from urls import UrlGate

USER_AGENT = "arachnida-spider/1.0"
TIMEOUT = 10            # seconds, for connecting and for each read
CHUNK_SIZE = 64 * 1024  # bytes per read when downloading an image
MAX_NAME_BYTES = 200    # keeps file names well below the usual 255-byte limit
HIDDEN_BASE = "hidden_image"
HTML_TYPES = ("text/html", "application/xhtml+xml")


class RateLimited(Exception):
    """Raised on HTTP 429: the whole crawl must stop."""

    def __init__(self, url: str, retry_at: datetime | None) -> None:
        super().__init__(url)
        self.url = url
        self.retry_at = retry_at

    def message(self) -> str:
        text = "Received 429 - Too Many Requests; you may retry later"
        if self.retry_at is not None:
            local = self.retry_at.astimezone()
            text += f", recommended time: {local:%Y-%m-%d %H:%M:%S %Z}"
        return text


@dataclass
class Stats:
    pages: int = 0          # HTML pages fetched and parsed
    saved: int = 0          # images written to disk
    duplicates: int = 0     # images identical to a file already saved
    rejected: int = 0       # image URLs whose content is not a supported image
    errors: int = 0         # network errors, HTTP errors, ...


def info(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(f"spider: warning: {message}", file=sys.stderr, flush=True)


def retry_after_date(value: str | None) -> datetime | None:
    """Absolute date of a Retry-After header (seconds or HTTP-date), or None."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return datetime.now(timezone.utc) + timedelta(seconds=int(value))
    try:
        date = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return date if date.tzinfo else date.replace(tzinfo=timezone.utc)


def describe(exc: requests.RequestException) -> str:
    """Short, readable reason for a network error (requests' own messages
    embed long urllib3 internals)."""
    if isinstance(exc, requests.exceptions.SSLError):
        return "TLS/SSL error (invalid or untrusted certificate?)"
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return f"connection timed out after {TIMEOUT} s"
    if isinstance(exc, requests.exceptions.Timeout):
        return f"no response for {TIMEOUT} s"
    if isinstance(exc, requests.exceptions.ConnectionError):
        text = str(exc)
        if "NameResolution" in text or "Name or service not known" in text:
            return "cannot resolve host name"
        if "Connection refused" in text:
            return "connection refused"
        return "connection failed"
    return exc.__class__.__name__


def check_rate_limit(response: requests.Response) -> None:
    if response.status_code == 429:
        raise RateLimited(response.url,
                          retry_after_date(response.headers.get("Retry-After")))


def media_type(response: requests.Response) -> str:
    """"text/html; charset=utf-8" -> "text/html"."""
    return response.headers.get("Content-Type", "").split(";")[0].strip().lower()


# --------------------------------------------------------------------------
# File names
# --------------------------------------------------------------------------

def safe_name(name: str) -> str:
    """A file name that cannot escape the destination directory.

    The name comes from a URL, i.e. from the website: "%2F" decodes to "/",
    and ".." or NUL bytes must never reach the filesystem.
    """
    name = name.replace("/", "_").replace("\\", "_").replace("\x00", "_")
    if name in ("", ".", ".."):
        name = "_"
    encoded = name.encode("utf-8")
    if len(encoded) > MAX_NAME_BYTES:
        stem, ext = os.path.splitext(name)
        budget = MAX_NAME_BYTES - len(ext.encode("utf-8"))
        stem = stem.encode("utf-8")[:budget].decode("utf-8", "ignore")
        name = stem + ext
    return name


def candidate_names(url_path: str, real_ext: str):
    """Successive file names to try for an image, until a free one is found.

    - nameless image ("/images/.png") -> hidden_image1.ext, hidden_image2.ext...
    - otherwise                       -> name.ext, name_1.ext, name_2.ext...
    where ext is the extension of the REAL format if the URL's one is wrong.
    """
    name = unquote(os.path.basename(url_path))
    if is_hidden_name(name):
        n = 1
        while True:
            yield f"{HIDDEN_BASE}{n}{real_ext}"
            n += 1

    ext_len = len(extension_of(name))
    stem = name[:-ext_len] if ext_len else name
    announced = format_from_extension(name)
    if announced is not None and announced.extension == real_ext:
        ext = name[-ext_len:]  # right format: keep the URL's extension as is
    else:
        ext = real_ext         # wrong extension: use the real format's one

    stem = safe_name(stem) if stem else "_"
    yield safe_name(stem + ext)
    n = 1
    while True:
        yield safe_name(f"{stem}_{n}{ext}")
        n += 1


def _current_umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


# Temporary files are created with mode 600; saved images get the usual mode
# of a new file (666 minus the user's umask, typically 644).
FILE_MODE = 0o666 & ~_current_umask()


def store(tmp_path: Path, url_path: str, real_ext: str, directory: Path) -> Path | None:
    """Move a downloaded image to its final name. None if it was a duplicate."""
    for name in candidate_names(url_path, real_ext):
        target = directory / name
        if not target.exists():
            os.chmod(tmp_path, FILE_MODE)
            os.replace(tmp_path, target)
            return target
        if target.is_file() and filecmp.cmp(tmp_path, target, shallow=False):
            tmp_path.unlink()
            return None
    raise AssertionError("unreachable")  # candidate_names never ends


# --------------------------------------------------------------------------
# Crawler
# --------------------------------------------------------------------------

class Crawler:
    def __init__(self, config) -> None:
        self.config = config
        self.gate = UrlGate(config.url)
        self.stats = Stats()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.scope_fixed = False  # becomes True after the start page's request

    def run(self) -> bool:
        """Crawl from the start URL. Returns False if the start page failed.

        Raises RateLimited on HTTP 429.
        """
        start = self.gate.admit_page(self.config.url)
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        first = True
        start_ok = True

        while queue:
            url, depth = queue.popleft()
            if not first and self.config.delay:
                time.sleep(self.config.delay)
            ok = self.visit(url, depth, queue)
            if first:
                start_ok = ok
                first = False
        return start_ok

    def visit(self, url: str, depth: int, queue: deque) -> bool:
        """Fetch one page, download its images, queue its links."""
        info(f"[depth {depth}] {url}")
        page = self.fetch_page(url)
        if page is None:
            return False
        html, final_url = page
        self.stats.pages += 1

        found = extract_links(html, final_url)

        # A link whose path has an image extension ("<a href=big.jpg>") is an
        # image of this page, not a page: handled like <img>, whatever the
        # depth or -r (see README, Design choices).
        image_links = [link for link in found.links
                       if format_from_extension(urlsplit(link).path)]
        page_links = [link for link in found.links if link not in image_links]

        for image_url in found.images + image_links:
            admitted = self.gate.admit_image(image_url)
            if admitted is not None:
                self.download_image(admitted)

        if self.config.recursive and depth < self.config.depth:
            for link in page_links:
                admitted = self.gate.admit_page(link)
                if admitted is not None:
                    queue.append((admitted, depth + 1))
        return True

    def fetch_page(self, url: str) -> tuple[str, str] | None:
        """(HTML text, final URL) of a page, or None if it cannot be used."""
        try:
            with self.session.get(url, timeout=TIMEOUT, stream=True) as response:
                check_rate_limit(response)
                final_url = response.url
                if not self.scope_fixed:
                    # The start page's redirects show where the site really
                    # lives: the scope follows them, once (README, scope).
                    self.scope_fixed = True
                    if self.gate.rebase(final_url):
                        info(f"  start page redirected to {final_url}, "
                             f"scope is now {self.gate.domain}")
                if not self.gate.same_page(url, final_url):  # redirected
                    if not self.gate.in_scope(final_url):
                        warn(f"{url}: redirected out of scope to {final_url}")
                        return None
                    if not self.gate.mark_page_seen(final_url):
                        info(f"  redirected to {final_url}, already crawled")
                        return None
                if not 200 <= response.status_code < 300:
                    self.error(f"{url}: HTTP {response.status_code}")
                    return None
                if media_type(response) not in HTML_TYPES:
                    info(f"  not an HTML page ({media_type(response) or 'no type'}), "
                         "skipped")
                    return None
                # requests assumes ISO-8859-1 for text/* without a charset;
                # UTF-8 is a much better default for today's web.
                charset = response.encoding if "charset" in \
                    response.headers.get("Content-Type", "").lower() else "utf-8"
                return response.content.decode(charset or "utf-8", "replace"), final_url
        except RateLimited:
            raise
        except requests.TooManyRedirects:
            self.error(f"{url}: too many redirects (redirect loop?)")
        except requests.RequestException as exc:
            self.error(f"{url}: {describe(exc)}")
        except LookupError:  # unknown charset name
            self.error(f"{url}: unknown character encoding")
        return None

    def download_image(self, url: str) -> None:
        """Download one image, validate it, store it under its final name."""
        tmp_path: Path | None = None
        try:
            with self.session.get(url, timeout=TIMEOUT, stream=True) as response:
                check_rate_limit(response)
                if not 200 <= response.status_code < 300:
                    self.error(f"  image {url}: HTTP {response.status_code}")
                    return
                if media_type(response) in HTML_TYPES:  # early filter
                    self.reject(url, f"server sent {media_type(response)}")
                    return

                chunks = response.iter_content(CHUNK_SIZE)
                head = b""
                for chunk in chunks:
                    head += chunk
                    if len(head) >= HEADER_SIZE:
                        break
                real = detect_format(head)
                if real is None:
                    self.reject(url, "content is not a supported image")
                    return

                fd, name = tempfile.mkstemp(dir=self.config.path,
                                            prefix=".spider-", suffix=".part")
                tmp_path = Path(name)
                with os.fdopen(fd, "wb") as out:
                    out.write(head)
                    for chunk in chunks:
                        out.write(chunk)

            url_path = urlsplit(url).path
            target = store(tmp_path, url_path, real.extension, self.config.path)
            tmp_path = None  # moved or deleted by store()
            if target is None:
                self.stats.duplicates += 1
                info(f"  = {url} (identical file already saved)")
            else:
                self.stats.saved += 1
                fixed = format_from_extension(url_path) != real
                note = f" (extension fixed: real format is {real.name})" \
                    if fixed else ""
                info(f"  + {target}{note}")
        except RateLimited:
            raise
        except requests.RequestException as exc:
            self.error(f"  image {url}: {describe(exc)}")
        except OSError as exc:
            self.error(f"  image {url}: cannot save: {exc}")
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()

    def reject(self, url: str, reason: str) -> None:
        self.stats.rejected += 1
        warn(f"image {url}: rejected, {reason}")

    def error(self, message: str) -> None:
        self.stats.errors += 1
        warn(message.strip())

    def summary(self) -> str:
        s = self.stats
        return (f"{s.pages} page(s) crawled, {s.saved} image(s) saved, "
                f"{s.duplicates} duplicate(s), {s.rejected} rejected, "
                f"{s.errors} error(s)")

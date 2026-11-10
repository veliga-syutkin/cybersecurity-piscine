"""URL handling for spider: resolution, normalization, scope, "already seen".

Every URL found while crawling goes through a single checkpoint, UrlGate,
which answers "may this URL be fetched?" (see README, Design choices):
    - only http / https;
    - normalized to a canonical form;
    - pages only: inside the crawl scope (same host as the start page, "www." ignored);
    - not already seen.
"""

from urllib.parse import urljoin, urlsplit, urlunsplit

from common.formats import format_from_extension

ALLOWED_SCHEMES = ("http", "https")
DEFAULT_PORTS = {"http": 80, "https": 443}


def resolve(base: str, link: str) -> str | None:
    """Absolute URL of a link found in a page, or None if there is none.

    `base` is the page's final URL (after redirects), or its <base href>.
    HTML attribute values may carry surrounding whitespace: it is stripped.
    """
    link = link.strip()
    if not link:
        return None
    return urljoin(base, link)


def remove_dot_segments(path: str) -> str:
    """Resolve "." and ".." segments of a path (RFC 3986, §5.2.4)."""
    output: list[str] = []
    for segment in path.split("/"):
        if segment == ".":
            continue
        if segment == "..":
            if len(output) > 1:  # never pop the leading "" (root)
                output.pop()
            continue
        output.append(segment)
    result = "/".join(output)
    # "/a/b/.." and "/a/." designate a directory: keep the trailing slash.
    if path.endswith(("/.", "/..")) and not result.endswith("/"):
        result += "/"
    return result or "/"


def normalize(url: str) -> str | None:
    """Canonical, fetchable form of an absolute URL, or None if unsupported.

    - scheme and host lowercased (the path keeps its case);
    - default port removed (:80 for http, :443 for https);
    - fragment removed (never sent to the server);
    - empty path replaced by "/", "." and ".." segments resolved;
    - query string kept as is; "/dir" and "/dir/" stay distinct.
    """
    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError on an invalid port
    except ValueError:
        return None

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES or not parts.hostname:
        return None

    host = parts.hostname  # already lowercased by urlsplit
    if ":" in host:        # IPv6 literal: brackets are needed in a URL
        host = f"[{host}]"
    netloc = host if port in (None, DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    if "@" in parts.netloc:  # keep user info, if any
        netloc = parts.netloc.rpartition("@")[0] + "@" + netloc

    path = remove_dot_segments(parts.path) if parts.path else "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def seen_key(normalized_url: str) -> str:
    """Key used for "already seen" checks.

    On top of normalize(): the "www." prefix and the http / https difference
    are ignored, so these all give the same key:
        http://site.com/a   https://site.com/a   https://www.site.com/a
    """
    parts = urlsplit(normalized_url)
    netloc = parts.netloc
    user, at, hostport = netloc.rpartition("@")
    netloc = user + at + strip_www(hostport)
    return urlunsplit(("", netloc, parts.path, parts.query, ""))


class UrlGate:
    """The single "may this URL be fetched?" checkpoint of the crawl."""

    def __init__(self, start_url: str) -> None:
        start = normalize(start_url)
        if start is None:
            raise ValueError(f"unsupported start URL: '{start_url}'")
        self.start_url = start
        # Scope: the start host without "www." ("www.site.com" and "site.com"
        # are the same site). Moved once by rebase() if the start page
        # redirects elsewhere.
        self.domain = strip_www(urlsplit(start).hostname or "")
        self._seen_pages: set[str] = set()
        self._seen_images: set[str] = set()

    def in_scope(self, normalized_url: str) -> bool:
        """Same host only ("www." ignored): subdomains are out of scope,
        "blog.site.com" is not part of a crawl of "site.com"."""
        host = strip_www(urlsplit(normalized_url).hostname or "")
        return host == self.domain

    def rebase(self, final_start_url: str) -> bool:
        """Set the scope to the host the start page really lives on (after
        its redirects), e.g. "site.com" -> "fr.site.com".

        Returns True if the scope changed.
        """
        normalized = normalize(final_start_url)
        if normalized is None:
            return False
        host = strip_www(urlsplit(normalized).hostname or "")
        if not host or host == self.domain:
            return False
        self.domain = host
        return True

    def admit_page(self, url: str) -> str | None:
        """Normalized URL of a page to visit, or None if it must be skipped.

        A page is marked as seen as soon as it is admitted (i.e. queued), so a
        page linked from many others is queued only once.
        """
        normalized = normalize(url)
        if normalized is None or not self.in_scope(normalized):
            return None
        key = seen_key(normalized)
        if key in self._seen_pages:
            return None
        self._seen_pages.add(key)
        return normalized

    def mark_page_seen(self, url: str) -> bool:
        """Mark a URL as seen without admitting it — used for the final URL
        after a redirect, so a direct link to it is not fetched again.

        Returns False if it was already seen (the page was, or will be,
        crawled through another link: no need to process it twice).
        """
        normalized = normalize(url)
        if normalized is None:
            return False
        key = seen_key(normalized)
        if key in self._seen_pages:
            return False
        self._seen_pages.add(key)
        return True

    def same_page(self, url_a: str, url_b: str) -> bool:
        """True if both URLs designate the same page for "already seen"."""
        a, b = normalize(url_a), normalize(url_b)
        return a is not None and b is not None and seen_key(a) == seen_key(b)

    def admit_image(self, url: str) -> str | None:
        """Normalized URL of an image to download, or None if it must be skipped.

        The image is selected by the extension of its path (query string and
        fragment excluded). The real format is checked later, on the content.

        No scope check: an image shown on an in-scope page is downloaded
        whatever its domain (e.g. a CDN). The scope limits the crawl (pages),
        and an image is a single request, never a starting point.
        """
        normalized = normalize(url)
        if normalized is None:
            return None
        if format_from_extension(urlsplit(normalized).path) is None:
            return None
        key = seen_key(normalized)
        if key in self._seen_images:
            return None
        self._seen_images.add(key)
        return normalized

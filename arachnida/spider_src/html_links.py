"""Extraction of the URLs found in an HTML page.

Pure extraction: no request, no scope or "already seen" decision (that is the
job of urls.UrlGate). Principle: what the user sees, spider downloads.
Extracted:
    - images: <img src>, <img srcset>, <source srcset> (inside <picture>);
    - links:  <a href>, <area href>, <iframe src>, <frame src>, and the target
              of <meta http-equiv="refresh">, treated as an ordinary link
              (see README, Design choices);
    - base:   the first <base href>, used to resolve every relative URL.
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser

from urls import resolve


@dataclass
class PageLinks:
    """Absolute URLs found in a page (not normalized, not filtered)."""

    images: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


def parse_refresh_target(content: str) -> str | None:
    """Target URL of a <meta http-equiv="refresh" content="...">, or None.

    Accepted forms (as browsers do): "5; url=page.html", "0;URL='page.html'",
    "0, url=page.html", "0; page.html". A delay alone ("30") has no target.
    """
    _, sep, rest = content.partition(";")
    if not sep:
        _, sep, rest = content.partition(",")
    if not sep:
        return None
    rest = rest.strip()
    if rest[:3].lower() == "url":
        after = rest[3:].lstrip()
        if after.startswith("="):
            rest = after[1:].strip()
    if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in "'\"":
        rest = rest[1:-1]
    return rest.strip() or None


def parse_srcset(srcset: str) -> list[str]:
    """URLs of a srcset attribute, e.g. "a-400.jpg 400w, a-800.jpg 2x".

    Follows the shape of the HTML "parse a srcset attribute" algorithm: a
    candidate is a URL (no whitespace) optionally followed by descriptors, and
    candidates are separated by commas. A URL itself may contain commas, so
    the string is not simply split on ",".
    """
    urls: list[str] = []
    i, n = 0, len(srcset)
    while i < n:
        # Skip whitespace and separating commas.
        while i < n and (srcset[i].isspace() or srcset[i] == ","):
            i += 1
        start = i
        while i < n and not srcset[i].isspace():
            i += 1
        url = srcset[start:i]
        if not url:
            break
        if url.endswith(","):
            # "a.jpg,b.jpg": trailing commas end the candidate, no descriptor.
            url = url.rstrip(",")
        else:
            # Skip the descriptors ("400w", "2x") up to the next comma.
            while i < n and srcset[i] != ",":
                i += 1
        if url:
            urls.append(url)
    return urls


class _LinkCollector(HTMLParser):
    """Collects raw attribute values; resolution happens once parsing is done,
    because <base href> applies to the whole document, even to URLs that come
    before it in the source."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)  # "&amp;" -> "&" in attributes
        self.base_href: str | None = None
        self.raw_images: list[str] = []
        self.raw_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Tag and attribute names are lowercased by HTMLParser; a value is None
        # for an attribute written without "=value".
        attributes = {name: value for name, value in attrs if value is not None}

        if tag == "img":
            if "src" in attributes:
                self.raw_images.append(attributes["src"])
            if "srcset" in attributes:
                self.raw_images.extend(parse_srcset(attributes["srcset"]))
        elif tag == "source" and "srcset" in attributes:
            self.raw_images.extend(parse_srcset(attributes["srcset"]))
        elif tag in ("a", "area") and "href" in attributes:
            self.raw_links.append(attributes["href"])
        elif tag in ("iframe", "frame") and "src" in attributes:
            self.raw_links.append(attributes["src"])
        elif tag == "base" and "href" in attributes and self.base_href is None:
            self.base_href = attributes["href"]  # only the first one counts
        elif (tag == "meta"
              and attributes.get("http-equiv", "").strip().lower() == "refresh"
              and "content" in attributes):
            target = parse_refresh_target(attributes["content"])
            if target is not None:
                self.raw_links.append(target)

    # <img ... /> is reported as a "startendtag": handle it the same way.
    handle_startendtag = handle_starttag


def extract_links(html: str, page_url: str) -> PageLinks:
    """URLs of the images and links of a page.

    `page_url` is the page's final URL (after redirects). If the page declares
    a <base href>, it is resolved against `page_url` and used instead of it.
    """
    collector = _LinkCollector()
    collector.feed(html)
    collector.close()

    base = page_url
    if collector.base_href is not None:
        base = resolve(page_url, collector.base_href) or page_url

    result = PageLinks()
    for raw in collector.raw_images:
        url = resolve(base, raw)
        if url is not None:
            result.images.append(url)
    for raw in collector.raw_links:
        url = resolve(base, raw)
        if url is not None:
            result.links.append(url)
    return result

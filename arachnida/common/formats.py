"""Image formats supported by both spider and scorpion.

Single source of truth for:
    - the supported extensions (spider selects image URLs with them);
    - the file signatures, a.k.a. magic bytes (spider validates downloads and
      fixes wrong extensions with them; scorpion detects the real format).

Signatures come from the specifications listed in Exif.md (§2 and References).
"""

import os
from dataclasses import dataclass

# A signature is a list of (offset, expected bytes) that must ALL match.
Signature = tuple[tuple[int, bytes], ...]


@dataclass(frozen=True)
class ImageFormat:
    name: str
    extensions: tuple[str, ...]      # lowercase, with the dot; first = canonical
    signatures: tuple[Signature, ...]  # alternatives: ANY of them may match

    @property
    def extension(self) -> str:
        """Canonical extension, used when an extension has to be fixed."""
        return self.extensions[0]

    def matches(self, header: bytes) -> bool:
        """True if the first bytes of a file match one of the signatures."""
        return any(
            all(header[offset:offset + len(expected)] == expected
                for offset, expected in signature)
            for signature in self.signatures
        )


JPEG = ImageFormat(
    name="JPEG",
    extensions=(".jpg", ".jpeg"),
    # SOI marker (FF D8) immediately followed by another marker (FF xx)
    # [ITU-T T.81, Table B.1].
    signatures=(((0, b"\xff\xd8\xff"),),),
)

PNG = ImageFormat(
    name="PNG",
    extensions=(".png",),
    # [PNG 3rd edition, §5.2]
    signatures=(((0, b"\x89PNG\r\n\x1a\n"),),),
)

GIF = ImageFormat(
    name="GIF",
    extensions=(".gif",),
    # "GIF" + version "87a" or "89a" [GIF89a, §17]
    signatures=(((0, b"GIF87a"),), ((0, b"GIF89a"),)),
)

BMP = ImageFormat(
    name="BMP",
    extensions=(".bmp",),
    # bfType = "BM", then bfSize (4 bytes), then bfReserved1 and bfReserved2,
    # which "must be zero" [Microsoft, BITMAPFILEHEADER]. Checking the reserved
    # bytes makes the 2-byte "BM" signature much less likely to match by chance
    # (e.g. a text file starting with "BM").
    signatures=(((0, b"BM"), (6, b"\x00\x00\x00\x00")),),
)

FORMATS: tuple[ImageFormat, ...] = (JPEG, PNG, GIF, BMP)

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    ext for fmt in FORMATS for ext in fmt.extensions
)

# Number of leading bytes needed to recognize any supported format.
HEADER_SIZE: int = max(
    offset + len(expected)
    for fmt in FORMATS
    for signature in fmt.signatures
    for offset, expected in signature
)


def detect_format(header: bytes) -> ImageFormat | None:
    """Real format of a file, from its first bytes (at least HEADER_SIZE)."""
    for fmt in FORMATS:
        if fmt.matches(header):
            return fmt
    return None


def extension_of(path: str) -> str:
    """Lowercase extension (with the dot) of a file name or URL path, or "".

    Unlike os.path.splitext, a name made only of dots and an extension
    (".png", "..png") is considered to HAVE that extension: such image URLs
    exist (e.g. "/images/.png") and must not be missed. A dot-file whose
    "extension" is not a supported one (".bashrc") is unaffected in practice,
    since only supported extensions are ever looked up.
    """
    name = os.path.basename(path)
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[1].lower()


def is_hidden_name(path: str) -> bool:
    """True for a name with nothing before its extension (".png", "..png")."""
    name = os.path.basename(path)
    return bool(name) and name.rsplit(".", 1)[0].strip(".") == ""


def format_from_extension(path: str) -> ImageFormat | None:
    """Format announced by the extension of a file name or URL path.

    The caller must pass a path only: no query string, no fragment
    ("photo.jpg?w=300" must be passed as "photo.jpg").
    """
    ext = extension_of(path)
    for fmt in FORMATS:
        if ext in fmt.extensions:
            return fmt
    return None

"""Exif parser: the TIFF structure found in a JPEG APP1 segment or a PNG eXIf
chunk (see Exif.md §4 to §6 and §8).

Hand-written on purpose (the subject asks for our own logic), with the safety
checks of Exif.md §8: every offset is bounds-checked, IFDs already visited are
not read again (no infinite loop), unknown types are skipped, a truncated
block never crashes the parser.
"""

import struct

from exif_tags import BYTE_ORDER_KEY, convert, tag_name


class ExifError(Exception):
    """The Exif block is unusable (bad header, first IFD out of bounds...)."""


# Size in bytes of one value of each type [TIFF §2], [Exif §4.6.2];
# 129 = UTF-8, added by Exif 3.0.
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8,
              11: 4, 12: 8, 129: 1}
# struct format of one value (bytes-like types are kept as bytes).
TYPE_FORMATS = {3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d"}
RATIONAL, SRATIONAL = 5, 10
BYTE_TYPES = (1, 2, 7, 129)  # BYTE, ASCII, UNDEFINED, UTF-8

MAX_ENTRIES = 1000  # far above any real IFD: more means a wrong position

# Pointer tags -> name of the IFD they point to [Exif §4.6.3]
POINTERS = {
    "0th": {0x8769: "exif", 0x8825: "gps"},
    "exif": {0xA005: "interoperability"},
}
IFD_ORDER = ("0th", "exif", "gps", "interoperability", "1st")


class TiffReader:
    """Bounds-checked reads in a TIFF block, in its declared byte order."""

    def __init__(self, data: bytes) -> None:
        if len(data) < 8:
            raise ExifError("truncated TIFF header")
        order = data[:2]
        if order == b"II":
            self.prefix, self.order = "<", "little endian (II)"
        elif order == b"MM":
            self.prefix, self.order = ">", "big endian (MM)"
        else:
            raise ExifError(f"invalid byte order {order!r} (expected II or MM)")
        self.data = data
        if self.unpack("H", 2)[0] != 42:
            raise ExifError("invalid TIFF magic number (expected 42)")

    def has(self, offset: int, size: int) -> bool:
        return 0 <= offset and offset + size <= len(self.data)

    def unpack(self, fmt: str, offset: int, count: int = 1) -> tuple:
        size = struct.calcsize(fmt) * count
        if not self.has(offset, size):
            raise ExifError(f"read out of bounds at offset {offset}")
        return struct.unpack_from(f"{self.prefix}{count}{fmt}", self.data, offset)


def read_values(reader: TiffReader, type_code: int, count: int, field: int,
                warnings: list[str], label: str):
    """Values of one entry. `field` is the offset of its 4-byte value field.

    Returns bytes for BYTE/ASCII/UNDEFINED/UTF-8, a tuple of numbers, or a
    tuple of (numerator, denominator) pairs; None if unreadable.
    """
    total = TYPE_SIZES[type_code] * count
    if total <= 4:
        start = field  # inline value, left-justified [TIFF §2]
    else:
        start = reader.unpack("I", field)[0]
        if not reader.has(start, total):
            warnings.append(f"{label}: value out of bounds "
                            f"(offset {start}, {total} bytes), skipped")
            return None

    if type_code in BYTE_TYPES:
        return reader.data[start:start + total]
    if type_code in (RATIONAL, SRATIONAL):
        fmt = "I" if type_code == RATIONAL else "i"
        flat = reader.unpack(fmt, start, 2 * count)
        return tuple(zip(flat[0::2], flat[1::2]))
    return reader.unpack(TYPE_FORMATS[type_code], start, count)


def read_ifd(reader: TiffReader, offset: int, name: str,
             warnings: list[str]) -> tuple[dict, int]:
    """Raw entries {tag: (type, values)} of one IFD, and the next IFD offset."""
    if not reader.has(offset, 2):
        raise ExifError(f"{name} IFD offset {offset} out of bounds")
    count = reader.unpack("H", offset)[0]
    if count > MAX_ENTRIES:
        raise ExifError(f"{name} IFD: {count} entries, not plausible")
    if not reader.has(offset + 2, 12 * count):
        raise ExifError(f"{name} IFD truncated ({count} entries announced)")

    entries: dict[int, tuple[int, object]] = {}
    for i in range(count):
        entry = offset + 2 + 12 * i
        # Bounds already checked above for the whole entry array.
        tag, type_code, n = struct.unpack_from(f"{reader.prefix}HHI",
                                               reader.data, entry)
        label = f"{name} IFD, {tag_name(name, tag)}"
        if type_code not in TYPE_SIZES:
            warnings.append(f"{label}: unknown type {type_code}, skipped")
            continue
        values = read_values(reader, type_code, n, entry + 8, warnings, label)
        if values is not None:
            entries[tag] = (type_code, values)

    next_field = offset + 2 + 12 * count
    next_offset = reader.unpack("I", next_field)[0] \
        if reader.has(next_field, 4) else 0
    return entries, next_offset


def parse_exif(data: bytes) -> dict:
    """Parse a TIFF/Exif block; returns the JSON-ready result.

    Raises ExifError if the header or the 0th IFD is unusable. Problems in
    other IFDs are reported in "warnings" and do not stop the parsing.
    """
    reader = TiffReader(data)
    warnings: list[str] = []
    raw_ifds: dict[str, dict] = {}
    visited: set[int] = set()

    def visit(name: str, offset: int) -> int:
        """Read one IFD (once); returns its "next IFD" offset."""
        if offset in visited:
            warnings.append(f"{name} IFD: offset {offset} already read "
                            "(loop), skipped")
            return 0
        visited.add(offset)
        entries, next_offset = read_ifd(reader, offset, name, warnings)
        raw_ifds[name] = entries
        for tag, child in POINTERS.get(name, {}).items():
            if tag in entries:
                type_code, values = entries[tag]
                if type_code in (3, 4) and isinstance(values, tuple) and values:
                    try:
                        visit(child, values[0])
                    except ExifError as exc:
                        warnings.append(str(exc))
        return next_offset

    first = reader.unpack("I", 4)[0]
    next_offset = visit("0th", first)          # errors here are fatal
    if next_offset:
        try:
            visit("1st", next_offset)          # thumbnail IFD [Exif §4.7.2]
        except ExifError as exc:
            warnings.append(str(exc))

    ifds = {}
    for name in IFD_ORDER:
        if name not in raw_ifds:
            continue
        entries = raw_ifds[name]
        raw_values = {tag: values for tag, (_, values) in entries.items()}
        raw_values[BYTE_ORDER_KEY] = reader.data[:2].decode("ascii")
        ifds[name] = {
            tag_name(name, tag): convert(name, tag_name(name, tag),
                                         type_code, values, raw_values)
            for tag, (type_code, values) in sorted(entries.items())
        }

    result = {"byte_order": reader.order, "ifds": ifds}
    if warnings:
        result["warnings"] = warnings
    return result

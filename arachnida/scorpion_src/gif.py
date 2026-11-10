"""GIF: header, logical screen descriptor, and blocks (GIF89a, §17 to §27).

Collected: version, size, number of frames, comments (Comment Extension,
label 0xFE), and application extensions (e.g. NETSCAPE2.0 = looping
animation), and the XMP packet ("XMP DataXMP", shown as text). All
multi-byte numbers are little endian [GIF89a §4].
"""

import struct

from exif_tags import XMP_HEAD, text_value

EXTENSION, IMAGE, TRAILER = 0x21, 0x2C, 0x3B
COMMENT, APPLICATION = 0xFE, 0xFF
XMP_APP_ID = b"XMP DataXMP"
# The XMP packet is stored raw, then followed by this 258-byte "magic
# trailer" that makes the GIF sub-block chain end properly (XMP spec, part 3).
XMP_TRAILER = b"\x01" + bytes(range(0xFF, -1, -1)) + b"\x00"


class Truncated(Exception):
    pass


def skip_sub_blocks(data: bytes, pos: int) -> tuple[bytes, int]:
    """Read a sequence of data sub-blocks (size byte + data, ends with 0)."""
    chunks = []
    while True:
        if pos >= len(data):
            raise Truncated()
        size = data[pos]
        pos += 1
        if size == 0:
            return b"".join(chunks), pos
        if pos + size > len(data):
            raise Truncated()
        chunks.append(data[pos:pos + size])
        pos += size


def color_table_size(packed: int) -> int:
    return 3 * (2 ** ((packed & 0x07) + 1)) if packed & 0x80 else 0


def parse_gif(data: bytes) -> dict:
    result: dict = {"version": data[3:6].decode("ascii", "replace"),
                    "image": None, "frames": 0, "comments": [],
                    "applications": [], "xmp": None}
    warnings: list[str] = []
    if len(data) < 13:
        result["warnings"] = ["truncated header"]
        return result

    width, height, packed = struct.unpack_from("<HHB", data, 6)
    result["image"] = {"width": width, "height": height,
                       "global_color_table": bool(packed & 0x80),
                       "color_resolution_bits": ((packed >> 4) & 0x07) + 1}
    pos = 13 + color_table_size(packed)

    try:
        while True:
            if pos >= len(data):
                raise Truncated()
            block = data[pos]
            pos += 1
            if block == TRAILER:
                break
            if block == IMAGE:  # image descriptor + optional local color table
                if pos + 9 > len(data):
                    raise Truncated()
                packed = data[pos + 8]
                pos += 9 + color_table_size(packed) + 1  # +1: LZW code size
                _, pos = skip_sub_blocks(data, pos)
                result["frames"] += 1
            elif block == EXTENSION:
                if pos >= len(data):
                    raise Truncated()
                label = data[pos]
                start = pos + 1
                body, pos = skip_sub_blocks(data, start)
                if label == APPLICATION and body.startswith(XMP_APP_ID):
                    packet_start = start + 1 + len(XMP_APP_ID)
                    packet_end = data.find(XMP_TRAILER, packet_start, pos)
                    if packet_end != -1 and result.get("xmp") is None:
                        result["xmp"] = text_value(
                            data[packet_start:packet_end].decode("utf-8",
                                                                 "replace"),
                            limit=XMP_HEAD)
                if label == COMMENT:
                    result["comments"].append(
                        text_value(body.decode("utf-8", "replace")))
                elif label == APPLICATION and len(body) >= 11:
                    result["applications"].append(
                        body[:11].decode("ascii", "replace"))
            else:
                warnings.append(f"unknown block 0x{block:02X} at offset "
                                f"{pos - 1}, stopped reading blocks")
                break
    except Truncated:
        warnings.append("truncated file (no trailer)")

    if warnings:
        result["warnings"] = warnings
    return result

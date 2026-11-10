"""PNG: walk the chunks (PNG 3rd edition, §5.3 and §11; see Exif.md §10).

Collected: IHDR (size, depth, color type), pHYs (resolution), tIME (last
modification), text chunks (tEXt, zTXt, iTXt), Exif (eXIf). Each chunk's
CRC is checked.
"""

import struct
import zlib

from exif import ExifError, parse_exif
from exif_tags import TEXT_HEAD as TEXT_LIMIT, XMP_HEAD, text_value

SIGNATURE_SIZE = 8
COLOR_TYPES = {0: "Greyscale", 2: "Truecolor", 3: "Indexed-color",
               4: "Greyscale with alpha", 6: "Truecolor with alpha"}
INTERLACE = {0: "none", 1: "Adam7"}
MAX_TEXT = 1024 * 1024  # decompressed text limit: protects from zip bombs
XMP_KEYWORD = b"XML:com.adobe.xmp"


def inflate(data: bytes, limit: int):
    """zlib-decompress a text, never producing more than MAX_TEXT bytes;
    returns its JSON value (abbreviated if long or capped)."""
    decompressor = zlib.decompressobj()
    text = decompressor.decompress(data, MAX_TEXT)
    capped = bool(decompressor.unconsumed_tail)
    return text_value(text.decode("utf-8", "replace"), capped, limit)


def parse_png(data: bytes) -> dict:
    result: dict = {"image": None, "time": None, "text": [], "exif": None}
    warnings: list[str] = []
    pos = SIGNATURE_SIZE

    while pos + 8 <= len(data):
        length, ctype = struct.unpack_from(">I4s", data, pos)
        name = ctype.decode("latin-1")
        if pos + 12 + length > len(data):
            warnings.append(f"chunk {name} truncated, stopped reading chunks")
            break
        body = data[pos + 8:pos + 8 + length]
        crc = struct.unpack_from(">I", data, pos + 8 + length)[0]
        if zlib.crc32(ctype + body) != crc:
            warnings.append(f"chunk {name}: CRC mismatch (corrupted?)")
        pos += 12 + length

        try:
            if ctype == b"IHDR" and length >= 13:
                w, h, depth, color, _, _, interlace = \
                    struct.unpack_from(">IIBBBBB", body)
                result["image"] = {
                    "width": w, "height": h, "bit_depth": depth,
                    "color_type": COLOR_TYPES.get(color, f"unknown ({color})"),
                    "interlace": INTERLACE.get(interlace, str(interlace))}
            elif ctype == b"pHYs" and length >= 9:
                x, y, unit = struct.unpack_from(">IIB", body)
                if unit == 1:  # pixels per metre
                    result["resolution"] = {
                        "raw": [x, y, "pixels per metre"],
                        "text": f"{round(x * 0.0254)} x {round(y * 0.0254)} dpi"}
                else:
                    result["resolution"] = {"raw": [x, y, "aspect ratio only"]}
            elif ctype == b"tIME" and length >= 7:
                y, mo, d, h, mi, s = struct.unpack_from(">HBBBBB", body)
                result["time"] = f"{y:04d}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}Z"
            elif ctype == b"tEXt":
                key, _, text = body.partition(b"\x00")
                result["text"].append({"chunk": "tEXt",
                                       "keyword": key.decode("latin-1"),
                                       "text": text_value(text.decode("latin-1"))})
            elif ctype == b"zTXt":
                key, _, rest = body.partition(b"\x00")
                result["text"].append({"chunk": "zTXt",
                                       "keyword": key.decode("latin-1"),
                                       "text": inflate(rest[1:], TEXT_LIMIT)})
            elif ctype == b"iTXt":
                key, _, rest = body.partition(b"\x00")
                # The XMP packet of a PNG is an iTXt chunk with this keyword.
                limit = XMP_HEAD if key == XMP_KEYWORD else TEXT_LIMIT
                compressed = rest[:1] == b"\x01"
                lang, _, rest = rest[2:].partition(b"\x00")
                translated, _, text = rest.partition(b"\x00")
                result["text"].append({
                    "chunk": "iTXt", "keyword": key.decode("latin-1"),
                    "language": lang.decode("ascii", "replace") or None,
                    "translated_keyword":
                        translated.decode("utf-8", "replace") or None,
                    "text": inflate(text, limit) if compressed
                    else text_value(text.decode("utf-8", "replace"),
                                    limit=limit)})
            elif ctype == b"eXIf":
                # Same TIFF structure as APP1, without "Exif\0\0" [PNG §11.3.4.5]
                try:
                    result["exif"] = parse_exif(body)
                except ExifError as exc:
                    warnings.append(f"Exif block unusable: {exc}")
            elif ctype == b"IEND":
                break
        except (struct.error, zlib.error) as exc:
            warnings.append(f"chunk {name} unreadable: {exc}")

    if result["image"] is None:
        warnings.append("no IHDR chunk")
    if warnings:
        result["warnings"] = warnings
    return result

"""JPEG: walk the marker segments (see Exif.md §3).

Collected: image size (SOFn frame header), the Exif block (APP1 "Exif\\0\\0"),
the XMP packet (APP1, shown as text), JFIF header (APP0), comments (COM), and
the list of other application segments (APPn), so that no metadata goes
unnoticed.
"""

import struct

from exif import ExifError, parse_exif
from exif_tags import XMP_HEAD, text_value

# SOFn markers: C0..CF except C4 (DHT), C8 (JPG), CC (DAC) [T.81 Table B.1]
SOF_NAMES = {
    0xC0: "baseline DCT", 0xC1: "extended sequential DCT",
    0xC2: "progressive DCT", 0xC3: "lossless",
    0xC5: "differential sequential DCT", 0xC6: "differential progressive DCT",
    0xC7: "differential lossless", 0xC9: "extended sequential DCT, arithmetic",
    0xCA: "progressive DCT, arithmetic", 0xCB: "lossless, arithmetic",
    0xCD: "differential sequential DCT, arithmetic",
    0xCE: "differential progressive DCT, arithmetic",
    0xCF: "differential lossless, arithmetic",
}
STANDALONE = set(range(0xD0, 0xD8)) | {0x01}  # RSTm, TEM: no length field
SOI, EOI, SOS, COM, APP0, APP1 = 0xD8, 0xD9, 0xDA, 0xFE, 0xE0, 0xE1
EXIF_ID = b"Exif\x00\x00"           # [Exif §4.7.2 C]
XMP_ID = b"http://ns.adobe.com/xap/1.0/\x00"
JFIF_ID = b"JFIF\x00"
DENSITY_UNITS = {0: "no unit (aspect ratio)", 1: "dots per inch",
                 2: "dots per cm"}


def parse_jpeg(data: bytes) -> dict:
    """Metadata of a JPEG file (whole content in `data`)."""
    result: dict = {"image": None, "jfif": None, "comments": [],
                    "other_segments": [], "exif": None, "xmp": None}
    warnings: list[str] = []
    pos = 2  # after SOI (checked by the caller through the signature)

    while pos < len(data):
        if data[pos] != 0xFF:
            warnings.append(f"expected a marker at offset {pos}, "
                            "stopped reading segments")
            break
        while pos < len(data) and data[pos] == 0xFF:  # fill bytes [T.81 B.1.1.2]
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in STANDALONE or marker == SOI:
            continue
        if marker == EOI:
            break
        if pos + 2 > len(data):
            warnings.append("truncated file (segment length missing)")
            break
        length = struct.unpack_from(">H", data, pos)[0]  # big endian [T.81 B.1.1.4]
        if length < 2 or pos + length > len(data):
            warnings.append(f"segment FF{marker:02X} at offset {pos - 2}: "
                            "length out of bounds, stopped reading segments")
            break
        payload = data[pos + 2:pos + length]
        pos += length

        if marker in SOF_NAMES and len(payload) >= 6:
            precision, height, width, components = \
                struct.unpack_from(">BHHB", payload, 0)
            result["image"] = {"width": width, "height": height,
                               "bits_per_sample": precision,
                               "components": components,
                               "coding": f"SOF{marker - 0xC0}: "
                                         f"{SOF_NAMES[marker]}"}
        elif marker == APP1 and payload.startswith(EXIF_ID):
            if result["exif"] is None:
                try:
                    result["exif"] = parse_exif(payload[len(EXIF_ID):])
                except ExifError as exc:
                    warnings.append(f"Exif block unusable: {exc}")
        elif marker == APP1 and payload.startswith(XMP_ID):
            # XMP (XML) shown as text, never parsed (README, Design choices).
            if result["xmp"] is None:
                result["xmp"] = text_value(
                    payload[len(XMP_ID):].decode("utf-8", "replace"),
                    limit=XMP_HEAD)
        elif marker == APP0 and payload.startswith(JFIF_ID) and len(payload) >= 14:
            major, minor, units, x, y = struct.unpack_from(">BBBHH", payload, 5)
            result["jfif"] = {"version": f"{major}.{minor:02d}",
                              "density": f"{x} x {y} "
                                         f"{DENSITY_UNITS.get(units, '?')}"}
        elif marker == COM:
            result["comments"].append(
                text_value(payload.decode("utf-8", "replace")))
        elif 0xE0 <= marker <= 0xEF:
            ident = payload[:payload.find(b"\x00")] if b"\x00" in payload[:32] \
                else payload[:8]
            result["other_segments"].append(
                {"segment": f"APP{marker - 0xE0}",
                 "type": ident.decode("ascii", "replace") or None,
                 "size": len(payload)})
        elif marker == SOS:
            break  # entropy-coded data follows: metadata segments are before

    if warnings:
        result["warnings"] = warnings
    return result

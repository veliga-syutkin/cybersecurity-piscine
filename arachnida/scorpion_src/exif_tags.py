"""Exif tag names, enumerations, and conversion of values to JSON.

Names and enumerated values are taken from the Exif 2.31 specification
(CIPA DC-008-2016): §4.6.4 (TIFF tags), §4.6.5 (Exif IFD), §4.6.6 (GPS IFD),
§4.6.7 (Interoperability IFD). See Exif.md, References.

Output rules (README, Design choices):
    - simple values (text, single number) stay as they are;
    - a converted value is {"raw": <as stored>, "text": <readable>, ...};
    - long binary values are abbreviated to {"size": n, "head": "<hex>"}.
"""

from fractions import Fraction

# --------------------------------------------------------------------------
# Tag names
# --------------------------------------------------------------------------

TIFF_TAGS = {  # 0th IFD and 1st IFD [Exif §4.6.4]
    0x0100: "ImageWidth", 0x0101: "ImageLength", 0x0102: "BitsPerSample",
    0x0103: "Compression", 0x0106: "PhotometricInterpretation",
    0x010E: "ImageDescription", 0x010F: "Make", 0x0110: "Model",
    0x0111: "StripOffsets", 0x0112: "Orientation", 0x0115: "SamplesPerPixel",
    0x0116: "RowsPerStrip", 0x0117: "StripByteCounts", 0x011A: "XResolution",
    0x011B: "YResolution", 0x011C: "PlanarConfiguration",
    0x0128: "ResolutionUnit", 0x012D: "TransferFunction", 0x0131: "Software",
    0x0132: "DateTime", 0x013B: "Artist", 0x013E: "WhitePoint",
    0x013F: "PrimaryChromaticities", 0x0201: "JPEGInterchangeFormat",
    0x0202: "JPEGInterchangeFormatLength", 0x0211: "YCbCrCoefficients",
    0x0212: "YCbCrSubSampling", 0x0213: "YCbCrPositioning",
    0x0214: "ReferenceBlackWhite", 0x8298: "Copyright",
    # Pointers to the other IFDs [Exif §4.6.3]
    0x8769: "ExifIFDPointer", 0x8825: "GPSInfoIFDPointer",
}

EXIF_TAGS = {  # Exif IFD [Exif §4.6.5]
    0x829A: "ExposureTime", 0x829D: "FNumber", 0x8822: "ExposureProgram",
    0x8824: "SpectralSensitivity", 0x8827: "PhotographicSensitivity",
    0x8828: "OECF", 0x8830: "SensitivityType",
    0x8831: "StandardOutputSensitivity", 0x8832: "RecommendedExposureIndex",
    0x8833: "ISOSpeed", 0x8834: "ISOSpeedLatitudeyyy",
    0x8835: "ISOSpeedLatitudezzz", 0x9000: "ExifVersion",
    0x9003: "DateTimeOriginal", 0x9004: "DateTimeDigitized",
    0x9010: "OffsetTime", 0x9011: "OffsetTimeOriginal",
    0x9012: "OffsetTimeDigitized", 0x9101: "ComponentsConfiguration",
    0x9102: "CompressedBitsPerPixel", 0x9201: "ShutterSpeedValue",
    0x9202: "ApertureValue", 0x9203: "BrightnessValue",
    0x9204: "ExposureBiasValue", 0x9205: "MaxApertureValue",
    0x9206: "SubjectDistance", 0x9207: "MeteringMode", 0x9208: "LightSource",
    0x9209: "Flash", 0x920A: "FocalLength", 0x9214: "SubjectArea",
    0x927C: "MakerNote", 0x9286: "UserComment", 0x9290: "SubSecTime",
    0x9291: "SubSecTimeOriginal", 0x9292: "SubSecTimeDigitized",
    0x9400: "Temperature", 0x9401: "Humidity", 0x9402: "Pressure",
    0x9403: "WaterDepth", 0x9404: "Acceleration",
    0x9405: "CameraElevationAngle", 0xA000: "FlashpixVersion",
    0xA001: "ColorSpace", 0xA002: "PixelXDimension", 0xA003: "PixelYDimension",
    0xA004: "RelatedSoundFile", 0xA005: "InteroperabilityIFDPointer",
    0xA20B: "FlashEnergy", 0xA20C: "SpatialFrequencyResponse",
    0xA20E: "FocalPlaneXResolution", 0xA20F: "FocalPlaneYResolution",
    0xA210: "FocalPlaneResolutionUnit", 0xA214: "SubjectLocation",
    0xA215: "ExposureIndex", 0xA217: "SensingMethod", 0xA300: "FileSource",
    0xA301: "SceneType", 0xA302: "CFAPattern", 0xA401: "CustomRendered",
    0xA402: "ExposureMode", 0xA403: "WhiteBalance",
    0xA404: "DigitalZoomRatio", 0xA405: "FocalLengthIn35mmFilm",
    0xA406: "SceneCaptureType", 0xA407: "GainControl", 0xA408: "Contrast",
    0xA409: "Saturation", 0xA40A: "Sharpness",
    0xA40B: "DeviceSettingDescription", 0xA40C: "SubjectDistanceRange",
    0xA420: "ImageUniqueID", 0xA430: "CameraOwnerName",
    0xA431: "BodySerialNumber", 0xA432: "LensSpecification",
    0xA433: "LensMake", 0xA434: "LensModel", 0xA435: "LensSerialNumber",
    0xA500: "Gamma",
}

GPS_TAGS = {  # GPS Info IFD [Exif §4.6.6]
    0x00: "GPSVersionID", 0x01: "GPSLatitudeRef", 0x02: "GPSLatitude",
    0x03: "GPSLongitudeRef", 0x04: "GPSLongitude", 0x05: "GPSAltitudeRef",
    0x06: "GPSAltitude", 0x07: "GPSTimeStamp", 0x08: "GPSSatellites",
    0x09: "GPSStatus", 0x0A: "GPSMeasureMode", 0x0B: "GPSDOP",
    0x0C: "GPSSpeedRef", 0x0D: "GPSSpeed", 0x0E: "GPSTrackRef",
    0x0F: "GPSTrack", 0x10: "GPSImgDirectionRef", 0x11: "GPSImgDirection",
    0x12: "GPSMapDatum", 0x13: "GPSDestLatitudeRef", 0x14: "GPSDestLatitude",
    0x15: "GPSDestLongitudeRef", 0x16: "GPSDestLongitude",
    0x17: "GPSDestBearingRef", 0x18: "GPSDestBearing",
    0x19: "GPSDestDistanceRef", 0x1A: "GPSDestDistance",
    0x1B: "GPSProcessingMethod", 0x1C: "GPSAreaInformation",
    0x1D: "GPSDateStamp", 0x1E: "GPSDifferential",
    0x1F: "GPSHPositioningError",
}

INTEROP_TAGS = {  # Interoperability IFD [Exif §4.6.7]
    0x0001: "InteroperabilityIndex",
}

TAGS_BY_IFD = {
    "0th": TIFF_TAGS, "1st": TIFF_TAGS, "exif": EXIF_TAGS,
    "gps": GPS_TAGS, "interoperability": INTEROP_TAGS,
}


def tag_name(ifd: str, tag: int) -> str:
    return TAGS_BY_IFD[ifd].get(tag, f"Tag 0x{tag:04X}")


# --------------------------------------------------------------------------
# Enumerations [Exif §4.6.4, §4.6.5, §4.6.6]
# --------------------------------------------------------------------------

ENUMS = {
    # Orientation: position of the 0th row and 0th column (top-left = normal)
    "Orientation": {1: "top-left", 2: "top-right", 3: "bottom-right",
                    4: "bottom-left", 5: "left-top", 6: "right-top",
                    7: "right-bottom", 8: "left-bottom"},
    "ResolutionUnit": {2: "inches", 3: "centimeters"},
    "FocalPlaneResolutionUnit": {2: "inches", 3: "centimeters"},
    "YCbCrPositioning": {1: "centered", 2: "co-sited"},
    "Compression": {1: "uncompressed", 6: "JPEG compression (thumbnails only)"},
    "PhotometricInterpretation": {2: "RGB", 6: "YCbCr"},
    "PlanarConfiguration": {1: "chunky format", 2: "planar format"},
    "ExposureProgram": {
        0: "Not defined", 1: "Manual", 2: "Normal program",
        3: "Aperture priority", 4: "Shutter priority",
        5: "Creative program (biased toward depth of field)",
        6: "Action program (biased toward fast shutter speed)",
        7: "Portrait mode", 8: "Landscape mode"},
    "SensitivityType": {
        0: "Unknown", 1: "Standard output sensitivity (SOS)",
        2: "Recommended exposure index (REI)", 3: "ISO speed",
        4: "SOS and REI", 5: "SOS and ISO speed", 6: "REI and ISO speed",
        7: "SOS and REI and ISO speed"},
    "MeteringMode": {0: "unknown", 1: "Average", 2: "CenterWeightedAverage",
                     3: "Spot", 4: "MultiSpot", 5: "Pattern", 6: "Partial",
                     255: "other"},
    "LightSource": {
        0: "unknown", 1: "Daylight", 2: "Fluorescent",
        3: "Tungsten (incandescent light)", 4: "Flash", 9: "Fine weather",
        10: "Cloudy weather", 11: "Shade",
        12: "Daylight fluorescent (D 5700 - 7100K)",
        13: "Day white fluorescent (N 4600 - 5500K)",
        14: "Cool white fluorescent (W 3800 - 4500K)",
        15: "White fluorescent (WW 3250 - 3800K)",
        16: "Warm white fluorescent (L 2600 - 3250K)",
        17: "Standard light A", 18: "Standard light B", 19: "Standard light C",
        20: "D55", 21: "D65", 22: "D75", 23: "D50",
        24: "ISO studio tungsten", 255: "other light source"},
    "ColorSpace": {1: "sRGB", 0xFFFF: "Uncalibrated"},
    "SensingMethod": {1: "Not defined", 2: "One-chip color area sensor",
                      3: "Two-chip color area sensor",
                      4: "Three-chip color area sensor",
                      5: "Color sequential area sensor", 7: "Trilinear sensor",
                      8: "Color sequential linear sensor"},
    "FileSource": {0: "others", 1: "scanner of transparent type",
                   2: "scanner of reflex type", 3: "DSC"},
    "SceneType": {1: "A directly photographed image"},
    "CustomRendered": {0: "Normal process", 1: "Custom process"},
    "ExposureMode": {0: "Auto exposure", 1: "Manual exposure",
                     2: "Auto bracket"},
    "WhiteBalance": {0: "Auto white balance", 1: "Manual white balance"},
    "SceneCaptureType": {0: "Standard", 1: "Landscape", 2: "Portrait",
                         3: "Night scene"},
    "GainControl": {0: "None", 1: "Low gain up", 2: "High gain up",
                    3: "Low gain down", 4: "High gain down"},
    "Contrast": {0: "Normal", 1: "Soft", 2: "Hard"},
    "Saturation": {0: "Normal", 1: "Low saturation", 2: "High saturation"},
    "Sharpness": {0: "Normal", 1: "Soft", 2: "Hard"},
    "SubjectDistanceRange": {0: "unknown", 1: "Macro", 2: "Close view",
                             3: "Distant view"},
    "GPSAltitudeRef": {0: "above sea level", 1: "below sea level"},
}

COMPONENTS = {0: "-", 1: "Y", 2: "Cb", 3: "Cr", 4: "R", 5: "G", 6: "B"}

BINARY_HEAD = 16  # bytes shown for a long binary value

# --------------------------------------------------------------------------
# Generic conversion
# --------------------------------------------------------------------------

ASCII, BYTE, UNDEFINED, UTF8 = 2, 1, 7, 129
RATIONAL_TYPES = (5, 10)


TEXT_HEAD = 1000      # characters shown for a long text (README, Design choices)
XMP_HEAD = 64 * 1024  # XMP: the size of a whole JPEG segment, i.e. all of it


def text_value(text: str, capped: bool = False, limit: int = TEXT_HEAD):
    """A text as is, or abbreviated if longer than `limit` characters.

    `capped` means the text was cut while being decompressed (zip bomb
    protection): its real length is unknown, at least len(text).
    """
    if len(text) <= limit and not capped:
        return text
    result = {"length": len(text), "head": text[:limit], "truncated": True}
    if capped:
        result["decompression_limit_reached"] = True
    return result


def decode_text(raw: bytes):
    """ASCII (or UTF-8) value: NUL-terminated; several strings if several NULs."""
    parts = [p.decode("utf-8", "replace").strip()
             for p in raw.split(b"\x00")]
    parts = [text_value(p) for p in parts if p]
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else parts


def binary(raw: bytes):
    """Short binary values in full (hex), long ones abbreviated."""
    if len(raw) <= BINARY_HEAD:
        return raw.hex()
    return {"size": len(raw), "head": raw[:BINARY_HEAD].hex()}


def as_float(r: tuple[int, int]) -> float | None:
    return None if r[1] == 0 else r[0] / r[1]


def fmt_number(x: float, digits: int = 6) -> str:
    return f"{round(x, digits):g}"


def rational_text(r: tuple[int, int]) -> str:
    value = as_float(r)
    return f"undefined ({r[0]}/0)" if value is None else fmt_number(value)


def one(values):
    """A single value as itself, several as a list."""
    return values[0] if len(values) == 1 else list(values)


def raw_json(type_code: int, values):
    """The value as stored, in JSON terms."""
    if type_code in RATIONAL_TYPES:
        return one([list(r) for r in values])
    if isinstance(values, bytes):
        return values.hex()
    return one(values)


def convert(ifd: str, name: str, type_code: int, values, ifd_values: dict):
    """JSON value of one tag. `ifd_values` gives the other raw values of the
    same IFD (e.g. GPSLatitudeRef, needed to convert GPSLatitude)."""
    special = CONVERTERS.get(name)
    if special is not None:
        try:
            result = special(type_code, values, ifd_values)
        except (TypeError, ValueError, IndexError, ZeroDivisionError):
            result = None  # unexpected shape: fall back to the generic form
        if result is not None:
            return result

    if type_code in (ASCII, UTF8):
        return decode_text(values)
    if type_code in (BYTE, UNDEFINED):
        return binary(values)
    if name in ENUMS and isinstance(values, tuple) and len(values) == 1:
        return {"raw": values[0],
                "text": ENUMS[name].get(values[0], "reserved")}
    if type_code in RATIONAL_TYPES:
        if len(values) == 1:
            return {"raw": list(values[0]), "text": rational_text(values[0])}
        return {"raw": [list(r) for r in values],
                "text": ", ".join(rational_text(r) for r in values)}
    return one(values)


# --------------------------------------------------------------------------
# Tag-specific conversions (return None to use the generic form)
# --------------------------------------------------------------------------

def _version(type_code, values, _):
    if not isinstance(values, bytes) or len(values) != 4:
        return None
    text = values.decode("ascii", "replace")
    return {"raw": text, "text": f"{int(text[:2])}.{text[2:]}"
            if text.isdigit() else text}


def _components(type_code, values, _):
    if not isinstance(values, bytes):
        return None
    return {"raw": list(values),
            "text": " ".join(COMPONENTS.get(b, "?") for b in values)}


def _one_byte_enum(name):
    def conv(type_code, values, _):
        if isinstance(values, bytes) and len(values) == 1:
            return {"raw": values[0],
                    "text": ENUMS[name].get(values[0], "reserved")}
        return None
    return conv


def _flash(type_code, values, _):
    """Bit field [Exif §4.6.5, Figure 16]."""
    v = values[0]
    parts = ["fired" if v & 0x01 else "did not fire"]
    parts.append({0: None, 1: "mode: compulsory firing",
                  2: "mode: compulsory suppression",
                  3: "mode: auto"}[(v >> 3) & 0x03] or "mode: unknown")
    ret = (v >> 1) & 0x03
    if ret == 2:
        parts.append("return light not detected")
    elif ret == 3:
        parts.append("return light detected")
    if v & 0x20:
        parts.append("no flash function")
    if v & 0x40:
        parts.append("red-eye reduction")
    return {"raw": v, "text": ", ".join(parts)}


def _exposure_time(type_code, values, _):
    n, d = values[0]
    if n == 0 or d == 0:
        return None
    if Fraction(n, d) < 1 and d % n == 0:
        text = f"1/{d // n} s"
    elif Fraction(n, d) < 1:
        text = f"{fmt_number(n / d)} s (≈ 1/{round(d / n)} s)"
    else:
        text = f"{fmt_number(n / d)} s"
    return {"raw": [n, d], "text": text}


def _fnumber(type_code, values, _):
    value = as_float(values[0])
    return None if value is None else {"raw": list(values[0]),
                                       "text": f"f/{value:.1f}"}


def _apex_aperture(type_code, values, _):
    """ApertureValue / MaxApertureValue in APEX: f-number = 2^(value/2)."""
    value = as_float(values[0])
    if value is None:
        return None
    return {"raw": list(values[0]),
            "text": f"{fmt_number(value)} APEX (f/{2 ** (value / 2):.1f})"}


def _apex_shutter(type_code, values, _):
    """ShutterSpeedValue in APEX: exposure time = 2^-value seconds."""
    value = as_float(values[0])
    if value is None:
        return None
    seconds = 2 ** -value
    readable = f"1/{round(1 / seconds)} s" if seconds < 1 else \
        f"{fmt_number(seconds)} s"
    return {"raw": list(values[0]),
            "text": f"{fmt_number(value)} APEX ({readable})"}


def _unit(unit: str, signed: bool = False):
    def conv(type_code, values, _):
        if len(values) != 1:
            return None
        value = as_float(values[0])
        if value is None:
            return None
        number = f"{value:+.2f}" if signed else fmt_number(value)
        return {"raw": list(values[0]), "text": f"{number} {unit}".strip()}
    return conv


def _subject_distance(type_code, values, _):
    n, d = values[0]
    if n == 0xFFFFFFFF:
        text = "infinity"
    elif n == 0:
        text = "unknown"
    elif d == 0:
        return None
    else:
        text = f"{fmt_number(n / d)} m"
    return {"raw": [n, d], "text": text}


def _gps_coordinate(ref_tag: int):
    """GPSLatitude & co: 3 rationals (degrees, minutes, seconds) + a ref."""
    def conv(type_code, values, ifd_values):
        if len(values) != 3:
            return None
        d, m, s = (as_float(r) for r in values)
        if None in (d, m, s):
            return None
        ref = ifd_values.get(ref_tag, b"")
        ref = ref.decode("ascii", "replace").strip("\x00 ") \
            if isinstance(ref, bytes) else ""
        decimal = d + m / 60 + s / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        text = f"{int(d)}° {int(m)}' {s:.2f}\" {ref}".strip()
        return {"raw": [list(r) for r in values], "text": text,
                "decimal": round(decimal, 6)}
    return conv


def _gps_altitude(type_code, values, ifd_values):
    value = as_float(values[0])
    if value is None:
        return None
    ref = ifd_values.get(0x05)
    below = isinstance(ref, bytes) and ref[:1] == b"\x01"
    side = "below" if below else "above"
    return {"raw": list(values[0]),
            "text": f"{fmt_number(value)} m {side} sea level"}


def _gps_time(type_code, values, _):
    if len(values) != 3:
        return None
    h, m, s = (as_float(r) for r in values)
    if None in (h, m, s):
        return None
    return {"raw": [list(r) for r in values],
            "text": f"{int(h):02d}:{int(m):02d}:{s:05.2f} UTC"}


CHARACTER_CODES = {  # 8-byte header of UserComment & co [Exif §4.6.5]
    b"ASCII\x00\x00\x00": "ASCII",
    b"UNICODE\x00": "Unicode",
    b"JIS\x00\x00\x00\x00\x00": "JIS",
    b"\x00" * 8: "Undefined",
}


def _encoded_text(type_code, values, ifd_values):
    """UserComment, GPSProcessingMethod, GPSAreaInformation: 8-byte character
    code, then the text. Falls back to the generic (hex) form if the text
    cannot be decoded reliably."""
    if not isinstance(values, bytes) or len(values) < 8:
        return None
    encoding = CHARACTER_CODES.get(values[:8])
    body = values[8:]
    text = None
    try:
        if encoding == "ASCII":
            text = body.decode("ascii")
        elif encoding == "Unicode":
            # UTF-16, in the byte order of the file (II / MM).
            big = ifd_values.get(BYTE_ORDER_KEY) == "MM"
            text = body.decode("utf-16-be" if big else "utf-16-le")
        elif encoding == "JIS":
            # JIS X 0208 two-byte codes, read through ISO-2022-JP escapes.
            text = (b"\x1b$B" + body + b"\x1b(B").decode("iso2022_jp")
        elif encoding == "Undefined":
            text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is None:
        return None
    text = text.strip("\x00 ")
    if any(not (c.isprintable() or c in "\n\r\t") for c in text):
        return None  # not readable text: keep the generic (hex) form
    return {"raw": binary(values), "encoding": encoding,
            "text": text_value(text)}


# Key under which exif.py passes the byte order ("II" / "MM") in ifd_values
# (a string, so it can never collide with a tag number).
BYTE_ORDER_KEY = "byte_order"


def _gps_version(type_code, values, _):
    if isinstance(values, bytes) and len(values) == 4:
        return {"raw": list(values), "text": ".".join(str(b) for b in values)}
    return None


CONVERTERS = {
    "ExifVersion": _version, "FlashpixVersion": _version,
    "ComponentsConfiguration": _components,
    "FileSource": _one_byte_enum("FileSource"),
    "SceneType": _one_byte_enum("SceneType"),
    "GPSAltitudeRef": _one_byte_enum("GPSAltitudeRef"),
    "Flash": _flash,
    "ExposureTime": _exposure_time,
    "FNumber": _fnumber,
    "ApertureValue": _apex_aperture, "MaxApertureValue": _apex_aperture,
    "ShutterSpeedValue": _apex_shutter,
    "BrightnessValue": _unit("APEX"),
    "ExposureBiasValue": _unit("EV", signed=True),
    "FocalLength": _unit("mm"),
    "SubjectDistance": _subject_distance,
    "GPSLatitude": _gps_coordinate(0x01), "GPSLongitude": _gps_coordinate(0x03),
    "GPSDestLatitude": _gps_coordinate(0x13),
    "GPSDestLongitude": _gps_coordinate(0x15),
    "GPSAltitude": _gps_altitude,
    "GPSTimeStamp": _gps_time,
    "GPSVersionID": _gps_version,
    "UserComment": _encoded_text,
    "GPSProcessingMethod": _encoded_text,
    "GPSAreaInformation": _encoded_text,
}

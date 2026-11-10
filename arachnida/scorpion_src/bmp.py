"""BMP: file header and DIB header (Microsoft BITMAPFILEHEADER,
BITMAPCOREHEADER / BITMAPINFOHEADER / V4 / V5). Little endian; no Exif.
"""

import struct

DIB_HEADERS = {12: "BITMAPCOREHEADER", 40: "BITMAPINFOHEADER",
               52: "BITMAPV2INFOHEADER", 56: "BITMAPV3INFOHEADER",
               108: "BITMAPV4HEADER", 124: "BITMAPV5HEADER"}
COMPRESSIONS = {0: "none (BI_RGB)", 1: "RLE 8-bit (BI_RLE8)",
                2: "RLE 4-bit (BI_RLE4)", 3: "bit fields (BI_BITFIELDS)",
                4: "JPEG (BI_JPEG)", 5: "PNG (BI_PNG)",
                6: "alpha bit fields (BI_ALPHABITFIELDS)"}


def parse_bmp(data: bytes) -> dict:
    warnings: list[str] = []
    if len(data) < 18:
        return {"image": None, "warnings": ["truncated header"]}

    declared_size, pixel_offset, dib_size = struct.unpack_from("<I4xII", data, 2)
    result: dict = {"declared_file_size": declared_size,
                    "pixel_data_offset": pixel_offset,
                    "dib_header": DIB_HEADERS.get(dib_size,
                                                  f"unknown ({dib_size} bytes)"),
                    "image": None}
    if declared_size != len(data):
        warnings.append(f"declared size {declared_size} differs from the "
                        f"actual size {len(data)}")

    if dib_size == 12 and len(data) >= 26:
        w, h, planes, bpp = struct.unpack_from("<HHHH", data, 18)
        result["image"] = {"width": w, "height": h, "bits_per_pixel": bpp}
    elif dib_size >= 40 and len(data) >= 54:
        (w, h, planes, bpp, compression, image_size, xppm, yppm, colors,
         _important) = struct.unpack_from("<iiHHIIiiII", data, 18)
        result["image"] = {
            "width": w, "height": abs(h),
            "row_order": "top-down" if h < 0 else "bottom-up",
            "bits_per_pixel": bpp,
            "compression": COMPRESSIONS.get(compression,
                                            f"unknown ({compression})"),
            "colors_used": colors or None}
        if xppm > 0 and yppm > 0:
            result["resolution"] = {
                "raw": [xppm, yppm, "pixels per metre"],
                "text": f"{round(xppm * 0.0254)} x {round(yppm * 0.0254)} dpi"}
    else:
        warnings.append("DIB header unreadable or truncated")

    if warnings:
        result["warnings"] = warnings
    return result

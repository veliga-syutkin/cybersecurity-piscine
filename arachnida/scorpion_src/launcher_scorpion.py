"""Entry point of scorpion: displays the metadata of image files, as JSON.

Usage: ./scorpion FILE1 [FILE2 ...]

Output: one JSON array on stdout, one object per file, in the order of the
arguments (see README, Design choices). Errors also go to stderr.

Exit codes:
    0   every file could be read (a file without metadata is not a failure)
    1   at least one file failed (the others are still processed)
    2   usage error (invalid arguments)
    130 interrupted by the user (Ctrl-C)
"""

import argparse
import json
import sys

from bmp import parse_bmp
from common.formats import (BMP, GIF, HEADER_SIZE, JPEG, PNG, detect_format,
                            extension_of, format_from_extension)
from fileinfo import file_attributes
from gif import parse_gif
from jpeg import parse_jpeg
from png import parse_png

PROG = "scorpion"
EXIT_OK, EXIT_FAILURE, EXIT_INTERRUPTED = 0, 1, 130
PARSERS = {JPEG: parse_jpeg, PNG: parse_png, GIF: parse_gif, BMP: parse_bmp}


class FileError(Exception):
    """The file cannot be processed; the message goes to the JSON and stderr."""


def creation_date(attributes: dict, details: dict) -> dict:
    """Best "creation date": Exif DateTimeOriginal first, else birth time."""
    exif = details.get("exif") or {}
    exif_ifd = exif.get("ifds", {}).get("exif", {})
    original = exif_ifd.get("DateTimeOriginal")
    if isinstance(original, str) and original.strip(": "):
        offset = exif_ifd.get("OffsetTimeOriginal")
        value = original
        if isinstance(offset, str) and offset.strip(": "):
            value += f" {offset}"
        return {"value": value,
                "source": "Exif DateTimeOriginal (camera clock"
                          + (")" if value == original else ", with UTC offset)")}
    birth = attributes["dates"]["birth"]
    if birth is not None:
        return {"value": birth, "source": "filesystem birth time"}
    return {"value": None, "source": None}


def describe_file(path: str) -> dict:
    """JSON object for one file. Raises FileError if it cannot be processed."""
    try:
        attributes = file_attributes(path)
        with open(path, "rb") as f:
            data = f.read()
    except IsADirectoryError:
        raise FileError("is a directory")
    except FileNotFoundError:
        raise FileError("no such file")
    except PermissionError:
        raise FileError("permission denied")
    except OSError as exc:
        raise FileError(exc.strerror or str(exc))

    real = detect_format(data[:HEADER_SIZE])
    announced = format_from_extension(path)
    warnings: list[str] = []

    # Signature vs extension (README, Design choices, scorpion).
    if real is None and announced is not None:
        raise FileError(f"content is not a valid {announced.name}")
    if real is None:
        raise FileError("not supported (unknown extension and content)")
    if announced is not None and announced != real:
        warnings.append(f"extension {extension_of(path)} but the content is "
                        f"{real.name}: processed as {real.name}")

    details = PARSERS[real](data)
    warnings += details.pop("warnings", [])

    entry = {"file": path, "format": real.name}
    entry["filesystem"] = attributes
    entry["creation_date"] = creation_date(attributes, details)
    entry.update(details)
    if warnings:
        entry["warnings"] = warnings
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Display the metadata (filesystem, Exif...) of image files "
                    "as JSON.")
    parser.add_argument("files", metavar="FILE", nargs="+",
                        help="image file (.jpg/.jpeg, .png, .gif, .bmp)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    entries = []
    status = EXIT_OK
    try:
        for path in args.files:
            try:
                entries.append(describe_file(path))
            except FileError as exc:
                entries.append({"file": path, "error": str(exc)})
                print(f"{PROG}: {path}: {exc}", file=sys.stderr)
                status = EXIT_FAILURE
    except KeyboardInterrupt:
        print(f"\n{PROG}: error: interrupted by user", file=sys.stderr)
        return EXIT_INTERRUPTED

    print(json.dumps(entries, indent=2, ensure_ascii=False))
    return status


if __name__ == "__main__":
    sys.exit(main())

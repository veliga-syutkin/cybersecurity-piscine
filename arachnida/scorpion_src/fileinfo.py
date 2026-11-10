"""Filesystem attributes of a file ("basic attributes" of the subject).

Size, permissions, owner, group, and four dates (see README, Design choices):
    birth     creation of the file (null when unavailable)
    modified  last change of the content         (st_mtime)
    changed   last change of the inode metadata  (st_ctime) — NOT the creation
    accessed  last access                        (st_atime)

Python 3.12 has no birth time on Linux: it is read with the statx() system
call through ctypes (glibc >= 2.28). On macOS, os.stat() provides it.
"""

import ctypes
import grp
import os
import pwd
import stat
import struct
import sys
from datetime import datetime

AT_FDCWD = -100
STATX_BTIME = 0x800
STATX_BUFFER_SIZE = 256   # sizeof(struct statx)
STX_MASK_OFFSET = 0       # __u32 stx_mask
STX_BTIME_OFFSET = 80     # struct statx_timestamp stx_btime {s64 sec; u32 nsec}

_statx = None
if sys.platform.startswith("linux"):
    try:
        _libc = ctypes.CDLL(None, use_errno=True)
        _statx = _libc.statx
        _statx.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_uint, ctypes.c_void_p)
        _statx.restype = ctypes.c_int
    except (OSError, AttributeError):  # no libc symbol (old glibc, musl...)
        _statx = None


def birth_time(path: str, st: os.stat_result) -> float | None:
    """Creation time as a timestamp, or None if the system does not give it."""
    if hasattr(st, "st_birthtime"):  # macOS, BSD
        return st.st_birthtime
    if _statx is None:
        return None
    buffer = ctypes.create_string_buffer(STATX_BUFFER_SIZE)
    if _statx(AT_FDCWD, os.fsencode(path), 0, STATX_BTIME, buffer) != 0:
        return None
    mask = struct.unpack_from("<I", buffer.raw, STX_MASK_OFFSET)[0] \
        if sys.byteorder == "little" else \
        struct.unpack_from(">I", buffer.raw, STX_MASK_OFFSET)[0]
    if not mask & STATX_BTIME:  # the filesystem does not store it
        return None
    order = "<" if sys.byteorder == "little" else ">"
    seconds, nanoseconds = struct.unpack_from(f"{order}qI", buffer.raw,
                                              STX_BTIME_OFFSET)
    return seconds + nanoseconds / 1e9


def iso(timestamp: float | None) -> str | None:
    """Local date and time with its UTC offset, e.g. 2026-09-18T10:30:13+02:00."""
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp).astimezone() \
        .isoformat(timespec="seconds")


def name_of(lookup, number: int) -> str | None:
    try:
        return lookup(number)[0]
    except KeyError:  # no such user / group on this system
        return None


def file_attributes(path: str) -> dict:
    """Raises OSError if the file cannot be stat'ed."""
    st = os.stat(path)
    return {
        "size": st.st_size,
        "permissions": {"text": stat.filemode(st.st_mode),
                        "octal": f"{stat.S_IMODE(st.st_mode):o}"},
        "owner": {"name": name_of(pwd.getpwuid, st.st_uid), "uid": st.st_uid},
        "group": {"name": name_of(grp.getgrgid, st.st_gid), "gid": st.st_gid},
        "dates": {
            "birth": iso(birth_time(path, st)),
            "modified": iso(st.st_mtime),
            "changed": iso(st.st_ctime),
            "accessed": iso(st.st_atime),
        },
    }

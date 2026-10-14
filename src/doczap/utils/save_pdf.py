"""Publish a completed PDF without copying over a user's existing file."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path

from doczap.utils.file_ops import validate_output_path


def rename_without_replace(source: Path, destination: Path) -> None:
    """Use the OS's exclusive rename, or an exclusive hard link as a fallback.

    The caller stages the file on the destination filesystem. No path here
    checks existence and then performs a replacing rename or copy.
    """
    if sys.platform == "win32":
        # Windows rename fails if the destination already exists, including on
        # FAT/exFAT where hard links are unavailable.
        os.rename(source, destination)
        return

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = getattr(libc, "renamex_np", None)
        if rename is not None:
            rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            result = rename(os.fsencode(source), os.fsencode(destination), 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is not None:
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # RENAME_NOREPLACE
    else:
        rename = None

    if rename is not None:
        if result == 0:
            return
        error = ctypes.get_errno()
        if error not in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
            raise OSError(error, os.strerror(error), str(destination))

    # Hard-link creation also fails atomically if the name exists. The staged
    # link is removed with its temporary directory after publication. If the
    # filesystem supports neither operation, fail without weakening safety.
    try:
        os.link(source, destination)
    except OSError as exc:
        if exc.errno in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EPERM}:
            raise OSError(
                exc.errno,
                "This filesystem cannot safely create the PDF without replacement. "
                "Choose another output folder.",
                str(destination),
            ) from exc
        raise


def save_pdf(
    produced: Path, destination: Path, *, input_path: Path, overwrite: bool
) -> None:
    """Validate again after rendering, then publish the complete PDF atomically."""
    validate_output_path(destination, overwrite=overwrite, input_path=input_path)
    if overwrite:
        # replace changes the directory entry; it never writes through an
        # output symlink or truncates a file before the complete PDF is ready.
        os.replace(produced, destination)
    else:
        rename_without_replace(produced, destination)

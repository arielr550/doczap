"""Operating-system specific details, kept in one place.

Everything that differs between macOS, Linux and Windows lives here so the
converters and front ends stay platform-neutral.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import IO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

APP_NAME = "doczap"


def soffice_candidates(platform: str = sys.platform) -> list[Path]:
    """Standard LibreOffice install locations to try when soffice is not on PATH."""
    if platform == "darwin":
        # LibreOffice's .dmg installer does not put soffice on PATH.
        return [
            Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
            Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice",
        ]
    if platform == "win32":
        roots = [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")]
        return [
            Path(root) / "LibreOffice" / "program" / "soffice.exe" for root in roots if root
        ]
    # The official .deb and .rpm packages install into a versioned /opt directory.
    return [
        Path("/usr/lib/libreoffice/program/soffice"),
        *sorted(Path("/opt").glob("libreoffice*/program/soffice"), reverse=True),
    ]


def cache_dir(platform: str = sys.platform) -> Path:
    """Per-user cache directory for DocZap."""
    if platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / APP_NAME


def try_lock(file: IO[str]) -> bool:
    """Take an exclusive lock on an open file without waiting.

    The lock is released when the file is closed.
    """
    try:
        if sys.platform == "win32":
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True

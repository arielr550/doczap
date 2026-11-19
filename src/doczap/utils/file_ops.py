from __future__ import annotations

import stat
from pathlib import Path

SUPPORTED_INPUTS = {".docx"}

# Device, inode, size and modification time: enough to tell that the file at a
# path is still the one the user agreed to replace.
FileIdentity = tuple[int, int, int, int]


def file_identity(path: Path) -> FileIdentity | None:
    """Identify the directory entry at path, without following a symlink. None if absent."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def validate_input_path(input_path: Path) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"Input path is not a file: {input_path}")


def validate_output_path(
    output_path: Path, overwrite: bool, *, input_path: Path | None = None
) -> None:
    if output_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Output must be a .pdf file, got: '{output_path.suffix or '<no suffix>'}'"
        )

    parent = output_path.parent
    if not parent.exists():
        raise FileNotFoundError(f"Output directory does not exist: {parent}")
    if not parent.is_dir():
        raise ValueError(f"Output parent path is not a directory: {parent}")

    try:
        info = output_path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        raise ValueError(f"Output path is a symbolic link: {output_path}. Choose another PDF path.")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Output path is not a regular file: {output_path}")
    if input_path is not None and output_path.samefile(input_path):
        raise ValueError(f"Output refers to the source document: {output_path}")
    if not overwrite:
        raise FileExistsError(
            f"Output file already exists: {output_path}. Use --overwrite to replace it."
        )


def ensure_supported_input(input_path: Path) -> None:
    ext = input_path.suffix.lower()
    if ext not in SUPPORTED_INPUTS:
        supported = ", ".join(sorted(SUPPORTED_INPUTS))
        raise ValueError(f"Unsupported input format '{ext or '<no suffix>'}'. Supported: {supported}")

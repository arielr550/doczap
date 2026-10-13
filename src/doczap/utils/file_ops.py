from __future__ import annotations

from pathlib import Path

SUPPORTED_INPUTS = {".docx"}


def validate_input_path(input_path: Path) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"Input path is not a file: {input_path}")


def validate_output_path(output_path: Path, overwrite: bool) -> None:
    if output_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Output must be a .pdf file, got: '{output_path.suffix or '<no suffix>'}'"
        )

    parent = output_path.parent
    if not parent.exists():
        raise FileNotFoundError(f"Output directory does not exist: {parent}")
    if not parent.is_dir():
        raise ValueError(f"Output parent path is not a directory: {parent}")

    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {output_path}. Use --overwrite to replace it."
        )


def ensure_supported_input(input_path: Path) -> None:
    ext = input_path.suffix.lower()
    if ext not in SUPPORTED_INPUTS:
        supported = ", ".join(sorted(SUPPORTED_INPUTS))
        raise ValueError(f"Unsupported input format '{ext or '<no suffix>'}'. Supported: {supported}")

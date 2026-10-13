from __future__ import annotations

from pathlib import Path

from doczap.converters.base import Converter
from doczap.converters.libreoffice import LibreOfficeConverter
from doczap.utils.file_ops import ensure_supported_input, validate_input_path, validate_output_path


def default_output_path(input_path: Path) -> Path:
    """Return the PDF path users normally expect: beside the source document."""
    return input_path.with_suffix(".pdf")


def select_converter(input_path: Path, output_path: Path) -> Converter:
    if input_path.suffix.lower() == ".docx" and output_path.suffix.lower() == ".pdf":
        return LibreOfficeConverter()
    raise ValueError(
        f"Unsupported conversion: {input_path.suffix or '<no suffix>'} -> "
        f"{output_path.suffix or '<no suffix>'}"
    )


def convert_document(
    input_file: str | Path,
    output_file: str | Path | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Validate and convert one document, returning the final PDF path."""
    input_path = Path(input_file).expanduser().resolve()
    output_path = (
        Path(output_file).expanduser().resolve()
        if output_file is not None
        else default_output_path(input_path)
    )

    validate_input_path(input_path)
    ensure_supported_input(input_path)
    validate_output_path(output_path, overwrite=overwrite)
    converter = select_converter(input_path, output_path)
    converter.convert(str(input_path), str(output_path))
    return output_path

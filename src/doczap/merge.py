"""Join PDFs into one, in the order given.

pypdf copies each page object as it is; nothing is re-rendered, so every page
looks exactly as it did in its own PDF.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import DependencyError, PyPdfError

from doczap.utils.file_ops import validate_input_path, validate_output_path
from doczap.utils.save_pdf import save_pdf


def read_pdf(path: Path) -> PdfReader:
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            # PDFs that only restrict printing or editing open with an empty password.
            try:
                opened = reader.decrypt("")
            except DependencyError:
                # AES needs a crypto library that DocZap does not bundle.
                raise ValueError(
                    f"{path.name} is encrypted in a way DocZap cannot open. Remove the protection first."
                ) from None
            if not opened:
                raise ValueError(f"{path.name} is password-protected. Remove the password first.")
        # Load the page tree now, so a broken PDF fails before anything is written.
        len(reader.pages)
    except PyPdfError as exc:
        raise ValueError(f"{path.name} is not a readable PDF ({exc}).") from exc
    return reader


def check_destination(destination: Path, sources: list[Path], *, overwrite: bool) -> None:
    for source in sources:
        validate_output_path(destination, overwrite=overwrite, input_path=source)


def merge_pdfs(
    sources: Iterable[str | Path], destination: str | Path, *, overwrite: bool = False
) -> int:
    """Write the pages of each source, in order, to destination. Returns the page count."""
    source_paths = [Path(source).expanduser().resolve() for source in sources]
    output = Path(destination).expanduser()
    # Keep the final component unresolved so validation can reject output symlinks.
    output = output.parent.resolve() / output.name
    if len(source_paths) < 2:
        raise ValueError("Choose at least two PDFs to merge.")
    for source in source_paths:
        validate_input_path(source)
        if source.suffix.lower() != ".pdf":
            raise ValueError(f"{source.name} is not a PDF.")
    check_destination(output, source_paths, overwrite=overwrite)

    writer = PdfWriter()
    for source in source_paths:
        writer.append(read_pdf(source))
    pages = len(writer.pages)

    # Stage beside the destination, then publish the complete file in one step,
    # so a failure never leaves a half-written PDF or damages an existing one.
    with tempfile.TemporaryDirectory(prefix=".doczap_", dir=output.parent) as temp_dir:
        staged = Path(temp_dir) / output.name
        with staged.open("wb") as staged_file:
            writer.write(staged_file)
        writer.close()
        check_destination(output, source_paths, overwrite=overwrite)
        save_pdf(staged, output, input_path=source_paths[0], overwrite=overwrite)
    return pages

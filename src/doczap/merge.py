"""Join PDFs into one, in the order given.

pypdf copies each page object as it is; nothing is re-rendered, so every page
looks exactly as it did in its own PDF.

Layers (optional content) are the exception pypdf leaves to the caller: which
layers are shown lives in the document catalog, not on the pages, so it is
copied here. Without it a hidden layer would show in the merged PDF.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import DependencyError, PyPdfError
from pypdf.generic import ArrayObject, DictionaryObject, NameObject

from doczap.utils.file_ops import (
    FileIdentity,
    validate_input_path,
    validate_output_path,
)
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


def layer_settings(path: Path, reader: PdfReader) -> DictionaryObject | None:
    settings = reader.root_object.get("/OCProperties")
    if settings is None:
        return None
    settings = settings.get_object()
    if not isinstance(settings, DictionaryObject):
        raise ValueError(f"{path.name} has damaged layer settings, so DocZap cannot merge it.")
    return settings


def combine_layers(layered: list[tuple[Path, DictionaryObject]], writer: PdfWriter) -> DictionaryObject:
    """One default layer configuration that shows and hides each layer as its own PDF did.

    The writer has already copied the pages, so cloning maps each layer to the
    same object the pages now use.
    """

    def unsupported(path: Path, reason: str) -> ValueError:
        return ValueError(
            f"{path.name} {reason}, which DocZap cannot combine with layers from another PDF. "
            "Merge it with PDFs that have no layers, or flatten its layers first."
        )

    groups, off, order, radio, locked, auto = (ArrayObject() for _ in range(6))
    intents = set()
    for path, settings in layered:
        if "/Configs" in settings:
            raise unsupported(path, "has alternative layer configurations")
        config = settings.get("/D", DictionaryObject()).get_object()
        if not isinstance(config, DictionaryObject):
            raise unsupported(path, "has damaged layer settings")
        intent = config.get("/Intent", NameObject("/View")).get_object()
        intents.add(tuple(intent) if isinstance(intent, ArrayObject) else (intent,))
        if len(intents) > 1:
            raise unsupported(path, "uses a different layer intent")

        own = list(settings.get("/OCGs", ArrayObject()).get_object())
        base = config.get("/BaseState", "/ON")
        if base == "/OFF":
            # Every layer starts hidden; only the /ON list is shown.
            shown = list(config.get("/ON", ArrayObject()).get_object())
            hidden = [group for group in own if group not in shown]
        elif base == "/ON":
            hidden = list(config.get("/OFF", ArrayObject()).get_object())
        else:
            raise unsupported(path, "has an unusual default layer state")

        groups.extend(group.clone(writer) for group in own)
        off.extend(group.clone(writer) for group in hidden)
        for target, key in ((order, "/Order"), (radio, "/RBGroups"), (locked, "/Locked"), (auto, "/AS")):
            target.extend(item.clone(writer) for item in config.get(key, ArrayObject()).get_object())

    config = DictionaryObject({NameObject("/BaseState"): NameObject("/ON"), NameObject("/OFF"): off})
    intent = intents.pop()
    if intent != ("/View",):
        config[NameObject("/Intent")] = intent[0] if len(intent) == 1 else ArrayObject(intent)
    for key, items in (("/Order", order), ("/RBGroups", radio), ("/Locked", locked), ("/AS", auto)):
        if items:
            config[NameObject(key)] = items
    return DictionaryObject({NameObject("/OCGs"): groups, NameObject("/D"): config})


def copy_layers(sources: list[tuple[Path, PdfReader]], writer: PdfWriter) -> None:
    layered = [
        (path, settings) for path, reader in sources if (settings := layer_settings(path, reader)) is not None
    ]
    if not layered:
        return
    if len(layered) == 1:
        # Only one PDF has layers: its settings apply unchanged, alternatives included.
        merged = layered[0][1].clone(writer)
    else:
        merged = combine_layers(layered, writer)
    writer.root_object[NameObject("/OCProperties")] = writer._add_object(merged)


def merge_pdfs(
    sources: Iterable[str | Path],
    destination: str | Path,
    *,
    overwrite: bool = False,
    replace_only: FileIdentity | None = None,
) -> int:
    """Write the pages of each source, in order, to destination. Returns the page count.

    replace_only limits overwrite to the existing file with that identity.
    """
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
    readers = [(source, read_pdf(source)) for source in source_paths]
    for _, reader in readers:
        writer.append(reader)
    copy_layers(readers, writer)
    pages = len(writer.pages)

    # Stage beside the destination, then publish the complete file in one step,
    # so a failure never leaves a half-written PDF or damages an existing one.
    with tempfile.TemporaryDirectory(prefix=".doczap_", dir=output.parent) as temp_dir:
        staged = Path(temp_dir) / output.name
        with staged.open("wb") as staged_file:
            writer.write(staged_file)
        writer.close()
        check_destination(output, source_paths, overwrite=overwrite)
        save_pdf(
            staged, output, input_path=source_paths[0], overwrite=overwrite, replace_only=replace_only
        )
    return pages

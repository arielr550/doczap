from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    TextStringObject,
)

from doczap.merge import merge_pdfs
from doczap.utils.file_ops import file_identity


def write_pdf(
    path: Path, *widths: int, password: str | None = None, owner_password: str | None = None
) -> Path:
    """A PDF with one blank page per width, so page order can be read back."""
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=100)
    if password is not None:
        writer.encrypt(password, owner_password, algorithm="RC4-128")
    with path.open("wb") as file:
        writer.write(file)
    return path


def write_layered_pdf(
    path: Path, width: int, *, hidden: bool, base_off: bool = False, alternatives: bool = False
) -> Path:
    """One page whose black square is drawn only in the layer "Secret"."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=width, height=100)
    layer = writer._add_object(
        DictionaryObject({NameObject("/Type"): NameObject("/OCG"), NameObject("/Name"): TextStringObject("Secret")})
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Properties"): DictionaryObject({NameObject("/Secret"): layer})}
    )
    content = DecodedStreamObject()
    content.set_data(b"/OC /Secret BDC 0 0 0 rg 10 10 80 80 re f EMC")
    page[NameObject("/Contents")] = writer._add_object(content)
    config = DictionaryObject({NameObject("/Order"): ArrayObject([layer])})
    if base_off:
        config[NameObject("/BaseState")] = NameObject("/OFF")
        config[NameObject("/ON")] = ArrayObject([] if hidden else [layer])
    elif hidden:
        config[NameObject("/OFF")] = ArrayObject([layer])
    settings = DictionaryObject({NameObject("/OCGs"): ArrayObject([layer]), NameObject("/D"): config})
    if alternatives:
        settings[NameObject("/Configs")] = ArrayObject([DictionaryObject({NameObject("/ON"): ArrayObject([layer])})])
    writer.root_object[NameObject("/OCProperties")] = settings
    with path.open("wb") as file:
        writer.write(file)
    return path


def hidden_layers(path: Path) -> list[bool | None]:
    """Per page: whether its layer is hidden by the default configuration, None without one."""
    reader = PdfReader(path)
    config = reader.root_object["/OCProperties"]["/D"]
    off = config.get("/OFF", [])
    layers = reader.root_object["/OCProperties"]["/OCGs"]
    result = []
    for page in reader.pages:
        if "/Properties" not in page.get("/Resources", {}):
            result.append(None)
            continue
        layer = page["/Resources"]["/Properties"].raw_get("/Secret")
        assert layer in layers, "the page's layer must be the one the catalog lists"
        result.append(layer in off)
    return result


def dark_pixels(path: Path) -> list[int]:
    """Render each page with poppler and count the dark pixels."""
    with tempfile.TemporaryDirectory() as folder:
        subprocess.run(["pdftoppm", "-gray", "-r", "10", path, f"{folder}/page"], check=True)
        counts = []
        for image in sorted(Path(folder).iterdir()):
            pixels = image.read_bytes().split(b"\n", 3)[3]  # Binary PGM after a three-line header.
            counts.append(sum(1 for value in pixels if value < 128))
        return counts


def page_widths(path: Path) -> list[int]:
    return [int(page.mediabox.width) for page in PdfReader(path).pages]


class MergeTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.folder = Path(temp_dir.name)
        self.first = write_pdf(self.folder / "first.pdf", 100, 110)
        self.second = write_pdf(self.folder / "second.pdf", 200)
        self.output = self.folder / "merged.pdf"

    def test_pages_follow_the_order_of_the_sources(self) -> None:
        third = write_pdf(self.folder / "third.pdf", 300, 310)

        pages = merge_pdfs([self.second, self.first, third], self.output)

        self.assertEqual(pages, 5)
        self.assertEqual(page_widths(self.output), [200, 100, 110, 300, 310])
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ["first.pdf", "merged.pdf", "second.pdf", "third.pdf"])

    def test_existing_pdf_is_kept_without_consent(self) -> None:
        self.output.write_bytes(b"old")

        with self.assertRaises(FileExistsError):
            merge_pdfs([self.first, self.second], self.output)
        self.assertEqual(self.output.read_bytes(), b"old")

        merge_pdfs([self.first, self.second], self.output, overwrite=True)
        self.assertEqual(page_widths(self.output), [100, 110, 200])

    def test_output_cannot_be_one_of_the_sources(self) -> None:
        original = self.first.read_bytes()

        with self.assertRaisesRegex(ValueError, "source document"):
            merge_pdfs([self.first, self.second], self.first, overwrite=True)
        self.assertEqual(self.first.read_bytes(), original)

    def test_unreadable_pdf_fails_before_anything_is_written(self) -> None:
        broken = self.folder / "broken.pdf"
        broken.write_bytes(b"not really a PDF")
        self.output.write_bytes(b"old")

        with (
            self.assertRaisesRegex(ValueError, "broken.pdf is not a readable PDF"),
            self.assertLogs("pypdf", level="WARNING"),
        ):
            merge_pdfs([self.first, broken], self.output, overwrite=True)
        self.assertEqual(self.output.read_bytes(), b"old")
        self.assertFalse([p for p in self.folder.iterdir() if p.name.startswith(".doczap_")])

    def test_password_protected_pdf_is_reported(self) -> None:
        locked = write_pdf(self.folder / "locked.pdf", 100, password="secret")

        with self.assertRaisesRegex(ValueError, "locked.pdf is password-protected"):
            merge_pdfs([self.first, locked], self.output)
        self.assertFalse(self.output.exists())

    def test_pdf_restricted_only_by_an_owner_password_is_merged(self) -> None:
        restricted = write_pdf(self.folder / "restricted.pdf", 400, password="", owner_password="owner")

        merge_pdfs([self.first, restricted], self.output)

        self.assertEqual(page_widths(self.output), [100, 110, 400])

    def test_needs_two_pdfs(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two"):
            merge_pdfs([self.first], self.output)

    def test_rejects_files_that_are_not_pdfs(self) -> None:
        notes = self.folder / "notes.txt"
        notes.write_text("hello")

        with self.assertRaisesRegex(ValueError, "notes.txt is not a PDF"):
            merge_pdfs([self.first, notes], self.output)

    def test_output_must_be_a_pdf(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a .pdf"):
            merge_pdfs([self.first, self.second], self.folder / "merged.txt")


    def test_consent_covers_only_the_file_it_was_given_for(self) -> None:
        self.output.write_bytes(b"old")
        agreed = file_identity(self.output)
        self.output.unlink()
        self.output.write_bytes(b"a different file")

        with self.assertRaisesRegex(FileExistsError, "merged.pdf changed after you chose to replace it"):
            merge_pdfs([self.first, self.second], self.output, overwrite=True, replace_only=agreed)
        self.assertEqual(self.output.read_bytes(), b"a different file")

        merge_pdfs([self.first, self.second], self.output, overwrite=True,
                   replace_only=file_identity(self.output))
        self.assertEqual(page_widths(self.output), [100, 110, 200])


class LayerTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.folder = Path(temp_dir.name)
        self.plain = write_pdf(self.folder / "plain.pdf", 200)
        self.output = self.folder / "merged.pdf"

    def test_hidden_layer_stays_hidden_beside_a_pdf_without_layers(self) -> None:
        layered = write_layered_pdf(self.folder / "layered.pdf", 100, hidden=True, alternatives=True)

        merge_pdfs([self.plain, layered], self.output)

        self.assertEqual(page_widths(self.output), [200, 100])
        reader = PdfReader(self.output)
        # Its settings are copied whole, alternative configurations included.
        self.assertIn("/Configs", reader.root_object["/OCProperties"])
        self.assertEqual(hidden_layers(self.output), [None, True])

    def test_each_pdf_keeps_its_own_layer_visibility(self) -> None:
        sources = [
            write_layered_pdf(self.folder / "hidden.pdf", 100, hidden=True),
            write_layered_pdf(self.folder / "shown.pdf", 110, hidden=False),
            write_layered_pdf(self.folder / "hidden-base.pdf", 120, hidden=True, base_off=True),
            write_layered_pdf(self.folder / "shown-base.pdf", 130, hidden=False, base_off=True),
        ]

        merge_pdfs([*sources, self.plain], self.output)

        self.assertEqual(page_widths(self.output), [100, 110, 120, 130, 200])
        reader = PdfReader(self.output)
        self.assertEqual(len(reader.root_object["/OCProperties"]["/OCGs"]), 4)
        self.assertEqual(len(reader.root_object["/OCProperties"]["/D"]["/Order"]), 4)
        self.assertEqual(hidden_layers(self.output), [True, False, True, False, None])

    @unittest.skipUnless(shutil.which("pdftoppm"), "poppler's pdftoppm is not installed")
    def test_merged_pdf_renders_hidden_layers_hidden(self) -> None:
        hidden = write_layered_pdf(self.folder / "hidden.pdf", 100, hidden=True)
        shown = write_layered_pdf(self.folder / "shown.pdf", 100, hidden=False)
        self.assertEqual(dark_pixels(hidden), [0])

        merge_pdfs([hidden, shown, hidden], self.output)

        before, visible, after = dark_pixels(self.output)
        self.assertEqual((before, after), (0, 0))
        self.assertGreater(visible, 0)

    def test_layers_that_cannot_be_combined_are_rejected_before_writing(self) -> None:
        hidden = write_layered_pdf(self.folder / "hidden.pdf", 100, hidden=True)
        complex_layers = write_layered_pdf(self.folder / "complex.pdf", 100, hidden=True, alternatives=True)
        self.output.write_bytes(b"old")

        with self.assertRaisesRegex(ValueError, "complex.pdf has alternative layer configurations"):
            merge_pdfs([hidden, complex_layers], self.output, overwrite=True)
        self.assertEqual(self.output.read_bytes(), b"old")
        self.assertFalse([p for p in self.folder.iterdir() if p.name.startswith(".doczap_")])


if __name__ == "__main__":
    unittest.main()

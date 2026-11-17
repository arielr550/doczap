from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from doczap.merge import merge_pdfs


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


if __name__ == "__main__":
    unittest.main()

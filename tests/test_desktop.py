"""Window tests. They need Tk and a display, so they skip on headless machines.

All tests share one Tk root, as the app does: creating a second Tk after
destroying the first can crash Tk on macOS.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import tkinter as tk

    from doczap import desktop

    ROOT = tk.Tk()
    ROOT.withdraw()
except Exception:  # No tkinter module, or no display to open a window on.
    ROOT = None


def tearDownModule() -> None:
    if ROOT is not None:
        ROOT.destroy()


def fake_convert(source, output, *, overwrite=False):
    Path(output).write_bytes(b"%PDF")
    return Path(output)


@unittest.skipUnless(ROOT is not None, "Tk cannot open a window here")
class DesktopWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.folder = Path(temp_dir.name).resolve()
        self.root = ROOT
        self.addCleanup(self.clear_root)

    def clear_root(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()

    def document(self, name: str) -> Path:
        path = self.folder / name
        path.write_bytes(b"docx")
        return path

    def wait_until_idle(self, app: desktop.App) -> None:
        deadline = time.monotonic() + 10
        while app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(app.busy)

    def test_only_word_documents_are_listed_once(self) -> None:
        report = self.document("report.docx")
        notes = self.folder / "notes.txt"
        notes.write_text("not a document")

        app = desktop.App(self.root, [str(report), str(report), str(notes)])

        self.assertEqual(app.sources, [report])
        self.assertIn("Ignored 1 file", app.status.get())

    def test_convert_saves_into_the_chosen_folder_and_clears_the_list(self) -> None:
        report = self.document("report.docx")
        out = self.folder / "out"
        out.mkdir()
        app = desktop.App(self.root, [str(report)])
        app.output_dir = out
        app.destination.set(desktop.FOLDER)

        with patch("doczap.batch.convert_document", side_effect=fake_convert):
            app.convert()
            self.wait_until_idle(app)

        self.assertTrue((out / "report.pdf").exists())
        self.assertEqual(app.sources, [])
        self.assertEqual(app.status.get(), "Created report.pdf.")

    def test_existing_pdf_is_skipped_when_the_user_says_no(self) -> None:
        report = self.document("report.docx")
        report.with_suffix(".pdf").write_bytes(b"old")
        app = desktop.App(self.root, [str(report)])

        with (
            patch("doczap.desktop.messagebox.askyesnocancel", return_value=False),
            patch("doczap.batch.convert_document") as convert,
        ):
            app.convert()

        convert.assert_not_called()
        self.assertEqual(report.with_suffix(".pdf").read_bytes(), b"old")
        self.assertEqual(app.status.get(), "Skipped 1 existing PDF.")

    def test_cancel_at_the_replace_question_does_nothing(self) -> None:
        report = self.document("report.docx")
        report.with_suffix(".pdf").write_bytes(b"old")
        app = desktop.App(self.root, [str(report)])

        with (
            patch("doczap.desktop.messagebox.askyesnocancel", return_value=None),
            patch("doczap.batch.convert_document") as convert,
        ):
            app.convert()

        convert.assert_not_called()
        self.assertEqual(app.sources, [report])


if __name__ == "__main__":
    unittest.main()

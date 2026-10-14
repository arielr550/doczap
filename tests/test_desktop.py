"""Window tests. They need Tk and a display, so they skip on headless machines.

All tests share one Tk root, as the app does: creating a second Tk after
destroying the first can crash Tk on macOS.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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


def fake_convert(source, output, *, overwrite=False, cancel=None):
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


@unittest.skipUnless("desktop" in globals(), "Tk module is unavailable")
class DesktopShutdownTests(unittest.TestCase):
    """Shutdown coordination needs no display: only the worker and Tk callbacks."""
    def app(self):
        app = desktop.App.__new__(desktop.App)
        app.root = Mock()
        app.status = Mock()
        app.worker = Mock()
        app.worker.is_alive.return_value = True
        app.cancel = threading.Event()
        app.closing = False
        app.busy = True
        return app

    def test_confirmed_quit_cancels_then_waits_for_worker(self) -> None:
        app = self.app()
        with patch("doczap.desktop.messagebox.askokcancel", return_value=True) as question:
            app.quit()
            app.quit()
        self.assertEqual(question.call_count, 1)
        self.assertTrue(app.cancel.is_set())
        self.assertTrue(app.closing)
        app.root.destroy.assert_not_called()
        app.poll()
        app.root.after.assert_called_once_with(50, app.poll_shutdown)
        app.root.destroy.assert_not_called()
        app.worker.is_alive.return_value = False
        app.poll_shutdown()
        app.root.destroy.assert_called_once_with()

    def test_declined_quit_leaves_conversion_running(self) -> None:
        app = self.app()
        with patch("doczap.desktop.messagebox.askokcancel", return_value=False):
            app.quit()
        self.assertFalse(app.cancel.is_set())
        self.assertFalse(app.closing)
        app.root.destroy.assert_not_called()

    def test_idle_quit_closes_without_question(self) -> None:
        app = self.app()
        app.busy = False
        with patch("doczap.desktop.messagebox.askokcancel") as question:
            app.quit()
        question.assert_not_called()
        app.root.destroy.assert_called_once_with()


@unittest.skipUnless("desktop" in globals(), "requires Tk module")
class DesktopEntryTests(unittest.TestCase):
    def test_packaged_conversion_mode_does_not_open_a_window(self) -> None:
        with (
            patch("sys.argv", ["DocZap", "--convert", "report.docx", "report.pdf", "--overwrite"]),
            patch("doczap.cli.convert_document", return_value=Path("report.pdf")) as convert,
            patch("doczap.desktop.tk.Tk") as window,
            self.assertLogs(level="INFO"),
        ):
            self.assertEqual(desktop.main(), 0)
        window.assert_not_called()
        convert.assert_called_once_with("report.docx", "report.pdf", overwrite=True)


if __name__ == "__main__":
    unittest.main()

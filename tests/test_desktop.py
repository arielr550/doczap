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

from pypdf import PdfReader

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

    def pdf(self, name: str, *widths: int) -> Path:
        from test_merge import write_pdf

        return write_pdf(self.folder / name, *(widths or (100,)))

    def wait_for_merge(self, app: desktop.App) -> None:
        deadline = time.monotonic() + 10
        while (app.busy or app.worker.is_alive()) and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.root.update()
        self.assertFalse(app.busy)

    def test_opened_pdfs_go_to_the_merge_tab(self) -> None:
        report = self.document("report.docx")
        first, second = self.pdf("first.pdf"), self.pdf("second.pdf")
        notes = self.folder / "notes.txt"
        notes.write_text("not a PDF")

        app = desktop.App(self.root, [str(first), str(report), str(second), str(first)])
        self.assertEqual(app.sources, [report])
        self.assertEqual(app.pdfs, [first, second])

        app.add_pdfs([str(notes)])
        self.assertEqual(app.pdfs, [first, second])
        self.assertIn("Ignored 1 file that is not a PDF", app.merge_status.get())

    def test_move_keeps_the_selected_pdfs_together(self) -> None:
        a, b, c, d = (self.pdf(f"{name}.pdf") for name in "abcd")
        app = desktop.App(self.root, [str(a), str(b), str(c), str(d)])

        app.merge_tree.selection_set([str(c), str(d)])
        app.move_selected_pdfs(-1)
        self.assertEqual(app.pdfs, [a, c, d, b])
        app.move_selected_pdfs(-1)
        app.move_selected_pdfs(-1)  # Already at the top: nothing moves.
        self.assertEqual(app.pdfs, [c, d, a, b])
        self.assertEqual(set(app.merge_tree.selection()), {str(c), str(d)})

        app.merge_tree.selection_set([str(c)])
        app.move_selected_pdfs(1)
        self.assertEqual(app.pdfs, [d, c, a, b])

    def test_merge_saves_the_pages_in_list_order(self) -> None:
        from test_merge import page_widths

        first, second = self.pdf("first.pdf", 100, 110), self.pdf("second.pdf", 200)
        output = self.folder / "joined.pdf"
        app = desktop.App(self.root, [str(second), str(first)])
        app.notebook.select(1)
        self.assertFalse(app.merge_button.instate(["disabled"]))

        with patch("doczap.desktop.filedialog.asksaveasfilename", return_value=str(output)):
            app.run_current_tab()
            self.wait_for_merge(app)

        self.assertEqual(page_widths(output), [200, 100, 110])
        self.assertEqual(app.pdfs, [])
        self.assertEqual(app.merge_status.get(), "Created joined.pdf (3 pages).")

    def test_merge_refuses_to_save_over_one_of_its_pdfs(self) -> None:
        first, second = self.pdf("first.pdf"), self.pdf("second.pdf")
        original = first.read_bytes()
        app = desktop.App(self.root, [str(first), str(second)])

        with (
            patch("doczap.desktop.filedialog.asksaveasfilename", return_value=str(first)),
            patch("doczap.desktop.messagebox.showerror") as error,
            patch("doczap.desktop.merge_pdfs") as merge,
        ):
            app.merge()

        error.assert_called_once()
        merge.assert_not_called()
        self.assertEqual(first.read_bytes(), original)

    def test_merge_asks_before_replacing_a_pdf_the_dialog_did_not_confirm(self) -> None:
        first, second = self.pdf("first.pdf"), self.pdf("second.pdf")
        (self.folder / "joined.pdf").write_bytes(b"old")
        app = desktop.App(self.root, [str(first), str(second)])

        # The dialog returned a name without .pdf, so it asked about a different file.
        with (
            patch("doczap.desktop.filedialog.asksaveasfilename", return_value=str(self.folder / "joined")),
            patch("doczap.desktop.messagebox.askyesno", return_value=False) as question,
            patch("doczap.desktop.merge_pdfs") as merge,
        ):
            app.merge()

        question.assert_called_once()
        merge.assert_not_called()
        self.assertEqual((self.folder / "joined.pdf").read_bytes(), b"old")


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


@unittest.skipUnless("desktop" in globals(), "Tk module is unavailable")
class MergeConsentTests(unittest.TestCase):
    """Consent to replace a file covers only that file. Needs no display."""

    def setUp(self) -> None:
        from test_merge import write_pdf

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.folder = Path(temp_dir.name).resolve()
        self.output = self.folder / "joined.pdf"
        self.app = desktop.App.__new__(desktop.App)
        self.app.root = Mock()
        self.app.merge_status = Mock()
        self.app.events = desktop.queue.Queue()
        self.app.busy = False
        self.app.worker = None
        self.app.pdfs = [write_pdf(self.folder / "first.pdf", 100), write_pdf(self.folder / "second.pdf", 200)]
        self.app.set_busy = Mock()

    def merge(self, answer: bool = True) -> tuple:
        with (
            patch("doczap.desktop.filedialog.asksaveasfilename", return_value=str(self.output)) as dialog,
            patch("doczap.desktop.messagebox.askyesno", return_value=answer) as self.question,
        ):
            self.app.merge()
        # DocZap asks itself, so the dialog must not ask as well (Windows, Linux).
        self.assertIs(dialog.call_args.kwargs["confirmoverwrite"], False)
        if self.app.worker is None:
            return ()
        self.app.worker.join(10)
        return self.app.events.get_nowait()

    def test_a_file_that_appears_after_the_dialog_is_not_replaced(self) -> None:
        self.app.set_busy.side_effect = lambda busy: self.output.write_bytes(b"someone else's")

        event = self.merge()

        self.question.assert_not_called()
        self.assertEqual(event[0], "merge failed")
        self.assertIn("joined.pdf was created or changed", event[1])
        self.assertEqual(self.output.read_bytes(), b"someone else's")
        self.assertFalse([p for p in self.folder.iterdir() if p.name.startswith(".doczap_")])

    def test_a_file_that_changes_after_consent_is_kept(self) -> None:
        from test_merge import write_pdf

        self.output.write_bytes(b"old")

        def replace_file(busy: bool) -> None:
            # Another program saves a new file under the same name.
            write_pdf(self.folder / "other.pdf", 300).replace(self.output)

        self.app.set_busy.side_effect = replace_file
        event = self.merge()

        self.question.assert_called_once()
        self.assertEqual(event[0], "merge failed")
        self.assertEqual(PdfReader(self.output).pages[0].mediabox.width, 300)

    def test_confirmed_replacement_replaces_the_file(self) -> None:
        self.output.write_bytes(b"old")

        event = self.merge(answer=True)

        self.question.assert_called_once()
        self.assertIn("joined.pdf", self.question.call_args.args[1])
        self.assertEqual(event[0], "merged")
        self.assertEqual([int(p.mediabox.width) for p in PdfReader(self.output).pages], [100, 200])

    def test_declined_replacement_does_nothing(self) -> None:
        self.output.write_bytes(b"old")

        self.assertEqual(self.merge(answer=False), ())

        self.app.set_busy.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b"old")

    def test_a_file_removed_after_consent_is_created_new(self) -> None:
        self.output.write_bytes(b"old")
        self.app.set_busy.side_effect = lambda busy: self.output.unlink()

        event = self.merge()

        self.assertEqual(event[0], "merged")
        self.assertEqual(len(PdfReader(self.output).pages), 2)


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

from __future__ import annotations

import errno
import os
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from doczap.conversion import convert_document
from doczap.process import ConversionCancelled
from doczap.utils.save_pdf import rename_without_replace


class FileSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="doczap_safety_")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name).resolve()
        self.source = self.folder / "report.docx"
        self.source.write_bytes(b"original document")
        self.output = self.source.with_suffix(".pdf")
        lookup = patch("doczap.converters.libreoffice.find_soffice", return_value="soffice")
        lookup.start()
        self.addCleanup(lookup.stop)

    def render(self, source: Path, folder: Path, **kwargs):
        (folder / f"{source.stem}.pdf").write_bytes(b"%PDF-new")
        return subprocess.CompletedProcess([], 0, "", "")

    def convert(self, *, overwrite=False, output=None):
        with patch("doczap.converters.libreoffice.LibreOfficeConverter._run_soffice", side_effect=self.render):
            return convert_document(self.source, output, overwrite=overwrite)

    def make_symlink(self, target: Path) -> None:
        try:
            self.output.symlink_to(target)
        except OSError as exc:
            if os.name == "nt":
                self.skipTest(f"Windows user cannot create symlinks: {exc}")
            raise

    def test_default_and_explicit_output_symlinks_are_rejected(self) -> None:
        self.make_symlink(self.source)
        for output in (None, self.output):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "symbolic link"):
                self.convert(output=output, overwrite=True)
        self.assertEqual(self.source.read_bytes(), b"original document")

    def test_broken_output_symlink_is_rejected(self) -> None:
        self.make_symlink(self.folder / "missing.pdf")
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.convert()
        self.assertTrue(self.output.is_symlink())

    def test_output_hard_link_to_source_is_rejected(self) -> None:
        os.link(self.source, self.output)
        with self.assertRaisesRegex(ValueError, "source document"):
            self.convert(overwrite=True)
        self.assertEqual(self.source.read_bytes(), b"original document")

    def test_directory_output_is_rejected(self) -> None:
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, "not a regular file"):
            self.convert(overwrite=True)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_rendering_is_staged_in_the_destination_folder(self) -> None:
        seen = []

        def render(source, folder, **kwargs):
            seen.append(folder.parent)
            return self.render(source, folder)

        with patch("doczap.converters.libreoffice.LibreOfficeConverter._run_soffice", side_effect=render):
            convert_document(self.source)
        self.assertEqual(seen, [self.folder])
        self.assertEqual(self.output.read_bytes(), b"%PDF-new")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["report.docx", "report.pdf"])

    def test_file_created_during_rendering_is_preserved(self) -> None:
        def render(source, folder, **kwargs):
            self.output.write_bytes(b"another process's PDF")
            return self.render(source, folder)

        with patch("doczap.converters.libreoffice.LibreOfficeConverter._run_soffice", side_effect=render):
            with self.assertRaises(FileExistsError):
                convert_document(self.source)
        self.assertEqual(self.output.read_bytes(), b"another process's PDF")

    def test_concurrent_conversions_only_publish_one_pdf(self) -> None:
        barrier = threading.Barrier(2)

        def render(source, folder, **kwargs):
            result = self.render(source, folder)
            barrier.wait(timeout=5)
            return result

        def convert():
            try:
                convert_document(self.source)
            except FileExistsError:
                return False
            return True

        with patch("doczap.converters.libreoffice.LibreOfficeConverter._run_soffice", side_effect=render):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: convert(), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.output.read_bytes(), b"%PDF-new")

    def test_failed_replacement_preserves_existing_pdf_and_cleans_staging(self) -> None:
        self.output.write_bytes(b"old PDF")
        with patch("doczap.utils.save_pdf.os.replace", side_effect=OSError(errno.ENOSPC, "Disk full")):
            with self.assertRaises(OSError):
                self.convert(overwrite=True)
        self.assertEqual(self.output.read_bytes(), b"old PDF")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["report.docx", "report.pdf"])

    def test_cancel_after_rendering_preserves_existing_pdf(self) -> None:
        self.output.write_bytes(b"old PDF")
        cancel = threading.Event()

        def render(source, folder, **kwargs):
            result = self.render(source, folder)
            cancel.set()
            return result

        with patch("doczap.converters.libreoffice.LibreOfficeConverter._run_soffice", side_effect=render):
            with self.assertRaises(ConversionCancelled):
                convert_document(self.source, overwrite=True, cancel=cancel)
        self.assertEqual(self.output.read_bytes(), b"old PDF")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["report.docx", "report.pdf"])

    def test_atomic_replacement_does_not_modify_existing_hard_links(self) -> None:
        self.output.write_bytes(b"old PDF")
        backup = self.folder / "backup.pdf"
        os.link(self.output, backup)
        self.convert(overwrite=True)
        self.assertEqual(self.output.read_bytes(), b"%PDF-new")
        self.assertEqual(backup.read_bytes(), b"old PDF")

    def test_symlink_created_during_rendering_cannot_damage_the_source(self) -> None:
        def render(source, folder, **kwargs):
            self.make_symlink(self.source)
            return self.render(source, folder)

        with patch("doczap.converters.libreoffice.LibreOfficeConverter._run_soffice", side_effect=render):
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                convert_document(self.source, overwrite=True)
        self.assertEqual(self.source.read_bytes(), b"original document")

    def test_race_at_the_final_rename_cannot_replace_a_pdf(self) -> None:
        produced = self.folder / "staged.pdf"
        produced.write_bytes(b"%PDF-new")
        self.output.write_bytes(b"existing PDF")
        with self.assertRaises(FileExistsError):
            rename_without_replace(produced, self.output)
        self.assertEqual(self.output.read_bytes(), b"existing PDF")
        self.assertTrue(produced.exists())

    @unittest.skipIf(os.name == "nt", "Windows uses exclusive rename directly")
    def test_unsupported_native_rename_uses_safe_hard_link_fallback(self) -> None:
        produced = self.folder / "staged.pdf"
        produced.write_bytes(b"%PDF-new")
        native = Mock(return_value=-1)
        libc = Mock(renameat2=native, renamex_np=native)
        with patch("doczap.utils.save_pdf.ctypes.CDLL", return_value=libc), patch(
            "doczap.utils.save_pdf.ctypes.get_errno", return_value=errno.ENOTSUP
        ):
            rename_without_replace(produced, self.output)
            with self.assertRaises(FileExistsError):
                rename_without_replace(produced, self.output)
        self.assertEqual(self.output.read_bytes(), b"%PDF-new")

    @unittest.skipIf(os.name == "nt", "Windows uses exclusive rename directly")
    def test_unsupported_filesystem_fails_without_creating_partial_output(self) -> None:
        produced = self.folder / "staged.pdf"
        produced.write_bytes(b"%PDF-new")
        native = Mock(return_value=-1)
        libc = Mock(renameat2=native, renamex_np=native)
        with patch("doczap.utils.save_pdf.ctypes.CDLL", return_value=libc), patch(
            "doczap.utils.save_pdf.ctypes.get_errno", return_value=errno.ENOTSUP
        ), patch("doczap.utils.save_pdf.os.link", side_effect=OSError(errno.ENOTSUP, "No hard links")):
            with self.assertRaisesRegex(OSError, "Choose another output folder"):
                rename_without_replace(produced, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(produced.read_bytes(), b"%PDF-new")


if __name__ == "__main__":
    unittest.main()

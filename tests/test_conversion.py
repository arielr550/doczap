from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from doczap import cli, desktop, system
from doczap.conversion import convert_document, default_output_path, select_converter
from doczap.converters.libreoffice import LibreOfficeConverter
from doczap.desktop import format_summary


def fake_soffice(pdf_bytes: bytes | None):
    """Return a subprocess.run stand-in that behaves like a successful soffice exit.

    When pdf_bytes is None it writes nothing, mimicking LibreOffice's habit of
    exiting 0 when it cannot load the source document.
    """

    def run(command, **kwargs):
        if pdf_bytes is not None:
            output_dir = Path(command[command.index("--outdir") + 1])
            (output_dir / f"{Path(command[-1]).stem}.pdf").write_bytes(pdf_bytes)
        return subprocess.CompletedProcess(
            command, 0, stdout="", stderr="" if pdf_bytes else "Error: source file could not be loaded"
        )

    return run


class ConversionTests(unittest.TestCase):
    def test_default_output_is_beside_input(self) -> None:
        self.assertEqual(
            default_output_path(Path("/documents/report.docx")),
            Path("/documents/report.pdf"),
        )

    def test_convert_document_uses_default_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "report.docx"
            input_path.touch()
            converter = Mock()

            with patch("doczap.conversion.select_converter", return_value=converter):
                result = convert_document(input_path)

            expected = input_path.resolve().with_suffix(".pdf")
            self.assertEqual(result, expected)
            converter.convert.assert_called_once_with(str(input_path.resolve()), str(expected))

    def test_existing_default_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "report.docx"
            output_path = Path(temp_dir) / "report.pdf"
            input_path.touch()
            output_path.touch()

            with self.assertRaises(FileExistsError):
                convert_document(input_path)

    def test_unsupported_conversion_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported conversion"):
            select_converter(Path("report.docx"), Path("report.txt"))

    def test_desktop_summary_reports_batch_and_skips(self) -> None:
        converted = [Path("one.pdf"), Path("two.pdf")]
        self.assertEqual(
            format_summary(converted, skipped=1),
            "Created 2 PDFs beside the originals. Skipped 1 existing file.",
        )

    def test_desktop_skips_existing_output_when_not_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "report.docx"
            input_path.touch()
            input_path.with_suffix(".pdf").touch()

            with (
                patch("doczap.desktop.confirm_overwrite", return_value=False),
                patch("doczap.desktop.convert_document") as convert,
            ):
                converted, errors, skipped = desktop.convert_files([str(input_path)])

            self.assertEqual((converted, errors, skipped), ([], [], 1))
            convert.assert_not_called()

    def test_cli_returns_nonzero_on_failure(self) -> None:
        with (
            patch("sys.argv", ["doczap", "missing.docx"]),
            patch("doczap.cli.convert_document", side_effect=FileNotFoundError("nope")),
            self.assertLogs(level="ERROR"),
        ):
            self.assertEqual(cli.main(), 1)


class LibreOfficeConverterTests(unittest.TestCase):
    def setUp(self) -> None:
        which = patch("doczap.converters.libreoffice.shutil.which", return_value="/usr/bin/soffice")
        which.start()
        self.addCleanup(which.stop)
        cache_root = tempfile.TemporaryDirectory()
        self.addCleanup(cache_root.cleanup)
        self.profile_cache = Path(cache_root.name) / "doczap" / "lo-profile"
        cache = patch(
            "doczap.converters.libreoffice.profile_cache_dir", return_value=self.profile_cache
        )
        cache.start()
        self.addCleanup(cache.stop)

    def profile_used(self, run: Mock) -> str:
        return next(arg for arg in run.call_args.args[0] if arg.startswith("-env:UserInstallation="))

    def test_cached_profile_is_reused_when_free(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with patch(
                "doczap.converters.libreoffice.subprocess.run", side_effect=fake_soffice(b"pdf")
            ) as run:
                LibreOfficeConverter()._run_soffice(Path("report.docx"), Path(output_dir))

        self.assertEqual(self.profile_used(run), f"-env:UserInstallation={self.profile_cache.as_uri()}")

    def test_concurrent_run_falls_back_to_temporary_profile(self) -> None:
        self.profile_cache.parent.mkdir(parents=True)
        with open(self.profile_cache.parent / "lo-profile.lock", "w") as held:
            self.assertTrue(system.try_lock(held))
            with tempfile.TemporaryDirectory() as output_dir:
                with patch(
                    "doczap.converters.libreoffice.subprocess.run", side_effect=fake_soffice(b"pdf")
                ) as run:
                    LibreOfficeConverter()._run_soffice(Path("report.docx"), Path(output_dir))

        self.assertNotIn(self.profile_cache.as_uri(), self.profile_used(run))
        self.assertIn("doczap_lo_profile_", self.profile_used(run))

    def run_with_fake_soffice(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with patch("doczap.converters.libreoffice.subprocess.run", side_effect=fake_soffice(b"pdf")):
                LibreOfficeConverter()._run_soffice(Path("report.docx"), Path(output_dir))

    def test_profile_blocks_remote_links(self) -> None:
        self.run_with_fake_soffice()

        registry = (self.profile_cache / "user" / "registrymodifications.xcu").read_text()
        self.assertIn(
            '<prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop>',
            registry,
        )

    def test_existing_profile_settings_are_kept(self) -> None:
        registry = self.profile_cache / "user" / "registrymodifications.xcu"
        registry.parent.mkdir(parents=True)
        other = '<item oor:path="/org.openoffice.Setup/Office"><prop oor:name="ooSetupInstCompleted" oor:op="fuse"><value>true</value></prop></item>'
        registry.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">\n'
            f"{other}\n</oor:items>\n"
        )

        self.run_with_fake_soffice()
        self.run_with_fake_soffice()

        text = registry.read_text()
        self.assertIn(other, text)
        self.assertEqual(text.count("BlockUntrustedRefererLinks"), 1)

    def test_timeout_is_bounded_and_reported(self) -> None:
        timeout = subprocess.TimeoutExpired(cmd=["soffice"], timeout=1)
        with patch("doczap.converters.libreoffice.subprocess.run", side_effect=timeout):
            converter = LibreOfficeConverter(timeout_seconds=1)
            with self.assertRaisesRegex(RuntimeError, "timed out after 1 seconds"):
                converter._run_soffice(Path("input.docx"), Path("."))

    def test_docx_import_filter_is_forced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            with patch(
                "doczap.converters.libreoffice.subprocess.run", side_effect=fake_soffice(b"pdf")
            ) as run:
                LibreOfficeConverter()._run_soffice(Path("report.docx"), output_dir)

            self.assertIn("--infilter=MS Word 2007 XML", run.call_args.args[0])

    def test_stale_pdf_is_not_reported_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "report.docx"
            dst = Path(temp_dir) / "report.pdf"
            src.touch()
            dst.write_bytes(b"old pdf")

            with patch("doczap.converters.libreoffice.subprocess.run", side_effect=fake_soffice(None)):
                with self.assertRaisesRegex(RuntimeError, "could not be loaded"):
                    LibreOfficeConverter().convert(str(src), str(dst))

            self.assertEqual(dst.read_bytes(), b"old pdf")

    def test_macos_launch_noise_is_dropped_from_errors(self) -> None:
        noisy = subprocess.CompletedProcess(
            ["soffice"],
            0,
            stdout="",
            stderr="2026-09-15 20:56:48.940 soffice[1:2] Task policy set failed: 4\n"
            "Error: source file could not be loaded",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "report.docx"
            src.touch()
            with patch("doczap.converters.libreoffice.subprocess.run", return_value=noisy):
                with self.assertRaises(RuntimeError) as raised:
                    LibreOfficeConverter().convert(str(src), str(src.with_suffix(".pdf")))

        self.assertIn("could not be loaded", str(raised.exception))
        self.assertNotIn("Task policy", str(raised.exception))

    def test_output_replaces_existing_pdf_with_same_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "report.docx"
            dst = Path(temp_dir) / "report.pdf"
            src.touch()
            dst.write_bytes(b"old pdf")

            with patch("doczap.converters.libreoffice.subprocess.run", side_effect=fake_soffice(b"new pdf")):
                LibreOfficeConverter().convert(str(src), str(dst))

            self.assertEqual(dst.read_bytes(), b"new pdf")

    def test_output_can_use_a_different_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "report.docx"
            dst = Path(temp_dir) / "final.pdf"
            src.touch()

            with patch("doczap.converters.libreoffice.subprocess.run", side_effect=fake_soffice(b"new pdf")):
                LibreOfficeConverter().convert(str(src), str(dst))

            self.assertEqual(dst.read_bytes(), b"new pdf")
            self.assertFalse((Path(temp_dir) / "report.pdf").exists())


class SystemTests(unittest.TestCase):
    def test_soffice_candidates_cover_each_platform(self) -> None:
        self.assertIn(
            Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
            system.soffice_candidates("darwin"),
        )
        self.assertIn(
            Path("/usr/lib/libreoffice/program/soffice"), system.soffice_candidates("linux")
        )
        with patch.dict("os.environ", {"PROGRAMFILES": "C:\\Program Files"}, clear=True):
            self.assertEqual(
                system.soffice_candidates("win32"),
                [Path("C:\\Program Files") / "LibreOffice" / "program" / "soffice.exe"],
            )

    def test_cache_dir_follows_platform_conventions(self) -> None:
        self.assertEqual(
            system.cache_dir("darwin"), Path.home() / "Library" / "Caches" / "doczap"
        )
        with patch.dict("os.environ", {"XDG_CACHE_HOME": "/xdg"}):
            self.assertEqual(system.cache_dir("linux"), Path("/xdg/doczap"))
        with patch.dict("os.environ", {"LOCALAPPDATA": "/local"}):
            self.assertEqual(system.cache_dir("win32"), Path("/local/doczap"))

    def test_lock_is_exclusive_until_released(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "test.lock"
            with open(lock_path, "w") as first:
                self.assertTrue(system.try_lock(first))
                with open(lock_path, "w") as second:
                    self.assertFalse(system.try_lock(second))
            with open(lock_path, "w") as third:
                self.assertTrue(system.try_lock(third))


class SofficeLookupTests(unittest.TestCase):
    def test_falls_back_to_standard_install_location(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled = Path(temp_dir) / "soffice"
            bundled.touch()
            with (
                patch("doczap.converters.libreoffice.shutil.which", return_value=None),
                patch("doczap.converters.libreoffice.soffice_candidates", return_value=[bundled]),
            ):
                self.assertEqual(LibreOfficeConverter().soffice_binary, str(bundled))

    def test_symlink_on_path_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            real = Path(temp_dir) / "LibreOffice.app" / "soffice"
            real.parent.mkdir()
            real.touch()
            link = Path(temp_dir) / "soffice"
            link.symlink_to(real)
            with patch("doczap.converters.libreoffice.shutil.which", return_value=str(link)):
                self.assertEqual(LibreOfficeConverter().soffice_binary, str(real.resolve()))

    def test_missing_soffice_fails_clearly(self) -> None:
        with (
            patch("doczap.converters.libreoffice.shutil.which", return_value=None),
            patch("doczap.converters.libreoffice.soffice_candidates", return_value=[]),
        ):
            with self.assertRaisesRegex(RuntimeError, "was not found"):
                LibreOfficeConverter()


if __name__ == "__main__":
    unittest.main()

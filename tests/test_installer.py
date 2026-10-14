"""Installer failure tests with isolated apps and stubbed macOS tools."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"


@unittest.skipUnless(os.name == "posix" and shutil.which("sh"), "requires POSIX")
class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="doczap installer ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.apps = self.root / "Applications with spaces"
        self.apps.mkdir()
        self.app = self.apps / "DocZap.app"
        self.fixture = self.root / "release"
        self.fixture.mkdir()
        self.new_app = self.fixture / "DocZap.app"
        (self.new_app / "Contents" / "MacOS").mkdir(parents=True)
        (self.new_app / "Contents" / "Info.plist").write_text("validated by stub")
        executable = self.new_app / "Contents" / "MacOS" / "DocZap"
        executable.write_text("new executable")
        executable.chmod(0o755)
        (self.new_app / "version").write_text("new")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = os.environ.copy()
        self.env.update(
            PATH=f"{self.bin}{os.pathsep}{self.env['PATH']}",
            HOME=str(self.root),
            DOCZAP_APPS_DIR=str(self.apps),
            DOCZAP_ZIP_URL="https://example.invalid/test.zip",
            FIXTURE=str(self.fixture),
            REAL_MV=shutil.which("mv") or "mv",
        )
        self.tool("uname", 'case "$1" in -s) echo Darwin;; -m) echo arm64;; esac')
        self.tool("curl", ': > "$3"')
        self.tool("ditto", 'cp -R "$FIXTURE/DocZap.app" "$4/DocZap.app"')
        self.tool(
            "codesign",
            'test "$1" = --verify; test "$2" = --deep; test "$3" = --strict; '
            'test "${BAD_SIGNATURE:-0}" != 1',
        )
        self.tool(
            "plutil",
            'if [ "$1" = -extract ]; then echo "${BUNDLE_EXECUTABLE:-DocZap}"; fi',
        )
        self.tool(
            "mv",
            '''
case "$1" in
    */DocZap.app)
        if [ "$1" != "$DOCZAP_APPS_DIR/DocZap.app" ]; then
            if [ "${SIGNAL_ON_INSTALL:-0}" = 1 ]; then
                kill -TERM "$PPID"
                exit 1
            fi
            if [ "${FAIL_INSTALL:-0}" = 1 ]; then exit 1; fi
        fi
        ;;
    */previous.app)
        if [ "${FAIL_RESTORE:-0}" = 1 ]; then exit 1; fi
        ;;
esac
exec "$REAL_MV" "$@"
''',
        )

    def tool(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!/bin/sh\nset -eu\n{body}\n")
        path.chmod(0o755)

    def existing_app(self) -> None:
        self.app.mkdir()
        (self.app / "version").write_text("old")

    def run_installer(self, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(INSTALLER)],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=15,
        )

    def assert_clean(self) -> None:
        self.assertEqual(list(self.apps.iterdir()), [self.app])

    def assert_preserved(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.app / "version").read_text(), "old")
        self.assert_clean()

    def test_successful_update(self) -> None:
        self.existing_app()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.app / "version").read_text(), "new")
        self.assert_clean()

    def test_first_install(self) -> None:
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.app / "version").read_text(), "new")
        self.assert_clean()

    def test_failed_download_preserves_installed_app(self) -> None:
        self.existing_app()
        self.tool("curl", "exit 1")
        self.assert_preserved(self.run_installer())

    def test_failed_extraction_preserves_installed_app(self) -> None:
        self.existing_app()
        self.tool("ditto", "exit 1")
        self.assert_preserved(self.run_installer())

    def test_missing_bundle_preserves_installed_app(self) -> None:
        self.existing_app()
        self.tool("ditto", ":")
        self.assert_preserved(self.run_installer())

    def test_missing_executable_preserves_installed_app(self) -> None:
        self.existing_app()
        (self.new_app / "Contents" / "MacOS" / "DocZap").unlink()
        self.assert_preserved(self.run_installer())

    def test_non_executable_bundle_preserves_installed_app(self) -> None:
        self.existing_app()
        (self.new_app / "Contents" / "MacOS" / "DocZap").chmod(0o644)
        self.assert_preserved(self.run_installer())

    def test_invalid_plist_preserves_installed_app(self) -> None:
        self.existing_app()
        self.tool("plutil", "exit 1")
        self.assert_preserved(self.run_installer())

    def test_unexpected_executable_preserves_installed_app(self) -> None:
        self.existing_app()
        self.assert_preserved(self.run_installer(BUNDLE_EXECUTABLE="OtherApp"))

    def test_invalid_signature_preserves_installed_app(self) -> None:
        self.existing_app()
        self.assert_preserved(self.run_installer(BAD_SIGNATURE="1"))

    def test_failed_final_move_restores_installed_app(self) -> None:
        self.existing_app()
        self.assert_preserved(self.run_installer(FAIL_INSTALL="1"))

    def test_signal_during_final_move_restores_installed_app(self) -> None:
        self.existing_app()
        self.assert_preserved(self.run_installer(SIGNAL_ON_INSTALL="1"))

    def test_failed_restore_keeps_backup(self) -> None:
        self.existing_app()
        result = self.run_installer(FAIL_INSTALL="1", FAIL_RESTORE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.app.exists())
        backups = list(self.apps.glob(".doczap-install.*/previous.app"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "version").read_text(), "old")
        self.assertIn(str(backups[0]), result.stderr)
        self.assertFalse((self.apps / ".doczap-install.lock").exists())

    def test_failed_staging_preserves_installed_app(self) -> None:
        self.existing_app()
        self.tool("mktemp", 'echo "Permission denied" >&2; exit 1')
        self.assert_preserved(self.run_installer())

    def test_symlink_destination_is_rejected(self) -> None:
        other = self.root / "Other.app"
        other.mkdir()
        (other / "version").write_text("other")
        self.app.symlink_to(other, target_is_directory=True)
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.app.is_symlink())
        self.assertEqual((other / "version").read_text(), "other")
        self.assert_clean()

    def test_file_destination_is_rejected(self) -> None:
        self.app.write_text("user file")
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.app.read_text(), "user file")
        self.assert_clean()

    def test_another_installer_lock_is_preserved(self) -> None:
        self.existing_app()
        lock = self.apps / ".doczap-install.lock"
        lock.mkdir()
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.app / "version").read_text(), "old")
        self.assertTrue(lock.exists())

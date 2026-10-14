"""Exercise real macOS extraction/signing and updates from the first release.

CI supplies DOCZAP_TEST_ZIP and DOCZAP_PREVIOUS_ZIP after building the app.
All installations go into a temporary Applications folder.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
READY = sys.platform == "darwin" and all(
    os.environ.get(name) for name in ("DOCZAP_TEST_ZIP", "DOCZAP_PREVIOUS_ZIP")
)


@unittest.skipUnless(READY, "requires macOS and built/previous release archives")
class NativeInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="doczap native installer ")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()
        self.apps = self.folder / "Applications with spaces"
        self.apps.mkdir()
        self.app = self.apps / "DocZap.app"
        self.archive = Path(os.environ["DOCZAP_TEST_ZIP"]).resolve()
        self.previous = Path(os.environ["DOCZAP_PREVIOUS_ZIP"]).resolve()
        result = self.install(self.previous)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.version(), "0.1.0")
        self.original_executable = (self.app / "Contents/MacOS/DocZap").read_bytes()

    def install(self, archive: Path, **environment) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(ROOT / "install.sh")],
            env={**os.environ, "DOCZAP_APPS_DIR": str(self.apps), "DOCZAP_ZIP_URL": archive.as_uri(), **environment},
            capture_output=True,
            text=True,
            timeout=120,
        )

    def version(self) -> str:
        with (self.app / "Contents/Info.plist").open("rb") as plist:
            return plistlib.load(plist)["CFBundleShortVersionString"]

    def assert_preserved(self, result) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.version(), "0.1.0")
        self.assertEqual((self.app / "Contents/MacOS/DocZap").read_bytes(), self.original_executable)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(self.app)], check=True)
        self.assertEqual(list(self.apps.iterdir()), [self.app])

    def test_update_from_v010(self) -> None:
        extracted = self.folder / "expected"
        extracted.mkdir()
        subprocess.run(["ditto", "-x", "-k", str(self.archive), str(extracted)], check=True)
        with (extracted / "DocZap.app/Contents/Info.plist").open("rb") as plist:
            expected = plistlib.load(plist)["CFBundleShortVersionString"]
        result = self.install(self.archive)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.version(), expected)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(self.app)], check=True)
        self.assertEqual(list(self.apps.iterdir()), [self.app])

        subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_app.py"), str(self.app / "Contents/MacOS/DocZap")],
            check=True,
            timeout=120,
        )

    def test_missing_bundle_preserves_v010(self) -> None:
        archive = self.folder / "missing.zip"
        with zipfile.ZipFile(archive, "w") as contents:
            contents.writestr("README.txt", "No application bundle")
        self.assert_preserved(self.install(archive))

    def test_invalid_signature_preserves_v010(self) -> None:
        extracted = self.folder / "unsigned"
        extracted.mkdir()
        subprocess.run(["ditto", "-x", "-k", str(self.archive), str(extracted)], check=True)
        plist_path = extracted / "DocZap.app/Contents/Info.plist"
        with plist_path.open("rb") as plist:
            info = plistlib.load(plist)
        info["CFBundleShortVersionString"] = "999.0.0"
        with plist_path.open("wb") as plist:
            plistlib.dump(info, plist)
        archive = self.folder / "invalid signature.zip"
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(extracted / "DocZap.app"), str(archive)], check=True)
        self.assert_preserved(self.install(archive))

    def test_failed_move_restores_v010(self) -> None:
        binaries = self.folder / "bin"
        binaries.mkdir()
        move = binaries / "mv"
        move.write_text(
            '#!/bin/sh\n'
            'case "$1" in */.doczap-install.*/DocZap.app) exit 1;; esac\n'
            'exec /bin/mv "$@"\n'
        )
        move.chmod(0o755)
        self.assert_preserved(self.install(self.archive, PATH=f"{binaries}{os.pathsep}{os.environ['PATH']}"))


if __name__ == "__main__":
    unittest.main()

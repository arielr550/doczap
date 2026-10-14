"""Build the DocZap desktop app with PyInstaller.

    uv run --managed-python --group build python scripts/build_app.py

On macOS this writes dist/DocZap.app. The app carries its own Python, so it
needs only LibreOffice on the machine that runs it. The uv-managed Python is
required because it includes Tk, which Homebrew's Python does not.
"""

from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
ICON_PATH = PROJECT_ROOT / "assets" / "logo.png"
APP_NAME = "DocZap"
BUNDLE_ID = "io.github.arielr550.doczap"
ENTRY_SCRIPT = "from doczap.desktop import main\n\nraise SystemExit(main())\n"


def project_version() -> str:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    if match is None:
        raise RuntimeError("Could not read the version from pyproject.toml")
    return match.group(1)


def check_python() -> None:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        raise SystemExit(
            "This Python has no Tk, so the app window cannot be built. Run with "
            "`uv run --managed-python --group build python scripts/build_app.py`."
        ) from None


def run_pyinstaller() -> None:
    from PyInstaller.__main__ import run

    BUILD_DIR.mkdir(exist_ok=True)
    # Launching through a module inside the package keeps doczap's data files
    # (the window logo) where doczap.desktop expects them.
    entry = BUILD_DIR / f"{APP_NAME}.py"
    entry.write_text(ENTRY_SCRIPT, encoding="utf-8")
    run(
        [
            str(entry),
            "--name", APP_NAME,
            "--windowed",
            "--icon", str(ICON_PATH),
            "--osx-bundle-identifier", BUNDLE_ID,
            "--collect-data", "doczap",
            "--distpath", str(DIST_DIR),
            "--workpath", str(BUILD_DIR / "pyinstaller"),
            "--specpath", str(BUILD_DIR),
            "--noconfirm",
            "--clean",
            "--log-level", "WARN",
        ]
    )


def finish_macos_app(app: Path) -> None:
    plist_path = app / "Contents" / "Info.plist"
    with plist_path.open("rb") as plist_file:
        info = plistlib.load(plist_file)
    version = project_version()
    info.update(
        {
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "NSHumanReadableCopyright": "MIT License",
            # Lets people drop documents on the Dock icon or use "Open With".
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Word Document",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": ["org.openxmlformats.wordprocessingml.document"],
                }
            ],
        }
    )
    with plist_path.open("wb") as plist_file:
        plistlib.dump(info, plist_file)

    # Editing Info.plist breaks PyInstaller's ad-hoc signature, so sign again.
    result = subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(app)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not sign {app.name}: {result.stderr.strip()}")

    # PyInstaller also leaves the unbundled folder next to the app.
    shutil.rmtree(DIST_DIR / APP_NAME, ignore_errors=True)


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("Building the app is only supported on macOS so far.")
    check_python()
    run_pyinstaller()
    app = DIST_DIR / f"{APP_NAME}.app"
    finish_macos_app(app)
    print(f"Built {app}")


if __name__ == "__main__":
    main()

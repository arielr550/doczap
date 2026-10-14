"""Build the DocZap desktop app with PyInstaller.

macOS writes dist/DocZap.app, which needs LibreOffice installed, and a zip of
it for releases:

    uv run --managed-python --group build python scripts/build_app.py

Windows writes a portable dist/DocZap folder with LibreOffice inside, plus a
zip of it. Pass the official LibreOffice installer to take LibreOffice from:

    uv run --managed-python --group build python scripts/build_app.py --libreoffice-msi LibreOffice.msi

The uv-managed Python is required because it includes Tk, which Homebrew's
Python does not.
"""

from __future__ import annotations

import argparse
import platform
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
# The tile inside the 1024 px icon, without the margin macOS icons keep.
ICON_TILE = (100, 100, 924, 924)
APP_NAME = "DocZap"
BUNDLE_ID = "io.github.arielr550.doczap"
ENTRY_SCRIPT = "from doczap.desktop import main\n\nraise SystemExit(main())\n"
# Per-language settings in LibreOffice's share/registry.
LANGUAGE_SETTINGS = ("Langpack-", "cjk_", "ctl_", "ctlseqcheck_")
# The dictionaries (spelling and hyphenation) of a default English install.
KEPT_EXTENSIONS = {"dict-en", "dict-es", "dict-fr"}


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


def run_pyinstaller(icon: Path, *extra: str) -> None:
    from PyInstaller.__main__ import run

    # Launching through a module inside the package keeps doczap's data files
    # (the window logo) where doczap.desktop expects them.
    entry = BUILD_DIR / f"{APP_NAME}.py"
    entry.write_text(ENTRY_SCRIPT, encoding="utf-8")
    run(
        [
            str(entry),
            "--name", APP_NAME,
            "--windowed",
            "--icon", str(icon),
            "--collect-data", "doczap",
            "--distpath", str(DIST_DIR),
            "--workpath", str(BUILD_DIR / "pyinstaller"),
            "--specpath", str(BUILD_DIR),
            "--noconfirm",
            "--clean",
            "--log-level", "WARN",
            *extra,
        ]
    )


# macOS


def build_macos() -> Path:
    run_pyinstaller(ICON_PATH, "--osx-bundle-identifier", BUNDLE_ID)
    app = DIST_DIR / f"{APP_NAME}.app"

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

    # ditto keeps the app's symlinks and signature intact, unlike zipfile.
    archive = DIST_DIR / f"{APP_NAME}-macos-{platform.machine()}.zip"
    archive.unlink(missing_ok=True)
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(archive)], check=True)
    print(f"Built {app}")
    return archive


# Windows


def windows_icon() -> Path:
    from PIL import Image

    icon = BUILD_DIR / f"{APP_NAME}.ico"
    with Image.open(ICON_PATH) as image:
        # Windows icons fill their square, so drop the macOS margin.
        image.crop(ICON_TILE).save(icon, sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])
    return icon


def extract_libreoffice(msi: Path, destination: Path) -> None:
    """Unpack the LibreOffice installer into a folder without installing it.

    An administrative install (msiexec /a) only copies the files out, so the
    result runs from any folder and leaves no trace in the system.
    """
    image = BUILD_DIR / "libreoffice"
    shutil.rmtree(image, ignore_errors=True)
    log = BUILD_DIR / "msiexec.log"
    # msiexec wants the quotes inside the property, so this has to be a string.
    command = f'msiexec /a "{msi.resolve()}" /qn /l*v "{log}" TARGETDIR="{image}"'
    if subprocess.run(command, check=False).returncode != 0:
        raise RuntimeError(f"msiexec could not unpack {msi.name}; see {log}")

    soffice = next(image.rglob("program/soffice.exe"), None)
    if soffice is None:
        raise RuntimeError(f"No program/soffice.exe in the unpacked {msi.name}")
    shutil.rmtree(destination, ignore_errors=True)
    shutil.move(str(soffice.parent.parent), str(destination))
    # The administrative install keeps a copy of the installer database.
    for leftover in destination.glob("*.msi"):
        leftover.unlink()

    # The installer would put LibreOffice's fonts (Carlito, Caladea, Liberation
    # and others) into C:\Windows\Fonts. LibreOffice also loads fonts from its
    # own share/fonts/truetype, so they go there and stay inside the bundle.
    fonts = destination / "share" / "fonts" / "truetype"
    fonts.mkdir(parents=True, exist_ok=True)
    for font in (destination / "Fonts").iterdir():
        shutil.move(str(font), str(fonts / font.name))
    (destination / "Fonts").rmdir()

    # LibreOffice needs the Visual C++ runtime, which the installer would put
    # into C:\Windows\System32. Keeping the DLLs next to soffice.exe lets the
    # bundle run on PCs without that runtime installed.
    for dll in (destination / "System64").glob("*.dll"):
        target = destination / "program" / dll.name
        if not target.exists():
            shutil.move(str(dll), str(target))
    for system_dir in ("System", "System64"):
        shutil.rmtree(destination / system_dir, ignore_errors=True)

    keep_english_only(destination)


def keep_english_only(libreoffice: Path) -> None:
    """Remove what a default English install leaves out.

    The administrative install unpacks every language. LibreOffice reads all of
    their settings and dictionaries on each start, which made a conversion take
    about four seconds instead of under one. What remains matches a default
    install on an English system.
    """
    # Interface translations and help play no part in rendering a document.
    # program/resource/common stays: it holds OpenSymbol, the font for bullets.
    for translation in (libreoffice / "program" / "resource").iterdir():
        if translation.name != "common":
            shutil.rmtree(translation)
    shutil.rmtree(libreoffice / "help", ignore_errors=True)

    registry = libreoffice / "share" / "registry"
    for settings in registry.glob("*.xcd"):
        if settings.name.startswith(LANGUAGE_SETTINGS) and not settings.name.startswith("Langpack-en-"):
            settings.unlink()
    for settings in (registry / "res").glob("*.xcd"):
        if not re.search(r"_en-[A-Z]{2}$", settings.stem):
            settings.unlink()

    for extension in (libreoffice / "share" / "extensions").iterdir():
        if extension.name not in KEPT_EXTENSIONS:
            shutil.rmtree(extension)


def folder_size(folder: Path) -> str:
    size = sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
    return f"{size / 1_000_000:.0f} MB"


def build_windows(msi: Path) -> Path:
    run_pyinstaller(windows_icon())
    app_dir = DIST_DIR / APP_NAME
    extract_libreoffice(msi, app_dir / "LibreOffice")

    # No version in the name, so the "latest release" download link never changes.
    archive = DIST_DIR / f"{APP_NAME}-windows-x64"
    archive = Path(shutil.make_archive(str(archive), "zip", root_dir=DIST_DIR, base_dir=APP_NAME))
    print(
        f"{app_dir.name}: {folder_size(app_dir)}, of which LibreOffice "
        f"{folder_size(app_dir / 'LibreOffice')}; {archive.name}: "
        f"{archive.stat().st_size / 1_000_000:.0f} MB"
    )
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the DocZap desktop app.")
    parser.add_argument(
        "--libreoffice-msi",
        type=Path,
        help="Windows only: the official LibreOffice .msi installer to bundle.",
    )
    args = parser.parse_args()

    check_python()
    BUILD_DIR.mkdir(exist_ok=True)
    if sys.platform == "darwin":
        built = build_macos()
    elif sys.platform == "win32":
        if args.libreoffice_msi is None:
            parser.error("--libreoffice-msi is required on Windows")
        built = build_windows(args.libreoffice_msi)
    else:
        raise SystemExit("The desktop app can be built on macOS and Windows only.")
    print(f"Built {built}")


if __name__ == "__main__":
    main()

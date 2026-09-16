from __future__ import annotations

import plistlib
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
APP_PATH = DIST_DIR / "DocZap.app"
PACKAGE_DIR = PROJECT_ROOT / "src" / "doczap"
LOGO_PATH = PROJECT_ROOT / "assets" / "logo.svg"
ICON_SIZES = (16, 32, 128, 256, 512)
UNUSED_PRIVACY_KEYS = (
    "NSAppleEventsUsageDescription",
    "NSAppleMusicUsageDescription",
    "NSCalendarsUsageDescription",
    "NSCameraUsageDescription",
    "NSContactsUsageDescription",
    "NSHomeKitUsageDescription",
    "NSMicrophoneUsageDescription",
    "NSPhotoLibraryUsageDescription",
    "NSRemindersUsageDescription",
    "NSSiriUsageDescription",
    "NSSystemAdministrationUsageDescription",
)

APPLESCRIPT = r'''
use scripting additions

on convertFiles(selectedFiles)
    set runnerPath to (POSIX path of (path to me)) & "Contents/Resources/run-converter"
    set commandText to quoted form of runnerPath

    repeat with selectedFile in selectedFiles
        set commandText to commandText & space & quoted form of POSIX path of selectedFile
    end repeat

    try
        set resultMessage to do shell script commandText
        display notification resultMessage with title "DocZap"
    on error errorMessage number errorNumber
        if errorNumber is not -128 then
            display alert "Conversion failed" message errorMessage as critical
        end if
    end try
end convertFiles

on run
    try
        set selectedFiles to choose file with prompt "Choose DOCX files to convert" ¬
            of type {"org.openxmlformats.wordprocessingml.document"} ¬
            with multiple selections allowed
        convertFiles(selectedFiles)
    on error errorMessage number errorNumber
        if errorNumber is not -128 then
            display alert "Could not select files" as critical
        end if
    end try
end run

on open droppedFiles
    convertFiles(droppedFiles)
end open
'''

RUNNER = r'''#!/bin/sh
set -eu

RESOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export UV_CACHE_DIR="${TMPDIR:-/tmp}/doczap-uv-cache"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$RESOURCE_DIR"

if command -v uv >/dev/null 2>&1; then
    UV_BINARY=$(command -v uv)
else
    osascript -e 'display alert "DocZap needs uv" message "Install uv, then open the app again." as critical'
    exit 1
fi

exec "$UV_BINARY" run --offline --no-project --python '>=3.10' python -m doczap.desktop "$@"
'''


def run_tool(command: list[str], action: str) -> None:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"Could not {action}: {reason}")


def compile_applescript() -> None:
    DIST_DIR.mkdir(exist_ok=True)
    if APP_PATH.exists():
        shutil.rmtree(APP_PATH)

    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as source:
        source.write(APPLESCRIPT)
        source_path = Path(source.name)

    try:
        run_tool(["osacompile", "-o", str(APP_PATH), str(source_path)], "compile the macOS app")
    finally:
        source_path.unlink(missing_ok=True)


def copy_runtime() -> None:
    resources = APP_PATH / "Contents" / "Resources"
    shutil.copytree(
        PACKAGE_DIR,
        resources / "doczap",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    runner_path = resources / "run-converter"
    runner_path.write_text(RUNNER, encoding="utf-8")
    runner_path.chmod(runner_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_icon() -> None:
    """Render assets/logo.svg into the app icon, replacing the default droplet."""
    resources = APP_PATH / "Contents" / "Resources"
    with tempfile.TemporaryDirectory() as temp_dir:
        master = Path(temp_dir) / "logo.png"
        run_tool(
            ["sips", "-s", "format", "png", str(LOGO_PATH), "--out", str(master)],
            "render the logo",
        )
        iconset = Path(temp_dir) / "DocZap.iconset"
        iconset.mkdir()
        for size in ICON_SIZES:
            for scale in (1, 2):
                pixels = str(size * scale)
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                run_tool(
                    ["sips", "-z", pixels, pixels, str(master), "--out", str(iconset / name)],
                    "resize the icon",
                )
        run_tool(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(resources / "DocZap.icns")],
            "build the app icon",
        )
    for default_icon in ("droplet.icns", "Assets.car"):
        (resources / default_icon).unlink(missing_ok=True)


def project_version() -> str:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    if match is None:
        raise RuntimeError("Could not read the version from pyproject.toml")
    return match.group(1)


def configure_app() -> None:
    plist_path = APP_PATH / "Contents" / "Info.plist"
    with plist_path.open("rb") as plist_file:
        info = plistlib.load(plist_file)

    for key in (*UNUSED_PRIVACY_KEYS, "CFBundleIconName"):
        info.pop(key, None)

    info.update(
        {
            "CFBundleIdentifier": "io.github.arielr550.doczap",
            "CFBundleName": "DocZap",
            "CFBundleDisplayName": "DocZap",
            "CFBundleIconFile": "DocZap",
            "CFBundleShortVersionString": project_version(),
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Word Document",
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": [
                        "org.openxmlformats.wordprocessingml.document"
                    ],
                }
            ],
        }
    )

    with plist_path.open("wb") as plist_file:
        plistlib.dump(info, plist_file)


def sign_app() -> None:
    run_tool(["codesign", "--force", "--deep", "--sign", "-", str(APP_PATH)], "sign the macOS app")


def main() -> None:
    compile_applescript()
    copy_runtime()
    install_icon()
    configure_app()
    sign_app()
    print(f"Built {APP_PATH}")


if __name__ == "__main__":
    main()

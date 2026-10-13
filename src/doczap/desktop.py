"""Helper behind the macOS app: converts files chosen in Finder beside the originals."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from doczap.conversion import convert_document, default_output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DocZap desktop conversion helper.")
    parser.add_argument("files", nargs="+", help="DOCX files selected in Finder.")
    return parser


def confirm_overwrite(output_path: Path) -> bool:
    script = """
on run argv
    set outputName to item 1 of argv
    set answer to display dialog (outputName & " already exists. Replace it?") ¬
        with title "DocZap" buttons {"Skip", "Replace"} default button "Skip" ¬
        cancel button "Skip" with icon caution
    return button returned of answer
end run
"""
    result = subprocess.run(
        ["osascript", "-e", script, output_path.name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "Replace"


def convert_files(files: list[str]) -> tuple[list[Path], list[str], int]:
    converted: list[Path] = []
    errors: list[str] = []
    skipped = 0

    for file_name in files:
        input_path = Path(file_name).expanduser().resolve()
        output_path = default_output_path(input_path)
        overwrite = False

        if output_path.exists():
            overwrite = confirm_overwrite(output_path)
            if not overwrite:
                skipped += 1
                continue

        try:
            converted.append(
                convert_document(input_path, output_path, overwrite=overwrite)
            )
        except Exception as exc:
            errors.append(f"{input_path.name}: {exc}")

    return converted, errors, skipped


def format_summary(converted: list[Path], skipped: int) -> str:
    if len(converted) == 1:
        summary = f"Created {converted[0].name} beside the original."
    elif converted:
        summary = f"Created {len(converted)} PDFs beside the originals."
    else:
        summary = "No files were converted."

    if skipped:
        summary += f" Skipped {skipped} existing file{'s' if skipped != 1 else ''}."
    return summary


def main() -> int:
    args = build_parser().parse_args()
    converted, errors, skipped = convert_files(args.files)

    if errors:
        print("\n".join([format_summary(converted, skipped), *errors]), file=sys.stderr)
        return 1

    print(format_summary(converted, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())

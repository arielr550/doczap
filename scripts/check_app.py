"""Check a frozen app: its license notices, and real conversions and merges.

Usage: uv run python scripts/check_app.py dist/DocZap/DocZap.exe

On Windows, set LIBREOFFICE_BUILD to the bundled build, such as 26.2.7.3.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader

# Reuse the small DOCX fixture. Only the child app converts and merges.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from build_app import notice_names
from test_integration import write_minimal_docx


def check_notices(executable: Path) -> None:
    if sys.platform == "darwin":
        notices = executable.parents[1] / "Resources" / "Licenses"
    else:
        notices = executable.parent / "Licenses"
    missing = [name for name in notice_names() if not (notices / name).is_file()]
    if missing:
        raise RuntimeError(f"The packaged app is missing license notices: {missing}")
    if sys.platform == "win32":
        # The Windows app bundles LibreOffice, so it points to its source.
        source = (notices / "LibreOffice-source.txt").read_text(encoding="utf-8")
        build = os.environ.get("LIBREOFFICE_BUILD", "")
        if f"/libreoffice/old/{build}" not in source:
            raise RuntimeError(f"The LibreOffice source notice does not point to {build}")
        for name in ("LICENSE.html", "NOTICE"):
            if not (executable.parent / "LibreOffice" / name).is_file():
                raise RuntimeError(f"The bundled LibreOffice has no {name}")
    print(f"License notices present in {notices}", flush=True)


def main() -> None:
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise SystemExit(f"App executable not found: {executable}")

    check_notices(executable)

    def run(*arguments: str) -> int:
        result = subprocess.run(
            [str(executable), *arguments], capture_output=True, text=True, timeout=90
        )
        print(f"{' '.join(Path(argument).name for argument in arguments)}: exit {result.returncode}", flush=True)
        if result.stdout:
            print(result.stdout, flush=True)
        if result.stderr:
            print(result.stderr, flush=True)
        return result.returncode

    def convert(source: Path, output: Path, *, overwrite: bool = False) -> int:
        return run("--convert", str(source), str(output), *(["--overwrite"] if overwrite else []))

    with tempfile.TemporaryDirectory(prefix="doczap frozen check ") as temporary:
        folder = Path(temporary)
        source = folder / "résumé draft.docx"
        output = folder / "converted report.pdf"
        write_minimal_docx(source)
        original = source.read_bytes()
        if convert(source, output) != 0 or not output.read_bytes().startswith(b"%PDF"):
            raise RuntimeError("The packaged app could not convert a real DOCX")
        pdf = output.read_bytes()
        if convert(source, output) == 0 or output.read_bytes() != pdf:
            raise RuntimeError("The packaged app replaced a PDF without consent")
        source.write_bytes(b"unreadable DOCX")
        if convert(source, output, overwrite=True) == 0 or output.read_bytes() != pdf:
            raise RuntimeError("A failed packaged conversion damaged the old PDF")
        source.write_bytes(original)
        output.write_bytes(b"old PDF")
        if convert(source, output, overwrite=True) != 0 or not output.read_bytes().startswith(b"%PDF"):
            raise RuntimeError("The packaged app could not replace a PDF with consent")
        if source.read_bytes() != original:
            raise RuntimeError("The packaged app modified the source DOCX")

        # Merge two real PDFs, the second one converted by the app as well.
        second = folder / "second.pdf"
        if convert(source, second) != 0:
            raise RuntimeError("The packaged app could not convert a second DOCX")
        merged = folder / "merged ü.pdf"
        if run("--check-merge", str(merged), str(output), str(second)) != 0:
            raise RuntimeError("The packaged app could not merge PDFs")
        if len(PdfReader(merged).pages) != len(PdfReader(output).pages) + len(PdfReader(second).pages):
            raise RuntimeError("The packaged merge lost pages")
        merged_pdf = merged.read_bytes()
        if run("--check-merge", str(merged), str(output), str(second)) == 0 or merged.read_bytes() != merged_pdf:
            raise RuntimeError("The packaged app replaced a merged PDF without consent")

        expected = sorted([source.name, output.name, second.name, merged.name])
        if sorted(path.name for path in folder.iterdir()) != expected:
            raise RuntimeError("The packaged app left temporary files")
    print("Packaged conversion and merge checks passed", flush=True)


if __name__ == "__main__":
    main()

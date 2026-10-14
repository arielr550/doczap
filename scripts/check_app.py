"""Check real conversions through a frozen app, including failure preservation.

Usage: uv run python scripts/check_app.py dist/DocZap/DocZap.exe
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

# Reuse the small DOCX fixture. Only the child app performs the conversions.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_integration import write_minimal_docx


def main() -> None:
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise SystemExit(f"App executable not found: {executable}")

    def convert(source: Path, output: Path, *, overwrite: bool = False) -> int:
        command = [str(executable), "--convert", str(source), str(output)]
        if overwrite:
            command.append("--overwrite")
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        print(f"{source.name}: exit {result.returncode}", flush=True)
        if result.stdout:
            print(result.stdout, flush=True)
        if result.stderr:
            print(result.stderr, flush=True)
        return result.returncode

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
        if sorted(path.name for path in folder.iterdir()) != sorted([source.name, output.name]):
            raise RuntimeError("The packaged app left temporary conversion files")
    print("Packaged conversion checks passed", flush=True)


if __name__ == "__main__":
    main()

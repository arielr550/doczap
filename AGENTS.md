# AGENTS.md

## Project Overview

Build **DocZap**, a **local, private, high-fidelity DOCX → PDF converter**.

The tool must:

* Preserve formatting exactly (layout, pagination, fonts, spacing)
* Run fully offline (no network calls)
* Be fast, minimal, and reliable
* Be designed for future extensibility (additional formats, engines)

---

## Non-Negotiable Constraints

1. **Local-only execution**

   * No APIs
   * No cloud services
   * No external network calls

2. **High fidelity conversion**

   * Output PDF must visually match the DOCX
   * No layout reconstruction using Python libraries

3. **Use LibreOffice as rendering engine**

   * Always use headless mode
   * Do NOT implement custom DOCX parsing/rendering

4. **Python environment must use `uv`**

   * All dependency management and execution via `uv`
   * Never use pip, pipenv, poetry, or conda

---

## Core Architecture

### 1. CLI Entry Point

The tool must be runnable as:

```bash
uv run python main.py input.docx [output.pdf] [--overwrite]
```

The output path defaults to the input path with a `.pdf` suffix.

Future support:

* Batch conversion
* Directory input
* Format auto-detection

---

### 2. Converter Abstraction

Define a base interface:

```python
class Converter:
    def convert(self, input_path: str, output_path: str) -> None:
        raise NotImplementedError
```

Do NOT hardcode specific tools in CLI logic.

---

### 3. LibreOffice Backend

Primary implementation:

* Uses `soffice` in headless mode
* Command:

```bash
soffice --headless --convert-to pdf --outdir <output_dir> <input_file>
```

Responsibilities:

* Execute subprocess safely
* Capture return codes
* Detect failures
* Handle output file naming

---

## Implementation Rules

### File Handling

* Validate input file exists
* Ensure output path is valid
* Do NOT overwrite files without explicit permission
* Use temporary directories when needed

### Error Handling

Fail loudly and clearly on:

* Missing input file
* Unsupported format
* LibreOffice not installed or not found
* Conversion failure

### Logging

Minimal but structured:

* Conversion started
* Conversion succeeded
* Conversion failed (with reason)

---

## Performance Requirements

* Conversion should complete within ~1–2 seconds for typical documents
* Avoid unnecessary file copying
* Avoid loading entire files into memory

---

## System Dependency

The system must have:

* LibreOffice installed and accessible via `soffice`

The program must:

* Detect if `soffice` is available in PATH, falling back to the platform's
  standard install location (for example `LibreOffice.app` on macOS)
* Provide a clear error if not found

---

## Extensibility Design

The system must be designed to support:

### Additional Formats

Examples:

* DOCX → HTML
* DOCX → TXT
* PDF → TXT

### Additional Engines

Examples:

* Pandoc
* Custom pipelines

This requires:

* Pluggable converter classes
* No tight coupling between CLI and backend

---

## Project Structure

```
project_root/
│
├── main.py                  # thin shim: uv run python main.py
├── doczap                   # shell launcher for the CLI
├── assets/logo.svg          # logo, also rendered into the macOS app icon
├── src/doczap/
│   ├── cli.py               # CLI (installed as the `doczap` command)
│   ├── desktop.py           # helper invoked by the macOS app
│   ├── conversion.py        # validation + converter selection
│   ├── system.py            # all OS-specific details (paths, locking)
│   ├── converters/
│   │   ├── base.py
│   │   └── libreoffice.py
│   └── utils/
│       └── file_ops.py
├── scripts/
│   └── build_macos_app.py   # builds dist/DocZap.app (macOS only, not committed)
├── tests/
│   ├── test_conversion.py   # unit tests, LibreOffice mocked
│   └── test_integration.py  # real conversion, skipped without soffice
├── .github/workflows/tests.yml  # CI: unit tests on macOS and Ubuntu
├── AGENTS.md
└── README.md
```

### Cross-platform groundwork

macOS is the only supported platform today; Linux and Windows are planned.
Keep the core platform-neutral:

* Put anything OS-specific (install paths, cache locations, file locking) in
  `src/doczap/system.py`, never directly in converters or the CLI
* Do not import POSIX-only modules (such as `fcntl`) outside `system.py`
* Desktop front ends (like the macOS app) stay thin wrappers over `conversion.py`

---

## Coding Guidelines

* Keep code simple and explicit
* Avoid over-engineering
* Prefer standard library over dependencies
* Use type hints where useful
* Keep functions small and testable

---

## Forbidden Approaches

DO NOT:

* Use python-docx for rendering
* Use ReportLab for layout reconstruction
* Use any cloud-based conversion APIs
* Attempt to manually rebuild document layout

These approaches will break formatting fidelity.

---

## Future Enhancements (Optional Tasks)

* Batch conversion:

  ```bash
  doczap *.docx
  ```

* Directory watch mode

* Single binary packaging (PyInstaller)

* Persistent LibreOffice process for performance

---

## Success Criteria

The implementation is correct if:

* The output PDF visually matches the DOCX
* The tool runs locally with no network usage
* The CLI works reliably
* The architecture allows easy extension

---

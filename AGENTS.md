# DocZap

Local, private DOCX → PDF converter. A real rendering engine (LibreOffice,
headless) does the layout, so the PDF matches the original document.

## Invariants

- No network use at run time. Privacy is the reason this tool exists.
- Do not rebuild document layout in Python (python-docx, ReportLab, and the
  like). It breaks fidelity; rendering belongs to a real engine.
- Never replace a user's file without explicit consent.
- Use `uv` for all Python work.

## Tests

```bash
uv run --offline python -m unittest discover -s tests
```

The integration tests are skipped when LibreOffice is not installed.

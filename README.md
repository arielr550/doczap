# DocZap

Fast, local, private DOCX → PDF conversion that keeps the layout intact.

Rendering is done by LibreOffice in headless mode, so the PDF matches what Word
shows. Nothing leaves your machine — no cloud APIs, no network calls.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Homebrew or the official installer)
- LibreOffice — `brew install --cask libreoffice`, or the `.dmg` into `/Applications`

## Usage

### macOS app

Build it once (and again after changing the source):

```bash
uv run --offline python scripts/build_macos_app.py
```

Open `dist/DocZap.app` and pick one or more Word documents, or drag DOCX files
onto it. Each PDF is saved next to its original, and you're asked before anything
is replaced. The app can be moved to `/Applications` or the Desktop.

### Command line

Save the PDF beside the DOCX:

```bash
./doczap report.docx
```

Or choose the output path (add `--overwrite` to replace an existing file):

```bash
uv run --offline python main.py input.docx output.pdf
```

## Fonts

Pagination only matches Word when the document's fonts are available to
LibreOffice. Microsoft's defaults (Calibri, Cambria) are usually missing on a Mac,
and missing fonts are silently substituted, which shifts line breaks and page
counts. Install the metric-compatible replacements:

```bash
brew install --cask font-carlito font-caladea
```

For other fonts (Aptos, for example), install the font files system-wide.

## Notes

- Runs only when you open it — no login item, background service, or watcher.
- LibreOffice exits after each conversion, with a 60-second timeout.
- Web-linked images are not downloaded, so they are left out of the PDF.
- Converts into a temporary file first, so a failed run never leaves a stale PDF.

## Extending

Add a converter class implementing `Converter` (`converters/base.py`), then route
to it from `select_converter(...)` in `conversion.py`. The CLI stays unchanged.

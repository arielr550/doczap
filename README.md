# DocZap

Fast, local, private DOCX → PDF conversion that keeps the layout intact.

Rendering is done by LibreOffice in headless mode, so the PDF matches what Word
shows. Nothing leaves your machine — no cloud APIs, no network calls.

## Requirements

- LibreOffice — `brew install --cask libreoffice`, or the `.dmg` into `/Applications`.
  The Windows app includes its own copy.
- [uv](https://docs.astral.sh/uv/) (Homebrew or the official installer), to run
  DocZap from source or build the app. The built app does not need it.

## Usage

### macOS app

Build it once (and again after changing the source):

```bash
uv run --managed-python --group build python scripts/build_app.py
```

The first build downloads PyInstaller. `--managed-python` matters: the app window
needs Tk, which Homebrew's Python leaves out.

Open `dist/DocZap.app`, add one or more Word documents (or drop them on the
DocZap icon), choose whether each PDF goes next to its document or into one
folder, and click **Convert to PDF**. You're asked before any existing PDF is
replaced. The app can be moved to `/Applications` or the Desktop.

To try the window without building, run
`uv run --managed-python python -m doczap.desktop`.

### Windows app

The Windows build is portable and includes LibreOffice, so there is nothing to
install. Extract `DocZap-<version>-windows-x64.zip` anywhere and run
`DocZap.exe` from the `DocZap` folder. It works like the macOS app; you can also
drop documents on `DocZap.exe`.

The app is not code-signed, so the first time Windows may show "Windows
protected your PC". Choose **More info**, then **Run anyway**.

To build it on Windows, download the LibreOffice installer
(`LibreOffice_<version>_Win_x86-64.msi` from libreoffice.org) and run:

```powershell
uv run --managed-python --group build python scripts/build_app.py --libreoffice-msi LibreOffice_<version>_Win_x86-64.msi
```

CI builds the zip on every pull request and keeps it for 14 days as a workflow
artifact.

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

Add a converter class implementing `Converter`
(`src/doczap/converters/base.py`), then route to it from `select_converter(...)`
in `src/doczap/conversion.py`. The CLI stays unchanged.

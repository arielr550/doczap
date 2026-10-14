# DocZap

Fast, local, private DOCX → PDF conversion that keeps the layout intact.

Rendering is done by LibreOffice in headless mode, so the PDF matches what Word
shows. Nothing leaves your machine — no cloud APIs, no network calls.

## Install

### macOS (Apple silicon)

```bash
curl -fsSL https://raw.githubusercontent.com/arielr550/doczap/main/install.sh | sh
```

This puts the latest DocZap into Applications; run it again to update. DocZap
also needs LibreOffice (`brew install --cask libreoffice`, or the `.dmg` from
[libreoffice.org](https://www.libreoffice.org/download/)), and the installer
tells you if it is missing.

DocZap is not notarized by Apple. The installer avoids the warning that brings,
because macOS only checks files downloaded by a browser. If you download the zip
from the releases page in a browser instead, open DocZap once, then allow it in
**System Settings → Privacy & Security → Open Anyway**.

### Windows

Download [DocZap-windows-x64.zip](https://github.com/arielr550/doczap/releases/latest/download/DocZap-windows-x64.zip),
extract it anywhere, and run `DocZap.exe` in the `DocZap` folder. LibreOffice is
included, so there is nothing else to install.

DocZap is not code-signed, so the first time Windows may show "Windows protected
your PC". Choose **More info**, then **Run anyway**.

## Usage

Open DocZap, add one or more Word documents (or drop them on the DocZap icon),
choose whether each PDF goes next to its document or into one folder, and click
**Convert to PDF**. You're asked before any existing PDF is replaced.

### Command line

From a clone of this repository (needs [uv](https://docs.astral.sh/uv/) and
LibreOffice), save the PDF beside the DOCX:

```bash
./doczap report.docx
```

Or choose the output path (add `--overwrite` to replace an existing file):

```bash
uv run --offline python main.py input.docx output.pdf
```

## Building from source

You need [uv](https://docs.astral.sh/uv/), and LibreOffice on macOS and Linux.

### macOS app

```bash
uv run --managed-python --group build python scripts/build_app.py
```

This writes `dist/DocZap.app` and a zip of it. The first build downloads
PyInstaller. `--managed-python` matters: the app window needs Tk, which
Homebrew's Python leaves out.

To try the window without building, run
`uv run --managed-python python -m doczap.desktop`.

### Windows app

Download the LibreOffice installer (`LibreOffice_<version>_Win_x86-64.msi` from
libreoffice.org) and run:

```powershell
uv run --managed-python --group build python scripts/build_app.py --libreoffice-msi LibreOffice_<version>_Win_x86-64.msi
```

CI builds both apps on every pull request and keeps them for 14 days as workflow
artifacts.

### Releases

Set the new version in `pyproject.toml`, merge it, then tag that commit:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

CI runs the tests, builds both apps, and publishes a GitHub Release with
`DocZap-macos-arm64.zip` and `DocZap-windows-x64.zip`.

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

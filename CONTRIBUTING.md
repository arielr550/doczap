# Working with DocZap

## Run from source

Install [uv](https://docs.astral.sh/uv/) and the latest
[LibreOffice](https://www.libreoffice.org/download/download-libreoffice/) for
DOCX conversion. From a clone, install the locked dependencies, then run DocZap.

```sh
uv sync --locked
uv run --offline doczap report.docx
```

The CLI saves beside the DOCX by default. Pass a second path to choose the output
and add `--overwrite` to authorize replacing an existing PDF.

The packaged app also supports `--convert` followed by the same arguments.

```sh
/Applications/DocZap.app/Contents/MacOS/DocZap --convert report.docx
```

On Windows, use `DocZap.exe --convert report.docx`.

## Develop and test

```sh
uv run --offline python -m unittest discover -s tests
```

LibreOffice and a working Tk display are needed for integration and desktop tests,
respectively. Use uv-managed Python on macOS to get Tk. To open the source app,
run `uv run --managed-python python -m doczap.desktop`.

Use synthetic fixtures. Keep personal documents, `.env` files, and credentials out
of commits and public issue reports; `.gitignore` excludes DOCX, PDF, and `.env`
files to help.

## Build the desktop app

On macOS, build with the following command.

```sh
uv run --managed-python --python 3.14.10 --group build python scripts/build_app.py
```

On Windows, download the official LibreOffice x64 MSI and pass its path.

```powershell
uv run --managed-python --python 3.14.10 --group build python scripts/build_app.py --libreoffice-msi LibreOffice.msi
```

Build with the Python version in `licenses/python/SOURCE.txt`; the build refuses
others because the bundled notices describe that Python. To change it, run
`scripts/update_python_notices.py` and update `.github/workflows/tests.yml`.

Both builds write archives to `dist/`, with third-party notices in each app's
`Licenses` folder. CI checks the notices, the macOS signature, and a real
conversion and merge through each packaged app. On pull requests, the archives
are kept as workflow artifacts for 14 days.

## Release

Update the version in `pyproject.toml` and regenerate the lockfile. After merging,
tag the release commit with the matching version, such as `v0.2.2`, and push that
tag. CI runs the tests, publishes the macOS and Windows archives to GitHub
Releases, and verifies installation and update recovery on macOS.

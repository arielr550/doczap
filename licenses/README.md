# Third-party notices

`scripts/build_app.py` copies these into each packaged app's `Licenses` folder,
together with DocZap's own license and those of pypdf and PyInstaller, which it
takes from the installed packages.

- `python/`: CPython and the libraries built into uv-managed Python (OpenSSL,
  SQLite, Tcl, zlib and others), taken by `scripts/update_python_notices.py`
  from the python-build-standalone release in `python/SOURCE.txt`. The build
  refuses any other Python version, so refresh them when changing it.
- `Tk.txt`: Tk's `license.terms`, from https://github.com/tcltk/tk.

The Windows app also bundles LibreOffice with its own `LICENSE.html` and
`NOTICE`, and `Licenses/LibreOffice-source.txt` points to the source code of
that exact build.

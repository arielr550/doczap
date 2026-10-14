# Changelog

## 0.1.1

- Preserve PDFs created by another conversion instead of replacing them without consent.
- Save PDFs atomically, including authorized replacements on Windows and external drives.
- Reject output symlinks, directories, and aliases of the source document.
- Preserve or restore the previous macOS app when an installer update fails.
- Stop LibreOffice and its child processes on timeout, cancellation, or application quit.
- Wait for conversion cleanup before closing the desktop window.
- Support `--convert` in the desktop executables for conversion without a window.
- Verify real conversions through packaged apps and macOS updates from v0.1.0 in CI.

## 0.1.0

- First release for Apple silicon macOS and Windows x64.

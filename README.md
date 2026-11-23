# DocZap

Convert Word documents to PDF and merge PDFs on your computer. DocZap uses
LibreOffice for conversion and copies pages directly when merging PDFs.

## Download

| Platform | Get started |
| --- | --- |
| Mac with Apple silicon | Download [DocZap for macOS](https://github.com/arielr550/doczap/releases/latest/download/DocZap-macos-arm64.zip), unzip it, and move DocZap to Applications. Install the latest [LibreOffice](https://www.libreoffice.org/download/download-libreoffice/) for DOCX conversion. |
| Windows x64 | Download [DocZap for Windows](https://github.com/arielr550/doczap/releases/latest/download/DocZap-windows-x64.zip), extract the entire archive, and open `DocZap.exe` inside the `DocZap` folder. LibreOffice is included. |

DocZap is not notarized by Apple or signed by a Windows publisher, so the first
launch shows a warning:

- **macOS:** open DocZap once, then choose **Open Anyway** in **System Settings →
  Privacy & Security**. [Apple explains this here](https://support.apple.com/en-us/102445).
- **Windows:** if "Windows protected your PC" appears, choose **More info**, then
  **Run anyway**.

## Use DocZap

- **Convert to PDF** — Add one or more `.docx` files, choose where to save the
  PDFs, and click **Convert to PDF**. Install the fonts used by the documents
  if exact line breaks and pagination matter.
- **Merge PDFs** — Add two or more PDFs, arrange them in page order, and
  click **Merge PDFs** to choose a destination. PDFs that require an opening
  password must be unlocked first. Some combinations of layered PDFs are
  unsupported and show an error.
- DocZap asks before replacing an existing PDF.

## Privacy and support

DocZap converts and merges files on your computer. It has no telemetry, account,
or upload feature, and it configures LibreOffice to block remote links in
documents, so linked web images are left out of the PDF. PDFs can retain
document information, links, annotations, or hidden layers. Review outputs
before sharing sensitive files.

For help, open a [GitHub issue](https://github.com/arielr550/doczap/issues) with
your DocZap version, operating system, and the steps to reproduce the problem.
Use sample files you can share publicly. Before pasting logs or error messages,
replace file names, folder paths, and document text you would not publish.

See [CONTRIBUTING.md](CONTRIBUTING.md) for command-line use, source builds,
and tests. DocZap is available under the [MIT License](LICENSE). Notices for
the bundled third-party software are in the app's `Licenses` folder (inside
`DocZap.app/Contents/Resources` on macOS).

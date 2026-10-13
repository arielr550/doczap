from __future__ import annotations

import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from doczap.conversion import convert_document
from doczap.converters.libreoffice import find_soffice

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>Hello from DocZap</w:t></w:r></w:p></w:body>
</w:document>"""

LINKED_IMAGE_DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
<w:body><w:p><w:r><w:drawing><wp:inline><wp:extent cx="952500" cy="952500"/><wp:docPr id="1" name="linked"/>
<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>
<pic:nvPicPr><pic:cNvPr id="1" name="linked"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip r:link="rIdImage"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="952500" cy="952500"/></a:xfrm><a:prstGeom prst="rect"/></pic:spPr>
</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p></w:body>
</w:document>"""

LINKED_IMAGE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{image_url}" TargetMode="External"/>
</Relationships>"""


def write_minimal_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as docx:
        docx.writestr("[Content_Types].xml", CONTENT_TYPES)
        docx.writestr("_rels/.rels", RELS)
        docx.writestr("word/document.xml", DOCUMENT)


@unittest.skipUnless(find_soffice(), "LibreOffice (soffice) is not installed")
class LibreOfficeIntegrationTests(unittest.TestCase):
    def test_real_conversion_produces_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "hello.docx"
            write_minimal_docx(input_path)

            output_path = convert_document(input_path)

            self.assertTrue(output_path.read_bytes().startswith(b"%PDF"))

    def test_unreadable_document_fails_even_when_pdf_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "broken.docx"
            input_path.write_bytes(b"not a zip file")
            stale = input_path.with_suffix(".pdf")
            stale.write_bytes(b"old pdf")

            with self.assertRaises(RuntimeError):
                convert_document(input_path, overwrite=True)

            self.assertEqual(stale.read_bytes(), b"old pdf")

    def test_concurrent_conversions_both_succeed(self) -> None:
        # Two soffice processes sharing one profile make one exit 0 without output.
        with tempfile.TemporaryDirectory() as temp_dir:
            docs = [Path(temp_dir) / f"doc{i}.docx" for i in range(2)]
            for doc in docs:
                write_minimal_docx(doc)

            profile_cache = Path(temp_dir) / "cache" / "lo-profile"
            with (
                patch("doczap.converters.libreoffice.profile_cache_dir", return_value=profile_cache),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                outputs = list(pool.map(convert_document, docs))

            for output in outputs:
                self.assertTrue(output.read_bytes().startswith(b"%PDF"))

    def test_remote_linked_image_is_not_fetched(self) -> None:
        requests: list[str] = []

        class Recorder(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                requests.append(self.path)
                self.send_response(404)
                self.end_headers()

            def log_message(self, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        image_url = f"http://127.0.0.1:{server.server_address[1]}/image.png"

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "linked.docx"
            with zipfile.ZipFile(input_path, "w") as docx:
                docx.writestr("[Content_Types].xml", CONTENT_TYPES)
                docx.writestr("_rels/.rels", RELS)
                docx.writestr("word/document.xml", LINKED_IMAGE_DOCUMENT)
                docx.writestr(
                    "word/_rels/document.xml.rels",
                    LINKED_IMAGE_RELS.format(image_url=image_url),
                )

            profile_cache = Path(temp_dir) / "cache" / "lo-profile"
            with patch("doczap.converters.libreoffice.profile_cache_dir", return_value=profile_cache):
                output_path = convert_document(input_path)

            self.assertTrue(output_path.read_bytes().startswith(b"%PDF"))
        self.assertEqual(requests, [])


if __name__ == "__main__":
    unittest.main()

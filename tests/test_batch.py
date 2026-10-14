from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from doczap.batch import Job, Result, format_summary, plan_jobs, run_jobs


def fake_convert(source, output, *, overwrite=False):
    Path(output).write_bytes(b"%PDF")
    return Path(output)


class PlanTests(unittest.TestCase):
    def test_pdfs_go_beside_their_documents_by_default(self) -> None:
        jobs = plan_jobs([Path("/a/one.docx"), Path("/b/two.docx")])
        self.assertEqual([job.output for job in jobs], [Path("/a/one.pdf"), Path("/b/two.pdf")])

    def test_pdfs_go_into_the_chosen_folder(self) -> None:
        jobs = plan_jobs([Path("/a/one.docx"), Path("/b/two.docx")], Path("/out"))
        self.assertEqual([job.output for job in jobs], [Path("/out/one.pdf"), Path("/out/two.pdf")])


class RunTests(unittest.TestCase):
    def test_failures_are_collected_and_the_rest_still_convert(self) -> None:
        def convert(source, output, *, overwrite=False):
            if Path(source).name == "bad.docx":
                raise RuntimeError("LibreOffice could not read it")
            return fake_convert(source, output)

        with tempfile.TemporaryDirectory() as temp_dir:
            jobs = plan_jobs([Path(temp_dir) / "bad.docx", Path(temp_dir) / "good.docx"])
            with patch("doczap.batch.convert_document", side_effect=convert):
                result = run_jobs(jobs)

        self.assertEqual([job.source.name for job in result.converted], ["good.docx"])
        self.assertEqual(result.errors, ["bad.docx: LibreOffice could not read it"])

    def test_same_name_into_one_folder_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir)
            jobs = plan_jobs([Path("/a/report.docx"), Path("/b/report.docx")], out)
            with patch("doczap.batch.convert_document", side_effect=fake_convert) as convert:
                result = run_jobs(jobs)

        self.assertEqual(convert.call_count, 1)
        self.assertEqual(len(result.converted), 1)
        self.assertIn("already saved as report.pdf", result.errors[0])

    def test_replace_choice_is_passed_on(self) -> None:
        job = Job(Path("/a/report.docx"), Path("/a/report.pdf"), replace=True)
        with patch("doczap.batch.convert_document") as convert:
            run_jobs([job])
        convert.assert_called_once_with(job.source, job.output, overwrite=True)


class SummaryTests(unittest.TestCase):
    def test_single_pdf_is_named(self) -> None:
        result = Result(converted=[Job(Path("report.docx"), Path("report.pdf"))])
        self.assertEqual(format_summary(result), "Created report.pdf.")

    def test_batch_with_skips_and_failures(self) -> None:
        result = Result(
            converted=[Job(Path("a.docx"), Path("a.pdf")), Job(Path("b.docx"), Path("b.pdf"))],
            errors=["c.docx: broken"],
        )
        self.assertEqual(
            format_summary(result, skipped=1),
            "Created 2 PDFs. Skipped 1 existing PDF. 1 document could not be converted.",
        )

    def test_nothing_converted(self) -> None:
        self.assertEqual(format_summary(Result()), "Nothing was converted.")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.backend_api.commands.document_processing import _collect_notice_pdf_candidates, _doc_pdf_extract_run


class PdfExtractCommandTest(unittest.TestCase):
    def test_multiple_pdf_default_output_uses_first_source_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "report-a.pdf"
            second = Path(temp_dir) / "report-b.pdf"
            first.touch()
            second.touch()
            selections = [
                {"file_path": str(first), "page_num": 1, "order": 1},
                {"file_path": str(second), "page_num": 1, "order": 2},
            ]

            with patch(
                "modules.backend_api.commands.document_processing.merge_pages_from_multiple_pdfs",
                return_value=(2, 2),
            ) as merge_pages:
                result = _doc_pdf_extract_run({
                    "pdf_files": [str(first), str(second)],
                    "page_selections": selections,
                })

            self.assertTrue(result["success"])
            self.assertEqual(Path(result["output_file"]), Path(temp_dir) / "report-a_merged_pages.pdf")
            self.assertEqual(merge_pages.call_args.args[1], Path(temp_dir) / "report-a_merged_pages.pdf")

    def test_notice_pdf_conversion_discovers_generated_docs_without_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "company"
            output_dir.mkdir()
            generated = output_dir / "授权委托书-test.docx"
            generated.touch()
            logs: list[str] = []

            candidates = _collect_notice_pdf_candidates(Path(temp_dir), [], logs)

            self.assertIn(generated.resolve(), candidates)
            self.assertTrue(any("1 个可转换Word文件" in line for line in logs))


if __name__ == "__main__":
    unittest.main()

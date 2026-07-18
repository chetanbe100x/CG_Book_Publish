from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import build_full_pdf_ir


class LegacyExtractWrapperTests(unittest.TestCase):
    def test_delegates_to_draft_extractor_only(self) -> None:
        job = object()
        result = {
            "draft_manifest": "Work/book_ir.full.draft.json",
            "review_queue": "Review/review_queue.draft.json",
        }
        output = io.StringIO()
        with (
            patch.object(build_full_pdf_ir.JobConfig, "load", return_value=job) as load,
            patch.object(
                build_full_pdf_ir,
                "extract_book_ir_job",
                return_value=result,
            ) as extract,
            redirect_stdout(output),
        ):
            code = build_full_pdf_ir.main(["--job", "Books/Test/job.json"])

        self.assertEqual(code, 0)
        load.assert_called_once_with("Books/Test/job.json")
        extract.assert_called_once_with(job)
        self.assertEqual(json.loads(output.getvalue()), result)

    def test_has_no_reviewed_output_override_or_direct_writer(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit):
            build_full_pdf_ir.main(
                ["--job", "Books/Test/job.json", "--output", "book_ir.full.json"]
            )
        source = Path(build_full_pdf_ir.__file__).read_text(encoding="utf-8")
        self.assertNotIn(".write_text(", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn('errors="replace"', source)


if __name__ == "__main__":
    unittest.main()

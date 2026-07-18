from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pypdf import PdfWriter

from book_pipeline import command_approve
from framework.core.models import IntegrityError, JobConfig, sha256_file
from framework.qa.visual import record_word_visual_review, validate_word_visual_review
from framework.qa.word_render import (
    A4_HEIGHT_POINTS,
    A4_WIDTH_POINTS,
    WordRenderError,
    _helper_source,
    _run_word_helper,
    render_with_word,
    validate_word_render_manifest,
)


class WordRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        project = Path(__file__).resolve().parents[3]
        self._temporary = tempfile.TemporaryDirectory(dir=project)
        self.temporary = Path(self._temporary.name)
        self.document = self.temporary / "candidate.docx"
        self.document.write_bytes(b"immutable DOCX fixture")
        self.output_dir = self.temporary / "QA"

    def tearDown(self) -> None:
        self._temporary.cleanup()

    @staticmethod
    def _write_pdf(path: Path, pages: int) -> None:
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=A4_WIDTH_POINTS, height=A4_HEIGHT_POINTS)
        with path.open("wb") as stream:
            writer.write(stream)

    def _successful_helper(self, pages: int = 2):
        def helper(*args, **kwargs):
            self._write_pdf(kwargs["output_pdf"], pages)
            return {
                "renderer": "microsoft_word",
                "word_version": "16.0",
                "page_count": pages,
                "section_count": 1,
                "sections": [
                    {
                        "index": 1,
                        "start_page": 1,
                        "end_page": pages,
                        "page_width_points": A4_WIDTH_POINTS,
                        "page_height_points": A4_HEIGHT_POINTS,
                        "orientation": 0,
                    }
                ],
                "bookmark_pages": {
                    "SourcePdfPage003": 1,
                    "SourcePdfPage004": 2,
                },
                "stdout": "",
                "stderr": "",
            }

        return helper

    def test_publishes_hash_bound_manifest_without_changing_document(self) -> None:
        original = self.document.read_bytes()
        with patch(
            "framework.qa.word_render._run_word_helper",
            side_effect=self._successful_helper(),
        ):
            result = render_with_word(
                self.document,
                self.output_dir,
                expected_page_count=2,
                expected_bookmarks=("SourcePdfPage003", "SourcePdfPage004"),
            )

        self.assertEqual(self.document.read_bytes(), original)
        self.assertTrue(Path(result["render_pdf"]).is_file())
        self.assertTrue(Path(result["manifest"]).is_file())
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(result["bookmark_pages"]["SourcePdfPage004"], 2)
        manifest = validate_word_render_manifest(
            self.document,
            Path(result["manifest"]),
        )
        self.assertEqual(manifest["document_sha256"], result["document_sha256"])
        self.assertEqual(manifest["render_pdf_sha256"], result["render_pdf_sha256"])

    def test_manifest_is_invalidated_by_manual_docx_edit(self) -> None:
        with patch(
            "framework.qa.word_render._run_word_helper",
            side_effect=self._successful_helper(),
        ):
            result = render_with_word(
                self.document,
                self.output_dir,
                expected_page_count=2,
            )
        self.document.write_bytes(b"edited after approval")
        with self.assertRaisesRegex(IntegrityError, "changed after"):
            validate_word_render_manifest(self.document, Path(result["manifest"]))

    def test_manifest_is_invalidated_by_render_pdf_edit(self) -> None:
        with patch(
            "framework.qa.word_render._run_word_helper",
            side_effect=self._successful_helper(),
        ):
            result = render_with_word(
                self.document,
                self.output_dir,
                expected_page_count=2,
            )
        Path(result["render_pdf"]).write_bytes(b"changed PDF")
        with self.assertRaisesRegex(IntegrityError, "PDF changed"):
            validate_word_render_manifest(self.document, Path(result["manifest"]))

    def test_fails_closed_on_page_count_mismatch_without_publishing(self) -> None:
        with patch(
            "framework.qa.word_render._run_word_helper",
            side_effect=self._successful_helper(pages=2),
        ):
            with self.assertRaisesRegex(WordRenderError, "expected 3"):
                render_with_word(
                    self.document,
                    self.output_dir,
                    expected_page_count=3,
                )
        self.assertFalse((self.output_dir / "candidate.word.pdf").exists())
        self.assertFalse((self.output_dir / "candidate.word-render.json").exists())

    def test_fails_closed_when_section_is_not_a4(self) -> None:
        helper = self._successful_helper()

        def wrong_geometry(*args, **kwargs):
            result = helper(*args, **kwargs)
            result["sections"][0]["page_width_points"] = 612.0
            result["sections"][0]["page_height_points"] = 792.0
            return result

        with patch(
            "framework.qa.word_render._run_word_helper",
            side_effect=wrong_geometry,
        ):
            with self.assertRaisesRegex(WordRenderError, "not A4"):
                render_with_word(
                    self.document,
                    self.output_dir,
                    expected_page_count=2,
                )

    def test_requires_every_expected_bookmark(self) -> None:
        with patch(
            "framework.qa.word_render._run_word_helper",
            side_effect=self._successful_helper(),
        ):
            with self.assertRaisesRegex(WordRenderError, "SourcePdfPage099"):
                render_with_word(
                    self.document,
                    self.output_dir,
                    expected_page_count=2,
                    expected_bookmarks=("SourcePdfPage099",),
                )

    def test_rehashes_original_even_when_word_helper_fails(self) -> None:
        def mutating_failure(*args, **kwargs):
            self.document.write_bytes(b"changed during failed render")
            raise WordRenderError("simulated helper failure")

        with patch(
            "framework.qa.word_render._run_word_helper",
            side_effect=mutating_failure,
        ):
            with self.assertRaisesRegex(IntegrityError, "changed while"):
                render_with_word(
                    self.document,
                    self.output_dir,
                    expected_page_count=2,
                )
        self.assertFalse((self.output_dir / "candidate.word.pdf").exists())
        self.assertFalse((self.output_dir / "candidate.word-render.json").exists())


    def test_word_unavailable_fails_closed(self) -> None:
        process = Mock()
        process.communicate.return_value = ("", "COM class is not registered")
        process.returncode = 1
        with (
            patch(
                "framework.qa.word_render._powershell_executable",
                return_value=Path("pwsh.exe"),
            ),
            patch("framework.qa.word_render.subprocess.Popen", return_value=process),
        ):
            with self.assertRaisesRegex(WordRenderError, "failed closed"):
                _run_word_helper(
                    self.temporary / "helper.ps1",
                    input_docx=self.document,
                    output_pdf=self.temporary / "out.pdf",
                    output_json=self.temporary / "out.json",
                    expected_bookmarks=(),
                    timeout_seconds=1,
                )
        process.kill.assert_not_called()


    def test_timeout_kills_only_the_owned_helper_and_flags_possible_orphan(self) -> None:
        process = Mock()
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="powershell", timeout=1),
            ("partial stdout", "partial stderr"),
        ]
        with (
            patch(
                "framework.qa.word_render._powershell_executable",
                return_value=Path("pwsh.exe"),
            ),
            patch("framework.qa.word_render.subprocess.Popen", return_value=process),
        ):
            with self.assertRaises(WordRenderError) as raised:
                _run_word_helper(
                    self.temporary / "helper.ps1",
                    input_docx=self.document,
                    output_pdf=self.temporary / "out.pdf",
                    output_json=self.temporary / "out.json",
                    expected_bookmarks=(),
                    timeout_seconds=1,
                )
        process.kill.assert_called_once_with()
        self.assertTrue(raised.exception.possible_orphan)
        self.assertIn("manual cleanup", str(raised.exception))

    def test_helper_uses_isolated_word_and_forbids_broad_process_cleanup(self) -> None:
        source = _helper_source()
        self.assertIn("New-Object -ComObject Word.Application", source)
        self.assertIn("$word.Visible = $false", source)
        self.assertIn("$document.Close(0)", source)
        self.assertIn("$word.Quit(0)", source)
        self.assertIn("ForEach-Object { $_ }", source)
        self.assertNotIn("GetActiveObject", source)
        self.assertNotIn("Get-Process", source)
        self.assertNotIn("Stop-Process", source)
        self.assertNotIn("taskkill", source.casefold())

    def test_manifest_requires_authoritative_word_renderer(self) -> None:
        pdf = self.temporary / "secondary.pdf"
        self._write_pdf(pdf, 1)
        manifest = self.temporary / "secondary.json"
        manifest.write_text(
            json.dumps(
                {
                    "renderer": "libreoffice",
                    "authoritative": False,
                    "passed": True,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(IntegrityError, "Microsoft Word"):
            validate_word_render_manifest(self.document, manifest)

    def test_visual_review_is_bound_to_the_word_manifest_hashes(self) -> None:
        with patch(
            "framework.qa.word_render._run_word_helper",
            side_effect=self._successful_helper(),
        ):
            rendered = render_with_word(
                self.document,
                self.output_dir,
                expected_page_count=2,
            )
        job = JobConfig(
            manifest_path=self.temporary / "job.json",
            job_id="word-review-test",
            school_class="11",
            subject="Maths",
            source=self.document,
            template=self.document,
            preview_output=self.document,
            final_output=self.document,
            approved_reference=None,
            qa_dir=self.output_dir,
        )
        job.status_path.write_text('{"state":"final_qa_passed"}', encoding="utf-8")
        review = record_word_visual_review(
            job,
            stage="final",
            passed=True,
            page_count=2,
            notes="Inspected every page at 100% zoom.",
            render_manifest=Path(rendered["manifest"]),
        )
        self.assertTrue(review["hash_bound"])
        self.assertEqual(
            validate_word_visual_review(job, stage="final")["document_sha256"],
            rendered["document_sha256"],
        )
        self.document.write_bytes(b"manual edit invalidates approval")
        with self.assertRaisesRegex(IntegrityError, "changed after"):
            validate_word_visual_review(job, stage="final")

    def test_word_preview_approval_requires_visual_review_validation(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        job = JobConfig(
            manifest_path=self.temporary / "job.json",
            job_id="word-approval-test",
            school_class="11",
            subject="Maths",
            source=self.document,
            template=self.document,
            preview_output=self.document,
            final_output=self.temporary / "final.docx",
            approved_reference=None,
            qa_dir=self.output_dir,
            render_authority="word",
        )
        job.status_path.write_text(
            json.dumps(
                {
                    "state": "preview_qa_passed",
                    "preview_sha256": sha256_file(self.document),
                    "source_sha256": sha256_file(self.document),
                    "template_sha256": sha256_file(self.document),
                }
            ),
            encoding="utf-8",
        )
        with patch("book_pipeline.validate_word_visual_review") as validate_review:
            result = command_approve(job)

        validate_review.assert_called_once_with(job, stage="preview")
        self.assertEqual(result["state"], "preview_approved")




if __name__ == "__main__":
    unittest.main()

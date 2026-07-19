from __future__ import annotations

from dataclasses import replace
import unittest
from pathlib import Path
from unittest.mock import patch

from framework.core.models import FrameworkError, JobConfig
from framework.qa import render
from framework.qa.pdf_layout import (
    A4_HEIGHT_POINTS,
    A4_WIDTH_POINTS,
    POINTS_PER_MM,
    analyze_word_pdf,
)


class _FakePage:
    def __init__(
        self,
        *,
        words: list[dict[str, object]],
        lines: list[dict[str, object]] | None = None,
        images: list[dict[str, object]] | None = None,
        rects: list[dict[str, object]] | None = None,
        curves: list[dict[str, object]] | None = None,
    ) -> None:
        self.width = A4_WIDTH_POINTS
        self.height = A4_HEIGHT_POINTS
        self._words = words
        self.lines = lines or []
        self.images = images or []
        self.rects = rects or []
        self.curves = curves or []

    def extract_words(self, **_: object) -> list[dict[str, object]]:
        return list(self._words)


class _FakePdf:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def __enter__(self) -> "_FakePdf":
        return self

    def __exit__(self, *_: object) -> None:
        return None


class PrintQaIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Path(__file__).resolve().parents[3]
        book = self.repository / "Books" / "Class 11" / "Maths"
        self.source_pdf = book / "Input" / "Maths_11th.pdf"
        self.template = self.repository / "Book_Template.docx"
        self.preview = self.template
        self.final = self.template
        self.qa_dir = book / "QA"

    def _job(
        self,
        *,
        page_type: str = "mcq",
        blocks: list[dict[str, object]] | None = None,
    ) -> JobConfig:
        self._page_meta = {
            3: {
                "source_page": 3,
                "page_type": page_type,
                "blocks": blocks or [],
            }
        }
        return JobConfig(
            manifest_path=self.repository / "Books" / "Class 11" / "Maths" / "job.json",
            job_id="print-qa",
            school_class="11",
            subject="Maths",
            source=self.source_pdf,
            template=self.template,
            preview_output=self.preview,
            final_output=self.final,
            approved_reference=None,
            qa_dir=self.qa_dir,
            source_type="pdf",
            normalized_source=self.qa_dir / "normalized.docx",
            content_manifest=None,
            preview_source_pages=1,
            preview_source_page_numbers=(3,),
            content_policy="reconstruct_content",
            typography_policy="mapped_pdf_fonts",
            boundary_strategy="explicit",
            pdf_font_map=(
                ("hindi", "Nirmala UI"),
                ("latin", "Arial"),
                ("math", "Cambria Math"),
            ),
            content_page_ranges=((3, 3),),
            expected_page_count=1,
            render_authority="word",
        )

    def _docx_job(self) -> JobConfig:
        self._page_meta = {}
        return JobConfig(
            manifest_path=self.repository / "unused-job.json",
            job_id="docx-print-qa",
            school_class="11",
            subject="Maths",
            source=self.template,
            template=self.template,
            preview_output=self.qa_dir / "unused-preview.docx",
            final_output=self.qa_dir / "unused-final.docx",
            approved_reference=None,
            qa_dir=self.qa_dir,
            source_type="docx",
            preview_source_pages=1,
            content_policy="layout_only",
            typography_policy="preserve_source",
            render_authority="word",
        )

    @staticmethod
    def _word(
        *,
        top_mm: float = 30.0,
        bottom_mm: float = 230.0,
        x0_mm: float = 25.0,
        x1_mm: float = 180.0,
        text: str = "Question",
    ) -> dict[str, object]:
        return {
            "text": text,
            "x0": x0_mm * POINTS_PER_MM,
            "x1": x1_mm * POINTS_PER_MM,
            "top": top_mm * POINTS_PER_MM,
            "bottom": bottom_mm * POINTS_PER_MM,
        }

    @staticmethod
    def _line(y_mm: float) -> dict[str, object]:
        return {
            "x0": 22.0 * POINTS_PER_MM,
            "x1": 192.0 * POINTS_PER_MM,
            "top": y_mm * POINTS_PER_MM,
            "bottom": y_mm * POINTS_PER_MM,
        }

    def _analyze(
        self,
        job: JobConfig,
        page: _FakePage,
        *,
        source_bottom_mm: float = 230.0,
    ) -> dict[str, object]:
        source_utilization = (
            100.0
            * (source_bottom_mm - 28.0)
            / (267.0 - 28.0)
        )
        with (
            patch(
                "framework.qa.pdf_layout.pdfplumber.open",
                return_value=_FakePdf([page]),
            ),
            patch(
                "framework.qa.pdf_layout._manifest_page_metadata",
                return_value=self._page_meta,
            ),
            patch(
                "framework.qa.pdf_layout._source_page_measurements",
                return_value={
                    3: {
                        "content_bottom_points": source_bottom_mm * POINTS_PER_MM,
                        "utilization_percent": source_utilization,
                    }
                }
                if job.source_type == "pdf"
                else {},
            ),
        ):
            return analyze_word_pdf(
                job,
                self.source_pdf,
                stage="preview",
                source_page_numbers=(3,) if job.source_type == "pdf" else (),
            )

    def test_heading_rule_is_not_mistaken_for_an_answer_line(self) -> None:
        page = _FakePage(
            words=[self._word()],
            lines=[self._line(40.0)],
        )
        result = self._analyze(self._job(page_type="mcq"), page)
        self.assertTrue(result["passed"], result["errors"])
        self.assertFalse(
            any("answer line" in message for message in result["errors"])
        )

    def test_short_answer_line_must_reach_260_mm(self) -> None:
        page = _FakePage(
            words=[self._word(bottom_mm=100.0)],
            lines=[self._line(250.0)],
        )
        blocks = [{"kind": "answer_lines", "source_bbox_points": [0.0, 100.0, 500.0, 260.0 * POINTS_PER_MM]}]
        result = self._analyze(self._job(page_type="short_answer", blocks=blocks), page)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any(
                "final answer line ends at 250.0 mm" in message
                for message in result["errors"]
            )
        )

    def test_answer_canvas_does_not_require_dotted_lines(self) -> None:
        page = _FakePage(
            words=[self._word(bottom_mm=100.0)],
            rects=[
                {
                    "x0": 25.0 * POINTS_PER_MM,
                    "x1": 185.0 * POINTS_PER_MM,
                    "top": 100.0 * POINTS_PER_MM,
                    "bottom": 261.0 * POINTS_PER_MM,
                }
            ],
        )
        result = self._analyze(
            self._job(
                page_type="short_answer",
                blocks=[{"type": "answer_canvas"}],
            ),
            page,
        )
        self.assertTrue(result["passed"], result["errors"])

    def test_visual_object_crossing_live_frame_is_rejected(self) -> None:
        page = _FakePage(
            words=[self._word()],
            images=[
                {
                    "x0": 20.0 * POINTS_PER_MM,
                    "x1": 100.0 * POINTS_PER_MM,
                    "top": 80.0 * POINTS_PER_MM,
                    "bottom": 120.0 * POINTS_PER_MM,
                }
            ],
        )
        result = self._analyze(self._job(page_type="mcq"), page)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("visual object(s) outside" in message for message in result["errors"])
        )

    def test_docx_input_skips_pdf_utilization_and_answer_rules(self) -> None:
        page = _FakePage(words=[self._word(bottom_mm=80.0)])
        result = self._analyze(self._docx_job(), page)

        self.assertTrue(result["passed"], result["errors"])
        messages = [*result["errors"], *result["warnings"]]
        self.assertFalse(
            any("utilization" in message for message in messages),
            messages,
        )
        self.assertFalse(
            any("answer line" in message for message in messages),
            messages,
        )

    def test_docx_input_still_enforces_live_frame(self) -> None:
        page = _FakePage(
            words=[self._word(bottom_mm=80.0, x0_mm=10.0)],
        )
        result = self._analyze(self._docx_job(), page)

        self.assertFalse(result["passed"])
        self.assertTrue(
            any(
                "outside the live content frame" in message
                for message in result["errors"]
            )
        )

    def test_pdf_source_dispatch_does_not_use_docx_renderer(self) -> None:
        job = self._job()
        with (
            patch(
                "framework.qa.render._render_pdf_source",
                return_value={"renderer": "poppler"},
            ) as pdf_source,
            patch("framework.qa.render._render_with_word") as word,
            patch("framework.qa.render._render_with_libreoffice") as libreoffice,
        ):
            result = render.render_document(job, "source")
        self.assertEqual(result["renderer"], "poppler")
        pdf_source.assert_called_once_with(job)
        word.assert_not_called()
        libreoffice.assert_not_called()

    def test_word_preview_dispatches_to_authoritative_renderer(self) -> None:
        job = self._job()
        with (
            patch(
                "framework.qa.render._render_with_word",
                return_value={"renderer": "microsoft_word"},
            ) as word,
            patch("framework.qa.render._render_with_libreoffice") as libreoffice,
        ):
            result = render.render_document(job, "preview")
        self.assertEqual(result["renderer"], "microsoft_word")
        word.assert_called_once_with(job, "preview")
        libreoffice.assert_not_called()

    def test_docx_word_render_does_not_require_pdf_bookmarks(self) -> None:
        job = replace(
            self._docx_job(),
            preview_output=self.template,
            preview_source_page_numbers=(3,),
        )
        word_result = {
            "bookmark_pages": {},
            "render_pdf": str(self.source_pdf),
            "page_count": 1,
            "manifest": "manifest.json",
            "render_pdf_sha256": "HASH",
            "word_version": "16.0",
        }
        with (
            patch(
                "framework.qa.render.render_with_word",
                return_value=word_result,
            ) as word,
            patch(
                "framework.qa.render._render_pdf_pages",
                return_value=([self.repository / "page-1.png"], "", ""),
            ),
            patch("framework.qa.render._contact_sheets", return_value=[]),
            patch(
                "framework.qa.render.analyze_word_pdf",
                return_value={"passed": True, "errors": [], "warnings": []},
            ) as layout,
            patch("framework.qa.render.atomic_json_write"),
        ):
            result = render._render_with_word(job, "preview")

        self.assertEqual(result["bookmark_pages"], {})
        self.assertEqual(word.call_args.kwargs["expected_bookmarks"], ())
        layout.assert_called_once_with(
            job,
            self.source_pdf,
            stage="preview",
            source_page_numbers=(),
            bookmark_pages={},
        )

    def test_word_render_rejects_bookmark_on_wrong_physical_page(self) -> None:
        job = self._job()
        with patch(
            "framework.qa.render.render_with_word",
            return_value={
                "bookmark_pages": {"SourcePdfPage003": 2},
            },
        ):
            with self.assertRaisesRegex(FrameworkError, "not one-to-one"):
                render._render_with_word(job, "preview")

    def test_word_render_rejects_raster_page_count_drift(self) -> None:
        job = self._job()
        rendered_pdf = self.source_pdf
        with (
            patch(
                "framework.qa.render.render_with_word",
                return_value={
                    "bookmark_pages": {"SourcePdfPage003": 1},
                    "render_pdf": str(rendered_pdf),
                    "page_count": 1,
                },
            ),
            patch(
                "framework.qa.render._render_pdf_pages",
                return_value=(
                    [self.repository / "page-1.png", self.repository / "page-2.png"],
                    "",
                    "",
                ),
            ),
        ):
            with self.assertRaisesRegex(FrameworkError, "page-count mismatch"):
                render._render_with_word(job, "preview")

    def test_pdf_layout_analysis_works_for_all_font_maps(self) -> None:
        """For every job with a pdf_font_map, run the fake-page analysis to verify no key errors on font role lookups."""
        from tests.conftest import all_font_maps
        page = _FakePage(
            words=[self._word(text="Test")],
        )
        for job_id, font_map in all_font_maps():
            with self.subTest(job_id=job_id):
                job = replace(
                    self._job(page_type="mcq"),
                    job_id=f"test-qa-{job_id}",
                    pdf_font_map=tuple(sorted((str(k), str(v)) for k, v in font_map.items())),
                )
                try:
                    result = self._analyze(job, page)
                    self.assertIsInstance(result, dict)
                    self.assertIn("passed", result)
                    self.assertIn("errors", result)
                except Exception as exc:
                    self.fail(f"analyze_word_pdf failed or crashed for job {job_id!r} font map: {exc}")


class JobConfigPrintFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Path(__file__).resolve().parents[3]
        book = self.repository / "Books" / "Class 11" / "Maths"
        self.source_docx = (
            book / "Input" / "Class 11 Maths - Printable Reference.docx"
        )
        self.source_pdf = book / "Input" / "Maths_11th.pdf"
        self.template = self.repository / "Book_Template.docx"
        self.qa_dir = book / "QA"

    def test_word_authority_does_not_break_docx_input_jobs(self) -> None:
        job = JobConfig(
            manifest_path=self.repository / "unused-job.json",
            job_id="docx-word",
            school_class="11",
            subject="Maths",
            source=self.source_docx,
            template=self.template,
            preview_output=self.qa_dir / "unused-preview.docx",
            final_output=self.qa_dir / "unused-final.docx",
            approved_reference=None,
            qa_dir=self.qa_dir,
            render_authority="word",
        )
        job.validate()
        self.assertIsNone(job.expected_pages_for_stage("final"))

    def test_content_page_ranges_must_be_strictly_increasing(self) -> None:
        source = self.source_pdf
        job = JobConfig(
            manifest_path=self.repository / "unused-job.json",
            job_id="bad-ranges",
            school_class="11",
            subject="Maths",
            source=source,
            template=self.template,
            preview_output=self.qa_dir / "unused-preview.docx",
            final_output=self.qa_dir / "unused-final.docx",
            approved_reference=None,
            qa_dir=self.qa_dir,
            source_type="pdf",
            normalized_source=self.qa_dir / "unused-normalized.docx",
            content_manifest=self.qa_dir / "unused-manifest.json",
            preview_source_pages=1,
            preview_source_page_numbers=(3,),
            content_policy="reconstruct_content",
            typography_policy="mapped_pdf_fonts",
            boundary_strategy="explicit",
            pdf_font_map=(
                ("hindi", "Nirmala UI"),
                ("latin", "Arial"),
                ("math", "Cambria Math"),
            ),
            content_page_ranges=((5, 6), (3, 4)),
            expected_page_count=4,
            render_authority="word",
        )
        with self.assertRaisesRegex(FrameworkError, "strictly increasing"):
            job.validate()

    def test_unknown_expected_page_stage_fails_closed(self) -> None:
        job = JobConfig(
            manifest_path=self.repository / "unused-job.json",
            job_id="stage",
            school_class="11",
            subject="Maths",
            source=self.source_docx,
            template=self.template,
            preview_output=self.qa_dir / "unused-preview.docx",
            final_output=self.qa_dir / "unused-final.docx",
            approved_reference=None,
            qa_dir=self.qa_dir,
        )
        with self.assertRaisesRegex(FrameworkError, "Unknown stage"):
            job.expected_pages_for_stage("draft")


if __name__ == "__main__":
    unittest.main()


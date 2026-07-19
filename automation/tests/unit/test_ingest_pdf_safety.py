from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from framework.core.models import (
    FrameworkError,
    IntegrityError,
    JobConfig,
    UnsupportedFeatureError,
    sha256_file,
)
from framework.ingest.pdf import ingest_pdf_job, validate_pdf_ingest_freshness


class PdfIngestSafetyTests(unittest.TestCase):
    def _job(self, root: Path) -> JobConfig:
        source = root / "source.pdf"
        template = root / "template.docx"
        manifest = root / "book_ir.full.json"
        normalized = root / "normalized.docx"
        source.write_bytes(b"pdf")
        template.write_bytes(b"docx")
        manifest.write_text("{}", encoding="utf-8")
        normalized.write_bytes(b"docx")
        return JobConfig(
            manifest_path=root / "job.json",
            job_id="pdf-safety",
            school_class="11",
            subject="Maths",
            source=source,
            template=template,
            preview_output=root / "preview.docx",
            final_output=root / "final.docx",
            approved_reference=None,
            qa_dir=root / "QA",
            source_type="pdf",
            normalized_source=normalized,
            content_manifest=manifest,
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
        )

    def test_all_font_maps_have_required_roles(self) -> None:
        """For every job with pdf_font_map, assert hindi, latin, math roles are present."""
        from tests.conftest import all_font_maps
        for job_id, font_map in all_font_maps():
            with self.subTest(job_id=job_id):
                for role in ("hindi", "latin", "math"):
                    self.assertIn(
                        role,
                        font_map,
                        f"pdf_font_map in job {job_id!r} is missing required role {role!r}",
                    )

    def test_all_required_fonts_lists_are_non_empty_when_declared(self) -> None:
        """For every job with required_fonts, assert each font name is non-empty and not whitespace."""
        from tests.conftest import discover_jobs
        for job_id, data, _ in discover_jobs():
            required_fonts = data.get("required_fonts", [])
            for font in required_fonts:
                with self.subTest(job_id=job_id, font=font):
                    self.assertTrue(
                        isinstance(font, str) and font.strip(),
                        f"Job {job_id!r} has empty or invalid font name in required_fonts: {font!r}",
                    )

    def test_required_fonts_are_checked_before_generation(self) -> None:
        job = JobConfig(
            manifest_path=Path("job.json"),
            job_id="font-gate",
            school_class="11",
            subject="Maths",
            source=Path("source.pdf"),
            template=Path("template.docx"),
            preview_output=Path("preview.docx"),
            final_output=Path("final.docx"),
            approved_reference=None,
            qa_dir=Path("QA"),
            source_type="pdf",
            normalized_source=Path("normalized.docx"),
            content_manifest=Path("book_ir.full.json"),
            pdf_font_map=(
                ("hindi", "Nirmala UI"),
                ("latin", "Arial"),
                ("math", "Cambria Math"),
            ),
            required_fonts=("Nirmala UI", "Arial", "Cambria Math"),
        )

        with patch(
            "framework.ingest.pdf.missing_fonts",
            return_value=["Nirmala UI"],
        ):
            with self.assertRaisesRegex(
                UnsupportedFeatureError,
                "Nirmala UI",
            ):
                ingest_pdf_job(job)

    def test_existing_normalized_source_requires_matching_ingest_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            job = self._job(Path(temporary_name))
            job.qa_dir.mkdir(parents=True)
            assert job.content_manifest is not None
            assert job.normalized_source is not None
            effective_path = job.qa_dir / "effective-manifest.json"
            effective_path.write_text("{}", encoding="utf-8")
            report = {
                "source": {"sha256": sha256_file(job.source)},
                "manifest": {"sha256": sha256_file(job.content_manifest)},
                "normalized_source": {
                    "sha256": sha256_file(job.normalized_source),
                },
                "effective_manifest": {
                    "path": str(effective_path),
                    "sha256": sha256_file(effective_path),
                },
            }
            (job.qa_dir / "ingest.json").write_text(
                json.dumps(report),
                encoding="utf-8",
            )
            validate_pdf_ingest_freshness(job)

            job.content_manifest.write_text('{"changed": true}', encoding="utf-8")
            with self.assertRaisesRegex(IntegrityError, "Content Manifest changed"):
                validate_pdf_ingest_freshness(job)

    def test_full_ingest_passes_configured_source_pages_to_ir_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            job = replace(
                self._job(Path(temporary_name)),
                content_page_ranges=((3, 4),),
                expected_page_count=2,
            )
            assert job.content_manifest is not None
            job.content_manifest.write_text('{"scope": "full"}', encoding="utf-8")
            with patch(
                "framework.ingest.pdf.missing_fonts",
                return_value=[],
            ), patch(
                "framework.ingest.pdf.pdf_inventory",
                return_value={"page_count": 2},
            ), patch(
                "framework.ingest.pdf.load_book_ir",
                side_effect=FrameworkError("stop after IR gate"),
            ) as loader:
                with self.assertRaisesRegex(FrameworkError, "stop after IR gate"):
                    ingest_pdf_job(job)
            self.assertEqual(loader.call_args.kwargs["expected_pages"], (3, 4))


if __name__ == "__main__":
    unittest.main()


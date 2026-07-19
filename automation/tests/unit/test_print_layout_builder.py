from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree
from PIL import Image

from framework.core.dependencies import disable_automatic_image_compression
from framework.core.layout import load_print_layout, mm_to_twips
from framework.core.models import FrameworkError, JobConfig
from framework.core.package import NS, W
from framework.ingest.builder import build_normalized_docx
from framework.ingest.print_builder import _option_columns


class PrintLayoutProfileTests(unittest.TestCase):
    def test_maths_profile_uses_reviewed_print_tokens(self) -> None:
        profile = load_print_layout("maths")
        self.assertEqual(profile.page.live_body_width_mm, 170.0)
        self.assertEqual(profile.page.margins_for_page(0), (22.0, 18.0))
        self.assertEqual(profile.page.margins_for_page(1), (18.0, 22.0))
        self.assertEqual(profile.style("chapter").size_points, 24.0)
        self.assertEqual(profile.style("question").size_points, 16.0)
        self.assertEqual(profile.style("english").size_points, 16.0)
        self.assertEqual(profile.style("option").size_points, 16.0)
        self.assertEqual(profile.inline_math_points, 16.0)
        self.assertEqual(profile.style("english").color, "000000")
        self.assertEqual(profile.options.table_width_twips, 9220)
        self.assertEqual(profile.options.two_column_widths_twips, (4700, 4520))
        self.assertEqual(profile.answer_space.default_pitch_points, 24.0)
        self.assertEqual(profile.answer_space.generous_pitch_points, 27.0)
        self.assertEqual(profile.images.formula_min_dpi, 300.0)

    def test_all_profiles_load_successfully(self) -> None:
        """For every profile in profiles/, call load_print_layout() and assert no error."""
        from tests.conftest import discover_profiles
        profiles = discover_profiles()
        self.assertGreater(len(profiles), 0, "No profiles discovered.")
        for name, _ in profiles:
            with self.subTest(profile=name):
                try:
                    profile = load_print_layout(name)
                    self.assertEqual(profile.name, name)
                except Exception as exc:
                    self.fail(f"Failed to load print layout for profile {name!r}: {exc}")

    def test_all_profiles_have_required_style_keys(self) -> None:
        """For every loaded profile, assert all 12 required style roles exist with valid values."""
        from tests.conftest import discover_profiles
        required_roles = (
            "body", "hindi", "english", "question", "question_label",
            "unit", "chapter", "question_type", "equation", "option",
            "option_label", "answer_line"
        )
        for name, data in discover_profiles():
            if "print_layout" not in data:
                continue  # Skip stubs
            with self.subTest(profile=name):
                profile = load_print_layout(name)
                for role in required_roles:
                    with self.subTest(role=role):
                        try:
                            style = profile.style(role)
                            self.assertIsNotNone(style)
                        except Exception as exc:
                            self.fail(f"Profile {name!r} is missing style role {role!r}: {exc}")

    def test_all_profiles_page_geometry_is_physically_valid(self) -> None:
        """Assert width = inside_margin + outside_margin + live_body_width (within 0.2mm tolerance) for every profile."""
        from tests.conftest import discover_profiles
        for name, data in discover_profiles():
            if "print_layout" not in data:
                continue  # Skip stubs
            with self.subTest(profile=name):
                profile = load_print_layout(name)
                total_width = profile.page.inside_margin_mm + profile.page.outside_margin_mm + profile.page.live_body_width_mm
                self.assertAlmostEqual(
                    profile.page.width_mm,
                    total_width,
                    delta=0.2,
                    msg=f"Profile {name!r} layout width does not match margin + body width sum",
                )

    def test_profiles_referenced_by_jobs_exist(self) -> None:
        """For every subject_profile in every job.json, assert a matching profile JSON exists and loads."""
        from tests.conftest import discover_jobs, discover_profiles
        profiles = {name for name, _ in discover_profiles()}
        jobs = discover_jobs()
        for job_id, data, _ in jobs:
            subject_profile = data.get("subject_profile", "science")
            with self.subTest(job_id=job_id, subject_profile=subject_profile):
                self.assertIn(
                    subject_profile,
                    profiles,
                    f"Job {job_id!r} references missing subject profile {subject_profile!r}",
                )

    def test_formula_width_controls_safe_option_grid_fallback(self) -> None:
        profile = load_print_layout("maths")
        block = {
            "columns": 2,
            "items": [
                {"label": "A", "formula_image": {"width_inches": 0.8}},
                {"label": "B", "text": "R"},
                {"label": "C", "formula_image": {"width_inches": 1.0}},
                {"label": "D", "text": "none of them"},
            ],
        }
        self.assertEqual(_option_columns(block, profile), 2)

        block["items"][0]["formula_image"]["width_inches"] = 2.7
        self.assertEqual(_option_columns(block, profile), 1)

    def test_rich_option_runs_return_a_stable_width_estimate(self) -> None:
        profile = load_print_layout("maths")
        block = {
            "columns": 2,
            "items": [
                {
                    "label": "A",
                    "runs": [
                        {"text": "x = ", "language": "math"},
                        {
                            "formula_image": {
                                "width_inches": 0.8,
                            }
                        },
                    ],
                },
                {"label": "B", "text": "x = 2"},
            ],
        }
        self.assertEqual(_option_columns(block, profile), 2)
        block["items"][0]["runs"][1]["formula_image"]["width_inches"] = 2.7
        self.assertEqual(_option_columns(block, profile), 1)

    def test_composition_setting_disables_word_image_compression(self) -> None:
        parts = {
            "word/settings.xml": (
                f'<w:settings xmlns:w="{NS["w"]}">'
                "<w:shapeDefaults/></w:settings>".encode("utf-8")
            )
        }
        disable_automatic_image_compression(parts)
        settings = etree.fromstring(parts["word/settings.xml"])
        value = settings.find(".//w:doNotAutoCompressPictures", NS)
        self.assertIsNotNone(value)
        self.assertEqual(
            [child.tag for child in settings],
            [W + "doNotAutoCompressPictures", W + "shapeDefaults"],
        )
        self.assertEqual(value.get(W + "val"), "true")



class PrintLayoutBuilderTests(unittest.TestCase):
    def _job(self, root: Path, temporary: Path) -> JobConfig:
        return JobConfig(
            manifest_path=temporary / "job.json",
            job_id="print-layout-test",
            school_class="11",
            subject="Maths",
            source=root / "Book_Template.docx",
            template=root / "Book_Template.docx",
            preview_output=temporary / "preview.docx",
            final_output=temporary / "final.docx",
            approved_reference=None,
            qa_dir=temporary / "QA",
            source_type="pdf",
            normalized_source=temporary / "normalized.docx",
            content_manifest=temporary / "manifest.json",
            preview_source_pages=2,
            preview_source_page_numbers=(3, 4),
            content_policy="reconstruct_content",
            typography_policy="mapped_pdf_fonts",
            boundary_strategy="explicit",
            pdf_font_map=(
                ("hindi", "Nirmala UI"),
                ("latin", "Arial"),
                ("math", "Cambria Math"),
            ),
            subject_profile="maths",
            first_content_side="recto",
        )

    @staticmethod
    def _paragraph_with_text(root: etree._Element, text: str) -> etree._Element:
        for paragraph in root.findall("./w:body/w:p", NS):
            value = "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))
            if text in value:
                return paragraph
        raise AssertionError(f"Paragraph not found: {text}")

    def test_builder_emits_exact_print_geometry_and_spacing(self) -> None:
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            formula = temporary / "formula.png"
            Image.new("RGB", (600, 200), "white").save(formula)
            job = self._job(root, temporary)
            manifest = {
                "book_name": "Print Layout Fixture",
                "pages": [
                    {
                        "source_page": 3,
                        "blocks": [
                            {
                                "kind": "heading",
                                "role": "unit_heading",
                                "text": "अध्याय 1",
                                "language": "hindi",
                                "source_ids": ["source.pdf:p003"],
                            },
                            {
                                "kind": "question",
                                "id": "q-003-01",
                                "label": "Q1.",
                                "hindi": "निम्न प्रश्न हल कीजिए।",
                                "english": "Solve the following question.",
                                "source_ids": ["source.pdf:p003"],
                            },
                            {
                                "kind": "options",
                                "for_question": "q-003-01",
                                "columns": 2,
                                "items": [
                                    {"label": "A", "text": "x = 1", "language": "math"},
                                    {"label": "B", "text": "x = 2", "language": "math"},
                                    {"label": "C", "text": "x = 3", "language": "math"},
                                    {"label": "D", "text": "x = 4", "language": "math"},
                                ],
                                "source_ids": ["source.pdf:p003"],
                            },
                            {
                                "kind": "options",
                                "columns": 2,
                                "items": [
                                    {"label": "A", "text": "A deliberately long equation-heavy option " * 3, "language": "math"},
                                    {"label": "B", "text": "short", "language": "latin"},
                                ],
                                "source_ids": ["source.pdf:p003"],
                            },
                            {
                                "kind": "answer_lines",
                                "count": 2,
                                "source_ids": ["source.pdf:p003"],
                            },
                            {
                                "kind": "formula_image",
                                "path": "formula.png",
                                "width_inches": 1.5,
                                "alt_text": "A sharp mathematical fraction",
                                "source_ids": ["source.pdf:p003"],
                            },
                            {
                                "kind": "answer_canvas",
                                "height_points": 72,
                                "width_points": 482.2,
                                "border": True,
                                "source_ids": ["source.pdf:p003"],
                            },
                        ],
                    },
                    {
                        "source_page": 4,
                        "blocks": [
                            {
                                "kind": "paragraph",
                                "text": "Verso body",
                                "language": "latin",
                                "source_ids": ["source.pdf:p004"],
                            }
                        ],
                    },
                ],
            }
            result = build_normalized_docx(job, manifest, job.normalized_source)
            self.assertEqual(result["layout_profile"], "maths")
            self.assertGreaterEqual(result["image_checks"][0]["effective_dpi"], 300)

            with zipfile.ZipFile(job.normalized_source) as package:
                document = etree.fromstring(package.read("word/document.xml"))
                settings = etree.fromstring(package.read("word/settings.xml"))
                styles = etree.fromstring(package.read("word/styles.xml"))

            bookmarks = document.findall(".//w:bookmarkStart", NS)
            self.assertEqual(len(bookmarks), 2)
            first_content = document.find("./w:body/w:p", NS)
            children = list(first_content)
            self.assertEqual(children[0].tag, W + "pPr")
            self.assertEqual(children[1].tag, W + "bookmarkStart")

            tables = document.findall("./w:body/w:tbl", NS)
            self.assertEqual(len(tables), 2)
            first_width = tables[0].find("w:tblPr/w:tblW", NS)
            first_indent = tables[0].find("w:tblPr/w:tblInd", NS)
            self.assertEqual(first_width.get(W + "w"), "9220")
            self.assertEqual(first_width.get(W + "type"), "dxa")
            self.assertEqual(
                [value.get(W + "w") for value in tables[0].findall("w:tblGrid/w:gridCol", NS)],
                ["4700", "4520"],
            )
            self.assertEqual(
                [value.get(W + "w") for value in tables[0].findall(".//w:tcW", NS)],
                ["4700", "4520", "4700", "4520"],
            )
            self.assertEqual(
                [value.get(W + "w") for value in tables[1].findall("w:tblGrid/w:gridCol", NS)],
                ["9220"],
            )
            self.assertEqual(len(document.findall(".//w:trPr/w:cantSplit", NS)), 4)

            question = self._paragraph_with_text(document, "Q1.")
            verso = self._paragraph_with_text(document, "Verso body")
            question_left = int(question.find("w:pPr/w:ind", NS).get(W + "left"))
            verso_left = int(verso.find("w:pPr/w:ind", NS).get(W + "left"))
            self.assertNotEqual(question_left, verso_left)
            self.assertEqual(int(first_indent.get(W + "w")) - question_left, 420)
            self.assertEqual(
                mm_to_twips(22.0) - mm_to_twips(18.0),
                question_left - verso_left,
            )

            dotted = document.findall(".//w:pBdr/w:bottom[@w:val='dotted']", NS)
            self.assertEqual(len(dotted), 2)
            self.assertEqual(len(document.findall(".//w:tab", NS)), 0)
            exact_pitch = document.findall(".//w:spacing[@w:line='480'][@w:lineRule='exact']", NS)
            self.assertEqual(len(exact_pitch), 2)
            self.assertEqual(len(document.findall(".//w:keepLines", NS)), 0)

            self.assertIsNone(settings.find(".//w:updateFields", NS))
            compression = settings.find(".//w:doNotAutoCompressPictures", NS)
            self.assertIsNotNone(compression)
            self.assertEqual(compression.get(W + "val"), "true")
            picture_properties = document.find(".//wp:docPr", NS)
            self.assertEqual(picture_properties.get("descr"), "A sharp mathematical fraction")

            chapter_style = styles.xpath(".//w:style[w:name[@w:val='Book Chapter']]", namespaces=NS)[0]
            self.assertEqual(chapter_style.find("w:rPr/w:sz", NS).get(W + "val"), "48")

    def test_builder_rejects_low_resolution_formula_image(self) -> None:
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            Image.new("RGB", (100, 50), "white").save(temporary / "formula.png")
            job = self._job(root, temporary)
            manifest = {
                "book_name": "Low DPI Fixture",
                "pages": [
                    {
                        "source_page": 3,
                        "blocks": [
                            {
                                "kind": "formula_image",
                                "path": "formula.png",
                                "width_inches": 2.0,
                                "alt_text": "Formula",
                                "source_ids": ["source.pdf:p003"],
                            }
                        ],
                    }
                ],
            }
            with self.assertRaisesRegex(FrameworkError, "effective DPI is too low"):
                build_normalized_docx(job, manifest, job.normalized_source)
            self.assertFalse(job.normalized_source.exists())

    def test_rich_text_formula_run_emits_inline_picture_with_alt_text(self) -> None:
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            Image.new("RGB", (600, 160), "white").save(temporary / "inline.png")
            job = self._job(root, temporary)
            manifest = {
                "book_name": "Inline Formula Fixture",
                "pages": [
                    {
                        "source_page": 3,
                        "blocks": [
                            {
                                "kind": "paragraph",
                                "runs": [
                                    {"text": "Evaluate ", "language": "latin"},
                                    {
                                        "formula_image": {
                                            "path": "inline.png",
                                            "alt_text": "x squared plus one",
                                            "width_inches": 1.5,
                                        }
                                    },
                                    {"text": " exactly.", "language": "latin"},
                                ],
                                "source_ids": ["source.pdf:p003"],
                            }
                        ],
                    }
                ],
            }

            result = build_normalized_docx(job, manifest, job.normalized_source)

            with zipfile.ZipFile(job.normalized_source) as package:
                document = etree.fromstring(package.read("word/document.xml"))
            paragraph = self._paragraph_with_text(document, "Evaluate")
            self.assertEqual(len(paragraph.findall(".//w:drawing", NS)), 1)
            self.assertIsNotNone(paragraph.find(".//wp:inline", NS))
            picture_properties = paragraph.find(".//wp:docPr", NS)
            self.assertEqual(picture_properties.get("descr"), "x squared plus one")
            self.assertEqual(result["image_checks"][0]["alt_text"], "x squared plus one")
            self.assertGreaterEqual(
                result["image_checks"][0]["effective_dpi"],
                300,
            )

    def test_question_formula_run_fails_closed_below_print_dpi(self) -> None:
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            Image.new("RGB", (100, 50), "white").save(temporary / "inline-low.png")
            job = self._job(root, temporary)
            manifest = {
                "book_name": "Low DPI Inline Formula Fixture",
                "pages": [
                    {
                        "source_page": 3,
                        "blocks": [
                            {
                                "kind": "question",
                                "label": "Q1.",
                                "hindi_runs": [
                                    {"text": "Solve ", "language": "latin"},
                                    {
                                        "formula_image": {
                                            "path": "inline-low.png",
                                            "alt_text": "low resolution fraction",
                                            "width_inches": 2.0,
                                        }
                                    },
                                ],
                                "source_ids": ["source.pdf:p003"],
                            }
                        ],
                    }
                ],
            }

            with self.assertRaisesRegex(
                FrameworkError,
                "effective DPI is too low",
            ):
                build_normalized_docx(job, manifest, job.normalized_source)
            self.assertFalse(job.normalized_source.exists())

if __name__ == "__main__":
    unittest.main()

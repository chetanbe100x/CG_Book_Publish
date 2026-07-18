from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfWriter

from framework.core.models import FrameworkError, IntegrityError, sha256_file
from framework.ingest.extract import (
    attach_answer_line_geometry,
    detect_answer_line_rectangles,
    extract_book_ir_job,
    extract_question_anchors,
    formula_image_block,
    infer_answer_line_count,
)
from framework.ingest.ir import load_book_ir
from framework.ingest.structured import (
    UnicodeSanitizationError,
    language_runs,
    parse_structured_file,
    parse_structured_lines,
    parse_structured_page,
    sanitize_text,
)


class UnicodeSanitizationTests(unittest.TestCase):
    def test_normalizes_real_unicode_and_spacing(self) -> None:
        self.assertEqual(sanitize_text("  cafe\u0301\u00a0  text  "), "caf\u00e9 text")

    def test_rejects_destructive_placeholders_and_mojibake(self) -> None:
        values = (
            "bad\x00text",
            "bad\ufffdtext",
            "\u00e0\u00a4\u00af\u00e0\u00a4\u00a6\u00e0\u00a4\u00bf",
        )
        for value in values:
            with self.subTest(value=repr(value)):
                with self.assertRaises(UnicodeSanitizationError):
                    sanitize_text(value)

    def test_routes_devanagari_and_math_to_separate_runs(self) -> None:
        runs = language_runs("\u092f\u0926\u093f x + 1 = 3", default="math")
        self.assertEqual(runs[0], {"text": "\u092f\u0926\u093f", "language": "hindi"})
        self.assertEqual(runs[1], {"text": " x + 1 = 3", "language": "math"})


class StructuredLineParserTests(unittest.TestCase):
    def test_groups_bilingual_question_with_stable_identity_and_runs(self) -> None:
        blocks = parse_structured_lines(
            [
                "Q1. \u092f\u0926\u093f (x + 1, y - 2) = (3, 1) \u0939\u094b \u0924\u094b x \u0935 y \u0915\u093e \u092e\u093e\u0928 -",
                "If (x + 1, y - 2) = (3, 1), find x and y.",
            ],
            "source.pdf:p014",
        )

        self.assertEqual(len(blocks), 1)
        question = blocks[0]
        self.assertEqual(question["kind"], "question")
        self.assertEqual(question["question_id"], "q-p014-001")
        self.assertEqual(question["label"], "Q1.")
        self.assertEqual(question["label_layout"], "inline")
        self.assertIn("\u092f\u0926\u093f", question["hindi"])
        self.assertIn("find x and y", question["english"])
        self.assertTrue(question["hindi_runs"])
        self.assertTrue(question["english_runs"])

    def test_classifies_and_merges_print_headings(self) -> None:
        result = parse_structured_page(
            [
                "\u0905\u0927\u094d\u092f\u093e\u092f\u20144 (Unit 2)",
                "\u0938\u092e\u094d\u092e\u093f\u0936\u094d\u0930 \u0938\u0902\u0916\u094d\u092f\u093e\u090f\u0901 \u090f\u0935\u0902 \u0926\u094d\u0935\u093f\u0918\u093e\u0924\u0940\u092f \u0938\u092e\u0940\u0915\u0930\u0923 (Complex Numbers and",
                "Quadratic Equations)",
                "\u092c\u0939\u0941\u0935\u093f\u0915\u0932\u094d\u092a\u0940\u092f \u092a\u094d\u0930\u0936\u094d\u0928 (MULTIPLE CHOICE QUESTIONS) 1 MARK",
                "QUESTION",
                "Q1. \u092a\u094d\u0930\u0936\u094d\u0928",
                "Question.",
            ],
            "source.pdf:p033",
        )

        headings = [
            block for block in result.blocks if block["kind"] == "heading"
        ]
        self.assertEqual(
            [block["role"] for block in headings],
            ["unit_heading", "chapter_heading", "question_type_heading"],
        )
        self.assertEqual(
            headings[1]["text"],
            "\u0938\u092e\u094d\u092e\u093f\u0936\u094d\u0930 \u0938\u0902\u0916\u094d\u092f\u093e\u090f\u0901 \u090f\u0935\u0902 \u0926\u094d\u0935\u093f\u0918\u093e\u0924\u0940\u092f \u0938\u092e\u0940\u0915\u0930\u0923 "
            "(Complex Numbers and Quadratic Equations)",
        )
        self.assertTrue(headings[2]["text"].endswith("1 MARK QUESTION"))
        self.assertEqual(headings[0]["source_ids"], ["source.pdf:p033"])
        self.assertIn("latin", {run["language"] for run in headings[1]["runs"]})

    def test_merges_wrapped_short_answer_heading(self) -> None:
        result = parse_structured_page(
            [
                "\u0932\u0918\u0941 \u0909\u0924\u094d\u0924\u0930\u0940\u092f \u092a\u094d\u0930\u0936\u094d\u0928 (03 \u0905\u0902\u0915 \u0915\u0947 \u092a\u094d\u0930\u0936\u094d\u0928) "
                "SHORT ANSWER QUESTION (03",
                "MARKS QUESTION)",
                "Q1. \u092e\u093e\u0928 \u091c\u094d\u091e\u093e\u0924 \u0915\u0940\u091c\u093f\u090f\u0964",
                "Find the value.",
            ],
            "source.pdf:p047",
        )
        heading = result.blocks[0]
        self.assertEqual(heading["kind"], "heading")
        self.assertEqual(heading["role"], "question_type_heading")
        self.assertTrue(heading["text"].endswith("(03 MARKS QUESTION)"))

    def test_detects_option_layout_and_attaches_to_question(self) -> None:
        result = parse_structured_page(
            [
                "MULTIPLE CHOICE QUESTIONS",
                "Q2. \u092b\u0932\u0928 f(x) = sin x \u090f\u0915 \u092a\u094d\u0930\u0915\u093e\u0930 \u0939\u0948\u0964",
                "What type of function is f(x) = sin x?",
                "(A) Odd function        (B) Even function",
                "(C) Polynomial function (D) None of them",
            ],
            "source.pdf:p014",
        )

        self.assertEqual(result.page_type, "mcq")
        self.assertEqual(
            [block["kind"] for block in result.blocks],
            ["heading", "question", "options"],
        )
        self.assertEqual(result.blocks[0]["role"], "question_type_heading")
        options = result.blocks[2]
        self.assertEqual(options["columns"], 2)
        self.assertEqual(options["layout"], "two_by_two")
        self.assertEqual(options["label_layout"], "parenthesized")
        self.assertEqual(options["for_question"], "q-p014-001")
        self.assertEqual([item["label"] for item in options["items"]], ["A", "B", "C", "D"])
        self.assertEqual(result.review_items, [])

    def test_merges_complementary_stacked_option_fragments(self) -> None:
        result = parse_structured_page(
            [
                "Q3. Function domain.",
                "The domain of the function is?",
                "(A) R - { }2                                        (B) R",
                "                                                            (D) none",
                "                   3",
                "(C) R - {- }2",
                "                    3",
                "Q4. Next question.",
                "Translate next question.",
            ],
            "source.pdf:p014",
        )

        option_blocks = [
            block for block in result.blocks if block["kind"] == "options"
        ]
        self.assertEqual(len(option_blocks), 1)
        options = option_blocks[0]
        self.assertEqual(options["for_question"], "q-p014-001")
        self.assertEqual(
            [item["label"] for item in options["items"]],
            ["A", "B", "C", "D"],
        )
        values = {item["label"]: item["text"] for item in options["items"]}
        self.assertTrue(values["A"].endswith("3"))
        self.assertTrue(values["C"].endswith("3"))
        self.assertNotIn(
            "option_sequence",
            {item["type"] for item in result.review_items},
        )
        self.assertNotIn(
            "3",
            [
                block.get("text")
                for block in result.blocks
                if block["kind"] == "paragraph"
            ],
        )

    def test_detects_one_and_four_column_option_layouts(self) -> None:
        one_column = parse_structured_lines(
            ["(A) Alpha", "(B) Beta", "(C) Gamma", "(D) Delta"],
            "source.pdf:p001",
        )
        four_column = parse_structured_lines(
            ["(A) 1 (B) 2 (C) 3 (D) 4"],
            "source.pdf:p002",
        )

        self.assertEqual(one_column[0]["layout"], "one_column")
        self.assertEqual(four_column[0]["layout"], "four_inline")

    def test_answer_lines_attach_to_the_preceding_question(self) -> None:
        result = parse_structured_page(
            [
                "Q3. \u092e\u093e\u0928 \u091c\u094d\u091e\u093e\u0924 \u0915\u0940\u091c\u093f\u090f\u0964",
                "Find the value.",
                "........................................",
                "........................................",
            ],
            "source.pdf:p047",
        )
        self.assertEqual([block["kind"] for block in result.blocks], ["question", "answer_lines"])
        answer_lines = result.blocks[1]
        self.assertEqual(answer_lines["count"], 2)
        self.assertEqual(answer_lines["spacing_points"], 30.5)
        self.assertEqual(answer_lines["for_question"], "q-p047-001")

    def test_routes_ambiguous_extraction_to_review_queue(self) -> None:
        result = parse_structured_page(
            ["Q7. Sample question", "(A) Alpha", "(C) Gamma"],
            "source.pdf:p006",
        )
        types = {item["type"] for item in result.review_items}
        self.assertEqual(types, {"missing_translation", "option_sequence"})
        options = next(block for block in result.blocks if block["kind"] == "options")
        self.assertEqual(options["confidence"], "medium")

    def test_preserves_incomplete_option_anchor_as_reviewable_text(self) -> None:
        result = parse_structured_page(["(A)"], "source.pdf:p006")
        self.assertEqual(result.blocks[0]["kind"], "paragraph")
        self.assertEqual(result.blocks[0]["text"], "(A)")
        self.assertEqual(result.review_items[0]["type"], "incomplete_options")

    def test_reads_extracted_text_via_pathlib(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            path = Path(temporary_name) / "page-007.txt"
            path.write_text("Q7. Sample question\n", encoding="utf-8")
            blocks = parse_structured_file(path)
        self.assertEqual(blocks[0]["kind"], "question")
        self.assertEqual(blocks[0]["question_id"], "q-p000-001")


class FormulaImageBlockTests(unittest.TestCase):
    def test_requires_complete_formula_crop_metadata(self) -> None:
        block = formula_image_block(
            path="figures/formula-014-01.png",
            crop_bbox_points=[10, 20, 110, 70],
            alt_text="fraction one over three x plus two",
            source_id="source.pdf:p014",
            for_question="q-p014-003",
            effective_dpi=320,
        )
        self.assertEqual(block["kind"], "formula_image")
        self.assertEqual(block["for_question"], "q-p014-003")
        with self.assertRaises(ValueError):
            formula_image_block(
                path="",
                crop_bbox_points=[10, 20, 110, 70],
                alt_text="formula",
                source_id="source.pdf:p014",
            )


class BookIrExtensionTests(unittest.TestCase):
    def _source_pdf(self, directory: Path) -> Path:
        source = directory / "source.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        with source.open("wb") as stream:
            writer.write(stream)
        return source

    def test_validates_formula_canvas_page_type_and_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            source = self._source_pdf(temporary)
            manifest_path = temporary / "book_ir.json"
            source_id = "source.pdf:p001"
            value = {
                "schema_version": 1,
                "book_name": "Fixture",
                "scope": "full",
                "source": {"sha256": sha256_file(source), "page_count": 1},
                "pages": [
                    {
                        "source_page": 1,
                        "page_type": "short_answer",
                        "utilization_exempt": True,
                        "utilization_exempt_reason": "source_intentionally_sparse",
                        "blocks": [
                            {
                                "kind": "question",
                                "question_id": "q-p001-001",
                                "label": "Q1.",
                                "label_layout": "inline",
                                "english_runs": [{"text": "Draw it.", "language": "latin"}],
                                "source_ids": [source_id],
                            },
                            formula_image_block(
                                path="formula.png",
                                crop_bbox_points=[10, 20, 110, 70],
                                alt_text="one over x",
                                source_id=source_id,
                                for_question="q-p001-001",
                            ),
                            {
                                "kind": "answer_canvas",
                                "canvas_type": "graph",
                                "height_points": 240,
                                "for_question": "q-p001-001",
                                "source_ids": [source_id],
                            },
                        ],
                    }
                ],
            }
            manifest_path.write_text(json.dumps(value), encoding="utf-8")
            loaded = load_book_ir(manifest_path, source_pdf=source)
            self.assertEqual(loaded["pages"][0]["page_type"], "short_answer")
            value["pages"][0]["blocks"][2]["for_question"] = "missing"
            manifest_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(FrameworkError):
                load_book_ir(manifest_path, source_pdf=source)


class _FakeGeometryPage:
    def __init__(
        self,
        *,
        rects: list[dict[str, object]] | None = None,
        words: list[dict[str, object]] | None = None,
    ) -> None:
        self.rects = rects or []
        self._words = words or []

    def extract_words(self, **_: object) -> list[dict[str, object]]:
        return self._words


class AnswerLineGeometryTests(unittest.TestCase):
    def _rectangle(
        self,
        *,
        top: float,
        height: float,
        x0: float = 51.0,
        width: float = 493.0,
        color: object = "P1334",
    ) -> dict[str, object]:
        return {
            "x0": x0,
            "top": top,
            "x1": x0 + width,
            "bottom": top + height,
            "width": width,
            "height": height,
            "stroking_color": None,
            "non_stroking_color": color,
        }

    def test_detects_only_large_patterned_source_rectangles(self) -> None:
        page = _FakeGeometryPage(
            rects=[
                self._rectangle(top=200, height=201),
                self._rectangle(top=200, height=201, color=(0, 0, 0)),
                self._rectangle(top=200, height=201, x0=100),
                self._rectangle(top=200, height=201, width=300),
                self._rectangle(top=200, height=40),
            ]
        )
        detected = detect_answer_line_rectangles(page)
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0]["pattern_color"], "P1334")

    def test_extracts_question_anchors_and_source_pitch(self) -> None:
        page = _FakeGeometryPage(
            words=[
                {"text": "Q2.", "top": 320.0},
                {"text": "body", "top": 340.0},
                {"text": "Q1.", "top": 80.0},
            ]
        )
        self.assertEqual(
            [anchor["number"] for anchor in extract_question_anchors(page)],
            [1, 2],
        )
        self.assertEqual(infer_answer_line_count(201.0), (7, 1.5))
        self.assertIsNone(infer_answer_line_count(210.0)[0])

    def test_attaches_answer_lines_in_verified_vertical_order(self) -> None:
        source_id = "source.pdf:p047"
        blocks = [
            {
                "kind": "question",
                "question_id": "q-p047-001",
                "label": "Q4.",
                "source_ids": [source_id],
            },
            {
                "kind": "options",
                "for_question": "q-p047-001",
                "source_ids": [source_id],
            },
            {
                "kind": "question",
                "question_id": "q-p047-002",
                "label": "Q5.",
                "source_ids": [source_id],
            },
        ]
        rectangles = [
            {
                **self._rectangle(top=250, height=201),
                "pattern_color": "P1334",
            },
            {
                **self._rectangle(top=500, height=87),
                "pattern_color": "P1334",
            },
        ]
        attached, reviews = attach_answer_line_geometry(
            blocks,
            question_anchors=[
                {"number": 4, "top": 100.0},
                {"number": 5, "top": 400.0},
            ],
            rectangles=rectangles,
            source_id=source_id,
            page_number=47,
        )

        self.assertEqual(reviews, [])
        self.assertEqual(
            [block["kind"] for block in attached],
            ["question", "options", "answer_lines", "question", "answer_lines"],
        )
        answer_blocks = [
            block for block in attached if block["kind"] == "answer_lines"
        ]
        self.assertEqual([block["count"] for block in answer_blocks], [7, 3])
        self.assertEqual(
            [block["for_question"] for block in answer_blocks],
            ["q-p047-001", "q-p047-002"],
        )
        self.assertEqual(answer_blocks[0]["spacing_points"], 28.5)
        self.assertEqual(
            answer_blocks[0]["source_evidence"]["type"],
            "pdf_tiling_pattern_rectangle",
        )
        self.assertEqual(
            answer_blocks[0]["source_bbox_points"],
            [51.0, 250, 544.0, 451],
        )

    def test_blocks_ambiguous_mapping_without_guessing(self) -> None:
        source_id = "source.pdf:p047"
        blocks = [
            {
                "kind": "question",
                "question_id": "q-p047-001",
                "label": "Q1.",
                "source_ids": [source_id],
            }
        ]
        rectangle = {
            **self._rectangle(top=250, height=201),
            "pattern_color": "P1334",
        }
        attached, reviews = attach_answer_line_geometry(
            blocks,
            question_anchors=[{"number": 2, "top": 100.0}],
            rectangles=[rectangle],
            source_id=source_id,
            page_number=47,
        )
        self.assertEqual(attached, blocks)
        self.assertEqual(len(reviews), 1)
        self.assertTrue(reviews[0]["blocking"])
        self.assertEqual(reviews[0]["type"], "answer_line_geometry")


class DraftExtractionTests(unittest.TestCase):
    def test_writes_drafts_without_overwriting_reviewed_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            book = Path(temporary_name)
            source = book / "source.pdf"
            source.write_bytes(b"fixture")
            reviewed = book / "Work" / "book_ir.full.json"
            reviewed.parent.mkdir()
            reviewed.write_text('{"reviewed": true}\n', encoding="utf-8")
            reviewed_queue = book / "Review" / "review_queue.json"
            reviewed_queue.parent.mkdir()
            reviewed_queue.write_text('{"approved": true}\n', encoding="utf-8")
            job = SimpleNamespace(
                source_type="pdf",
                source=source,
                content_manifest=reviewed,
                manifest_path=book / "job.json",
                school_class="11",
                subject="Maths",
                content_page_numbers=(1,),
            )
            page_text = "Chapter ending note\n3x+2\n"
            before_manifest = reviewed.read_bytes()
            before_queue = reviewed_queue.read_bytes()
            with (
                patch(
                    "framework.ingest.extract.extract_pdf_pages",
                    return_value=([page_text], "fixture-extractor", 1),
                ),
                patch(
                    "framework.ingest.extract.extract_pdf_answer_geometry",
                    return_value={},
                ),
            ):
                result = extract_book_ir_job(job)
            self.assertEqual(reviewed.read_bytes(), before_manifest)
            self.assertEqual(reviewed_queue.read_bytes(), before_queue)
            draft = json.loads(Path(result["draft_manifest"]).read_text(encoding="utf-8"))
            self.assertTrue(draft["pages"][0]["utilization_exempt"])
            queue = json.loads(Path(result["review_queue"]).read_text(encoding="utf-8"))
            self.assertIn("formula_layout", {item["type"] for item in queue["items"]})
            self.assertEqual(queue["reviewed_manifest"]["sha256"], sha256_file(reviewed))

    def test_refuses_every_protected_draft_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            book = Path(temporary_name)
            source = book / "source.pdf"
            source.write_bytes(b"fixture")
            template = book / "template.docx"
            template.write_bytes(b"template")
            layout_reference = book / "layout-reference.docx"
            layout_reference.write_bytes(b"reference")
            reviewed = book / "Work" / "book_ir.json"
            reviewed.parent.mkdir()
            reviewed.write_text("{}", encoding="utf-8")
            reviewed_queue = book / "Review" / "review_queue.json"
            reviewed_queue.parent.mkdir()
            reviewed_queue.write_text("{}", encoding="utf-8")
            job = SimpleNamespace(
                source_type="pdf",
                source=source,
                template=template,
                layout_reference=layout_reference,
                content_manifest=reviewed,
                manifest_path=book / "job.json",
            )
            safe_output = book / "Work" / "candidate.draft.json"
            safe_review = book / "Review" / "candidate.draft.json"
            protected = (
                source,
                template,
                layout_reference,
                reviewed,
                reviewed_queue,
            )
            for destination in protected:
                with self.subTest(destination=destination, kind="manifest"):
                    with self.assertRaises(IntegrityError):
                        extract_book_ir_job(
                            job,
                            output_path=destination,
                            review_path=safe_review,
                        )
                with self.subTest(destination=destination, kind="review"):
                    with self.assertRaises(IntegrityError):
                        extract_book_ir_job(
                            job,
                            output_path=safe_output,
                            review_path=destination,
                        )


if __name__ == "__main__":
    unittest.main()

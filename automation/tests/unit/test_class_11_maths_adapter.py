from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from framework.adapters.class_11_maths_pdf import _enrich_manifest, prepare
from framework.core.models import JobConfig


class Class11MathsAdapterTests(unittest.TestCase):
    @staticmethod
    def _job() -> JobConfig:
        placeholder = Path("placeholder.docx")
        return JobConfig(
            manifest_path=Path("job.json"),
            job_id="adapter-test",
            school_class="11",
            subject="Maths",
            source=Path("Maths_11th.pdf"),
            template=placeholder,
            preview_output=Path("preview.docx"),
            final_output=Path("final.docx"),
            approved_reference=None,
            qa_dir=Path("QA"),
            source_type="pdf",
            normalized_source=Path("normalized.docx"),
            content_manifest=Path("book_ir.full.json"),
        )

    @staticmethod
    def _question(question_id: str) -> dict:
        return {
            "kind": "question",
            "question_id": question_id,
            "label": "Q.",
            "hindi": "??????",
            "english": "Question",
        }

    def test_inserts_source_figure_after_its_option_group(self) -> None:
        manifest = {
            "pages": [
                {
                    "source_page": 3,
                    "blocks": [
                        self._question("q-p003-002"),
                        {
                            "kind": "options",
                            "for_question": "q-p003-002",
                            "items": [
                                {
                                    "label": "D",
                                    "text": "(A - B) U (B - C) A B C",
                                }
                            ],
                        },
                        {"kind": "paragraph", "text": "A B C"},
                    ],
                }
            ]
        }

        _enrich_manifest(self._job(), manifest)

        blocks = manifest["pages"][0]["blocks"]
        self.assertEqual([block["kind"] for block in blocks], ["question", "options", "figure"])
        figure = blocks[-1]
        self.assertEqual(figure["for_question"], "q-p003-002")
        self.assertEqual(figure["crop_dpi"], 300)
        self.assertTrue(figure["alt_text"])
        self.assertEqual(
            blocks[1]["items"][0]["text"],
            "(A - B) U (B - C)",
        )

    def test_attaches_table_to_the_correct_question_and_cleans_extracted_tokens(self) -> None:
        manifest = {
            "pages": [
                {
                    "source_page": 94,
                    "blocks": [
                        self._question("q-p094-001"),
                        self._question("q-p094-002"),
                    ],
                }
            ]
        }

        _enrich_manifest(self._job(), manifest)

        blocks = manifest["pages"][0]["blocks"]
        self.assertEqual(blocks[-1]["kind"], "figure")
        self.assertEqual(blocks[-1]["for_question"], "q-p094-002")
        self.assertEqual(
            blocks[1]["english"],
            "Find the mean deviation of the given data.",
        )

    def test_preserves_source_canvas_dimensions_and_question_binding(self) -> None:
        manifest = {
            "pages": [
                {
                    "source_page": 19,
                    "blocks": [
                        self._question("q-p019-001"),
                        {
                            "kind": "answer_lines",
                            "for_question": "q-p019-001",
                            "count": 4,
                        },
                        self._question("q-p019-002"),
                    ],
                }
            ]
        }

        _enrich_manifest(self._job(), manifest)

        blocks = manifest["pages"][0]["blocks"]
        self.assertEqual(
            [block["kind"] for block in blocks],
            [
                "question",
                "figure",
                "answer_lines",
                "question",
                "answer_canvas",
            ],
        )
        canvas = blocks[-1]
        self.assertEqual(canvas["for_question"], "q-p019-002")
        self.assertAlmostEqual(canvas["height_points"], 115.5)
        self.assertTrue(canvas["source_detected"])

        self.assertTrue(canvas["border"])
    def test_replaces_verified_complex_math_with_inline_source_crops(self) -> None:
        manifest = {
            "pages": [
                {
                    "source_page": 14,
                    "blocks": [
                        self._question("q-p014-003"),
                        {
                            "kind": "options",
                            "for_question": "q-p014-003",
                            "items": [
                                {"label": label, "text": label}
                                for label in ("A", "B", "C", "D")
                            ],
                        },
                    ],
                }
            ]
        }

        _enrich_manifest(self._job(), manifest)

        question, options = manifest["pages"][0]["blocks"]
        self.assertIn("hindi", question)
        formulas = [
            run["formula_image"]
            for run in question["hindi_runs"] + question["english_runs"]
            if "formula_image" in run
        ]
        self.assertEqual(len(formulas), 2)
        self.assertTrue(all(value["crop_dpi"] == 400 for value in formulas))
        by_label = {item["label"]: item for item in options["items"]}
        self.assertIn("formula_image", by_label["A"])
        self.assertIn("formula_image", by_label["C"])
        self.assertEqual(by_label["B"]["text"], "B")

    def test_prepare_walks_nested_formula_images_at_400_dpi(self) -> None:
        formulas: list[dict] = []

        def formula(name: str) -> dict:
            value = {
                "path": f"formulas/{name}.png",
                "crop_bbox_points": [10.0, 20.0, 154.0, 56.0],
                "alt_text": f"Formula {name}",
                "width_inches": 2.0,
                "effective_dpi": 300,
            }
            formulas.append(value)
            return value

        manifest = {
            "pages": [
                {
                    "source_page": 4,
                    "blocks": [
                        {
                            "kind": "question",
                            "question_id": "q-p004-001",
                            "label": "Q1.",
                            "hindi_runs": [
                                {"formula_image": formula("question-hindi")}
                            ],
                            "english_runs": [
                                {"formula_image": formula("question-english")}
                            ],
                        },
                        {
                            "kind": "paragraph",
                            "runs": [
                                {"text": "Use ", "language": "latin"},
                                {"formula_image": formula("paragraph")},
                            ],
                        },
                        {
                            "kind": "options",
                            "items": [
                                {
                                    "label": "A",
                                    "formula_image": formula("option-direct"),
                                },
                                {
                                    "label": "B",
                                    "runs": [
                                        {
                                            "formula_image": formula(
                                                "option-run"
                                            )
                                        }
                                    ],
                                },
                            ],
                        },
                    ],
                }
            ]
        }

        with patch(
            "framework.adapters.class_11_maths_pdf._prepare_crop",
            return_value=(800, 200),
        ) as prepare_crop:
            prepare(self._job(), manifest)

        self.assertEqual(prepare_crop.call_count, len(formulas))
        self.assertTrue(
            all(call.kwargs["dpi"] == 400 for call in prepare_crop.call_args_list)
        )
        for value in formulas:
            self.assertEqual(value["rendered_pixels"], [800, 200])
            self.assertEqual(value["rendered_dpi"], 400)
            self.assertEqual(value["effective_dpi"], 400.0)

if __name__ == "__main__":
    unittest.main()


from __future__ import annotations

import unittest

from framework.core.models import FrameworkError
from framework.ingest.ir import _validate_block


class OptionRepresentationValidationTests(unittest.TestCase):
    SOURCE_ID = "source.pdf:p001"

    def _validate(self, block: dict) -> None:
        _validate_block(
            block,
            page_number=1,
            expected_source_id=self.SOURCE_ID,
            index=1,
        )

    def _options(self, items: list[dict]) -> dict:
        return {
            "kind": "options",
            "columns": 1,
            "layout": "one_column",
            "items": items,
            "source_ids": [self.SOURCE_ID],
        }

    def test_accepts_text_runs_and_nested_formula_image_items(self) -> None:
        self._validate(
            self._options(
                [
                    {"label": "A", "text": "Plain text"},
                    {
                        "label": "B",
                        "runs": [
                            {"text": "x", "language": "math"},
                            {"text": " = 2", "language": "latin"},
                        ],
                    },
                    {
                        "label": "C",
                        "formula_image": {
                            "kind": "formula_image",
                            "path": "figures/option-c.png",
                            "alt_text": "fraction x over y",
                            "effective_dpi": 320,
                            "crop_bbox_points": [10, 20, 110, 70],
                            "width_inches": 1.25,
                        },
                    },
                ]
            )
        )

    def test_rejects_option_without_a_supported_representation(self) -> None:
        with self.assertRaisesRegex(
            FrameworkError,
            "requires text, runs, or formula_image",
        ):
            self._validate(self._options([{"label": "A"}]))

    def test_rejects_incomplete_nested_formula_metadata(self) -> None:
        base = {
            "path": "figures/option-a.png",
            "alt_text": "square root of x",
            "effective_dpi": 300,
        }
        invalid_values = (
            ({**base, "alt_text": ""}, "alt_text"),
            ({**base, "effective_dpi": 0}, "effective_dpi"),
            ({**base, "effective_dpi": True}, "effective_dpi"),
            ({**base, "kind": "figure"}, "kind must be formula_image"),
        )
        for formula, message in invalid_values:
            with self.subTest(message=message):
                with self.assertRaisesRegex(FrameworkError, message):
                    self._validate(
                        self._options(
                            [{"label": "A", "formula_image": formula}]
                        )
                    )
class RichTextFormulaRunValidationTests(unittest.TestCase):
    SOURCE_ID = "source.pdf:p001"

    def _validate_formula(self, formula: dict, **run_values: object) -> None:
        _validate_block(
            {
                "kind": "paragraph",
                "runs": [{"formula_image": formula, **run_values}],
                "source_ids": [self.SOURCE_ID],
            },
            page_number=1,
            expected_source_id=self.SOURCE_ID,
            index=1,
        )

    def test_accepts_formula_run_without_declared_effective_dpi(self) -> None:
        self._validate_formula(
            {
                "path": "figures/inline-formula.png",
                "alt_text": "fraction x over y",
                "width_inches": 1.25,
                "crop_bbox_points": [10, 20, 110, 70],
            }
        )

    def test_rejects_ambiguous_or_incomplete_formula_runs(self) -> None:
        base = {
            "path": "figures/inline-formula.png",
            "alt_text": "fraction x over y",
            "width_inches": 1.25,
        }
        invalid_values = (
            ({**base, "path": ""}, {}, "path"),
            ({**base, "alt_text": ""}, {}, "alt_text"),
            ({**base, "width_inches": 0}, {}, "width_inches"),
            ({**base, "effective_dpi": 0}, {}, "effective_dpi"),
            (base, {"text": "duplicate"}, "exactly one"),
        )
        for formula, run_values, message in invalid_values:
            with self.subTest(message=message):
                with self.assertRaisesRegex(FrameworkError, message):
                    self._validate_formula(formula, **run_values)




class TechnicalImageValidationTests(unittest.TestCase):
    SOURCE_ID = "source.pdf:p001"

    def _validate(self, kind: str, **values: object) -> None:
        _validate_block(
            {
                "kind": kind,
                "path": "figures/source.png",
                "alt_text": "Technical diagram from the source",
                "effective_dpi": 300,
                "source_ids": [self.SOURCE_ID],
                **values,
            },
            page_number=1,
            expected_source_id=self.SOURCE_ID,
            index=1,
        )

    def test_figure_and_formula_image_require_alt_text_and_effective_dpi(self) -> None:
        for kind in ("figure", "formula_image"):
            with self.subTest(kind=kind, valid=True):
                self._validate(kind)
            with self.subTest(kind=kind, missing_alt=True):
                with self.assertRaisesRegex(FrameworkError, "alt_text"):
                    self._validate(kind, alt_text="")
            with self.subTest(kind=kind, invalid_dpi=True):
                with self.assertRaisesRegex(FrameworkError, "effective_dpi"):
                    self._validate(kind, effective_dpi=-1)


if __name__ == "__main__":
    unittest.main()

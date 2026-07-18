from __future__ import annotations

import hashlib
import json
from math import isfinite
from pathlib import Path
from typing import Any

from ..core.models import FrameworkError, sha256_file


ALLOWED_BLOCK_KINDS = {
    "heading",
    "paragraph",
    "question",
    "options",
    "equation",
    "figure",
    "formula_image",
    "table",
    "spacer",
    "answer_lines",
    "answer_canvas",
}
ALLOWED_CONFIDENCE = {"high", "medium"}
ALLOWED_PAGE_TYPES = {"mcq", "fill_blank", "short_answer", "long_answer", "mixed", "chapter_end", "other"}
ALLOWED_OPTION_LAYOUTS = {"one_column": 1, "two_by_two": 2, "four_inline": 4}


def manifest_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FrameworkError(f"{label} must be non-empty text")
    return value


def _validate_runs(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise FrameworkError(f"{label} must be a non-empty array")
    for index, run in enumerate(value, start=1):
        if not isinstance(run, dict):
            raise FrameworkError(f"{label} run {index} must be an object")
        run_label = f"{label} run {index}"
        has_text = isinstance(run.get("text"), str) and bool(run["text"].strip())
        has_formula = run.get("formula_image") is not None
        if has_text == has_formula:
            raise FrameworkError(
                f"{run_label} requires exactly one of text or formula_image"
            )
        if has_formula:
            _validate_image(
                run["formula_image"],
                f"{run_label}.formula_image",
                nested_formula=True,
                require_effective_dpi=False,
                require_width=True,
            )
            continue

        _require_text(run.get("text"), f"{run_label}.text")
        language = run.get("language", "latin")
        if language not in {"hindi", "latin", "math"}:
            raise FrameworkError(f"{run_label} has invalid language")


def _positive_number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FrameworkError(f"{label} must be positive")
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise FrameworkError(f"{label} must be positive")
    return result


def _validate_image(
    value: Any,
    label: str,
    *,
    nested_formula: bool = False,
    require_effective_dpi: bool = True,
    require_width: bool = False,
) -> None:
    if not isinstance(value, dict):
        raise FrameworkError(f"{label} must be an object")
    declared_kind = value.get("kind")
    if nested_formula and declared_kind not in {None, "formula_image"}:
        raise FrameworkError(f"{label}.kind must be formula_image when provided")
    _require_text(value.get("path"), f"{label}.path")
    _require_text(value.get("alt_text"), f"{label}.alt_text")
    if require_effective_dpi or "effective_dpi" in value:
        _positive_number(value.get("effective_dpi"), f"{label}.effective_dpi")
    if require_width:
        _positive_number(value.get("width_inches"), f"{label}.width_inches")
    _validate_bbox(value.get("crop_bbox_points"), f"{label}.crop_bbox_points")
    for name in ("width_inches", "height_inches"):
        if name in value:
            _positive_number(value[name], f"{label}.{name}")


def _validate_option_content(option: dict[str, Any], label: str) -> None:
    has_text = isinstance(option.get("text"), str) and bool(option["text"].strip())
    has_runs = isinstance(option.get("runs"), list) and bool(option["runs"])
    has_formula = option.get("formula_image") is not None
    if not (has_text or has_runs or has_formula):
        raise FrameworkError(f"{label} requires text, runs, or formula_image")
    if "text" in option:
        _require_text(option["text"], f"{label}.text")
    if "runs" in option:
        _validate_runs(option["runs"], f"{label}.runs")
    if "formula_image" in option:
        _validate_image(
            option["formula_image"],
            f"{label}.formula_image",
            nested_formula=True,
        )


def _validate_bbox(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or len(value) != 4 or not all(
        isinstance(item, (int, float)) for item in value
    ):
        raise FrameworkError(f"{label} must contain four numeric values")
    left, top, right, bottom = (float(item) for item in value)
    if left < 0 or top < 0 or right <= left or bottom <= top:
        raise FrameworkError(f"{label} must describe a positive rectangle")


def _validate_block(
    block: Any,
    *,
    page_number: int,
    expected_source_id: str,
    index: int,
) -> None:
    label = f"page {page_number} block {index}"
    if not isinstance(block, dict):
        raise FrameworkError(f"{label} must be an object")
    kind = block.get("kind")
    if kind not in ALLOWED_BLOCK_KINDS:
        raise FrameworkError(f"{label} has unsupported kind: {kind}")
    confidence = block.get("confidence", "high")
    if confidence not in ALLOWED_CONFIDENCE:
        raise FrameworkError(
            f"{label} confidence must be high or medium; low-confidence content "
            "belongs in the review queue"
        )
    source_ids = block.get("source_ids")
    if not isinstance(source_ids, list) or not source_ids:
        raise FrameworkError(f"{label} requires source_ids")
    if expected_source_id not in source_ids:
        raise FrameworkError(
            f"{label} must include its source page ID: {expected_source_id}"
        )
    for_question = block.get("for_question")
    if for_question is not None:
        _require_text(for_question, f"{label}.for_question")

    if kind in {"heading", "paragraph", "equation"}:
        has_text = isinstance(block.get("text"), str) and bool(block["text"].strip())
        has_runs = isinstance(block.get("runs"), list) and bool(block["runs"])
        if not (has_text or has_runs):
            raise FrameworkError(f"{label} requires text or runs")
        if has_runs:
            _validate_runs(block["runs"], f"{label}.runs")
    elif kind == "question":
        question_id = block.get("question_id")
        if question_id is not None:
            _require_text(question_id, f"{label}.question_id")
        _require_text(block.get("label"), f"{label}.label")
        label_layout = block.get("label_layout", "inline")
        if label_layout not in {"inline", "standalone"}:
            raise FrameworkError(f"{label}.label_layout is unsupported")
        has_plain_text = any(
            isinstance(block.get(name), str) and block[name].strip()
            for name in ("hindi", "english")
        )
        has_run_text = any(
            isinstance(block.get(name), list) and block[name]
            for name in ("hindi_runs", "english_runs")
        )
        if not (has_plain_text or has_run_text):
            raise FrameworkError(f"{label} requires Hindi or English text/runs")
        for name in ("hindi_runs", "english_runs"):
            if name in block:
                _validate_runs(block[name], f"{label}.{name}")
    elif kind == "options":
        options = block.get("items")
        if not isinstance(options, list) or not options:
            raise FrameworkError(f"{label} requires option items")
        labels: list[str] = []
        for option_index, option in enumerate(options, start=1):
            if not isinstance(option, dict):
                raise FrameworkError(f"{label} option {option_index} must be an object")
            option_label = _require_text(
                option.get("label"), f"{label} option {option_index}.label"
            )
            labels.append(option_label)
            _validate_option_content(
                option, f"{label} option {option_index}"
            )
        if len(labels) != len(set(labels)):
            raise FrameworkError(f"{label} option labels must be unique")
        columns = block.get("columns", 2)
        if not isinstance(columns, int) or columns not in {1, 2, 4}:
            raise FrameworkError(f"{label}.columns must be 1, 2, or 4")
        layout = block.get("layout")
        if layout is not None:
            if layout not in ALLOWED_OPTION_LAYOUTS:
                raise FrameworkError(f"{label}.layout is unsupported")
            if ALLOWED_OPTION_LAYOUTS[layout] != columns:
                raise FrameworkError(f"{label}.layout does not match columns")
        if block.get("label_layout", "parenthesized") not in {
            "parenthesized",
            "plain",
        }:
            raise FrameworkError(f"{label}.label_layout is unsupported")
    elif kind in {"figure", "formula_image"}:
        _validate_image(block, label)
    elif kind == "table":
        rows = block.get("rows")
        if not isinstance(rows, list) or not rows or not all(
            isinstance(row, list) and row for row in rows
        ):
            raise FrameworkError(f"{label} requires non-empty table rows")
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise FrameworkError(f"{label} table rows must have equal width")
    elif kind == "spacer":
        points = block.get("points")
        if not isinstance(points, (int, float)) or points < 0:
            raise FrameworkError(f"{label}.points must be non-negative")
    elif kind == "answer_lines":
        count = block.get("count")
        spacing = block.get("spacing_points", 16)
        if not isinstance(count, int) or not 1 <= count <= 50:
            raise FrameworkError(f"{label}.count must be an integer from 1 to 50")
        if not isinstance(spacing, (int, float)) or spacing <= 0:
            raise FrameworkError(f"{label}.spacing_points must be positive")
    elif kind == "answer_canvas":
        canvas_type = block.get("canvas_type", "blank")
        if canvas_type not in {"blank", "graph", "venn", "coordinate_grid", "diagram"}:
            raise FrameworkError(f"{label}.canvas_type is unsupported")
        height = block.get("height_points")
        if not isinstance(height, (int, float)) or height <= 0:
            raise FrameworkError(f"{label}.height_points must be positive")
        width = block.get("width_points")
        if width is not None and (not isinstance(width, (int, float)) or width <= 0):
            raise FrameworkError(f"{label}.width_points must be positive")


def load_book_ir(
    path: Path,
    *,
    source_pdf: Path,
    expected_pages: tuple[int, ...] = (),
) -> dict[str, Any]:
    if not path.is_file():
        raise FrameworkError(f"Book IR manifest not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrameworkError(f"Invalid book IR manifest: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FrameworkError("Book IR root must be an object")
    if value.get("schema_version") != 1:
        raise FrameworkError("Unsupported book IR schema_version")
    _require_text(value.get("book_name"), "book_name")
    scope = value.get("scope")
    if scope not in {"preview", "full"}:
        raise FrameworkError("Book IR scope must be preview or full")
    source = value.get("source")
    if not isinstance(source, dict):
        raise FrameworkError("Book IR requires source metadata")
    if source.get("sha256") != sha256_file(source_pdf):
        raise FrameworkError("Book IR source hash does not match the immutable PDF")
    page_count = source.get("page_count")
    if not isinstance(page_count, int) or page_count < 1:
        raise FrameworkError("Book IR source.page_count must be positive")
    pages = value.get("pages")
    if not isinstance(pages, list) or not pages:
        raise FrameworkError("Book IR requires pages")
    numbers: list[int] = []
    question_ids: set[str] = set()
    references: list[tuple[str, str]] = []
    for page_index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            raise FrameworkError(f"Book IR page {page_index} must be an object")
        page_number = page.get("source_page")
        if not isinstance(page_number, int) or not 1 <= page_number <= page_count:
            raise FrameworkError(f"Invalid source_page at Book IR page {page_index}")
        page_type = page.get("page_type")
        if page_type is not None and page_type not in ALLOWED_PAGE_TYPES:
            raise FrameworkError(f"Book IR page {page_number} has invalid page_type")
        utilization_exempt = page.get("utilization_exempt", False)
        if not isinstance(utilization_exempt, bool):
            raise FrameworkError(
                f"Book IR page {page_number}.utilization_exempt must be boolean"
            )
        if utilization_exempt:
            _require_text(
                page.get("utilization_exempt_reason"),
                f"Book IR page {page_number}.utilization_exempt_reason",
            )
        numbers.append(page_number)
        expected_source_id = f"{source_pdf.name}:p{page_number:03d}"
        blocks = page.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise FrameworkError(f"Book IR page {page_number} requires blocks")
        for block_index, block in enumerate(blocks, start=1):
            _validate_block(
                block,
                page_number=page_number,
                expected_source_id=expected_source_id,
                index=block_index,
            )
            if block.get("kind") == "question" and block.get("question_id"):
                question_id = str(block["question_id"])
                if question_id in question_ids:
                    raise FrameworkError(f"Duplicate question_id: {question_id}")
                question_ids.add(question_id)
            if block.get("for_question"):
                references.append(
                    (
                        str(block["for_question"]),
                        f"page {page_number} block {block_index}",
                    )
                )
    for question_id, reference_label in references:
        if question_id not in question_ids:
            raise FrameworkError(
                f"{reference_label}.for_question references unknown question_id: "
                f"{question_id}"
            )
    if len(numbers) != len(set(numbers)):
        raise FrameworkError("Book IR source pages must be unique")
    if expected_pages and tuple(numbers) != expected_pages:
        raise FrameworkError(
            "Book IR pages do not match preview_source_page_numbers: "
            f"expected {list(expected_pages)}, got {numbers}"
        )
    if scope == "preview" and not expected_pages:
        raise FrameworkError("Preview Book IR requires an explicit page selection")
    value["manifest_sha256"] = manifest_sha256(value)
    return value


def manifest_scope(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    return str(value.get("scope", ""))

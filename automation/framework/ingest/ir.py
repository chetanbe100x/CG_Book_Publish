from __future__ import annotations

import hashlib
import json
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
    "table",
    "spacer",
    "answer_lines",
    "answer_lines",
}
ALLOWED_CONFIDENCE = {"high", "medium"}


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
    if kind in {"heading", "paragraph", "equation"}:
        has_text = isinstance(block.get("text"), str) and bool(block["text"].strip())
        has_runs = isinstance(block.get("runs"), list) and bool(block["runs"])
        if not (has_text or has_runs):
            raise FrameworkError(f"{label} requires text or runs")
    elif kind == "question":
        _require_text(block.get("label"), f"{label}.label")
        if not any(
            isinstance(block.get(name), str) and block[name].strip()
            for name in ("hindi", "english")
        ):
            raise FrameworkError(f"{label} requires hindi or english text")
    elif kind == "options":
        options = block.get("items")
        if not isinstance(options, list) or not options:
            raise FrameworkError(f"{label} requires option items")
        for option_index, option in enumerate(options, start=1):
            if not isinstance(option, dict):
                raise FrameworkError(f"{label} option {option_index} must be an object")
            _require_text(option.get("label"), f"{label} option {option_index}.label")
            _require_text(option.get("text"), f"{label} option {option_index}.text")
    elif kind == "figure":
        _require_text(block.get("path"), f"{label}.path")
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
    elif kind == "answer_lines":
        count = block.get("count")
        spacing = block.get("spacing_points", 16)
        if not isinstance(count, int) or not 1 <= count <= 50:
            raise FrameworkError(f"{label}.count must be an integer from 1 to 50")
        if not isinstance(spacing, (int, float)) or spacing <= 0:
            raise FrameworkError(f"{label}.spacing_points must be positive")


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
    for page_index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            raise FrameworkError(f"Book IR page {page_index} must be an object")
        page_number = page.get("source_page")
        if not isinstance(page_number, int) or not 1 <= page_number <= page_count:
            raise FrameworkError(f"Invalid source_page at Book IR page {page_index}")
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

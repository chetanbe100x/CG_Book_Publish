from __future__ import annotations

import re
from typing import Any

from lxml import etree

from ..core.models import JobConfig
from ..core.package import DocxPackage, NS, W


A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0
MM_PER_TWIP = 25.4 / 1440.0
FORBIDDEN_TEXT = {
    "\x00": "NUL",
    "\ufffd": "Unicode replacement character",
    "\u25a1": "white square",
    "\u25a0": "black square",
}
OPTION_LABEL_RE = re.compile(r"\(([A-D])\)")
WORD_TRUE_VALUES = {"1", "true", "on"}
WORD_FALSE_VALUES = {"0", "false", "off"}


def _on_off(element: etree._Element | None, *, default: bool) -> bool:
    if element is None:
        return default
    value = element.get(W + "val")
    if value is None:
        return True
    normalized = value.strip().casefold()
    if normalized in WORD_TRUE_VALUES:
        return True
    if normalized in WORD_FALSE_VALUES:
        return False
    return default



def _attribute(element: etree._Element | None, name: str) -> str | None:
    return None if element is None else element.get(W + name)


def _bookmark_numbers(body: etree._Element) -> list[int]:
    values: list[int] = []
    for element in body.findall(".//w:bookmarkStart", NS):
        name = element.get(W + "name", "")
        if name.startswith("SourcePdfPage") and name[13:].isdigit():
            values.append(int(name[13:]))
    return values


def _option_table_errors(body: etree._Element) -> list[str]:
    errors: list[str] = []
    for table_index, table in enumerate(body.findall(".//w:tbl", NS), start=1):
        if table.findall(".//w:tbl", NS):
            continue
        grid_cols = table.findall("w:tblGrid/w:gridCol", NS)
        if any(_attribute(col, "w") == "540" for col in grid_cols):
            continue
        text = "".join(table.xpath(".//w:t/text()", namespaces=NS))
        labels = OPTION_LABEL_RE.findall(text)
        if not labels:
            continue
        properties = table.find("w:tblPr", NS)
        layout = None if properties is None else properties.find("w:tblLayout", NS)
        if _attribute(layout, "type") != "fixed":
            errors.append(f"Option table {table_index} is not fixed-layout")
        indent = None if properties is None else properties.find("w:tblInd", NS)
        indent_value = _attribute(indent, "w")
        if (
            _attribute(indent, "type") != "dxa"
            or not (indent_value or "").isdigit()
        ):
            errors.append(f"Option table {table_index} has no exact DXA indent")
        margins = None if properties is None else properties.find("w:tblCellMar", NS)
        for edge in ("top", "right", "bottom", "left"):
            margin = None if margins is None else margins.find(f"w:{edge}", NS)
            margin_value = _attribute(margin, "w")
            if (
                _attribute(margin, "type") != "dxa"
                or not (margin_value or "").isdigit()
            ):
                errors.append(
                    f"Option table {table_index} has no exact {edge} cell margin"
                )
        width = None if properties is None else properties.find("w:tblW", NS)
        width_value = _attribute(width, "w")
        if _attribute(width, "type") != "dxa" or not (width_value or "").isdigit():
            errors.append(f"Option table {table_index} has no exact DXA width")
            continue
        grid_values = [
            value
            for value in (
                _attribute(node, "w")
                for node in table.findall("w:tblGrid/w:gridCol", NS)
            )
            if value is not None and value.isdigit()
        ]
        if not grid_values:
            errors.append(f"Option table {table_index} has no explicit column grid")
        elif sum(int(value) for value in grid_values) != int(width_value):
            errors.append(
                f"Option table {table_index} grid does not match its table width"
            )
        rows = table.findall("w:tr", NS)
        if any(row.find("w:trPr/w:cantSplit", NS) is None for row in rows):
            errors.append(f"Option table {table_index} has a splittable row")
        expected = ["A", "B", "C", "D"]
        if labels != expected:
            errors.append(
                f"Option table {table_index} must contain labels A-D exactly once "
                f"in order; got {labels}"
            )
        if grid_values:
            grid_widths = [int(value) for value in grid_values]
            for row_index, row in enumerate(rows, start=1):
                cells = row.findall("w:tc", NS)
                if len(cells) != len(grid_widths):
                    errors.append(
                        f"Option table {table_index} row {row_index} cell count "
                        "does not match its column grid"
                    )
                    continue
                for column_index, (cell, grid_width) in enumerate(
                    zip(cells, grid_widths, strict=True),
                    start=1,
                ):
                    cell_width = cell.find("w:tcPr/w:tcW", NS)
                    width_type = _attribute(cell_width, "type")
                    width_text = _attribute(cell_width, "w")
                    if (
                        width_type != "dxa"
                        or not (width_text or "").isdigit()
                        or int(width_text) != grid_width
                    ):
                        errors.append(
                            f"Option table {table_index} row {row_index} cell "
                            f"{column_index} width does not match its column grid"
                        )
    return errors


def validate_print_contract(
    job: JobConfig,
    package: DocxPackage,
    *,
    stage: str,
    source_pages: int | None,
) -> dict[str, Any]:
    """Validate deterministic workbook properties before renderer-specific QA."""
    if job.render_authority != "word":
        return {"passed": True, "errors": [], "warnings": [], "skipped": True}

    body = package.body()
    errors: list[str] = []
    warnings: list[str] = []
    source_locked = job.source_type == "pdf"
    if not source_locked:
        expected_pages: list[int] = []
    elif stage == "preview":
        expected_pages = list(job.preview_source_page_numbers)
    elif stage == "final":
        expected_pages = list(job.content_page_numbers)
    else:
        expected_pages = []
        errors.append(f"Unsupported print-contract stage: {stage}")

    breaks = body.findall(".//w:br[@w:type='page']", NS)
    bookmarks = _bookmark_numbers(body)
    if source_locked:
        if source_pages is not None and source_pages != len(expected_pages):
            errors.append(
                "Selected source-page count does not match the configured sequence: "
                f"expected {len(expected_pages)}, got {source_pages}"
            )
        if not expected_pages:
            errors.append("Print contract has no expected source-page sequence")
        if job.pagination_policy != "sample_flow":
            expected_breaks = max(0, len(expected_pages) - 1)
            if len(breaks) != expected_breaks:
                errors.append(
                    f"Explicit page-break mismatch: expected {expected_breaks}, "
                    f"got {len(breaks)}"
                )
            if bookmarks != expected_pages:
                errors.append(
                    "Source-page bookmark sequence mismatch: "
                    f"expected {expected_pages}, got {bookmarks}"
                )

    sections = body.findall(".//w:sectPr", NS)
    final_section = body.find("w:sectPr", NS)
    if final_section is None:
        errors.append("Print document has no final body section properties")
    if not sections:
        errors.append("Print document has no section properties")
    for section_index, section in enumerate(sections, start=1):
        page_size = section.find("w:pgSz", NS)
        width = _attribute(page_size, "w")
        height = _attribute(page_size, "h")
        if not (width or "").isdigit() or not (height or "").isdigit():
            errors.append(
                f"Print document section {section_index} has no numeric page size"
            )
        else:
            width_mm = int(width) * MM_PER_TWIP
            height_mm = int(height) * MM_PER_TWIP
            if abs(width_mm - A4_WIDTH_MM) > 0.5 or abs(height_mm - A4_HEIGHT_MM) > 0.5:
                errors.append(
                    f"Print document section {section_index} is not A4 within 0.5 mm: "
                    f"{width_mm:.2f} x {height_mm:.2f} mm"
                )

    full_text = "".join(body.xpath(".//w:t/text()", namespaces=NS))
    for character, label in FORBIDDEN_TEXT.items():
        if character in full_text:
            errors.append(f"Document text contains forbidden {label}")

    settings = package.optional_xml("word/settings.xml")
    if settings is None:
        errors.append("Print document has no Word settings part")
    else:
        update_fields = settings.find(".//w:updateFields", NS)
        if update_fields is not None and _on_off(update_fields, default=True):
            errors.append("Automatic field updating is enabled")
        compression = settings.find(".//w:doNotAutoCompressPictures", NS)
        if not _on_off(compression, default=False):
            errors.append(
                "Word automatic picture compression is not explicitly disabled"
            )

    answer_line_tabs = body.xpath(
        ".//w:p[w:pPr/w:pBdr/w:bottom[@w:val='dotted']]"
        "/w:pPr/w:tabs/w:tab[@w:leader]",
        namespaces=NS,
    )
    if answer_line_tabs:
        errors.append("Dotted answer lines also use tab leaders")

    errors.extend(_option_table_errors(body))
    return {
        "passed": not errors,
        "stage": stage,
        "expected_source_pages": expected_pages,
        "bookmark_source_pages": bookmarks,
        "explicit_page_breaks": len(breaks),
        "errors": errors,
        "warnings": warnings,
        "skipped": False,
    }


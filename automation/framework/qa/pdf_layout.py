from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pdfplumber

from ..core.models import FrameworkError, IntegrityError, JobConfig, sha256_file
from ..ingest.pdf import effective_manifest_path


POINTS_PER_MM = 72.0 / 25.4
A4_WIDTH_POINTS = 210.0 * POINTS_PER_MM
A4_HEIGHT_POINTS = 297.0 * POINTS_PER_MM
SAFE_TOP_MM = 28.0
SAFE_BOTTOM_MM = 267.0
FOOTER_TOP_MM = 276.0
RECTO_INSIDE_MM = 22.0
RECTO_OUTSIDE_MM = 18.0
FRAME_TOLERANCE_MM = 1.5
VISUAL_CENTER_INSET_MM = 4.0
ANSWER_LINE_MIN_TOP_MM = 55.0
ANSWER_LINE_MIN_WIDTH_MM = 150.0
ANSWER_LINE_TARGET_BOTTOM_MM = 260.0
FAIL_UTILIZATION_PERCENT = 60.0
WARN_UTILIZATION_PERCENT = 75.0
MCQ_TARGET_UTILIZATION_PERCENT = 82.0
MCQ_DENSE_UTILIZATION_PERCENT = 95.0
SOURCE_UTILIZATION_TOLERANCE_PERCENT = 8.0
SOURCE_UTILIZATION_WARNING_PERCENT = 4.0

# Source-locked pages may contract by at most eight percentage points. This
# absorbs renderer/font rounding without accepting materially compressed pages.


def _load_manifest_pages(path: Path) -> dict[int, dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    pages = value.get("pages", [])
    if not isinstance(pages, list):
        return {}
    result: dict[int, dict[str, Any]] = {}
    for page in pages:
        if isinstance(page, dict) and isinstance(page.get("source_page"), int):
            result[int(page["source_page"])] = page
    return result


def _manifest_page_metadata(job: JobConfig) -> dict[int, dict[str, Any]]:
    manifest_path = job.content_manifest
    if job.source_type == "pdf":
        report_path = job.qa_dir / "ingest.json"
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise IntegrityError(
                    f"PDF ingest provenance is invalid: {exc}"
                ) from exc
            binding = report.get("effective_manifest")
            if binding is not None:
                if not isinstance(binding, dict):
                    raise IntegrityError(
                        "PDF ingest effective-manifest binding is invalid"
                    )
                expected_path = effective_manifest_path(job).resolve()
                reported_path = binding.get("path")
                expected_hash = binding.get("sha256")
                if (
                    not isinstance(reported_path, str)
                    or Path(reported_path).resolve() != expected_path
                ):
                    raise IntegrityError(
                        "PDF ingest names an unexpected effective manifest"
                    )
                if (
                    not isinstance(expected_hash, str)
                    or not expected_path.is_file()
                    or sha256_file(expected_path) != expected_hash
                ):
                    raise IntegrityError(
                        "Effective manifest changed after PDF ingest"
                    )
                manifest_path = expected_path
    if manifest_path is None or not manifest_path.is_file():
        return {}
    return _load_manifest_pages(manifest_path)


def _object_box(
    value: dict[str, Any],
    *,
    page_height: float,
) -> tuple[float, float, float, float] | None:
    try:
        x0 = float(value["x0"])
        x1 = float(value["x1"])
        if "top" in value and "bottom" in value:
            top = float(value["top"])
            bottom = float(value["bottom"])
        else:
            top = page_height - float(value["y1"])
            bottom = page_height - float(value["y0"])
    except (KeyError, TypeError, ValueError):
        return None
    return min(x0, x1), max(x0, x1), min(top, bottom), max(top, bottom)


def _content_visual_boxes(
    page: Any,
    *,
    left: float,
    right: float,
    safe_top: float,
    footer_top: float,
) -> list[tuple[float, float, float, float]]:
    boxes: list[tuple[float, float, float, float]] = []
    page_width = float(page.width)
    page_height = float(page.height)
    for attribute in ("images", "rects", "curves", "lines"):
        for value in getattr(page, attribute, ()) or ():
            if not isinstance(value, dict):
                continue
            box = _object_box(value, page_height=page_height)
            if box is None:
                continue
            x0, x1, top, bottom = box
            width = x1 - x0
            height = bottom - top
            center_x = (x0 + x1) / 2.0
            if width >= page_width * 0.9 or height >= page_height * 0.9:
                continue
            if (
                left + VISUAL_CENTER_INSET_MM * POINTS_PER_MM
                <= center_x <= right - VISUAL_CENTER_INSET_MM * POINTS_PER_MM
                and bottom >= safe_top - 2.0 * POINTS_PER_MM
                and top <= footer_top
            ):
                boxes.append(box)
    return boxes


def _horizontal_answer_extent(page: Any, *, left: float, right: float) -> float | None:
    groups: dict[int, list[tuple[float, float, float]]] = {}
    page_height = float(page.height)
    for attribute in ("lines", "curves", "rects"):
        for value in getattr(page, attribute, ()) or ():
            if not isinstance(value, dict):
                continue
            box = _object_box(value, page_height=page_height)
            if box is None:
                continue
            x0, x1, top, bottom = box
            center_y = (top + bottom) / 2.0
            if (
                bottom - top <= 1.5 * POINTS_PER_MM
                and ANSWER_LINE_MIN_TOP_MM * POINTS_PER_MM
                <= center_y
                <= SAFE_BOTTOM_MM * POINTS_PER_MM
            ):
                key = round(center_y / 1.5)
                groups.setdefault(key, []).append((x0, x1, center_y))

    candidates: list[float] = []
    for segments in groups.values():
        x0 = min(segment[0] for segment in segments)
        x1 = max(segment[1] for segment in segments)
        center_y = max(segment[2] for segment in segments)
        if (
            x1 - x0 >= ANSWER_LINE_MIN_WIDTH_MM * POINTS_PER_MM
            and abs(x0 - left) <= 6.0 * POINTS_PER_MM
            and abs(x1 - right) <= 6.0 * POINTS_PER_MM
        ):
            candidates.append(center_y)
    return max(candidates) if candidates else None


def _content_measurement(
    page: Any,
    *,
    left: float,
    right: float,
    safe_top: float,
    safe_bottom: float,
    footer_top: float,
    restrict_to_live_frame: bool = False,
    style_policy: str = "source_authority",
) -> dict[str, Any]:
    words = page.extract_words(
        x_tolerance=1.0,
        y_tolerance=1.0,
        keep_blank_chars=False,
        use_text_flow=False,
    ) or []
    content_words = [
        word
        for word in words
        if float(word["bottom"]) < footer_top
        and not (
            float(word["top"]) > 270.0 * POINTS_PER_MM
            and str(word["text"]).strip().isdigit()
        )
        and (
            not restrict_to_live_frame
            or (
                float(word["x1"]) > left
                and float(word["x0"]) < right
            )
        )
    ]
    visual_boxes = _content_visual_boxes(
        page,
        left=left,
        right=right,
        safe_top=safe_top,
        footer_top=footer_top,
    )
    tops = [float(word["top"]) for word in content_words]
    tops.extend(box[2] for box in visual_boxes)
    bottoms = [float(word["bottom"]) for word in content_words]
    bottoms.extend(box[3] for box in visual_boxes)
    min_top = min(tops) if tops else None
    max_bottom = max(bottoms) if bottoms else None
    left_ans = left + 27.0 if style_policy == "content_only" else left
    answer_extent = _horizontal_answer_extent(page, left=left_ans, right=right)
    if answer_extent is not None:
        max_bottom = max(max_bottom or answer_extent, answer_extent)
    utilization = (
        100.0
        * max(0.0, min(safe_bottom, max_bottom) - safe_top)
        / (safe_bottom - safe_top)
        if max_bottom is not None
        else 0.0
    )
    return {
        "words": content_words,
        "visual_boxes": visual_boxes,
        "content_top_points": min_top,
        "content_bottom_points": max_bottom,
        "answer_extent_points": answer_extent,
        "utilization_percent": utilization,
    }


def _source_page_measurements(
    job: JobConfig,
    source_page_numbers: tuple[int, ...],
) -> dict[int, dict[str, Any]]:
    if job.source_type != "pdf" or not source_page_numbers:
        return {}
    result: dict[int, dict[str, Any]] = {}
    with pdfplumber.open(job.source) as source_pdf:
        for source_page in source_page_numbers:
            if source_page < 1 or source_page > len(source_pdf.pages):
                raise FrameworkError(
                    f"Source PDF page is out of range: {source_page}"
                )
            page = source_pdf.pages[source_page - 1]
            width = float(page.width)
            left = RECTO_OUTSIDE_MM * POINTS_PER_MM
            right = width - RECTO_OUTSIDE_MM * POINTS_PER_MM
            measured = _content_measurement(
                page,
                left=left,
                right=right,
                safe_top=SAFE_TOP_MM * POINTS_PER_MM,
                safe_bottom=SAFE_BOTTOM_MM * POINTS_PER_MM,
                footer_top=FOOTER_TOP_MM * POINTS_PER_MM,
                restrict_to_live_frame=True,
            )
            result[source_page] = {
                "content_top_points": measured["content_top_points"],
                "content_bottom_points": measured["content_bottom_points"],
                "utilization_percent": measured["utilization_percent"],
            }
    return result


def _answer_space_rules(
    page_meta: dict[str, Any],
    source_measurement: dict[str, Any],
) -> tuple[bool, bool, float | None]:
    raw_blocks = page_meta.get("blocks", [])
    blocks = raw_blocks if isinstance(raw_blocks, list) else []
    has_answer_canvas = any(
        isinstance(block, dict) and block.get("kind") == "answer_canvas"
        for block in blocks
    )
    answer_blocks = [
        block
        for block in blocks
        if isinstance(block, dict) and block.get("kind") == "answer_lines"
    ]
    targets: list[float] = []
    for block in answer_blocks:
        bbox = block.get("source_bbox_points")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            top = float(bbox[1])
            bottom = float(bbox[3])
        except (TypeError, ValueError):
            continue
        if bottom > top:
            targets.append(bottom)
    target: float | None = None
    if answer_blocks:
        page_type = page_meta.get("page_type", "other")
        if page_type in {"short_answer", "long_answer"}:
            target = (267.0 * POINTS_PER_MM) - 27.0
        else:
            if targets:
                target = min(
                    max(targets),
                    ANSWER_LINE_TARGET_BOTTOM_MM * POINTS_PER_MM,
                )
            elif source_measurement.get("content_bottom_points") is not None:
                target = min(
                    float(source_measurement["content_bottom_points"]),
                    ANSWER_LINE_TARGET_BOTTOM_MM * POINTS_PER_MM,
                )
    return has_answer_canvas, bool(answer_blocks), target


def analyze_word_pdf(
    job: JobConfig,
    pdf_path: str | Path,
    *,
    stage: str,
    source_page_numbers: tuple[int, ...],
    bookmark_pages: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Measure the Word-exported PDF against the source-locked print contract."""

    source = Path(pdf_path).resolve()
    if not source.is_file():
        raise FrameworkError(f"Word render PDF is missing: {source}")
    expected_count = job.expected_pages_for_stage(stage)
    metadata = _manifest_page_metadata(job)
    source_locked = job.source_type == "pdf"
    source_measurements = _source_page_measurements(job, source_page_numbers)
    errors: list[str] = []
    warnings: list[str] = []
    page_results: list[dict[str, Any]] = []

    with pdfplumber.open(source) as pdf:
        if job.pagination_policy != "sample_flow":
            if expected_count is not None and len(pdf.pages) != expected_count:
                errors.append(
                    "Rendered page-count mismatch: "
                    f"expected {expected_count}, got {len(pdf.pages)}"
                )
            if source_page_numbers and len(source_page_numbers) != len(pdf.pages):
                errors.append(
                    "Source-page mapping length does not match rendered page count"
                )

        for physical_index, page in enumerate(pdf.pages, start=1):
            if job.pagination_policy == "sample_flow" and bookmark_pages:
                active_bookmark = None
                for name, page_num in bookmark_pages.items():
                    if name.startswith("SourcePdfPage"):
                        try:
                            bm_page = int(page_num)
                        except (TypeError, ValueError):
                            continue
                        if bm_page <= physical_index:
                            if active_bookmark is None or bm_page > int(bookmark_pages[active_bookmark]):
                                active_bookmark = name
                if active_bookmark:
                    source_page = int(active_bookmark[13:])
                else:
                    source_page = None
            else:
                source_page = (
                    source_page_numbers[physical_index - 1]
                    if physical_index <= len(source_page_numbers)
                    else None
                )
            page_errors: list[str] = []
            page_warnings: list[str] = []
            width = float(page.width)
            height = float(page.height)
            if abs(width - A4_WIDTH_POINTS) > 0.5 * POINTS_PER_MM or abs(
                height - A4_HEIGHT_POINTS
            ) > 0.5 * POINTS_PER_MM:
                page_errors.append(
                    f"not A4: {width / POINTS_PER_MM:.2f} x "
                    f"{height / POINTS_PER_MM:.2f} mm"
                )

            first_recto = job.first_content_side == "recto"
            recto = physical_index % 2 == (1 if first_recto else 0)
            left_mm, right_margin_mm = (
                (RECTO_INSIDE_MM, RECTO_OUTSIDE_MM)
                if recto
                else (RECTO_OUTSIDE_MM, RECTO_INSIDE_MM)
            )
            left = left_mm * POINTS_PER_MM
            right = width - right_margin_mm * POINTS_PER_MM
            safe_top = SAFE_TOP_MM * POINTS_PER_MM
            safe_bottom = SAFE_BOTTOM_MM * POINTS_PER_MM
            footer_top = FOOTER_TOP_MM * POINTS_PER_MM
            page_meta = metadata.get(source_page or -1, {})
            page_type = str(page_meta.get("page_type", "other"))

            measured = _content_measurement(
                page,
                left=left,
                right=right,
                safe_top=safe_top,
                safe_bottom=safe_bottom,
                footer_top=footer_top,
                style_policy=job.source_style_policy,
            )
            content_words = measured["words"]
            visual_boxes = measured["visual_boxes"]
            min_top = measured["content_top_points"]
            max_bottom = measured["content_bottom_points"]
            answer_extent = measured["answer_extent_points"]
            utilization = float(measured["utilization_percent"])
            if min_top is None or max_bottom is None:
                page_errors.append("unexpected blank page")
            else:
                if min_top < safe_top - 2.0 * POINTS_PER_MM:
                    page_errors.append(
                        f"content starts too high at {min_top / POINTS_PER_MM:.1f} mm"
                    )
                if max_bottom > safe_bottom + 1.0 * POINTS_PER_MM:
                    page_errors.append(
                        f"content crosses footer clearance at "
                        f"{max_bottom / POINTS_PER_MM:.1f} mm"
                    )
                outside_words = [
                    word
                    for word in content_words
                    if float(word["x0"])
                    < left - FRAME_TOLERANCE_MM * POINTS_PER_MM
                    or float(word["x1"])
                    > right + FRAME_TOLERANCE_MM * POINTS_PER_MM
                ]
                if outside_words:
                    page_errors.append(
                        f"{len(outside_words)} text fragment(s) outside the "
                        "live content frame"
                    )
                outside_visuals = [
                    box
                    for box in visual_boxes
                    if box[0] < left - FRAME_TOLERANCE_MM * POINTS_PER_MM
                    or box[1] > right + FRAME_TOLERANCE_MM * POINTS_PER_MM
                ]
                if outside_visuals:
                    page_errors.append(
                        f"{len(outside_visuals)} visual object(s) outside the "
                        "live content frame"
                    )

            source_measurement = source_measurements.get(source_page or -1, {})
            source_bottom = source_measurement.get("content_bottom_points")
            source_utilization_value = source_measurement.get(
                "utilization_percent"
            )
            source_utilization = (
                float(source_utilization_value)
                if source_utilization_value is not None
                else None
            )
            utilization_delta = (
                utilization - source_utilization
                if source_utilization is not None
                else None
            )
            exempt = bool(page_meta.get("utilization_exempt", False)) or page_type in {
                "chapter_end",
                "intentional_whitespace",
            }
            if source_locked and not exempt and job.pagination_policy != "sample_flow":
                if utilization_delta is not None:
                    if utilization_delta < -SOURCE_UTILIZATION_TOLERANCE_PERCENT:
                        page_errors.append(
                            "vertical utilization is compressed by "
                            f"{abs(utilization_delta):.1f} percentage points "
                            "relative to the source"
                        )
                    elif utilization_delta < -SOURCE_UTILIZATION_WARNING_PERCENT:
                        page_warnings.append(
                            "vertical utilization is "
                            f"{abs(utilization_delta):.1f} percentage points "
                            "below the source"
                        )
                    if (
                        page_type == "mcq"
                        and source_utilization >= MCQ_TARGET_UTILIZATION_PERCENT
                        and utilization < MCQ_TARGET_UTILIZATION_PERCENT
                    ):
                        page_warnings.append(
                            "MCQ utilization is below the source-supported "
                            f"{MCQ_TARGET_UTILIZATION_PERCENT:.0f}% target at "
                            f"{utilization:.1f}%"
                        )
                    if (
                        page_type == "mcq"
                        and utilization > MCQ_DENSE_UTILIZATION_PERCENT
                        and utilization_delta
                        > SOURCE_UTILIZATION_TOLERANCE_PERCENT
                    ):
                        page_warnings.append(
                            f"MCQ utilization is dense at {utilization:.1f}%"
                        )
                elif utilization < FAIL_UTILIZATION_PERCENT:
                    page_errors.append(
                        f"vertical utilization is only {utilization:.1f}%"
                    )
                elif utilization < WARN_UTILIZATION_PERCENT:
                    page_warnings.append(
                        f"vertical utilization is low at {utilization:.1f}%"
                    )

            has_answer_canvas, requires_answer_lines, answer_target = (
                _answer_space_rules(page_meta, source_measurement)
            )
            if source_locked and job.pagination_policy != "sample_flow" and requires_answer_lines and answer_extent is None:
                page_errors.append("no full-width answer line was detected")
            elif (
                source_locked
                and job.pagination_policy != "sample_flow"
                and requires_answer_lines
                and answer_extent is not None
                and answer_target is not None
                and answer_extent < answer_target
            ):
                page_errors.append(
                    f"final answer line ends at {answer_extent / POINTS_PER_MM:.1f} mm; "
                    f"source target is {answer_target / POINTS_PER_MM:.1f} mm"
                )

            if page_errors:
                errors.extend(
                    f"physical page {physical_index}"
                    + (f" / source {source_page}" if source_page is not None else "")
                    + f": {message}"
                    for message in page_errors
                )
            if page_warnings:
                warnings.extend(
                    f"physical page {physical_index}"
                    + (f" / source {source_page}" if source_page is not None else "")
                    + f": {message}"
                    for message in page_warnings
                )
            page_results.append(
                {
                    "physical_page": physical_index,
                    "source_page": source_page,
                    "page_type": page_type,
                    "recto": recto,
                    "width_mm": round(width / POINTS_PER_MM, 2),
                    "height_mm": round(height / POINTS_PER_MM, 2),
                    "content_top_mm": (
                        round(min_top / POINTS_PER_MM, 2)
                        if min_top is not None
                        else None
                    ),
                    "content_bottom_mm": (
                        round(max_bottom / POINTS_PER_MM, 2)
                        if max_bottom is not None
                        else None
                    ),
                    "utilization_percent": round(utilization, 1),
                    "source_content_bottom_mm": (
                        round(float(source_bottom) / POINTS_PER_MM, 2)
                        if source_bottom is not None
                        else None
                    ),
                    "source_utilization_percent": (
                        round(source_utilization, 1)
                        if source_utilization is not None
                        else None
                    ),
                    "utilization_delta_percent": (
                        round(utilization_delta, 1)
                        if utilization_delta is not None
                        else None
                    ),
                    "has_answer_canvas": has_answer_canvas,
                    "requires_answer_lines": requires_answer_lines,
                    "source_answer_target_bottom_mm": (
                        round(answer_target / POINTS_PER_MM, 2)
                        if answer_target is not None
                        else None
                    ),
                    "errors": page_errors,
                    "warnings": page_warnings,
                }
            )

    return {
        "passed": not errors,
        "stage": stage,
        "pdf": str(source),
        "source_pdf": str(job.source) if source_locked else None,
        "source_utilization_tolerance_percent": (
            SOURCE_UTILIZATION_TOLERANCE_PERCENT if source_locked else None
        ),
        "page_count": len(page_results),
        "errors": errors,
        "warnings": warnings,
        "pages": page_results,
    }

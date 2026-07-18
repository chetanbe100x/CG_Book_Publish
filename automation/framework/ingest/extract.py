from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader

from ..core.models import (
    FrameworkError,
    IntegrityError,
    JobConfig,
    atomic_json_write,
    sha256_file,
    utc_now,
)
from .structured import UnicodeSanitizationError, parse_structured_page

ANSWER_LINE_PITCH_POINTS = 28.5
_ANSWER_LINE_PITCH_TOLERANCE_POINTS = 2.25
_ANSWER_RECT_X_TARGETS = (51.0, 62.0)
_ANSWER_RECT_X_TOLERANCE_POINTS = 3.0
_ANSWER_RECT_MIN_WIDTH_POINTS = 450.0
_ANSWER_RECT_MIN_HEIGHT_POINTS = 60.0
_PDF_QUESTION_ANCHOR_RE = re.compile(r"^Q\s*(?P<number>\d+)\.?$", re.IGNORECASE)
_QUESTION_LABEL_RE = re.compile(r"^Q\s*(?P<number>\d+)\.?$", re.IGNORECASE)

_MATH_ONLY_RE = re.compile(r"^[0-9A-Za-z(){}+\-\u2212=./,\s]+$")
_QUESTION_TYPE_KEYWORDS = {
    "mcq": ("multiple choice", "\u092c\u0939\u0941\u0935\u093f\u0915\u0932\u094d\u092a\u0940\u092f"),
    "fill_blank": ("fill in the blank", "\u0930\u093f\u0915\u094d\u0924 \u0938\u094d\u0925\u093e\u0928"),
    "short_answer": ("short answer", "\u0932\u0918\u0941 \u0909\u0924\u094d\u0924\u0930\u0940\u092f"),
    "long_answer": ("long answer", "\u0926\u0940\u0930\u094d\u0918 \u0909\u0924\u094d\u0924\u0930\u0940\u092f"),
}
_TYPED_CONTENT_KINDS = {
    "answer_canvas",
    "answer_lines",
    "figure",
    "formula_image",
    "options",
    "paragraph",
    "question",
}


def _formula_layout_reasons(page_text: str) -> list[str]:
    reasons: list[str] = []
    if _COMPLEX_MATH_RE.search(page_text):
        reasons.append("root, integral, summation, limit, or determinant notation")
    for raw_line in page_text.splitlines():
        line = raw_line.strip().replace("\u200b", "")
        if not 2 <= len(line) <= 24 or not _MATH_ONLY_RE.fullmatch(line):
            continue
        if any(character.isdigit() for character in line) and any(
            token in line for token in ("+", "-", "\u2212", "=", "/", "x", "y")
        ):
            reasons.append("a short split formula line that may be a stacked fraction")
            break
    return reasons


def formula_image_block(
    *,
    path: str,
    crop_bbox_points: list[float],
    alt_text: str,
    source_id: str,
    for_question: str | None = None,
    effective_dpi: float = 300,
) -> dict[str, Any]:
    """Create a formula-image block only from complete, reviewable geometry."""

    if not path.strip() or not alt_text.strip() or not source_id.strip():
        raise ValueError("Formula image path, alt text, and source ID are required")
    if len(crop_bbox_points) != 4:
        raise ValueError("Formula image crop must contain four coordinates")
    left, top, right, bottom = (float(value) for value in crop_bbox_points)
    if left < 0 or top < 0 or right <= left or bottom <= top:
        raise ValueError("Formula image crop must describe a positive rectangle")
    if effective_dpi <= 0:
        raise ValueError("Formula image effective DPI must be positive")
    block: dict[str, Any] = {
        "kind": "formula_image",
        "path": path,
        "crop_bbox_points": [left, top, right, bottom],
        "alt_text": alt_text,
        "effective_dpi": float(effective_dpi),
        "source_ids": [source_id],
        "confidence": "medium",
    }
    if for_question:
        block["for_question"] = for_question
    return block


def _source_is_intentionally_sparse(page_text: str) -> bool:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    character_count = sum(len(line) for line in lines)
    return bool(lines) and len(lines) <= 6 and character_count <= 240


def _question_type_from_heading(text: str) -> str | None:
    folded = text.casefold()
    for page_type, keywords in _QUESTION_TYPE_KEYWORDS.items():
        if any(keyword.casefold() in folded for keyword in keywords):
            return page_type
    return None


def propagate_continuation_page_types(pages: list[dict[str, Any]]) -> None:
    """Carry the last explicit question type across consecutive source pages.

    Content before a new question-type heading keeps the inherited type, while
    content after it receives the new type. A page containing both is therefore
    classified as ``mixed``. Gaps and unit/chapter boundaries reset inheritance.
    """

    active_type: str | None = None
    previous_source_page: int | None = None
    for page in pages:
        source_page = int(page["source_page"])
        if (
            previous_source_page is not None
            and source_page != previous_source_page + 1
        ):
            active_type = None
        current_type = active_type
        content_types: list[str] = []
        heading_types: list[str] = []
        for block in page.get("blocks", []):
            if not isinstance(block, dict):
                continue
            if block.get("kind") == "heading":
                role = block.get("role")
                if role in {"unit_heading", "chapter_heading"}:
                    current_type = None
                elif role == "question_type_heading":
                    detected = _question_type_from_heading(
                        str(block.get("text", ""))
                    )
                    if detected is not None:
                        current_type = detected
                        heading_types.append(detected)
                continue
            kind = block.get("kind")
            if kind not in _TYPED_CONTENT_KINDS:
                continue
            inferred = current_type
            if inferred is None and kind == "options":
                inferred = "mcq"
            if inferred is not None:
                content_types.append(inferred)

        observed = set(content_types)
        if len(observed) > 1:
            page["page_type"] = "mixed"
        elif observed:
            page["page_type"] = next(iter(observed))
        elif len(set(heading_types)) > 1:
            page["page_type"] = "mixed"
        elif heading_types:
            page["page_type"] = heading_types[-1]

        active_type = current_type
        previous_source_page = source_page


_COMPLEX_MATH_RE = re.compile(r"[\u221a\u2211\u222b]|\b(?:lim|det)\b", re.IGNORECASE)


def _pdftotext_candidates() -> Iterable[Path]:
    configured = os.environ.get("BOOK_PDFTOTEXT")
    if configured:
        yield Path(configured)
    located = shutil.which("pdftotext")
    if located:
        yield Path(located)
    runtime_root = Path(sys.executable).resolve().parent.parent
    yield runtime_root / "native" / "poppler" / "Library" / "bin" / "pdftotext.exe"
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        yield Path(program_files) / "Git" / "mingw64" / "bin" / "pdftotext.exe"


def _find_pdftotext() -> Path | None:
    seen: set[Path] = set()
    for candidate in _pdftotext_candidates():
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


def _extract_with_pdftotext(source: Path, executable: Path) -> list[str]:
    completed = subprocess.run(
        [
            str(executable),
            "-layout",
            "-enc",
            "UTF-8",
            str(source),
            "-",
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise FrameworkError(f"pdftotext failed for {source}: {detail}")
    try:
        value = completed.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise FrameworkError("pdftotext did not produce valid UTF-8") from exc
    pages = value.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _extract_with_pypdf(reader: PdfReader) -> list[str]:
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text(extraction_mode="layout") or "")
    return pages


def extract_pdf_pages(source: Path) -> tuple[list[str], str, int]:
    """Extract page-oriented Unicode text and report the backend used."""

    try:
        reader = PdfReader(source)
    except Exception as exc:
        raise FrameworkError(f"Invalid PDF source: {source}: {exc}") from exc
    if reader.is_encrypted:
        raise FrameworkError(f"Encrypted PDF sources are not supported: {source}")
    page_count = len(reader.pages)
    executable = _find_pdftotext()
    if executable is not None:
        pages = _extract_with_pdftotext(source, executable)
        backend = str(executable)
    else:
        pages = _extract_with_pypdf(reader)
        backend = "pypdf-layout"
    if len(pages) != page_count:
        raise FrameworkError(
            "PDF text extraction page count mismatch: "
            f"expected {page_count}, got {len(pages)}"
        )
    return pages, backend, page_count


def _configured_content_pages(job: JobConfig, page_count: int) -> tuple[int, ...]:
    configured = tuple(int(value) for value in getattr(job, "content_page_numbers", ()))
    if not configured:
        ranges = getattr(job, "content_page_ranges", ())
        expanded: list[int] = []
        for value in ranges:
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise FrameworkError("content_page_ranges entries must be [start, end]")
            start, end = (int(item) for item in value)
            if end < start:
                raise FrameworkError("content_page_ranges end must not precede start")
            expanded.extend(range(start, end + 1))
        configured = tuple(expanded)
    if not configured:
        configured = tuple(range(1, page_count + 1))
    if tuple(sorted(set(configured))) != configured:
        raise FrameworkError("Content source pages must be unique and increasing")
    if any(page < 1 or page > page_count for page in configured):
        raise FrameworkError("A configured content source page is outside the PDF")
    return configured


def draft_manifest_path(job: JobConfig) -> Path:
    if job.content_manifest is None:
        raise FrameworkError("PDF extraction requires content_manifest")
    reviewed = job.content_manifest
    return reviewed.with_name(f"{reviewed.stem}.draft{reviewed.suffix}")


def draft_review_path(job: JobConfig) -> Path:
    return job.manifest_path.parent / "Review" / "review_queue.draft.json"


def _assert_draft_destinations(
    job: JobConfig,
    output_path: Path,
    review_path: Path,
) -> None:
    assert job.content_manifest is not None
    protected: dict[Path, str] = {
        job.source.resolve(): "source",
        job.content_manifest.resolve(): "reviewed Book IR manifest",
        (job.manifest_path.parent / "Review" / "review_queue.json").resolve():
            "reviewed review queue",
    }
    template = getattr(job, "template", None)
    if template is not None:
        protected[Path(template).resolve()] = "template"
    layout_reference = getattr(job, "layout_reference", None)
    if layout_reference is not None:
        protected[Path(layout_reference).resolve()] = "layout reference"
    candidates = (
        ("Draft manifest", output_path.resolve()),
        ("Draft review queue", review_path.resolve()),
    )
    for candidate_label, candidate in candidates:
        protected_label = protected.get(candidate)
        if protected_label:
            raise IntegrityError(
                f"{candidate_label} collides with protected {protected_label}: {candidate}"
            )
    if candidates[0][1] == candidates[1][1]:
        raise IntegrityError("Draft manifest and review queue paths must differ")


def detect_answer_line_rectangles(page: Any) -> list[dict[str, Any]]:
    """Return source rectangles that encode large patterned answer-line areas."""

    detected: list[dict[str, Any]] = []
    for rectangle in page.rects:
        colors = (
            rectangle.get("stroking_color"),
            rectangle.get("non_stroking_color"),
        )
        pattern_colors = [
            value
            for value in colors
            if isinstance(value, str) and value.startswith("P")
        ]
        if not pattern_colors:
            continue
        x0 = float(rectangle.get("x0", 0))
        top = float(rectangle.get("top", 0))
        width = float(rectangle.get("width", 0))
        height = float(rectangle.get("height", 0))
        if min(abs(x0 - target) for target in _ANSWER_RECT_X_TARGETS) > (
            _ANSWER_RECT_X_TOLERANCE_POINTS
        ):
            continue
        if width <= _ANSWER_RECT_MIN_WIDTH_POINTS:
            continue
        if height <= _ANSWER_RECT_MIN_HEIGHT_POINTS:
            continue
        x1 = float(rectangle.get("x1", x0 + width))
        bottom = float(rectangle.get("bottom", top + height))
        detected.append(
            {
                "x0": x0,
                "top": top,
                "x1": x1,
                "bottom": bottom,
                "width": width,
                "height": height,
                "pattern_color": pattern_colors[0],
            }
        )
    return sorted(detected, key=lambda value: (value["top"], value["x0"]))


def infer_answer_line_count(height_points: float) -> tuple[int | None, float]:
    """Infer answer-line count from the source pitch, returning residual error."""

    height = float(height_points)
    count = round(height / ANSWER_LINE_PITCH_POINTS)
    residual = abs(height - count * ANSWER_LINE_PITCH_POINTS)
    if count < 1 or residual > _ANSWER_LINE_PITCH_TOLERANCE_POINTS:
        return None, residual
    return count, residual


def extract_question_anchors(page: Any) -> list[dict[str, Any]]:
    """Read printed question anchors with source-page vertical coordinates."""

    anchors: list[dict[str, Any]] = []
    for word in page.extract_words(use_text_flow=True, keep_blank_chars=False):
        text = str(word.get("text", "")).strip()
        match = _PDF_QUESTION_ANCHOR_RE.fullmatch(text)
        if match is None:
            continue
        anchors.append(
            {
                "number": int(match.group("number")),
                "text": text,
                "top": float(word["top"]),
            }
        )
    return sorted(anchors, key=lambda value: value["top"])


def _answer_line_review(
    *,
    source_id: str,
    page_number: int,
    ordinal: int,
    rectangle: dict[str, Any],
    description: str,
) -> dict[str, Any]:
    return {
        "review_id": f"review-p{page_number:03d}-answer-lines-{ordinal:03d}",
        "type": "answer_line_geometry",
        "source_ids": [source_id],
        "source_bbox_points": [
            rectangle["x0"],
            rectangle["top"],
            rectangle["x1"],
            rectangle["bottom"],
        ],
        "description": description,
        "blocking": True,
    }


def attach_answer_line_geometry(
    blocks: list[dict[str, Any]],
    *,
    question_anchors: list[dict[str, Any]],
    rectangles: list[dict[str, Any]],
    source_id: str,
    page_number: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach patterned answer rectangles to verified preceding questions.

    Mapping is deliberately fail-closed: parsed questions and source anchors must
    agree exactly in vertical order, counts must fit the source pitch, and a
    question may own only one patterned rectangle.
    """

    if not rectangles:
        return list(blocks), []
    parsed_questions = [
        block for block in blocks if block.get("kind") == "question"
    ]
    parsed_numbers: list[int] = []
    parsed_labels_valid = True
    for block in parsed_questions:
        match = _QUESTION_LABEL_RE.fullmatch(str(block.get("label", "")).strip())
        if match is None:
            parsed_labels_valid = False
            break
        parsed_numbers.append(int(match.group("number")))
    anchor_numbers = [int(anchor["number"]) for anchor in question_anchors]
    mapping_valid = (
        parsed_labels_valid
        and len(parsed_questions) == len(question_anchors)
        and parsed_numbers == anchor_numbers
    )
    if not mapping_valid:
        description = (
            "Answer-line rectangle could not be mapped safely because parsed "
            f"question labels {parsed_numbers} do not match source anchors "
            f"{anchor_numbers} in vertical order."
        )
        return (
            list(blocks),
            [
                _answer_line_review(
                    source_id=source_id,
                    page_number=page_number,
                    ordinal=ordinal,
                    rectangle=rectangle,
                    description=description,
                )
                for ordinal, rectangle in enumerate(rectangles, start=1)
            ],
        )

    candidates: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for ordinal, rectangle in enumerate(rectangles, start=1):
        count, residual = infer_answer_line_count(rectangle["height"])
        if count is None:
            reviews.append(
                _answer_line_review(
                    source_id=source_id,
                    page_number=page_number,
                    ordinal=ordinal,
                    rectangle=rectangle,
                    description=(
                        "Answer-line count is ambiguous: rectangle height "
                        f"{rectangle['height']:.2f} pt does not fit the "
                        f"{ANSWER_LINE_PITCH_POINTS:.1f} pt source pitch "
                        f"(residual {residual:.2f} pt)."
                    ),
                )
            )
            continue
        preceding = [
            index
            for index, anchor in enumerate(question_anchors)
            if float(anchor["top"]) < float(rectangle["top"])
        ]
        if not preceding:
            reviews.append(
                _answer_line_review(
                    source_id=source_id,
                    page_number=page_number,
                    ordinal=ordinal,
                    rectangle=rectangle,
                    description=(
                        "Answer-line rectangle has no preceding source question "
                        "anchor and cannot be attached safely."
                    ),
                )
            )
            continue
        question_index = preceding[-1]
        candidates.append(
            {
                "ordinal": ordinal,
                "rectangle": rectangle,
                "count": count,
                "residual": residual,
                "question": parsed_questions[question_index],
            }
        )

    candidates_by_question: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        question_id = str(candidate["question"]["question_id"])
        candidates_by_question.setdefault(question_id, []).append(candidate)
    existing_answer_refs = {
        str(block.get("for_question"))
        for block in blocks
        if block.get("kind") in {"answer_lines", "answer_canvas"}
        and block.get("for_question")
    }
    attachments: dict[str, dict[str, Any]] = {}
    for question_id, mapped in candidates_by_question.items():
        ambiguous = len(mapped) != 1 or question_id in existing_answer_refs
        if ambiguous:
            reason = (
                "Multiple patterned answer rectangles map to the same question."
                if len(mapped) != 1
                else "The question already has an extracted answer area."
            )
            for candidate in mapped:
                reviews.append(
                    _answer_line_review(
                        source_id=source_id,
                        page_number=page_number,
                        ordinal=int(candidate["ordinal"]),
                        rectangle=candidate["rectangle"],
                        description=f"{reason} Automatic attachment was withheld.",
                    )
                )
            continue
        candidate = mapped[0]
        rectangle = candidate["rectangle"]
        attachments[question_id] = {
            "kind": "answer_lines",
            "count": int(candidate["count"]),
            "spacing_points": ANSWER_LINE_PITCH_POINTS,
            "for_question": question_id,
            "source_bbox_points": [
                rectangle["x0"],
                rectangle["top"],
                rectangle["x1"],
                rectangle["bottom"],
            ],
            "source_evidence": {
                "type": "pdf_tiling_pattern_rectangle",
                "pattern_color": rectangle["pattern_color"],
                "height_points": rectangle["height"],
                "pitch_points": ANSWER_LINE_PITCH_POINTS,
                "line_count_method": "round(height/pitch)",
                "residual_points": float(candidate["residual"]),
            },
            "source_ids": [source_id],
            "confidence": "high",
        }

    attached_blocks: list[dict[str, Any]] = []
    active_question_id: str | None = None
    for block in blocks:
        if block.get("kind") == "question":
            if active_question_id in attachments:
                attached_blocks.append(attachments.pop(active_question_id))
            active_question_id = str(block["question_id"])
        attached_blocks.append(block)
    if active_question_id in attachments:
        attached_blocks.append(attachments.pop(active_question_id))
    if attachments:
        raise FrameworkError("Internal answer-line attachment ordering failure")
    reviews.sort(key=lambda item: item["review_id"])
    return attached_blocks, reviews


def extract_pdf_answer_geometry(
    source: Path,
    selected_pages: tuple[int, ...],
    page_count: int,
) -> dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Extract patterned answer rectangles and question anchors by source page."""

    geometry: dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    try:
        import pdfplumber
    except ImportError as exc:
        raise FrameworkError(
            "PDF answer-line geometry extraction requires pdfplumber"
        ) from exc
    try:
        with pdfplumber.open(source) as pdf:
            if len(pdf.pages) != page_count:
                raise FrameworkError(
                    "PDF geometry page count mismatch: "
                    f"expected {page_count}, got {len(pdf.pages)}"
                )
            for page_number in selected_pages:
                page = pdf.pages[page_number - 1]
                rectangles = detect_answer_line_rectangles(page)
                if rectangles:
                    geometry[page_number] = (
                        extract_question_anchors(page),
                        rectangles,
                    )
    except FrameworkError:
        raise
    except Exception as exc:
        raise FrameworkError(
            f"PDF answer-line geometry extraction failed for {source}: {exc}"
        ) from exc
    return geometry


def _empty_page_block(source_id: str, page_number: int) -> dict[str, Any]:
    return {
        "kind": "paragraph",
        "text": f"[No extractable text on source page {page_number}]",
        "language": "latin",
        "source_ids": [source_id],
        "confidence": "medium",
    }


def extract_book_ir_job(
    job: JobConfig,
    *,
    output_path: Path | None = None,
    review_path: Path | None = None,
) -> dict[str, Any]:
    """Generate an unreviewed Book IR draft without touching reviewed artifacts."""

    if job.source_type != "pdf":
        raise FrameworkError("The extract command is only valid for PDF jobs")
    if job.content_manifest is None:
        raise FrameworkError("PDF extraction requires content_manifest")
    output = (output_path or draft_manifest_path(job)).resolve()
    review = (review_path or draft_review_path(job)).resolve()
    _assert_draft_destinations(job, output, review)

    reviewed_hash_before = (
        sha256_file(job.content_manifest) if job.content_manifest.is_file() else None
    )
    reviewed_review = job.manifest_path.parent / "Review" / "review_queue.json"
    reviewed_review_hash_before = (
        sha256_file(reviewed_review) if reviewed_review.is_file() else None
    )

    raw_pages, backend, page_count = extract_pdf_pages(job.source)
    selected_pages = _configured_content_pages(job, page_count)
    answer_geometry = extract_pdf_answer_geometry(
        job.source,
        selected_pages,
        page_count,
    )
    pages: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    source_name = job.source.name
    for page_number in selected_pages:
        source_id = f"{source_name}:p{page_number:03d}"
        try:
            parsed = parse_structured_page(
                raw_pages[page_number - 1].splitlines(),
                source_id,
            )
        except UnicodeSanitizationError as exc:
            raise FrameworkError(
                f"Unsafe Unicode on source page {page_number}: {exc}"
            ) from exc
        blocks = parsed.blocks
        page_reviews = list(parsed.review_items)
        page_geometry = answer_geometry.get(page_number)
        if page_geometry is not None:
            blocks, geometry_reviews = attach_answer_line_geometry(
                blocks,
                question_anchors=page_geometry[0],
                rectangles=page_geometry[1],
                source_id=source_id,
                page_number=page_number,
            )
            page_reviews.extend(geometry_reviews)
        if not blocks:
            blocks = [_empty_page_block(source_id, page_number)]
            page_reviews.append(
                {
                    "review_id": f"review-p{page_number:03d}-empty-page-001",
                    "type": "empty_page",
                    "source_ids": [source_id],
                    "description": "No extractable content was found on this source page.",
                    "blocking": True,
                }
            )
        formula_reasons = _formula_layout_reasons(raw_pages[page_number - 1])
        if formula_reasons:
            page_reviews.append(
                {
                    "review_id": f"review-p{page_number:03d}-formula-layout-001",
                    "type": "formula_layout",
                    "source_ids": [source_id],
                    "description": (
                        "Complex 2-D formula layout requires a verified crop or tested "
                        "OMML conversion: " + "; ".join(formula_reasons) + "."
                    ),
                    "required_fields": ["path", "crop_bbox_points", "alt_text"],
                    "blocking": True,
                }
            )
        page_value: dict[str, Any] = {
            "source_page": page_number,
            "page_type": parsed.page_type,
            "blocks": blocks,
        }
        has_question_content = any(
            block["kind"] in {"question", "options", "answer_lines", "answer_canvas"}
            for block in blocks
        )
        if (
            not has_question_content
            and _source_is_intentionally_sparse(raw_pages[page_number - 1])
        ):
            page_value["utilization_exempt"] = True
            page_value["utilization_exempt_reason"] = "source_intentionally_sparse"
        pages.append(page_value)
        review_items.extend(page_reviews)
    propagate_continuation_page_types(pages)

    generated_at = utc_now()
    source_hash = sha256_file(job.source)
    manifest = {
        "schema_version": 1,
        "book_name": f"Class {job.school_class} {job.subject}",
        "scope": "full",
        "draft": {
            "generated_at": generated_at,
            "review_status": "unreviewed",
            "extractor": backend,
        },
        "source": {
            "path": str(job.source),
            "sha256": source_hash,
            "page_count": page_count,
        },
        "pages": pages,
    }
    atomic_json_write(output, manifest)
    draft_hash = sha256_file(output)
    queue = {
        "schema_version": 1,
        "generated_at": generated_at,
        "status": "unreviewed",
        "source": {"path": str(job.source), "sha256": source_hash},
        "draft_manifest": {"path": str(output), "sha256": draft_hash},
        "reviewed_manifest": {
            "path": str(job.content_manifest),
            "sha256": reviewed_hash_before,
        },
        "items": review_items,
    }
    atomic_json_write(review, queue)

    reviewed_hash_after = (
        sha256_file(job.content_manifest) if job.content_manifest.is_file() else None
    )
    reviewed_review_hash_after = (
        sha256_file(reviewed_review) if reviewed_review.is_file() else None
    )
    if reviewed_hash_after != reviewed_hash_before:
        raise IntegrityError("Reviewed Book IR changed during extraction")
    if reviewed_review_hash_after != reviewed_review_hash_before:
        raise IntegrityError("Reviewed review queue changed during extraction")
    return {
        "draft_manifest": str(output),
        "draft_manifest_sha256": draft_hash,
        "review_queue": str(review),
        "review_items": len(review_items),
        "selected_pages": list(selected_pages),
        "extractor": backend,
        "reviewed_manifest_unchanged": True,
    }


__all__ = [
    "ANSWER_LINE_PITCH_POINTS",
    "attach_answer_line_geometry",
    "detect_answer_line_rectangles",
    "draft_manifest_path",
    "draft_review_path",
    "extract_book_ir_job",
    "extract_pdf_answer_geometry",
    "extract_pdf_pages",
    "extract_question_anchors",
    "formula_image_block",
    "infer_answer_line_count",
    "propagate_continuation_page_types",
]

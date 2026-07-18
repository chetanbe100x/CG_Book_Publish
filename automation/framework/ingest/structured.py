from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")
_DEVANAGARI_CHAR_RE = re.compile(r"[\u0900-\u097f]+")
_QUESTION_RE = re.compile(
    r"^\s*Q(?:UESTION)?\s*\.?\s*(?P<number>\d+)\s*[.):-]?\s*(?P<body>.*)$",
    re.IGNORECASE,
)
_OPTION_ANCHOR_RE = re.compile(r"(?<!\w)\(\s*(?P<label>[A-D])\s*\)", re.IGNORECASE)
_ANSWER_LINE_RE = re.compile(r"^(?:[._\-\u2024\u2026]\s*){8,}$")
_SOURCE_PAGE_RE = re.compile(r":p(?P<page>\d{1,6})$", re.IGNORECASE)
_PRINTED_PAGE_RE = re.compile(r"^\d{1,4}$")
_UNIT_HEADING_RE = re.compile(
    r"^(?:\u0905\u0927\u094d\u092f\u093e\u092f|CHAPTER|UNIT)"
    r"\s*[-\u2014\u2013:]?\s*\d+",
    re.IGNORECASE,
)
_MARK_HEADING_CONTINUATION_RE = re.compile(
    r"^(?:\d+\s+)?MARKS?\s+QUESTION\)?$",
    re.IGNORECASE,
)
_QUESTION_TYPE_HEADING_TOKENS = (
    "multiple choice question",
    "fill in the blank",
    "short answer question",
    "long answer question",
    "\u092c\u0939\u0941\u0935\u093f\u0915\u0932\u094d\u092a\u0940\u092f "
    "\u092a\u094d\u0930\u0936\u094d\u0928",
    "\u0930\u093f\u0915\u094d\u0924 \u0938\u094d\u0925\u093e\u0928",
    "\u0932\u0918\u0941 \u0909\u0924\u094d\u0924\u0930\u0940\u092f "
    "\u092a\u094d\u0930\u0936\u094d\u0928",
    "\u0926\u0940\u0930\u094d\u0918 \u0909\u0924\u094d\u0924\u0930\u0940\u092f "
    "\u092a\u094d\u0930\u0936\u094d\u0928",
)
_MOJIBAKE_RE = re.compile(r"(?:\u00c3.|\u00e0[\u00a4\u00a5]|\u00e2[\u0080-\u00bf])")
_FORBIDDEN_UNICODE = {"\x00": "NUL", "\ufffd": "U+FFFD replacement character"}

PAGE_TYPES = {
    "mcq", "fill_blank", "short_answer", "long_answer", "mixed",
    "chapter_end", "other",
}
OPTION_LAYOUTS = {1: "one_column", 2: "two_by_two", 4: "four_inline"}


class UnicodeSanitizationError(ValueError):
    """Raised when extracted PDF text contains evidence of data loss."""


def sanitize_text(text: str) -> str:
    """Normalize extracted text and reject characters that conceal data loss.

    Layout extraction can introduce non-breaking spaces and decomposed Unicode.
    Those forms are normalized, but NUL and U+FFFD are rejected because silently
    deleting either character would make a corrupt extraction appear valid.
    """

    if not isinstance(text, str):
        raise TypeError("Extracted text must be a string")
    for character, label in _FORBIDDEN_UNICODE.items():
        if character in text:
            raise UnicodeSanitizationError(f"Extracted text contains {label}")
    if _MOJIBAKE_RE.search(text):
        raise UnicodeSanitizationError("Extracted text appears to contain mojibake")
    normalized = unicodedata.normalize("NFC", text.replace("\u00a0", " "))
    normalized = normalized.replace("\ufeff", "").replace("\u200b", "")
    return re.sub(r"[ \t]+", " ", normalized).strip()


def _language_for(text: str) -> str:
    return "hindi" if _DEVANAGARI_RE.search(text) else "latin"


def _append_run(runs: list[dict[str, str]], text: str, language: str) -> None:
    if not text:
        return
    if not text.strip() and runs:
        runs[-1]["text"] += text
        return
    if runs and runs[-1]["language"] == language:
        runs[-1]["text"] += text
    else:
        runs.append({"text": text, "language": language})


def language_runs(text: str, *, default: str | None = None) -> list[dict[str, str]]:
    """Return font-routing runs without changing the source text order."""

    value = sanitize_text(text)
    if not value:
        return []
    fallback = default or ("math" if _DEVANAGARI_RE.search(value) else "latin")
    runs: list[dict[str, str]] = []
    cursor = 0
    for match in _DEVANAGARI_CHAR_RE.finditer(value):
        if match.start() > cursor:
            _append_run(runs, value[cursor : match.start()], fallback)
        _append_run(runs, match.group(0), "hindi")
        cursor = match.end()
    if cursor < len(value):
        _append_run(runs, value[cursor:], fallback)
    return runs


def stable_question_id(source_id: str, ordinal: int) -> str:
    """Build a deterministic ID from the source page and page-local order."""

    if ordinal < 1:
        raise ValueError("Question ordinal must be positive")
    match = _SOURCE_PAGE_RE.search(source_id)
    page = int(match.group("page")) if match else 0
    return f"q-p{page:03d}-{ordinal:03d}"


def _stable_review_id(source_id: str, review_type: str, ordinal: int) -> str:
    match = _SOURCE_PAGE_RE.search(source_id)
    page = int(match.group("page")) if match else 0
    token = re.sub(r"[^a-z0-9]+", "-", review_type.casefold()).strip("-")
    return f"review-p{page:03d}-{token}-{ordinal:03d}"


def _base_block(source_id: str, confidence: str) -> dict[str, Any]:
    return {"source_ids": [source_id], "confidence": confidence}


def _paragraph_block(
    text: str,
    *,
    source_id: str,
    confidence: str,
) -> dict[str, Any]:
    language = _language_for(text)
    block: dict[str, Any] = {
        "kind": "paragraph",
        "text": text,
        "language": language,
        "runs": language_runs(
            text,
            default="math" if language == "hindi" else "latin",
        ),
        **_base_block(source_id, confidence),
    }
    if language == "hindi":
        block["role"] = "hindi"
    return block


def _is_unit_heading(text: str) -> bool:
    return _UNIT_HEADING_RE.match(text) is not None


def _is_question_type_heading(text: str) -> bool:
    folded = text.casefold()
    return any(token.casefold() in folded for token in _QUESTION_TYPE_HEADING_TOKENS)


@dataclass(frozen=True)
class _SourceLine:
    text: str
    layout_text: str
    column: int


def _has_unclosed_parenthesis(text: str) -> bool:
    return text.count("(") > text.count(")")


def _combine_source_lines(first: _SourceLine, second: _SourceLine) -> _SourceLine:
    return _SourceLine(
        text=f"{first.text} {second.text}".strip(),
        layout_text=f"{first.layout_text.rstrip()} {second.layout_text.strip()}",
        column=first.column,
    )


def _merge_wrapped_heading_continuations(
    lines: list[_SourceLine],
) -> list[_SourceLine]:
    """Merge only source wraps that are structurally identifiable as headings."""

    merged: list[_SourceLine] = []
    index = 0
    expect_chapter_title = False
    while index < len(lines):
        line = lines[index]
        if expect_chapter_title:
            if (
                _has_unclosed_parenthesis(line.text)
                and index + 1 < len(lines)
                and not _QUESTION_RE.match(lines[index + 1].text)
                and not _options_on_line(lines[index + 1].layout_text)
            ):
                line = _combine_source_lines(line, lines[index + 1])
                index += 1
            merged.append(line)
            expect_chapter_title = False
            index += 1
            continue
        if _is_unit_heading(line.text):
            merged.append(line)
            expect_chapter_title = True
            index += 1
            continue
        if _is_question_type_heading(line.text) and index + 1 < len(lines):
            continuation = lines[index + 1]
            is_split_mark_heading = (
                _has_unclosed_parenthesis(line.text)
                and _MARK_HEADING_CONTINUATION_RE.fullmatch(
                    continuation.text
                ) is not None
            )
            is_split_question_word = (
                continuation.text.casefold() == "question"
                and re.search(r"\bmarks?$", line.text, re.IGNORECASE) is not None
            )
            if is_split_mark_heading or is_split_question_word:
                line = _combine_source_lines(line, continuation)
                index += 1
        merged.append(line)
        index += 1
    return merged


def _heading_block(
    text: str,
    *,
    role: str,
    source_id: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "kind": "heading",
        "role": role,
        "level": 1 if role == "chapter_heading" else 2,
        "text": text,
        "language": _language_for(text),
        "runs": language_runs(text, default="latin"),
        **_base_block(source_id, confidence),
    }


@dataclass
class _Question:
    question_id: str
    label: str
    source_id: str
    confidence: str
    label_layout: str
    hindi_parts: list[str] = field(default_factory=list)
    english_parts: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        target = self.hindi_parts if _language_for(text) == "hindi" else self.english_parts
        target.append(text)

    def block(self) -> dict[str, Any] | None:
        hindi = " ".join(self.hindi_parts).strip()
        english = " ".join(self.english_parts).strip()
        if not (hindi or english):
            return None
        block: dict[str, Any] = {
            "kind": "question",
            "question_id": self.question_id,
            "label": self.label,
            "label_layout": self.label_layout,
            **_base_block(self.source_id, self.confidence),
        }
        if hindi:
            block["hindi"] = hindi
            block["hindi_runs"] = language_runs(hindi, default="math")
        if english:
            block["english"] = english
            block["english_runs"] = language_runs(english, default="latin")
        return block


@dataclass
class _Option:
    label: str
    source_column: int = 0
    parts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.parts).strip()


@dataclass(frozen=True)
class StructuredPageResult:
    blocks: list[dict[str, Any]]
    review_items: list[dict[str, Any]]
    page_type: str


def _options_on_line(line: str) -> list[_Option]:
    matches = list(_OPTION_ANCHOR_RE.finditer(line))
    if not matches or line[: matches[0].start()].strip():
        return []
    options: list[_Option] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        text = sanitize_text(line[match.end() : end])
        options.append(
            _Option(
                label=match.group("label").upper(),
                source_column=match.start(),
                parts=[text] if text else [],
            )
        )
    return options


def _option_columns(anchor_counts: list[int]) -> int:
    widest_row = max(anchor_counts, default=1)
    if widest_row >= 4:
        return 4
    if widest_row >= 2:
        return 2
    return 1


def _classify_page(lines: list[str], blocks: list[dict[str, Any]]) -> str:
    folded = "\n".join(lines).casefold()
    detected: set[str] = set()
    keywords = {
        "mcq": ("multiple choice", "\u092c\u0939\u0941\u0935\u093f\u0915\u0932\u094d\u092a\u0940\u092f"),
        "fill_blank": ("fill in the blank", "\u0930\u093f\u0915\u094d\u0924 \u0938\u094d\u0925\u093e\u0928"),
        "short_answer": ("short answer", "\u0932\u0918\u0941 \u0909\u0924\u094d\u0924\u0930\u0940\u092f"),
        "long_answer": ("long answer", "\u0926\u0940\u0930\u094d\u0918 \u0909\u0924\u094d\u0924\u0930\u0940\u092f"),
    }
    for page_type, values in keywords.items():
        if any(value in folded for value in values):
            detected.add(page_type)
    if any(block["kind"] == "options" for block in blocks):
        detected.add("mcq")
    if len(detected) > 1:
        return "mixed"
    return next(iter(detected), "other")


def parse_structured_page(
    lines: Iterable[str],
    source_id: str = "unknown",
    *,
    confidence: str = "high",
) -> StructuredPageResult:
    """Parse one page into compatible Book IR v1 blocks plus review items."""

    source_id = sanitize_text(source_id)
    if not source_id:
        raise ValueError("source_id must be non-empty")
    if confidence not in {"high", "medium"}:
        raise ValueError("confidence must be high or medium")

    source_lines: list[_SourceLine] = []
    for raw_line in lines:
        text = sanitize_text(raw_line)
        if not text:
            continue
        layout_text = unicodedata.normalize(
            "NFC", raw_line.replace("\u00a0", " ")
        )
        layout_text = layout_text.replace("\ufeff", "").replace("\u200b", "")
        column = len(layout_text) - len(layout_text.lstrip(" \t"))
        source_lines.append(
            _SourceLine(text=text, layout_text=layout_text, column=column)
        )
    if source_lines and _PRINTED_PAGE_RE.fullmatch(source_lines[-1].text):
        source_lines.pop()
    source_lines = _merge_wrapped_heading_continuations(source_lines)
    cleaned_lines = [line.text for line in source_lines]

    blocks: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    question: _Question | None = None
    active_question_id: str | None = None
    options: list[_Option] = []
    option_anchor_counts: list[int] = []
    answer_line_count = 0
    question_ordinal = 0
    review_ordinal = 0
    chapter_heading_expected = False

    def add_review(
        review_type: str,
        description: str,
        *,
        for_question: str | None = None,
        blocking: bool = True,
    ) -> None:
        nonlocal review_ordinal
        review_ordinal += 1
        item: dict[str, Any] = {
            "review_id": _stable_review_id(source_id, review_type, review_ordinal),
            "type": review_type,
            "source_ids": [source_id],
            "description": description,
            "blocking": blocking,
        }
        if for_question:
            item["for_question"] = for_question
        review_items.append(item)

    def flush_question() -> None:
        nonlocal question, active_question_id
        if question is None:
            return
        block = question.block()
        active_question_id = question.question_id
        if block is None:
            blocks.append(
                _paragraph_block(
                    question.label,
                    source_id=source_id,
                    confidence="medium",
                )
            )
            add_review(
                "orphan_question_label",
                f"{question.label} has no extracted statement.",
                for_question=question.question_id,
            )
        else:
            if not block.get("hindi") or not block.get("english"):
                block["confidence"] = "medium"
                missing = "Hindi" if not block.get("hindi") else "English"
                add_review(
                    "missing_translation",
                    f"{question.label} has no extracted {missing} statement.",
                    for_question=question.question_id,
                )
            blocks.append(block)
        question = None

    def flush_options() -> None:
        nonlocal options, option_anchor_counts
        if not options:
            return
        columns = _option_columns(option_anchor_counts)
        labels = [option.label for option in options]
        duplicate_labels = len(labels) != len(set(labels))
        if not duplicate_labels:
            order = {"A": 0, "B": 1, "C": 2, "D": 3}
            options.sort(key=lambda option: order[option.label])
            labels = [option.label for option in options]
        missing_labels = [
            label for label in ("A", "B", "C", "D") if label not in labels
        ]
        incomplete_text = any(not option.text for option in options)
        invalid_sequence = duplicate_labels or bool(missing_labels)
        if incomplete_text:
            for option in options:
                text = f"({option.label})"
                if option.text:
                    text += f" {option.text}"
                blocks.append(
                    _paragraph_block(
                        text,
                        source_id=source_id,
                        confidence="medium",
                    )
                )
            add_review(
                "incomplete_options",
                "One or more option labels have no extracted option text.",
                for_question=active_question_id,
            )
        else:
            unusual = invalid_sequence or duplicate_labels or len(labels) != 4
            option_confidence = "medium" if unusual else confidence
            block: dict[str, Any] = {
                "kind": "options",
                "columns": columns,
                "layout": OPTION_LAYOUTS[columns],
                "label_layout": "parenthesized",
                "items": [
                    {
                        "label": option.label,
                        "text": option.text,
                        "language": _language_for(option.text),
                        "runs": language_runs(
                            option.text,
                            default=(
                                "math"
                                if _language_for(option.text) == "hindi"
                                else "latin"
                            ),
                        ),
                    }
                    for option in options
                ],
                **_base_block(source_id, option_confidence),
            }
            if active_question_id:
                block["for_question"] = active_question_id
            blocks.append(block)
            if unusual:
                add_review(
                    "option_sequence",
                    "Expected option labels (A) through (D) exactly once; "
                    f"extracted {labels}, missing {missing_labels}.",
                    for_question=active_question_id,
                )
        options = []
        option_anchor_counts = []

    def flush_answer_lines() -> None:
        nonlocal answer_line_count
        if not answer_line_count:
            return
        block: dict[str, Any] = {
            "kind": "answer_lines",
            "count": answer_line_count,
            "spacing_points": 30.5,
            **_base_block(source_id, confidence),
        }
        if active_question_id:
            block["for_question"] = active_question_id
        blocks.append(block)
        answer_line_count = 0

    for source_line in source_lines:
        line = source_line.text
        heading_role: str | None = None
        if _is_unit_heading(line):
            heading_role = "unit_heading"
        elif _is_question_type_heading(line):
            heading_role = "question_type_heading"
        elif chapter_heading_expected and _QUESTION_RE.match(line) is None:
            heading_role = "chapter_heading"
        if heading_role is not None:
            flush_answer_lines()
            flush_options()
            flush_question()
            active_question_id = None
            blocks.append(
                _heading_block(
                    line,
                    role=heading_role,
                    source_id=source_id,
                    confidence=confidence,
                )
            )
            chapter_heading_expected = heading_role == "unit_heading"
            continue
        chapter_heading_expected = False
        question_match = _QUESTION_RE.match(line)
        if question_match is not None:
            flush_answer_lines()
            flush_options()
            flush_question()
            question_ordinal += 1
            number = int(question_match.group("number"))
            body = question_match.group("body").strip()
            question = _Question(
                question_id=stable_question_id(source_id, question_ordinal),
                label=f"Q{number}.",
                source_id=source_id,
                confidence=confidence,
                label_layout="inline" if body else "standalone",
            )
            active_question_id = question.question_id
            if body:
                question.add(body)
            continue

        line_options = _options_on_line(source_line.layout_text)
        if line_options:
            flush_answer_lines()
            flush_question()
            existing_labels = {option.label for option in options}
            if any(option.label in existing_labels for option in line_options):
                flush_options()
            options.extend(line_options)
            option_anchor_counts.append(len(line_options))
            continue

        if _ANSWER_LINE_RE.fullmatch(line):
            flush_options()
            flush_question()
            answer_line_count += 1
            continue

        if options:
            unique_labels = {option.label for option in options}
            one_column = max(option_anchor_counts, default=1) == 1
            short_continuation = len(line) <= 48 and len(line.split()) <= 8
            if (
                (one_column and "D" not in unique_labels)
                or len(unique_labels) < 4
                or short_continuation
            ):
                nearest = min(
                    reversed(options),
                    key=lambda option: abs(
                        option.source_column - source_line.column
                    ),
                )
                nearest.parts.append(line)
                continue
            flush_options()

        if answer_line_count:
            flush_answer_lines()
        if question is not None:
            question.add(line)
            continue
        blocks.append(
            _paragraph_block(
                line,
                source_id=source_id,
                confidence=confidence,
            )
        )

    flush_question()
    flush_options()
    flush_answer_lines()
    return StructuredPageResult(
        blocks=blocks,
        review_items=review_items,
        page_type=_classify_page(cleaned_lines, blocks),
    )


def parse_structured_lines(
    lines: Iterable[str],
    source_id: str = "unknown",
    *,
    confidence: str = "high",
) -> list[dict[str, Any]]:
    """Compatibility wrapper returning only Book IR blocks."""

    return parse_structured_page(lines, source_id, confidence=confidence).blocks


def parse_structured_text(
    page_text: str,
    source_id: str = "unknown",
    *,
    confidence: str = "high",
) -> list[dict[str, Any]]:
    """Parse the lines in one extracted PDF page."""

    if not isinstance(page_text, str):
        raise TypeError("page_text must be a string")
    return parse_structured_lines(
        page_text.splitlines(),
        source_id,
        confidence=confidence,
    )


def parse_structured_file(
    path: Path,
    *,
    source_id: str | None = None,
    encoding: str = "utf-8",
    confidence: str = "high",
) -> list[dict[str, Any]]:
    """Parse a page-oriented text extraction stored on disk."""

    source = Path(path)
    return parse_structured_text(
        source.read_text(encoding=encoding),
        source_id or source.name,
        confidence=confidence,
    )


__all__ = [
    "PAGE_TYPES",
    "StructuredPageResult",
    "UnicodeSanitizationError",
    "language_runs",
    "parse_structured_file",
    "parse_structured_lines",
    "parse_structured_page",
    "parse_structured_text",
    "sanitize_text",
    "stable_question_id",
]

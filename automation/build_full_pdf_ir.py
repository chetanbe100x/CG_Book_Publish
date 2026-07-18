from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


PDFTOTEXT = Path(r"C:\Program Files\Git\mingw64\bin\pdftotext.exe")
QUESTION_RE = re.compile(r"^Q\s*\d+\.", re.IGNORECASE)
DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def clean_lines(page_text: str) -> list[str]:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in page_text.splitlines()]
    lines = [line for line in lines if line]
    # Printed page numbers are the final standalone number on most source pages.
    if lines and re.fullmatch(r"\d{1,3}", lines[-1]):
        lines.pop()
    return lines


def heading_level(line: str) -> int | None:
    folded = line.upper()
    if line.startswith("अध्याय") or folded in {"CLASS 11", "MATHEMATICS"}:
        return 1
    if "INDEX" in folded or "(SETS)" in folded or "(UNIT" in folded:
        return 2
    if (
        "QUESTION" in folded
        or "MARKS" in folded
        or "रिक्त स्थान" in line
        or "लघु उत्तरीय" in line
        or "दीर्घ उत्तरीय" in line
    ):
        return 2
    return None


def mode_for(line: str, current: tuple[str, int] | None) -> tuple[str, int] | None:
    folded = line.upper()
    if "LONG ANSWER" in folded or "दीर्घ उत्तरीय" in line:
        match = re.search(r"(\d{1,2})\s*MARK", folded)
        return ("long", int(match.group(1)) if match else 4)
    if "SHORT ANSWER" in folded or "लघु उत्तरीय" in line:
        match = re.search(r"(\d{1,2})\s*MARK", folded)
        return ("short", int(match.group(1)) if match else 3)
    if "MULTIPLE CHOICE" in folded or "FILL IN THE BLANK" in folded or "बहुविकल्पीय" in line:
        return None
    return current


def make_page(page_number: int, lines: list[str], section_mode: tuple[str, int] | None) -> tuple[dict, tuple[str, int] | None]:
    source_id = f"Maths_11th.pdf:p{page_number:03d}"
    blocks: list[dict] = []
    page_mode = section_mode
    question_count = 0
    for line in lines:
        next_mode = mode_for(line, page_mode)
        if next_mode != page_mode:
            page_mode = next_mode
        level = heading_level(line)
        if level is not None:
            blocks.append({"kind": "heading", "level": level, "text": line, "source_ids": [source_id], "confidence": "high"})
            continue
        if QUESTION_RE.match(line):
            question_count += 1
            match = QUESTION_RE.match(line)
            assert match is not None
            label = match.group(0)
            remainder = line[match.end():].strip()
            runs = [{"text": label, "language": "latin", "bold": True}]
            if remainder:
                runs.append({"text": " " + remainder, "language": "hindi" if DEVANAGARI_RE.search(remainder) else "latin"})
            blocks.append({"kind": "paragraph", "runs": runs, "source_ids": [source_id], "confidence": "high"})
            continue
        if line.startswith("(") and ")" in line and len(line) < 8:
            blocks.append({"kind": "paragraph", "text": line, "language": "latin", "source_ids": [source_id], "confidence": "high"})
            continue
        language = "hindi" if DEVANAGARI_RE.search(line) else "latin"
        role = "equation" if any(token in line for token in ("∩", "∪", "√", "≤", "≥", "Σ", "∫", "x²", "y²")) else ("hindi" if language == "hindi" else "body")
        blocks.append({"kind": "paragraph", "text": line, "language": language, "role": role, "source_ids": [source_id], "confidence": "high"})

    # Keep the two pilot-verified technical figures in the production IR.
    if page_number == 3:
        blocks.append({"kind": "figure", "path": "figures/page-003-venn.png", "width_inches": 2.2, "source_ids": [source_id], "confidence": "high"})
    if page_number == 19:
        blocks.append({"kind": "figure", "path": "figures/page-019-mapping.png", "width_inches": 2.2, "source_ids": [source_id], "confidence": "high"})

    if page_mode is not None and question_count:
        mode, marks = page_mode
        count = 7 if mode == "short" and marks >= 3 else 5 if mode == "short" else 10 if marks >= 4 else 8
        blocks.append({"kind": "answer_lines", "count": count, "spacing_points": 20 if mode == "short" else 18, "source_ids": [source_id], "confidence": "high"})
    if not blocks:
        blocks.append({"kind": "paragraph", "text": f"[Source page {page_number}]", "source_ids": [source_id], "confidence": "high"})
    return {"source_page": page_number, "blocks": blocks}, page_mode


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    book = root / "Books" / "Class 11" / "Maths"
    source = book / "Input" / "Maths_11th.pdf"
    output = book / "Work" / "book_ir.full.json"
    if not PDFTOTEXT.is_file():
        raise SystemExit(f"pdftotext not found: {PDFTOTEXT}")
    raw = subprocess.check_output([str(PDFTOTEXT), "-layout", "-enc", "UTF-8", str(source), "-"], stderr=subprocess.DEVNULL)
    pages = raw.decode("utf-8", errors="replace").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    page_blocks: list[dict] = []
    section_mode: tuple[str, int] | None = None
    for page_number, page_text in enumerate(pages, start=1):
        page, section_mode = make_page(page_number, clean_lines(page_text), section_mode)
        page_blocks.append(page)
    manifest = {
        "schema_version": 1,
        "book_name": "Class 11 Mathematics 2026-27",
        "scope": "full",
        "source": {"path": "../Input/Maths_11th.pdf", "sha256": sha256(source), "page_count": len(page_blocks)},
        "pages": page_blocks,
    }
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "pages": len(page_blocks), "blocks": sum(len(page["blocks"]) for page in page_blocks)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

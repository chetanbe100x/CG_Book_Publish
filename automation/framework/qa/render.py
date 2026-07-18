from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..core.models import FrameworkError, JobConfig, atomic_json_write, sha256_file
from .pdf_layout import analyze_word_pdf
from .word_render import render_with_word


def _automation_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _vendor_renderer() -> Path:
    return _automation_root() / "vendor" / "render_docx.py"


def _soffice() -> Path:
    configured = os.environ.get("SOFFICE_PATH")
    candidates = [
        Path(configured) if configured else None,
        Path(r"C:\Program Files\LibreOffice\program\soffice.com"),
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise FrameworkError("LibreOffice soffice.com was not found")


def _poppler() -> Path:
    dependencies = Path(sys.executable).resolve().parent.parent
    candidate = dependencies / "native" / "poppler" / "Library" / "bin"
    if (candidate / "pdftoppm.exe").is_file():
        return candidate
    fallback = Path(r"C:\Users\chetan\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin")
    if (fallback / "pdftoppm.exe").is_file():
        return fallback
    raise FrameworkError(f"Bundled Poppler was not found at {candidate} or {fallback}")


def _clean_generated_outputs(output_dir: Path, docx_stem: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.iterdir():
        if path.is_file() and (
            path.name.startswith("page-")
            or path.name.startswith("contact-sheet-")
            or path.name == f"{docx_stem}.pdf"
        ):
            path.unlink()


def _contact_sheets(page_paths: list[Path], output_dir: Path) -> list[Path]:
    sheets: list[Path] = []
    per_sheet = 4
    thumb_width = 600
    margin = 24
    label_height = 36
    for start in range(0, len(page_paths), per_sheet):
        group = page_paths[start : start + per_sheet]
        thumbs: list[Image.Image] = []
        for page in group:
            with Image.open(page) as source:
                ratio = thumb_width / source.width
                thumbs.append(
                    source.convert("RGB").resize(
                        (thumb_width, round(source.height * ratio))
                    )
                )
        cell_height = max(image.height for image in thumbs) + label_height
        canvas = Image.new(
            "RGB",
            (thumb_width * 2 + margin * 3, cell_height * 2 + margin * 3),
            "#dddddd",
        )
        draw = ImageDraw.Draw(canvas)
        for index, image in enumerate(thumbs):
            row, column = divmod(index, 2)
            x = margin + column * (thumb_width + margin)
            y = margin + row * (cell_height + margin)
            canvas.paste(image, (x, y + label_height))
            draw.text((x, y + 8), page_paths[start + index].stem, fill="black")
        destination = output_dir / f"contact-sheet-{start // per_sheet + 1:03d}.png"
        canvas.save(destination)
        sheets.append(destination)
    return sheets


def _render_with_libreoffice(job: JobConfig, stage: str) -> dict[str, Any]:
    document = job.docx_for_stage(stage)
    if not document.is_file():
        raise FrameworkError(f"Cannot render missing {stage} document: {document}")
    output_dir = job.render_dir(stage)
    _clean_generated_outputs(output_dir, document.stem)
    temp_base = job.qa_dir / ".render_tmp" / f"{stage}-{uuid.uuid4().hex}"
    temp_base.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    environment["TEMP"] = str(temp_base)
    environment["TMP"] = str(temp_base)
    environment["SOFFICE_PATH"] = str(_soffice())
    environment["CODEX_POPPLER_PATH"] = str(_poppler())
    command = [
        sys.executable,
        str(_vendor_renderer()),
        str(document),
        "--output_dir",
        str(output_dir),
        "--emit_pdf",
        "--verbose",
    ]
    try:
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
            check=False,
            timeout=300,
        )
        if process.returncode != 0:
            raise FrameworkError(
                "DOCX render failed\nSTDOUT:\n"
                + process.stdout
                + "\nSTDERR:\n"
                + process.stderr
            )
        pages = sorted(
            output_dir.glob("page-*.png"),
            key=lambda path: int(path.stem.split("-")[-1]),
        )
        if not pages:
            raise FrameworkError("Renderer completed without producing page PNGs")
        sheets = _contact_sheets(pages, output_dir)
        return {
            "stage": stage,
            "document": str(document),
            "output_dir": str(output_dir),
            "page_count": len(pages),
            "pages": [str(path) for path in pages],
            "contact_sheets": [str(path) for path in sheets],
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
    finally:
        shutil.rmtree(temp_base, ignore_errors=True)


def _render_pdf_pages(pdf_path: Path, output_dir: Path) -> tuple[list[Path], str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.glob("page-*.png"):
        path.unlink()
    for path in output_dir.glob("contact-sheet-*.png"):
        path.unlink()
    prefix = output_dir / "page"
    process = subprocess.run(
        [
            str(_poppler() / "pdftoppm.exe"),
            "-png",
            "-r",
            "144",
            str(pdf_path),
            str(prefix),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=300,
    )
    if process.returncode != 0:
        raise FrameworkError(
            "Word PDF rasterization failed\nSTDOUT:\n"
            + process.stdout
            + "\nSTDERR:\n"
            + process.stderr
        )
    pages = sorted(
        output_dir.glob("page-*.png"),
        key=lambda path: int(path.stem.split("-")[-1]),
    )
    if not pages:
        raise FrameworkError("Word PDF rasterization produced no page PNGs")
    return pages, process.stdout, process.stderr


def _render_pdf_source(job: JobConfig) -> dict[str, Any]:
    document = job.docx_for_stage("source")
    if not document.is_file():
        raise FrameworkError(f"Cannot render missing source PDF: {document}")
    if document.suffix.casefold() != ".pdf":
        raise FrameworkError(f"PDF source renderer requires a PDF: {document}")
    output_dir = job.render_dir("source")
    pages, stdout, stderr = _render_pdf_pages(document, output_dir)
    sheets = _contact_sheets(pages, output_dir)
    return {
        "stage": "source",
        "document": str(document),
        "renderer": "poppler",
        "authoritative": False,
        "output_dir": str(output_dir),
        "page_count": len(pages),
        "pages": [str(path) for path in pages],
        "contact_sheets": [str(path) for path in sheets],
        "stdout": stdout,
        "stderr": stderr,
    }


def _render_with_word(job: JobConfig, stage: str) -> dict[str, Any]:
    document = job.docx_for_stage(stage)
    if not document.is_file():
        raise FrameworkError(f"Cannot render missing {stage} document: {document}")
    if job.source_type == "pdf":
        source_page_numbers = (
            job.preview_source_page_numbers
            if stage == "preview"
            else job.content_page_numbers
        )
    else:
        source_page_numbers = ()
    expected_bookmarks = tuple(
        f"SourcePdfPage{number:03d}" for number in source_page_numbers
    )
    document_hash = sha256_file(document)
    output_dir = job.render_dir(stage) / f"word-{document_hash[:16]}"
    expected = None if job.pagination_policy == "sample_flow" else job.expected_pages_for_stage(stage)
    word = render_with_word(
        document,
        output_dir,
        expected_page_count=expected,
        expected_bookmarks=expected_bookmarks,
        require_a4=True,
        orientation="portrait",
    )
    expected_map = {
        name: index for index, name in enumerate(expected_bookmarks, start=1)
    }
    if job.pagination_policy != "sample_flow" and expected_bookmarks and word["bookmark_pages"] != expected_map:
        raise FrameworkError(
            "Microsoft Word source-page map is not one-to-one: "
            f"expected {expected_map}, got {word['bookmark_pages']}"
        )

    pdf_path = Path(word["render_pdf"])
    pages, stdout, stderr = _render_pdf_pages(pdf_path, output_dir)
    if len(pages) != int(word["page_count"]):
        raise FrameworkError(
            "Word PDF rasterization page-count mismatch: "
            f"expected {word['page_count']}, got {len(pages)}"
        )
    sheets = _contact_sheets(pages, output_dir)
    layout = analyze_word_pdf(
        job,
        pdf_path,
        stage=stage,
        source_page_numbers=source_page_numbers,
        bookmark_pages=word["bookmark_pages"],
    )
    layout_path = output_dir / "layout-analysis.json"
    atomic_json_write(layout_path, layout)
    if not layout["passed"]:
        raise FrameworkError(
            "Word print-layout QA failed: " + "; ".join(layout["errors"])
        )
    return {
        "stage": stage,
        "document": str(document),
        "renderer": "microsoft_word",
        "authoritative": True,
        "output_dir": str(output_dir),
        "page_count": len(pages),
        "pages": [str(path) for path in pages],
        "contact_sheets": [str(path) for path in sheets],
        "word_render_manifest": word["manifest"],
        "render_pdf": word["render_pdf"],
        "render_pdf_sha256": word["render_pdf_sha256"],
        "word_version": word["word_version"],
        "bookmark_pages": word["bookmark_pages"],
        "layout_analysis": str(layout_path),
        "layout": layout,
        "stdout": stdout,
        "stderr": stderr,
    }


def render_document(job: JobConfig, stage: str) -> dict[str, Any]:
    if stage == "source" and job.source_type == "pdf":
        return _render_pdf_source(job)
    if job.render_authority == "word" and stage in {"preview", "final"}:
        return _render_with_word(job, stage)
    return _render_with_libreoffice(job, stage)

from __future__ import annotations

import importlib
from pathlib import Path
import json
from typing import Any

from pypdf import PdfReader

from ..core.models import (
    FrameworkError,
    JobConfig,
    StatusStore,
    atomic_json_write,
    sha256_file,
    utc_now,
)
from .builder import build_normalized_docx
from .ir import load_book_ir


def pdf_inventory(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        reader = PdfReader(source)
    except Exception as exc:
        raise FrameworkError(f"Invalid PDF source: {source}: {exc}") from exc
    if reader.is_encrypted:
        raise FrameworkError(f"Encrypted PDF sources are not supported: {source}")
    page_text: list[dict[str, int]] = []
    sizes: list[dict[str, float]] = []
    extraction_errors: list[dict[str, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        box = page.mediabox
        sizes.append(
            {
                "width_points": round(float(box.width), 2),
                "height_points": round(float(box.height), 2),
            }
        )
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            text = ""
            extraction_errors.append({"page": str(index), "error": str(exc)})
        page_text.append(
            {
                "page": index,
                "characters": len(text),
                "nul_characters": text.count("\x00"),
                "replacement_characters": text.count("\ufffd"),
            }
        )
    unique_sizes = {
        (value["width_points"], value["height_points"]) for value in sizes
    }
    metadata = {
        str(key).lstrip("/"): str(value)
        for key, value in (reader.metadata or {}).items()
    }
    return {
        "path": str(source),
        "sha256": sha256_file(source),
        "size": source.stat().st_size,
        "page_count": len(reader.pages),
        "encrypted": False,
        "metadata": metadata,
        "page_sizes": [
            {"width_points": width, "height_points": height}
            for width, height in sorted(unique_sizes)
        ],
        "text_extraction": page_text,
        "extraction_errors": extraction_errors,
        "total_extracted_characters": sum(value["characters"] for value in page_text),
        "total_nul_characters": sum(value["nul_characters"] for value in page_text),
    }


def _manifest_text(manifest: dict[str, Any]) -> str:
    values: list[str] = []
    for page in manifest["pages"]:
        for block in page["blocks"]:
            for key in ("text", "label", "hindi", "english"):
                value = block.get(key)
                if isinstance(value, str):
                    values.append(value)
            for run in block.get("runs", []):
                if isinstance(run, dict) and isinstance(run.get("text"), str):
                    values.append(run["text"])
            for item in block.get("items", []):
                if isinstance(item, dict):
                    values.extend(str(item.get(key, "")) for key in ("label", "text"))
    return "\n".join(values)


def _validate_numbering_review(
    job: JobConfig,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    assert job.content_manifest is not None
    review_path = job.content_manifest.parent / "numbering_review.json"
    errors: list[str] = []
    if not review_path.is_file():
        errors.append(f"Numbering review is missing: {review_path}")
        return {"passed": False, "path": str(review_path), "errors": errors}
    import json

    value = json.loads(review_path.read_text(encoding="utf-8"))
    checks = value.get("checks")
    if not isinstance(checks, list):
        errors.append("numbering_review.json requires a checks array")
        checks = []
    manifest_text = _manifest_text(manifest)
    for index, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            errors.append(f"Numbering check {index} must be an object")
            continue
        anchor = str(check.get("anchor", ""))
        if not anchor or anchor not in manifest_text:
            errors.append(f"Numbering check {index} anchor is absent from Book IR")
        label = str(check.get("expected_question_label", ""))
        if label and label not in manifest_text:
            errors.append(f"Numbering check {index} question label {label} is absent")
        for option in check.get("expected_option_labels", []):
            if str(option) not in manifest_text:
                errors.append(
                    f"Numbering check {index} option label {option} is absent"
                )
    return {
        "passed": not errors,
        "path": str(review_path),
        "check_count": len(checks),
        "errors": errors,
    }


def ingest_pdf_job(job: JobConfig) -> dict[str, Any]:
    if job.source_type != "pdf":
        raise FrameworkError("The ingest command is only valid for PDF jobs")
    assert job.content_manifest is not None
    assert job.normalized_source is not None
    inventory = pdf_inventory(job.source)
    manifest_scope = json.loads(job.content_manifest.read_text(encoding="utf-8")).get("scope")
    manifest = load_book_ir(
        job.content_manifest,
        source_pdf=job.source,
        expected_pages=job.preview_source_page_numbers if manifest_scope == "preview" else (),
    )
    if int(manifest["source"]["page_count"]) != int(inventory["page_count"]):
        raise FrameworkError("Book IR page count does not match the source PDF")
    if job.adapter:
        try:
            adapter = importlib.import_module(f"framework.adapters.{job.adapter}")
        except ImportError as exc:
            raise FrameworkError(f"PDF adapter could not be loaded: {job.adapter}") from exc
        prepare = getattr(adapter, "prepare", None)
        if not callable(prepare):
            raise FrameworkError(f"PDF adapter has no prepare() function: {job.adapter}")
        prepare(job, manifest)
    numbering = _validate_numbering_review(job, manifest)
    if not numbering["passed"]:
        raise FrameworkError("Numbering review failed: " + "; ".join(numbering["errors"]))
    composition = build_normalized_docx(job, manifest, job.normalized_source)
    source_manifest_path = job.content_manifest.parent / "source_manifest.json"
    source_manifest = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "source": inventory,
        "selected_pages": list(job.preview_source_page_numbers),
        "content_manifest": str(job.content_manifest),
        "content_manifest_sha256": sha256_file(job.content_manifest),
    }
    atomic_json_write(source_manifest_path, source_manifest)
    result = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "source": inventory,
        "manifest": {
            "path": str(job.content_manifest),
            "sha256": sha256_file(job.content_manifest),
            "scope": manifest["scope"],
            "selected_pages": [page["source_page"] for page in manifest["pages"]],
        },
        "numbering_review": numbering,
        "normalized_source": {
            **composition,
            "sha256": sha256_file(job.normalized_source),
        },
    }
    atomic_json_write(job.qa_dir / "ingest.json", result)
    StatusStore(job).transition(
        "ingested",
        source_sha256=sha256_file(job.source),
        template_sha256=sha256_file(job.template),
        content_manifest_sha256=sha256_file(job.content_manifest),
        normalized_source_sha256=sha256_file(job.normalized_source),
    )
    return result





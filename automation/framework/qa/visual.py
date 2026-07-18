from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.models import IntegrityError, JobConfig, atomic_json_write, utc_now
from .word_render import validate_word_render_manifest


def record_visual_review(
    job: JobConfig,
    *,
    stage: str,
    passed: bool,
    page_count: int,
    notes: str,
    render_manifest: Path | None = None,
) -> dict[str, Any]:
    """Record a human/agent page inspection without changing workflow state."""
    if stage not in {"source", "preview", "final"}:
        raise ValueError(f"Unknown visual-review stage: {stage}")

    binding: dict[str, Any] = {"hash_bound": False}
    if render_manifest is not None:
        manifest_path = Path(render_manifest).resolve()
        manifest = validate_word_render_manifest(
            job.docx_for_stage(stage),
            manifest_path,
        )
        if int(manifest.get("page_count", 0)) != int(page_count):
            raise IntegrityError(
                "Visual-review page count does not match the Microsoft Word render"
            )
        binding = {
            "hash_bound": True,
            "render_manifest": str(manifest_path),
            "document_sha256": manifest["document_sha256"],
            "render_pdf_sha256": manifest["render_pdf_sha256"],
            "renderer": "microsoft_word",
            "word_version": manifest["word_version"],
        }

    review = {
        "stage": stage,
        "passed": bool(passed),
        "page_count": int(page_count),
        "reviewed_at": utc_now(),
        "notes": notes,
        **binding,
    }
    review_path = job.qa_dir / f"visual-review-{stage}.json"
    atomic_json_write(review_path, review)

    status = json.loads(job.status_path.read_text(encoding="utf-8"))
    status.setdefault("visual_reviews", {})[stage] = review
    status["updated_at"] = utc_now()
    atomic_json_write(job.status_path, status)

    if job.report_path.exists():
        report = job.report_path.read_text(encoding="utf-8")
        report = report.replace(
            "Visual review status: generated; human inspection required",
            f"Visual review status: {'PASS' if passed else 'FAIL'}; {page_count} pages inspected",
        )
        marker = f"Visual review ({stage}):"
        if marker not in report:
            report += (
                f"\n{marker} {'PASS' if passed else 'FAIL'}\n"
                f"Pages inspected: {page_count}\n"
                f"Notes: {notes}\n"
            )
        job.report_path.write_text(report, encoding="utf-8")
    return {"review_file": str(review_path), **review}


def record_word_visual_review(
    job: JobConfig,
    *,
    stage: str,
    passed: bool,
    page_count: int,
    notes: str,
    render_manifest: Path,
) -> dict[str, Any]:
    """Record a visual review that is bound to an authoritative Word render."""
    return record_visual_review(
        job,
        stage=stage,
        passed=passed,
        page_count=page_count,
        notes=notes,
        render_manifest=render_manifest,
    )


def validate_word_visual_review(job: JobConfig, *, stage: str) -> dict[str, Any]:
    """Fail if a recorded Word visual approval is missing, stale, or unbound."""
    if stage not in {"source", "preview", "final"}:
        raise ValueError(f"Unknown visual-review stage: {stage}")
    review_path = job.qa_dir / f"visual-review-{stage}.json"
    if not review_path.is_file():
        raise IntegrityError(f"Visual review is missing for {stage}")
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"Visual review is invalid for {stage}: {exc}") from exc
    if not review.get("passed"):
        raise IntegrityError(f"Visual review has not passed for {stage}")
    if not review.get("hash_bound"):
        raise IntegrityError(
            f"Visual review for {stage} is not bound to a Microsoft Word render"
        )
    raw_manifest = review.get("render_manifest")
    if not isinstance(raw_manifest, str) or not raw_manifest:
        raise IntegrityError(f"Visual review for {stage} has no render manifest")
    manifest = validate_word_render_manifest(
        job.docx_for_stage(stage),
        Path(raw_manifest),
    )
    if review.get("document_sha256") != manifest.get("document_sha256"):
        raise IntegrityError("Visual-review DOCX hash does not match its Word render")
    if review.get("render_pdf_sha256") != manifest.get("render_pdf_sha256"):
        raise IntegrityError("Visual-review PDF hash does not match its Word render")
    if int(review.get("page_count", 0)) != int(manifest.get("page_count", -1)):
        raise IntegrityError("Visual-review page count does not match its Word render")
    return review

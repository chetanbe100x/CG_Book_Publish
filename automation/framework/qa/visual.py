from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.models import JobConfig, atomic_json_write, utc_now


def record_visual_review(
    job: JobConfig,
    *,
    stage: str,
    passed: bool,
    page_count: int,
    notes: str,
) -> dict[str, Any]:
    """Record a human/agent page inspection without changing workflow state."""
    if stage not in {"source", "preview", "final"}:
        raise ValueError(f"Unknown visual-review stage: {stage}")

    review = {
        "stage": stage,
        "passed": bool(passed),
        "page_count": int(page_count),
        "reviewed_at": utc_now(),
        "notes": notes,
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

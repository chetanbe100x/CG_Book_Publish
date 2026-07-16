from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..core.models import JobConfig, utc_now


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def write_artifact(job: JobConfig, audit: dict[str, Any]) -> None:
    template = audit["template"]
    features = template["features"]
    geometry = json.dumps(features.get("geometry", []), ensure_ascii=False, indent=2)
    content = f"""# Template Execution Contract

## Reference

- Path: `{template['path']}`
- SHA-256: `{template['sha256']}`
- Package parts: {template['package_part_count']}
- Section count: {features.get('section_count', 0)}

## Page System

```json
{geometry}
```

The template's final section properties, header parts, footer parts,
relationships, decorative media, margins, and page-number field are
preserve-only.

## Editable Slot

- Package part: `word/document.xml`
- Slot: children of `w:body` before final `w:sectPr`
- Policy: replace from the audited source while preserving source text,
  typography, equations, numbering, tables, drawings, VML, and formatting.

## Package Preservation

- `Book_Template.docx` is immutable and must retain the SHA-256 above.
- Template headers, footers, relationships, and recurring media are preserve-only.
- `word/settings.xml` may only be changed to remove `w:updateFields`.
- Source dependencies are copied only when referenced by selected body content.

## Fidelity Gates

- Exact body token sequence and structural object counts.
- Valid XML and relationship targets.
- Template page geometry and recurring parts unchanged.
- Render every page to PNG and inspect before approval or delivery.
"""
    _atomic_text(job.artifact_path, content)


def write_qa_report(
    job: JobConfig,
    *,
    stage: str,
    validation: dict[str, Any],
    render: dict[str, Any] | None = None,
    regression: dict[str, Any] | None = None,
) -> None:
    lines = [
        "Accuracy-First Book Conversion QA Report",
        f"Generated: {utc_now()}",
        f"Job: {job.job_id}",
        f"Class / Subject: {job.school_class} / {job.subject}",
        f"Stage: {stage}",
        f"Structural result: {'PASS' if validation.get('passed') else 'FAIL'}",
        "",
    ]
    if validation.get("errors"):
        lines.append("Errors:")
        lines.extend(f"- {value}" for value in validation["errors"])
        lines.append("")
    if validation.get("warnings"):
        lines.append("Warnings:")
        lines.extend(f"- {value}" for value in validation["warnings"])
        lines.append("")
    if render:
        lines.extend(
            [
                f"Rendered pages: {render['page_count']}",
                f"Render directory: {render['output_dir']}",
                "Visual review status: generated; human inspection required",
                "",
            ]
        )
    if regression:
        lines.extend(
            [
                f"Approved regression: {'PASS' if regression.get('passed') else 'FAIL'}",
                *[f"- {value}" for value in regression.get("errors", [])],
                "",
            ]
        )
    lines.extend(
        [
            "Protected files:",
            f"- Source: {job.source}",
            f"- Template: {job.template}",
            f"- Approved reference: {job.approved_reference or 'not configured'}",
            "",
        ]
    )
    _atomic_text(job.report_path, "\n".join(lines))

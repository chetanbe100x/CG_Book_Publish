from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from framework.core.audit import audit_job
from framework.core.compose import compose, create_full, create_preview
from framework.core.models import FrameworkError, JobConfig, StatusStore, sha256_file
from framework.qa.render import render_document
from framework.qa.report import write_artifact, write_qa_report
from framework.qa.structural import compare_with_approved, validate_output


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def command_audit(job: JobConfig) -> dict:
    result = audit_job(job)
    write_artifact(job, result)
    return result


def command_preview(job: JobConfig) -> dict:
    if not job.audit_path.exists():
        command_audit(job)
    return create_preview(job)


def command_qa(job: JobConfig, stage: str) -> dict:
    source_pages = job.preview_source_pages if stage == "preview" else None
    document = job.docx_for_stage(stage)
    validation = (
        validate_output(job, document, source_pages)
        if stage != "source"
        else {
            "passed": True,
            "errors": [],
            "warnings": [],
            "output": str(document),
            "sha256": sha256_file(document),
        }
    )
    if not validation["passed"]:
        write_qa_report(job, stage=stage, validation=validation)
        raise FrameworkError("Structural QA failed: " + "; ".join(validation["errors"]))
    render = render_document(job, stage)
    regression = compare_with_approved(job, document) if stage == "final" else None
    if regression is not None and not regression["passed"]:
        write_qa_report(
            job,
            stage=stage,
            validation=validation,
            render=render,
            regression=regression,
        )
        raise FrameworkError("Approved regression failed: " + "; ".join(regression["errors"]))
    write_qa_report(
        job,
        stage=stage,
        validation=validation,
        render=render,
        regression=regression,
    )
    store = StatusStore(job)
    if stage == "preview":
        store.transition(
            "preview_qa_passed",
            preview_sha256=sha256_file(document),
            preview_pages=render["page_count"],
        )
    elif stage == "final":
        store.transition(
            "final_qa_passed",
            final_sha256=sha256_file(document),
            final_pages=render["page_count"],
        )
    return {"validation": validation, "render": render, "regression": regression}


def command_approve(job: JobConfig) -> dict:
    status = StatusStore(job).load()
    if status.get("state") != "preview_qa_passed":
        raise FrameworkError("Preview approval requires a passed preview QA run")
    return StatusStore(job).transition(
        "preview_approved",
        approved_preview_sha256=sha256_file(job.preview_output),
        approved_source_sha256=sha256_file(job.source),
        approved_template_sha256=sha256_file(job.template),
    )


def command_regression(job: JobConfig) -> dict:
    candidate = job.qa_dir / "Regression Candidate.docx"
    if candidate.exists():
        candidate.unlink()
    composition = compose(job, candidate, None)
    validation = validate_output(job, candidate, None)
    regression = compare_with_approved(job, candidate)
    result = {
        "composition": composition,
        "validation": validation,
        "regression": regression,
    }
    if not validation["passed"] or not regression["passed"]:
        raise FrameworkError("Class 12 Maths regression failed")
    return result


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Accuracy-first DOCX book conversion pipeline")
    subparsers = root.add_subparsers(dest="command", required=True)
    for name in ("audit", "preview", "approve-preview", "full", "status", "regression"):
        command = subparsers.add_parser(name)
        command.add_argument("--job", required=True)
    qa = subparsers.add_parser("qa")
    qa.add_argument("--job", required=True)
    qa.add_argument("--stage", choices=("source", "preview", "final"), required=True)
    return root


def main() -> int:
    args = build_parser().parse_args()
    try:
        job = JobConfig.load(args.job)
        if args.command == "audit":
            result = command_audit(job)
        elif args.command == "preview":
            result = command_preview(job)
        elif args.command == "qa":
            result = command_qa(job, args.stage)
        elif args.command == "approve-preview":
            result = command_approve(job)
        elif args.command == "full":
            result = create_full(job)
        elif args.command == "regression":
            result = command_regression(job)
        else:
            result = StatusStore(job).load()
        _print(result)
        return 0
    except FrameworkError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

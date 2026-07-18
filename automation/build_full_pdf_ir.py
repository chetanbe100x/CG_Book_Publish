from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from framework.core.models import FrameworkError, JobConfig
from framework.ingest.extract import extract_book_ir_job


DEFAULT_JOB = (
    Path(__file__).resolve().parents[1]
    / "Books"
    / "Class 11"
    / "Maths"
    / "job.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compatibility wrapper for draft-only PDF extraction. "
            "Reviewed Book IR and review-queue files are never overwritten."
        )
    )
    parser.add_argument("--job", default=str(DEFAULT_JOB))
    return parser


def _print(value: object) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        job = JobConfig.load(args.job)
        result = extract_book_ir_job(job)
    except (FrameworkError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

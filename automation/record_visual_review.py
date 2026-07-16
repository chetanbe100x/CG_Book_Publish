from __future__ import annotations

import argparse
import json

from framework.core.models import JobConfig
from framework.qa.visual import record_visual_review


def main() -> int:
    parser = argparse.ArgumentParser(description="Record completed page-by-page visual QA")
    parser.add_argument("--job", required=True)
    parser.add_argument("--stage", choices=("source", "preview", "final"), required=True)
    parser.add_argument("--pages", type=int, required=True)
    parser.add_argument("--result", choices=("pass", "fail"), required=True)
    parser.add_argument("--notes", required=True)
    args = parser.parse_args()
    result = record_visual_review(
        JobConfig.load(args.job),
        stage=args.stage,
        passed=args.result == "pass",
        page_count=args.pages,
        notes=args.notes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

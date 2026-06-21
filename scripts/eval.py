"""Run Inspector against a fixture and score findings vs its bugs.json manifest.

Usage:
    python scripts/eval.py examples/sample-buggy-web
    python scripts/eval.py examples/sample-buggy-web --surface web --max-steps 40 --min-recall 0.5

Tip: score the Claude brain with  INSPECTOR_DRIVER=anthropic  + ANTHROPIC_API_KEY.
Exits non-zero if recall < --min-recall (default 0.0 → measurement only).
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

load_dotenv()

from inspector.eval import run_and_score  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_path")
    ap.add_argument("--surface", default=None)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--min-recall", type=float, default=0.0)
    args = ap.parse_args()

    report = run_and_score(args.repo_path, args.surface, args.max_steps)

    print(f"\n=== {report.get('fixture')} ({report.get('surface')}) — "
          f"ready={report.get('ready')} stop={report.get('stop_reason')} ===")
    print(f"recall={report['recall']}  precision={report['precision']}  f1={report['f1']}  "
          f"({report['detected']}/{report['total_expected']} bugs, "
          f"{report['false_positives']} false-pos)")
    for b in report["per_bug"]:
        mark = "✓" if b["detected"] else "✗"
        print(f"  {mark} {b['id']} [{b['severity']}/{b['difficulty']}] {b['screen']}")
    print(f"\nreplay: {report.get('replay')}")
    print(json.dumps(report, indent=2))

    return 0 if report["recall"] >= args.min_recall else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Learning report: aggregate logged runs and show suggestions (algorithmic, no external model).
Usage:
  python scripts/learn_report.py           # report from default log
  python scripts/learn_report.py --suggest # include update suggestions
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json

from src.learning import aggregate_log, suggest_updates, get_log_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate learning log and optionally suggest updates.")
    parser.add_argument("--log", type=Path, default=None, help="Path to learning_log.jsonl")
    parser.add_argument("--suggest", action="store_true", help="Compute and print update suggestions")
    parser.add_argument("--json", action="store_true", help="Output report as JSON")
    args = parser.parse_args()

    log_path = args.log or get_log_path()
    report = aggregate_log(log_path)

    if args.json:
        out = {
            "total_runs": report.total_runs,
            "overall": report.overall,
            "by_palette": report.by_palette,
            "by_keyword": report.by_keyword,
        }
        if args.suggest:
            out["suggestions"] = suggest_updates(report=report)
        print(json.dumps(out, indent=2))
        return

    print(f"Learning report (log: {log_path})")
    print(f"Total runs: {report.total_runs}")
    if report.total_runs == 0:
        print("No entries yet. Generate videos with --learn to build the log.")
        return
    print("\nOverall:")
    for k, v in report.overall.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.3f}")
        else:
            print(f"  {k}: {v}")
    print("\nBy palette:")
    for name, data in report.by_palette.items():
        print(f"  {name}: count={data.get('count', 0)}, mean_motion={data.get('mean_motion_level', 0):.3f}")
    print("\nBy keyword (top 15 by count):")
    kw_items = sorted(report.by_keyword.items(), key=lambda x: -x[1].get("count", 0))[:15]
    for kw, data in kw_items:
        print(f"  {kw}: count={data.get('count', 0)}, mean_motion={data.get('mean_motion_level', 0):.3f}")

    if args.suggest:
        suggestions = suggest_updates(report=report)
        print("\nSuggestions (for training/learning):")
        if not suggestions:
            print("  None.")
        for s in suggestions:
            print(f"  - {s}")


if __name__ == "__main__":
    main()

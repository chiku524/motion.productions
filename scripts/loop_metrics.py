#!/usr/bin/env python3
"""
Summarise the per-container loop metrics written by scripts/automate_loop.py.

    python scripts/loop_metrics.py                    # last 24 h, knowledge/metrics (or $LOOP_METRICS_DIR)
    python scripts/loop_metrics.py --hours 6 --dir knowledge/metrics
    python scripts/loop_metrics.py --rows-per-item 3.5 --json

Reports per container and in total: clips, accept rate (accepted / (accepted + rejected)), re-rolls per
clip, newly observed registry cells (total and per active hour), discovery rows posted per clip, and a
projection of daily D1 rows written against the Cloudflare free limit (100,000 / day).

D1 write projection (an ESTIMATE; the Worker does not report rows written back to the client):
    rows per clip   = post_items x --rows-per-item (default 3: one row + its index entries) + write_requests
    projected / day = sum over containers of (clips per active hour x 24 x rows per clip) + --fixed-overhead
Reference from docs/EXHAUSTIVE_REGISTRY_PLAN.md: 91-145 rows per creative clip, ~7.3k fixed rows/day.
Rate uses each container's active span (first to last record), i.e. it assumes 24 h of continuous running.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.knowledge.loop_metrics import FILE_PREFIX, default_metrics_dir  # noqa: E402

D1_DAILY_WRITE_LIMIT = 100_000
DEFAULT_ROWS_PER_ITEM = 3.0
DEFAULT_FIXED_OVERHEAD = 7_300
MIN_SPAN_HOURS = 0.25  # avoid absurd rates from a handful of clips seconds apart


def load_records(directory: Path, since_epoch: float) -> list[dict]:
    out: list[dict] = []
    for path in sorted(directory.glob(f"{FILE_PREFIX}*.jsonl*")):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and float(r.get("t") or 0) >= since_epoch:
                        out.append(r)
        except OSError:
            continue
    return out


def summarise(records: list[dict], rows_per_item: float, fixed_overhead: float) -> dict:
    by_name: dict[str, list[dict]] = {}
    for r in records:
        by_name.setdefault(str(r.get("name") or "loop"), []).append(r)

    containers = {}
    for name, rs in sorted(by_name.items()):
        rs.sort(key=lambda r: r.get("t", 0))
        n = len(rs)
        counts = {k: sum(1 for r in rs if r.get("outcome") == k) for k in ("accepted", "rejected", "unchecked", "error")}
        gated = counts["accepted"] + counts["rejected"]
        # An iteration that rendered successfully (accepted/unchecked) posts rows; rejected ones post nothing.
        posted = [r for r in rs if r.get("outcome") in ("accepted", "unchecked")]
        span_h = max(MIN_SPAN_HOURS, (rs[-1].get("t", 0) - rs[0].get("t", 0)) / 3600.0)
        new_cells = sum(int(r.get("new_cells") or 0) for r in rs)
        items_per_clip = (sum(int(r.get("post_items") or 0) for r in posted) / len(posted)) if posted else 0.0
        wreq_per_clip = (sum(int(r.get("write_requests") or 0) for r in rs) / n) if n else 0.0
        rows_per_clip = items_per_clip * rows_per_item + wreq_per_clip
        clips_per_h = n / span_h
        containers[name] = {
            "clips": n, **counts,
            "accept_rate": (counts["accepted"] / gated) if gated else None,
            "rerolls_per_clip": sum(int(r.get("rerolls") or 0) for r in rs) / n,
            "new_cells": new_cells,
            "new_cells_per_hour": new_cells / span_h,
            "post_items_per_clip": items_per_clip,
            "write_requests_per_clip": wreq_per_clip,
            "est_d1_rows_per_clip": rows_per_clip,
            "active_hours": span_h,
            "clips_per_hour": clips_per_h,
            "projected_d1_rows_per_day": clips_per_h * 24 * rows_per_clip,
        }

    total_clips = sum(c["clips"] for c in containers.values())
    acc = sum(c["accepted"] for c in containers.values())
    rej = sum(c["rejected"] for c in containers.values())
    variable = sum(c["projected_d1_rows_per_day"] for c in containers.values())
    projected = variable + (fixed_overhead if containers else 0)
    total = {
        "clips": total_clips, "accepted": acc, "rejected": rej,
        "accept_rate": (acc / (acc + rej)) if (acc + rej) else None,
        "new_cells": sum(c["new_cells"] for c in containers.values()),
        "new_cells_per_hour": sum(c["new_cells_per_hour"] for c in containers.values()),
        "post_items_per_clip": (sum(c["post_items_per_clip"] * (c["accepted"] + c["unchecked"]) for c in containers.values())
                                / max(1, sum(c["accepted"] + c["unchecked"] for c in containers.values()))),
        "projected_d1_rows_per_day": projected,
        "d1_daily_limit": D1_DAILY_WRITE_LIMIT,
        "d1_limit_used_pct": 100.0 * projected / D1_DAILY_WRITE_LIMIT,
        "clips_per_day_at_limit": (
            (D1_DAILY_WRITE_LIMIT - fixed_overhead) / (variable / max(1e-9, sum(c["clips_per_hour"] * 24 for c in containers.values())))
            if variable > 0 else None
        ),
        "reference_rows_per_clip_91_145_projection": [
            sum(c["clips_per_hour"] * 24 for c in containers.values()) * r + fixed_overhead for r in (91, 145)
        ],
    }
    return {"containers": containers, "total": total}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.0f}%"


def render(summary: dict, hours: float, directory: Path) -> str:
    cs, t = summary["containers"], summary["total"]
    if not cs:
        return f"No loop metrics in {directory} for the last {hours:g} h (containers paused, or no clips yet)."
    lines = [f"Loop metrics - last {hours:g} h - {directory}", ""]
    head = f"{'container':<14}{'clips':>6}{'accept':>8}{'reroll/clip':>12}{'new cells':>10}{'cells/h':>9}{'rows posted/clip':>18}{'est D1 rows/clip':>18}{'D1 rows/day':>13}"
    lines.append(head)
    lines.append("-" * len(head))
    for name, c in cs.items():
        lines.append(
            f"{name:<14}{c['clips']:>6}{_pct(c['accept_rate']):>8}{c['rerolls_per_clip']:>12.2f}{c['new_cells']:>10}"
            f"{c['new_cells_per_hour']:>9.1f}{c['post_items_per_clip']:>18.1f}{c['est_d1_rows_per_clip']:>18.1f}"
            f"{c['projected_d1_rows_per_day']:>13,.0f}"
        )
    lines.append("")
    lines.append(f"Total: {t['clips']} clips, accept rate {_pct(t['accept_rate'])} "
                 f"({t['accepted']} accepted / {t['rejected']} rejected as duplicates), "
                 f"{t['new_cells']} new cells ({t['new_cells_per_hour']:.1f}/h)")
    lines.append(f"Rows posted per clip: {t['post_items_per_clip']:.1f}")
    lines.append(f"Projected D1 writes/day: {t['projected_d1_rows_per_day']:,.0f} of {t['d1_daily_limit']:,} free "
                 f"({t['d1_limit_used_pct']:.0f}%) - estimate, 24 h of continuous running")
    lo, hi = t["reference_rows_per_clip_91_145_projection"]
    lines.append(f"  with the docs' 91-145 rows/clip: {lo:,.0f} - {hi:,.0f}")
    if t["clips_per_day_at_limit"] is not None:
        lines.append(f"  clips/day that would hit the limit at the measured rows/clip: {t['clips_per_day_at_limit']:,.0f}")
    if t["d1_limit_used_pct"] > 100:
        lines.append("  WARNING: projection exceeds the free D1 write limit - do not restart all loops.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", default=None, help="metrics directory (default $LOOP_METRICS_DIR or knowledge/metrics)")
    ap.add_argument("--hours", type=float, default=24.0, help="look-back window in hours (default 24)")
    ap.add_argument("--rows-per-item", type=float, default=DEFAULT_ROWS_PER_ITEM,
                    help="D1 rows written per posted discovery item (estimate, default 3)")
    ap.add_argument("--fixed-overhead", type=float, default=DEFAULT_FIXED_OVERHEAD,
                    help="fixed D1 rows/day (leases, compaction, loop state; default 7300)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = ap.parse_args(argv)

    directory = Path(args.dir or os.environ.get("LOOP_METRICS_DIR") or default_metrics_dir())
    recs = load_records(directory, time.time() - args.hours * 3600.0) if directory.is_dir() else []
    summary = summarise(recs, args.rows_per_item, args.fixed_overhead)
    print(json.dumps(summary, indent=2) if args.json else render(summary, args.hours, directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
Aggregate the learning log by keyword and palette. Our algorithms only — no external model.
Produces a summary report for training/learning purposes.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .log import read_log, get_log_path


@dataclass
class AggregationReport:
    """Summary of logged runs for learning."""
    total_runs: int
    by_palette: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_keyword: dict[str, dict[str, Any]] = field(default_factory=dict)
    overall: dict[str, Any] = field(default_factory=dict)


def _words(prompt: str) -> set[str]:
    return set(re.findall(r"[a-z]+", (prompt or "").lower()))


def aggregate_log(log_path: Path | None = None) -> AggregationReport:
    """
    Read the learning log and aggregate by palette and by keyword.
    Returns a report with mean motion_level, mean_brightness, counts, etc.
    """
    entries = read_log(log_path)
    if not entries:
        return AggregationReport(total_runs=0)

    by_palette: dict[str, list[dict[str, Any]]] = {}
    by_keyword: dict[str, list[dict[str, Any]]] = {}
    all_motion: list[float] = []
    all_brightness: list[float] = []
    all_contrast: list[float] = []

    for e in entries:
        spec = e.get("spec", {})
        analysis = e.get("analysis", {})
        prompt = e.get("prompt", "")
        palette = spec.get("palette_name", "default")
        by_palette.setdefault(palette, []).append({"spec": spec, "analysis": analysis})
        words = _words(prompt)
        for w in words:
            by_keyword.setdefault(w, []).append({"spec": spec, "analysis": analysis})
        all_motion.append(analysis.get("motion_level", 0))
        all_brightness.append(analysis.get("mean_brightness", 0))
        all_contrast.append(analysis.get("mean_contrast", 0))

    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {}
        motions = [x["analysis"].get("motion_level", 0) for x in items]
        bright = [x["analysis"].get("mean_brightness", 0) for x in items]
        return {
            "count": len(items),
            "mean_motion_level": sum(motions) / len(motions),
            "mean_brightness": sum(bright) / len(bright),
        }

    report_by_palette = {k: summarize(v) for k, v in by_palette.items()}
    report_by_keyword = {k: summarize(v) for k, v in by_keyword.items()}

    n = len(entries)
    overall = {
        "total_runs": n,
        "mean_motion_level": sum(all_motion) / n if all_motion else 0,
        "mean_brightness": sum(all_brightness) / n if all_brightness else 0,
        "mean_contrast": sum(all_contrast) / n if all_contrast else 0,
    }

    return AggregationReport(
        total_runs=n,
        by_palette=report_by_palette,
        by_keyword=report_by_keyword,
        overall=overall,
    )

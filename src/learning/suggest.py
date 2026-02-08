"""
Suggest updates to our data (intensity, palette) based on aggregated learning.
Heavy algorithms and rules only — no external model.
"""
from pathlib import Path
from typing import Any

from .aggregate import aggregate_log, AggregationReport


def suggest_updates(
    report: AggregationReport | None = None,
    log_path: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Given an aggregation report, suggest optional updates for our procedural data.
    Returns a list of suggestions, e.g. {"type": "intensity", "keyword": "calm", "suggested_value": 0.3}.
    """
    if report is None:
        report = aggregate_log(log_path)
    suggestions: list[dict[str, Any]] = []

    # Rule: if a keyword's mean_motion_level is very low and we want more visible motion,
    # suggest slightly higher intensity for that keyword (if we had intensity in spec).
    MOTION_LOW = 2.0
    MOTION_HIGH = 15.0
    for keyword, data in report.by_keyword.items():
        if data.get("count", 0) < 2:
            continue
        mean_motion = data.get("mean_motion_level", 0)
        if mean_motion < MOTION_LOW:
            suggestions.append({
                "type": "intensity",
                "keyword": keyword,
                "reason": f"low_motion ({mean_motion:.2f})",
                "suggested_action": "Consider increasing intensity or motion for this keyword in data/keywords.py",
            })
        elif mean_motion > MOTION_HIGH:
            suggestions.append({
                "type": "intensity",
                "keyword": keyword,
                "reason": f"high_motion ({mean_motion:.2f})",
                "suggested_action": "Consider decreasing intensity for this keyword if you want calmer output",
            })

    # Rule: if a palette's mean_brightness is very low/high, note it for possible palette tweak
    for palette, data in report.by_palette.items():
        if data.get("count", 0) < 2:
            continue
        mean_bright = data.get("mean_brightness", 128)
        if mean_bright < 50:
            suggestions.append({
                "type": "palette",
                "palette": palette,
                "reason": f"very_dark ({mean_bright:.1f})",
                "suggested_action": "Consider brightening this palette in data/palettes.py if desired",
            })
        elif mean_bright > 220:
            suggestions.append({
                "type": "palette",
                "palette": palette,
                "reason": f"very_bright ({mean_bright:.1f})",
                "suggested_action": "Consider darkening this palette if desired",
            })

    return suggestions

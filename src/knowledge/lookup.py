"""
Lookup: build knowledge dict for creation from aggregate + learned registries.
Creation uses this to refine parameters from origins + learned values.
"""
from typing import Any

from .registry import load_registry


def get_knowledge_for_creation(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Build the knowledge dict passed to build_spec_from_instruction.
    Combines: aggregate (by_keyword, by_palette, overall) + learned registries.
    """
    from ..learning import aggregate_log
    from ..learning.log import get_log_path

    knowledge: dict[str, Any] = {}

    # Aggregate from learning log
    try:
        log_path = get_log_path(config)
        report = aggregate_log(log_path)
        knowledge["by_keyword"] = {
            k: {
                "count": v.get("count", 0),
                "mean_motion_level": v.get("mean_motion_level", 0),
                "mean_brightness": v.get("mean_brightness", 0),
            }
            for k, v in report.by_keyword.items()
        }
        knowledge["by_palette"] = {
            k: {
                "count": v.get("count", 0),
                "mean_motion_level": v.get("mean_motion_level", 0),
                "mean_brightness": v.get("mean_brightness", 0),
            }
            for k, v in report.by_palette.items()
        }
        knowledge["overall"] = report.overall
    except Exception:
        knowledge.setdefault("by_keyword", {})
        knowledge.setdefault("by_palette", {})
        knowledge.setdefault("overall", {})

    # Learned colors (for palette refinement / blending)
    try:
        learned_colors = load_registry("learned_colors", config)
        knowledge["learned_colors"] = learned_colors.get("colors", {})
    except Exception:
        knowledge["learned_colors"] = {}

    # Learned motion (for motion refinement)
    try:
        learned_motion = load_registry("learned_motion", config)
        knowledge["learned_motion"] = learned_motion.get("profiles", [])
    except Exception:
        knowledge["learned_motion"] = []

    return knowledge

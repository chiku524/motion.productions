"""
Lookup: build knowledge dict for creation from aggregate + learned registries.
Creation uses this to refine parameters from origins + learned values.
When api_base is set, fetches from D1 via API to utilize cloud-stored discoveries.
"""
import logging
from typing import Any

from .registry import load_registry

logger = logging.getLogger(__name__)


def get_knowledge_for_creation(
    config: dict[str, Any] | None = None,
    *,
    api_base: str | None = None,
) -> dict[str, Any]:
    """
    Build the knowledge dict passed to build_spec_from_instruction.
    Combines: aggregate (by_keyword, by_palette, overall) + learned registries.
    When api_base is set, fetches learned_colors and learned_motion from API (D1).
    """
    from ..learning import aggregate_log
    from ..learning.log import get_log_path

    knowledge: dict[str, Any] = {}
    base = api_base or (config or {}).get("api_base", "")

    # Aggregate: prefer API learning/stats when api_base set, else local log
    if base:
        try:
            from ..api_client import api_request_with_retry
            stats = api_request_with_retry(base, "GET", "/api/learning/stats", timeout=15)
            knowledge["by_keyword"] = stats.get("by_keyword", {})
            knowledge["by_palette"] = stats.get("by_palette", {})
            knowledge["overall"] = stats.get("overall", {})
        except Exception as e:
            from ..api_client import APIError
            if isinstance(e, APIError):
                logger.warning("GET /api/learning/stats failed (status=%s): %s — using local log fallback", e.status_code, e)
            # else: pass (e.g. no local log yet)
    if not knowledge.get("by_keyword"):
        try:
            log_path = get_log_path(config)
            report = aggregate_log(log_path)
            knowledge["by_keyword"] = {
                k: {"count": v.get("count", 0), "mean_motion_level": v.get("mean_motion_level", 0), "mean_brightness": v.get("mean_brightness", 0)}
                for k, v in report.by_keyword.items()
            }
            knowledge["by_palette"] = {
                k: {"count": v.get("count", 0), "mean_motion_level": v.get("mean_motion_level", 0), "mean_brightness": v.get("mean_brightness", 0)}
                for k, v in report.by_palette.items()
            }
            knowledge["overall"] = report.overall
        except Exception:
            knowledge.setdefault("by_keyword", {})
            knowledge.setdefault("by_palette", {})
            knowledge.setdefault("overall", {})

    # Learned colors, motion, and audio: prefer API when api_base set, else local
    if base:
        try:
            from ..api_client import api_request_with_retry
            data = api_request_with_retry(base, "GET", "/api/knowledge/for-creation", timeout=15)
            knowledge["learned_colors"] = data.get("learned_colors", {})
            knowledge["learned_motion"] = data.get("learned_motion", [])
            knowledge["learned_audio"] = data.get("learned_audio", [])
            knowledge["learned_gradient"] = data.get("learned_gradient", [])
            knowledge["learned_camera"] = data.get("learned_camera", [])
            knowledge["origin_gradient"] = data.get("origin_gradient", [])
            knowledge["origin_camera"] = data.get("origin_camera", [])
            knowledge["origin_motion"] = data.get("origin_motion", [])
        except Exception as e:
            from ..api_client import APIError
            if isinstance(e, APIError):
                logger.warning("GET /api/knowledge/for-creation failed (status=%s): %s — using local registries", e.status_code, e)
            knowledge["learned_colors"] = {}
            knowledge["learned_motion"] = []
            knowledge["learned_audio"] = []
            knowledge["learned_gradient"] = []
            knowledge["learned_camera"] = []
            knowledge["origin_gradient"] = []
            knowledge["origin_camera"] = []
            knowledge["origin_motion"] = []
    if not knowledge.get("learned_colors"):
        try:
            learned_colors = load_registry("learned_colors", config)
            knowledge["learned_colors"] = learned_colors.get("colors", {})
        except Exception:
            knowledge["learned_colors"] = {}
    if not knowledge.get("learned_motion"):
        try:
            learned_motion = load_registry("learned_motion", config)
            knowledge["learned_motion"] = learned_motion.get("profiles", [])
        except Exception:
            knowledge["learned_motion"] = []
    if "learned_audio" not in knowledge:
        knowledge["learned_audio"] = []
    if "learned_gradient" not in knowledge:
        knowledge["learned_gradient"] = []
    if "learned_camera" not in knowledge:
        knowledge["learned_camera"] = []
    if "origin_gradient" not in knowledge:
        knowledge["origin_gradient"] = []
    if "origin_camera" not in knowledge:
        knowledge["origin_camera"] = []
    if "origin_motion" not in knowledge:
        knowledge["origin_motion"] = []

    return knowledge

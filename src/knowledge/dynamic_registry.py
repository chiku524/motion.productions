"""
Dynamic registry: combined frames = one instance.
Holds lenient non-pure blends (time-bound): time, motion, audio_semantic, lighting,
composition, graphics, temporal, technical. Successful single-value blends go to STATIC.
Registries are 100% accurate; precise algorithms/functions live in scripts & code.
See docs/REGISTRIES.md.
"""
from pathlib import Path
from typing import Any

# All categories in the DYNAMIC registry (per combined-frames window).
# Covers every aspect of an MP4 that is time-bound / non-pure. Single-value blends → STATIC.
DYNAMIC_ASPECTS = [
    {"id": "time", "description": "Time (duration, rate, sync) over the window.", "sub_aspects": ["duration", "rate", "sync"]},
    {"id": "motion", "description": "Motion (speed, direction, rhythm) over the window.", "sub_aspects": ["speed", "direction", "rhythm", "trend"]},
    {"id": "gradient", "description": "Gradient type and strength over the window.", "sub_aspects": ["gradient_type", "strength"]},
    {"id": "camera", "description": "Camera motion (static, pan, tilt, zoom, dolly) over the window.", "sub_aspects": ["motion_type", "speed", "steadiness"]},
    {"id": "audio_semantic", "description": "Semantic audio (role, mood, tempo, presence) — non-pure blends from spec/usage.", "sub_aspects": ["role", "mood", "tempo", "presence", "melody", "dialogue", "sfx"]},
    {"id": "lighting", "description": "Lighting (brightness, contrast, saturation) over the window — not static.", "sub_aspects": ["brightness", "contrast", "saturation", "key_intensity", "color_temperature"]},
    {"id": "composition", "description": "Composition (center of mass, balance, framing) over the window.", "sub_aspects": ["center_of_mass", "balance", "luminance_balance", "framing"]},
    {"id": "graphics", "description": "Graphics (edge density, spatial variance, busyness, shape) over the window.", "sub_aspects": ["edge_density", "spatial_variance", "busyness", "shape_overlay"]},
    {"id": "temporal", "description": "Temporal (pacing, cut frequency, shot length, motion trend) over the window.", "sub_aspects": ["pacing", "motion_trend", "cut_frequency", "shot_length"]},
    {"id": "technical", "description": "Technical (resolution, fps, aspect) for the window.", "sub_aspects": ["width", "height", "fps", "aspect_ratio"]},
    {"id": "transition", "description": "Transition type (cut, fade, dissolve, wipe) between segments.", "sub_aspects": ["type", "duration"]},
    {"id": "depth", "description": "Depth/realism (parallax, layers) over the window.", "sub_aspects": ["parallax_strength", "layer_count"]},
]

DYNAMIC_REGISTRY_FILES = {
    a["id"]: f"dynamic_{a['id']}.json" for a in DYNAMIC_ASPECTS
}


def get_dynamic_registry_dir(config: dict[str, Any] | None = None) -> Path:
    """Path to the dynamic registry directory (combined frames = one instance)."""
    from .registry import get_registry_dir
    return get_registry_dir(config) / "dynamic"


def dynamic_registry_path(config: dict[str, Any] | None, aspect: str) -> Path:
    """Path to the JSON file for a dynamic aspect."""
    fname = DYNAMIC_REGISTRY_FILES.get(aspect, f"dynamic_{aspect}.json")
    return get_dynamic_registry_dir(config) / fname


def load_dynamic_registry(aspect: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load dynamic registry for one aspect."""
    path = dynamic_registry_path(config, aspect)
    if not path.exists():
        return _empty_dynamic_registry(aspect)
    try:
        with open(path, encoding="utf-8") as f:
            import json
            return json.load(f)
    except (Exception, OSError):
        return _empty_dynamic_registry(aspect)


def save_dynamic_registry(aspect: str, data: dict[str, Any], config: dict[str, Any] | None = None) -> Path:
    """Save dynamic registry with human-readable structure."""
    from .registry import get_registry_dir
    get_registry_dir(config).mkdir(parents=True, exist_ok=True)
    dynamic_dir = get_dynamic_registry_dir(config)
    dynamic_dir.mkdir(parents=True, exist_ok=True)
    path = dynamic_registry_path(config, aspect)
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def _empty_dynamic_registry(aspect: str) -> dict[str, Any]:
    """Empty dynamic registry structure for readers."""
    info = next((a for a in DYNAMIC_ASPECTS if a["id"] == aspect), {"id": aspect, "description": "", "sub_aspects": []})
    return {
        "_meta": {
            "registry": "dynamic",
            "goal": "Record every instance of dynamic elements over combined frames (e.g. 1 second).",
            "aspect": aspect,
            "description": info.get("description", ""),
            "sub_aspects": info.get("sub_aspects", []),
        },
        "entries": [],
        "count": 0,
    }


# Default window size for "combined frames" (seconds)
DEFAULT_DYNAMIC_WINDOW_SECONDS = 1.0

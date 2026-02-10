"""
Static registry: one frame = one instance.
Pure elements only: COLOR and SOUND. Every pixel = color; every sample = sound.
Records every instance of color and sound per frame. Accuracy of recorded values
is paramount; extraction/growth use precise keys and metrics.
See docs/REGISTRY_TAXONOMY.md for the definitive category list.
"""
from pathlib import Path
from typing import Any

# All aspects recorded in the STATIC registry (per frame)
# Each aspect has: key used in JSON, short description for readers
STATIC_ASPECTS = [
    {
        "id": "color",
        "description": "Color at the pixel level (R, G, B, A; blending, opacity, chroma, luminance).",
        "sub_aspects": ["blending", "opacity", "chroma", "luminance", "hue", "saturation", "brightness", "contrast"],
    },
    {
        "id": "sound",
        "description": "Sound at the sample level (amplitude/weight; tone and timbre derived from sample runs).",
        "sub_aspects": ["weight", "tone", "timbre", "amplitude"],
    },
]

STATIC_REGISTRY_FILES = {
    "color": "static_colors.json",
    "sound": "static_sound.json",
}


def get_static_registry_dir(config: dict[str, Any] | None = None) -> Path:
    """Path to the static registry directory (one frame = one instance)."""
    from .registry import get_registry_dir
    return get_registry_dir(config) / "static"


def static_registry_path(config: dict[str, Any] | None, aspect: str) -> Path:
    """Path to the JSON file for a static aspect (e.g. color, sound)."""
    fname = STATIC_REGISTRY_FILES.get(aspect, f"static_{aspect}.json")
    return get_static_registry_dir(config) / fname


def load_static_registry(aspect: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load static registry for one aspect. Returns structure with _meta and aspect data."""
    path = static_registry_path(config, aspect)
    if not path.exists():
        return _empty_static_registry(aspect)
    try:
        with open(path, encoding="utf-8") as f:
            import json
            return json.load(f)
    except (Exception, OSError):
        return _empty_static_registry(aspect)


def save_static_registry(aspect: str, data: dict[str, Any], config: dict[str, Any] | None = None) -> Path:
    """Save static registry with human-readable structure."""
    from .registry import get_registry_dir
    get_registry_dir(config).mkdir(parents=True, exist_ok=True)
    static_dir = get_static_registry_dir(config)
    static_dir.mkdir(parents=True, exist_ok=True)
    path = static_registry_path(config, aspect)
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def _empty_static_registry(aspect: str) -> dict[str, Any]:
    """Empty static registry structure for readers."""
    info = next((a for a in STATIC_ASPECTS if a["id"] == aspect), {"id": aspect, "description": "", "sub_aspects": []})
    return {
        "_meta": {
            "registry": "static",
            "goal": "Record every instance of static elements (color, sound) per single frame.",
            "aspect": aspect,
            "description": info.get("description", ""),
            "sub_aspects": info.get("sub_aspects", []),
        },
        "entries": [],
        "count": 0,
    }

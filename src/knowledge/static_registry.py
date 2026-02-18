"""
Static registry: one frame = one instance.
Pure elements only — no categories like brightness/contrast/saturation (those live in DYNAMIC).
Static holds: (1) pure color (R, G, B, opacity), (2) pure sound (amplitude, tone, timbre at sample/beat level).
Pure blends are recorded with depth % = weights/densities of other pure elements.
Every primitive (origin) known is seeded so the loop can blend from them.
See docs/REGISTRIES.md.
"""
from pathlib import Path
from typing import Any

# -----------------------------------------------------------------------------
# COLOR PRIMITIVES — every pure color known (origin values). R, G, B, opacity only.
# Brightness/luminance/contrast/saturation are dynamic (per-window), not static.
# -----------------------------------------------------------------------------
def _rgb(r: int, g: int, b: int) -> dict[str, Any]:
    return {"r": r, "g": g, "b": b, "opacity": 1.0}


STATIC_COLOR_PRIMITIVES = [
    _rgb(0, 0, 0),           # black
    _rgb(255, 255, 255),     # white
    _rgb(255, 0, 0),         # red
    _rgb(0, 255, 0),         # green (lime)
    _rgb(0, 0, 255),         # blue
    _rgb(255, 255, 0),       # yellow
    _rgb(0, 255, 255),       # cyan / aqua
    _rgb(255, 0, 255),       # magenta / fuchsia
    _rgb(255, 165, 0),       # orange
    _rgb(128, 0, 128),       # purple
    _rgb(255, 192, 203),     # pink
    _rgb(75, 0, 130),        # indigo
    _rgb(238, 130, 238),     # violet
    _rgb(102, 51, 153),      # rebeccapurple
    _rgb(147, 112, 219),     # mediumpurple
    _rgb(218, 112, 214),     # orchid
    _rgb(255, 105, 180),     # hotpink
    _rgb(255, 20, 147),      # deeppink
    _rgb(199, 21, 133),      # mediumvioletred
    _rgb(255, 0, 255),       # fuchsia
    _rgb(128, 0, 0),         # maroon
    _rgb(139, 0, 0),         # darkred
    _rgb(220, 20, 60),       # crimson
    _rgb(178, 34, 34),       # firebrick
    _rgb(205, 92, 92),       # indianred
    _rgb(255, 99, 71),       # tomato
    _rgb(255, 69, 0),        # orangered
    _rgb(255, 127, 80),      # coral
    _rgb(255, 140, 0),       # darkorange
    _rgb(255, 215, 0),       # gold
    _rgb(184, 134, 11),      # darkgoldenrod
    _rgb(210, 180, 140),     # tan
    _rgb(139, 69, 19),       # saddlebrown
    _rgb(160, 82, 45),       # sienna
    _rgb(210, 105, 30),      # chocolate
    _rgb(205, 133, 63),      # peru
    _rgb(165, 42, 42),       # brown
    _rgb(128, 128, 0),       # olive
    _rgb(85, 107, 47),       # darkolivegreen
    _rgb(107, 142, 35),      # olivedrab
    _rgb(34, 139, 34),       # forestgreen
    _rgb(0, 128, 0),         # green
    _rgb(0, 255, 127),       # springgreen
    _rgb(46, 139, 87),       # seagreen
    _rgb(60, 179, 113),      # mediumseagreen
    _rgb(0, 206, 209),       # darkturquoise
    _rgb(0, 255, 255),       # aqua (cyan)
    _rgb(0, 191, 255),       # deepskyblue
    _rgb(30, 144, 255),      # dodgerblue
    _rgb(70, 130, 180),      # steelblue
    _rgb(0, 0, 128),         # navy
    _rgb(25, 25, 112),       # midnightblue
    _rgb(65, 105, 225),      # royalblue
    _rgb(106, 90, 205),      # slateblue
    _rgb(72, 61, 139),       # darkslateblue
    _rgb(230, 230, 250),     # lavender
    _rgb(216, 191, 216),     # thistle
    _rgb(221, 160, 221),     # plum
    _rgb(238, 232, 170),     # palegoldenrod
    _rgb(245, 245, 220),     # beige
    _rgb(255, 248, 220),     # cornsilk
    _rgb(255, 250, 205),     # lemonchiffon
    _rgb(255, 255, 224),     # lightyellow
    _rgb(240, 255, 240),     # honeydew
    _rgb(245, 255, 250),     # mintcream
    _rgb(240, 255, 255),     # azure
    _rgb(255, 250, 250),     # snow
    _rgb(245, 245, 245),     # whitesmoke
    _rgb(220, 220, 220),     # gainsboro
    _rgb(211, 211, 211),     # lightgray
    _rgb(169, 169, 169),     # darkgray
    _rgb(128, 128, 128),     # gray
    _rgb(105, 105, 105),     # dimgray
    _rgb(47, 79, 79),        # darkslategray
    _rgb(112, 128, 144),     # slategray
    _rgb(192, 192, 192),     # silver
]

# -----------------------------------------------------------------------------
# SOUND: origin primitives + mesh (registry).
# - Origin/primitive set = 4 types: silence, rumble, tone, hiss (used for depth %).
# - Discovered pure sound *values* are blends of these primitives; depth % = how much
#   each origin/primitive makes up the discovered value (always relevant for all discovered values).
# - The mesh = static_sound registry = primitives + discovered blends. New discoveries
#   are recorded with depth_breakdown = origin_noises (weights) so the mesh stays a
#   playground of combinable values. Kick, snare, melody, speech, etc. are Blended (dynamic).
# -----------------------------------------------------------------------------
# Noise names (pure primitives). Tone "low"|"mid"|"high" maps to rumble|tone|hiss.
STATIC_SOUND_NOISE_NAMES = ["silence", "rumble", "tone", "hiss"]


def _snd(noise: str, strength_pct: float, tone_measurement: str = "") -> dict[str, Any]:
    """One pure sound: noise name + strength (0-1). tone_measurement is for keying only."""
    return {
        "noise": noise,
        "strength_pct": strength_pct,
        "amplitude": strength_pct,
        "weight": strength_pct,
        "tone": tone_measurement or ("silent" if noise == "silence" else "mid"),
        "timbre": noise,
    }


# Minimal primitive set (origin values): silence + strength bands per noise (rumble/tone/hiss).
# These are seeded into the mesh; discovered blends (primitives combined for one instant)
# are added by the loop and recorded in the same registry.
STATIC_SOUND_PRIMITIVES = [
    _snd("silence", 0.0, "silent"),
    _snd("rumble", 0.25, "low"),
    _snd("rumble", 0.5, "low"),
    _snd("rumble", 0.75, "low"),
    _snd("tone", 0.25, "mid"),
    _snd("tone", 0.5, "mid"),
    _snd("tone", 0.75, "mid"),
    _snd("hiss", 0.25, "high"),
    _snd("hiss", 0.5, "high"),
    _snd("hiss", 0.75, "high"),
]

# All aspects in STATIC: pure elements only. Depth % = weights of other pure elements (pure blends).
STATIC_ASPECTS = [
    {
        "id": "color",
        "description": "Pure color (R, G, B, opacity). Pure blends store depth_breakdown = weights of other pure colors.",
        "sub_aspects": ["r", "g", "b", "opacity", "depth_breakdown"],
    },
    {
        "id": "sound",
        "description": "Pure sound: origin/primitive values (silence, rumble, tone, hiss) plus mesh of discovered blends per instant. depth_breakdown = origin_noises (primitives blending together); new discoveries recorded in registry.",
        "sub_aspects": ["noise", "strength_pct", "amplitude", "tone", "timbre", "depth_breakdown"],
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



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
# Full set of CSS named colors (sRGB) so the loop can blend from all known-to-man primitives.
# Brightness/luminance/contrast/saturation are dynamic (per-window), not static.
# -----------------------------------------------------------------------------
def _rgb(r: int, g: int, b: int) -> dict[str, Any]:
    return {"r": r, "g": g, "b": b, "opacity": 1.0}


STATIC_COLOR_PRIMITIVES = [
    # Core 16 + extended CSS/SVG/X11 named colors (alphabetical for maintainability)
    _rgb(240, 248, 255),    # aliceblue
    _rgb(250, 235, 215),    # antiquewhite
    _rgb(0, 255, 255),      # aqua / cyan
    _rgb(127, 255, 212),    # aquamarine
    _rgb(240, 255, 255),    # azure
    _rgb(245, 245, 220),    # beige
    _rgb(255, 228, 196),    # bisque
    _rgb(0, 0, 0),          # black
    _rgb(255, 235, 205),    # blanchedalmond
    _rgb(0, 0, 255),        # blue
    _rgb(138, 43, 226),     # blueviolet
    _rgb(165, 42, 42),      # brown
    _rgb(222, 184, 135),    # burlywood
    _rgb(95, 158, 160),     # cadetblue
    _rgb(127, 255, 0),      # chartreuse
    _rgb(210, 105, 30),     # chocolate
    _rgb(255, 127, 80),     # coral
    _rgb(100, 149, 237),    # cornflowerblue
    _rgb(255, 248, 220),    # cornsilk
    _rgb(220, 20, 60),      # crimson
    _rgb(0, 255, 255),      # cyan
    _rgb(0, 0, 139),        # darkblue
    _rgb(0, 139, 139),      # darkcyan
    _rgb(184, 134, 11),     # darkgoldenrod
    _rgb(169, 169, 169),    # darkgray / darkgrey
    _rgb(0, 100, 0),        # darkgreen
    _rgb(189, 183, 107),    # darkkhaki
    _rgb(139, 0, 139),      # darkmagenta
    _rgb(85, 107, 47),      # darkolivegreen
    _rgb(255, 140, 0),      # darkorange
    _rgb(153, 50, 204),     # darkorchid
    _rgb(139, 0, 0),        # darkred
    _rgb(233, 150, 122),    # darksalmon
    _rgb(143, 188, 143),    # darkseagreen
    _rgb(72, 61, 139),      # darkslateblue
    _rgb(47, 79, 79),       # darkslategray / darkslategrey
    _rgb(0, 206, 209),      # darkturquoise
    _rgb(148, 0, 211),      # darkviolet
    _rgb(255, 20, 147),     # deeppink
    _rgb(0, 191, 255),      # deepskyblue
    _rgb(105, 105, 105),    # dimgray / dimgrey
    _rgb(30, 144, 255),     # dodgerblue
    _rgb(178, 34, 34),      # firebrick
    _rgb(255, 250, 240),    # floralwhite
    _rgb(34, 139, 34),      # forestgreen
    _rgb(255, 0, 255),      # fuchsia / magenta
    _rgb(220, 220, 220),    # gainsboro
    _rgb(248, 248, 255),    # ghostwhite
    _rgb(255, 215, 0),      # gold
    _rgb(218, 165, 32),     # goldenrod
    _rgb(0, 128, 0),        # green
    _rgb(173, 255, 47),     # greenyellow
    _rgb(128, 128, 128),    # gray / grey
    _rgb(240, 255, 240),    # honeydew
    _rgb(255, 105, 180),    # hotpink
    _rgb(205, 92, 92),      # indianred
    _rgb(75, 0, 130),       # indigo
    _rgb(255, 255, 240),    # ivory
    _rgb(240, 230, 140),    # khaki
    _rgb(230, 230, 250),    # lavender
    _rgb(255, 240, 245),    # lavenderblush
    _rgb(124, 252, 0),      # lawngreen
    _rgb(255, 250, 205),    # lemonchiffon
    _rgb(173, 216, 230),    # lightblue
    _rgb(240, 128, 128),    # lightcoral
    _rgb(224, 255, 255),    # lightcyan
    _rgb(250, 250, 210),    # lightgoldenrodyellow
    _rgb(211, 211, 211),    # lightgray / lightgrey
    _rgb(144, 238, 144),    # lightgreen
    _rgb(255, 182, 193),    # lightpink
    _rgb(255, 160, 122),    # lightsalmon
    _rgb(32, 178, 170),     # lightseagreen
    _rgb(135, 206, 250),    # lightskyblue
    _rgb(119, 136, 153),    # lightslategray / lightslategrey
    _rgb(176, 196, 222),    # lightsteelblue
    _rgb(255, 255, 224),    # lightyellow
    _rgb(0, 255, 0),        # lime
    _rgb(50, 205, 50),      # limegreen
    _rgb(250, 240, 230),    # linen
    _rgb(255, 0, 255),      # magenta
    _rgb(128, 0, 0),       # maroon
    _rgb(102, 205, 170),    # mediumaquamarine
    _rgb(0, 0, 205),       # mediumblue
    _rgb(186, 85, 211),     # mediumorchid
    _rgb(147, 112, 219),    # mediumpurple
    _rgb(60, 179, 113),     # mediumseagreen
    _rgb(123, 104, 238),    # mediumslateblue
    _rgb(0, 250, 154),      # mediumspringgreen
    _rgb(72, 209, 204),     # mediumturquoise
    _rgb(199, 21, 133),     # mediumvioletred
    _rgb(25, 25, 112),      # midnightblue
    _rgb(245, 255, 250),    # mintcream
    _rgb(255, 228, 225),    # mistyrose
    _rgb(255, 228, 181),    # moccasin
    _rgb(255, 222, 173),    # navajowhite
    _rgb(0, 0, 128),        # navy
    _rgb(253, 245, 230),    # oldlace
    _rgb(128, 128, 0),      # olive
    _rgb(107, 142, 35),     # olivedrab
    _rgb(255, 165, 0),      # orange
    _rgb(255, 69, 0),       # orangered
    _rgb(218, 112, 214),    # orchid
    _rgb(238, 232, 170),    # palegoldenrod
    _rgb(152, 251, 152),    # palegreen
    _rgb(175, 238, 238),    # paleturquoise
    _rgb(219, 112, 147),    # palevioletred
    _rgb(255, 239, 213),    # papayawhip
    _rgb(255, 218, 185),    # peachpuff
    _rgb(205, 133, 63),     # peru
    _rgb(255, 192, 203),    # pink
    _rgb(221, 160, 221),    # plum
    _rgb(176, 224, 230),    # powderblue
    _rgb(128, 0, 128),      # purple
    _rgb(102, 51, 153),     # rebeccapurple
    _rgb(255, 0, 0),        # red
    _rgb(188, 143, 143),    # rosybrown
    _rgb(65, 105, 225),     # royalblue
    _rgb(139, 69, 19),      # saddlebrown
    _rgb(250, 128, 114),    # salmon
    _rgb(244, 164, 96),     # sandybrown
    _rgb(46, 139, 87),      # seagreen
    _rgb(255, 245, 238),    # seashell
    _rgb(160, 82, 45),      # sienna
    _rgb(192, 192, 192),    # silver
    _rgb(135, 206, 235),    # skyblue
    _rgb(106, 90, 205),     # slateblue
    _rgb(112, 128, 144),    # slategray / slategrey
    _rgb(255, 250, 250),    # snow
    _rgb(0, 255, 127),      # springgreen
    _rgb(70, 130, 180),     # steelblue
    _rgb(210, 180, 140),    # tan
    _rgb(0, 128, 128),      # teal
    _rgb(216, 191, 216),    # thistle
    _rgb(255, 99, 71),      # tomato
    _rgb(64, 224, 208),     # turquoise
    _rgb(238, 130, 238),    # violet
    _rgb(245, 222, 179),    # wheat
    _rgb(255, 255, 255),    # white
    _rgb(245, 245, 245),    # whitesmoke
    _rgb(255, 255, 0),      # yellow
    _rgb(154, 205, 50),     # yellowgreen
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
# Full coverage: silence plus 0.1–0.9 step 0.1 for each of rumble, tone, hiss (known-to-man pure sounds).
STATIC_SOUND_PRIMITIVES = [
    _snd("silence", 0.0, "silent"),
]
for noise in ("rumble", "tone", "hiss"):
    tone_measurement = "low" if noise == "rumble" else ("mid" if noise == "tone" else "high")
    for pct in (0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9):
        STATIC_SOUND_PRIMITIVES.append(_snd(noise, pct, tone_measurement))

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



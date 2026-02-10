"""
Blending: combine primitives to produce new values.
Supports every primitive domain and multiple blending approaches.
When primitives are blended, the result may be novel and added to learned knowledge.
"""
from typing import Any, Literal

BlendApproach = Literal["linear", "average", "dominant", "geometric", "additive", "min_max", "alternating"]


# -----------------------------------------------------------------------------
# Approach 1: LINEAR — weighted interpolation (default)
# -----------------------------------------------------------------------------
def _blend_linear(a: float, b: float, weight: float) -> float:
    return a * (1 - weight) + b * weight


# -----------------------------------------------------------------------------
# Approach 2: AVERAGE — equal contribution
# -----------------------------------------------------------------------------
def _blend_average(a: float, b: float, _weight: float) -> float:
    return (a + b) / 2.0


# -----------------------------------------------------------------------------
# Approach 3: DOMINANT — pick one based on threshold
# -----------------------------------------------------------------------------
def _blend_dominant(a: float, b: float, weight: float) -> float:
    return b if weight >= 0.5 else a


# -----------------------------------------------------------------------------
# Approach 4: GEOMETRIC — sqrt(a*b) for numeric
# -----------------------------------------------------------------------------
def _blend_geometric(a: float, b: float, _weight: float) -> float:
    import math
    return math.sqrt(max(0, a) * max(0, b))


# -----------------------------------------------------------------------------
# Approach 5: ADDITIVE — sum with clamp
# -----------------------------------------------------------------------------
def _blend_additive(a: float, b: float, _weight: float) -> float:
    return min(1.0, max(0.0, (a + b) / 2.0))


# -----------------------------------------------------------------------------
# Approach 6: MIN_MAX — take min or max
# -----------------------------------------------------------------------------
def _blend_min_max(a: float, b: float, weight: float) -> float:
    return max(a, b) if weight >= 0.5 else min(a, b)


# -----------------------------------------------------------------------------
# Approach 7: ALTERNATING — per-dimension alternate
# -----------------------------------------------------------------------------
def _blend_alternating(a: float, b: float, weight: float) -> float:
    return b if weight > 0.66 else (a if weight < 0.33 else (a + b) / 2)


def _numeric_blend(a: float, b: float, weight: float, approach: BlendApproach) -> float:
    """Apply blending approach to two numeric values."""
    f = {
        "linear": _blend_linear,
        "average": _blend_average,
        "dominant": _blend_dominant,
        "geometric": _blend_geometric,
        "additive": _blend_additive,
        "min_max": _blend_min_max,
        "alternating": _blend_alternating,
    }.get(approach, _blend_linear)
    return f(a, b, weight)


def _ordinal_blend(
    items: list[str],
    idx_a: int,
    idx_b: int,
    weight: float,
    approach: BlendApproach,
) -> str:
    """Blend two ordinal (categorical) values by interpolating index."""
    n = len(items)
    if n == 0:
        return items[0] if items else ""
    ia = max(0, min(idx_a, n - 1))
    ib = max(0, min(idx_b, n - 1))
    if approach == "dominant":
        idx = ib if weight >= 0.5 else ia
    elif approach == "min_max":
        idx = max(ia, ib) if weight >= 0.5 else min(ia, ib)
    else:
        idx = int(ia * (1 - weight) + ib * weight + 0.5)
    return items[max(0, min(idx, n - 1))]


# =============================================================================
# COLOR
# =============================================================================
def blend_colors(
    rgb_a: tuple[float, float, float],
    rgb_b: tuple[float, float, float],
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> tuple[int, int, int]:
    """Blend two RGB colors."""
    r = _numeric_blend(rgb_a[0], rgb_b[0], weight, approach)
    g = _numeric_blend(rgb_a[1], rgb_b[1], weight, approach)
    b = _numeric_blend(rgb_a[2], rgb_b[2], weight, approach)
    return (
        max(0, min(255, int(r))),
        max(0, min(255, int(g))),
        max(0, min(255, int(b))),
    )


def blend_palettes(
    palette_a: list[tuple[int, int, int]],
    palette_b: list[tuple[int, int, int]],
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> list[tuple[int, int, int]]:
    """Blend two palettes color-by-color."""
    n = max(len(palette_a), len(palette_b))
    result = []
    for i in range(n):
        ca = palette_a[i % len(palette_a)] if palette_a else (128, 128, 128)
        cb = palette_b[i % len(palette_b)] if palette_b else (128, 128, 128)
        result.append(blend_colors(ca, cb, weight=weight, approach=approach))
    return result


# =============================================================================
# MOTION
# =============================================================================
def blend_motion_params(
    speed_a: str,
    speed_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend two motion speeds."""
    order = ["static", "slow", "medium", "fast"]
    ia = order.index(speed_a) if speed_a in order else 1
    ib = order.index(speed_b) if speed_b in order else 1
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_smoothness(
    a: str,
    b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend motion smoothness (jerky, rough, smooth, fluid)."""
    order = ["jerky", "rough", "smooth", "fluid"]
    ia = order.index(a) if a in order else 2
    ib = order.index(b) if b in order else 2
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_directionality(
    a: str,
    b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend motion directionality (none, horizontal, vertical, diagonal, radial)."""
    order = ["none", "horizontal", "vertical", "diagonal", "radial"]
    ia = order.index(a) if a in order else 0
    ib = order.index(b) if b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_rhythm(
    a: str,
    b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend motion rhythm (steady, pulsing, wave, random)."""
    order = ["steady", "pulsing", "wave", "random"]
    ia = order.index(a) if a in order else 0
    ib = order.index(b) if b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_acceleration(
    a: str,
    b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend motion acceleration (constant, ease_in, ease_out, ease_in_out)."""
    order = ["constant", "ease_in", "ease_out", "ease_in_out"]
    ia = order.index(a) if a in order else 0
    ib = order.index(b) if b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_intensity(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend two intensity values (0-1)."""
    return max(0.0, min(1.0, _numeric_blend(a, b, weight, approach)))


# =============================================================================
# LIGHTING
# =============================================================================
def blend_key_intensity(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend key intensity (0.5-1.25)."""
    return max(0.5, min(1.25, _numeric_blend(a, b, weight, approach)))


def blend_fill_ratio(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend fill ratio (0.2-0.8)."""
    return max(0.2, min(0.8, _numeric_blend(a, b, weight, approach)))


def blend_rim_strength(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend rim strength (0-0.8)."""
    return max(0.0, min(0.8, _numeric_blend(a, b, weight, approach)))


def blend_ambient_level(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend ambient level (0.2-0.8)."""
    return max(0.2, min(0.8, _numeric_blend(a, b, weight, approach)))


def blend_color_temperature(
    a: str,
    b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend color temperature (warm, neutral, cool)."""
    order = ["warm", "neutral", "cool"]
    ia = order.index(a) if a in order else 1
    ib = order.index(b) if b in order else 1
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_contrast_ratio(
    a: str,
    b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend contrast ratio (flat, normal, high, chiaroscuro)."""
    order = ["flat", "normal", "high", "chiaroscuro"]
    ia = order.index(a) if a in order else 1
    ib = order.index(b) if b in order else 1
    return _ordinal_blend(order, ia, ib, weight, approach)


# Order of lighting preset names for ordinal blending
_LIGHTING_PRESET_ORDER = ["neutral", "documentary", "noir", "golden_hour", "neon", "moody"]


def blend_lighting_preset_names(
    preset_a: str,
    preset_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend two lighting preset names → single preset name (primitive-level)."""
    ia = _LIGHTING_PRESET_ORDER.index(preset_a) if preset_a in _LIGHTING_PRESET_ORDER else 0
    ib = _LIGHTING_PRESET_ORDER.index(preset_b) if preset_b in _LIGHTING_PRESET_ORDER else 0
    return _ordinal_blend(_LIGHTING_PRESET_ORDER, ia, ib, weight, approach)


def blend_lighting_presets(
    preset_a: str,
    preset_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
    presets: dict[str, tuple[float, ...]] | None = None,
) -> tuple[float, float, float, float, float]:
    """Blend two lighting presets (contrast, saturation, lift, gamma, gain)."""
    if presets is None:
        from ..lighting.grading import LIGHTING_PRESETS
        presets = LIGHTING_PRESETS
    pa = presets.get(preset_a, (1.0, 1.0, 0.0, 1.0, 1.0))
    pb = presets.get(preset_b, (1.0, 1.0, 0.0, 1.0, 1.0))
    return tuple(
        _numeric_blend(pa[i], pb[i], weight, approach)
        for i in range(5)
    )


# =============================================================================
# CAMERA
# =============================================================================
def blend_camera(
    motion_a: str,
    motion_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend camera motion types."""
    order = ["static", "pan", "tilt", "dolly", "crane", "zoom", "zoom_out", "handheld"]
    ia = order.index(motion_a) if motion_a in order else 0
    ib = order.index(motion_b) if motion_b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_camera_speed(speed_a: str, speed_b: str, weight: float = 0.5, approach: BlendApproach = "linear") -> str:
    """Blend camera speed (slow, medium, fast)."""
    order = ["slow", "medium", "fast"]
    ia = order.index(speed_a) if speed_a in order else 1
    ib = order.index(speed_b) if speed_b in order else 1
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_steadiness(
    a: str,
    b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend camera steadiness (locked, stable, handheld, shaky)."""
    order = ["locked", "stable", "handheld", "shaky"]
    ia = order.index(a) if a in order else 1
    ib = order.index(b) if b in order else 1
    return _ordinal_blend(order, ia, ib, weight, approach)


# =============================================================================
# COMPOSITION
# =============================================================================
def blend_framing(
    frame_a: str,
    frame_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend shot framing (wide, medium, close, etc.)."""
    order = ["wide", "medium", "close", "extreme_close", "pov"]
    ia = order.index(frame_a) if frame_a in order else 1
    ib = order.index(frame_b) if frame_b in order else 1
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_balance(
    bal_a: str,
    bal_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend composition balance."""
    order = ["left_heavy", "balanced", "right_heavy", "top_heavy", "bottom_heavy"]
    ia = order.index(bal_a) if bal_a in order else 1
    ib = order.index(bal_b) if bal_b in order else 1
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_symmetry(
    a: str,
    b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend composition symmetry (asymmetric, slight, bilateral)."""
    order = ["asymmetric", "slight", "bilateral"]
    ia = order.index(a) if a in order else 0
    ib = order.index(b) if b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


# =============================================================================
# TEMPORAL
# =============================================================================
def blend_pacing(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend pacing values."""
    return max(0.3, min(2.0, _numeric_blend(a, b, weight, approach)))


def blend_cut_frequency(
    freq_a: str,
    freq_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend cut frequency."""
    order = ["none", "rare", "normal", "fast", "rapid"]
    ia = order.index(freq_a) if freq_a in order else 2
    ib = order.index(freq_b) if freq_b in order else 2
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_shot_length(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend shot length in seconds."""
    return max(1.0, _numeric_blend(a, b, weight, approach))


def blend_story_beat(
    beat_a: str,
    beat_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend story beat phase."""
    order = ["setup", "development", "climax", "resolution"]
    ia = order.index(beat_a) if beat_a in order else 0
    ib = order.index(beat_b) if beat_b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


# =============================================================================
# TRANSITIONS
# =============================================================================
def blend_transition_type(
    type_a: str,
    type_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend transition type (cut, fade, dissolve, wipe)."""
    order = ["cut", "fade", "dissolve", "wipe"]
    ia = order.index(type_a) if type_a in order else 0
    ib = order.index(type_b) if type_b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_transition_duration(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend transition duration in seconds."""
    return max(0.0, _numeric_blend(a, b, weight, approach))


# =============================================================================
# GRAPHICS
# =============================================================================
def blend_gradient_type(
    grad_a: str,
    grad_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend gradient type."""
    order = ["vertical", "horizontal", "radial", "angled"]
    ia = order.index(grad_a) if grad_a in order else 0
    ib = order.index(grad_b) if grad_b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_shape_overlay(
    shape_a: str,
    shape_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "dominant",
) -> str:
    """Blend shape overlay (none, circle, rect)."""
    order = ["none", "circle", "rect"]
    ia = order.index(shape_a) if shape_a in order else 0
    ib = order.index(shape_b) if shape_b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_edge_density(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend edge density (0-1)."""
    return max(0.0, min(1.0, _numeric_blend(a, b, weight, approach)))


def blend_spatial_variance(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend spatial variance (0-1)."""
    return max(0.0, min(1.0, _numeric_blend(a, b, weight, approach)))


def blend_busyness(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend busyness (0-1)."""
    return max(0.0, min(1.0, _numeric_blend(a, b, weight, approach)))


# =============================================================================
# AUDIO
# =============================================================================
def blend_audio_tempo(
    tempo_a: str,
    tempo_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend audio tempo."""
    order = ["slow", "medium", "fast"]
    ia = order.index(tempo_a) if tempo_a in order else 1
    ib = order.index(tempo_b) if tempo_b in order else 1
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_audio_mood(
    mood_a: str,
    mood_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend audio mood."""
    order = ["neutral", "calm", "tense", "uplifting", "dark"]
    ia = order.index(mood_a) if mood_a in order else 0
    ib = order.index(mood_b) if mood_b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_audio_intensity(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend audio intensity (0-1)."""
    return max(0.0, min(1.0, _numeric_blend(a, b, weight, approach)))


def blend_audio_presence(
    a: str,
    b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend audio presence (silence, ambient, music, sfx, full)."""
    order = ["silence", "ambient", "music", "sfx", "full"]
    ia = order.index(a) if a in order else 2
    ib = order.index(b) if b in order else 2
    return _ordinal_blend(order, ia, ib, weight, approach)


# =============================================================================
# NARRATIVE
# =============================================================================
def blend_genre(
    genre_a: str,
    genre_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend genre."""
    order = ["general", "documentary", "thriller", "ad", "tutorial", "educational", "explainer"]
    ia = order.index(genre_a) if genre_a in order else 0
    ib = order.index(genre_b) if genre_b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_tone(
    tone_a: str,
    tone_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend tone."""
    order = ["neutral", "dreamy", "dark", "bright", "calm", "energetic", "moody"]
    ia = order.index(tone_a) if tone_a in order else 0
    ib = order.index(tone_b) if tone_b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_tension_curve(
    curve_a: str,
    curve_b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend tension curve."""
    order = ["flat", "slow_build", "standard", "immediate"]
    ia = order.index(curve_a) if curve_a in order else 2
    ib = order.index(curve_b) if curve_b in order else 2
    return _ordinal_blend(order, ia, ib, weight, approach)


def blend_style(
    a: str,
    b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend narrative style (cinematic, abstract, minimal, realistic, anime)."""
    order = ["cinematic", "abstract", "minimal", "realistic", "anime"]
    ia = order.index(a) if a in order else 0
    ib = order.index(b) if b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


# =============================================================================
# TECHNICAL
# =============================================================================
def blend_resolution(
    res_a: tuple[int, int],
    res_b: tuple[int, int],
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> tuple[int, int]:
    """Blend resolution (pick one or interpolate dimensions)."""
    if approach == "dominant":
        return res_b if weight >= 0.5 else res_a
    w = int(res_a[0] * (1 - weight) + res_b[0] * weight)
    h = int(res_a[1] * (1 - weight) + res_b[1] * weight)
    # Snap to common values
    common = [(256, 256), (512, 512), (720, 480), (1280, 720), (1920, 1080)]
    best = min(common, key=lambda c: abs(c[0] - w) + abs(c[1] - h))
    return best


def blend_fps(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend frame rate."""
    v = _numeric_blend(a, b, weight, approach)
    for fps in [12, 24, 30, 60]:
        if abs(v - fps) < 6:
            return float(fps)
    return max(12, min(60, round(v)))


def blend_aspect_ratio(
    a: str,
    b: str,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> str:
    """Blend aspect ratio (1:1, 16:9, 4:3, 9:16)."""
    order = ["1:1", "16:9", "4:3", "9:16"]
    ia = order.index(a) if a in order else 0
    ib = order.index(b) if b in order else 0
    return _ordinal_blend(order, ia, ib, weight, approach)


# =============================================================================
# DEPTH
# =============================================================================
def blend_parallax_strength(
    a: float,
    b: float,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> float:
    """Blend parallax strength."""
    return max(0.0, min(0.5, _numeric_blend(a, b, weight, approach)))


def blend_layer_count(
    a: int,
    b: int,
    *,
    weight: float = 0.5,
    approach: BlendApproach = "linear",
) -> int:
    """Blend layer count (1-4)."""
    v = _numeric_blend(float(a), float(b), weight, approach)
    return max(1, min(4, int(round(v))))


# -----------------------------------------------------------------------------
# BLENDING API — all primitives and approaches
# -----------------------------------------------------------------------------
BLEND_APPROACHES: tuple[BlendApproach, ...] = (
    "linear",
    "average",
    "dominant",
    "geometric",
    "additive",
    "min_max",
    "alternating",
)

# Map: domain -> (blend_func_name, description)
# Every origin primitive has a blend function.
BLEND_FUNCTIONS_BY_DOMAIN: dict[str, list[tuple[str, str]]] = {
    "color": [
        ("blend_colors", "Blend two RGB colors"),
        ("blend_palettes", "Blend two color palettes"),
    ],
    "motion": [
        ("blend_motion_params", "Blend motion speed (static/slow/medium/fast)"),
        ("blend_smoothness", "Blend motion smoothness (jerky/rough/smooth/fluid)"),
        ("blend_directionality", "Blend motion directionality (none/horizontal/vertical/diagonal/radial)"),
        ("blend_rhythm", "Blend motion rhythm (steady/pulsing/wave/random)"),
        ("blend_acceleration", "Blend motion acceleration (constant/ease_in/ease_out/ease_in_out)"),
        ("blend_intensity", "Blend intensity 0-1"),
    ],
    "lighting": [
        ("blend_key_intensity", "Blend key intensity 0.5-1.25"),
        ("blend_fill_ratio", "Blend fill ratio 0.2-0.8"),
        ("blend_rim_strength", "Blend rim strength 0-0.8"),
        ("blend_ambient_level", "Blend ambient level 0.2-0.8"),
        ("blend_color_temperature", "Blend color temperature (warm/neutral/cool)"),
        ("blend_contrast_ratio", "Blend contrast ratio (flat/normal/high/chiaroscuro)"),
        ("blend_lighting_presets", "Blend lighting presets (contrast, saturation, etc.)"),
    ],
    "camera": [
        ("blend_camera", "Blend camera motion type"),
        ("blend_camera_speed", "Blend camera speed"),
        ("blend_steadiness", "Blend camera steadiness (locked/stable/handheld/shaky)"),
    ],
    "composition": [
        ("blend_framing", "Blend shot framing (wide/medium/close/etc.)"),
        ("blend_balance", "Blend composition balance"),
        ("blend_symmetry", "Blend composition symmetry (asymmetric/slight/bilateral)"),
    ],
    "temporal": [
        ("blend_pacing", "Blend pacing factor"),
        ("blend_cut_frequency", "Blend cut frequency (none/rare/normal/fast/rapid)"),
        ("blend_shot_length", "Blend shot length in seconds"),
        ("blend_story_beat", "Blend story beat phase (setup/development/climax/resolution)"),
    ],
    "transition": [
        ("blend_transition_type", "Blend transition type (cut/fade/dissolve/wipe)"),
        ("blend_transition_duration", "Blend transition duration"),
    ],
    "graphics": [
        ("blend_gradient_type", "Blend gradient type"),
        ("blend_shape_overlay", "Blend shape overlay (none/circle/rect)"),
        ("blend_edge_density", "Blend edge density 0-1"),
        ("blend_spatial_variance", "Blend spatial variance 0-1"),
        ("blend_busyness", "Blend busyness 0-1"),
    ],
    "audio": [
        ("blend_audio_tempo", "Blend audio tempo (slow/medium/fast)"),
        ("blend_audio_mood", "Blend audio mood (neutral/calm/tense/uplifting/dark)"),
        ("blend_audio_intensity", "Blend audio intensity 0-1"),
        ("blend_audio_presence", "Blend audio presence (silence/ambient/music/sfx/full)"),
    ],
    "narrative": [
        ("blend_genre", "Blend genre (general/documentary/thriller/etc.)"),
        ("blend_tone", "Blend tone (neutral/dreamy/dark/bright/etc.)"),
        ("blend_style", "Blend narrative style (cinematic/abstract/minimal/realistic/anime)"),
        ("blend_tension_curve", "Blend tension curve (flat/slow_build/standard/immediate)"),
    ],
    "technical": [
        ("blend_resolution", "Blend resolution (width, height)"),
        ("blend_fps", "Blend frame rate"),
        ("blend_aspect_ratio", "Blend aspect ratio (1:1/16:9/4:3/9:16)"),
    ],
    "depth": [
        ("blend_parallax_strength", "Blend parallax strength"),
        ("blend_layer_count", "Blend layer count (1-4)"),
    ],
}

"""
Look-matching algorithms for the procedural renderer.

Registries store *values*; this module turns those values into motion, framing,
and interpolation that read as the intended look instead of a linear RGB wash.
"""
from __future__ import annotations

# Rule of thirds / golden-section subject anchors (offset from frame center 0.5)
_THIRD = 1.0 / 3.0
_GOLDEN = 1.0 - (1.0 / 1.618033988749895)  # ≈ 0.382

_SHOT_COMP_SCALE: dict[str, float] = {
    "wide": 1.2,
    "establishing": 1.2,
    "extreme_wide": 1.35,
    "medium": 1.0,
    "close": 0.5,
    "close_up": 0.5,
    "extreme_close": 0.32,
    "extreme_closeup": 0.32,
    "pov": 0.65,
    "handheld": 0.9,
}


def ease_in(u: float) -> float:
    u = max(0.0, min(1.0, float(u)))
    return u * u


def ease_out(u: float) -> float:
    u = max(0.0, min(1.0, float(u)))
    return 1.0 - (1.0 - u) * (1.0 - u)


def ease_in_out(u: float) -> float:
    """Smoothstep 0→1."""
    u = max(0.0, min(1.0, float(u)))
    return u * u * (3.0 - 2.0 * u)


def ease_smoother(u: float) -> float:
    """Smootherstep — fluid motion."""
    u = max(0.0, min(1.0, float(u)))
    return u * u * u * (u * (u * 6.0 - 15.0) + 10.0)


def ease_back(u: float) -> float:
    """Slight overshoot (rough / organic)."""
    u = max(0.0, min(1.0, float(u)))
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * (u - 1.0) ** 3 + c1 * (u - 1.0) ** 2


def ease_unit(
    u: float,
    smoothness: str = "smooth",
    *,
    bounce: bool = False,
    falling: bool = False,
) -> float:
    """
    Map linear keyframe u∈[0,1] through motion_smoothness / bounce physics.

    bounce+falling → ease-in (gravity accelerate); bounce+rising → ease-out.
    jerky → stepped; fluid → smootherstep; rough → overshoot; else smoothstep.
    """
    u = max(0.0, min(1.0, float(u)))
    s = (smoothness or "smooth").strip().lower()
    if bounce:
        return ease_in(u) if falling else ease_out(u)
    if s == "jerky":
        return round(u * 5.0) / 5.0
    if s in ("fluid", "smooth"):
        return ease_smoother(u) if s == "fluid" else ease_in_out(u)
    if s == "rough":
        return ease_back(u)
    return ease_in_out(u)


def composition_offset(
    balance: str | None,
    shot_type: str | None = "medium",
) -> tuple[float, float]:
    """
    Screen-space (dx, dy) from composition_balance using rule-of-thirds anchors.

    Positive x = right, positive y = down. Close shots scale the offset down
    so the subject stays readable; wide shots push further onto the thirds.
    """
    b = (balance or "balanced").strip().lower().replace(" ", "_")
    anchors = {
        "left_heavy": (_THIRD - 0.5, 0.0),
        "right_heavy": (2.0 * _THIRD - 0.5, 0.0),
        "top_heavy": (0.0, _THIRD - 0.5),
        "bottom_heavy": (0.0, 2.0 * _THIRD - 0.5),
        "golden_left": (_GOLDEN - 0.5, 0.0),
        "golden_right": (1.0 - _GOLDEN - 0.5, 0.0),
        "balanced": (0.0, 0.0),
    }
    dx, dy = anchors.get(b, (0.0, 0.0))
    shot = (shot_type or "medium").strip().lower().replace(" ", "_")
    scale = _SHOT_COMP_SCALE.get(shot, 1.0)
    return dx * scale, dy * scale


def camera_for_subject_motion(
    entities: list[dict] | None,
    *,
    bounce_prefers_static: bool = True,
) -> str:
    """
    Cinematography default when the prompt never named a camera move.

    Walking left/right → tracking; toward/away → dolly; bounce/idle → static.
    Keeps subject motion readable instead of a random whip-pan/rotate.
    """
    trajs: list[str] = []
    bounce = False
    for ent in entities or []:
        if not isinstance(ent, dict) or ent.get("is_prop"):
            continue
        t = str(ent.get("trajectory") or "none").lower()
        if t not in ("", "none"):
            trajs.append(t)
        bounce = bounce or bool(ent.get("bounce"))
    if bounce and bounce_prefers_static:
        return "static"
    if "toward" in trajs or "away" in trajs:
        return "dolly"
    if any(t in ("left", "right") for t in trajs):
        return "tracking"
    return "static"


def primary_subject(layers: list[dict] | None) -> dict | None:
    """Foreground subject for tracking — skip setting scenery."""
    scored: list[tuple[int, int, dict]] = []
    for layer in layers or []:
        if not isinstance(layer, dict):
            continue
        kind = str(layer.get("kind") or "")
        if kind in ("tree", "cloud", "building", "wave"):
            continue
        lid = str(layer.get("id") or "")
        prompt_ent = 0 if lid.startswith("prop_") else 1
        z = int(layer.get("z") or 0)
        scored.append((prompt_ent, z, layer))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]


def tracking_pan_x(subject_x: float) -> float:
    """
    Camera pan so scene coordinate subject_x samples at screen center.

    Inverse of `_apply_camera_transform` pan: pixel 0.5 looks up `0.5 + pan_x`.
    """
    return float(subject_x) - 0.5

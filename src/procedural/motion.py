"""
Motion curves and time-based functions. Our algorithms only — no external model.
Used by the renderer to drive movement over time.
"""
import math
from typing import Callable


from .look import ease_in_out


def wave(t: float, freq: float = 1.0, phase: float = 0.0) -> float:
    """Sinusoidal wave, output in [-1, 1]."""
    return math.sin(2 * math.pi * freq * t + phase)


def flow(t: float, speed: float = 0.5) -> float:
    """Slow drift (bounded)."""
    return (t * speed) % 1.0


def pulse(t: float, freq: float = 0.5) -> float:
    """Pulsing 0–1."""
    return 0.5 + 0.5 * math.sin(2 * math.pi * freq * t)


def get_motion_func(motion_type: str) -> Callable[[float], float]:
    """Legacy label → numeric recipe. Prefer motion_recipe_value when level is known."""
    level, rhythm = _label_to_level_rhythm(motion_type)
    return lambda t: motion_recipe_value(t, level=level, rhythm=rhythm)


def _label_to_level_rhythm(motion_type: str) -> tuple[float, str]:
    t = (motion_type or "flow").strip().lower()
    if t == "slow":
        return 3.0, "steady"
    if t == "wave":
        return 8.0, "wave"
    if t == "fast":
        return 18.0, "steady"
    if t == "pulse":
        return 10.0, "pulsing"
    return 6.0, "steady"


def label_from_motion_level(level: float, rhythm: str = "steady") -> str:
    """Display label derived from numeric recipe (not a closed catalog the renderer switches on)."""
    r = (rhythm or "steady").strip().lower()
    if r == "pulsing":
        return "pulse"
    if r == "wave":
        return "wave"
    lv = float(level)
    if lv < 4.0:
        return "slow"
    if lv >= 16.0:
        return "fast"
    return "flow"


def motion_recipe_value(
    t: float,
    *,
    level: float = 8.0,
    std: float = 0.0,
    rhythm: str = "steady",
    smoothness: str = "smooth",
) -> float:
    """
    Continuous 0–1 motion value from a numeric recipe.

    level: extraction-scale 0–25 (higher = faster / larger).
    std: motion variance; adds wobble.
    rhythm / smoothness: MOTION_ORIGINS axes, interpolated rather than enum-switched.
    """
    lv = max(0.0, min(25.0, float(level)))
    speed = max(0.05, min(2.5, lv / 10.0))
    amp = max(0.15, min(1.0, lv / 20.0))
    wobble = max(0.0, min(0.35, float(std) / 40.0))
    r = (rhythm or "steady").strip().lower()
    if r == "pulsing":
        base = pulse(t, 0.3 + speed * 0.4)
    elif r == "wave":
        base = 0.5 + 0.5 * wave(t, 0.15 + speed * 0.12)
    elif r == "random":
        base = 0.5 + 0.5 * math.sin(t * (3.1 + speed) + math.sin(t * 11.0))
    else:
        drift = flow(t, 0.15 + speed * 0.1)
        sine = 0.5 + 0.5 * math.sin(2 * math.pi * speed * 0.15 * t)
        base = (1.0 - amp) * drift + amp * sine
    if wobble:
        base = base * (1.0 - wobble) + wobble * (0.5 + 0.5 * math.sin(t * 7.3 + float(std)))
    s = (smoothness or "smooth").strip().lower()
    if s == "jerky":
        base = round(base * 6) / 6.0
    elif s == "rough":
        base = round(base * 12) / 12.0
    return max(0.0, min(1.0, float(base)))


def directionality_offsets(
    directionality: str,
    motion_val: float,
    *,
    smoothness: str = "smooth",
) -> tuple[float, float]:
    """
    Map MOTION_ORIGINS.directionality + motion value → (dx, dy) drift in 0–1 space.
    Used to bias gradient sampling and layer motion.
    """
    d = (directionality or "none").lower()
    amp = 0.28
    if smoothness == "jerky":
        # Quantize motion for stepped feel
        motion_val = round(motion_val * 6) / 6.0
        amp = 0.32
    elif smoothness == "fluid":
        amp = 0.34
    elif smoothness == "rough":
        amp = 0.30

    if d == "horizontal":
        return motion_val * amp, 0.0
    if d == "vertical":
        return 0.0, motion_val * amp
    if d == "diagonal":
        return motion_val * amp * 0.7, motion_val * amp * 0.7
    if d == "radial":
        # Expand/contract feel via equal xy push from center (handled in gradient)
        return motion_val * amp * 0.5, motion_val * amp * 0.5
    return 0.0, 0.0


def get_camera_params(
    camera_motion: str, t: float
) -> tuple[float, float, float, float]:
    """
    Return (zoom_scale, pan_x, pan_y, rotate_rad) for camera motion.
    zoom_scale: 1 = no zoom; >1 = zoom in; <1 = zoom out
    pan_x, pan_y: offset in 0-1 normalized space
    rotate_rad: rotation in radians
    """
    if camera_motion == "static" or not camera_motion:
        return 1.0, 0.0, 0.0, 0.0
    if camera_motion == "zoom":
        # Gentle zoom in over time (scale 1 → 1.3)
        s = 1.0 + 0.3 * (0.5 + 0.5 * math.sin(t * 0.5))
        return s, 0.0, 0.0, 0.0
    if camera_motion == "zoom_out":
        # Zoom out over time (scale 1.3 → 1)
        s = 1.3 - 0.3 * (0.5 + 0.5 * math.sin(t * 0.5))
        return max(0.5, s), 0.0, 0.0, 0.0
    if camera_motion == "pan":
        # Horizontal pan
        pan_x = 0.2 * math.sin(t * 0.3)
        return 1.0, pan_x, 0.0, 0.0
    if camera_motion == "rotate":
        # Slow rotation
        return 1.0, 0.0, 0.0, t * 0.3
    if camera_motion == "dolly":
        # Dolly: zoom in (push forward)
        s = 1.0 + 0.25 * ease_in_out(min(1.0, t / 4.0))
        return min(s, 1.25), 0.0, 0.0, 0.0
    if camera_motion == "crane":
        # Crane: vertical movement + slight zoom
        pan_y = 0.15 * ease_in_out(min(1.0, t / 3.0))
        s = 1.0 + 0.1 * math.sin(t * 0.4)
        return s, 0.0, pan_y, 0.0
    if camera_motion == "tilt":
        # Tilt: vertical pan (camera angles up/down)
        pan_y = 0.18 * math.sin(t * 0.35)
        return 1.0, 0.0, pan_y, 0.0
    if camera_motion == "roll":
        # Roll: rotation around view axis
        return 1.0, 0.0, 0.0, t * 0.25
    if camera_motion == "truck":
        # Truck: lateral movement (horizontal, like pan)
        pan_x = 0.22 * math.sin(t * 0.28)
        return 1.0, pan_x, 0.0, 0.0
    if camera_motion == "pedestal":
        # Pedestal: vertical camera move
        pan_y = 0.12 * ease_in_out(min(1.0, t / 4.0))
        return 1.0, 0.0, pan_y, 0.0
    if camera_motion == "arc":
        # Arc: combine pan + vertical
        pan_x = 0.15 * math.sin(t * 0.3)
        pan_y = 0.1 * math.cos(t * 0.3)
        return 1.0, pan_x, pan_y, 0.0
    if camera_motion == "tracking":
        # Tracking: horizontal follow (like pan)
        pan_x = 0.2 * ease_in_out(min(1.0, t / 3.0))
        return 1.0, pan_x, 0.0, 0.0
    if camera_motion == "whip_pan":
        # Whip pan: fast horizontal sweep
        pan_x = 0.4 * math.sin(t * 2.0)
        return 1.0, pan_x, 0.0, 0.0
    if camera_motion == "birds_eye":
        # Birds eye: overhead feel — zoom out + slow orbit
        s = 0.85 - 0.1 * math.sin(t * 0.2)
        rotate = t * 0.15
        return max(0.6, s), 0.0, 0.0, rotate
    if camera_motion == "handheld":
        # Organic micro-shake + slight drift
        pan_x = 0.012 * math.sin(t * 11.3) + 0.008 * math.sin(t * 7.1)
        pan_y = 0.010 * math.sin(t * 9.7 + 1.2) + 0.006 * math.cos(t * 5.3)
        rot = 0.015 * math.sin(t * 6.5)
        return 1.0, pan_x, pan_y, rot
    return 1.0, 0.0, 0.0, 0.0


def steadiness_shake(
    steadiness: str,
    t: float,
) -> tuple[float, float, float]:
    """
    Extra (pan_x, pan_y, rotate) from camera steadiness origin.
    locked/stable → none; handheld → mild; shaky → strong.
    """
    s = (steadiness or "stable").lower()
    if s in ("locked", "stable", "tripod", ""):
        return 0.0, 0.0, 0.0
    if s == "handheld":
        return (
            0.010 * math.sin(t * 13.1),
            0.008 * math.sin(t * 10.4 + 0.7),
            0.012 * math.sin(t * 8.2),
        )
    if s in ("shaky", "unstable", "chaotic"):
        return (
            0.028 * math.sin(t * 17.0) + 0.015 * math.sin(t * 23.0),
            0.022 * math.sin(t * 19.0 + 1.1),
            0.035 * math.sin(t * 14.0),
        )
    return 0.0, 0.0, 0.0


def rhythm_modulation(rhythm: str, t: float) -> float:
    """
    Scalar ~0.85–1.15 modulating intensity / layer scale from motion_rhythm.
    """
    r = (rhythm or "steady").lower()
    if r == "pulsing":
        return 0.88 + 0.22 * pulse(t, 1.2)
    if r == "wave":
        return 0.92 + 0.14 * (0.5 + 0.5 * wave(t, 0.45))
    if r == "random":
        # Deterministic pseudo-random wobble
        return 0.9 + 0.2 * (0.5 + 0.5 * math.sin(t * 5.7 + math.sin(t * 13.3)))
    return 1.0

"""
Seeded camera motion for pixel-field clips (opt-in via LOOP_CAMERA_VARIATION).

Pairing fields used to be locked to a static camera, so every clip had the same framing.
With ``LOOP_CAMERA_VARIATION=1`` the builder draws one camera move per seed and the renderer
applies it to the field coordinates. Amplitudes are tuned so the move is visible within a
single second. The flag is off by default, which keeps the camera ``static`` (legacy behaviour).
"""
from __future__ import annotations

import math
import os
import random
import secrets

#: Camera names that are valid registry values (see builder._CAMERA_VALID) and work on a field.
FIELD_CAMERA_CHOICES: tuple[str, ...] = ("static", "pan", "tilt", "zoom", "zoom_out", "rotate", "arc")
#: Relative likelihood of each choice; static stays possible but is the minority.
_FIELD_CAMERA_WEIGHTS: dict[str, float] = {
    "static": 0.10, "pan": 0.20, "tilt": 0.14, "zoom": 0.17, "zoom_out": 0.13, "rotate": 0.12, "arc": 0.14,
}

_TRUE = {"1", "true", "yes", "on", "y"}


def camera_variation_enabled() -> bool:
    """LOOP_CAMERA_VARIATION (default off)."""
    return os.environ.get("LOOP_CAMERA_VARIATION", "").strip().lower() in _TRUE


def pick_field_camera(seed: int | None) -> str:
    """Seeded draw of a field camera move (reproducible for a seed; entropy when seed is None)."""
    rng = random.Random(int(seed)) if seed is not None else random.Random(secrets.randbits(31))
    names = list(FIELD_CAMERA_CHOICES)
    r = rng.random() * sum(_FIELD_CAMERA_WEIGHTS[n] for n in names)
    for n in names:
        r -= _FIELD_CAMERA_WEIGHTS[n]
        if r < 0:
            return n
    return names[-1]


def _rng(seed: int, camera: str) -> random.Random:
    return random.Random(f"fieldcam:{int(seed)}:{camera}")


def field_camera_params(camera_motion: str, t: float, seed: int) -> tuple[float, float, float, float]:
    """
    (zoom, pan_x, pan_y, rotate_rad) for a pixel field at clip time ``t`` seconds.

    Per-seed direction and amplitude make two clips with the same move still differ.
    ``static`` (or unknown names) return the identity transform.
    """
    cam = (camera_motion or "static").strip().lower()
    t = max(0.0, float(t))
    if cam == "static" or cam not in FIELD_CAMERA_CHOICES:
        return 1.0, 0.0, 0.0, 0.0
    rng = _rng(seed, cam)
    sign = rng.choice((-1.0, 1.0))
    if cam == "pan":
        return 1.0, sign * rng.uniform(0.10, 0.24) * t, 0.0, 0.0
    if cam == "tilt":
        return 1.0, 0.0, sign * rng.uniform(0.10, 0.24) * t, 0.0
    if cam == "zoom":
        return 1.0 + rng.uniform(0.18, 0.45) * t, 0.0, 0.0, 0.0
    if cam == "zoom_out":
        amp = rng.uniform(0.18, 0.45)
        return 1.0 + amp * max(0.0, 1.0 - t), 0.0, 0.0, 0.0
    if cam == "rotate":
        return 1.0, 0.0, 0.0, sign * rng.uniform(0.18, 0.55) * t
    # arc: a small curved drift (pan + tilt out of phase) with a hint of push-in
    ax, ay = rng.uniform(0.06, 0.16), rng.uniform(0.06, 0.16)
    ph = rng.uniform(0.0, math.pi)
    w = rng.uniform(1.2, 2.4) * math.pi
    return (
        1.0 + 0.08 * t,
        sign * ax * math.sin(w * t + ph),
        ay * math.cos(w * t + ph) - ay * math.cos(ph),
        0.0,
    )
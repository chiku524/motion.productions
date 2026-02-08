"""
Prompt → scene spec using only our rules and data. No neural network, no external model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .data import (
    KEYWORD_TO_PALETTE,
    KEYWORD_TO_MOTION,
    KEYWORD_TO_INTENSITY,
    KEYWORD_TO_GRADIENT,
    KEYWORD_TO_CAMERA,
    KEYWORD_TO_SHAPE,
    DEFAULT_PALETTE,
    DEFAULT_MOTION,
    DEFAULT_INTENSITY,
    DEFAULT_GRADIENT,
    DEFAULT_CAMERA,
    DEFAULT_SHAPE,
)


@dataclass
class SceneSpec:
    """Result of parsing a prompt: palette, motion, intensity, gradient, camera, etc."""
    palette_name: str
    motion_type: str
    intensity: float
    raw_prompt: str
    gradient_type: str = "vertical"   # vertical | radial | angled | horizontal
    camera_motion: str = "static"     # static | zoom | zoom_out | pan | rotate
    shape_overlay: str = "none"       # none | circle | rect


def parse_prompt_to_spec(prompt: str, *, seed: int | None = None) -> SceneSpec:
    """
    Turn a text prompt into a scene specification using only our keyword tables.
    No external model — pure lookup and rules.
    """
    prompt = (prompt or "").strip().lower()
    words = set(re.findall(r"[a-z]+", prompt))

    palette = DEFAULT_PALETTE
    for w in words:
        if w in KEYWORD_TO_PALETTE:
            palette = KEYWORD_TO_PALETTE[w]
            break

    motion = DEFAULT_MOTION
    for w in words:
        if w in KEYWORD_TO_MOTION:
            motion = KEYWORD_TO_MOTION[w]
            break

    intensity = DEFAULT_INTENSITY
    for w in words:
        if w in KEYWORD_TO_INTENSITY:
            intensity = KEYWORD_TO_INTENSITY[w]
            break

    gradient = DEFAULT_GRADIENT
    for w in words:
        if w in KEYWORD_TO_GRADIENT:
            gradient = KEYWORD_TO_GRADIENT[w]
            break

    camera = DEFAULT_CAMERA
    for w in words:
        if w in KEYWORD_TO_CAMERA:
            camera = KEYWORD_TO_CAMERA[w]
            break

    shape = DEFAULT_SHAPE
    for w in words:
        if w in KEYWORD_TO_SHAPE:
            shape = KEYWORD_TO_SHAPE[w]
            break

    return SceneSpec(
        palette_name=palette,
        motion_type=motion,
        intensity=float(intensity),
        raw_prompt=prompt,
        gradient_type=gradient,
        camera_motion=camera,
        shape_overlay=shape,
    )

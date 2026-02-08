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
    DEFAULT_PALETTE,
    DEFAULT_MOTION,
    DEFAULT_INTENSITY,
)


@dataclass
class SceneSpec:
    """Result of parsing a prompt: our data only (palette name, motion, intensity)."""
    palette_name: str
    motion_type: str
    intensity: float
    raw_prompt: str


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

    return SceneSpec(
        palette_name=palette,
        motion_type=motion,
        intensity=float(intensity),
        raw_prompt=prompt,
    )

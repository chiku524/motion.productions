"""
Per-video instance of scenery structure — not a second look pipeline.

Prompt-named values (palette, intensity, shot, lighting, composition) stay exact.
Only horizon, texture salt, and beat timing are instanced so two clips of the
same setting are not cloned plates.
"""
from __future__ import annotations

import random
from typing import Any

from .forms import form_seed


def scene_rng(prompt: str, creation_seed: int | None, stream: str = "scene") -> random.Random:
    return random.Random(form_seed(prompt or "", stream, extra=int(creation_seed or 0)))


def instantiate_scene(
    *,
    prompt: str,
    setting: str | None,
    creation_seed: int | None,
    palette_colors: list[tuple[int, int, int]] | None,
    intensity: float,
    shot_type: str,
    default_shot: str = "medium",
) -> dict[str, Any]:
    """Author per-clip scenery instance. Look categories are passed through unchanged."""
    del setting, default_shot
    rng = scene_rng(prompt, creation_seed, "scene")
    return {
        "horizon": rng.uniform(0.56, 0.68),
        "tex_salt": rng.randint(0, 10_000_000),
        "beat_weights": _beat_weights(rng),
        "palette_colors": list(palette_colors) if palette_colors else None,
        "intensity": float(intensity),
        "shot_type": shot_type,
    }


def _beat_weights(rng: random.Random) -> list[float]:
    w1 = rng.uniform(0.18, 0.32)
    w3 = rng.uniform(0.22, 0.36)
    w2 = max(0.28, 1.0 - w1 - w3)
    total = w1 + w2 + w3
    return [w1 / total, w2 / total, w3 / total]

"""
Per-video instance of every unspecified look parameter.

Prompt-named categories stay (ocean lighting, walk → tracking camera).
Numeric scenery — palette RGB, horizon, sky/ground, composition jitter,
shot when unspecified, intensity — is authored from prompt + creation_seed
so each loop clip is a new generation, not a cloned setting template.
"""
from __future__ import annotations

import random
from typing import Any, Sequence

from .forms import form_seed

_BACKDROP_BASE: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    "city": ((18, 8, 28), (-10, -5, 35)),
    "neon": ((25, 0, 40), (-5, 20, 45)),
    "ocean": ((-15, 10, 35), (-20, 25, 50)),
    "beach": ((40, 28, 8), (20, 35, 55)),
    "underwater": ((-30, 15, 40), (-40, 20, 55)),
    "forest": ((-10, 35, -5), (-15, 20, 10)),
    "night": ((-25, -20, -5), (-35, -25, 15)),
    "noir": ((-30, -30, -25), (-40, -35, -20)),
    "golden_hour": ((45, 22, -5), (50, 30, 5)),
    "day": ((15, 18, 5), (10, 25, 45)),
    "desert": ((50, 30, 5), (35, 40, 20)),
    "mountain": ((10, 15, 20), (5, 20, 40)),
    "space": ((-40, -35, -10), (-50, -40, 20)),
    "studio": ((8, 8, 10), (12, 12, 15)),
    "interior": ((12, 8, 5), (5, 5, 8)),
    "exterior": ((15, 20, 8), (8, 22, 40)),
    "rain": ((-20, -5, 15), (-25, 5, 25)),
    "snow": ((35, 38, 42), (20, 30, 45)),
    "street": ((15, 10, 20), (-5, 5, 30)),
    "park": ((-5, 30, -8), (5, 25, 35)),
    "moody": ((-15, -10, 5), (-25, -15, 20)),
    "abstract": ((20, -10, 35), (10, 15, 40)),
}


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
    """Author a unique look instance. Categorical prompt locks are applied by the caller."""
    rng = scene_rng(prompt, creation_seed, "scene")
    setting_key = (setting or "").strip().lower()
    ground_b, sky_b = _BACKDROP_BASE.get(setting_key, ((10, 10, 10), (8, 12, 20)))
    ground_d = _jitter_delta(ground_b, rng, 18.0)
    sky_d = _jitter_delta(sky_b, rng, 18.0)
    shot = shot_type
    if shot == default_shot:
        shot = rng.choice(("medium", "medium", "wide", "close"))
    colors = _jitter_palette(palette_colors, rng) if palette_colors else None
    return {
        "horizon": rng.uniform(0.54, 0.72),
        "ground_d": ground_d,
        "sky_d": sky_d,
        "backdrop_amp": rng.uniform(0.16, 0.32),
        "comp_dx": rng.uniform(-0.06, 0.06),
        "comp_dy": rng.uniform(-0.03, 0.03),
        "tex_salt": rng.randint(0, 10_000_000),
        "haze": rng.uniform(0.08, 0.22),
        "palette_colors": colors,
        "intensity": max(0.12, min(1.0, float(intensity) * rng.uniform(0.88, 1.14))),
        "shot_type": shot,
        "color_temperature": rng.choice(("neutral", "warm", "cool", "neutral")),
        "beat_weights": _beat_weights(rng),
    }


def _beat_weights(rng: random.Random) -> list[float]:
    w1 = rng.uniform(0.18, 0.32)
    w3 = rng.uniform(0.22, 0.36)
    w2 = max(0.28, 1.0 - w1 - w3)
    total = w1 + w2 + w3
    return [w1 / total, w2 / total, w3 / total]


def _jitter_delta(
    base: tuple[float, float, float],
    rng: random.Random,
    amount: float,
) -> tuple[float, float, float]:
    return (
        float(base[0]) + rng.uniform(-amount, amount),
        float(base[1]) + rng.uniform(-amount, amount),
        float(base[2]) + rng.uniform(-amount, amount),
    )


def _jitter_palette(
    colors: Sequence[tuple[int, int, int]],
    rng: random.Random,
    amount: float = 0.045,
) -> list[tuple[int, int, int]]:
    from ..knowledge.color_space import oklab_to_rgb, rgb_to_oklab

    out: list[tuple[int, int, int]] = []
    for c in colors:
        L, a, b = rgb_to_oklab(c)
        L = max(0.06, min(0.94, L + rng.uniform(-amount, amount)))
        a = a + rng.uniform(-amount * 1.3, amount * 1.3)
        b = b + rng.uniform(-amount * 1.3, amount * 1.3)
        out.append(oklab_to_rgb((L, a, b)))
    return out

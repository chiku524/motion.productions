"""
Setting-linked prop primitives for mini-scene backgrounds.

Stylized scenery: trees, fish, waves, buildings, clouds.
Spawned from setting keywords and/or explicit prompt words.
Geometry is authored per video (prompt + seed); these recipes only pick
kinds and rough placement, not cloned meshes or learned_entities rows.
"""
from __future__ import annotations

import random
from typing import Any

from ..procedural.forms import form_seed

PROP_KINDS = ("tree", "fish", "wave", "building", "cloud")

# setting → (kind, min_count, max_count) authored per video — not cloned positions
SETTING_KIND_WEIGHTS: dict[str, list[tuple[str, int, int]]] = {
    "forest": [("tree", 3, 6), ("cloud", 0, 2)],
    "park": [("tree", 2, 5), ("cloud", 0, 2)],
    "ocean": [("wave", 1, 2), ("fish", 1, 2), ("cloud", 0, 2)],
    "beach": [("wave", 1, 2), ("cloud", 1, 3)],
    "underwater": [("fish", 2, 4), ("wave", 0, 1)],
    "city": [("building", 2, 5), ("cloud", 0, 2)],
    "neon": [("building", 2, 4), ("cloud", 0, 1)],
    "street": [("building", 2, 4), ("cloud", 0, 2)],
    "night": [("building", 1, 3), ("cloud", 0, 2)],
    "mountain": [("tree", 1, 3), ("cloud", 1, 3)],
    "day": [("cloud", 1, 3)],
    "golden_hour": [("cloud", 1, 3), ("tree", 0, 2)],
    "desert": [("cloud", 0, 2)],
    "rain": [("cloud", 1, 3), ("building", 0, 2)],
    "snow": [("cloud", 1, 3), ("tree", 1, 3)],
}

# Default colors per prop kind (overridden by color_hint / palette)
PROP_COLORS: dict[str, tuple[int, int, int]] = {
    "tree": (34, 120, 55),
    "fish": (240, 140, 50),
    "wave": (70, 140, 200),
    "building": (70, 75, 95),
    "cloud": (230, 235, 245),
}


def jump_arc_keyframes(
    *,
    duration: float,
    start_x: float = 0.2,
    end_x: float = 0.8,
    water_y: float = 0.72,
    peak_y: float = 0.35,
) -> list[dict[str, float]]:
    """Fish jump: leave water → peak → re-enter (mild pitch, not a tumble)."""
    duration = max(1.2, float(duration))
    return [
        {"t": 0.0, "x": start_x, "y": water_y, "scale": 0.92, "opacity": 0.0, "rot": 0.12},
        {"t": duration * 0.12, "x": start_x + 0.05, "y": water_y - 0.05, "scale": 0.96, "opacity": 1.0, "rot": -0.22},
        {"t": duration * 0.45, "x": (start_x + end_x) / 2, "y": peak_y, "scale": 1.0, "opacity": 1.0, "rot": 0.05},
        {"t": duration * 0.78, "x": end_x - 0.05, "y": water_y - 0.04, "scale": 0.96, "opacity": 1.0, "rot": 0.28},
        {"t": duration, "x": end_x, "y": water_y, "scale": 0.92, "opacity": 0.0, "rot": 0.38},
    ]


def static_prop_keyframes(
    *,
    duration: float,
    x: float,
    y: float,
    scale: float = 1.0,
    sway: bool = False,
) -> list[dict[str, float]]:
    """Mostly static prop with optional gentle sway."""
    duration = max(0.5, float(duration))
    if sway:
        return [
            {"t": 0.0, "x": x, "y": y, "scale": scale, "opacity": 1.0, "rot": -0.03},
            {"t": duration * 0.5, "x": x + 0.01, "y": y, "scale": scale, "opacity": 1.0, "rot": 0.03},
            {"t": duration, "x": x, "y": y, "scale": scale, "opacity": 1.0, "rot": -0.02},
        ]
    return [
        {"t": 0.0, "x": x, "y": y, "scale": scale, "opacity": 1.0, "rot": 0.0},
        {"t": duration, "x": x, "y": y, "scale": scale, "opacity": 1.0, "rot": 0.0},
    ]


def drift_prop_keyframes(
    *,
    duration: float,
    trajectory: str,
    y: float,
    scale: float = 1.0,
) -> list[dict[str, float]]:
    """Horizontal/vertical drift for waves, clouds, swimming fish."""
    duration = max(1.0, float(duration))
    traj = (trajectory or "left").lower()
    starts = {
        "left": (0.9, 0.15),
        "right": (0.1, 0.85),
        "up": (0.5, 0.5),
        "down": (0.5, 0.5),
    }
    x0, x1 = starts.get(traj, (0.2, 0.8))
    if traj in ("up", "down"):
        y0, y1 = (0.7, 0.3) if traj == "up" else (0.3, 0.7)
        return [
            {"t": 0.0, "x": x0, "y": y0, "scale": scale, "opacity": 0.9, "rot": 0.0},
            {"t": duration, "x": x0, "y": y1, "scale": scale, "opacity": 0.9, "rot": 0.0},
        ]
    return [
        {"t": 0.0, "x": x0, "y": y, "scale": scale, "opacity": 0.85, "rot": 0.0},
        {"t": duration, "x": x1, "y": y, "scale": scale, "opacity": 0.85, "rot": 0.0},
    ]


def _clip01(v: float) -> float:
    return max(0.06, min(0.94, float(v)))


def _tint(rgb: tuple[int, int, int], rng: random.Random, amount: int = 28) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c) + rng.randint(-amount, amount))) for c in rgb)  # type: ignore[return-value]


def _tree_species_label(rng: random.Random, setting: str) -> str:
    s = (setting or "").lower()
    if s in ("snow", "mountain"):
        return rng.choice(("pine", "pine", "fir", "oak"))
    if s in ("beach", "desert"):
        return rng.choice(("palm", "palm", "tree"))
    if s in ("forest", "park"):
        return rng.choice(("oak", "oak", "pine", "maple", "tree"))
    return rng.choice(("oak", "pine", "tree"))


def _place_kind(kind: str, rng: random.Random) -> tuple[float, float, float, str, bool, int]:
    """Return x, y, scale, trajectory, bounce, z for a newly authored prop."""
    if kind == "tree":
        return (
            rng.uniform(0.06, 0.94),
            rng.uniform(0.56, 0.76),
            rng.uniform(0.55, 1.35),
            "none",
            False,
            0,
        )
    if kind == "cloud":
        return (
            rng.uniform(0.08, 0.92),
            rng.uniform(0.10, 0.30),
            rng.uniform(0.65, 1.45),
            rng.choice(("left", "right", "none")),
            False,
            0,
        )
    if kind == "building":
        return (
            rng.uniform(0.08, 0.92),
            rng.uniform(0.46, 0.62),
            rng.uniform(0.85, 1.75),
            "none",
            False,
            0,
        )
    if kind == "wave":
        return (
            rng.uniform(0.28, 0.72),
            rng.uniform(0.70, 0.86),
            rng.uniform(1.05, 1.65),
            rng.choice(("left", "right", "none")),
            False,
            0,
        )
    # fish
    jump = rng.random() < 0.45
    return (
        rng.uniform(0.12, 0.40) if jump else rng.uniform(0.10, 0.88),
        rng.uniform(0.58, 0.78) if jump else rng.uniform(0.38, 0.70),
        rng.uniform(0.50, 0.95),
        "jump" if jump else rng.choice(("left", "right")),
        jump,
        2,
    )


def _make_prop(
    kind: str,
    rng: random.Random,
    setting_key: str,
    index: int,
) -> dict[str, Any]:
    x, y, scale, traj, bounce, z = _place_kind(kind, rng)
    label = kind
    if kind == "tree":
        label = _tree_species_label(rng, setting_key)
    elif kind == "fish":
        label = rng.choice(("fish", "goldfish", "reef fish", "tuna"))
    return {
        "id": f"prop_{kind}_{index}_{int(x * 1000)}_{int(scale * 100)}",
        "kind": kind,
        "label": label,
        "color_hint": None,
        "prop_color": _tint(PROP_COLORS.get(kind, (180, 180, 180)), rng),
        "directionality": "horizontal" if traj in ("left", "right", "jump") else "none",
        "trajectory": "right" if traj == "jump" else traj,
        "bounce": bounce,
        "sfx_on": ["whoosh"] if kind == "fish" and traj == "jump" else [],
        "expression": "neutral",
        "personality": "neutral",
        "gag": "none",
        "z": z,
        "is_prop": True,
        "prop_scale": scale,
        "prop_x": _clip01(x),
        "prop_y": _clip01(y),
        "prop_motion": traj,
    }


def props_for_setting(
    setting: str | None,
    *,
    duration: float = 5.0,
    existing_kinds: set[str] | None = None,
    max_props: int = 8,
    prompt: str = "",
    creation_seed: int | None = None,
) -> list[dict[str, Any]]:
    """Author a unique scenery layout from setting + prompt + seed."""
    del duration
    if not setting:
        return []
    setting_key = str(setting).strip().lower()
    weights = SETTING_KIND_WEIGHTS.get(setting_key)
    if not weights:
        return []
    rng = random.Random(form_seed(prompt, setting_key, extra=int(creation_seed or 0)))
    existing = existing_kinds or set()
    out: list[dict[str, Any]] = []
    n = 0
    for kind, lo, hi in weights:
        if kind not in PROP_KINDS:
            continue
        count = rng.randint(lo, hi)
        if kind in existing and kind in ("fish", "wave", "cloud"):
            count = 0 if kind == "fish" else min(count, 1)
            if kind == "fish":
                continue
        for _ in range(count):
            if len(out) >= max_props:
                break
            out.append(_make_prop(kind, rng, setting_key, n))
            n += 1
    return out


def merge_setting_props(
    entities: list[dict[str, Any]],
    setting: str | None,
    *,
    duration: float = 5.0,
    prompt: str = "",
    creation_seed: int | None = None,
) -> list[dict[str, Any]]:
    """Append setting props behind/around existing foreground entities."""
    existing_kinds = {
        str(e.get("kind") or "")
        for e in entities
        if isinstance(e, dict)
    }
    props = props_for_setting(
        setting,
        duration=duration,
        existing_kinds=existing_kinds,
        prompt=prompt,
        creation_seed=creation_seed,
    )
    if not props:
        return entities
    return list(props) + list(entities)

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

# setting → list of prop spawn recipes (kind, typical trajectory, bounce, z-bias)
SETTING_PROP_RECIPES: dict[str, list[dict[str, Any]]] = {
    "forest": [
        {"kind": "tree", "trajectory": "none", "x": 0.18, "y": 0.62, "scale": 1.1, "z": 0},
        {"kind": "tree", "trajectory": "none", "x": 0.78, "y": 0.64, "scale": 0.95, "z": 0},
        {"kind": "tree", "trajectory": "none", "x": 0.48, "y": 0.68, "scale": 0.75, "z": 0},
    ],
    "ocean": [
        {"kind": "wave", "trajectory": "left", "x": 0.5, "y": 0.78, "scale": 1.4, "z": 0},
        {"kind": "fish", "trajectory": "jump", "x": 0.25, "y": 0.7, "scale": 0.7, "z": 2, "bounce": True},
    ],
    "beach": [
        {"kind": "wave", "trajectory": "right", "x": 0.5, "y": 0.8, "scale": 1.3, "z": 0},
        {"kind": "cloud", "trajectory": "left", "x": 0.7, "y": 0.22, "scale": 1.0, "z": 0},
    ],
    "underwater": [
        {"kind": "fish", "trajectory": "right", "x": 0.2, "y": 0.45, "scale": 0.8, "z": 2},
        {"kind": "fish", "trajectory": "left", "x": 0.85, "y": 0.6, "scale": 0.55, "z": 1},
        {"kind": "wave", "trajectory": "none", "x": 0.5, "y": 0.15, "scale": 1.2, "z": 0},
    ],
    "city": [
        {"kind": "building", "trajectory": "none", "x": 0.2, "y": 0.55, "scale": 1.3, "z": 0},
        {"kind": "building", "trajectory": "none", "x": 0.45, "y": 0.5, "scale": 1.6, "z": 0},
        {"kind": "building", "trajectory": "none", "x": 0.75, "y": 0.58, "scale": 1.1, "z": 0},
    ],
    "neon": [
        {"kind": "building", "trajectory": "none", "x": 0.25, "y": 0.52, "scale": 1.4, "z": 0},
        {"kind": "building", "trajectory": "none", "x": 0.7, "y": 0.48, "scale": 1.7, "z": 0},
    ],
    "mountain": [
        {"kind": "tree", "trajectory": "none", "x": 0.15, "y": 0.7, "scale": 0.6, "z": 0},
        {"kind": "cloud", "trajectory": "right", "x": 0.3, "y": 0.2, "scale": 1.1, "z": 0},
    ],
    "day": [
        {"kind": "cloud", "trajectory": "left", "x": 0.65, "y": 0.2, "scale": 1.0, "z": 0},
    ],
    "golden_hour": [
        {"kind": "cloud", "trajectory": "right", "x": 0.35, "y": 0.25, "scale": 1.15, "z": 0},
        {"kind": "tree", "trajectory": "none", "x": 0.85, "y": 0.65, "scale": 0.85, "z": 0},
    ],
    "desert": [
        {"kind": "cloud", "trajectory": "left", "x": 0.4, "y": 0.18, "scale": 0.7, "z": 0},
    ],
    "rain": [
        {"kind": "cloud", "trajectory": "none", "x": 0.5, "y": 0.15, "scale": 1.4, "z": 0},
        {"kind": "building", "trajectory": "none", "x": 0.8, "y": 0.55, "scale": 1.0, "z": 0},
    ],
    "snow": [
        {"kind": "cloud", "trajectory": "left", "x": 0.35, "y": 0.18, "scale": 1.2, "z": 0},
        {"kind": "cloud", "trajectory": "right", "x": 0.75, "y": 0.22, "scale": 0.9, "z": 0},
        {"kind": "tree", "trajectory": "none", "x": 0.2, "y": 0.68, "scale": 0.85, "z": 0},
    ],
    "street": [
        {"kind": "building", "trajectory": "none", "x": 0.2, "y": 0.52, "scale": 1.3, "z": 0},
        {"kind": "building", "trajectory": "none", "x": 0.75, "y": 0.55, "scale": 1.15, "z": 0},
        {"kind": "cloud", "trajectory": "left", "x": 0.55, "y": 0.2, "scale": 0.85, "z": 0},
    ],
    "park": [
        {"kind": "tree", "trajectory": "none", "x": 0.2, "y": 0.62, "scale": 1.0, "z": 0},
        {"kind": "tree", "trajectory": "none", "x": 0.78, "y": 0.65, "scale": 0.9, "z": 0},
        {"kind": "cloud", "trajectory": "right", "x": 0.45, "y": 0.2, "scale": 1.0, "z": 0},
    ],
    "night": [
        {"kind": "building", "trajectory": "none", "x": 0.3, "y": 0.55, "scale": 1.2, "z": 0},
        {"kind": "cloud", "trajectory": "left", "x": 0.7, "y": 0.18, "scale": 0.9, "z": 0},
    ],
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


def props_for_setting(
    setting: str | None,
    *,
    duration: float = 5.0,
    existing_kinds: set[str] | None = None,
    max_props: int = 6,
    prompt: str = "",
    creation_seed: int | None = None,
) -> list[dict[str, Any]]:
    """
    Build entity dicts for setting scenery. Placement and species vary per
    prompt+seed so two forest videos do not share the same three trees.
    """
    del duration  # duration is applied later when keyframes are built
    if not setting:
        return []
    setting_key = str(setting).strip().lower()
    recipes = SETTING_PROP_RECIPES.get(setting_key)
    if not recipes:
        return []
    rng = random.Random(form_seed(prompt, setting_key, extra=int(creation_seed or 0)))
    existing = existing_kinds or set()
    out: list[dict[str, Any]] = []
    for i, recipe in enumerate(recipes):
        if len(out) >= max_props:
            break
        kind = str(recipe.get("kind") or "")
        if kind not in PROP_KINDS:
            continue
        if kind in existing and kind in ("fish", "wave", "cloud"):
            continue
        traj = str(recipe.get("trajectory") or "none")
        bounce = bool(recipe.get("bounce"))
        x = _clip01(float(recipe.get("x", 0.5)) + rng.uniform(-0.14, 0.14))
        y = _clip01(float(recipe.get("y", 0.5)) + rng.uniform(-0.07, 0.07))
        scale = max(0.45, float(recipe.get("scale", 1.0)) * rng.uniform(0.72, 1.28))
        z = int(recipe.get("z", 0))
        color = _tint(PROP_COLORS.get(kind, (180, 180, 180)), rng)
        label = kind
        if kind == "tree":
            label = _tree_species_label(rng, setting_key)
        elif kind == "fish":
            label = rng.choice(("fish", "fish", "goldfish", "reef fish"))
        ent: dict[str, Any] = {
            "id": f"prop_{kind}_{i}_{int(x * 100)}_{int(scale * 100)}",
            "kind": kind,
            "label": label,
            "color_hint": None,
            "prop_color": color,
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
            "prop_x": x,
            "prop_y": y,
            "prop_motion": traj,
        }
        out.append(ent)
    # Extra trees/clouds so forests aren't a fixed trio
    if setting_key in ("forest", "park") and len(out) < max_props:
        n_extra = rng.randint(0, 2)
        for j in range(n_extra):
            if len(out) >= max_props:
                break
            x = rng.uniform(0.08, 0.92)
            y = rng.uniform(0.58, 0.74)
            scale = rng.uniform(0.55, 1.2)
            label = _tree_species_label(rng, setting_key)
            out.append({
                "id": f"prop_tree_x{j}_{int(x * 100)}",
                "kind": "tree",
                "label": label,
                "color_hint": None,
                "prop_color": _tint(PROP_COLORS["tree"], rng, 36),
                "directionality": "none",
                "trajectory": "none",
                "bounce": False,
                "sfx_on": [],
                "expression": "neutral",
                "personality": "neutral",
                "gag": "none",
                "z": 0,
                "is_prop": True,
                "prop_scale": scale,
                "prop_x": x,
                "prop_y": y,
                "prop_motion": "none",
            })
    if len(out) > 2 and rng.random() < 0.22:
        idx = rng.randrange(len(out))
        kind = str(out[idx].get("kind") or "")
        n_kind = sum(1 for e in out if e.get("kind") == kind)
        primary = {"forest": "tree", "park": "tree", "ocean": "wave", "city": "building"}.get(setting_key)
        if not (kind == primary and n_kind <= 2):
            out.pop(idx)
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

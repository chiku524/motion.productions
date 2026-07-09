"""
Setting-linked prop primitives for mini-scene backgrounds.

Stylized (not photoreal) scenery: trees, fish, waves, buildings, clouds.
Spawned from setting keywords and/or explicit prompt words; discovered via learned_entities.
"""
from __future__ import annotations

from typing import Any

from ..random_utils import secure_choice, secure_random

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
    """Fish jump: leave water → peak → re-enter (for scene graph keyframes)."""
    duration = max(1.2, float(duration))
    return [
        {"t": 0.0, "x": start_x, "y": water_y, "scale": 0.85, "opacity": 0.0, "rot": 0.2},
        {"t": duration * 0.12, "x": start_x + 0.05, "y": water_y - 0.05, "scale": 0.9, "opacity": 1.0, "rot": -0.4},
        {"t": duration * 0.45, "x": (start_x + end_x) / 2, "y": peak_y, "scale": 1.0, "opacity": 1.0, "rot": 0.0},
        {"t": duration * 0.78, "x": end_x - 0.05, "y": water_y - 0.04, "scale": 0.9, "opacity": 1.0, "rot": 0.5},
        {"t": duration, "x": end_x, "y": water_y, "scale": 0.85, "opacity": 0.0, "rot": 0.8},
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


def props_for_setting(
    setting: str | None,
    *,
    duration: float = 5.0,
    existing_kinds: set[str] | None = None,
    max_props: int = 4,
) -> list[dict[str, Any]]:
    """
    Build entity dicts for setting scenery. Skips kinds already present in the prompt.
    """
    if not setting:
        return []
    recipes = SETTING_PROP_RECIPES.get(str(setting).strip().lower())
    if not recipes:
        return []
    existing = existing_kinds or set()
    out: list[dict[str, Any]] = []
    for i, recipe in enumerate(recipes):
        if len(out) >= max_props:
            break
        kind = str(recipe.get("kind") or "")
        if kind not in PROP_KINDS:
            continue
        # Always allow multiple trees/buildings; skip duplicate fish/wave/cloud if already in prompt
        if kind in existing and kind in ("fish", "wave", "cloud") and kind in {e.get("kind") for e in out}:
            continue
        if kind in existing and kind in ("fish",) and any(e.get("kind") == "fish" for e in out):
            # one auto fish is enough when prompt already has fish
            continue
        traj = str(recipe.get("trajectory") or "none")
        bounce = bool(recipe.get("bounce"))
        x = float(recipe.get("x", 0.5))
        y = float(recipe.get("y", 0.5))
        scale = float(recipe.get("scale", 1.0))
        z = int(recipe.get("z", 0))
        color = PROP_COLORS.get(kind, (180, 180, 180))
        ent: dict[str, Any] = {
            "id": f"prop_{kind}_{i}",
            "kind": kind,
            "label": kind,
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
    # Occasionally drop one prop for variety
    if len(out) > 2 and secure_random() < 0.25:
        out.pop(secure_choice(range(len(out))))
    return out


def merge_setting_props(
    entities: list[dict[str, Any]],
    setting: str | None,
    *,
    duration: float = 5.0,
) -> list[dict[str, Any]]:
    """Append setting props behind/around existing foreground entities."""
    existing_kinds = {
        str(e.get("kind") or "")
        for e in entities
        if isinstance(e, dict)
    }
    props = props_for_setting(setting, duration=duration, existing_kinds=existing_kinds)
    if not props:
        return entities
    # Props first (lower z), then foreground entities
    return list(props) + list(entities)

"""
Scene graph: stylized entity layers with keyframed motion (Phase 2+).

No external assets required — circle/rect/arrow/character primitives only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class LayerKeyframe:
    t: float  # seconds
    x: float = 0.5  # normalized 0–1
    y: float = 0.5
    scale: float = 1.0
    rot: float = 0.0  # radians
    opacity: float = 1.0


@dataclass
class SceneLayer:
    id: str
    kind: str  # circle | rect | arrow | character
    color: tuple[int, int, int] = (220, 60, 60)
    z: int = 1
    keyframes: list[LayerKeyframe] = field(default_factory=list)
    sfx_on: list[str] = field(default_factory=list)  # e.g. ["bounce"]
    bounce: bool = False
    expression: str = "neutral"  # happy | sad | angry | calm | excited | nervous | neutral
    personality: str = "neutral"  # playful | serious | energetic | shy | confident | neutral

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["color"] = list(self.color)
        return d


@dataclass
class SceneGraph:
    layers: list[SceneLayer] = field(default_factory=list)

    def to_dict_list(self) -> list[dict[str, Any]]:
        return [layer.to_dict() for layer in self.layers]


def _lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


def sample_layer_at(layer: SceneLayer | dict[str, Any], t: float) -> dict[str, float]:
    """Interpolate layer pose at time t (seconds)."""
    if isinstance(layer, dict):
        kfs = layer.get("keyframes") or []
        kind = layer.get("kind", "circle")
    else:
        kfs = [asdict(k) if hasattr(k, "__dataclass_fields__") else k for k in layer.keyframes]
        kind = layer.kind
    if not kfs:
        return {"x": 0.5, "y": 0.5, "scale": 1.0, "rot": 0.0, "opacity": 1.0, "kind": kind}
    kfs = sorted(kfs, key=lambda k: float(k.get("t", 0)))
    if t <= float(kfs[0].get("t", 0)):
        k = kfs[0]
        return {
            "x": float(k.get("x", 0.5)),
            "y": float(k.get("y", 0.5)),
            "scale": float(k.get("scale", 1.0)),
            "rot": float(k.get("rot", 0.0)),
            "opacity": float(k.get("opacity", 1.0)),
            "kind": kind,
        }
    if t >= float(kfs[-1].get("t", 0)):
        k = kfs[-1]
        return {
            "x": float(k.get("x", 0.5)),
            "y": float(k.get("y", 0.5)),
            "scale": float(k.get("scale", 1.0)),
            "rot": float(k.get("rot", 0.0)),
            "opacity": float(k.get("opacity", 1.0)),
            "kind": kind,
        }
    for i in range(len(kfs) - 1):
        t0 = float(kfs[i].get("t", 0))
        t1 = float(kfs[i + 1].get("t", 0))
        if t0 <= t <= t1:
            u = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            # Bounce easing: ease toward floor contacts
            a, b = kfs[i], kfs[i + 1]
            return {
                "x": _lerp(float(a.get("x", 0.5)), float(b.get("x", 0.5)), u),
                "y": _lerp(float(a.get("y", 0.5)), float(b.get("y", 0.5)), u),
                "scale": _lerp(float(a.get("scale", 1.0)), float(b.get("scale", 1.0)), u),
                "rot": _lerp(float(a.get("rot", 0.0)), float(b.get("rot", 0.0)), u),
                "opacity": _lerp(float(a.get("opacity", 1.0)), float(b.get("opacity", 1.0)), u),
                "kind": kind,
            }
    k = kfs[-1]
    return {
        "x": float(k.get("x", 0.5)),
        "y": float(k.get("y", 0.5)),
        "scale": float(k.get("scale", 1.0)),
        "rot": float(k.get("rot", 0.0)),
        "opacity": float(k.get("opacity", 1.0)),
        "kind": kind,
    }


def _trajectory_path(
    trajectory: str,
    *,
    duration: float,
    bounce: bool,
) -> list[LayerKeyframe]:
    """Build keyframes for a simple directional path."""
    duration = max(1.0, float(duration or 4.0))
    traj = (trajectory or "none").lower()
    start = {"x": 0.5, "y": 0.5}
    end = {"x": 0.5, "y": 0.5}
    if traj == "left":
        start, end = {"x": 0.85, "y": 0.5}, {"x": 0.15, "y": 0.5}
    elif traj == "right":
        start, end = {"x": 0.15, "y": 0.5}, {"x": 0.85, "y": 0.5}
    elif traj == "up":
        start, end = {"x": 0.5, "y": 0.85}, {"x": 0.5, "y": 0.2}
    elif traj == "down":
        start, end = {"x": 0.5, "y": 0.2}, {"x": 0.5, "y": 0.85}
    elif traj == "toward":
        return [
            LayerKeyframe(t=0.0, x=0.5, y=0.55, scale=0.5),
            LayerKeyframe(t=duration, x=0.5, y=0.5, scale=1.6),
        ]
    elif traj == "away":
        return [
            LayerKeyframe(t=0.0, x=0.5, y=0.5, scale=1.4),
            LayerKeyframe(t=duration, x=0.5, y=0.55, scale=0.4),
        ]
    elif traj == "none" and bounce:
        # Vertical bounce in place
        kfs: list[LayerKeyframe] = []
        n_bounces = max(2, int(duration / 0.7))
        for i in range(n_bounces + 1):
            t = duration * (i / n_bounces)
            y = 0.75 if i % 2 == 0 else 0.35
            kfs.append(LayerKeyframe(t=t, x=0.5, y=y, scale=1.0))
        return kfs

    if bounce:
        # Horizontal/vertical path with bounce arcs
        kfs = []
        n = max(3, int(duration / 0.6))
        for i in range(n + 1):
            u = i / n
            t = duration * u
            x = start["x"] + (end["x"] - start["x"]) * u
            # Parabolic bounce between floor contacts
            phase = (u * n) % 1.0
            y_base = start["y"] + (end["y"] - start["y"]) * u
            y = y_base - 0.25 * (4 * phase * (1 - phase))  # arc up
            if i % 2 == 0:
                y = max(y_base, 0.72)  # floor contact
            kfs.append(LayerKeyframe(t=t, x=x, y=min(0.9, max(0.15, y)), scale=1.0))
        return kfs

    return [
        LayerKeyframe(t=0.0, x=start["x"], y=start["y"], scale=1.0),
        LayerKeyframe(t=duration, x=end["x"], y=end["y"], scale=1.0),
    ]


def _color_from_hint(hint: str | None, palette_colors: list[tuple[int, int, int]] | None) -> tuple[int, int, int]:
    if palette_colors:
        return tuple(int(c) for c in palette_colors[len(palette_colors) // 2][:3])  # type: ignore[return-value]
    # Named palette midpoints (fallback)
    named = {
        "warm": (220, 90, 50),
        "cool": (60, 120, 200),
        "neon": (255, 40, 180),
        "forest": (40, 140, 70),
        "red": (220, 50, 50),
        "blue": (50, 90, 220),
    }
    if hint and hint in named:
        return named[hint]
    return (220, 60, 60)


def build_scene_graph_from_instruction(
    instruction: Any,
    *,
    duration_seconds: float | None = None,
    palette_colors: list[tuple[int, int, int]] | None = None,
) -> SceneGraph:
    """Build a SceneGraph from InterpretedInstruction.entities."""
    duration = float(
        duration_seconds
        or getattr(instruction, "duration_seconds", None)
        or 4.0
    )
    entities = list(getattr(instruction, "entities", None) or [])
    layers: list[SceneLayer] = []
    for i, ent in enumerate(entities):
        if not isinstance(ent, dict):
            continue
        kind = str(ent.get("kind") or "circle")
        if kind not in ("circle", "rect", "arrow", "character"):
            kind = "circle"
        traj = str(ent.get("trajectory") or "none")
        bounce = bool(ent.get("bounce"))
        # Infer trajectory from directionality if missing
        if traj == "none":
            d = str(ent.get("directionality") or getattr(instruction, "motion_directionality", "none"))
            if d == "horizontal":
                traj = "left"
            elif d == "vertical":
                traj = "down" if bounce else "up"
            elif d == "diagonal":
                traj = "right"
            elif d == "radial":
                traj = "toward"
        color = _color_from_hint(ent.get("color_hint"), palette_colors)
        kfs = _trajectory_path(traj, duration=duration, bounce=bounce)
        sfx_on = list(ent.get("sfx_on") or [])
        if bounce and "bounce" not in sfx_on:
            sfx_on.append("bounce")
        layers.append(
            SceneLayer(
                id=str(ent.get("id") or f"e{i}"),
                kind=kind,
                color=color,
                z=i + 1,
                keyframes=kfs,
                sfx_on=sfx_on,
                bounce=bounce,
                expression=str(ent.get("expression") or "neutral"),
                personality=str(ent.get("personality") or "neutral"),
            )
        )
    return SceneGraph(layers=layers)


def sfx_events_from_scene_graph(
    graph: SceneGraph,
    *,
    duration_seconds: float,
) -> list[dict[str, Any]]:
    """Emit bounce/impact events at floor-contact keyframes."""
    events: list[dict[str, Any]] = []
    for layer in graph.layers:
        if "bounce" not in (layer.sfx_on or []) and not layer.bounce:
            continue
        # Floor contacts: local y maxima (lower on screen = higher y in our coords)
        kfs = layer.keyframes
        for i, kf in enumerate(kfs):
            y = kf.y
            is_floor = y >= 0.65
            if is_floor:
                events.append({
                    "kind": "bounce",
                    "t_sec": float(kf.t),
                    "strength": 0.85,
                    "layer_id": layer.id,
                })
            elif i > 0 and i < len(kfs) - 1:
                # Local peak toward floor
                if kfs[i - 1].y < y and kfs[i + 1].y < y and y > 0.55:
                    events.append({
                        "kind": "bounce",
                        "t_sec": float(kf.t),
                        "strength": 0.7,
                        "layer_id": layer.id,
                    })
    # Deduplicate near-simultaneous events
    events.sort(key=lambda e: e["t_sec"])
    deduped: list[dict[str, Any]] = []
    for e in events:
        if deduped and abs(e["t_sec"] - deduped[-1]["t_sec"]) < 0.08:
            continue
        if 0 <= e["t_sec"] <= duration_seconds + 0.05:
            deduped.append(e)
    return deduped


def walk_cycle_keyframes(
    *,
    duration: float,
    direction: str = "left",
    personality: str = "neutral",
) -> list[LayerKeyframe]:
    """Simple character walk: horizontal drift with bobbing (Phase D personality)."""
    duration = max(1.0, float(duration))
    x0, x1 = (0.8, 0.2) if direction == "left" else (0.2, 0.8)
    # Personality modulates step rate and bob amplitude
    pers = (personality or "neutral").lower()
    step_sec = 0.35
    bob = 0.04
    scale_base = 1.0
    if pers == "energetic":
        step_sec, bob, scale_base = 0.22, 0.07, 1.08
    elif pers == "playful":
        step_sec, bob, scale_base = 0.28, 0.06, 1.05
    elif pers == "shy":
        step_sec, bob, scale_base = 0.45, 0.02, 0.9
    elif pers == "serious":
        step_sec, bob, scale_base = 0.4, 0.015, 1.0
    elif pers == "confident":
        step_sec, bob, scale_base = 0.32, 0.035, 1.1
    steps = max(4, int(duration / step_sec))
    kfs: list[LayerKeyframe] = []
    for i in range(steps + 1):
        u = i / steps
        t = duration * u
        x = x0 + (x1 - x0) * u
        y = 0.55 + (bob if i % 2 else -bob * 0.5)
        kfs.append(LayerKeyframe(t=t, x=x, y=y, scale=scale_base))
    return kfs

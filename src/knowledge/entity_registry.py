"""
Entity registry growth: persist stylized scene entities from instruction/spec
into novel discovery payloads for D1 learned_entities.
"""
from __future__ import annotations

from typing import Any


def entity_profile_key(
    kind: str,
    *,
    trajectory: str = "none",
    bounce: bool = False,
    color_hint: str | None = None,
    directionality: str = "none",
    expression: str = "neutral",
    personality: str = "neutral",
    gag: str = "none",
) -> str:
    """Stable composite key for an entity profile (matches Worker upsert)."""
    kind = (kind or "circle").strip().lower() or "circle"
    traj = (trajectory or "none").strip().lower() or "none"
    bounce_s = "1" if bounce else "0"
    color = (color_hint or "none").strip().lower() or "none"
    direc = (directionality or "none").strip().lower() or "none"
    expr = (expression or "neutral").strip().lower() or "neutral"
    pers = (personality or "neutral").strip().lower() or "neutral"
    gag_s = (gag or "none").strip().lower() or "none"
    # Keep base key compatible; append expression/personality/gag when non-default
    base = f"{kind}_{traj}_{bounce_s}_{color}_{direc}"
    if expr != "neutral" or pers != "neutral" or gag_s != "none":
        return f"{base}_{expr}_{pers}_{gag_s}"
    return base


def _normalize_entity(ent: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(ent, dict):
        return None
    kind = str(ent.get("kind") or "circle").strip().lower()
    if kind not in ("circle", "rect", "arrow", "character", "tree", "fish", "wave", "building", "cloud"):
        kind = "circle"
    traj = str(ent.get("trajectory") or "none").strip().lower() or "none"
    bounce = bool(ent.get("bounce"))
    color_hint = ent.get("color_hint")
    if color_hint is not None:
        color_hint = str(color_hint).strip().lower() or None
    directionality = str(ent.get("directionality") or "none").strip().lower() or "none"
    expression = str(ent.get("expression") or "neutral").strip().lower() or "neutral"
    personality = str(ent.get("personality") or "neutral").strip().lower() or "neutral"
    gag = str(ent.get("gag") or "none").strip().lower() or "none"
    if bounce and gag == "none":
        gag = "squash"
    label = str(ent.get("label") or kind).strip()[:80]
    key = entity_profile_key(
        kind,
        trajectory=traj,
        bounce=bounce,
        color_hint=color_hint,
        directionality=directionality,
        expression=expression,
        personality=personality,
        gag=gag,
    )
    return {
        "key": key,
        "kind": kind,
        "trajectory": traj,
        "bounce": bounce,
        "color_hint": color_hint,
        "label": label,
        "directionality": directionality,
        "expression": expression,
        "personality": personality,
        "gag": gag,
        "sfx_on": list(ent.get("sfx_on") or []),
    }


def entities_from_instruction_or_spec(
    instruction: Any | None = None,
    spec: Any | None = None,
) -> list[dict[str, Any]]:
    """Collect entity dicts from instruction.entities or spec.scene_layers."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    raw_entities = list(getattr(instruction, "entities", None) or []) if instruction else []
    for ent in raw_entities:
        norm = _normalize_entity(ent if isinstance(ent, dict) else {})
        if not norm or norm["key"] in seen:
            continue
        seen.add(norm["key"])
        out.append(norm)

    layers = getattr(spec, "scene_layers", None) if spec is not None else None
    if isinstance(layers, list):
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            # Infer trajectory from first→last keyframe when possible
            traj = "none"
            kfs = layer.get("keyframes") or []
            if len(kfs) >= 2:
                x0 = float(kfs[0].get("x", 0.5))
                x1 = float(kfs[-1].get("x", 0.5))
                y0 = float(kfs[0].get("y", 0.5))
                y1 = float(kfs[-1].get("y", 0.5))
                dx, dy = x1 - x0, y1 - y0
                if abs(dx) >= abs(dy) and abs(dx) > 0.05:
                    traj = "right" if dx > 0 else "left"
                elif abs(dy) > 0.05:
                    traj = "down" if dy > 0 else "up"
            bounce = bool(layer.get("bounce"))
            color = layer.get("color")
            color_hint = None
            if isinstance(color, (list, tuple)) and len(color) >= 3:
                r, g, b = int(color[0]), int(color[1]), int(color[2])
                if r > g and r > b:
                    color_hint = "red"
                elif b > r and b > g:
                    color_hint = "blue"
                elif g > r and g > b:
                    color_hint = "forest"
            norm = _normalize_entity({
                "kind": layer.get("kind"),
                "trajectory": traj,
                "bounce": bounce,
                "color_hint": color_hint,
                "label": layer.get("id") or layer.get("kind"),
                "directionality": "horizontal" if traj in ("left", "right") else (
                    "vertical" if traj in ("up", "down") else "none"
                ),
                "expression": layer.get("expression") or "neutral",
                "personality": layer.get("personality") or "neutral",
                "gag": layer.get("gag") or "none",
                "sfx_on": layer.get("sfx_on") or [],
            })
            if not norm or norm["key"] in seen:
                continue
            seen.add(norm["key"])
            out.append(norm)
    return out


def grow_entities_from_spec(
    instruction: Any | None = None,
    spec: Any | None = None,
    *,
    prompt: str | None = None,
    collect_novel_for_sync: bool = True,
) -> tuple[int, list[dict[str, Any]]]:
    """
    Grow entity profiles from the current run's instruction/spec.
    Returns (added_count, novel_payloads) for POST /api/knowledge/discoveries.
    """
    entities = entities_from_instruction_or_spec(instruction, spec)
    if not entities:
        return 0, []
    novel: list[dict[str, Any]] = []
    for ent in entities:
        payload = {
            "key": ent["key"],
            "kind": ent["kind"],
            "trajectory": ent["trajectory"],
            "bounce": 1 if ent["bounce"] else 0,
            "color_hint": ent.get("color_hint"),
            "label": ent.get("label"),
            "directionality": ent.get("directionality") or "none",
            "expression": ent.get("expression") or "neutral",
            "personality": ent.get("personality") or "neutral",
            "gag": ent.get("gag") or "none",
            "entity_json": {
                "kind": ent["kind"],
                "trajectory": ent["trajectory"],
                "bounce": ent["bounce"],
                "color_hint": ent.get("color_hint"),
                "label": ent.get("label"),
                "directionality": ent.get("directionality"),
                "expression": ent.get("expression") or "neutral",
                "personality": ent.get("personality") or "neutral",
                "gag": ent.get("gag") or "none",
                "sfx_on": ent.get("sfx_on") or [],
            },
        }
        if prompt:
            payload["source_prompt"] = prompt[:80]
        if collect_novel_for_sync:
            novel.append(payload)
    return len(novel), novel

"""
Free-form mini-script parsing (Phase E).

Splits everyday prompts on "then" / beat separators into ordered actions
that map to NarrativeScript beats for ~5s clips.
"""
from __future__ import annotations

import re
from typing import Any

from .narrative_script import NarrativeScript, ScriptBeat


_SPLIT_RE = re.compile(
    r"\s*(?:,\s*then\s+|;\s*then\s+|\bthen\s+|→|->)\s*",
    re.IGNORECASE,
)

_ACTION_WORDS = {
    "bounce": "bounce",
    "bouncing": "bounce",
    "bounces": "bounce",
    "walk": "walk",
    "walking": "walk",
    "walks": "walk",
    "drift": "left",
    "drifting": "left",
    "slide": "left",
    "sliding": "left",
    "fly": "toward",
    "flying": "toward",
    "enter": "toward",
    "enters": "toward",
    "exit": "right",
    "exits": "right",
    "leave": "right",
    "leaves": "right",
    "rise": "up",
    "rising": "up",
    "fall": "down",
    "falling": "down",
    "pulse": "toward",
    "pulsing": "toward",
}


def split_script_clauses(prompt: str) -> list[str]:
    """Split a prompt into ordered beat clauses when separators are present."""
    raw = (prompt or "").strip()
    if not raw:
        return []
    parts = [p.strip(" .,!") for p in _SPLIT_RE.split(raw) if p and p.strip(" .,!")]
    return parts if len(parts) >= 2 else []


def _clause_action(clause: str) -> str:
    words = re.findall(r"[a-z0-9]+", clause.lower())
    for label in ("left", "right", "up", "down", "toward", "away"):
        if label in words:
            # Prefer explicit bounce/walk when both present
            if any(w in ("bounce", "bouncing", "bounces") for w in words):
                return "bounce"
            if any(w in ("walk", "walking", "walks") for w in words):
                return "walk"
            return label
    for w in words:
        if w in _ACTION_WORDS:
            return _ACTION_WORDS[w]
    return "left"


def _clause_sfx(clause: str, action: str) -> list[str]:
    words = set(re.findall(r"[a-z0-9]+", clause.lower()))
    sfx: list[str] = []
    if action == "bounce" or "bounce" in words or "bouncing" in words:
        sfx.append("bounce")
    if "whoosh" in words:
        sfx.append("whoosh")
    if "click" in words or "impact" in words or "thump" in words:
        sfx.append("click" if "click" in words else "impact")
    return sfx


def parse_freeform_mini_script(
    prompt: str,
    *,
    total_duration: float = 5.0,
) -> NarrativeScript | None:
    """
    If the prompt has then-separated beats, return a NarrativeScript.
    Otherwise return None (caller keeps single-entity path).
    """
    clauses = split_script_clauses(prompt)
    if not clauses:
        return None
    total_duration = max(3.0, float(total_duration))
    n = len(clauses)
    beat_dur = round(total_duration / n, 3)
    sections = ["intro", "drop", "break", "build"]
    beats: list[ScriptBeat] = []
    for i, clause in enumerate(clauses):
        action = _clause_action(clause)
        sfx = _clause_sfx(clause, action)
        beats.append(
            ScriptBeat(
                name=f"beat{i + 1}",
                duration_sec=beat_dur if i < n - 1 else round(total_duration - beat_dur * (n - 1), 3),
                text=None,
                music_section=sections[i % len(sections)],
                entity_action=action,
                sfx=sfx,
            )
        )
    topic = clauses[0][:60]
    return NarrativeScript(topic=topic, beats=beats)


def freeform_entities_from_prompt(
    prompt: str,
    *,
    base_entity: dict[str, Any] | None = None,
    total_duration: float = 5.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """
    Build timed entity hints + SFX from a then-separated prompt.
    Preserves kind/color/expression from base_entity when provided.
    """
    from .narrative_script import script_to_entities_and_sfx

    script = parse_freeform_mini_script(prompt, total_duration=total_duration)
    if not script:
        return None
    kind = "circle"
    if base_entity and isinstance(base_entity, dict):
        kind = str(base_entity.get("kind") or "circle")
    ents, sfx = script_to_entities_and_sfx(
        script,
        entity_kind=kind if kind in ("circle", "rect", "arrow", "character") else "circle",
    )
    if base_entity and isinstance(base_entity, dict):
        for e in ents:
            # Keep walk→character from script; otherwise inherit base kind
            if e.get("kind") != "character":
                e["kind"] = kind
            for k in ("color_hint", "expression", "personality", "directionality", "label"):
                if base_entity.get(k) is not None and not e.get(k):
                    e[k] = base_entity.get(k)
    return ents, sfx

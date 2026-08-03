"""
Multi-beat educational / narrative scripts (Phase 5 / Roadmap B–F).

Maps a topic prompt into intro → concept → example → recap beats with
per-beat entity actions, music section hints, expressions, and SFX.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScriptBeat:
    name: str  # hook | concept | example | recap | setup | beat | resolve
    duration_sec: float
    text: str | None = None
    music_section: str = "drop"  # intro|build|drop|break
    entity_action: str | None = None  # left|right|bounce|walk|toward
    sfx: list[str] = field(default_factory=list)
    position: str = "center"  # text overlay position
    font_size: int = 40
    expression: str | None = None  # happy|sad|angry|calm|excited|nervous
    callout: bool = False  # ring active subject during this beat
    arrow: bool = False  # draw arrow pointing at subject


@dataclass
class NarrativeScript:
    topic: str
    beats: list[ScriptBeat] = field(default_factory=list)

    @property
    def total_duration(self) -> float:
        return sum(b.duration_sec for b in self.beats)


_BEAT_EXPRESSION: dict[str, str] = {
    "hook": "excited",
    "setup": "calm",
    "concept": "calm",
    "example": "happy",
    "beat": "excited",
    "beat1": "calm",
    "beat2": "excited",
    "beat3": "happy",
    "recap": "calm",
    "resolve": "happy",
    "drop": "excited",
}

_BEAT_LAYOUT: dict[str, tuple[str, int]] = {
    "hook": ("top", 38),
    "setup": ("top", 36),
    "concept": ("top", 36),
    "example": ("center", 42),
    "beat": ("center", 40),
    "recap": ("bottom", 36),
    "resolve": ("bottom", 36),
}


def _layout_for_beat(name: str, index: int = 0) -> tuple[str, int]:
    key = (name or "").lower()
    if key in _BEAT_LAYOUT:
        return _BEAT_LAYOUT[key]
    positions = ["top", "center", "bottom", "center"]
    return positions[index % len(positions)], 36


def build_mini_scene_script(
    *,
    total_duration: float = 5.0,
    action: str = "bounce",
    topic: str | None = None,
) -> NarrativeScript:
    """
    Compact 3-beat arc for ~5s everyday mini-scenes: setup → beat → resolve.
    """
    total_duration = max(3.0, float(total_duration))
    weights = [0.25, 0.45, 0.30]
    names = ["setup", "beat", "resolve"]
    label = (topic or action).strip() or action
    texts = [None, None, None]
    if topic:
        texts = [label[:40], None, None]
    action_map = {
        "bounce": ["toward", "bounce", "right"],
        "walk": ["left", "walk", "right"],
        "drift": ["left", "right", "toward"],
        "toward": ["toward", "toward", "away"],
    }
    actions = action_map.get(action, ["left", action if action else "bounce", "right"])
    sections = ["intro", "drop", "break"]
    if action == "walk":
        # Keep walk SFX light — whoosh/click would auto-map to spin/double_take gags
        sfx_sets = [[], ["click"], []]
    else:
        sfx_sets = [["whoosh"], ["bounce"] if "bounce" in actions or action == "bounce" else ["click"], []]
    beats: list[ScriptBeat] = []
    for i, (w, name, text, act, section, sfx) in enumerate(
        zip(weights, names, texts, actions, sections, sfx_sets)
    ):
        pos, fs = _layout_for_beat(name, i)
        beats.append(
            ScriptBeat(
                name=name,
                duration_sec=round(total_duration * w, 2),
                text=text,
                music_section=section,
                entity_action=act,
                sfx=list(sfx),
                position=pos,
                font_size=fs,
                expression=_BEAT_EXPRESSION.get(name, "neutral"),
                callout=(name == "beat"),
            )
        )
    return NarrativeScript(topic=label, beats=beats)


def build_educational_script(
    topic: str,
    *,
    total_duration: float = 120.0,
    style: str = "educational",
) -> NarrativeScript:
    """
    Allocate a 4-beat educational arc. Durations scale to total_duration.
    For short clips (<=8s), use the compact mini-scene script instead.
    """
    topic = (topic or "the topic").strip() or "the topic"
    total_duration = max(5.0, float(total_duration))
    if total_duration <= 8.0:
        return build_mini_scene_script(total_duration=total_duration, action="bounce", topic=topic)

    # Prefer graphics template layout hints when available
    template_name = "explainer"
    if "tutorial" in (style or "").lower():
        template_name = "tutorial"
    elif "concept" in (style or "").lower():
        template_name = "concept_example_summary"

    weights = [0.15, 0.35, 0.30, 0.20]  # hook, concept, example, recap
    names = ["hook", "concept", "example", "recap"]
    texts = [
        f"What is {topic}?",
        f"The idea behind {topic}",
        f"An example of {topic}",
        f"Remember: {topic}",
    ]
    actions = ["toward", "left", "bounce", "right"]
    sections = ["intro", "build", "drop", "break"]
    sfx_sets = [[], ["whoosh"], ["bounce"], ["click"]]

    tpl_positions: list[tuple[str, int]] = []
    try:
        from ..graphics.templates import get_educational_template
        segs = get_educational_template(template_name, topic=topic)
        for seg in segs:
            tpl_positions.append((seg.position, int(seg.font_size)))
    except ImportError:
        pass

    beats: list[ScriptBeat] = []
    for i, (w, name, text, action, section, sfx) in enumerate(
        zip(weights, names, texts, actions, sections, sfx_sets)
    ):
        if i < len(tpl_positions):
            pos, fs = tpl_positions[i]
        else:
            pos, fs = _layout_for_beat(name, i)
        beats.append(
            ScriptBeat(
                name=name,
                duration_sec=round(total_duration * w, 2),
                text=text,
                music_section=section,
                entity_action=action,
                sfx=list(sfx),
                position=pos,
                font_size=fs,
                expression=_BEAT_EXPRESSION.get(name, "neutral"),
                callout=(name in ("concept", "example")),
                arrow=(name == "example"),
            )
        )
    return NarrativeScript(topic=topic, beats=beats)


def script_to_entities_and_sfx(
    script: NarrativeScript,
    *,
    entity_kind: str = "circle",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Flatten beats into timed entity hints + SFX (sequential windows, not overlapping)."""
    entities: list[dict[str, Any]] = []
    sfx_events: list[dict[str, Any]] = []
    t = 0.0
    for i, beat in enumerate(script.beats):
        traj = beat.entity_action or "left"
        bounce = traj == "bounce" or "bounce" in beat.sfx
        is_walk = traj == "walk"
        gag = None
        if bounce:
            gag = "squash"
        elif is_walk:
            # Walk bob comes from walk_cycle_keyframes — don't overwrite with spin/double_take
            gag = None
        elif traj == "toward":
            gag = "flourish"
        elif "whoosh" in beat.sfx:
            gag = "spin"
        elif (beat.name or "").lower() in ("hook", "beat"):
            gag = "double_take"
        # Beat pacing: setup slower, climax faster, resolve ease-out
        pacing = 1.0
        name = (beat.name or "").lower()
        if name in ("setup", "hook", "beat1"):
            pacing = 0.85
        elif name in ("beat", "example", "drop") or name.startswith("beat"):
            pacing = 1.15 if bounce else 1.05
        elif name in ("resolve", "recap"):
            pacing = 0.9
        expression = beat.expression or _BEAT_EXPRESSION.get(name, "neutral")
        entities.append({
            "id": f"beat{i}",
            "kind": "character" if traj == "walk" else entity_kind,
            "label": beat.name,
            "trajectory": "left" if traj == "walk" else traj,
            "bounce": bounce,
            "sfx_on": list(beat.sfx),
            "directionality": "horizontal",
            "t_start": round(t, 3),
            "t_end": round(t + beat.duration_sec, 3),
            "pacing": pacing,
            "gag": gag,
            "expression": expression,
        })
        for kind in beat.sfx:
            sfx_events.append({
                "kind": kind,
                "t_sec": round(t + beat.duration_sec * 0.5, 3),
                "strength": 0.75,
            })
        t += beat.duration_sec
    return entities, sfx_events


def script_beats_to_dicts(script: NarrativeScript) -> list[dict[str, Any]]:
    """Timed beat dicts for SceneSpec.script_beats (renderer text + music + callouts)."""
    out: list[dict[str, Any]] = []
    t = 0.0
    for beat in script.beats:
        t_end = t + float(beat.duration_sec)
        out.append({
            "name": beat.name,
            "text": beat.text,
            "t_start": round(t, 3),
            "t_end": round(t_end, 3),
            "duration_sec": round(float(beat.duration_sec), 3),
            "music_section": beat.music_section,
            "entity_action": beat.entity_action,
            "position": beat.position or "center",
            "font_size": int(beat.font_size or 40),
            "expression": beat.expression,
            "callout": bool(beat.callout),
            "arrow": bool(getattr(beat, "arrow", False)),
        })
        t = t_end
    return out


def resolve_overlay_at_time(
    script_beats: list[dict[str, Any]] | None,
    t: float,
    *,
    fallback_text: str | None = None,
    fallback_position: str = "center",
    fallback_font_size: int = 44,
) -> dict[str, Any]:
    """Active beat overlay metadata for time t."""
    defaults = {
        "text": fallback_text,
        "position": fallback_position,
        "font_size": fallback_font_size,
        "name": None,
        "callout": False,
        "arrow": False,
        "expression": None,
    }
    if not script_beats:
        return defaults

    def _from_beat(beat: dict[str, Any]) -> dict[str, Any]:
        text = beat.get("text")
        return {
            "text": str(text) if text else fallback_text,
            "position": str(beat.get("position") or fallback_position),
            "font_size": int(beat.get("font_size") or fallback_font_size),
            "name": beat.get("name"),
            "callout": bool(beat.get("callout")),
            "arrow": bool(beat.get("arrow")),
            "expression": beat.get("expression"),
        }

    for beat in script_beats:
        if not isinstance(beat, dict):
            continue
        t0 = float(beat.get("t_start", 0.0))
        t1 = float(beat.get("t_end", t0))
        if t0 <= t < t1:
            return _from_beat(beat)
    last = script_beats[-1]
    if isinstance(last, dict) and t >= float(last.get("t_start", 0.0)):
        return _from_beat(last)
    return defaults


def resolve_text_at_time(
    script_beats: list[dict[str, Any]] | None,
    t: float,
    *,
    fallback: str | None = None,
) -> str | None:
    """Pick the active beat's overlay text for time t (seconds into the clip)."""
    return resolve_overlay_at_time(script_beats, t, fallback_text=fallback).get("text")

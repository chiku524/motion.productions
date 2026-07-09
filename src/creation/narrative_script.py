"""
Multi-beat educational / narrative scripts (Phase 5 / Roadmap B–E scaffold).

Maps a topic prompt into intro → concept → example → recap beats with
per-beat entity actions, music section hints, and SFX.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScriptBeat:
    name: str  # hook | concept | example | recap
    duration_sec: float
    text: str | None = None
    music_section: str = "drop"  # intro|build|drop|break
    entity_action: str | None = None  # left|right|bounce|walk|toward
    sfx: list[str] = field(default_factory=list)


@dataclass
class NarrativeScript:
    topic: str
    beats: list[ScriptBeat] = field(default_factory=list)

    @property
    def total_duration(self) -> float:
        return sum(b.duration_sec for b in self.beats)


def build_educational_script(
    topic: str,
    *,
    total_duration: float = 120.0,
    style: str = "educational",
) -> NarrativeScript:
    """
    Allocate a 4-beat educational arc. Durations scale to total_duration.
    """
    topic = (topic or "the topic").strip() or "the topic"
    total_duration = max(8.0, float(total_duration))
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
    beats: list[ScriptBeat] = []
    for w, name, text, action, section, sfx in zip(weights, names, texts, actions, sections, sfx_sets):
        beats.append(
            ScriptBeat(
                name=name,
                duration_sec=round(total_duration * w, 2),
                text=text,
                music_section=section,
                entity_action=action,
                sfx=list(sfx),
            )
        )
    return NarrativeScript(topic=topic, beats=beats)


def script_to_entities_and_sfx(
    script: NarrativeScript,
    *,
    entity_kind: str = "circle",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Flatten beats into entity hints + timed SFX for InterpretedInstruction-like payloads."""
    entities: list[dict[str, Any]] = []
    sfx_events: list[dict[str, Any]] = []
    t = 0.0
    for i, beat in enumerate(script.beats):
        traj = beat.entity_action or "left"
        bounce = traj == "bounce" or "bounce" in beat.sfx
        entities.append({
            "id": f"beat{i}",
            "kind": "character" if traj == "walk" else entity_kind,
            "label": beat.name,
            "trajectory": "left" if traj == "walk" else traj,
            "bounce": bounce,
            "sfx_on": list(beat.sfx),
            "directionality": "horizontal",
        })
        for kind in beat.sfx:
            sfx_events.append({
                "kind": kind,
                "t_sec": round(t + beat.duration_sec * 0.5, 3),
                "strength": 0.75,
            })
        t += beat.duration_sec
    return entities, sfx_events

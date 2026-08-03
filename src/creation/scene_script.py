"""
Build SceneScript from InterpretedInstruction.
Genre-based shot sequences and pacing. Phase 2 + Phase 5.
"""
from ..cinematography import SceneScript, ShotSpec
from ..interpretation import InterpretedInstruction
from ..procedural.parser import SceneSpec
from ..procedural.data import (
    KEYWORD_TO_PACING,
    DEFAULT_PACING,
)
from ..narrative.genre_rules import get_genre_rules
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Genre → suggested shot sequence (for multi-shot videos)
GENRE_SHOT_SEQUENCES: dict[str, list[str]] = {
    "documentary": ["wide", "medium", "close", "medium"],
    "thriller": ["close", "medium", "wide"],
    "ad": ["medium", "close", "medium"],
    "tutorial": ["medium", "close"],
    "educational": ["wide", "medium", "close", "medium"],
    "explainer": ["medium", "close", "medium"],
    "general": ["medium"],
}


def build_scene_script_from_instruction(
    instruction: InterpretedInstruction,
    *,
    duration_seconds: float,
    segment_index: int | None = None,
    total_segments: int | None = None,
) -> SceneScript:
    """
    Build a SceneScript from instruction. Genre can influence shot sequence.
    Returns SceneScript with one or more shots; pacing applied per shot.
    """
    genre = getattr(instruction, "genre", "general") or "general"
    shot_seq = GENRE_SHOT_SEQUENCES.get(genre, ["medium"])
    base_pacing = _resolve_pacing(instruction)
    # Story-beat-aware pacing for long-form: setup slower, climax faster
    if segment_index is not None and total_segments is not None and total_segments > 1:
        progress = (segment_index - 1) / max(1, total_segments - 1)  # 0 = start, 1 = end
        if progress < 0.33:
            pacing = base_pacing * 0.85  # setup: slightly slower
        elif progress > 0.66:
            pacing = base_pacing * 0.9   # resolution: slightly slower
        else:
            pacing = base_pacing * 1.1   # development/climax: slightly faster
    else:
        pacing = base_pacing
    transition = getattr(instruction, "transition_in", "cut") or "cut"

    # Single-shot mode: one shot for whole duration
    if len(shot_seq) == 1 or duration_seconds < 6:
        shot_type = getattr(instruction, "shot_type", shot_seq[0]) or shot_seq[0]
        dur = duration_seconds
        shots = [
            ShotSpec(
                shot_type=shot_type,
                transition_in=transition,
                transition_out=getattr(instruction, "transition_out", transition) or transition,
                pacing=pacing,
                duration_seconds=dur,
            )
        ]
        return SceneScript(shots=shots, total_duration=dur)

    # Multi-shot: divide duration across shots so sum == duration_seconds
    n = min(len(shot_seq), max(1, int(duration_seconds / 3)))  # at least 3 sec per shot
    seq = shot_seq[:n]
    weights = [0.9 if i == 0 else 1.0 for i in range(n)]
    wsum = sum(weights) or 1.0
    raw = [duration_seconds * (w / wsum) for w in weights]
    # Floor at 1.5s then renormalize so total matches exactly
    floored = [max(1.5, d) for d in raw]
    fsum = sum(floored)
    if fsum > duration_seconds and n > 1:
        scale = duration_seconds / fsum
        floored = [max(1.2, d * scale) for d in floored]
        # Fix residual on last shot
        floored[-1] = max(1.2, duration_seconds - sum(floored[:-1]))
    else:
        floored[-1] = max(1.2, duration_seconds - sum(floored[:-1]))

    genre_rules = get_genre_rules(genre)
    preferred = getattr(genre_rules, "preferred_transition", transition) or transition
    shots: list[ShotSpec] = []
    for i, st in enumerate(seq):
        # Alternate cut/dissolve for multi-shot educational/documentary feel
        if i == 0:
            trans_in = transition
        elif preferred in ("dissolve", "fade") or genre in ("documentary", "educational", "explainer"):
            trans_in = "dissolve" if i % 2 == 1 else "cut"
        else:
            trans_in = transition
        trans_out = getattr(instruction, "transition_out", transition) or transition
        if i < n - 1:
            trans_out = trans_in if trans_in != "cut" else transition
        shots.append(
            ShotSpec(
                shot_type=st,
                transition_in=trans_in,
                transition_out=trans_out,
                pacing=pacing,
                duration_seconds=round(floored[i], 3),
            )
        )
    total = sum(s.duration_seconds for s in shots)
    # Final clamp: nudge last shot so sum == requested duration
    if abs(total - duration_seconds) > 0.02 and shots:
        shots[-1].duration_seconds = round(
            max(1.2, shots[-1].duration_seconds + (duration_seconds - total)), 3
        )
        total = sum(s.duration_seconds for s in shots)
    return SceneScript(shots=shots, total_duration=total)


def _resolve_pacing(instruction: InterpretedInstruction) -> float:
    """Resolve pacing from instruction (pacing_factor or keywords); fallback to genre rules. Phase 5."""
    pacing = getattr(instruction, "pacing_factor", None)
    if pacing is not None and pacing != 1.0:
        return max(0.3, min(2.0, float(pacing)))
    words = getattr(instruction, "keywords", []) or []
    for w in words:
        if w in KEYWORD_TO_PACING:
            return max(0.3, min(2.0, KEYWORD_TO_PACING[w]))
    genre = getattr(instruction, "genre", "general") or "general"
    rules = get_genre_rules(genre)
    return getattr(rules, "default_pacing", DEFAULT_PACING)


def cut_times_from_script(scene_script: SceneScript) -> list[float]:
    """Shot boundary times (seconds) for audio sync accents."""
    times, _ = cut_meta_from_script(scene_script)
    return times


def cut_meta_from_script(scene_script: SceneScript) -> tuple[list[float], list[str]]:
    """Shot boundaries with the transition type used at each cut."""
    times: list[float] = []
    types: list[str] = []
    shots = list(getattr(scene_script, "shots", None) or [])
    if len(shots) < 2:
        return [], []
    acc = 0.0
    for i, shot in enumerate(shots[:-1]):
        acc += float(getattr(shot, "duration_seconds", 0) or 0)
        if acc <= 0.05:
            continue
        times.append(acc)
        nxt = shots[i + 1]
        tt = (
            getattr(nxt, "transition_in", None)
            or getattr(shot, "transition_out", None)
            or "cut"
        )
        types.append(str(tt).lower())
    return times, types


def spec_from_shot(
    base_spec: SceneSpec,
    shot: ShotSpec,
) -> SceneSpec:
    """Create a SceneSpec for a single shot from base spec + shot overrides."""
    return SceneSpec(
        palette_name=base_spec.palette_name,
        motion_type=base_spec.motion_type,
        intensity=base_spec.intensity,
        raw_prompt=base_spec.raw_prompt,
        palette_colors=getattr(base_spec, "palette_colors", None),
        gradient_type=getattr(base_spec, "gradient_type", "vertical") or "vertical",
        camera_motion=getattr(base_spec, "camera_motion", "static") or "static",
        shape_overlay=getattr(base_spec, "shape_overlay", "none") or "none",
        shot_type=shot.shot_type,
        transition_in=shot.transition_in,
        transition_out=shot.transition_out,
        lighting_preset=getattr(base_spec, "lighting_preset", "neutral") or "neutral",
        genre=getattr(base_spec, "genre", "general") or "general",
        style=getattr(base_spec, "style", "cinematic") or "cinematic",
        composition_balance=getattr(base_spec, "composition_balance", "balanced") or "balanced",
        composition_symmetry=getattr(base_spec, "composition_symmetry", "slight") or "slight",
        pacing_factor=getattr(base_spec, "pacing_factor", 1.0) or 1.0,
        tension_curve=getattr(base_spec, "tension_curve", "standard") or "standard",
        audio_tempo=getattr(base_spec, "audio_tempo", "medium") or "medium",
        audio_mood=getattr(base_spec, "audio_mood", "neutral") or "neutral",
        audio_presence=getattr(base_spec, "audio_presence", "ambient") or "ambient",
        audio_genre=getattr(base_spec, "audio_genre", "none") or "none",
        audio_vocals=bool(getattr(base_spec, "audio_vocals", False)),
        motion_directionality=getattr(base_spec, "motion_directionality", "none") or "none",
        motion_smoothness=getattr(base_spec, "motion_smoothness", "smooth") or "smooth",
        motion_rhythm=getattr(base_spec, "motion_rhythm", "steady") or "steady",
        sfx_events=getattr(base_spec, "sfx_events", None),
        scene_layers=getattr(base_spec, "scene_layers", None),
        text_overlay=getattr(base_spec, "text_overlay", None),
        text_position=getattr(base_spec, "text_position", "center") or "center",
        educational_template=getattr(base_spec, "educational_template", None),
        script_beats=getattr(base_spec, "script_beats", None),
        music_sections=getattr(base_spec, "music_sections", None),
        depth_parallax=getattr(base_spec, "depth_parallax", False),
        film_look=bool(getattr(base_spec, "film_look", False)),
        render_engine=getattr(base_spec, "render_engine", "procedural") or "procedural",
        pure_colors=getattr(base_spec, "pure_colors", None),
        creation_mode=getattr(base_spec, "creation_mode", "blended") or "blended",
        pure_sounds=getattr(base_spec, "pure_sounds", None),
        cut_times=getattr(base_spec, "cut_times", None),
        cut_transitions=getattr(base_spec, "cut_transitions", None),
        camera_steadiness=getattr(base_spec, "camera_steadiness", "stable") or "stable",
        color_temperature=getattr(base_spec, "color_temperature", "neutral") or "neutral",
    )

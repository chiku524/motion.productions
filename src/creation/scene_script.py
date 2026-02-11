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

    # Multi-shot: divide duration across shots
    n = min(len(shot_seq), max(1, int(duration_seconds / 3)))  # at least 3 sec per shot
    seq = shot_seq[:n]
    base_dur = duration_seconds / n
    shots: list[ShotSpec] = []
    for i, st in enumerate(seq):
        # Slight variation per shot
        dur = base_dur * (0.9 if i == 0 else 1.0) if i < n - 1 else duration_seconds - sum(s.duration_seconds for s in shots)
        dur = max(2.0, dur)
        trans_in = transition if i == 0 else transition
        trans_out = transition if i < n - 1 else (getattr(instruction, "transition_out", transition) or transition)
        shots.append(
            ShotSpec(
                shot_type=st,
                transition_in=trans_in,
                transition_out=trans_out,
                pacing=pacing,
                duration_seconds=dur,
            )
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
        gradient_type=getattr(base_spec, "gradient_type", "vertical") or "vertical",
        camera_motion=getattr(base_spec, "camera_motion", "static") or "static",
        shape_overlay=getattr(base_spec, "shape_overlay", "none") or "none",
        shot_type=shot.shot_type,
        transition_in=shot.transition_in,
        transition_out=shot.transition_out,
        lighting_preset=getattr(base_spec, "lighting_preset", "neutral") or "neutral",
        genre=getattr(base_spec, "genre", "general") or "general",
        style=getattr(base_spec, "style", "cinematic") or "cinematic",
        text_overlay=getattr(base_spec, "text_overlay", None),
        text_position=getattr(base_spec, "text_position", "center") or "center",
        educational_template=getattr(base_spec, "educational_template", None),
        depth_parallax=getattr(base_spec, "depth_parallax", False),
    )

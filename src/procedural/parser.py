"""
Prompt → scene spec using only our rules and data. No neural network, no external model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .data import (
    KEYWORD_TO_DEPTH,
    KEYWORD_TO_PALETTE,
    KEYWORD_TO_MOTION,
    KEYWORD_TO_INTENSITY,
    KEYWORD_TO_GRADIENT,
    KEYWORD_TO_CAMERA,
    KEYWORD_TO_SHAPE,
    KEYWORD_TO_SHOT,
    KEYWORD_TO_TRANSITION,
    KEYWORD_TO_LIGHTING,
    KEYWORD_TO_GENRE,
    KEYWORD_TO_COMPOSITION_BALANCE,
    KEYWORD_TO_COMPOSITION_SYMMETRY,
    KEYWORD_TO_TENSION,
    KEYWORD_TO_AUDIO_TEMPO,
    KEYWORD_TO_AUDIO_MOOD,
    KEYWORD_TO_AUDIO_PRESENCE,
    DEFAULT_PALETTE,
    DEFAULT_MOTION,
    DEFAULT_INTENSITY,
    DEFAULT_GRADIENT,
    DEFAULT_CAMERA,
    DEFAULT_SHAPE,
    DEFAULT_SHOT,
    DEFAULT_TRANSITION,
    DEFAULT_LIGHTING,
    DEFAULT_GENRE,
    DEFAULT_COMPOSITION_BALANCE,
    DEFAULT_COMPOSITION_SYMMETRY,
    DEFAULT_TENSION,
    DEFAULT_AUDIO_TEMPO,
    DEFAULT_AUDIO_MOOD,
    DEFAULT_AUDIO_PRESENCE,
    DEFAULT_PACING,
)


@dataclass
class SceneSpec:
    """Result of parsing a prompt: palette, motion, intensity, gradient, camera, etc.
    INTENDED_LOOP: palette_colors from blending primitives + learned; else palette_name lookup.
    """
    palette_name: str
    motion_type: str
    intensity: float
    palette_colors: list[tuple[int, int, int]] | None = None  # blended from primitives + learned
    raw_prompt: str
    gradient_type: str = "vertical"   # vertical | radial | angled | horizontal
    camera_motion: str = "static"     # static | zoom | zoom_out | pan | rotate
    shape_overlay: str = "none"       # none | circle | rect
    shot_type: str = "medium"         # wide | medium | close | pov | handheld
    transition_in: str = "cut"        # cut | fade | dissolve | wipe
    transition_out: str = "cut"
    lighting_preset: str = "neutral"  # noir | golden_hour | neon | documentary | moody
    genre: str = "general"            # documentary | thriller | ad | tutorial | educational
    composition_balance: str = "balanced"
    composition_symmetry: str = "slight"
    pacing_factor: float = 1.0
    tension_curve: str = "standard"
    audio_tempo: str = "medium"
    audio_mood: str = "neutral"
    audio_presence: str = "ambient"
    text_overlay: str | None = None   # Phase 4: text to display
    text_position: str = "center"
    educational_template: str | None = None
    depth_parallax: bool = False      # Phase 7: enable 2.5D parallax


def parse_prompt_to_spec(prompt: str, *, seed: int | None = None) -> SceneSpec:
    """
    Turn a text prompt into a scene specification using only our keyword tables.
    Blends at primitive level: all matching palette/motion keywords → single blended value.
    """
    from .data.palettes import PALETTES
    from ..knowledge.blending import blend_palettes, blend_motion_params

    prompt = (prompt or "").strip().lower()
    words = set(re.findall(r"[a-z]+", prompt))

    # Collect all palette and motion hints (primitive-level blending)
    palette_hints: list[str] = []
    seen_p: set[str] = set()
    for w in words:
        if w in KEYWORD_TO_PALETTE:
            p = KEYWORD_TO_PALETTE[w]
            if p not in seen_p:
                palette_hints.append(p)
                seen_p.add(p)
    if not palette_hints:
        palette_hints = [DEFAULT_PALETTE]

    motion_hints: list[str] = []
    seen_m: set[str] = set()
    for w in words:
        if w in KEYWORD_TO_MOTION:
            m = KEYWORD_TO_MOTION[w]
            if m not in seen_m:
                motion_hints.append(m)
                seen_m.add(m)
    if not motion_hints:
        motion_hints = [DEFAULT_MOTION]

    # Blend palette primitives → single palette_colors
    result = list(PALETTES.get(palette_hints[0], PALETTES["default"]))
    for name in palette_hints[1:]:
        other = PALETTES.get(name, PALETTES["default"])
        result = blend_palettes(result, other, weight=0.5)
    palette_colors = result

    # Blend motion primitives → single motion_type
    motion = motion_hints[0]
    for hint in motion_hints[1:]:
        motion = blend_motion_params(motion, hint, weight=0.5)

    palette = palette_hints[0]  # for palette_name (label/fallback)

    intensity = DEFAULT_INTENSITY
    for w in words:
        if w in KEYWORD_TO_INTENSITY:
            intensity = KEYWORD_TO_INTENSITY[w]
            break

    gradient = DEFAULT_GRADIENT
    for w in words:
        if w in KEYWORD_TO_GRADIENT:
            gradient = KEYWORD_TO_GRADIENT[w]
            break

    camera = DEFAULT_CAMERA
    for w in words:
        if w in KEYWORD_TO_CAMERA:
            camera = KEYWORD_TO_CAMERA[w]
            break

    shape = DEFAULT_SHAPE
    for w in words:
        if w in KEYWORD_TO_SHAPE:
            shape = KEYWORD_TO_SHAPE[w]
            break

    shot = DEFAULT_SHOT
    for w in words:
        if w in KEYWORD_TO_SHOT:
            shot = KEYWORD_TO_SHOT[w]
            break

    transition = DEFAULT_TRANSITION
    for w in words:
        if w in KEYWORD_TO_TRANSITION:
            transition = KEYWORD_TO_TRANSITION[w]
            break

    lighting = DEFAULT_LIGHTING
    for w in words:
        if w in KEYWORD_TO_LIGHTING:
            lighting = KEYWORD_TO_LIGHTING[w]
            break

    genre_val = DEFAULT_GENRE
    for w in words:
        if w in KEYWORD_TO_GENRE:
            genre_val = KEYWORD_TO_GENRE[w]
            break

    comp_balance = DEFAULT_COMPOSITION_BALANCE
    for w in words:
        if w in KEYWORD_TO_COMPOSITION_BALANCE:
            comp_balance = KEYWORD_TO_COMPOSITION_BALANCE[w]
            break

    comp_symmetry = DEFAULT_COMPOSITION_SYMMETRY
    for w in words:
        if w in KEYWORD_TO_COMPOSITION_SYMMETRY:
            comp_symmetry = KEYWORD_TO_COMPOSITION_SYMMETRY[w]
            break

    tension = DEFAULT_TENSION
    for w in words:
        if w in KEYWORD_TO_TENSION:
            tension = KEYWORD_TO_TENSION[w]
            break

    audio_t = DEFAULT_AUDIO_TEMPO
    for w in words:
        if w in KEYWORD_TO_AUDIO_TEMPO:
            audio_t = KEYWORD_TO_AUDIO_TEMPO[w]
            break

    audio_m = DEFAULT_AUDIO_MOOD
    for w in words:
        if w in KEYWORD_TO_AUDIO_MOOD:
            audio_m = KEYWORD_TO_AUDIO_MOOD[w]
            break

    audio_p = DEFAULT_AUDIO_PRESENCE
    for w in words:
        if w in KEYWORD_TO_AUDIO_PRESENCE:
            audio_p = KEYWORD_TO_AUDIO_PRESENCE[w]
            break

    pacing = DEFAULT_PACING
    for w in words:
        if w in KEYWORD_TO_PACING:
            pacing = max(0.3, min(2.0, float(KEYWORD_TO_PACING[w])))
            break

    depth_parallax = any(w in KEYWORD_TO_DEPTH and KEYWORD_TO_DEPTH[w] for w in words)

    return SceneSpec(
        palette_name=palette,
        motion_type=motion,
        palette_colors=palette_colors,
        intensity=float(intensity),
        raw_prompt=prompt,
        gradient_type=gradient,
        camera_motion=camera,
        shape_overlay=shape,
        shot_type=shot,
        transition_in=transition,
        transition_out=transition,
        lighting_preset=lighting,
        genre=genre_val,
        composition_balance=comp_balance,
        composition_symmetry=comp_symmetry,
        pacing_factor=pacing,
        tension_curve=tension,
        audio_tempo=audio_t,
        audio_mood=audio_m,
        audio_presence=audio_p,
        text_overlay=None,
        text_position="center",
        educational_template=None,
        depth_parallax=depth_parallax,
    )

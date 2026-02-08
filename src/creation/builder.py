"""
Build output from extracted knowledge.
Converts InterpretedInstruction (+ optional knowledge lookup) → SceneSpec for rendering.
"""
from typing import Any

from ..interpretation import InterpretedInstruction
from ..procedural.parser import SceneSpec


def build_spec_from_instruction(
    instruction: InterpretedInstruction,
    *,
    knowledge: dict[str, Any] | None = None,
) -> SceneSpec:
    """
    Build a SceneSpec from an InterpretedInstruction.

    If knowledge is provided (from learning/aggregate), uses it to refine
    palette/motion/intensity when the instruction is ambiguous or when
    knowledge suggests better parameters for desired outcomes.

    Args:
        instruction: Precise interpretation of user input
        knowledge: Optional aggregated learning (by_keyword, by_palette, overall)

    Returns:
        SceneSpec ready for the procedural renderer
    """
    palette = instruction.palette_name
    motion = instruction.motion_type
    intensity = instruction.intensity
    gradient = getattr(instruction, "gradient_type", "vertical") or "vertical"
    camera = getattr(instruction, "camera_motion", "static") or "static"
    shape = getattr(instruction, "shape_overlay", "none") or "none"

    # Optional: refine from knowledge
    if knowledge:
        palette, motion, intensity = _refine_from_knowledge(
            palette, motion, intensity,
            instruction.keywords,
            knowledge,
        )

    return SceneSpec(
        palette_name=palette,
        motion_type=motion,
        intensity=intensity,
        raw_prompt=instruction.raw_prompt,
        gradient_type=gradient,
        camera_motion=camera,
        shape_overlay=shape,
    )


def _refine_from_knowledge(
    palette: str,
    motion: str,
    intensity: float,
    keywords: list[str],
    knowledge: dict[str, Any],
) -> tuple[str, str, float]:
    """
    Optionally refine palette/motion/intensity from accumulated knowledge.
    Uses by_keyword and by_palette to pick parameters that produced good outcomes.
    """
    by_keyword = knowledge.get("by_keyword", {})
    by_palette = knowledge.get("by_palette", {})
    overall = knowledge.get("overall", {})

    # If we have keyword stats, prefer palette/motion that had high counts and reasonable motion
    best_motion = motion
    best_intensity = intensity
    MOTION_LOW, MOTION_HIGH = 1.0, 25.0  # "good" motion range from analysis

    for kw in keywords:
        data = by_keyword.get(kw, {})
        if not data:
            continue
        count = data.get("count", 0)
        mean_motion = data.get("mean_motion_level", 0)
        if count >= 2 and MOTION_LOW <= mean_motion <= MOTION_HIGH:
            # This keyword produced good motion; keep current params
            best_motion = motion
            best_intensity = intensity
            break

    # If palette has good stats, keep it
    pal_data = by_palette.get(palette, {})
    if pal_data.get("count", 0) >= 2:
        pal_motion = pal_data.get("mean_motion_level", 0)
        if not (MOTION_LOW <= pal_motion <= MOTION_HIGH):
            # Palette tended to produce bad motion; slightly adjust intensity
            if pal_motion < MOTION_LOW:
                best_intensity = min(1.0, intensity + 0.1)
            else:
                best_intensity = max(0.1, intensity - 0.1)

    return palette, best_motion, best_intensity

"""
Growth: extraction → compare → add novel.
Extracts from every domain; records per-domain and full blend discoveries.
"""
from pathlib import Path
from typing import Any

from .registry import (
    load_registry,
    add_learned_color,
    add_learned_motion_profile,
    add_learned_lighting_profile,
    add_learned_composition_profile,
    add_learned_graphics_profile,
    add_learned_temporal_profile,
    add_learned_technical_profile,
    extract_and_record_full_blend,
    is_color_novel,
)
from .schema import BaseKnowledgeExtract
from .domain_extraction import extract_to_domains, analysis_dict_to_domains
from .name_reserve import ensure_reserve


def grow_from_extract(
    extract: BaseKnowledgeExtract,
    *,
    prompt: str = "",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Take an extraction result and grow the knowledge base.
    Extracts from every domain; adds novel values; records full blend.
    Returns a summary of what was added.
    """
    ensure_reserve(1000, config=config)
    added: dict[str, Any] = {"colors": 0, "motion": 0, "lighting": 0, "composition": 0,
                             "graphics": 0, "temporal": 0, "technical": 0, "full_blend": 0}

    # Color
    r, g, b = extract.dominant_color_rgb
    if r is not None and g is not None and b is not None:
        learned = load_registry("learned_colors", config)
        if is_color_novel(r, g, b, learned):
            add_learned_color(r, g, b, source_prompt=prompt, config=config)
            added["colors"] += 1

    # Motion (only count when novel)
    if add_learned_motion_profile(
        extract.motion_level, extract.motion_std, extract.motion_trend,
        source_prompt=prompt, config=config,
    ) is not None:
        added["motion"] += 1

    # Lighting
    if add_learned_lighting_profile(
        extract.mean_brightness, extract.mean_contrast, extract.mean_saturation,
        source_prompt=prompt, config=config,
    ):
        added["lighting"] += 1

    # Composition
    if add_learned_composition_profile(
        extract.center_of_mass_x, extract.center_of_mass_y, extract.luminance_balance,
        source_prompt=prompt, config=config,
    ):
        added["composition"] += 1

    # Graphics
    if add_learned_graphics_profile(
        extract.edge_density, extract.spatial_variance, extract.busyness,
        source_prompt=prompt, config=config,
    ):
        added["graphics"] += 1

    # Temporal
    if add_learned_temporal_profile(
        extract.duration_seconds, extract.motion_trend,
        source_prompt=prompt, config=config,
    ):
        added["temporal"] += 1

    # Technical
    if add_learned_technical_profile(
        extract.width, extract.height, extract.fps,
        source_prompt=prompt, config=config,
    ):
        added["technical"] += 1

    # Blend extraction: record the full blend of all domains
    domains = extract_to_domains(extract)
    extract_and_record_full_blend(domains, source_prompt=prompt, config=config)
    added["full_blend"] += 1

    return added


def grow_from_analysis(
    analysis: dict[str, Any],
    *,
    prompt: str = "",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Grow from OutputAnalysis.to_dict() or similar analysis structure.
    Extracts from every available domain; records full blend.
    """
    ensure_reserve(1000, config=config)
    added: dict[str, Any] = {"colors": 0, "motion": 0, "lighting": 0, "composition": 0,
                             "graphics": 0, "temporal": 0, "technical": 0, "full_blend": 0}

    # Color
    dom = analysis.get("dominant_color_rgb")
    if dom and len(dom) >= 3:
        r, g, b = float(dom[0]), float(dom[1]), float(dom[2])
        learned = load_registry("learned_colors", config)
        if is_color_novel(r, g, b, learned):
            add_learned_color(r, g, b, source_prompt=prompt, config=config)
            added["colors"] += 1

    # Motion (only count when novel)
    motion_level = analysis.get("motion_level", 0)
    motion_std = analysis.get("motion_std", 0)
    motion_trend = analysis.get("motion_trend", "steady") or "steady"
    if add_learned_motion_profile(
        motion_level, motion_std, motion_trend,
        source_prompt=prompt, config=config,
    ) is not None:
        added["motion"] += 1

    # Lighting (analysis has brightness, contrast)
    if add_learned_lighting_profile(
        analysis.get("mean_brightness", 128),
        analysis.get("mean_contrast", 50),
        1.0,  # saturation not in analysis
        source_prompt=prompt, config=config,
    ):
        added["lighting"] += 1

    # Blend extraction: full blend from analysis domains
    domains = analysis_dict_to_domains(analysis)
    extract_and_record_full_blend(domains, source_prompt=prompt, config=config)
    added["full_blend"] += 1

    return added

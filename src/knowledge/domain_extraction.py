"""
Domain extraction: map BaseKnowledgeExtract to per-domain structures.
Every aspect (every domain) is extracted and structured for growth.
"""
from typing import Any

from .schema import BaseKnowledgeExtract


def extract_to_domains(extract: BaseKnowledgeExtract) -> dict[str, dict[str, Any]]:
    """
    Map a full extraction to per-domain structures.
    Each domain gets a dict suitable for comparison and growth.
    """
    return {
        "color": {
            "dominant_rgb": extract.dominant_color_rgb,
            "mean_brightness": extract.mean_brightness,
            "mean_contrast": extract.mean_contrast,
            "mean_saturation": extract.mean_saturation,
            "mean_hue": extract.mean_hue,
            "color_variance": extract.color_variance,
            "color_std_over_time": extract.color_std_over_time,
        },
        "lighting": {
            "brightness": extract.mean_brightness,
            "contrast": extract.mean_contrast,
            "saturation": extract.mean_saturation,
            "key_fill_approx": min(1.0, extract.mean_brightness / 255.0),
        },
        "motion": {
            "motion_level": extract.motion_level,
            "motion_std": extract.motion_std,
            "motion_trend": extract.motion_trend,
        },
        "composition": {
            "center_of_mass_x": extract.center_of_mass_x,
            "center_of_mass_y": extract.center_of_mass_y,
            "luminance_balance": extract.luminance_balance,
        },
        "graphics": {
            "edge_density": extract.edge_density,
            "spatial_variance": extract.spatial_variance,
            "gradient_strength": extract.gradient_strength,
            "busyness": extract.busyness,
        },
        "temporal": {
            "duration_seconds": extract.duration_seconds,
            "fps": extract.fps,
            "motion_trend": extract.motion_trend,
        },
        "technical": {
            "width": extract.width,
            "height": extract.height,
            "fps": extract.fps,
            "duration_seconds": extract.duration_seconds,
        },
    }


def analysis_dict_to_domains(analysis: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map analysis dict (from OutputAnalysis.to_dict()) to per-domain structures."""
    return {
        "color": {
            "dominant_rgb": analysis.get("dominant_color_rgb", (0, 0, 0)),
            "mean_brightness": analysis.get("mean_brightness", 0),
            "mean_contrast": analysis.get("mean_contrast", 0),
        },
        "lighting": {
            "brightness": analysis.get("mean_brightness", 0),
            "contrast": analysis.get("mean_contrast", 0),
        },
        "motion": {
            "motion_level": analysis.get("motion_level", 0),
            "motion_std": analysis.get("motion_std", 0),
            "motion_trend": "steady",
        },
        "composition": {},
        "graphics": {},
        "temporal": {"duration_seconds": analysis.get("duration_seconds", 0)},
        "technical": {},
    }

"""
Origins: primitives of every film/video aspect. Base knowledge.
Every aspect that resides within filmmaking/video-making has its origins here.
"""
from dataclasses import dataclass, field
from typing import Any


# -----------------------------------------------------------------------------
# COLOR — primitives: RGB, HSL, contrast, saturation
# -----------------------------------------------------------------------------
COLOR_ORIGINS = {
    "rgb_primaries": [(255, 0, 0), (0, 255, 0), (0, 0, 255)],
    "hsl_dimensions": ["hue", "saturation", "lightness"],
    "contrast_values": [0.5, 0.75, 1.0, 1.25, 1.5],
    "saturation_values": [0.0, 0.5, 1.0, 1.25, 1.5],
    "brightness_range": (0.0, 255.0),
}


# -----------------------------------------------------------------------------
# LIGHTING — primitives: key, fill, rim, ambient, temperature
# -----------------------------------------------------------------------------
LIGHTING_ORIGINS = {
    "key_intensity": [0.5, 0.75, 1.0, 1.25],
    "fill_ratio": [0.2, 0.4, 0.6, 0.8],
    "rim_strength": [0.0, 0.2, 0.5, 0.8],
    "ambient_level": [0.2, 0.4, 0.6, 0.8],
    "color_temperature": ["warm", "neutral", "cool"],
    "contrast_ratio": ["flat", "normal", "high", "chiaroscuro"],
}


# -----------------------------------------------------------------------------
# MOTION — primitives: speed, smoothness, directionality, rhythm
# -----------------------------------------------------------------------------
MOTION_ORIGINS = {
    "speed": ["static", "slow", "medium", "fast"],
    "smoothness": ["jerky", "rough", "smooth", "fluid"],
    "directionality": ["none", "horizontal", "vertical", "diagonal", "radial"],
    "rhythm": ["steady", "pulsing", "wave", "random"],
    "acceleration": ["constant", "ease_in", "ease_out", "ease_in_out"],
}


# -----------------------------------------------------------------------------
# CAMERA — primitives: pan, tilt, dolly, crane, zoom, static
# -----------------------------------------------------------------------------
CAMERA_ORIGINS = {
    "motion_type": ["static", "pan", "tilt", "dolly", "crane", "zoom", "zoom_out", "handheld"],
    "speed": ["slow", "medium", "fast"],
    "steadiness": ["locked", "stable", "handheld", "shaky"],
}


# -----------------------------------------------------------------------------
# COMPOSITION — primitives: framing, balance, symmetry
# -----------------------------------------------------------------------------
COMPOSITION_ORIGINS = {
    "framing": ["wide", "medium", "close", "extreme_close", "pov"],
    "rule_of_thirds": [True, False],
    "center_of_mass_range": ((0.0, 1.0), (0.0, 1.0)),
    "balance": ["left_heavy", "balanced", "right_heavy", "top_heavy", "bottom_heavy"],
    "symmetry": ["asymmetric", "slight", "bilateral"],
}


# -----------------------------------------------------------------------------
# TEMPORAL — primitives: pacing, cut frequency, shot length
# -----------------------------------------------------------------------------
TEMPORAL_ORIGINS = {
    "pacing": [0.5, 0.75, 1.0, 1.25, 1.5],
    "cut_frequency": ["none", "rare", "normal", "fast", "rapid"],
    "shot_length_seconds": [1.0, 2.0, 4.0, 6.0, 10.0],
    "story_beats": ["setup", "development", "climax", "resolution"],
}


# -----------------------------------------------------------------------------
# TRANSITIONS — primitives: cut, fade, dissolve, wipe
# -----------------------------------------------------------------------------
TRANSITION_ORIGINS = {
    "type": ["cut", "fade", "dissolve", "wipe"],
    "duration_seconds": [0.0, 0.25, 0.5, 1.0],
}


# -----------------------------------------------------------------------------
# GRAPHICS / SPATIAL — primitives: gradient, shape, texture
# -----------------------------------------------------------------------------
GRAPHICS_ORIGINS = {
    "gradient_type": ["vertical", "horizontal", "radial", "angled"],
    "shape_overlay": ["none", "circle", "rect"],
    "edge_density_range": (0.0, 1.0),
    "spatial_variance_range": (0.0, 1.0),
    "busyness_range": (0.0, 1.0),
}


# -----------------------------------------------------------------------------
# AUDIO — primitives: tempo, mood, intensity, silence
# -----------------------------------------------------------------------------
AUDIO_ORIGINS = {
    "tempo": ["slow", "medium", "fast"],
    "mood": ["neutral", "calm", "tense", "uplifting", "dark"],
    "intensity": [0.0, 0.25, 0.5, 0.75, 1.0],
    "presence": ["silence", "ambient", "music", "sfx", "full"],
}


# -----------------------------------------------------------------------------
# NARRATIVE — primitives: genre, tone, style
# -----------------------------------------------------------------------------
NARRATIVE_ORIGINS = {
    "genre": ["general", "documentary", "thriller", "ad", "tutorial", "educational", "explainer"],
    "tone": ["neutral", "dreamy", "dark", "bright", "calm", "energetic", "moody"],
    "style": ["cinematic", "abstract", "minimal", "realistic", "anime"],
    "tension_curve": ["flat", "slow_build", "standard", "immediate"],
}


# -----------------------------------------------------------------------------
# TECHNICAL — primitives: resolution, fps, aspect
# -----------------------------------------------------------------------------
TECHNICAL_ORIGINS = {
    "resolution": [(256, 256), (512, 512), (720, 480), (1280, 720), (1920, 1080)],
    "fps": [12, 24, 30, 60],
    "aspect_ratio": ["1:1", "16:9", "4:3", "9:16"],
}


# -----------------------------------------------------------------------------
# DEPTH / REALISM — primitives: parallax, layers
# -----------------------------------------------------------------------------
DEPTH_ORIGINS = {
    "parallax_strength": [0.0, 0.05, 0.1, 0.2],
    "layer_count": [1, 2, 3, 4],
}


def get_all_origins() -> dict[str, Any]:
    """Return the full origins registry for every film/video aspect."""
    return {
        "color": COLOR_ORIGINS,
        "lighting": LIGHTING_ORIGINS,
        "motion": MOTION_ORIGINS,
        "camera": CAMERA_ORIGINS,
        "composition": COMPOSITION_ORIGINS,
        "temporal": TEMPORAL_ORIGINS,
        "transition": TRANSITION_ORIGINS,
        "graphics": GRAPHICS_ORIGINS,
        "audio": AUDIO_ORIGINS,
        "narrative": NARRATIVE_ORIGINS,
        "technical": TECHNICAL_ORIGINS,
        "depth": DEPTH_ORIGINS,
    }


def get_origin_domains() -> list[str]:
    """Return list of all origin domain names."""
    return list(get_all_origins().keys())

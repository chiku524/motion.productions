"""
Interpreter: analyze a generated video and produce a structured description.
Uses the base-knowledge extractor for full extraction; OutputAnalysis for backward compat.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metrics import (
    color_histogram,
    frame_difference,
    dominant_colors,
    brightness_and_contrast,
)


@dataclass
class OutputAnalysis:
    """Structured interpretation of a generated video (our algorithms only)."""
    path: str
    num_frames_sampled: int
    duration_seconds: float
    # Color
    mean_brightness: float
    mean_contrast: float
    dominant_color_rgb: tuple[float, float, float]
    histogram_bins: int
    # Motion (frame-to-frame difference)
    motion_level: float  # mean of frame diffs
    motion_std: float
    # Consistency (variance of per-frame brightness over time)
    brightness_std_over_time: float
    # Which of our palettes is closest (by name)
    closest_palette: str
    palette_distance: float
    # Raw for learning
    per_frame_brightness: list[float] = field(default_factory=list)
    per_frame_motion: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "path": self.path,
            "num_frames_sampled": self.num_frames_sampled,
            "duration_seconds": self.duration_seconds,
            "mean_brightness": self.mean_brightness,
            "mean_contrast": self.mean_contrast,
            "dominant_color_rgb": list(self.dominant_color_rgb),
            "histogram_bins": self.histogram_bins,
            "motion_level": self.motion_level,
            "motion_std": self.motion_std,
            "brightness_std_over_time": self.brightness_std_over_time,
            "closest_palette": self.closest_palette,
            "palette_distance": self.palette_distance,
        }
        if self.per_frame_brightness:
            d["per_frame_brightness"] = self.per_frame_brightness
        if self.per_frame_motion:
            d["per_frame_motion"] = self.per_frame_motion
        return d


def _extract_to_output_analysis(ext: "BaseKnowledgeExtract") -> OutputAnalysis:
    """Convert BaseKnowledgeExtract to OutputAnalysis for backward compatibility."""
    bins = len(ext.histogram_r) if ext.histogram_r else 16
    return OutputAnalysis(
        path=ext.path,
        num_frames_sampled=ext.num_frames_sampled,
        duration_seconds=ext.duration_seconds,
        mean_brightness=ext.mean_brightness,
        mean_contrast=ext.mean_contrast,
        dominant_color_rgb=ext.dominant_color_rgb,
        histogram_bins=bins,
        motion_level=ext.motion_level,
        motion_std=ext.motion_std,
        brightness_std_over_time=ext.brightness_std_over_time,
        closest_palette=ext.closest_palette,
        palette_distance=ext.palette_distance,
        per_frame_brightness=ext.brightness_per_frame[:50] if ext.brightness_per_frame else [],
        per_frame_motion=ext.motion_per_frame[:50] if ext.motion_per_frame else [],
    )


def analyze_video(
    video_path: str | Path,
    *,
    max_frames: int = 60,
    sample_every: int = 1,
) -> OutputAnalysis:
    """
    Interpret a generated video using base-knowledge extraction.
    Returns OutputAnalysis (backward compat). Use extract_from_video for full extract.
    """
    from ..knowledge import extract_from_video, BaseKnowledgeExtract
    ext = extract_from_video(
        video_path,
        max_frames=max_frames,
        sample_every=sample_every,
    )
    return _extract_to_output_analysis(ext)

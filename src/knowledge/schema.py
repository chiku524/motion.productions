"""
Base knowledge schema: every aspect that resides within video files.
This is the single source of truth for what we extract.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BaseKnowledgeExtract:
    """
    Comprehensive extraction of every aspect within a video file.
    Colors, graphics, resolutions, motion, frame rate, composition, etc.
    """

    # --- Video metadata ---
    path: str
    width: int
    height: int
    fps: float
    duration_seconds: float
    num_frames_sampled: int
    num_frames_total: int | None = None

    # --- Color ---
    mean_brightness: float = 0.0
    mean_contrast: float = 0.0
    mean_saturation: float = 0.0
    mean_hue: float = 0.0  # 0–360
    dominant_color_rgb: tuple[float, float, float] = (0.0, 0.0, 0.0)
    secondary_colors_rgb: list[tuple[float, float, float]] = field(default_factory=list)
    histogram_r: list[float] = field(default_factory=list)
    histogram_g: list[float] = field(default_factory=list)
    histogram_b: list[float] = field(default_factory=list)
    color_variance: float = 0.0  # variance of color across frame
    color_std_over_time: float = 0.0  # consistency of color across frames

    # --- Graphics / spatial ---
    edge_density: float = 0.0  # high-frequency energy
    spatial_variance: float = 0.0  # how uniform vs. varied the image is
    gradient_strength: float = 0.0  # magnitude of gradients
    busyness: float = 0.0  # combination of edges + variance

    # --- Motion ---
    motion_level: float = 0.0  # mean frame-to-frame difference
    motion_std: float = 0.0
    motion_trend: str = "steady"  # "increasing" | "decreasing" | "steady"
    motion_per_frame: list[float] = field(default_factory=list)
    brightness_per_frame: list[float] = field(default_factory=list)
    brightness_std_over_time: float = 0.0  # temporal consistency

    # --- Composition ---
    center_of_mass_x: float = 0.5  # 0–1
    center_of_mass_y: float = 0.5  # 0–1
    luminance_balance: float = 0.5  # 0=dark-biased, 0.5=balanced, 1=light-biased

    # --- Palette match (our data) ---
    closest_palette: str = "default"
    palette_distance: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging and API."""
        d: dict[str, Any] = {
            "path": self.path,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration_seconds": self.duration_seconds,
            "num_frames_sampled": self.num_frames_sampled,
            "mean_brightness": self.mean_brightness,
            "mean_contrast": self.mean_contrast,
            "mean_saturation": self.mean_saturation,
            "mean_hue": self.mean_hue,
            "dominant_color_rgb": list(self.dominant_color_rgb),
            "color_variance": self.color_variance,
            "color_std_over_time": self.color_std_over_time,
            "edge_density": self.edge_density,
            "spatial_variance": self.spatial_variance,
            "gradient_strength": self.gradient_strength,
            "busyness": self.busyness,
            "motion_level": self.motion_level,
            "motion_std": self.motion_std,
            "motion_trend": self.motion_trend,
            "brightness_std_over_time": self.brightness_std_over_time,
            "center_of_mass_x": self.center_of_mass_x,
            "center_of_mass_y": self.center_of_mass_y,
            "luminance_balance": self.luminance_balance,
            "closest_palette": self.closest_palette,
            "palette_distance": self.palette_distance,
        }
        if self.motion_per_frame:
            d["motion_per_frame"] = self.motion_per_frame[:60]
        if self.histogram_r:
            d["histogram_bins"] = len(self.histogram_r)
        return d

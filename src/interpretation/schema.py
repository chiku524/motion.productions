"""
Schema for what the user is instructing.
Precise representation of parsed user input.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InterpretedInstruction:
    """
    Precise interpretation of a user's text/script/prompt.
    What the user wants: palette, motion, intensity, duration, style, tone, etc.
    """

    # Core visual
    palette_name: str
    motion_type: str
    intensity: float  # 0–1

    # Duration (seconds; None = use default)
    duration_seconds: float | None = None

    # Style / tone (optional hints)
    style: str | None = None
    tone: str | None = None

    # Keywords extracted (for lookup and learning)
    keywords: list[str] = field(default_factory=list)

    # Negations: things the user explicitly does NOT want
    avoid_motion: list[str] = field(default_factory=list)
    avoid_palette: list[str] = field(default_factory=list)

    # Raw prompt (normalized)
    raw_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging and API."""
        d: dict[str, Any] = {
            "palette_name": self.palette_name,
            "motion_type": self.motion_type,
            "intensity": self.intensity,
            "keywords": self.keywords,
            "raw_prompt": self.raw_prompt,
        }
        if self.duration_seconds is not None:
            d["duration_seconds"] = self.duration_seconds
        if self.style:
            d["style"] = self.style
        if self.tone:
            d["tone"] = self.tone
        if self.avoid_motion:
            d["avoid_motion"] = self.avoid_motion
        if self.avoid_palette:
            d["avoid_palette"] = self.avoid_palette
        return d

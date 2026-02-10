"""
Abstract interface for video generation. One prompt (+ optional conditioning) → one clip or full video.
Implementations can be: single-call text-to-video, or image-to-video for temporal continuation.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class VideoGenerator(ABC):
    """
    Generates video from a prompt. Used by the pipeline to produce either:
    - One clip (duration_seconds <= model max), or
    - One segment for temporal continuation (caller concatenates for full video).
    """

    @abstractmethod
    def max_clip_seconds(self) -> float:
        """Max duration (seconds) this model can produce in a single call."""
        ...

    @abstractmethod
    def generate_clip(
        self,
        prompt: str,
        output_path: Path,
        duration_seconds: float,
        *,
        conditioning_image_path: Path | None = None,
        seed: int | None = None,
        config: dict[str, Any] | None = None,
        segment_index: int | None = None,
        total_segments: int | None = None,
    ) -> Path:
        """
        Generate one clip and write to output_path.
        - If conditioning_image_path is set, continue from that frame (for temporal continuation).
        - Returns the path where the clip was written.
        """
        ...

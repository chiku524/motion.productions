"""
Procedural video generator: implements VideoGenerator using interpretation + creation + renderer.
No external "model" — only our algorithms and data. Writes frames to video with a minimal encoder.
"""
from pathlib import Path
from typing import Any

from ..video_generator.base import VideoGenerator
from .parser import SceneSpec
from .renderer import render_frame


class ProceduralVideoGenerator(VideoGenerator):
    """
    Generates video from a prompt using only our procedural engine:
    prompt → (our parser) → spec → (our renderer) → frames → (encoder) → file.
    No neural network, no external model.
    """

    def __init__(
        self,
        width: int = 512,
        height: int = 512,
        fps: int = 24,
    ):
        self.width = width
        self.height = height
        self.fps = fps

    def max_clip_seconds(self) -> float:
        # We can generate any length; pipeline uses this for "single call" vs segmenting.
        return 600.0  # 10 min as "one clip" so we always do one full video in one go

    def generate_clip(
        self,
        prompt: str,
        output_path: Path,
        duration_seconds: float,
        *,
        conditioning_image_path: Path | None = None,
        seed: int | None = None,
        config: dict[str, Any] | None = None,
    ) -> Path:
        # Conditioning is for temporal continuation; procedural engine ignores it for now
        # (we could use it later to match last frame color/mood)
        del conditioning_image_path

        seed = seed if seed is not None else 42
        if config:
            out_cfg = config.get("output", {})
            width = out_cfg.get("width", self.width)
            height = out_cfg.get("height", self.height)
            fps = out_cfg.get("fps", self.fps)
        else:
            width, height, fps = self.width, self.height, self.fps

        from ..interpretation import interpret_user_prompt
        from ..creation import build_spec_from_instruction
        instruction = interpret_user_prompt(prompt, default_duration=duration_seconds)
        spec = build_spec_from_instruction(instruction, knowledge=None)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix == "":
            output_path = output_path.with_suffix(".mp4")

        num_frames = int(duration_seconds * fps)
        try:
            import imageio
        except ImportError:
            raise ImportError(
                "Procedural generator needs 'imageio' to write video. "
                "Install with: pip install imageio imageio-ffmpeg"
            ) from None

        writer = imageio.get_writer(
            str(output_path),
            fps=fps,
            codec="libx264",
            quality=8,
        )
        try:
            for i in range(num_frames):
                t = i / fps
                frame = render_frame(spec, t, width, height, seed=seed)
                writer.append_data(frame)
        finally:
            writer.close()

        return output_path

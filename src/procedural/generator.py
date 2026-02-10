"""
Procedural video generator: implements VideoGenerator using interpretation + creation + renderer.
No external "model" — only our algorithms and data. Writes frames to video with a minimal encoder.
Supports SceneScript (multi-shot with transitions and pacing). Phase 2.
"""
from pathlib import Path
from typing import Any

from ..video_generator.base import VideoGenerator
from .parser import SceneSpec
from .renderer import render_frame
from ..cinematography import SceneScript


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
        config: dict | None = None,
    ):
        from ..config import resolve_output_config
        cfg = config or {}
        out = resolve_output_config(cfg)
        self.width = out.get("width", width) or width
        self.height = out.get("height", height) or height
        self.fps = out.get("fps", fps) or fps
        self._config = config

    def max_clip_seconds(self) -> float:
        # Pipeline uses this for "single call" vs segmenting. Long-form = multiple segments.
        if self._config:
            v = self._config.get("video", {})
            return float(v.get("max_single_clip_seconds", 15))
        return 15.0

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
        # Coerce to int/float in case config returns dict or wrong type
        width = int(width) if width is not None else self.width
        height = int(height) if height is not None else self.height
        if isinstance(fps, dict):
            try:
                num = fps.get("num") or fps.get("numerator", 24)
                den = fps.get("den") or fps.get("denominator", 1)
                fps = float(num) / float(den) if den else float(self.fps)
            except (TypeError, ValueError, ZeroDivisionError):
                fps = float(self.fps)
        else:
            try:
                fps = float(fps) if fps is not None else float(self.fps)
            except (TypeError, ValueError):
                fps = float(self.fps)
        if fps <= 0:
            fps = float(self.fps)

        from ..interpretation import interpret_user_prompt
        from ..creation import build_spec_from_instruction
        from ..creation.scene_script import build_scene_script_from_instruction, spec_from_shot
        from ..knowledge import get_knowledge_for_creation
        instruction = interpret_user_prompt(prompt, default_duration=duration_seconds)
        knowledge = get_knowledge_for_creation(config)
        base_spec = build_spec_from_instruction(instruction, knowledge=knowledge)
        scene_script = build_scene_script_from_instruction(
            instruction,
            duration_seconds=duration_seconds,
            segment_index=segment_index,
            total_segments=total_segments,
        )
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
        fps_val = float(fps)
        trans_duration = 0.5
        from ..cinematography.transitions import apply_transition

        # Cumulative shot end times (seconds)
        shot_end_times: list[float] = []
        acc = 0.0
        for s in scene_script.shots:
            acc += s.duration_seconds
            shot_end_times.append(acc)

        try:
            for i in range(num_frames):
                t_global = i / fps_val
                shot_index = 0
                for k, end in enumerate(shot_end_times):
                    if t_global < end:
                        shot_index = k
                        break
                if t_global >= shot_end_times[-1]:
                    shot_index = len(scene_script.shots) - 1

                shot = scene_script.shots[shot_index]
                t_local = t_global - (shot_end_times[shot_index - 1] if shot_index > 0 else 0)
                pacing = getattr(shot, "pacing", 1.0) or 1.0
                t_local *= pacing  # Pacing: faster = more motion per second
                spec = spec_from_shot(base_spec, shot)
                frame = render_frame(
                    spec, t_local, width, height, seed=seed,
                    duration_seconds=duration_seconds,
                )

                # Transitions at shot boundaries
                shot_start = shot_end_times[shot_index - 1] if shot_index > 0 else 0.0
                shot_end = shot_end_times[shot_index]
                shot_elapsed = t_global - shot_start

                is_first_frames = shot_elapsed < trans_duration
                is_last_frames = (shot_end - t_global) < trans_duration

                if is_first_frames and shot.transition_in != "cut":
                    frame = apply_transition(
                        frame, shot_elapsed, trans_duration, shot.transition_in, is_in=True
                    )
                elif is_last_frames and shot.transition_out != "cut":
                    t_out = trans_duration - (shot_end - t_global)
                    frame = apply_transition(
                        frame, t_out, trans_duration, shot.transition_out, is_in=False
                    )
                writer.append_data(frame)
        finally:
            writer.close()

        return output_path

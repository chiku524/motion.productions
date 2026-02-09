"""
Pipeline: one prompt → one full video file. No user-facing "scenes"; output is always a single file.
For long durations we use temporal continuation (generate segments that continue from previous
frames) and concatenate internally, then return one path.
"""
from pathlib import Path
from typing import Any

from .config import load_config, get_output_dir
from .concat import concat_segments
from .prompt import enrich_prompt
from .video_generator.base import VideoGenerator


def generate_full_video(
    prompt: str,
    duration_seconds: float,
    *,
    generator: VideoGenerator,
    output_path: Path | None = None,
    style: str | None = None,
    tone: str | None = None,
    seed: int | None = None,
    config: dict[str, Any] | None = None,
) -> Path:
    """
    Generate one full video from one prompt. Returns the path to the single output file.
    - If duration <= model max: one generator call → one file.
    - If duration > model max: generate segments with temporal continuation, concat, return one file.
    """
    if config is None:
        config = load_config()
    out_dir = get_output_dir(config)
    out_dir.mkdir(parents=True, exist_ok=True)

    effective_prompt = enrich_prompt(
        prompt,
        style=style,
        tone=tone,
        duration_seconds=duration_seconds,
        config=config,
    )

    max_clip = generator.max_clip_seconds()
    if duration_seconds <= max_clip:
        # Single clip = full video in one call
        if output_path is None:
            output_path = out_dir / _next_filename(config, "video")
        output_path = Path(output_path)
        if output_path.suffix == "":
            output_path = output_path.with_suffix(".mp4")
        generator.generate_clip(
            effective_prompt,
            output_path,
            duration_seconds,
            seed=seed,
            config=config,
        )
        # Phase 6: optional audio mix
        output_path = _maybe_add_audio(output_path, config, prompt)
        return output_path

    # Long-form: segments with temporal continuation, then concat
    segment_paths: list[Path] = []
    segment_duration = min(max_clip, duration_seconds)  # could split evenly
    total = 0.0
    index = 0
    conditioning_path: Path | None = None

    import math
    total_segments = max(1, math.ceil(duration_seconds / segment_duration))
    while total < duration_seconds:
        index += 1
        remaining = duration_seconds - total
        seg_dur = min(segment_duration, remaining)
        seg_path = out_dir / f"_seg_{index:04d}.mp4"
        generator.generate_clip(
            effective_prompt if conditioning_path is None else "[continuation from previous frames]",
            seg_path,
            seg_dur,
            conditioning_image_path=conditioning_path,
            seed=seed if index == 1 else None,
            config=config,
            segment_index=index,
            total_segments=total_segments,
        )
        segment_paths.append(seg_path)
        total += seg_dur
        # In a real impl, extract last frame from seg_path and set conditioning_path for next segment
        conditioning_path = None  # TODO: extract last frame when you have a real backend

    if output_path is None:
        output_path = out_dir / _next_filename(config, "video")
    output_path = Path(output_path)
    if output_path.suffix == "":
        output_path = output_path.with_suffix(".mp4")

    concat_segments(segment_paths, output_path)

    # Phase 6: optional audio mix
    output_path = _maybe_add_audio(output_path, config, effective_prompt)

    # Optional: remove segment files to save space (keep for debugging initially)
    # for p in segment_paths:
    #     p.unlink(missing_ok=True)

    return output_path


def _maybe_add_audio(
    output_path: Path,
    config: dict[str, Any],
    prompt: str,
    *,
    instruction: Any = None,
) -> Path:
    """Optionally add procedural audio if config enables it. Uses audio origins: mood, tempo, presence."""
    audio_cfg = config.get("audio", {}) or {}
    if not audio_cfg.get("add", False):
        return output_path
    try:
        from .audio import mix_audio_to_video
        mood = "neutral"
        tempo = "medium"
        presence = "ambient"
        if instruction is not None:
            mood = getattr(instruction, "audio_mood", None) or "neutral"
            tempo = getattr(instruction, "audio_tempo", None) or "medium"
            presence = getattr(instruction, "audio_presence", None) or "ambient"
        elif prompt:
            try:
                from .interpretation import interpret_user_prompt
                inst = interpret_user_prompt(prompt, default_duration=6)
                mood = getattr(inst, "audio_mood", None) or "neutral"
                tempo = getattr(inst, "audio_tempo", None) or "medium"
                presence = getattr(inst, "audio_presence", None) or "ambient"
            except Exception:
                if any(w in prompt.lower() for w in ("moody", "noir", "dark")):
                    mood = "moody"
        out = mix_audio_to_video(
            output_path, output_path=output_path,
            mood=mood, tempo=tempo, presence=presence,
        )
        return Path(out)
    except ImportError:
        return output_path
    except Exception:
        return output_path


def _next_filename(config: dict[str, Any], default_prefix: str) -> str:
    """Simple next filename: prefix + timestamp to avoid overwrites."""
    from datetime import datetime
    prefix = config.get("output", {}).get("filename_prefix", default_prefix)
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

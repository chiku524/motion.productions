"""
Per-instance extraction: every frame (static) and every combined-frames window (dynamic).
Used to find new values that do not reside in any registry and add them to the
respective static or dynamic registry.
"""
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from ..analysis.metrics import (
    brightness_and_contrast,
    color_histogram,
    color_variance,
    dominant_colors,
    frame_difference,
    saturation_and_hue,
    center_of_mass,
    edge_density,
    spatial_variance,
)


def _read_frames(
    video_path: str | Path,
    *,
    max_frames: int | None = None,
    sample_every: int = 1,
) -> tuple[list[np.ndarray], float, int, int]:
    """Read frames and return (frames_list, fps, width, height)."""
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")
    try:
        import imageio
    except ImportError:
        raise ImportError("extract_from_video needs imageio. pip install imageio imageio-ffmpeg") from None

    reader = imageio.get_reader(str(path))
    try:
        meta = reader.get_meta_data()
    except Exception:
        meta = {}
    fps = 24.0
    fps_raw = meta.get("fps", 24.0)
    if isinstance(fps_raw, (int, float)) and fps_raw > 0:
        fps = float(fps_raw)
    elif isinstance(fps_raw, dict):
        try:
            num = fps_raw.get("num") or fps_raw.get("numerator", 24)
            den = fps_raw.get("den") or fps_raw.get("denominator", 1)
            fps = float(num) / float(den) if den else 24.0
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    frames_list: list = []
    for i, fr in enumerate(reader):
        if max_frames is not None and i >= max_frames * max(1, sample_every):
            break
        if i % sample_every == 0:
            frames_list.append(fr)
    reader.close()

    if not frames_list:
        raise ValueError(f"No frames could be read from {path}")

    frames = [np.asarray(f) for f in frames_list]
    if frames[0].ndim == 2:
        frames = [np.stack([f, f, f], axis=-1) for f in frames]
    elif frames[0].shape[-1] == 4:
        frames = [f[:, :, :3].copy() for f in frames]

    h, w = frames[0].shape[:2]
    return frames, fps, w, h


def _extract_audio_segments(
    video_path: str | Path,
    fps: float,
    num_frames: int,
) -> list[dict[str, Any]]:
    """
    Extract per-frame audio (amplitude, tone) from the video's audio track.
    One dict per frame: {"amplitude": float, "weight": float, "tone": str, "timbre": str}.
    Returns [] on failure or if no audio (so callers get empty sound for each frame).
    """
    if fps <= 0 or num_frames <= 0:
        return []
    try:
        from pydub import AudioSegment
    except ImportError:
        return []
    path = Path(video_path)
    if not path.exists():
        return []
    try:
        # pydub can read mp4 and extract audio via ffmpeg
        audio = AudioSegment.from_file(str(path))
    except Exception:
        return []
    if audio.frame_count() == 0:
        return []
    out: list[dict[str, Any]] = []
    frame_dur_ms = 1000.0 / fps
    for i in range(num_frames):
        start_ms = int(i * frame_dur_ms)
        end_ms = int((i + 1) * frame_dur_ms)
        if start_ms >= len(audio):
            out.append({})
            continue
        segment = audio[start_ms:min(end_ms, len(audio))]
        samples = np.array(segment.get_array_of_samples())
        if len(samples) == 0:
            out.append({"amplitude": 0.0, "weight": 0.0, "tone": "silent", "timbre": "silent"})
            continue
        # RMS amplitude (normalize to 0–1 range; 16-bit max 32768)
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        amplitude = min(1.0, rms / 32768.0) if rms else 0.0
        weight = amplitude
        # Simple tone from dominant frequency (FFT)
        if len(samples) >= 256:
            fft = np.abs(np.fft.rfft(samples[: 2048]))
            freqs = np.fft.rfftfreq(2048, 1.0 / segment.frame_rate)
            if len(fft) and np.max(fft) > 0:
                peak_idx = int(np.argmax(fft))
                peak_hz = float(freqs[peak_idx])
                if peak_hz < 200:
                    tone = "low"
                elif peak_hz < 2000:
                    tone = "mid"
                else:
                    tone = "high"
            else:
                tone = "silent" if amplitude < 0.01 else "mid"
        else:
            tone = "silent" if amplitude < 0.01 else "mid"
        out.append({"amplitude": amplitude, "weight": weight, "tone": tone, "timbre": tone})
    return out


def extract_static_per_frame(
    video_path: str | Path,
    *,
    max_frames: int | None = None,
    sample_every: int = 1,
) -> Iterator[dict[str, Any]]:
    """
    Yield one static instance per frame. Each instance contains COLOR (and when
    audio extraction exists, SOUND) for that single frame. Compare each to the
    static registry; if not present, add with a sensible name.

    Yields:
        {
            "frame_index": int,
            "time_seconds": float,
            "color": {"r", "g", "b", "brightness", "contrast", "saturation", "hue", "dominant_rgb"},
            "sound": {}  # placeholder until audio extraction per segment is implemented
        }
    """
    frames, fps, width, height = _read_frames(video_path, max_frames=max_frames, sample_every=sample_every)
    audio_segments = _extract_audio_segments(video_path, fps, len(frames))

    for i, fr in enumerate(frames):
        bc = brightness_and_contrast(fr)
        sh = saturation_and_hue(fr)
        dom = dominant_colors(fr, n=1)
        dominant_rgb = dom[0] if dom else (0.0, 0.0, 0.0)
        sound = audio_segments[i] if i < len(audio_segments) else {}
        # Every static color sub-aspect (doc: blending, opacity, chroma, luminance, hue, saturation, brightness, contrast)
        brightness_val = bc["brightness"]
        sat_val = sh["saturation"]
        yield {
            "frame_index": i,
            "time_seconds": i / fps if fps > 0 else 0.0,
            "color": {
                "r": float(dominant_rgb[0]),
                "g": float(dominant_rgb[1]),
                "b": float(dominant_rgb[2]),
                "brightness": brightness_val,
                "luminance": brightness_val,  # same as brightness (Y); explicit for coverage
                "contrast": bc["contrast"],
                "saturation": sat_val,
                "chroma": sat_val,  # chroma proxy; explicit for coverage
                "hue": sh["hue"],
                "color_variance": float(color_variance(fr)),
                "opacity": 1.0,  # we decode RGB only; set 1.0 (alpha would go here if RGBA)
            },
            "sound": sound,
        }


def extract_dynamic_per_window(
    video_path: str | Path,
    *,
    window_seconds: float = 1.0,
    max_frames: int | None = None,
    sample_every: int = 1,
) -> Iterator[dict[str, Any]]:
    """
    Yield one dynamic instance per window of combined frames (e.g. 1 second).
    Each instance contains MOTION, TIME, and other dynamic aspects over that window.
    Compare each to the dynamic registry; if not present, add with a sensible name.

    Yields:
        {
            "window_index": int,
            "start_seconds": float,
            "end_seconds": float,
            "motion": {"level", "std", "trend"},
            "time": {"duration", "fps"},
            "lighting": {"brightness", "contrast", "saturation"},
            "composition": {"center_x", "center_y", "luminance_balance"},
            "graphics": {"edge_density", "spatial_variance", "busyness"},
            "audio_semantic": {}  # placeholder until semantic audio classification
        }
    """
    frames, fps, width, height = _read_frames(video_path, max_frames=max_frames, sample_every=sample_every)
    if not frames or fps <= 0:
        return

    n = len(frames)
    frames_per_window = max(1, int(round(window_seconds * fps)))
    num_windows = max(1, (n + frames_per_window - 1) // frames_per_window)

    for w in range(num_windows):
        start_i = w * frames_per_window
        end_i = min(start_i + frames_per_window, n)
        window_frames = frames[start_i:end_i]

        # Motion over window (level, trend, direction, rhythm)
        per_motion: list[float] = []
        direction_scores: list[tuple[float, float]] = []  # (horizontal_bias, vertical_bias)
        for j in range(1, len(window_frames)):
            fa = window_frames[j - 1].astype(np.float64)
            fb = window_frames[j].astype(np.float64)
            if fa.shape == fb.shape and fa.ndim >= 2:
                diff = np.abs(fa - fb)
                if diff.ndim == 3:
                    diff = diff.mean(axis=-1)
                per_motion.append(float(diff.mean()))
                h, w = diff.shape[:2]
                if w >= 2 and h >= 2:
                    left = float(diff[:, : w // 2].sum())
                    right = float(diff[:, w // 2 :].sum())
                    top = float(diff[: h // 2, :].sum())
                    bottom = float(diff[h // 2 :, :].sum())
                    horiz = abs(left - right)
                    vert = abs(top - bottom)
                    direction_scores.append((horiz, vert))
            else:
                per_motion.append(frame_difference(window_frames[j - 1], window_frames[j]))
        motion_level = sum(per_motion) / len(per_motion) if per_motion else 0.0
        motion_std = float(np.std(per_motion)) if per_motion else 0.0
        if len(per_motion) >= 3:
            first_third = sum(per_motion[: len(per_motion) // 3]) / max(1, len(per_motion) // 3)
            last_third = sum(per_motion[-len(per_motion) // 3 :]) / max(1, len(per_motion) // 3)
            diff = last_third - first_third
            motion_trend = "increasing" if diff > 2.0 else ("decreasing" if diff < -2.0 else "steady")
        else:
            motion_trend = "steady"
        # Direction: horizontal vs vertical bias from spatial distribution of frame-to-frame change
        if direction_scores:
            mean_h = sum(s[0] for s in direction_scores) / len(direction_scores)
            mean_v = sum(s[1] for s in direction_scores) / len(direction_scores)
            if mean_h > mean_v * 1.2:
                motion_direction = "horizontal"
            elif mean_v > mean_h * 1.2:
                motion_direction = "vertical"
            else:
                motion_direction = "neutral"
        else:
            motion_direction = "neutral"
        # Rhythm: steady vs pulsing from variance of per-frame motion
        motion_rhythm = "pulsing" if (per_motion and motion_std > max(2.0, motion_level * 0.5)) else "steady"

        # Lighting/composition/graphics from middle frame of window
        mid_idx = len(window_frames) // 2
        mid_fr = window_frames[mid_idx]
        bc = brightness_and_contrast(mid_fr)
        sh = saturation_and_hue(mid_fr)
        cx, cy = center_of_mass(mid_fr)
        edge_den = edge_density(mid_fr)
        spat_var = spatial_variance(mid_fr)
        cx_norm = cx / width if width else 0.5
        cy_norm = cy / height if height else 0.5
        lum_bal = min(1.0, max(0.0, bc["brightness"] / 255.0))

        yield {
            "window_index": w,
            "start_seconds": start_i / fps,
            "end_seconds": end_i / fps,
            "motion": {
                "level": motion_level,
                "std": motion_std,
                "trend": motion_trend,
                "direction": motion_direction,
                "rhythm": motion_rhythm,
            },
            "time": {"duration": (end_i - start_i) / fps, "fps": fps, "rate": fps},
            "lighting": {"brightness": bc["brightness"], "contrast": bc["contrast"], "saturation": sh["saturation"]},
            "composition": {"center_x": cx_norm, "center_y": cy_norm, "luminance_balance": lum_bal},
            "graphics": {"edge_density": edge_den, "spatial_variance": spat_var, "busyness": 0.5 * edge_den + 0.5 * spat_var},
            "audio_semantic": {},  # TODO: music/melody/dialogue/SFX when semantic audio is implemented
        }

"""
Per-instance extraction: every frame (static) and every combined-frames window (dynamic).
Used to find new values that do not reside in any registry and add them to the
respective static or dynamic registry.
"""
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from ..audio.features import measure_audio_frame
from .evidence import DECLARED, OBSERVED
from ..analysis.metrics import (
    brightness_and_contrast,
    color_variance,
    dominant_colors,
    frame_difference,
    saturation_and_hue,
    center_of_mass,
    edge_density,
    spatial_variance,
    gradient_strength,
    gradient_direction,
)


def read_video_once(
    video_path: str | Path,
    *,
    max_frames: int | None = None,
    sample_every: int = 1,
) -> tuple[list[np.ndarray], float, int, int, list[dict[str, Any]]]:
    """
    Read video once and return frames + metadata + per-frame audio segments.
    Use this when both static and dynamic extraction are needed to avoid double decoding.
    Returns: (frames, fps, width, height, audio_segments)
    """
    frames, fps, width, height = _read_frames(
        video_path, max_frames=max_frames, sample_every=sample_every
    )
    audio_segments = _extract_audio_segments(video_path, fps, len(frames))
    return frames, fps, width, height, audio_segments


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
    Extract pure sound per frame: any form of noise within a single instant (one frame).
    One frame = one instant in time (e.g. 1/24 s at 24 fps), not a 1-second window.
    Returns one dict per frame: {"amplitude", "weight", "tone", "timbre"}.
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
        # One shared measurement (also used by the sound v2 synth to aim at a cell): RMS amplitude, peak_hz,
        # spectral flatness, attack ratio, zcr. Stereo is mixed down; the FFT axis uses the real chunk length.
        m = measure_audio_frame(samples, segment.frame_rate, segment.channels)
        amplitude = m["amplitude"]
        weight = amplitude
        tone = "silent" if amplitude < 0.01 else "mid"
        peak_hz = m["peak_hz"]
        spectral_flatness = m["spectral_flatness"]
        attack_ratio = m["attack_ratio"]
        zcr = m["zcr"]
        if peak_hz > 0:
            tone = "low" if peak_hz < 200 else ("mid" if peak_hz < 2000 else "high")
        v2_key = None
        if len(samples) // max(1, segment.channels) >= 256:
            from .keyspace import sound_v2_key  # binned from the unrounded measurement
            v2_key = sound_v2_key(amplitude, peak_hz, spectral_flatness, attack_ratio, zcr)
        from .blend_depth import classify_sound_primitive
        primitive = classify_sound_primitive(
            amplitude, tone,
            spectral_flatness=spectral_flatness,
            attack_ratio=attack_ratio,
            zcr=zcr,
        )
        out.append({
            "amplitude": amplitude,
            "weight": weight,
            "tone": tone,
            "timbre": primitive,
            "primitive": primitive,
            "spectral_flatness": round(spectral_flatness, 3),
            "attack_ratio": round(attack_ratio, 3),
            "zcr": round(zcr, 3),
            "peak_hz": round(peak_hz, 1),
            # Sound v2 cell measured from THIS decoded frame (evidence tier: observed).
            **({"v2_key": v2_key, "evidence_tier": OBSERVED} if v2_key else {}),
        })
    return out


def read_audio_segments_only(
    audio_path: str | Path,
    fps: float = 24.0,
    duration_seconds: float | None = None,
    num_frames: int | None = None,
) -> list[dict[str, Any]]:
    """
    Extract pure sound per frame (one instant per frame) from an audio file (WAV or video).
    Each segment = one frame = one instant of noise (amplitude, tone, timbre). Used by the
    sound-only workflow to build the mesh of per-instant sounds. Either duration_seconds
    or num_frames must be provided.
    """
    if duration_seconds is not None:
        num_frames = int(duration_seconds * fps)
    if num_frames is None or num_frames <= 0:
        return []
    return _extract_audio_segments(audio_path, fps, num_frames)


def _extract_static_from_preloaded(
    frames: list[np.ndarray],
    fps: float,
    audio_segments: list[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    """Yield one static instance per frame from pre-loaded frames and audio. Internal use."""
    for i, fr in enumerate(frames):
        bc = brightness_and_contrast(fr)
        sh = saturation_and_hue(fr)
        dom = dominant_colors(fr, n=1)
        dominant_rgb = dom[0] if dom else (0.0, 0.0, 0.0)
        sound = audio_segments[i] if i < len(audio_segments) else {}
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


def extract_static_per_frame(
    video_path: str | Path,
    *,
    max_frames: int | None = None,
    sample_every: int = 1,
) -> Iterator[dict[str, Any]]:
    """
    Yield one static instance per frame. Each instance contains COLOR and SOUND.
    Uses read_video_once internally. For unified extraction, prefer read_video_once + _extract_static_from_preloaded.
    """
    frames, fps, _, _, audio_segments = read_video_once(
        video_path, max_frames=max_frames, sample_every=sample_every
    )
    yield from _extract_static_from_preloaded(frames, fps, audio_segments)


def _derive_audio_semantic_from_segments(
    audio_segments: list[dict[str, Any]],
    start_i: int,
    end_i: int,
) -> dict[str, Any]:
    """Infer audio_semantic (role, mood, tempo) from per-frame audio segments in the window."""
    segs = [audio_segments[i] for i in range(start_i, min(end_i, len(audio_segments))) if i < len(audio_segments) and audio_segments[i]]
    if not segs:
        return {}
    amps = [float(s.get("amplitude") or s.get("weight") or 0) for s in segs]
    mean_amp = sum(amps) / len(amps) if amps else 0
    amp_std = (sum((a - mean_amp) ** 2 for a in amps) / len(amps)) ** 0.5 if len(amps) > 1 else 0
    if mean_amp < 0.05:
        role, presence = "ambient", "silence"
    elif mean_amp > 0.3:
        role, presence = "music", "full"
    else:
        role, presence = "ambient", "ambient"
    tempo = "medium" if amp_std > 0.05 else "slow"
    mood = "calm" if mean_amp < 0.1 else ("energetic" if mean_amp > 0.4 else "neutral")
    return {"role": role, "type": role, "mood": mood, "tempo": tempo, "presence": presence}


def _gray_small(frame: np.ndarray) -> np.ndarray:
    f = frame[::4, ::4].astype(np.float64)
    return f.mean(axis=-1) if f.ndim == 3 else f


def measure_transition_duration(frames: list[np.ndarray], boundary: int, fps: float) -> float | None:
    """
    Real transition duration (seconds) around the frame index where a new window starts.

    Looks at consecutive-frame change in a +-0.5 s band. A cut is one spike (duration 0.0); a dissolve or
    fade keeps the change elevated above the clip's background motion for several frames, and the length of
    that run is the duration. Returns None when it cannot be measured (too few frames / shape change).
    """
    n = len(frames)
    if fps <= 0 or boundary < 1 or boundary >= n or n < 4:
        return None
    try:
        span = max(2, int(round(fps * 0.5)))
        lo, hi = max(1, boundary - span), min(n - 1, boundary + span)
        d: dict[int, float] = {}
        prev = _gray_small(frames[lo - 1])
        for i in range(lo, hi + 1):
            cur = _gray_small(frames[i])
            if cur.shape != prev.shape:
                return None
            d[i] = float(np.abs(cur - prev).mean())
            prev = cur
        # background motion: median change in the band outside the boundary neighbourhood
        outside = [v for i, v in d.items() if abs(i - boundary) > 2]
        base = float(np.median(outside)) if outside else 0.0
        peak = max(d[i] for i in d if abs(i - boundary) <= 1)
        if peak <= base * 1.5 + 0.5:
            return 0.0  # nothing stands out from the clip's own motion: no transition event
        thr = base + 0.5 * (peak - base)
        centre = max((i for i in d if abs(i - boundary) <= 1), key=lambda i: d[i])
        run = 1
        i = centre - 1
        while i in d and d[i] >= thr:
            run += 1
            i -= 1
        i = centre + 1
        while i in d and d[i] >= thr:
            run += 1
            i += 1
        return 0.0 if run <= 1 else round(run / fps, 3)
    except Exception:
        return None


def measure_depth_proxy(grid_motion: list[np.ndarray]) -> dict[str, Any] | None:
    """
    Depth proxy from motion parallax: how differently the 3x3 image regions move over the window (near things
    move more than far things). Returns {parallax_strength, layer_count, proxy} or None without motion data.
    This is a measured proxy, not true depth.
    """
    if not grid_motion:
        return None
    g = np.mean(np.stack(grid_motion), axis=0).ravel()  # mean motion per region
    top = float(g.max())
    if top < 0.5:
        return {"parallax_strength": 0.0, "layer_count": 1, "proxy": "motion_parallax_grid"}
    spread = float(np.std(g) / (np.mean(g) + 1e-9))
    strength = round(min(1.0, spread) * 10) / 10  # 0.1 steps keep the key space small
    levels = {int(v) for v in np.floor(g / top * 3.999)}  # 4 relative motion levels
    return {"parallax_strength": float(strength), "layer_count": int(max(1, len(levels))), "proxy": "motion_parallax_grid"}


def _extract_dynamic_from_preloaded(
    frames: list[np.ndarray],
    fps: float,
    width: int,
    height: int,
    *,
    window_seconds: float = 1.0,
    audio_segments: list[dict[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield one dynamic instance per window from pre-loaded frames. Internal use."""
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
        grid_motion: list[np.ndarray] = []
        direction_scores: list[tuple[float, float]] = []
        for j in range(1, len(window_frames)):
            fa = window_frames[j - 1].astype(np.float64)
            fb = window_frames[j].astype(np.float64)
            if fa.shape == fb.shape and fa.ndim >= 2:
                diff = np.abs(fa - fb)
                if diff.ndim == 3:
                    diff = diff.mean(axis=-1)
                per_motion.append(float(diff.mean()))
                h, ww = diff.shape[:2]
                if h >= 3 and ww >= 3:
                    gh, gw = (h // 3) * 3, (ww // 3) * 3
                    grid_motion.append(diff[:gh, :gw].reshape(3, gh // 3, 3, gw // 3).mean(axis=(1, 3)))
                if ww >= 2 and h >= 2:
                    left = float(diff[:, : ww // 2].sum())
                    right = float(diff[:, ww // 2 :].sum())
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
        if direction_scores:
            mean_h = sum(s[0] for s in direction_scores) / len(direction_scores)
            mean_v = sum(s[1] for s in direction_scores) / len(direction_scores)
            motion_direction = "horizontal" if mean_h > mean_v * 1.2 else ("vertical" if mean_v > mean_h * 1.2 else "neutral")
        else:
            motion_direction = "neutral"
        motion_rhythm = "pulsing" if (per_motion and motion_std > max(2.0, motion_level * 0.5)) else "steady"

        mid_idx = len(window_frames) // 2
        mid_fr = window_frames[mid_idx]
        bc = brightness_and_contrast(mid_fr)
        sh = saturation_and_hue(mid_fr)
        cx, cy = center_of_mass(mid_fr)
        edge_den = edge_density(mid_fr)
        spat_var = spatial_variance(mid_fr)
        lum_bal = min(1.0, max(0.0, bc["brightness"] / 255.0))
        grad_str = gradient_strength(mid_fr)
        grad_dir = gradient_direction(mid_fr)
        gradient_type = grad_dir if grad_str > 0.05 else "static"
        if motion_level < 1.0:
            camera_motion = "static"
        elif motion_direction == "horizontal":
            camera_motion = "pan"
        elif motion_direction == "vertical":
            camera_motion = "tilt"
        elif motion_trend == "increasing" and motion_level > 5.0:
            camera_motion = "zoom"
        elif motion_trend == "decreasing" and motion_level > 5.0:
            camera_motion = "zoom_out"
        else:
            camera_motion = "static"

        audio_semantic = {}
        if audio_segments:
            audio_semantic = _derive_audio_semantic_from_segments(audio_segments, start_i, end_i)

        # Temporal blend (strict): mean of per-frame dominant colors in this window.
        # Motion over the window "combines" pixels → this blend can be recorded as new pure (e.g. black+white→grey).
        r_list, g_list, b_list = [], [], []
        for fr in window_frames:
            dom = dominant_colors(fr, n=1)
            if dom:
                r_list.append(float(dom[0][0]))
                g_list.append(float(dom[0][1]))
                b_list.append(float(dom[0][2]))
        if r_list:
            temporal_blend_rgb = (
                sum(r_list) / len(r_list),
                sum(g_list) / len(g_list),
                sum(b_list) / len(b_list),
            )
        else:
            temporal_blend_rgb = None

        # Transition detection at window boundary: compare last frame of previous window with first of this window
        transition_type = "cut"
        transition_duration_seconds = 0.0
        if w > 0 and start_i > 0 and start_i - 1 < n and len(window_frames) > 0:
            prev_last = frames[start_i - 1]
            curr_first = window_frames[0]
            if prev_last.shape == curr_first.shape and prev_last.ndim >= 2:
                diff = np.abs(prev_last.astype(np.float64) - curr_first.astype(np.float64))
                if diff.ndim == 3:
                    diff = diff.mean(axis=-1)
                mean_diff = float(diff.mean())
                # High change at boundary → cut; low change → dissolve/fade
                if mean_diff > 25:
                    transition_type = "cut"
                elif mean_diff > 12:
                    transition_type = "dissolve"
                else:
                    transition_type = "fade"
        # Real duration from the frames around the boundary (was a constant 0.0). Unmeasurable -> declared.
        measured_duration = measure_transition_duration(frames, start_i, fps) if w > 0 else None
        if measured_duration is not None:
            transition_duration_seconds = measured_duration
        transition_dict = {
            "type": transition_type,
            "duration_seconds": transition_duration_seconds,
            "measured": measured_duration is not None,
        }
        depth_proxy = measure_depth_proxy(grid_motion)
        # Evidence per category: only what was measured from pixels/samples is observed. Camera is still a
        # guess from frame differences and audio_semantic a guess from loudness, so both stay declared.
        evidence = {
            "camera": DECLARED,
            "audio_semantic": DECLARED,
            "transition": OBSERVED if measured_duration is not None else DECLARED,
            "depth": OBSERVED if depth_proxy else DECLARED,
        }

        yield {
            "window_index": w,
            "temporal_blend_rgb": temporal_blend_rgb,
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
            "gradient": {"gradient_type": gradient_type, "strength": grad_str},
            "camera": {"motion_type": camera_motion, "speed": "medium" if motion_level > 5 else "slow"},
            "lighting": {"brightness": bc["brightness"], "contrast": bc["contrast"], "saturation": sh["saturation"]},
            "composition": {"center_x": cx / width if width else 0.5, "center_y": cy / height if height else 0.5, "luminance_balance": lum_bal},
            "graphics": {"edge_density": edge_den, "spatial_variance": spat_var, "busyness": 0.5 * edge_den + 0.5 * spat_var},
            "audio_semantic": audio_semantic,
            "transition": transition_dict,
            "depth": depth_proxy or {},
            "evidence": evidence,
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
    For unified extraction, prefer read_video_once + _extract_dynamic_from_preloaded.
    Includes audio_semantic inferred from per-frame audio when available.
    """
    frames, fps, width, height, audio_segments = read_video_once(
        video_path, max_frames=max_frames, sample_every=sample_every
    )
    yield from _extract_dynamic_from_preloaded(
        frames, fps, width, height,
        window_seconds=window_seconds,
        audio_segments=audio_segments,
    )

"""
Sound: procedural audio, SFX, mix with video. Phase 6.
Procedural audio uses origins: tempo, mood, presence.
Requires: pydub, ffmpeg and ffprobe on PATH.
"""
from __future__ import annotations

import logging
import os
import random
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydub import AudioSegment

logger = logging.getLogger(__name__)


def generate_silence(duration_seconds: float, sample_rate: int = 44100) -> "bytes":
    """Generate silence as raw PCM bytes."""
    try:
        from pydub import AudioSegment
    except ImportError:
        return b""
    seg = AudioSegment.silent(duration=int(duration_seconds * 1000), frame_rate=sample_rate)
    return seg.raw_data


def generate_tone(
    frequency: float,
    duration_seconds: float,
    *,
    volume_db: float = -20,
    sample_rate: int = 44100,
) -> "bytes":
    """Generate a simple sine tone. For procedural SFX building blocks."""
    try:
        from pydub.generators import Sine
    except ImportError:
        return b""
    gen = Sine(frequency)
    seg = gen.to_audio_segment(duration=int(duration_seconds * 1000))
    seg = seg + volume_db
    return seg.raw_data


def mix_audio_to_video(
    video_path: Path,
    output_path: Path | None = None,
    *,
    audio_path: Path | None = None,
    mood: str = "neutral",
    tempo: str = "medium",
    presence: str = "ambient",
    cut_times: list[float] | None = None,
    pure_sounds: list[dict] | None = None,
) -> Path:
    """
    Add audio to a video. Phase 6.
    - If audio_path: mix that file.
    - Else if pure_sounds (from registry mesh): mix multiple per-instant sounds into one track.
    - Else: generate procedural ambient from origins (tempo, mood, presence).
    - Always writes to a temp file first to avoid ffmpeg in-place corruption.
    Raises RuntimeError if pydub is missing or ffmpeg/ffprobe are not on PATH.
    """
    try:
        from pydub import AudioSegment
    except ImportError as e:
        raise RuntimeError(
            "pydub is required for audio. Install with: pip install pydub"
        ) from e

    import subprocess

    video_path = Path(video_path)
    output_path = output_path or video_path.parent / (video_path.stem + "_with_audio" + video_path.suffix)
    in_place = output_path.resolve() == video_path.resolve()

    # Write to temp first when overwriting same file (ffmpeg in-place can fail)
    final_output = output_path
    if in_place:
        fd, tmp_out = tempfile.mkstemp(suffix=".mp4", prefix="mux_")
        os.close(fd)
        output_path = Path(tmp_out)

    # Get video duration from ffprobe
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        duration = float(out.stdout.strip() or 5.0)
    except FileNotFoundError as e:
        raise RuntimeError(
            "ffprobe not found. Audio requires ffmpeg. Install: winget install FFmpeg / brew install ffmpeg / apt install ffmpeg"
        ) from e
    except (subprocess.CalledProcessError, ValueError) as e:
        logger.warning("ffprobe failed for %s: %s — using duration 5.0s", video_path, e)
        duration = 5.0

    if audio_path and audio_path.exists():
        audio = AudioSegment.from_file(str(audio_path))
        audio = audio[: int(duration * 1000)]
    elif pure_sounds and len(pure_sounds) > 0:
        # Mix multiple pure sounds from the registry (per-instant mesh)
        audio = generate_audio_from_pure_sounds(
            pure_sounds,
            duration_ms=int(duration * 1000),
        )
    else:
        # Procedural audio from origins: mood, tempo, presence
        audio = _generate_procedural_audio(
            duration_ms=int(duration * 1000),
            mood=mood,
            tempo=tempo,
            presence=presence,
        )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_wav = f.name
    try:
        audio.export(tmp_wav, format="wav")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(video_path), "-i", tmp_wav, "-c:v", "copy", "-c:a", "aac", "-shortest", str(output_path)],
                capture_output=True,
                check=True,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "ffmpeg not found. Audio requires ffmpeg on PATH. Install: winget install FFmpeg / brew install ffmpeg / apt install ffmpeg"
            ) from e
    finally:
        Path(tmp_wav).unlink(missing_ok=True)

    if in_place:
        shutil.move(str(output_path), str(final_output))
        return final_output
    return output_path


def _tone_to_freq_db(tone: str, amplitude: float) -> tuple[float, float]:
    """Map tone (low/mid/high/silent) and amplitude (0–1) to (frequency_hz, volume_db)."""
    tone_lower = (tone or "").strip().lower()
    if tone_lower in ("silent", "silence", "") or (amplitude or 0) < 0.01:
        return 0.0, -60.0  # effectively silent
    freq_map = {"low": 82.0, "mid": 220.0, "high": 880.0}
    freq = freq_map.get(tone_lower, 220.0)
    # Amplitude 0–1 → dB about -30 (quiet) to -18 (audible)
    amp = max(0.0, min(1.0, float(amplitude or 0.5)))
    db = -30.0 + amp * 12.0
    return freq, db


def generate_audio_from_pure_sounds(
    pure_sounds: list[dict],
    duration_ms: int,
    *,
    sample_rate: int = 44100,
) -> AudioSegment:
    """
    Mix multiple pure sounds (from the static_sound registry mesh) into one track.
    Each entry can have tone (low/mid/high/silent), amplitude/weight, timbre.
    Overlays all with reduced gain so they combine into a single evolving layer.
    """
    try:
        from pydub import AudioSegment
        from pydub.generators import Sine
    except ImportError as e:
        raise RuntimeError("pydub is required for audio. Install with: pip install pydub") from e

    try:
        from pydub.generators import Sine
    except ImportError:
        return AudioSegment.silent(duration=duration_ms, frame_rate=sample_rate)

    frame_rate = sample_rate
    base = AudioSegment.silent(duration=duration_ms, frame_rate=frame_rate)
    n = max(1, len([e for e in pure_sounds if isinstance(e, dict)]))
    # Per-layer gain reduction so combined level is reasonable
    layer_db = -10.0 * (1.0 / n) ** 0.5  # softer when more layers

    for i, entry in enumerate(pure_sounds):
        if not isinstance(entry, dict):
            continue
        tone = (entry.get("tone") or entry.get("timbre") or "mid").strip() or "mid"
        amp = float(entry.get("amplitude") or entry.get("weight") or 0.5)
        freq, db = _tone_to_freq_db(tone, amp)
        if freq <= 0:
            continue
        try:
            tone_seg = Sine(freq).to_audio_segment(duration=duration_ms)
            tone_seg = tone_seg + (db + layer_db)
        except Exception:
            continue
        # Stagger start slightly so layers don't all align (more texture)
        offset_ms = (i * 47) % max(1, duration_ms // 2)
        base = base.overlay(tone_seg, position=offset_ms)

    return base


def _repeat_to_duration(segment, duration_ms: int):
    """Repeat an AudioSegment until at least duration_ms, then slice to exact length. pydub has no .loop()."""

    n = len(segment)
    if n >= duration_ms:
        return segment[:duration_ms]
    repeats = (duration_ms + n - 1) // n
    repeated = segment * repeats
    return repeated[:duration_ms]


def _generate_procedural_audio(
    duration_ms: int,
    mood: str = "neutral",
    tempo: str = "medium",
    presence: str = "ambient",
    target_primitive: str | None = None,
) -> AudioSegment:
    """
    Generate procedural audio from origin primitives (AUDIO_ORIGINS).
    When target_primitive is set (rustle/click/whoosh/…), shape the waveform so
    Pure sound depth_breakdown can record that origin noise.
    """
    from pydub import AudioSegment

    frame_rate = 44100
    base = AudioSegment.silent(duration=duration_ms, frame_rate=frame_rate)

    if presence == "silence":
        return base

    try:
        from pydub.generators import Sine
    except ImportError as e:
        logger.warning("pydub.generators.Sine not available: %s — using silence for procedural audio", e)
        return base

    try:
        from pydub.generators import WhiteNoise
    except ImportError:
        WhiteNoise = None  # type: ignore[misc, assignment]

    # Mood: frequency and volume (full AUDIO_ORIGINS mood set + film aliases).
    mood_config = {
        "neutral": (110, -22),
        "calm": (82, -20),
        "tense": (55, -18),
        "uplifting": (165, -20),
        "dark": (55, -18),
        "dramatic": (82, -15),
        "peaceful": (87, -25),
        "chaotic": (220, -14),
        "soft": (131, -26),
        "harsh": (247, -12),
        "dreamy": (174, -23),
        "bright": (262, -15),
        "energetic": (294, -13),
        "moody": (55, -20),
        "melancholy": (73, -22),
        "hopeful": (185, -17),
        "ominous": (48, -18),
        "playful": (330, -16),
        "suspenseful": (92, -17),
        "intense": (140, -12),
        "noir": (49, -19),
        "thriller": (44, -18),
    }
    freq, db = mood_config.get(mood, (110, -22))

    tempo_ms = {"slow": 4000, "medium": 2500, "fast": 1200}.get(tempo, 2500)
    tone_dur = min(tempo_ms, duration_ms)

    if presence == "full":
        db = max(db - 4, -24)
    elif presence == "ambient":
        db = db

    tone = Sine(freq).to_audio_segment(duration=tone_dur) + db
    looped = _repeat_to_duration(tone, duration_ms)
    result = base.overlay(looped)

    # Cover all ten SOUND_ORIGIN_PRIMITIVES via spectral shape (mission: touch every origin noise).
    prim = (target_primitive or "").strip().lower()
    if not prim:
        prim = random.choice(
            ["tone", "hum", "hiss", "rumble", "rustle", "click", "whoosh", "thump", "drip", "tone"]
        )

    def _noise(dur: int, volume: int) -> AudioSegment:
        if WhiteNoise is None:
            return Sine(4000).to_audio_segment(duration=dur) + volume
        return WhiteNoise().to_audio_segment(duration=dur) + volume

    if prim == "hiss":
        result = result.overlay(_noise(min(800, duration_ms), db - 10))
    elif prim == "hum":
        hum = Sine(60).to_audio_segment(duration=min(2000, duration_ms)) + (db - 6)
        result = result.overlay(_repeat_to_duration(hum, duration_ms))
    elif prim == "rumble":
        rumble = Sine(40).to_audio_segment(duration=min(2500, duration_ms)) + (db - 4)
        result = result.overlay(_repeat_to_duration(rumble, duration_ms))
    elif prim == "rustle":
        for t in range(0, duration_ms, 180):
            result = result.overlay(_noise(min(60, duration_ms - t), db - 8), position=t)
    elif prim == "click":
        for t in range(0, duration_ms, max(400, tempo_ms // 2)):
            click = Sine(2000).to_audio_segment(duration=18) + (db + 2)
            result = result.overlay(click, position=t)
            if WhiteNoise is not None:
                result = result.overlay(_noise(12, db), position=t)
    elif prim == "whoosh":
        result = result.overlay(_noise(min(900, duration_ms), db - 6), position=max(0, duration_ms // 4))
        result = result.overlay(Sine(800).to_audio_segment(duration=min(600, duration_ms)) + (db - 10))
    elif prim == "thump":
        thump = Sine(55).to_audio_segment(duration=80) + (db + 4)
        for t in range(0, duration_ms, max(500, tempo_ms)):
            result = result.overlay(thump, position=t)
    elif prim == "drip":
        for t in range(200, duration_ms, 700):
            result = result.overlay(Sine(1200).to_audio_segment(duration=30) + (db - 2), position=t)
    elif prim == "tone":
        mid_tone = Sine(330).to_audio_segment(duration=min(1500, duration_ms)) + (db - 8)
        result = result.overlay(_repeat_to_duration(mid_tone, duration_ms))
    else:
        if mood in ("uplifting", "calm", "neutral") or random.random() < 0.35:
            mid_tone = Sine(330).to_audio_segment(duration=min(1500, duration_ms)) + (db - 8)
            result = result.overlay(_repeat_to_duration(mid_tone, duration_ms))
        if mood in ("uplifting", "bright") or random.random() < 0.25:
            high_tone = Sine(1200).to_audio_segment(duration=min(800, duration_ms)) + (db - 12)
            result = result.overlay(_repeat_to_duration(high_tone, duration_ms))

    return result


def generate_audio_only(
    duration_seconds: float,
    output_path: Path,
    *,
    mood: str = "neutral",
    tempo: str = "medium",
    presence: str = "ambient",
    target_primitive: str | None = None,
) -> Path:
    """
    Generate procedural audio to a WAV file (no video). Used by the sound-only
    workflow to discover pure sound values without rendering video.
    Pass target_primitive to bias toward a specific SOUND_ORIGIN_PRIMITIVES entry.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration_ms = int(duration_seconds * 1000)
    audio = _generate_procedural_audio(
        duration_ms=duration_ms,
        mood=mood,
        tempo=tempo,
        presence=presence,
        target_primitive=target_primitive,
    )
    audio.export(str(output_path), format="wav")
    return output_path

"""
Sound: procedural audio, SFX, mix with video. Phase 6.
Procedural audio uses origins: tempo, mood, presence.
Requires: pydub, ffmpeg and ffprobe on PATH.
"""
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

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
        from pydub import AudioSegment
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
) -> Path:
    """
    Add audio to a video. Phase 6.
    - If audio_path: mix that file.
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


def _repeat_to_duration(segment, duration_ms: int):
    """Repeat an AudioSegment until at least duration_ms, then slice to exact length. pydub has no .loop()."""
    from pydub import AudioSegment

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
) -> "AudioSegment":
    """Generate procedural audio from origin primitives (AUDIO_ORIGINS)."""
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

    # Mood: frequency and volume (origin primitives). Levels set so audio is clearly audible when unmuted.
    mood_config = {
        "neutral": (110, -22),
        "calm": (82, -20),
        "tense": (55, -18),
        "uplifting": (165, -20),
        "dark": (55, -18),
        "moody": (55, -20),
        "noir": (49, -19),
        "thriller": (44, -18),
    }
    freq, db = mood_config.get(mood, (110, -22))

    # Tempo: tone length (origin primitive)
    tempo_ms = {"slow": 4000, "medium": 2500, "fast": 1200}.get(tempo, 2500)
    tone_dur = min(tempo_ms, duration_ms)

    # Presence: intensity of audible content
    if presence == "full":
        db = max(db - 4, -24)  # Louder for full
    elif presence == "ambient":
        db = db  # Keep quiet
    # music/sfx: treat like ambient for now (future: add rhythm or SFX)

    tone = Sine(freq).to_audio_segment(duration=tone_dur) + db
    # pydub AudioSegment has no .loop(); repeat segment to fill target duration
    looped = _repeat_to_duration(tone, duration_ms)
    return base.overlay(looped)

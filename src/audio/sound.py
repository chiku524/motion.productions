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
    audio_genre: str = "none",
    audio_vocals: bool = False,
    sfx_events: list[dict] | None = None,
    vocal_phrase: str | None = None,
) -> Path:
    """
    Add audio to a video. Phase 6+.
    - If audio_path: mix that file.
    - Else if presence=music or audio_genre set: in-house arrangement engine.
    - Else if pure_sounds: mix registry mesh.
    - Else: procedural ambient from origins.
    - Overlay event SFX (bounce etc.) and optional offline vocals.
    - cut_times: soft click accents at scene cuts.
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

    final_output = output_path
    if in_place:
        fd, tmp_out = tempfile.mkstemp(suffix=".mp4", prefix="mux_")
        os.close(fd)
        output_path = Path(tmp_out)

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

    duration_ms = int(duration * 1000)

    if audio_path and audio_path.exists():
        audio = AudioSegment.from_file(str(audio_path))
        audio = audio[:duration_ms]
    else:
        audio = _build_audio_bed(
            duration_ms=duration_ms,
            mood=mood,
            tempo=tempo,
            presence=presence,
            pure_sounds=pure_sounds,
            audio_genre=audio_genre,
        )

    # Cut accents + event SFX
    from .event_sfx import schedule_sfx_events, cut_accent_events
    events = list(sfx_events or [])
    events.extend(cut_accent_events(cut_times))
    audio = schedule_sfx_events(audio, events, duration_ms=duration_ms)

    # Offline vocals
    if audio_vocals or (presence == "music" and audio_genre not in ("none", "")):
        from .vocals import mix_vocals_into
        # Only force vocal bed when explicitly requested
        if audio_vocals:
            audio = mix_vocals_into(
                audio,
                enable=True,
                mood=mood,
                phrase=vocal_phrase,
                duration_ms=duration_ms,
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


def _build_audio_bed(
    *,
    duration_ms: int,
    mood: str,
    tempo: str,
    presence: str,
    pure_sounds: list[dict] | None,
    audio_genre: str,
):
    """Select music arrangement vs ambient vs sfx-only bed."""
    from pydub import AudioSegment

    presence = (presence or "ambient").lower()
    genre = (audio_genre or "none").lower()

    if presence == "silence":
        return AudioSegment.silent(duration=duration_ms, frame_rate=44100)

    use_music = presence in ("music", "full") or genre not in ("none", "", "ambient")
    if use_music and genre in ("none", "", "ambient") and presence == "music":
        genre = "deep_house"

    if use_music and genre not in ("none", ""):
        from .music import generate_arrangement_audio, duck_under_sfx
        music = generate_arrangement_audio(
            duration_ms, genre=genre if genre != "ambient" else "ambient", tempo=tempo, mood=mood
        )
        if presence == "full":
            # Layer light ambient under music
            amb = _generate_procedural_audio(duration_ms, mood=mood, tempo=tempo, presence="ambient")
            music = music.overlay(amb + (-8))
        return music

    if presence == "sfx":
        # Sparse transient bed only (events overlay later)
        base = AudioSegment.silent(duration=duration_ms, frame_rate=44100)
        sparse = _generate_procedural_audio(duration_ms, mood=mood, tempo=tempo, presence="sfx")
        return base.overlay(sparse + (-4))

    if pure_sounds and len(pure_sounds) > 0:
        return generate_audio_from_pure_sounds(pure_sounds, duration_ms=duration_ms)

    return _generate_procedural_audio(duration_ms, mood=mood, tempo=tempo, presence=presence)


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
    elif presence == "sfx":
        # Sparse transient-oriented bed (events add the real hits)
        db = db - 6
    elif presence == "music":
        # Fallback if arrangement engine unavailable — harmonic stack
        db = db - 2
    elif presence == "ambient":
        db = db

    tone = Sine(freq).to_audio_segment(duration=tone_dur) + db
    looped = _repeat_to_duration(tone, duration_ms)
    result = base.overlay(looped)

    if presence == "music":
        # Extra harmonic layers for music-like bed fallback
        for mul, g_off in ((1.5, -10), (2.0, -14), (3.0, -18)):
            harm = Sine(freq * mul).to_audio_segment(duration=min(tone_dur, duration_ms)) + (db + g_off)
            result = result.overlay(_repeat_to_duration(harm, duration_ms))

    if presence == "sfx":
        # Only sparse clicks/thumps — no continuous bed dominance
        result = base
        for t in range(0, duration_ms, max(500, tempo_ms)):
            thump = Sine(60).to_audio_segment(duration=70).fade_out(65) + (db + 2)
            result = result.overlay(thump, position=t)
        return result

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

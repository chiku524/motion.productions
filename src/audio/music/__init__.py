"""
In-house music arrangement engine (Phase 3).

Generates structured beds (deep house, techno, ambient, cinematic) from
oscillators + noise — no external APIs or sample packs.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Arrangement:
    genre: str
    bpm: float
    sections: list[str] = field(default_factory=list)  # intro|build|drop|break
    bars: int = 8


def arrangement_for(
    genre: str,
    *,
    tempo: str = "medium",
    mood: str = "neutral",
    duration_sec: float = 4.0,
) -> Arrangement:
    genre = (genre or "none").lower()
    tempo = (tempo or "medium").lower()
    bpm_map = {"slow": 100.0, "medium": 122.0, "fast": 128.0}
    bpm = bpm_map.get(tempo, 122.0)
    if genre == "deep_house":
        bpm = 122.0 if tempo == "medium" else (118.0 if tempo == "slow" else 126.0)
    elif genre == "techno":
        bpm = 130.0 if tempo != "slow" else 124.0
    elif genre == "ambient":
        bpm = 80.0
    elif genre == "cinematic":
        bpm = 90.0
    elif genre in ("none", ""):
        genre = "ambient" if mood in ("calm", "peaceful", "dreamy") else "deep_house"

    bars = max(4, int(math.ceil(duration_sec * bpm / 60.0 / 4.0)) * 4)
    # Section plan
    if duration_sec < 3:
        sections = ["drop"]
    elif duration_sec < 8:
        sections = ["intro", "drop"]
    else:
        sections = ["intro", "build", "drop", "break"]
    return Arrangement(genre=genre, bpm=bpm, sections=sections, bars=bars)


def _beat_ms(bpm: float) -> float:
    return 60_000.0 / max(60.0, bpm)


def _kick(dur_ms: int = 90):
    from pydub.generators import Sine
    # Pitch-down thump approximation: low sine + fade
    seg = Sine(55).to_audio_segment(duration=dur_ms).fade_out(dur_ms)
    return seg + (-10)


def _hat(dur_ms: int = 40):
    try:
        from pydub.generators import WhiteNoise
        seg = WhiteNoise().to_audio_segment(duration=dur_ms).fade_out(dur_ms)
        return seg + (-28)
    except ImportError:
        from pydub.generators import Sine
        return Sine(8000).to_audio_segment(duration=dur_ms).fade_out(dur_ms) + (-30)


def _bass_note(freq: float, dur_ms: int):
    from pydub.generators import Sine
    return Sine(freq).to_audio_segment(duration=dur_ms).fade_out(min(80, dur_ms // 2)) + (-16)


def _pad_chord(freqs: list[float], dur_ms: int):
    from pydub import AudioSegment
    from pydub.generators import Sine
    base = AudioSegment.silent(duration=dur_ms)
    for f in freqs:
        tone = Sine(f).to_audio_segment(duration=dur_ms).fade_in(40).fade_out(min(200, dur_ms // 3))
        base = base.overlay(tone + (-22))
    return base


def generate_arrangement_audio(
    duration_ms: int,
    *,
    genre: str = "deep_house",
    tempo: str = "medium",
    mood: str = "neutral",
    sample_rate: int = 44100,
):
    """Render a full music bed for duration_ms."""
    from pydub import AudioSegment

    duration_sec = duration_ms / 1000.0
    arr = arrangement_for(genre, tempo=tempo, mood=mood, duration_sec=duration_sec)
    beat = _beat_ms(arr.bpm)
    bar = beat * 4
    out = AudioSegment.silent(duration=duration_ms, frame_rate=sample_rate)

    # Chord roots by mood (Hz)
    root = {
        "dark": 55.0,
        "tense": 58.0,
        "calm": 65.0,
        "peaceful": 65.0,
        "dreamy": 73.0,
        "uplifting": 82.0,
        "energetic": 87.0,
        "neutral": 73.0,
    }.get((mood or "neutral").lower(), 73.0)

    if arr.genre in ("deep_house", "techno"):
        # Four-on-floor kick
        t = 0.0
        while t < duration_ms:
            out = out.overlay(_kick(), position=int(t))
            t += beat
        # Offbeat hats
        t = beat / 2
        while t < duration_ms:
            out = out.overlay(_hat(), position=int(t))
            t += beat
        # Bass every bar
        bass_pattern = [root, root * 1.5, root * 1.25, root * 0.75]
        bar_i = 0
        t = 0.0
        while t < duration_ms:
            freq = bass_pattern[bar_i % len(bass_pattern)]
            note_dur = int(min(bar * 0.9, duration_ms - t))
            if note_dur > 20:
                out = out.overlay(_bass_note(freq, note_dur), position=int(t))
            t += bar
            bar_i += 1
        # Pad stabs on drop sections (second half)
        if duration_ms > 2000:
            pad = _pad_chord([root * 2, root * 2.5, root * 3], min(800, duration_ms // 3))
            out = out.overlay(pad, position=duration_ms // 2)

    elif arr.genre == "cinematic":
        pad = _pad_chord([root, root * 1.5, root * 2], duration_ms)
        out = out.overlay(pad)
        # Sparse low hits
        t = 0.0
        while t < duration_ms:
            out = out.overlay(_kick(120) + (-6), position=int(t))
            t += bar * 2

    else:  # ambient
        pad = _pad_chord([root, root * 1.25, root * 1.5], duration_ms)
        out = out.overlay(pad + (-4))

    return out.set_frame_rate(sample_rate)


def duck_under_sfx(music, sfx_events: list[dict[str, Any]] | None, *, duck_db: float = -6.0):
    """Slightly reduce music around SFX hits (simple whole-bed duck — lightweight)."""
    if not sfx_events:
        return music
    # For v1: global slight reduction when many events; per-hit ducking is expensive
    if len(sfx_events) >= 2:
        return music + duck_db / 2
    return music

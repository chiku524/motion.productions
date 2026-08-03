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
    sections: list[str] | None = None,
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
    # Prefer script-aligned sections when provided (educational / mini-scene beats)
    if sections:
        cleaned = [str(s).lower() for s in sections if s]
        plan = cleaned if cleaned else ["drop"]
    elif duration_sec < 3:
        plan = ["drop"]
    elif duration_sec < 8:
        plan = ["intro", "drop"]
    else:
        plan = ["intro", "build", "drop", "break"]
    return Arrangement(genre=genre, bpm=bpm, sections=plan, bars=bars)


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


def _section_bounds_ms(
    duration_ms: int,
    n_sec: int,
    section_durations_ms: list[float] | None = None,
) -> list[float]:
    """Cumulative end times (ms) for each music section. Unequal when weights given."""
    n_sec = max(1, n_sec)
    if section_durations_ms and len(section_durations_ms) >= n_sec:
        weights = [max(1.0, float(w)) for w in section_durations_ms[:n_sec]]
        total_w = sum(weights) or 1.0
        scale = duration_ms / total_w
        bounds: list[float] = []
        acc = 0.0
        for w in weights:
            acc += w * scale
            bounds.append(acc)
        bounds[-1] = float(duration_ms)
        return bounds
    section_ms = duration_ms / n_sec
    return [(i + 1) * section_ms for i in range(n_sec)]


def _section_index_at(t_ms: float, bounds: list[float]) -> int:
    for i, end in enumerate(bounds):
        if t_ms < end:
            return i
    return max(0, len(bounds) - 1)


def generate_arrangement_audio(
    duration_ms: int,
    *,
    genre: str = "deep_house",
    tempo: str = "medium",
    mood: str = "neutral",
    sample_rate: int = 44100,
    music_sections: list[str] | None = None,
    section_durations_ms: list[float] | None = None,
):
    """Render a full music bed for duration_ms."""
    from pydub import AudioSegment

    duration_sec = duration_ms / 1000.0
    arr = arrangement_for(
        genre, tempo=tempo, mood=mood, duration_sec=duration_sec, sections=music_sections,
    )
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

    # Section timeline: prefer beat-weighted windows over equal splits
    n_sec = max(1, len(arr.sections))
    bounds = _section_bounds_ms(duration_ms, n_sec, section_durations_ms)

    def _sec_len(i: int) -> float:
        start = 0.0 if i == 0 else bounds[i - 1]
        return max(1.0, bounds[i] - start)

    if arr.genre in ("deep_house", "techno"):
        # Four-on-floor kick — quieter in intro/break
        t = 0.0
        while t < duration_ms:
            sec_i = _section_index_at(t, bounds)
            section = arr.sections[sec_i] if arr.sections else "drop"
            kick_adj = {"intro": -6, "break": -6, "build": -2}.get(section, 0)
            out = out.overlay(_kick() + kick_adj, position=int(t))
            t += beat
        # Offbeat hats (skip sparse intro)
        t = beat / 2
        while t < duration_ms:
            sec_i = _section_index_at(t, bounds)
            section = arr.sections[sec_i] if arr.sections else "drop"
            if section != "intro":
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
        # Pad stabs on drop/build sections
        for i, section in enumerate(arr.sections):
            if section in ("drop", "build") and duration_ms > 1500:
                sec_len = _sec_len(i)
                start = 0.0 if i == 0 else bounds[i - 1]
                pos = int(start + sec_len * 0.15)
                pad = _pad_chord([root * 2, root * 2.5, root * 3], min(800, int(sec_len * 0.5)))
                if pos < duration_ms:
                    out = out.overlay(pad, position=pos)

    elif arr.genre == "cinematic":
        # Section-shaped pad + denser hits on drop
        for i, section in enumerate(arr.sections or ["drop"]):
            start = 0.0 if i == 0 else bounds[i - 1]
            end = bounds[i] if i < len(bounds) else float(duration_ms)
            chunk = max(1, int(end - start))
            gain = {"intro": -8, "build": -4, "drop": -2, "break": -10}.get(section, -4)
            pad = _pad_chord([root, root * 1.5, root * 2], chunk) + gain
            out = out.overlay(pad, position=int(start))
        t = 0.0
        while t < duration_ms:
            sec_i = _section_index_at(t, bounds)
            section = arr.sections[sec_i] if arr.sections else "drop"
            step = bar if section == "drop" else bar * 2
            hit_adj = {"intro": -10, "break": -12, "build": -8}.get(section, -6)
            out = out.overlay(_kick(120) + hit_adj, position=int(t))
            t += step

    else:  # ambient — gentle section dynamics (not a flat pad)
        for i, section in enumerate(arr.sections or ["drop"]):
            start = 0.0 if i == 0 else bounds[i - 1]
            end = bounds[i] if i < len(bounds) else float(duration_ms)
            chunk = max(1, int(end - start))
            gain = {"intro": -10, "build": -6, "drop": -3, "break": -12}.get(section, -6)
            freqs = [root, root * 1.25, root * 1.5]
            if section == "drop":
                freqs = [root, root * 1.5, root * 2]
            elif section == "break":
                freqs = [root, root * 1.2]
            pad = _pad_chord(freqs, chunk) + gain
            out = out.overlay(pad, position=int(start))
            # Sparse soft ticks on drop/build only
            if section in ("drop", "build") and chunk > 800:
                tick_t = start + chunk * 0.35
                out = out.overlay(_hat() + (-14), position=int(tick_t))

    return out.set_frame_rate(sample_rate)


def duck_under_sfx(music, sfx_events: list[dict[str, Any]] | None, *, duck_db: float = -6.0):
    """Slightly reduce music around SFX hits (simple whole-bed duck — lightweight)."""
    if not sfx_events:
        return music
    # For v1: global slight reduction when many events; per-hit ducking is expensive
    if len(sfx_events) >= 2:
        return music + duck_db / 2
    return music

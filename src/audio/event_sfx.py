"""
Event-synced SFX scheduler: overlay Pure-sound-style hits at timed events
(e.g. bounce impacts). Fully in-house — no external APIs.
"""
from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


def _make_hit(
    kind: str,
    *,
    strength: float = 0.8,
    sample_rate: int = 44100,
):
    """Synthesize a short SFX hit as an AudioSegment."""
    from pydub import AudioSegment
    from pydub.generators import Sine

    try:
        from pydub.generators import WhiteNoise
    except ImportError:
        WhiteNoise = None  # type: ignore[misc, assignment]

    strength = max(0.1, min(1.0, float(strength)))
    kind = (kind or "impact").lower()

    if kind in ("bounce", "thump", "impact"):
        # Low thump + short noise burst
        dur = int(80 + 40 * strength)
        freq = 90.0 if kind == "bounce" else (70.0 if kind == "thump" else 110.0)
        tone = Sine(freq).to_audio_segment(duration=dur)
        # Exponential-ish fade
        tone = tone.fade_out(dur)
        tone = tone + (-18 + 8 * strength)
        if WhiteNoise is not None:
            noise = WhiteNoise().to_audio_segment(duration=max(20, dur // 3))
            noise = noise.fade_out(max(15, dur // 3)) + (-28)
            tone = tone.overlay(noise)
        return tone.set_frame_rate(sample_rate)

    if kind == "click":
        dur = 25
        tone = Sine(1800).to_audio_segment(duration=dur).fade_out(dur)
        return (tone + (-16)).set_frame_rate(sample_rate)

    if kind == "whoosh":
        dur = int(180 + 80 * strength)
        if WhiteNoise is not None:
            noise = WhiteNoise().to_audio_segment(duration=dur)
            noise = noise.fade_in(dur // 3).fade_out(dur // 2) + (-22)
            return noise.set_frame_rate(sample_rate)
        tone = Sine(400).to_audio_segment(duration=dur).fade_in(40).fade_out(dur // 2)
        return (tone + (-20)).set_frame_rate(sample_rate)

    if kind == "rustle":
        dur = 120
        if WhiteNoise is not None:
            noise = WhiteNoise().to_audio_segment(duration=dur).fade_out(dur) + (-30)
            return noise.set_frame_rate(sample_rate)
        return AudioSegment.silent(duration=dur, frame_rate=sample_rate)

    if kind == "drip":
        tone = Sine(880).to_audio_segment(duration=40).fade_out(35) + (-18)
        return tone.set_frame_rate(sample_rate)

    # Default impact
    tone = Sine(100).to_audio_segment(duration=60).fade_out(55) + (-20)
    return tone.set_frame_rate(sample_rate)


def schedule_sfx_events(
    base,
    events: list[dict[str, Any]] | None,
    *,
    duration_ms: int,
    sample_rate: int = 44100,
):
    """
    Overlay timed SFX events onto an AudioSegment bed.
    events: [{kind, t_sec, strength}]
    """
    if not events:
        return base
    from pydub import AudioSegment

    out = base
    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("kind") or "impact")
        t_sec = ev.get("t_sec")
        if t_sec is None:
            continue
        try:
            pos_ms = int(float(t_sec) * 1000)
        except (TypeError, ValueError):
            continue
        if pos_ms < 0 or pos_ms >= duration_ms:
            continue
        strength = float(ev.get("strength") or 0.8)
        try:
            hit = _make_hit(kind, strength=strength, sample_rate=sample_rate)
            out = out.overlay(hit, position=pos_ms)
        except Exception as e:
            logger.debug("SFX overlay failed kind=%s: %s", kind, e)
    return out


def infer_bounce_events(
    duration_sec: float,
    *,
    interval: float = 0.7,
    strength: float = 0.8,
) -> list[dict[str, Any]]:
    """Evenly spaced bounce events when no scene-graph timings exist."""
    duration_sec = max(0.5, float(duration_sec))
    events: list[dict[str, Any]] = []
    t = interval * 0.5
    while t < duration_sec:
        events.append({"kind": "bounce", "t_sec": round(t, 3), "strength": strength})
        t += interval
    return events


def infer_weather_events(
    setting: str | None,
    duration_sec: float,
) -> list[dict[str, Any]]:
    """Sparse weather SFX for rain/snow/forest settings."""
    s = (setting or "").strip().lower()
    duration_sec = max(0.5, float(duration_sec))
    events: list[dict[str, Any]] = []
    if s == "rain":
        t = 0.35
        while t < duration_sec:
            events.append({"kind": "drip", "t_sec": round(t, 3), "strength": 0.4})
            t += 0.55 + (0.25 * ((int(t * 10) % 3) / 3.0))
    elif s == "snow":
        t = 0.8
        while t < duration_sec:
            events.append({"kind": "rustle", "t_sec": round(t, 3), "strength": 0.3})
            t += 1.4
    elif s in ("forest", "park"):
        t = 1.0
        while t < duration_sec:
            events.append({"kind": "rustle", "t_sec": round(t, 3), "strength": 0.35})
            t += 1.8
    return events


def cut_accent_events(
    cut_times: list[float] | None,
    *,
    transition_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Accents at scene cuts. transition_types aligns with cut_times when provided:
    cut→click, fade/dissolve→soft whoosh, wipe→whoosh.
    """
    if not cut_times:
        return []
    events: list[dict[str, Any]] = []
    for i, t in enumerate(cut_times):
        if not t or float(t) <= 0.05:
            continue
        kind = "click"
        strength = 0.45
        if transition_types and i < len(transition_types):
            tt = (transition_types[i] or "cut").lower()
            if tt in ("dissolve", "fade"):
                kind = "whoosh"
                strength = 0.35
            elif tt == "wipe":
                kind = "whoosh"
                strength = 0.55
            elif tt == "cut":
                kind = "click"
                strength = 0.45
        events.append({"kind": kind, "t_sec": float(t), "strength": strength})
    return events

"""
Offline vocal beds (Phase 4) — no cloud TTS required.

Primary: formant / vowel-pad synthesis on chord tones.
Optional: local TTS (espeak/piper) if present on PATH for short phrases.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_vocal_bed(
    duration_ms: int,
    *,
    mood: str = "neutral",
    root_hz: float | None = None,
    sample_rate: int = 44100,
):
    """Sung-ish non-lyrical vocal pad from layered sines (formant-ish)."""
    from pydub import AudioSegment
    from pydub.generators import Sine

    mood = (mood or "neutral").lower()
    root = root_hz or {
        "dark": 110.0,
        "calm": 146.0,
        "dreamy": 164.0,
        "uplifting": 196.0,
        "energetic": 220.0,
        "neutral": 174.0,
    }.get(mood, 174.0)

    # Simple vowel formant ratios
    formants = [root, root * 2.2, root * 3.5]
    bed = AudioSegment.silent(duration=duration_ms, frame_rate=sample_rate)
    for i, f in enumerate(formants):
        tone = Sine(f).to_audio_segment(duration=duration_ms)
        tone = tone.fade_in(200).fade_out(min(400, duration_ms // 4))
        # Tremolo-ish via volume steps every ~500ms
        gain = -24 - i * 3
        bed = bed.overlay(tone + gain)
    return bed.set_frame_rate(sample_rate)


def try_local_tts(text: str, *, duration_ms: int | None = None, sample_rate: int = 44100):
    """
    If espeak or piper is on PATH, synthesize speech; else return None.
    Never calls network services.
    """
    text = (text or "").strip()
    if not text or len(text) > 200:
        return None

    espeak = shutil.which("espeak") or shutil.which("espeak-ng")
    if espeak:
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = f.name
            subprocess.run(
                [espeak, "-w", wav_path, text],
                check=True,
                capture_output=True,
                timeout=15,
            )
            from pydub import AudioSegment
            seg = AudioSegment.from_file(wav_path)
            Path(wav_path).unlink(missing_ok=True)
            if duration_ms and len(seg) > duration_ms:
                seg = seg[:duration_ms]
            return seg.set_frame_rate(sample_rate)
        except Exception as e:
            logger.debug("espeak TTS failed: %s", e)
            Path(wav_path).unlink(missing_ok=True) if "wav_path" in dir() else None

    piper = shutil.which("piper")
    if piper:
        logger.debug("piper found but voice model not configured — skipping")
    return None


def mix_vocals_into(
    bed,
    *,
    enable: bool,
    mood: str = "neutral",
    phrase: str | None = None,
    duration_ms: int,
):
    """Overlay vocal bed (+ optional local TTS phrase) onto music/ambient bed."""
    if not enable:
        return bed
    vocals = generate_vocal_bed(duration_ms, mood=mood)
    out = bed.overlay(vocals)
    if phrase:
        spoken = try_local_tts(phrase, duration_ms=min(duration_ms, 5000))
        if spoken is not None:
            out = out.overlay(spoken, position=max(0, duration_ms // 10))
    return out

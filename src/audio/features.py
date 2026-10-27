"""
Per-frame audio feature measurement shared by the extractor (what a clip actually contains) and the
sound v2 synth (closed-loop targeting of a cell), so both sides bin identical numbers.

Mono float samples in int16 units (-32768..32767). Pure numpy, deterministic, no I/O.
"""
from __future__ import annotations

from typing import Any

import numpy as np

FFT_MAX = 2048
MIN_FFT_SAMPLES = 256


def to_mono(samples: Any, channels: int = 1) -> np.ndarray:
    x = np.asarray(samples, dtype=np.float64)
    ch = int(channels or 1)
    if ch > 1 and x.size >= ch:
        x = x[: (x.size // ch) * ch].reshape(-1, ch).mean(axis=1)
    return x


def measure_audio_frame(samples: Any, sample_rate: int, channels: int = 1) -> dict[str, float]:
    """amplitude (RMS 0..1), peak_hz, spectral_flatness, attack_ratio, zcr for one frame of audio."""
    x = to_mono(samples, channels)
    out = {"amplitude": 0.0, "peak_hz": 0.0, "spectral_flatness": 0.5, "attack_ratio": 0.0, "zcr": 0.0}
    n = int(x.size)
    if n == 0:
        return out
    rms = float(np.sqrt(np.mean(x ** 2)))
    out["amplitude"] = min(1.0, rms / 32768.0) if rms else 0.0
    if n < MIN_FFT_SAMPLES:
        return out
    chunk = x[:FFT_MAX]
    fft = np.abs(np.fft.rfft(chunk))
    # Frequencies must use the real chunk length: a 1/24 s frame at 44.1 kHz is 1837 samples, not 2048.
    freqs = np.fft.rfftfreq(len(chunk), 1.0 / float(sample_rate))
    if fft.size and np.max(fft) > 0:
        out["peak_hz"] = float(freqs[int(np.argmax(fft))])
        geom = np.exp(np.mean(np.log(fft + 1e-12)))
        arith = np.mean(fft) + 1e-12
        out["spectral_flatness"] = float(min(1.0, max(0.0, geom / arith)))
    half = max(1, len(chunk) // 2)
    attack_rms = float(np.sqrt(np.mean(chunk[:half] ** 2)))
    tail_rms = float(np.sqrt(np.mean(chunk[half:] ** 2))) + 1e-12
    out["attack_ratio"] = float(min(1.0, attack_rms / (attack_rms + tail_rms)))
    signs = np.sign(chunk)
    out["zcr"] = float(np.mean(signs[1:] != signs[:-1]))
    return out
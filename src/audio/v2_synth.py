"""
Sound v2 synth: build audio that aims at specific sound.L1 cells (see src/knowledge/keyspace.py).

Closed loop: for each target cell a small deterministic grid of (tone frequency, noise ratio, noise colour)
candidates is rendered, MEASURED with the same function the extractor uses (src/audio/features.py) and the
candidate that lands in the cell most often is used. Cells the grid cannot hit are reported, never faked:
the registry only ever records what the extractor measures from the decoded clip.

Deterministic for a given seed; peak is limited to PEAK_CEILING so clips never clip.
"""
from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from ..knowledge import keyspace as K
from .features import measure_audio_frame

PEAK_CEILING = 10 ** (-1.0 / 20.0)  # -1 dBFS
_TRIALS = 3
_RATIOS = (0.0, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 25.0, 60.0)
_COLOURS = ("white", "low", "high", "vlow", "vhigh")


def _rng(seed: int, *salt: Any) -> np.random.Generator:
    key = "|".join(str(x) for x in (int(seed), *salt)).encode()
    return np.random.default_rng(int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big"))


def _noise(rng: np.random.Generator, n: int, colour: str, sr: int) -> np.ndarray:
    w = rng.standard_normal(n)
    if colour != "white":
        spec = np.fft.rfft(w)
        f = np.fft.rfftfreq(n, 1.0 / sr)
        shape = {
            "low": 1.0 / (1.0 + f / 300.0),
            "vlow": 1.0 / (1.0 + (f / 300.0) ** 2),
            "high": f / 2000.0 + 0.02,
            "vhigh": (f / 2000.0) ** 2 + 0.002,
        }[colour]
        spec *= shape
        w = np.fft.irfft(spec, n)
    rms = float(np.sqrt(np.mean(w ** 2))) or 1.0
    return w / rms


def render_frame(
    rng: np.random.Generator, n: int, sr: int, *, freq: float, noise_ratio: float, colour: str,
    amplitude: float, attack_ratio: float,
) -> np.ndarray:
    """One frame (n samples, int16 units, float64). RMS ~= amplitude*32768 unless the peak ceiling bites."""
    t = np.arange(n) / sr
    tone = np.sqrt(2.0) * np.sin(2 * np.pi * freq * t + rng.uniform(0, 2 * np.pi))
    x = tone + noise_ratio * _noise(rng, n, colour, sr) if noise_ratio > 0 else tone
    # first-half vs second-half level share -> measured attack_ratio
    r = min(0.97, max(0.03, attack_ratio))
    env = np.empty(n)
    half = max(1, n // 2)
    env[:half] = r
    env[half:] = 1.0 - r
    k = max(1, n // 64)  # smooth the step so the join does not click
    env = np.convolve(np.pad(env, (k, k), mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")[:n]
    x = x * env
    rms = float(np.sqrt(np.mean(x ** 2))) or 1.0
    x = x * (amplitude * 32768.0 / rms)
    peak = float(np.max(np.abs(x))) or 1.0
    if peak > PEAK_CEILING * 32767.0:
        x = x * (PEAK_CEILING * 32767.0 / peak)
    return x


def _hit(x: np.ndarray, sr: int, ordinal: int) -> bool:
    m = measure_audio_frame(np.round(x), sr)
    key = K.sound_v2_key(m["amplitude"], m["peak_hz"], m["spectral_flatness"], m["attack_ratio"], m["zcr"])
    return K.sound_v2_key_to_ordinal(key) == ordinal


def _candidates(ordinal: int) -> list[dict[str, Any]]:
    c = K.sound_v2_cell_center(ordinal)
    _, band, _, _, _ = K.decode_sound_v2_ordinal(ordinal)
    lo = 0.0 if band == 0 else K.SOUND_V2_BAND_EDGES[band - 1]
    hi = K.SOUND_V2_BAND_EDGES[band] if band < len(K.SOUND_V2_BAND_EDGES) else 16000.0
    freqs = [c["peak_hz"], max(lo, 40.0) * 1.15, hi * 0.87]
    out = []
    for ratio in _RATIOS:
        for colour in _COLOURS if ratio > 0 else ("white",):
            for f in freqs:
                out.append({"freq": float(min(max(f, 30.0), 20000.0)), "noise_ratio": ratio, "colour": colour})
    return out


def plan_cell(ordinal: int, *, sr: int = 44100, fps: float = 24.0, seed: int = 0) -> dict[str, Any]:
    """Pick the best candidate for a cell by measuring it. Returns params + expected hit rate (0..1)."""
    n = max(256, int(sr / fps))
    c = K.sound_v2_cell_center(ordinal)
    best: dict[str, Any] | None = None
    for i, cand in enumerate(_candidates(ordinal)):
        hits = 0
        for trial in range(_TRIALS):
            rng = _rng(seed, ordinal, i, trial)
            x = render_frame(rng, n, sr, amplitude=c["amplitude"], attack_ratio=c["attack_ratio"], **cand)
            hits += int(_hit(x, sr, ordinal))
        if best is None or hits > best["hits"]:
            best = {**cand, "hits": hits}
        if hits == _TRIALS:
            break
    assert best is not None
    return {
        "ordinal": ordinal,
        "cell_id": K.sound_v2_cell_id(ordinal),
        "amplitude": c["amplitude"],
        "attack_ratio": c["attack_ratio"],
        "freq": best["freq"],
        "noise_ratio": best["noise_ratio"],
        "colour": best["colour"],
        "expected_hit_rate": best["hits"] / _TRIALS,
    }


def synth_v2_cells(
    ordinals: list[int], duration_ms: int, *, seed: int = 0, sample_rate: int = 44100, fps: float = 24.0,
):
    """AudioSegment (mono 16-bit) whose frames are split evenly between the target cells.

    Returns (segment, plans). Frames are 1/fps long so the extractor's per-frame measurement sees them as
    rendered. Needs at least 2 frames per cell; extra cells beyond that budget are dropped.
    """
    from pydub import AudioSegment

    n = max(256, int(sample_rate / fps))
    total = max(1, int(round(duration_ms / 1000.0 * fps)))
    cells = list(dict.fromkeys(int(o) for o in ordinals))[: max(1, total // 2)]
    plans = [plan_cell(o, sr=sample_rate, fps=fps, seed=seed) for o in cells]
    per = max(2, total // max(1, len(plans)))
    chunks: list[np.ndarray] = []
    for pi, p in enumerate(plans):
        for fi in range(per):
            rng = _rng(seed, "frame", p["ordinal"], pi, fi)
            chunks.append(render_frame(
                rng, n, sample_rate, freq=p["freq"], noise_ratio=p["noise_ratio"], colour=p["colour"],
                amplitude=p["amplitude"], attack_ratio=p["attack_ratio"],
            ))
    pcm = np.concatenate(chunks) if chunks else np.zeros(n)
    want = int(sample_rate * duration_ms / 1000.0)
    if pcm.size < want:
        pcm = np.concatenate([pcm, np.zeros(want - pcm.size)])
    pcm = np.clip(np.round(pcm[:want]), -32768, 32767).astype("<i2")
    seg = AudioSegment(data=pcm.tobytes(), sample_width=2, frame_rate=sample_rate, channels=1)
    return seg, plans
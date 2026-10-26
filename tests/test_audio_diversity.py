"""Audio variation: per-seed primitive textures, window layers all audible."""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("pydub")

from src.audio import sound as S  # noqa: E402
from src.knowledge.blend_depth import SOUND_ORIGIN_PRIMITIVES  # noqa: E402

PRIMS = [p for p in SOUND_ORIGIN_PRIMITIVES if p != "silence"]


def _samples(seg) -> np.ndarray:
    return np.array(seg.get_array_of_samples(), dtype=np.float64)


def _spectrum(seg, bands: int = 24) -> np.ndarray:
    x = _samples(seg)
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    edges = np.unique(np.geomspace(20, len(mag) - 1, bands + 1).astype(int))
    e = np.array([mag[a:b].sum() for a, b in zip(edges[:-1], edges[1:])])
    return e / max(e.sum(), 1e-9)


@pytest.mark.parametrize("prim", PRIMS)
def test_texture_deterministic_per_seed(prim):
    a = S._primitive_texture(prim, 1000, db=-20, seed=11)
    b = S._primitive_texture(prim, 1000, db=-20, seed=11)
    assert a.raw_data == b.raw_data
    assert len(a) == 1000


@pytest.mark.parametrize("prim", PRIMS)
def test_texture_differs_between_seeds(prim):
    specs = [_spectrum(S._primitive_texture(prim, 1000, db=-20, seed=s)) for s in range(1, 9)]
    raw = {S._primitive_texture(prim, 1000, db=-20, seed=s).raw_data for s in range(1, 9)}
    assert len(raw) == 8
    # spectra must not all collapse onto one shape
    dists = [float(np.abs(specs[i] - specs[j]).sum()) for i in range(8) for j in range(i + 1, 8)]
    assert max(dists) > 0.05, f"{prim}: spectra identical across seeds"


def test_legacy_texture_unchanged_without_seed():
    a = S._primitive_texture("hum", 1000, db=-20)
    b = S._primitive_texture_legacy("hum", 1000, db=-20)
    assert a.raw_data == b.raw_data


def test_same_pairing_different_seed_sounds_different():
    pair = [S.__dict__["_primitive_from_entry"]({"name": p}) for p in ("hum", "click")]
    entries = [{"name": p, "amplitude": 0.6} for p in pair]
    mixes = [S.generate_audio_from_pure_sounds(entries, 1000, pairing_kind="frame", seed=s) for s in range(1, 7)]
    assert len({m.raw_data for m in mixes}) == 6
    specs = [_spectrum(m) for m in mixes]
    assert max(float(np.abs(specs[0] - s).sum()) for s in specs[1:]) > 0.05


def test_window_mix_every_layer_audible_in_one_second(monkeypatch):
    from pydub.generators import Sine

    freqs = {"hum": 220.0, "tone": 660.0, "click": 1320.0, "drip": 2640.0}

    def fake(prim, duration_ms, *, db=-20.0, tempo_ms=2500, sample_rate=44100, seed=None):
        return Sine(freqs[prim], sample_rate=sample_rate).to_audio_segment(duration=duration_ms) + db

    monkeypatch.setattr(S, "_primitive_texture", fake)
    entries = [{"name": n, "amplitude": 0.6} for n in freqs]
    for seed in (None, 5):
        mix = S.generate_audio_from_pure_sounds(entries, 1000, pairing_kind="window", seed=seed)
        x = _samples(mix)
        mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        hz = np.fft.rfftfreq(len(x), 1 / mix.frame_rate)
        floor = float(np.median(mag))
        for name, f in freqs.items():
            peak = float(mag[(hz > f * 0.97) & (hz < f * 1.03)].max())
            assert peak > floor * 20, f"{name} inaudible in 1s window (seed={seed})"


def test_window_and_frame_differ():
    entries = [{"name": p, "amplitude": 0.6} for p in ("hum", "click", "rustle")]
    f = S.generate_audio_from_pure_sounds(entries, 2000, pairing_kind="frame", seed=3)
    w = S.generate_audio_from_pure_sounds(entries, 2000, pairing_kind="window", seed=3)
    assert f.raw_data != w.raw_data
    assert len(f) == len(w) == 2000


def test_seed_reaches_audio_from_spec():
    from src.procedural.parser import SceneSpec

    assert "creation_seed" in SceneSpec.__dataclass_fields__
    assert S.layer_seed(None, 0) is None
    assert S.layer_seed(7, 0) != S.layer_seed(7, 1)
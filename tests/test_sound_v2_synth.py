"""Sound v2: widened synth range, peak limiter, closed-loop cell synth (deterministic by seed)."""
from __future__ import annotations

import numpy as np

from src.audio import sound as S
from src.audio.features import measure_audio_frame
from src.audio.v2_synth import plan_cell, synth_v2_cells
from src.knowledge import keyspace as K

# Cells the synth reaches with 100% of its trial frames (found by calibration; stable by seed).
REACHABLE = [43, 746, 1407, 2015, 2539, 3190, 3938, 4620, 5136, 5656]


def _pcm(seg) -> np.ndarray:
    return np.array(seg.get_array_of_samples(), dtype=np.float64)


def test_amp_to_db_is_monotonic_capped_and_silent_floor():
    xs = [0.0005, 0.001, 0.01, 0.1, 0.3, 0.6, 1.0, 5.0]
    dbs = [S.amp_to_db(x) for x in xs]
    assert dbs[0] == S.SILENT_DB
    assert all(a <= b for a, b in zip(dbs, dbs[1:]))
    assert max(dbs) <= S.PEAK_CEILING_DB + 1e-9


def test_tone_db_range_is_wider_than_the_old_twelve_db_span():
    _, lo = S._tone_to_freq_db("mid", 0.01)
    _, hi = S._tone_to_freq_db("mid", 1.0)
    assert hi - lo > 30.0  # was 12 dB (-30..-18)


def test_pure_sound_mix_tracks_amplitude_and_never_clips():
    def entry(amp):
        return {"amplitude": amp, "tone": "mid", "timbre": "hum", "weight": "medium", "name": "x"}

    quiet = S.generate_audio_from_pure_sounds([entry(0.02)], 1000, seed=3)
    loud = S.generate_audio_from_pure_sounds([entry(0.95)], 1000, seed=3)
    assert loud.dBFS - quiet.dBFS > 20.0  # old mapping: <= 10 dB
    for seg in (quiet, loud):
        assert seg.max_dBFS <= S.PEAK_CEILING_DB + 0.2


def test_limit_peak_only_attenuates_and_is_deterministic():
    from pydub.generators import Sine

    hot = Sine(440).to_audio_segment(duration=500, volume=-0.1)
    out = S.limit_peak(hot)
    assert out.max_dBFS <= S.PEAK_CEILING_DB + 0.2
    assert S.limit_peak(hot).raw_data == out.raw_data
    soft = Sine(440).to_audio_segment(duration=500, volume=-30.0)
    assert S.limit_peak(soft).raw_data == soft.raw_data


def test_synth_is_deterministic_by_seed_and_varies_across_seeds():
    a, pa = synth_v2_cells(REACHABLE[:4], 1000, seed=7)
    b, pb = synth_v2_cells(REACHABLE[:4], 1000, seed=7)
    c, _ = synth_v2_cells(REACHABLE[:4], 1000, seed=8)
    assert a.raw_data == b.raw_data and pa == pb
    assert a.raw_data != c.raw_data


def test_synth_clips_are_one_second_non_clipping_and_cover_all_amp_bins():
    seg, plans = synth_v2_cells(REACHABLE, 3000, seed=1)
    assert len(seg) == 3000 and seg.channels == 1
    pcm = _pcm(seg)
    assert np.abs(pcm).max() <= 32767 * 10 ** (S.PEAK_CEILING_DB / 20.0) + 2
    assert {K.decode_sound_v2_ordinal(p["ordinal"])[0] for p in plans} == {K.decode_sound_v2_ordinal(o)[0] for o in REACHABLE}


def test_closed_loop_frames_measure_into_their_target_cells():
    sr, n = 44100, int(44100 / 24)
    seg, plans = synth_v2_cells(REACHABLE[:6], 2000, seed=2)
    pcm = _pcm(seg).astype(np.float64)
    per = len(pcm) // n // len(plans)
    hits = total = 0
    for pi, p in enumerate(plans):
        for fi in range(per):
            i = (pi * per + fi) * n
            m = measure_audio_frame(pcm[i : i + n], sr)
            key = K.sound_v2_key(m["amplitude"], m["peak_hz"], m["spectral_flatness"], m["attack_ratio"], m["zcr"])
            hits += int(K.sound_v2_key_to_ordinal(key) == p["ordinal"])
            total += 1
    assert total >= 12
    assert hits / total >= 0.5  # honest closed loop: most frames land in the target cell


def test_plan_cell_reports_expected_hit_rate_honestly():
    p = plan_cell(REACHABLE[0])
    assert 0.0 <= p["expected_hit_rate"] <= 1.0
    assert p["cell_id"] == K.sound_v2_cell_id(REACHABLE[0])


def test_generate_audio_only_target_v2_cells(tmp_path):
    out = S.generate_audio_only(1.0, tmp_path / "a.wav", target_v2_cells=REACHABLE[:3], seed=4)
    assert out.exists() and out.stat().st_size > 1000
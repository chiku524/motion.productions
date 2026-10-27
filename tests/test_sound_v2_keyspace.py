"""Sound v2 (sound.L1) key space: binning, ordinals, decoding, parity vectors shared with the Worker."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.knowledge import keyspace as K

VECTORS = json.loads((Path(__file__).parent / "vectors" / "sound_v2_vectors.json").read_text(encoding="utf-8"))


def test_space_size_is_product_of_radices():
    prod = 1
    for r in K.SOUND_V2_RADICES:
        prod *= r
    assert prod == K.SOUND_V2_SPACE_SIZE == 6144


def test_every_ordinal_round_trips_and_keys_are_unique():
    keys = set()
    for n in range(K.SOUND_V2_SPACE_SIZE):
        bins = K.decode_sound_v2_ordinal(n)
        assert K.sound_v2_ordinal(bins) == n
        key = K.sound_v2_key_from_bins(bins)
        assert K.is_sound_v2_key(key)
        assert K.sound_v2_key_to_ordinal(key) == n
        keys.add(key)
    assert len(keys) == K.SOUND_V2_SPACE_SIZE


def test_cell_centres_land_in_their_own_cell():
    """The representative values of a cell must bin back to that same cell (synth targeting relies on it)."""
    for n in range(K.SOUND_V2_SPACE_SIZE):
        c = K.sound_v2_cell_center(n)
        key = K.sound_v2_key(c["amplitude"], c["peak_hz"], c["spectral_flatness"], c["attack_ratio"], c["zcr"])
        assert K.sound_v2_key_to_ordinal(key) == n, (n, c)


@pytest.mark.parametrize("v", VECTORS["vectors"])
def test_parity_vectors(v):
    key = K.sound_v2_key(v["amplitude"], v["peak_hz"], v["flatness"], v["attack"], v["zcr"])
    assert key == v["key"]
    assert K.sound_v2_key_to_ordinal(key) == v["ordinal"]
    assert K.sound_v2_cell_id(key) == v["cell_id"]


def test_amplitude_bins_reach_loud_values_that_v1_could_not():
    """v1 keys stopped at ~0.13 because of the synth range; v2 must separate loud levels."""
    bins = [K.amp_bin(a) for a in (0.0005, 0.002, 0.01, 0.05, 0.13, 0.3, 0.6)]
    assert bins == sorted(bins)
    assert len(set(bins)) == len(bins)
    assert K.amp_bin(1.0) == K.SOUND_V2_AMP_BINS - 1


def test_features_dropped_by_v1_now_change_the_key():
    base = dict(amplitude=0.1, peak_hz=300, spectral_flatness=0.2, attack_ratio=0.5, zcr=0.03)
    k0 = K.sound_v2_key(**base)
    assert K.sound_v2_key(**{**base, "peak_hz": 3000}) != k0  # pitch
    assert K.sound_v2_key(**{**base, "spectral_flatness": 0.6}) != k0  # flatness
    assert K.sound_v2_key(**{**base, "attack_ratio": 0.8}) != k0  # attack
    assert K.sound_v2_key(**{**base, "zcr": 0.2}) != k0  # zcr
    assert K.sound_v2_key(**{**base, "amplitude": 0.4}) != k0  # amplitude


def test_invalid_keys_rejected():
    for bad in ("", "0.12_mid_hum", "s2.12-0-0-0-0", "s2.00-8-0-0-0", "s2.0-0-0-0-0", "s3.00-0-0-0-0", None, 5):
        assert not K.is_sound_v2_key(bad)
    with pytest.raises(ValueError):
        K.parse_sound_v2_key("0.12_mid_hum")
    with pytest.raises(ValueError):
        K.decode_sound_v2_ordinal(K.SOUND_V2_SPACE_SIZE)


def test_non_finite_and_garbage_inputs_do_not_raise():
    key = K.sound_v2_key(float("nan"), None, "x", float("inf"), -1)
    assert K.is_sound_v2_key(key)


def test_segment_without_measured_features_has_no_v2_key():
    assert K.sound_v2_from_segment({}) is None
    assert K.sound_v2_from_segment({"amplitude": 0.1, "tone": "mid"}) is None  # v1-shaped segment
    seg = {"amplitude": 0.1, "peak_hz": 440.0, "spectral_flatness": 0.2, "attack_ratio": 0.5, "zcr": 0.03}
    assert K.is_sound_v2_key(K.sound_v2_from_segment(seg))


def test_v1_keys_are_untouched_by_the_new_module():
    from src.knowledge.growth_per_instance import _static_sound_key

    assert _static_sound_key({"amplitude": 0.12, "tone": "mid", "timbre": "hum"}) == "0.12_mid_hum"
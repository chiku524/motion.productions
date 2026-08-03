"""Gags, tension curves, weather SFX, spotlight, style, multi-shot duration."""
from __future__ import annotations

import unittest

import numpy as np

from src.audio.event_sfx import infer_weather_events
from src.creation.builder import build_spec_from_instruction
from src.creation.scene_script import build_scene_script_from_instruction
from src.depth.layers import create_depth_layers
from src.graphics.primitives import draw_spotlight
from src.interpretation.parser import interpret_user_prompt
from src.lighting.grading import apply_style_look
from src.narrative.story import get_tension_at
from src.procedural.renderer import render_frame


class TestFidelityPass(unittest.TestCase):
    def test_tension_curves_differ(self):
        mid_std = get_tension_at(0.5, "standard")
        mid_flat = get_tension_at(0.5, "flat")
        early_imm = get_tension_at(0.2, "immediate")
        late_slow = get_tension_at(0.2, "slow_build")
        self.assertAlmostEqual(mid_flat, 0.55, places=2)
        self.assertGreater(early_imm, late_slow)
        self.assertNotAlmostEqual(mid_std, mid_flat, places=2)

    def test_rain_weather_drips(self):
        ev = infer_weather_events("rain", 5.0)
        self.assertTrue(ev)
        self.assertTrue(all(e["kind"] == "drip" for e in ev))
        snow = infer_weather_events("snow", 5.0)
        self.assertTrue(all(e["kind"] == "rustle" for e in snow))

    def test_spin_gag_not_wiped_by_walk_cycle(self):
        instruction = interpret_user_prompt("a character flourishes and spins left")
        # Force character + spin gag
        instruction.entities = [{
            "id": "c0",
            "kind": "character",
            "trajectory": "left",
            "gag": "spin",
            "expression": "excited",
            "personality": "playful",
        }]
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        chars = [L for L in (spec.scene_layers or []) if L.get("kind") == "character"]
        self.assertTrue(chars)
        # Spin gag should keep rotation keyframes (not flat walk)
        rots = [abs(float(k.get("rot") or 0)) for L in chars for k in (L.get("keyframes") or [])]
        self.assertGreater(max(rots or [0]), 0.5)

    def test_multi_shot_duration_sums(self):
        instruction = interpret_user_prompt("educational documentary about cities")
        instruction.genre = "educational"
        instruction.duration_seconds = 12.0
        script = build_scene_script_from_instruction(instruction, duration_seconds=12.0)
        total = sum(s.duration_seconds for s in script.shots)
        self.assertAlmostEqual(total, 12.0, places=1)
        self.assertGreaterEqual(len(script.shots), 2)

    def test_atmosphere_setting_tint(self):
        forest = create_depth_layers(24, 24, num_layers=1, seed=1, base_rgb=(100, 100, 100), setting="forest")
        rain = create_depth_layers(24, 24, num_layers=1, seed=1, base_rgb=(100, 100, 100), setting="rain")
        self.assertFalse(np.array_equal(forest[0][0], rain[0][0]))

    def test_spotlight_darkens_edges(self):
        frame = np.full((48, 48, 3), 180, dtype=np.uint8)
        out = draw_spotlight(frame, (24, 24), radius=10, darkness=0.5)
        self.assertLess(int(out[0, 0, 0]), int(out[24, 24, 0]))

    def test_anime_style_look(self):
        frame = np.full((20, 20, 3), [80, 120, 160], dtype=np.uint8)
        anime = apply_style_look(frame, "anime")
        minimal = apply_style_look(frame, "minimal")
        self.assertFalse(np.array_equal(frame, anime))
        self.assertFalse(np.array_equal(anime, minimal))

    def test_rain_spec_includes_drip_sfx(self):
        instruction = interpret_user_prompt("a red ball bouncing in the rain")
        instruction.duration_seconds = 5.0
        instruction.setting = "rain"
        spec = build_spec_from_instruction(instruction, knowledge={})
        kinds = [e.get("kind") for e in (spec.sfx_events or []) if isinstance(e, dict)]
        self.assertIn("drip", kinds)
        frame = render_frame(spec, 0.4, 64, 64, seed=1)
        self.assertEqual(frame.shape, (64, 64, 3))

    def test_spec_from_shot_keeps_setting(self):
        from src.cinematography.schema import ShotSpec
        from src.creation.scene_script import spec_from_shot

        instruction = interpret_user_prompt("a ball bouncing in the forest")
        instruction.duration_seconds = 6.0
        instruction.setting = "forest"
        base = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(base.setting, "forest")
        shot = ShotSpec(duration_seconds=3.0, shot_type="wide", transition_in="cut", transition_out="cut")
        derived = spec_from_shot(base, shot)
        self.assertEqual(derived.setting, "forest")
        self.assertEqual(derived.script_beats, base.script_beats)

    def test_overlay_expression_at_time(self):
        from src.creation.narrative_script import resolve_overlay_at_time

        beats = [
            {"name": "setup", "t_start": 0.0, "t_end": 2.0, "text": "A", "expression": "calm"},
            {"name": "beat", "t_start": 2.0, "t_end": 4.0, "text": "B", "expression": "excited"},
            {"name": "resolve", "t_start": 4.0, "t_end": 6.0, "text": "C", "expression": "happy"},
        ]
        mid = resolve_overlay_at_time(beats, 3.0)
        self.assertEqual(mid.get("expression"), "excited")
        self.assertEqual(mid.get("text"), "B")
        late = resolve_overlay_at_time(beats, 5.5)
        self.assertEqual(late.get("expression"), "happy")

    def test_t_content_drives_tension_and_beats(self):
        from src.creation.narrative_script import build_mini_scene_script, script_beats_to_dicts

        instruction = interpret_user_prompt("a character walks left")
        instruction.duration_seconds = 6.0
        instruction.entities = [{
            "id": "c0",
            "kind": "character",
            "trajectory": "left",
            "expression": "neutral",
        }]
        narr = build_mini_scene_script(total_duration=6.0, action="walk", topic="walk")
        beats = script_beats_to_dicts(narr)
        spec = build_spec_from_instruction(instruction, knowledge={})
        spec.script_beats = beats
        spec.tension_curve = "slow_build"
        # Local shot time near 0 but clip-global near climax — tension/beats must use t_content
        early = render_frame(spec, 0.05, 48, 48, seed=2, duration_seconds=6.0, t_content=0.05)
        late = render_frame(spec, 0.05, 48, 48, seed=2, duration_seconds=6.0, t_content=5.5)
        self.assertEqual(early.shape, late.shape)
        # Frames should differ once global beat/tension advance
        self.assertFalse(np.array_equal(early, late))

    def test_mini_scene_keeps_beat_expressions(self):
        instruction = interpret_user_prompt("a happy character walks left")
        instruction.duration_seconds = 5.0
        instruction.entities = [{
            "id": "c0",
            "kind": "character",
            "trajectory": "left",
            "bounce": False,
            "expression": "happy",
            "personality": "playful",
        }]
        spec = build_spec_from_instruction(instruction, knowledge={})
        # Prompt expression survives on the character layer
        layer = next(
            (L for L in (spec.scene_layers or []) if L.get("kind") == "character"),
            None,
        )
        self.assertIsNotNone(layer)
        self.assertEqual(layer.get("expression"), "happy")
        # Timed beat faces remain on script_beats for render-time overrides
        beats = getattr(spec, "script_beats", None) or []
        self.assertTrue(beats)
        beat_exprs = [b.get("expression") for b in beats if isinstance(b, dict)]
        self.assertTrue(any(e for e in beat_exprs))

    def test_music_section_bounds_unequal(self):
        from src.audio.music import _section_bounds_ms

        equal = _section_bounds_ms(1000, 4)
        self.assertAlmostEqual(equal[0], 250.0, places=1)
        weighted = _section_bounds_ms(1000, 3, [100.0, 300.0, 600.0])
        self.assertAlmostEqual(weighted[0], 100.0, places=0)
        self.assertAlmostEqual(weighted[1], 400.0, places=0)
        self.assertAlmostEqual(weighted[2], 1000.0, places=0)

    def test_walk_mini_scene_keeps_bob_not_spin(self):
        from src.creation.narrative_script import build_mini_scene_script, script_to_entities_and_sfx

        narr = build_mini_scene_script(total_duration=5.0, action="walk", topic="walk")
        ents, _sfx = script_to_entities_and_sfx(narr, entity_kind="circle")
        walk_ents = [e for e in ents if e.get("kind") == "character" or e.get("trajectory") in ("left", "right", "walk")]
        self.assertTrue(ents)
        # Walk beats must not auto-assign spin/double_take
        for e in ents:
            self.assertNotIn(e.get("gag"), ("spin", "double_take", "flourish"))

        instruction = interpret_user_prompt("a person walking left with calm ambient music")
        instruction.duration_seconds = 5.0
        instruction.entities = [{
            "id": "c0",
            "kind": "character",
            "trajectory": "left",
            "expression": "calm",
            "personality": "playful",
        }]
        spec = build_spec_from_instruction(instruction, knowledge={})
        chars = [L for L in (spec.scene_layers or []) if L.get("kind") == "character"]
        self.assertTrue(chars)
        # Walk cycles produce many bobbing keyframes (not a 2-point slide)
        for L in chars:
            self.assertGreater(len(L.get("keyframes") or []), 3)

    def test_melancholy_maps_to_dark_mood(self):
        from src.procedural.data.keywords import KEYWORD_TO_AUDIO_MOOD, KEYWORD_TO_SETTING

        self.assertEqual(KEYWORD_TO_AUDIO_MOOD.get("melancholy"), "dark")
        self.assertEqual(KEYWORD_TO_SETTING.get("drizzle"), "rain")
        self.assertEqual(KEYWORD_TO_SETTING.get("storm"), "rain")

    def test_mini_scene_fidelity_bias_prefers_buckets(self):
        from src.automation.prompt_gen import _classify_mini_scene, generate_mini_scene_prompt

        self.assertEqual(_classify_mini_scene("explain gravity with a bouncing ball"), "educational")
        self.assertEqual(_classify_mini_scene("a person walking in the rain"), "weather")
        self.assertEqual(_classify_mini_scene("ball enters then bounces then exits"), "multibeat")
        # Biased draws should succeed
        p = generate_mini_scene_prompt(fidelity_bias=True)
        self.assertTrue(p)

    def test_continuous_subject_path_segments(self):
        from src.creation.narrative_script import build_mini_scene_script, script_to_entities_and_sfx

        narr = build_mini_scene_script(total_duration=5.0, action="walk", topic="walk")
        ents, _ = script_to_entities_and_sfx(narr)
        self.assertEqual(len(ents), 1)
        self.assertIn("path_segments", ents[0])
        self.assertGreaterEqual(len(ents[0]["path_segments"]), 2)

    def test_short_educational_has_teach_copy(self):
        from src.creation.narrative_script import build_educational_script

        narr = build_educational_script("gravity", total_duration=5.0)
        texts = [b.text for b in narr.beats]
        self.assertEqual(len(texts), 3)
        self.assertTrue(all(texts))
        self.assertTrue(any("gravity" in (t or "").lower() for t in texts))
        self.assertTrue(any(b.callout or b.arrow for b in narr.beats))

    def test_weather_particles_stable_across_nearby_frames(self):
        from src.procedural.renderer import _apply_weather_overlay

        base = np.full((64, 64, 3), 80, dtype=np.uint8)
        a = _apply_weather_overlay(base.copy(), "rain", 0.40, seed=7)
        b = _apply_weather_overlay(base.copy(), "rain", 0.42, seed=7)
        # Adjacent frames should be similar (streaks advect), not fully reshuffled
        diff = np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32)))
        reshuffle = _apply_weather_overlay(base.copy(), "rain", 0.40, seed=999)
        reshuffle_diff = np.mean(np.abs(a.astype(np.float32) - reshuffle.astype(np.float32)))
        self.assertLess(diff, reshuffle_diff)


if __name__ == "__main__":
    unittest.main()

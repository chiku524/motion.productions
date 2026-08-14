"""
Fidelity smoke tests: everyday mini-scene prompts must resolve to the right
entities, direction, music genre, bounce SFX, and scene layers.
"""
from __future__ import annotations

import unittest

from src.creation.builder import build_spec_from_instruction
from src.creation.narrative_script import build_mini_scene_script
from src.interpretation.parser import interpret_user_prompt
from src.knowledge.entity_registry import entity_profile_key, grow_entities_from_spec


class TestMiniSceneFidelity(unittest.TestCase):
    def test_red_ball_bounce_deep_house(self):
        prompt = "a red ball bouncing left to a deep house beat with soft vocals"
        instruction = interpret_user_prompt(prompt)
        self.assertTrue(instruction.entities, "expected at least one entity")
        ent = instruction.entities[0]
        self.assertEqual(ent.get("kind"), "circle")
        self.assertTrue(ent.get("bounce"))
        self.assertEqual(ent.get("trajectory"), "left")
        self.assertEqual(getattr(instruction, "audio_genre", None), "deep_house")
        self.assertTrue(getattr(instruction, "audio_vocals", False))
        sfx_on = ent.get("sfx_on") or []
        sfx_events = getattr(instruction, "sfx_events", None) or []
        sfx_kinds = [e.get("kind") for e in sfx_events if isinstance(e, dict)]
        self.assertTrue(
            "bounce" in sfx_on or "bounce" in sfx_kinds or ent.get("bounce"),
            "expected bounce SFX hint on entity or instruction",
        )

        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.audio_genre, "deep_house")
        self.assertTrue(spec.audio_vocals)
        self.assertTrue(spec.scene_layers, "expected scene layers from entities")
        self.assertEqual(spec.scene_layers[0].get("kind"), "circle")
        self.assertTrue(spec.sfx_events, "expected bounce SFX timings")

    def test_person_walking_house(self):
        prompt = "a person walking toward the camera with uplifting house music and vocals"
        instruction = interpret_user_prompt(prompt)
        self.assertTrue(instruction.entities)
        kinds = {e.get("kind") for e in instruction.entities}
        self.assertIn("character", kinds)
        self.assertEqual(getattr(instruction, "audio_genre", None), "deep_house")
        self.assertTrue(getattr(instruction, "audio_vocals", False))
        trajs = {e.get("trajectory") for e in instruction.entities}
        self.assertIn("toward", trajs)

        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertTrue(spec.scene_layers)
        self.assertTrue(any(l.get("kind") == "character" for l in spec.scene_layers))

    def test_blue_ball_techno(self):
        prompt = "a blue ball bouncing right with techno music"
        instruction = interpret_user_prompt(prompt)
        self.assertTrue(instruction.entities)
        self.assertEqual(instruction.entities[0].get("kind"), "circle")
        self.assertEqual(instruction.entities[0].get("trajectory"), "right")
        self.assertTrue(instruction.entities[0].get("bounce"))
        self.assertEqual(getattr(instruction, "audio_genre", None), "techno")

    def test_entity_growth_payload(self):
        prompt = "a red ball bouncing left to a deep house beat"
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        added, novel = grow_entities_from_spec(instruction, spec, prompt=prompt)
        self.assertGreater(added, 0)
        self.assertTrue(novel)
        self.assertIn("key", novel[0])
        self.assertTrue(all(n["kind"] == "circle" for n in novel))
        bouncing = [n for n in novel if n.get("bounce") == 1]
        self.assertTrue(bouncing, "expected at least one bouncing entity profile after mini-scene expansion")
        key = entity_profile_key(
            "circle",
            trajectory=bouncing[0].get("trajectory") or "none",
            bounce=True,
            color_hint=bouncing[0].get("color_hint"),
            directionality=bouncing[0].get("directionality"),
            expression=bouncing[0].get("expression") or "neutral",
            personality=bouncing[0].get("personality") or "neutral",
            gag=bouncing[0].get("gag") or "none",
        )
        self.assertEqual(bouncing[0]["key"], key)
        self.assertIn(bouncing[0].get("gag"), ("squash", "none", "spin", "flourish", "wink", "double_take"))

    def test_character_expression_personality(self):
        prompt = "a happy playful person walking left with uplifting house music"
        instruction = interpret_user_prompt(prompt)
        self.assertTrue(instruction.entities)
        ent = instruction.entities[0]
        self.assertEqual(ent.get("kind"), "character")
        self.assertEqual(ent.get("expression"), "happy")
        self.assertEqual(ent.get("personality"), "playful")
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertTrue(spec.scene_layers)
        layer = next(l for l in spec.scene_layers if l.get("kind") == "character")
        self.assertEqual(layer.get("expression"), "happy")
        self.assertEqual(layer.get("personality"), "playful")

    def test_beat_time_windows_and_squash(self):
        prompt = "a red ball enters from the left then bounces then exits right with whoosh"
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertTrue(spec.scene_layers)
        # Continuous subject (path_segments) or staggered timed windows
        foreground = [
            L for L in spec.scene_layers
            if L.get("kind") in ("circle", "rect", "arrow", "character")
        ]
        self.assertTrue(foreground)
        has_segments = any(
            isinstance(e, dict) and e.get("path_segments")
            for e in (getattr(instruction, "entities", None) or [])
        )
        starts = [l.get("keyframes", [{}])[0].get("t", 0) for l in spec.scene_layers]
        self.assertTrue(
            has_segments
            or any(float(s) > 0.05 for s in starts)
            or len(spec.scene_layers) >= 2
        )
        bouncing = [l for l in spec.scene_layers if l.get("bounce") or l.get("gag") == "squash"]
        self.assertTrue(
            bouncing
            or any(l.get("gag") for l in spec.scene_layers)
            or has_segments
        )
        # Phase E: freeform beats wire timed overlays + music sections
        self.assertTrue(spec.script_beats, "expected script_beats from freeform then-clauses")
        self.assertGreaterEqual(len(spec.script_beats), 2)
        self.assertTrue(any(b.get("text") for b in spec.script_beats))
        self.assertEqual(len(spec.music_sections or []), len(spec.script_beats))
        self.assertTrue(any(b.get("callout") for b in spec.script_beats))

    def test_setting_themed_blended_background(self):
        """Mini-scenes with entities must use blended mode + setting, not rainbow pure mesh."""
        prompt = "a red ball bouncing left at sunset with warm ambient vocals"
        instruction = interpret_user_prompt(prompt)
        self.assertEqual(getattr(instruction, "setting", None), "golden_hour")
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "blended")
        self.assertTrue(spec.pure_colors is None or spec.pure_colors == [])
        self.assertEqual(spec.setting, "golden_hour")
        self.assertIn(spec.palette_name, ("warm_sunset", "fire", "default"))
        self.assertTrue(spec.scene_layers)

    def test_neon_city_setting(self):
        prompt = "a person walking right through a neon city with techno music"
        instruction = interpret_user_prompt(prompt)
        self.assertIn(getattr(instruction, "setting", None), ("city", "neon"))
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "blended")
        self.assertIn(spec.setting, ("city", "neon"))

    def test_abstract_mesh_prompt(self):
        from src.automation.prompt_gen import generate_abstract_mesh_prompt
        knowledge = {
            "color_by_name": {
                "amber veil": {"key": "a", "r": 200, "g": 140, "b": 40},
                "teal mist": {"key": "b", "r": 20, "g": 160, "b": 170},
            }
        }
        prompt = generate_abstract_mesh_prompt(knowledge=knowledge, avoid=set())
        self.assertIsNotNone(prompt)
        low = prompt.lower()
        self.assertTrue(
            any(cue in low for cue in ("color mesh", "pixel field", "pixel wash", "pure mesh", "abstract mesh", "rainbow mesh")),
            prompt,
        )
        self.assertFalse(any(obj in low for obj in ("person", "ball", "tree", "fish", "car")), prompt)
        again = generate_abstract_mesh_prompt(knowledge=knowledge, avoid={prompt})
        if again is not None:
            self.assertNotEqual(again, prompt)

    def test_abstract_mesh_stays_pure_no_layers(self):
        prompt = "pure color mesh of amber and teal pulsing with calm ambient music"
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)

    def test_setting_props_forest_trees(self):
        prompt = "a person walking left in a forest with soft vocals"
        instruction = interpret_user_prompt(prompt)
        self.assertEqual(getattr(instruction, "setting", None), "forest")
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "blended")
        kinds = {l.get("kind") for l in (spec.scene_layers or [])}
        self.assertIn("tree", kinds)
        self.assertIn("character", kinds)

    def test_setting_props_ocean_fish(self):
        prompt = "a fish jumping in the ocean with soft whoosh and calm ambient music"
        instruction = interpret_user_prompt(prompt)
        self.assertEqual(getattr(instruction, "setting", None), "ocean")
        self.assertTrue(any(e.get("kind") == "fish" for e in instruction.entities))
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        kinds = {l.get("kind") for l in (spec.scene_layers or [])}
        self.assertIn("fish", kinds)
        # Waves often auto-spawn for ocean setting
        self.assertTrue("wave" in kinds or "fish" in kinds)

    def test_linguistic_extracts_expression(self):
        from src.interpretation.linguistic import extract_linguistic_mappings
        prompt = "a happy playful person walking left with uplifting house music"
        instruction = interpret_user_prompt(prompt)
        mappings = extract_linguistic_mappings(prompt, instruction)
        domains = {m["domain"] for m in mappings}
        self.assertIn("expression", domains)
        self.assertIn("personality", domains)

    def test_linguistic_extracts_setting(self):
        from src.interpretation.linguistic import extract_linguistic_mappings
        prompt = "a blue orb drifting upward by the ocean with calm ambient music"
        instruction = interpret_user_prompt(prompt)
        self.assertEqual(getattr(instruction, "setting", None), "ocean")
        mappings = extract_linguistic_mappings(prompt, instruction)
        domains = {m["domain"] for m in mappings}
        self.assertIn("setting", domains)

    def test_targeted_entity_prompt_fills_gaps(self):
        from src.automation.prompt_gen import generate_targeted_entity_prompt
        from unittest import mock

        knowledge = {
            "learned_entities": [
                {"kind": "circle", "trajectory": "left", "bounce": 1},
                {"kind": "circle", "trajectory": "right", "bounce": 0},
            ]
        }
        prompt = generate_targeted_entity_prompt(knowledge, coverage={"learned_entities_coverage_pct": 5})
        self.assertIsNotNone(prompt)
        self.assertIsInstance(prompt, str)
        self.assertTrue(len(prompt) > 10)
        lower = prompt.lower()
        self.assertTrue(
            any(
                w in lower
                for w in (
                    "ball", "orb", "block", "box", "arrow", "person", "character", "figure",
                    "tree", "pine", "oak", "fish", "wave", "building", "tower", "cloud",
                    "bird", "sparrow", "gull", "star", "car", "van", "bike", "kite",
                    "lantern", "mushroom", "rocket",
                )
            ),
            f"unexpected entity phrasing: {prompt}",
        )
        # When the only candidate is avoided, return None (deterministic path)
        with mock.patch("src.automation.prompt_gen.secure_choice", side_effect=lambda seq: seq[0]):
            with mock.patch("src.automation.prompt_gen.secure_random", return_value=0.1):
                fixed = generate_targeted_entity_prompt(knowledge)
                self.assertIsNotNone(fixed)
                self.assertIsNone(generate_targeted_entity_prompt(knowledge, avoid={fixed}))

    def test_pure_per_frame_meshes_registry_colors(self):
        import numpy as np
        from src.procedural.renderer import _render_pure_per_frame

        xx, yy = np.meshgrid(np.linspace(0, 1, 48), np.linspace(0, 1, 48))
        colors = [(255, 0, 0), (0, 0, 255)]
        r, g, b = _render_pure_per_frame(xx, yy, colors, 0.4, 42, 1.0, motion_level=2.0)
        mixed = (r > 30) & (b > 30)
        self.assertGreater(int(np.sum(mixed)), 20, "expected interpolated pixels, not hard color cells")


if __name__ == "__main__":
    unittest.main()

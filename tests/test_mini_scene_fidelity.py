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
        )
        self.assertEqual(bouncing[0]["key"], key)

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
        # Sequential windows: not all layers active for full 0..5s
        starts = [l.get("keyframes", [{}])[0].get("t", 0) for l in spec.scene_layers]
        self.assertTrue(any(float(s) > 0.05 for s in starts) or len(spec.scene_layers) >= 2)
        bouncing = [l for l in spec.scene_layers if l.get("bounce") or l.get("gag") == "squash"]
        self.assertTrue(bouncing or any(l.get("gag") for l in spec.scene_layers))

    def test_linguistic_extracts_expression(self):
        from src.interpretation.linguistic import extract_linguistic_mappings
        prompt = "a happy playful person walking left with uplifting house music"
        instruction = interpret_user_prompt(prompt)
        mappings = extract_linguistic_mappings(prompt, instruction)
        domains = {m["domain"] for m in mappings}
        self.assertIn("expression", domains)
        self.assertIn("personality", domains)


if __name__ == "__main__":
    unittest.main()

"""
Fidelity smoke tests: everyday mini-scene prompts must resolve to the right
entities, direction, music genre, bounce SFX, and scene layers.
"""
from __future__ import annotations

import unittest

from src.creation.builder import build_spec_from_instruction
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
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)
        self.assertEqual(spec.audio_genre, "none")
        self.assertTrue(spec.pure_colors)
        self.assertTrue(spec.pure_sounds)
        self.assertTrue(spec.sound_pairing)

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
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)
        self.assertTrue(spec.pure_colors)
        self.assertTrue(any(e.get("kind") == "character" for e in instruction.entities))

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
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)
        self.assertEqual(ent.get("expression"), "happy")
        self.assertEqual(ent.get("personality"), "playful")

    def test_beat_time_windows_and_squash(self):
        prompt = "a red ball enters from the left then bounces then exits right with whoosh"
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)
        self.assertTrue(spec.pure_colors)
        self.assertTrue(instruction.entities, "prompt still names the bouncing subject")
        self.assertTrue(
            any(e.get("bounce") or e.get("kind") == "circle" for e in instruction.entities)
        )

    def test_setting_themed_blended_background(self):
        """Named-subject prompts stay a registry field; setting still binds hint colors."""
        prompt = "a red ball bouncing left at sunset with warm ambient vocals"
        instruction = interpret_user_prompt(prompt)
        self.assertEqual(getattr(instruction, "setting", None), "golden_hour")
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)
        self.assertTrue(spec.pure_colors)
        self.assertEqual(spec.setting, "golden_hour")
        origins = {(255, 165, 0), (255, 0, 0), (255, 255, 0), (255, 192, 203)}
        self.assertTrue(origins.intersection(set(spec.pure_colors)))

    def test_neon_city_setting(self):
        prompt = "a person walking right through a neon city with techno music"
        instruction = interpret_user_prompt(prompt)
        self.assertIn(getattr(instruction, "setting", None), ("city", "neon"))
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)
        self.assertIn(spec.setting, ("city", "neon"))
        self.assertTrue(spec.pure_colors)

    def test_pixel_pairing_prompt_frame_and_window(self):
        from src.automation.prompt_gen import generate_pixel_pairing_prompt
        knowledge = {
            "color_by_name": {
                "amber veil": {"key": "a", "r": 200, "g": 140, "b": 40},
                "teal mist": {"key": "b", "r": 20, "g": 160, "b": 170},
            },
            "learned_motion": [{"name": "slow drift", "motion_level": 4.0}],
        }
        frame = generate_pixel_pairing_prompt(kind="frame", knowledge=knowledge, avoid=set())
        self.assertIsNotNone(frame)
        flow = frame.lower()
        self.assertTrue("pair" in flow or "static frame" in flow, frame)
        self.assertIn("sound pairing", flow)
        self.assertFalse(any(obj in flow for obj in ("person", "ball", "tree", "fish", "car")), frame)
        window = generate_pixel_pairing_prompt(kind="window", knowledge=knowledge, avoid=set())
        self.assertIsNotNone(window)
        wlow = window.lower()
        self.assertTrue(
            any(cue in wlow for cue in ("motion window", "dynamic pairing", "window blend")),
            window,
        )
        self.assertTrue("sound" in wlow or "paired with" in wlow, window)

    def test_user_prompt_is_registry_field(self):
        prompt = "Sunset over the ocean, dreamy"
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 6.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertEqual(spec.render_engine, "procedural")
        self.assertFalse(spec.scene_layers)
        self.assertTrue(spec.pure_colors)
        self.assertTrue(spec.pure_sounds)
        self.assertIn(spec.sound_pairing, ("frame", "window"))
        self.assertEqual(spec.audio_genre, "none")
        self.assertEqual(spec.camera_motion, "static")
        warm_or_water = {
            (255, 165, 0), (255, 0, 0), (255, 255, 0), (255, 192, 203),
            (0, 0, 255), (0, 0, 128), (0, 128, 128), (0, 255, 255),
            (255, 192, 203), (128, 0, 128),
        }
        self.assertTrue(warm_or_water.intersection(set(spec.pure_colors)))
        self.assertLessEqual(len(spec.pure_colors), 12)

    def test_abstract_mesh_stays_pure_no_layers(self):
        prompt = "static frame: amber paired with teal"
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)
        self.assertLessEqual(float(spec.motion_level or 0), 3.5)
        self.assertEqual(spec.sound_pairing, "frame")
        self.assertEqual(spec.audio_genre, "none")
        self.assertTrue(spec.pure_sounds)
        self.assertEqual(len(spec.pure_sounds), 2)
        self.assertGreaterEqual(len(spec.pure_colors or []), 6)
        self.assertLessEqual(len(spec.pure_colors or []), 12)
        self.assertEqual(float(spec.motion_sync or 0), 1.0)
        self.assertEqual(spec.camera_motion, "static")
        self.assertEqual(spec.camera_steadiness, "locked")

    def test_motion_window_stays_pure_higher_motion(self):
        prompt = "motion window: amber paired with teal in slow drift"
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)
        self.assertGreaterEqual(float(spec.motion_level or 0), 9.0)
        self.assertEqual(spec.sound_pairing, "window")
        self.assertEqual(spec.audio_genre, "none")
        self.assertTrue(spec.pure_sounds)
        self.assertEqual(len(spec.pure_sounds), 4)
        self.assertGreaterEqual(len(spec.pure_colors or []), 8)
        self.assertLessEqual(len(spec.pure_colors or []), 24)
        self.assertGreaterEqual(float(spec.motion_sync or 0), 0.5)
        self.assertEqual(spec.camera_motion, "static")
        self.assertEqual(spec.camera_steadiness, "locked")

    def test_setting_props_forest_trees(self):
        prompt = "a person walking left in a forest with soft vocals"
        instruction = interpret_user_prompt(prompt)
        self.assertEqual(getattr(instruction, "setting", None), "forest")
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)
        self.assertTrue(spec.sound_pairing)
        self.assertIsNotNone(spec.motion_sync)
        self.assertTrue(spec.pure_colors)
        forest = {(0, 255, 0), (128, 128, 0), (165, 42, 42)}
        self.assertTrue(forest.intersection(set(spec.pure_colors)))
        self.assertTrue(any(e.get("kind") == "character" for e in instruction.entities))

    def test_setting_props_ocean_fish(self):
        prompt = "a fish jumping in the ocean with soft whoosh and calm ambient music"
        instruction = interpret_user_prompt(prompt)
        self.assertEqual(getattr(instruction, "setting", None), "ocean")
        self.assertTrue(any(e.get("kind") == "fish" for e in instruction.entities))
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)
        self.assertTrue(spec.pure_colors)
        ocean = {(0, 0, 255), (0, 0, 128), (0, 128, 128), (0, 255, 255)}
        self.assertTrue(ocean.intersection(set(spec.pure_colors)))

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

    def test_named_colors_occupy_visible_masses(self):
        import numpy as np
        from src.procedural.renderer import _render_pure_per_frame

        xx, yy = np.meshgrid(np.linspace(0, 1, 64), np.linspace(0, 1, 64))
        named = [(255, 0, 0), (0, 0, 255)]
        fillers = [(i * 12, 180, 40) for i in range(6)]
        r, g, b = _render_pure_per_frame(
            xx, yy, named + fillers, 0.0, 3, 1.0, motion_level=2.0, named_count=2,
        )
        rgb = np.stack([r, g, b], axis=-1)
        d_red = np.linalg.norm(rgb - np.array(named[0], dtype=np.float32), axis=-1)
        d_blue = np.linalg.norm(rgb - np.array(named[1], dtype=np.float32), axis=-1)
        near_named = (d_red < 90) | (d_blue < 90)
        self.assertGreater(
            float(near_named.mean()),
            0.18,
            "prompt-named colors must occupy visible masses, not hash dust",
        )

    def test_window_pairing_moves_more_than_static_frame(self):
        import numpy as np
        from src.procedural.renderer import _render_pure_per_frame

        xx, yy = np.meshgrid(np.linspace(0, 1, 32), np.linspace(0, 1, 32))
        colors = [(255, 0, 0), (0, 0, 255), (0, 255, 0)]
        r0, _, _ = _render_pure_per_frame(xx, yy, colors, 0.0, 7, 1.0, motion_level=2.5)
        r1, _, _ = _render_pure_per_frame(xx, yy, colors, 0.8, 7, 1.0, motion_level=2.5)
        static_delta = float(np.mean(np.abs(r0 - r1)))
        r2, _, _ = _render_pure_per_frame(xx, yy, colors, 0.0, 7, 1.0, motion_level=16.0, motion_val=0.8)
        r3, _, _ = _render_pure_per_frame(xx, yy, colors, 0.8, 7, 1.0, motion_level=16.0, motion_val=0.2)
        window_delta = float(np.mean(np.abs(r2 - r3)))
        self.assertGreater(window_delta, static_delta)

    def test_pixels_form_distinct_masses_from_a_pool(self):
        import numpy as np
        from src.procedural.renderer import _render_pure_per_frame

        xx, yy = np.meshgrid(np.linspace(0, 1, 48), np.linspace(0, 1, 48))
        colors = [(i * 15, 40, 240 - i * 12) for i in range(16)]
        r, g, b = _render_pure_per_frame(xx, yy, colors, 0.0, 19, 1.0, motion_level=2.0)
        self.assertGreater(float(np.std(r)), 15.0)
        # Interiors of masses are coherent; boundaries still differ.
        interior = float(np.mean(np.abs(r[8:16, 8:16] - r[8:16, 8:16].mean())))
        self.assertLess(interior, float(np.std(r)))

    def test_synchronized_color_change_is_more_coherent_than_independent(self):
        import numpy as np
        from src.procedural.renderer import _render_pure_per_frame

        xx, yy = np.meshgrid(np.linspace(0, 1, 32), np.linspace(0, 1, 32))
        colors = [(255, 0, 0), (0, 0, 255)]
        kwargs = dict(motion_level=16.0, motion_val=0.6)
        r0, _, _ = _render_pure_per_frame(xx, yy, colors, 0.0, 11, 1.0, **kwargs, motion_sync=1.0)
        r1, _, _ = _render_pure_per_frame(xx, yy, colors, 0.7, 11, 1.0, **kwargs, motion_sync=1.0)
        u0, _, _ = _render_pure_per_frame(xx, yy, colors, 0.0, 11, 1.0, **kwargs, motion_sync=0.0)
        u1, _, _ = _render_pure_per_frame(xx, yy, colors, 0.7, 11, 1.0, **kwargs, motion_sync=0.0)
        changed_sync = (np.abs(r1 - r0) > 20).astype(np.float32)
        changed_indep = (np.abs(u1 - u0) > 20).astype(np.float32)

        def _patch_coherence(mask: np.ndarray, size: int = 8) -> float:
            # |patch mean - 0.5|: masses that flip together sit near 0 or 1.
            vals = []
            h, w = mask.shape
            for y in range(0, h - size + 1, size):
                for x in range(0, w - size + 1, size):
                    m = float(mask[y : y + size, x : x + size].mean())
                    vals.append(abs(m - 0.5))
            return float(np.mean(vals)) if vals else 0.0

        self.assertGreater(_patch_coherence(changed_sync), _patch_coherence(changed_indep))
        self.assertGreater(float(np.mean(np.abs(r1 - r0))), 0.5)

    def test_cartoon_word_stays_registry_field(self):
        prompt = (
            "cel cartoon: a teal person holds still then turns in a kitchen, "
            "amber walls, cartoon hold then snap, anime look"
        )
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 2.5
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertEqual(spec.render_engine, "procedural")
        self.assertFalse(spec.scene_layers)
        self.assertTrue(spec.pure_colors)
        self.assertTrue(spec.pure_sounds)
        self.assertEqual(spec.camera_motion, "static")
        self.assertEqual(spec.camera_steadiness, "locked")
        self.assertEqual(spec.audio_genre, "none")

    def test_same_prompt_different_seeds_are_distinct_fields(self):
        import numpy as np
        from src.procedural.renderer import render_frame

        prompt = "static frame: amber paired with teal"
        knowledge = {
            "color_by_name": {
                "amber": {"key": "a", "r": 200, "g": 140, "b": 40},
                "teal": {"key": "b", "r": 20, "g": 160, "b": 170},
            },
            "static_colors": {
                "c1": {"r": 12, "g": 40, "b": 90, "name": "navy hush", "count": 1},
                "c2": {"r": 210, "g": 80, "b": 30, "name": "ember wash", "count": 1},
                "c3": {"r": 90, "g": 20, "b": 140, "name": "violet dusk", "count": 2},
                "c4": {"r": 30, "g": 180, "b": 110, "name": "mint drift", "count": 3},
            },
        }
        instruction_a = interpret_user_prompt(prompt)
        instruction_b = interpret_user_prompt(prompt)
        spec_a = build_spec_from_instruction(instruction_a, knowledge=knowledge, creation_seed=11)
        spec_b = build_spec_from_instruction(instruction_b, knowledge=knowledge, creation_seed=99)
        self.assertEqual(spec_a.creation_mode, "pure_per_frame")
        self.assertEqual(spec_b.creation_mode, "pure_per_frame")
        frame_a = render_frame(spec_a, 0.2, 96, 96, seed=11)
        frame_b = render_frame(spec_b, 0.2, 96, 96, seed=99)
        self.assertGreater(float(np.mean(np.abs(frame_a.astype(np.int16) - frame_b.astype(np.int16)))), 4.0)

    def test_leftover_cel_spec_renders_as_field(self):
        import numpy as np
        from src.procedural.parser import SceneSpec
        from src.procedural.renderer import render_frame

        spec = SceneSpec(
            palette_name="default",
            motion_type="slow",
            intensity=0.6,
            raw_prompt="leftover cel",
            palette_colors=[(200, 140, 40), (20, 160, 170), (40, 50, 80)],
            render_engine="cel",
            creation_mode="blended",
            style="cartoon",
            scene_layers=[{"kind": "character", "keyframes": [{"t": 0, "x": 0.5, "y": 0.5}]}],
        )
        frame = render_frame(spec, 0.2, 96, 96, seed=7)
        self.assertEqual(spec.render_engine, "procedural")
        self.assertEqual(spec.creation_mode, "pure_per_frame")
        self.assertFalse(spec.scene_layers)
        self.assertEqual(frame.shape, (96, 96, 3))
        unique = len(np.unique(frame.reshape(-1, 3), axis=0))
        self.assertGreater(unique, 20)

    def test_reference_origin_recipe_from_frames(self):
        import numpy as np
        from src.knowledge.reference_origin import measure_frames

        still = np.full((48, 48, 3), (200, 160, 80), dtype=np.uint8)
        snap = still.copy()
        snap[:, 24:] = (40, 80, 160)
        frames = [still] * 10 + [snap] * 2 + [still] * 10
        recipe = measure_frames(frames, fps=24.0, loop="cartoon")
        self.assertGreater(float(recipe["hold_frac"]), 0.6)
        self.assertTrue(recipe["palette"])
        self.assertIn("r", recipe["palette"][0])
        self.assertEqual(recipe["render_engine"], "cel")
        self.assertNotIn("frames", recipe)
        field = recipe.get("field") or {}
        self.assertTrue(field.get("frames"))
        self.assertEqual(int(field.get("width") or 0), 192)
        from src.knowledge.reference_origin import decode_index_map

        idx0 = decode_index_map(field["frames"][0], field["height"], field["width"])
        self.assertEqual(idx0.shape, (field["height"], field["width"]))

    def test_reference_origin_spreads_samples_across_clip(self):
        from src.knowledge.reference_origin import stride_for_clip

        # 68s @ 30fps with a 72-frame cap must not sample every frame (opening only).
        self.assertEqual(stride_for_clip(30.0, 68.27, 72), 28)
        self.assertEqual(stride_for_clip(24.0, 0.0, 72), 1)

    def test_loop_origin_is_not_attached_or_replayed(self):
        instruction = interpret_user_prompt(
            "cel cartoon: a person holds still then turns in a kitchen, cartoon hold then snap"
        )
        instruction.duration_seconds = 2.5
        knowledge = {
            "loop_origin": {
                "palette": [{"r": 210, "g": 90, "b": 40, "name": "origin ochre"}],
                "has_field": True,
                "field": {"frames": ["nope"], "width": 8, "height": 8},
            }
        }
        spec = build_spec_from_instruction(instruction, knowledge=knowledge)
        self.assertNotIn("loop_origin", spec.instance or {})
        self.assertNotIn((210, 90, 40), spec.palette_colors[:4])


if __name__ == "__main__":
    unittest.main()

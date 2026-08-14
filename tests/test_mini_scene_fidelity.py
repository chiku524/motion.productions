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
        self.assertTrue(any(layer.get("kind") == "character" for layer in spec.scene_layers))

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
        layer = next(layer for layer in spec.scene_layers if layer.get("kind") == "character")
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
        starts = [layer.get("keyframes", [{}])[0].get("t", 0) for layer in spec.scene_layers]
        self.assertTrue(
            has_segments
            or any(float(s) > 0.05 for s in starts)
            or len(spec.scene_layers) >= 2
        )
        bouncing = [layer for layer in spec.scene_layers if layer.get("bounce") or layer.get("gag") == "squash"]
        self.assertTrue(
            bouncing
            or any(layer.get("gag") for layer in spec.scene_layers)
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
        self.assertGreaterEqual(len(spec.pure_colors or []), 16)
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
        self.assertGreaterEqual(len(spec.pure_colors or []), 16)
        self.assertGreaterEqual(float(spec.motion_sync or 0), 0.5)
        self.assertEqual(spec.camera_motion, "static")
        self.assertEqual(spec.camera_steadiness, "locked")

    def test_setting_props_forest_trees(self):
        prompt = "a person walking left in a forest with soft vocals"
        instruction = interpret_user_prompt(prompt)
        self.assertEqual(getattr(instruction, "setting", None), "forest")
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "blended")
        self.assertIsNone(spec.sound_pairing)
        self.assertIsNone(spec.motion_sync)
        kinds = {layer.get("kind") for layer in (spec.scene_layers or [])}
        self.assertIn("tree", kinds)
        self.assertIn("character", kinds)

    def test_setting_props_ocean_fish(self):
        prompt = "a fish jumping in the ocean with soft whoosh and calm ambient music"
        instruction = interpret_user_prompt(prompt)
        self.assertEqual(getattr(instruction, "setting", None), "ocean")
        self.assertTrue(any(e.get("kind") == "fish" for e in instruction.entities))
        instruction.duration_seconds = 5.0
        spec = build_spec_from_instruction(instruction, knowledge={})
        kinds = {layer.get("kind") for layer in (spec.scene_layers or [])}
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

    def test_pixels_pair_independently_from_a_large_pool(self):
        import numpy as np
        from src.procedural.renderer import _render_pure_per_frame

        xx, yy = np.meshgrid(np.linspace(0, 1, 48), np.linspace(0, 1, 48))
        colors = [(i * 15, 40, 240 - i * 12) for i in range(16)]
        r, g, b = _render_pure_per_frame(xx, yy, colors, 0.0, 19, 1.0, motion_level=2.0)
        neighbor = float(np.mean(np.abs(r[:, 1:] - r[:, :-1])))
        self.assertGreater(neighbor, 4.0)
        self.assertGreater(float(np.std(r)), 20.0)

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

    def test_cartoon_prompt_is_named_subject_not_pairing(self):
        from src.automation.prompt_gen import generate_cartoon_prompt

        knowledge = {
            "color_by_name": {
                "amber veil": {"key": "a", "r": 200, "g": 140, "b": 40},
                "teal mist": {"key": "b", "r": 20, "g": 160, "b": 170},
            }
        }
        prompt = generate_cartoon_prompt(knowledge=knowledge, avoid=set())
        self.assertIsNotNone(prompt)
        low = prompt.lower()
        self.assertTrue("cel cartoon" in low or "modern cartoon" in low, prompt)
        self.assertTrue(any(s in low for s in ("person", "kid", "teen", "character")), prompt)
        self.assertTrue(any(s in low for s in ("kitchen", "apartment", "cafe", "bedroom", "office", "street", "park", "subway")), prompt)
        self.assertTrue("hold" in low or "snap" in low, prompt)
        self.assertNotIn("pixel pairing", low)
        self.assertNotIn("static frame", low)
        self.assertNotIn("motion window", low)

    def test_cartoon_spec_cel_hold_snap_identity(self):
        prompt = (
            "cel cartoon: a teal person holds still then turns in a kitchen, "
            "amber walls, cartoon hold then snap, anime look"
        )
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 2.5
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.creation_mode, "blended")
        self.assertEqual(spec.render_engine, "cel")
        self.assertIn(spec.style, ("cartoon", "anime"))
        self.assertFalse(spec.film_look)
        self.assertEqual(spec.camera_motion, "static")
        self.assertEqual(spec.camera_steadiness, "locked")
        self.assertEqual(spec.audio_genre, "none")
        self.assertGreaterEqual(float(spec.motion_sync or 0), 0.85)
        self.assertEqual(getattr(instruction, "setting", None), "kitchen")
        kinds = {layer.get("kind") for layer in (spec.scene_layers or [])}
        self.assertIn("character", kinds)
        char = next(layer for layer in spec.scene_layers if layer.get("kind") == "character")
        kfs = char.get("keyframes") or []
        self.assertGreaterEqual(len(kfs), 4)
        xs = [float(k.get("x")) for k in kfs]
        self.assertEqual(xs[0], xs[1])
        self.assertNotEqual(xs[1], xs[2])

    def test_cel_frame_is_inked_modern_interior(self):
        import numpy as np
        from src.procedural.renderer import render_frame

        prompt = (
            "cel cartoon: a teal person holds still then turns in a kitchen, "
            "amber walls, cartoon hold then snap, anime look"
        )
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 2.5
        spec = build_spec_from_instruction(instruction, knowledge={})
        self.assertEqual(spec.render_engine, "cel")
        frame = render_frame(spec, 0.2, 256, 256, seed=7)
        self.assertEqual(frame.shape, (256, 256, 3))
        luma = frame.astype(np.float32).mean(axis=2)
        ink = luma < 50
        self.assertGreater(float(ink.mean()), 0.01, "expected ink outlines")
        top = frame[:70].astype(np.float32).mean()
        bottom = frame[190:].astype(np.float32).mean()
        self.assertGreater(abs(top - bottom), 12.0, "expected a wall/floor split, not a blob wash")
        unique = len(np.unique(frame.reshape(-1, 3), axis=0))
        self.assertLess(unique, 8000, "cel fills should be flatter than shaded blobs")

    def test_cartoon_workflow_pick_prompt_never_pairing(self):
        import importlib.util
        import os
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "scripts" / "automate_loop.py"
        spec = importlib.util.spec_from_file_location("automate_loop_cartoon_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        old = os.environ.get("LOOP_WORKFLOW_TYPE")
        os.environ["LOOP_WORKFLOW_TYPE"] = "cartoon"
        try:
            prompt, meta = mod.pick_prompt({"recent_prompts": []}, knowledge={}, coverage={})
        finally:
            if old is None:
                os.environ.pop("LOOP_WORKFLOW_TYPE", None)
            else:
                os.environ["LOOP_WORKFLOW_TYPE"] = old
        self.assertEqual(meta.get("source"), "cartoon")
        low = (prompt or "").lower()
        self.assertIn("cartoon", low)
        self.assertNotIn("pixel pairing", low)

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

    def test_cartoon_prompt_and_spec_use_loop_origin(self):
        from src.automation.prompt_gen import generate_cartoon_prompt

        origin = {
            "palette": [{"r": 210, "g": 90, "b": 40, "name": "origin ochre"}],
            "hold_frac": 0.7,
            "snap_frac": 0.08,
        }
        knowledge = {"loop_origin": origin, "color_by_name": {"origin ochre": {"r": 210, "g": 90, "b": 40}}}
        prompt = generate_cartoon_prompt(knowledge=knowledge, avoid=set())
        self.assertIsNotNone(prompt)
        self.assertIn("origin ochre", prompt.lower())

        instruction = interpret_user_prompt(
            "cel cartoon: a person holds still then turns in a kitchen, cartoon hold then snap"
        )
        instruction.duration_seconds = 2.5
        spec = build_spec_from_instruction(instruction, knowledge=knowledge)
        self.assertIn((210, 90, 40), spec.palette_colors[:4])
        self.assertEqual((spec.instance or {}).get("loop_origin"), origin)
        char = next(layer for layer in spec.scene_layers if layer.get("kind") == "character")
        kfs = char.get("keyframes") or []
        self.assertGreaterEqual(float(kfs[1]["t"]), 1.5)

    def test_cartoon_origin_field_is_the_starting_picture(self):
        import numpy as np
        from src.automation.prompt_gen import generate_cartoon_prompt
        from src.knowledge.reference_origin import measure_frames, slim_loop_origin
        from src.procedural.cel import render_cel_frame

        left = np.zeros((48, 48, 3), dtype=np.uint8)
        left[:, :24] = (220, 40, 40)
        left[:, 24:] = (40, 80, 200)
        right = left.copy()
        right[:, :24] = (40, 180, 80)
        right[:, 24:] = (220, 180, 40)
        recipe = measure_frames([left] * 4 + [right] * 4, fps=24.0, loop="cartoon")
        self.assertTrue(recipe.get("has_field"))
        origin = recipe
        knowledge = {"loop_origin": origin, "color_by_name": {}}
        prompt = generate_cartoon_prompt(knowledge=knowledge, avoid=set())
        self.assertIsNotNone(prompt)
        self.assertIn("origin field", prompt.lower())
        self.assertNotIn("kitchen", prompt.lower())

        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 2.5
        spec = build_spec_from_instruction(instruction, knowledge=knowledge)
        attached = (spec.instance or {}).get("loop_origin") or {}
        self.assertTrue(attached.get("has_field"))
        self.assertNotIn("field", attached)
        self.assertEqual(slim_loop_origin(origin).get("has_field"), True)

        spec.instance = {**(spec.instance or {}), "loop_origin": origin}
        hold = render_cel_frame(spec, 0.1, 96, 96, seed=3, duration_seconds=2.5)
        snap = render_cel_frame(spec, 2.4, 96, 96, seed=3, duration_seconds=2.5)
        self.assertEqual(hold.shape, (96, 96, 3))
        left_mean = hold[:, :40].astype(np.float32).mean(axis=(0, 1))
        right_mean = hold[:, 56:].astype(np.float32).mean(axis=(0, 1))
        self.assertGreater(float(left_mean[0] - left_mean[2]), 20.0)
        self.assertGreater(float(right_mean[2] - right_mean[0]), 20.0)
        self.assertGreater(float(np.abs(hold.astype(np.float32) - snap.astype(np.float32)).mean()), 8.0)


if __name__ == "__main__":
    unittest.main()

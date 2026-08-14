"""Per-video unique geometry: fish/trees/clouds are created from prompt+seed."""
from __future__ import annotations

import unittest

import numpy as np

from src.creation.builder import build_spec_from_instruction
from src.creation.props import props_for_setting
from src.interpretation.parser import interpret_user_prompt
from src.procedural.forms import (
    create_form,
    fish_mask,
    form_seed,
    rotate_into_local,
    tree_parts,
)


def _grid(n: int = 64):
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    xx = xx / max(1, n - 1)
    yy = yy / max(1, n - 1)
    return xx, yy


class TestProceduralForms(unittest.TestCase):
    def test_form_seed_stable_and_unique(self):
        a = form_seed("orange fish jumping", "fish0", extra=1)
        b = form_seed("orange fish jumping", "fish0", extra=1)
        c = form_seed("orange fish jumping", "fish0", extra=2)
        d = form_seed("blue fish jumping", "fish0", extra=1)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, d)

    def test_fish_masks_differ_across_seeds(self):
        xx, yy = _grid(48)
        a = create_form("fish", form_seed("orange fish", "f", extra=1), prompt="orange fish", trajectory="right")
        b = create_form("fish", form_seed("orange fish", "f", extra=2), prompt="orange fish", trajectory="right")
        ma = fish_mask(xx, yy, 0.5, 0.5, 0.18, a)
        mb = fish_mask(xx, yy, 0.5, 0.5, 0.18, b)
        self.assertFalse(np.array_equal(ma, mb))
        self.assertGreater(float(ma.max()), 0.8)
        self.assertGreater(float(mb.max()), 0.8)

    def test_same_prompt_and_seed_same_fish(self):
        seed = form_seed("koi jumping in the ocean", "fish0", extra=9)
        a = create_form("fish", seed, prompt="koi jumping in the ocean", label="koi", trajectory="jump")
        b = create_form("fish", seed, prompt="koi jumping in the ocean", label="koi", trajectory="jump")
        self.assertEqual(a["body_rx"], b["body_rx"])
        self.assertEqual(a["tail_spread"], b["tail_spread"])
        self.assertEqual(a["species"], "goldfish")

    def test_fish_mask_stays_connected_under_rotation(self):
        xx, yy = _grid(64)
        form = create_form(
            "fish",
            form_seed("fish jumping", "f", extra=3),
            prompt="a fish jumping in the ocean",
            trajectory="right",
        )
        rot = 0.35
        cx, cy, radius = 0.5, 0.5, 0.16
        xx_l, yy_l = rotate_into_local(xx, yy, cx, cy, rot)
        mask = fish_mask(xx_l, yy_l, cx, cy, radius, form)
        binary = (mask > 0.35).astype(np.uint8)
        self.assertGreater(int(binary.sum()), 40)
        # One connected component: flood from the centroid of the mask
        ys, xs = np.where(binary)
        self.assertGreater(len(ys), 0)
        start = (int(np.unravel_index(np.argmax(mask), mask.shape)[0]),
                 int(np.unravel_index(np.argmax(mask), mask.shape)[1]))
        q = [start]
        seen = set()
        h, w = binary.shape
        while q:
            y, x = q.pop()
            if (y, x) in seen or y < 0 or x < 0 or y >= h or x >= w:
                continue
            if binary[y, x] == 0:
                continue
            seen.add((y, x))
            q.extend(((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)))
        self.assertGreaterEqual(len(seen) / max(1, int(binary.sum())), 0.85)

    def test_pine_and_oak_masks_differ(self):
        xx, yy = _grid(48)
        pine = create_form("tree", 11, prompt="pine trees in a forest", label="pine", setting="forest")
        oak = create_form("tree", 11, prompt="oak trees in a forest", label="oak", setting="forest")
        self.assertEqual(pine["species"], "pine")
        self.assertEqual(oak["species"], "oak")
        pa = tree_parts(xx, yy, 0.5, 0.62, 0.2, pine)["canopy"]
        oa = tree_parts(xx, yy, 0.5, 0.62, 0.2, oak)["canopy"]
        self.assertFalse(np.array_equal(pa, oa))
        self.assertGreater(float(pa.max()), 0.5)
        self.assertGreater(float(oa.max()), 0.5)
        self.assertGreater(float(tree_parts(xx, yy, 0.5, 0.62, 0.2, oak)["leaves"].max()), 0.2)

    def test_forest_prop_positions_vary_with_seed(self):
        a = props_for_setting("forest", prompt="a person walking in a forest", creation_seed=1)
        b = props_for_setting("forest", prompt="a person walking in a forest", creation_seed=99)
        self.assertTrue(any(e["kind"] == "tree" for e in a))
        self.assertTrue(any(e["kind"] == "tree" for e in b))
        xa = sorted(round(e["prop_x"], 3) for e in a if e["kind"] == "tree")
        xb = sorted(round(e["prop_x"], 3) for e in b if e["kind"] == "tree")
        self.assertNotEqual(xa, xb)

    def test_same_prompt_seed_same_forest_layout(self):
        a = props_for_setting("forest", prompt="forest walk", creation_seed=7)
        b = props_for_setting("forest", prompt="forest walk", creation_seed=7)
        self.assertEqual(
            [(e["kind"], e["prop_x"], e["label"]) for e in a],
            [(e["kind"], e["prop_x"], e["label"]) for e in b],
        )

    def test_two_prompts_author_distinct_scene_instances(self):
        p1 = "a person walking left in a forest with soft vocals"
        p2 = "a person walking left in a pine forest at dusk"
        i1 = interpret_user_prompt(p1)
        i2 = interpret_user_prompt(p2)
        i1.duration_seconds = 5.0
        i2.duration_seconds = 5.0
        a = build_spec_from_instruction(i1, knowledge={}, creation_seed=11)
        b = build_spec_from_instruction(i2, knowledge={}, creation_seed=12)
        self.assertIsNotNone(a.instance)
        self.assertIsNotNone(b.instance)
        self.assertNotEqual(a.instance.get("horizon"), b.instance.get("horizon"))
        trees_a = [l["form"]["species"] for l in (a.scene_layers or []) if l.get("kind") == "tree"]
        trees_b = [l["form"]["species"] for l in (b.scene_layers or []) if l.get("kind") == "tree"]
        self.assertTrue(trees_a)
        self.assertTrue(trees_b)
        xa = sorted(round(l["keyframes"][0]["x"], 3) for l in (a.scene_layers or []) if l.get("kind") == "tree")
        xb = sorted(round(l["keyframes"][0]["x"], 3) for l in (b.scene_layers or []) if l.get("kind") == "tree")
        self.assertNotEqual(xa, xb)

    def test_same_prompt_and_seed_same_instance(self):
        prompt = "waves in the ocean with a jumping fish"
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 4.0
        a = build_spec_from_instruction(instruction, knowledge={}, creation_seed=21)
        b = build_spec_from_instruction(instruction, knowledge={}, creation_seed=21)
        self.assertEqual(a.instance.get("horizon"), b.instance.get("horizon"))
        self.assertEqual(a.palette_colors, b.palette_colors)
        self.assertEqual(a.shot_type, b.shot_type)

    def test_same_prompt_different_seeds_keep_named_look(self):
        prompt = "waves in the ocean with a jumping fish"
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 4.0
        a = build_spec_from_instruction(instruction, knowledge={}, creation_seed=21)
        b = build_spec_from_instruction(instruction, knowledge={}, creation_seed=99)
        self.assertEqual(a.palette_colors, b.palette_colors)
        self.assertEqual(a.shot_type, b.shot_type)
        self.assertEqual(a.intensity, b.intensity)
        self.assertEqual(a.lighting_preset, b.lighting_preset)
        self.assertNotEqual(a.instance.get("horizon"), b.instance.get("horizon"))
        self.assertNotEqual(a.instance.get("tex_salt"), b.instance.get("tex_salt"))

    def test_ocean_keeps_named_look_family(self):
        instruction = interpret_user_prompt("waves in the ocean")
        instruction.setting = "ocean"
        instruction.duration_seconds = 4.0
        spec = build_spec_from_instruction(instruction, knowledge={}, creation_seed=8)
        self.assertEqual(spec.gradient_type, "horizontal")
        self.assertEqual(spec.lighting_preset, "documentary")

    def test_builder_does_not_inject_learned_entities(self):
        instruction = interpret_user_prompt("slow warm gradient with calm ambient music")
        instruction.duration_seconds = 4.0
        knowledge = {
            "learned_entities": [{
                "kind": "fish",
                "label": "registry fish",
                "trajectory": "left",
                "bounce": True,
            }] * 8,
        }
        spec = build_spec_from_instruction(instruction, knowledge=knowledge, creation_seed=3)
        kinds = {l.get("kind") for l in (spec.scene_layers or [])}
        ids = {l.get("id") for l in (spec.scene_layers or [])}
        self.assertNotIn("learned0", ids)
        self.assertNotIn("fish", kinds)

    def test_named_registry_entity_appears_when_prompt_cites_it(self):
        instruction = interpret_user_prompt(
            "a Crimson Dart jumping in the ocean",
            knowledge={
                "learned_entities": [{
                    "kind": "fish",
                    "name": "Crimson Dart",
                    "label": "Crimson Dart",
                    "trajectory": "right",
                    "bounce": True,
                    "form": {"species": "goldfish", "body_rx": 0.91, "tail_spread": 0.44},
                }],
            },
        )
        kinds = {e.get("kind") for e in (instruction.entities or [])}
        self.assertIn("fish", kinds)
        named = [e for e in instruction.entities if (e.get("label") or "") == "Crimson Dart"]
        self.assertTrue(named)
        self.assertEqual(named[0].get("form", {}).get("species"), "goldfish")

    def test_composed_noun_is_not_collapsed_to_circle(self):
        instruction = interpret_user_prompt("a red kite drifting left with calm ambient music")
        kinds = [e.get("kind") for e in (instruction.entities or [])]
        self.assertIn("composed", kinds)
        self.assertTrue(any(e.get("label") == "kite" for e in instruction.entities))

    def test_prompt_fish_gets_form_on_layer(self):
        prompt = "an orange fish jumping in the ocean with a whoosh"
        instruction = interpret_user_prompt(prompt)
        instruction.duration_seconds = 5.0
        a = build_spec_from_instruction(instruction, knowledge={}, creation_seed=4)
        b = build_spec_from_instruction(instruction, knowledge={}, creation_seed=5)
        fish_a = [l for l in (a.scene_layers or []) if l.get("kind") == "fish"]
        fish_b = [l for l in (b.scene_layers or []) if l.get("kind") == "fish"]
        self.assertTrue(fish_a)
        self.assertTrue(fish_b)
        self.assertIn("form", fish_a[0])
        keys = ("body_rx", "body_ry", "tail_spread", "dorsal_rx", "start_x")
        self.assertTrue(
            any(fish_a[0]["form"].get(k) != fish_b[0]["form"].get(k) for k in keys)
        )


if __name__ == "__main__":
    unittest.main()

"""Prompt / seed diversity: wide template space, entropy seeds, no full recent-prompt reset."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from src.audio.pairing import pairing_kind_from_prompt
from src.automation.prompt_gen import (
    _FRAME_TEMPLATES,
    _WINDOW_TEMPLATES,
    generate_mission_prompt,
    generate_pixel_pairing_prompt,
    generate_targeted_color_family_prompt,
)
from src.creation.builder import build_spec_from_instruction
from src.interpretation.parser import interpret_user_prompt
from src.random_utils import fresh_seed


def _load_loop():
    path = Path(__file__).resolve().parents[1] / "scripts" / "automate_loop.py"
    spec = importlib.util.spec_from_file_location("automate_loop_diversity_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _spec(prompt: str):
    inst = interpret_user_prompt(prompt)
    inst.duration_seconds = 1.0
    return build_spec_from_instruction(inst, knowledge={})


class TestPromptSpace(unittest.TestCase):
    def test_template_space_is_wide(self):
        self.assertGreaterEqual(len(_FRAME_TEMPLATES), 10)
        self.assertGreaterEqual(len(_WINDOW_TEMPLATES), 10)

    def test_templates_keep_pairing_anchor_phrases(self):
        for tpl in _WINDOW_TEMPLATES:
            self.assertIn("motion window", tpl)
        for tpl in _FRAME_TEMPLATES:
            self.assertIn("static frame", tpl)
        for kind in ("frame", "window"):
            anchor = "motion window" if kind == "window" else "static frame"
            for _ in range(80):
                self.assertIn(anchor, generate_mission_prompt(kind=kind, focus="color", api_base=""))

    def test_mission_prompts_are_varied(self):
        for kind in ("frame", "window"):
            prompts = {
                generate_mission_prompt(kind=kind, focus="color", api_base="", mission=None)
                for _ in range(150)
            }
            self.assertGreaterEqual(len(prompts), 120, kind)
            openers = {" ".join(p.split()[:3]) for p in prompts}
            self.assertGreaterEqual(len(openers), 8, f"{kind}: templates barely vary")

    def test_pixel_pairing_prompts_are_varied(self):
        prompts = {
            generate_pixel_pairing_prompt(kind="window", knowledge={}) for _ in range(120)
        }
        self.assertGreaterEqual(len(prompts), 100)

    def test_every_template_keeps_pairing_kind_and_pure_mode(self):
        samples = []
        for kind in ("frame", "window"):
            for _ in range(60):
                samples.append((kind, generate_mission_prompt(kind=kind, focus="color", api_base="")))
                samples.append((kind, generate_mission_prompt(kind=kind, focus="sound", api_base="")))
                samples.append((kind, generate_pixel_pairing_prompt(kind=kind, knowledge={})))
        for _ in range(40):
            samples.append(("frame", generate_targeted_color_family_prompt(api_base="")))
        for kind, prompt in samples:
            self.assertTrue(prompt)
            self.assertEqual(pairing_kind_from_prompt(prompt), kind, prompt)
            spec = _spec(prompt)
            self.assertEqual(spec.creation_mode, "pure_per_frame", prompt)
            self.assertEqual(spec.sound_pairing, kind, prompt)
            self.assertTrue(spec.pure_sounds, prompt)


class TestSeeds(unittest.TestCase):
    def test_salted_seed_is_unique_and_31_bit(self):
        seeds = [fresh_seed("job-1", 7) for _ in range(3000)]
        self.assertEqual(len(set(seeds)), len(seeds))
        self.assertTrue(all(0 <= s < 2**31 for s in seeds))

    def test_seed_is_not_a_function_of_job_id_and_counter(self):
        self.assertNotEqual(fresh_seed("same", 1), fresh_seed("same", 1))

    def test_automate_loop_no_longer_uses_salted_hash(self):
        src = (Path(__file__).resolve().parents[1] / "scripts" / "automate_loop.py").read_text(encoding="utf-8")
        self.assertNotIn("hash(job_id)", src)
        self.assertIn("fresh_seed(job_id", src)


class TestRecentPrompts(unittest.TestCase):
    def test_relax_keeps_newest_half(self):
        mod = _load_loop()
        state = {"recent_prompts": [f"p{i}" for i in range(10)]}
        mod.relax_recent_prompts(state)
        self.assertEqual(state["recent_prompts"], [f"p{i}" for i in range(5, 10)])

    def test_relax_never_resets_a_populated_list_in_one_step(self):
        mod = _load_loop()
        state = {"recent_prompts": ["a", "b", "c"]}
        mod.relax_recent_prompts(state)
        self.assertEqual(state["recent_prompts"], ["c"])

    def test_relax_handles_missing_key(self):
        mod = _load_loop()
        state = {}
        mod.relax_recent_prompts(state)
        self.assertEqual(state["recent_prompts"], [])


if __name__ == "__main__":
    unittest.main()
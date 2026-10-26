"""a/an agreement in the grammar helper and in every prompt generator."""
from __future__ import annotations

import re
import unittest

from src.automation.prompt_gen import (
    generate_mini_scene_prompt,
    generate_mission_prompt,
    generate_pixel_pairing_prompt,
    generate_procedural_prompt,
    generate_targeted_color_family_prompt,
    generate_targeted_entity_prompt,
)
from src.grammar import article, articles_fixed, fix_articles, with_article
from src.interpretation.prompt_gen import generate_interpretation_prompt

_BAD = re.compile(r"(?<![\w'\-])(a|an)\s+([A-Za-z0-9][\w'\-]*)", re.I)


def _violations(text: str) -> list[str]:
    return [m.group(0) for m in _BAD.finditer(text) if m.group(1).lower() != article(m.group(2))]


class TestArticle(unittest.TestCase):
    def test_vowel_and_consonant_sounds(self):
        for w in ("ivory", "excited", "orange", "amber", "umbrella", "ugly", "under", "unusual", "hour", "honest", "8-bit", "olive"):
            self.assertEqual(article(w), "an", w)
        for w in ("red", "teal", "unicorn", "user", "uniform", "European", "one-off", "usual", "ukulele", "green", "5", "hat"):
            self.assertEqual(article(w), "a", w)

    def test_edge_inputs(self):
        self.assertEqual(article(""), "a")
        self.assertEqual(article("  Ivory"), "an")
        self.assertEqual(with_article("ivory"), "an ivory")
        self.assertEqual(with_article("red ball"), "a red ball")
        self.assertEqual(with_article(""), "")

    def test_fix_articles_sentence(self):
        self.assertEqual(fix_articles("a excited person and a ivory ball"), "an excited person and an ivory ball")
        self.assertEqual(fix_articles("an red box, an unicorn"), "a red box, a unicorn")
        self.assertEqual(fix_articles("A orange fox"), "An orange fox")
        self.assertEqual(fix_articles("An teal fox"), "A teal fox")
        self.assertEqual(fix_articles("a hourglass"), "an hourglass")
        self.assertEqual(fix_articles("a red ball with a user"), "a red ball with a user")  # unchanged
        self.assertIsNone(fix_articles(None))
        self.assertEqual(fix_articles(""), "")

    def test_fix_is_idempotent_and_leaves_inner_words(self):
        s = "banana and an apple; pizza with a ham"
        self.assertEqual(fix_articles(s), s)
        self.assertEqual(fix_articles(fix_articles("a ivory")), "an ivory")

    def test_decorator(self):
        @articles_fixed
        def f():
            return "a ivory"

        @articles_fixed
        def g():
            return None

        self.assertEqual(f(), "an ivory")
        self.assertIsNone(g())


class TestGeneratedPromptsGrammar(unittest.TestCase):
    def _scan(self, fn, n=250, **kw):
        bad = []
        for _ in range(n):
            p = fn(**kw)
            if p:
                bad += _violations(p)
        self.assertEqual(bad, [], fn.__name__)

    def test_mini_scene(self):
        self._scan(generate_mini_scene_prompt, avoid=set())

    def test_procedural(self):
        self._scan(generate_procedural_prompt)

    def test_pixel_pairing_and_mission(self):
        self._scan(generate_pixel_pairing_prompt, kind="window")
        self._scan(generate_pixel_pairing_prompt, kind="frame")
        self._scan(generate_mission_prompt, kind="frame", focus="color", api_base="")
        self._scan(generate_targeted_color_family_prompt, api_base="")

    def test_entity_and_interpretation(self):
        self._scan(generate_targeted_entity_prompt)
        self._scan(generate_interpretation_prompt)

    def test_known_glitches_never_appear(self):
        seen = " ".join(filter(None, (generate_mini_scene_prompt(avoid=set()) for _ in range(300))))
        for glitch in ("a excited", "a ivory", "a amber", "a orange", "a olive", "an red", "an blue"):
            self.assertNotIn(glitch, seen.lower())


if __name__ == "__main__":
    unittest.main()
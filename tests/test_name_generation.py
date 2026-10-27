"""Regression tests: generated registry names / interpretation prompts must be well-formed words."""
from src.interpretation.prompt_gen import generate_interpretation_prompt_batch
from src.knowledge import blend_names as bn


def test_malformed_fusions_are_detected():
    for bad in ("waveow", "ivoryum", "Sageum", "Valeow", "Goldow", "Willowow", "Rainin", "Roseure"):
        assert bn.is_malformed_fusion(bad), bad
        assert not bn.is_semantic_name(bad), bad


def test_real_words_and_compounds_are_not_flagged():
    for ok in ("Ivory", "Slate", "Emberglow", "Dawnrise", "Moonlight", "Golden", "Flower", "Woolbrook"):
        assert not bn.is_malformed_fusion(ok), ok


def test_generated_names_never_fuse_word_and_fragment_and_stay_unique():
    names: set[str] = set()
    for i in range(3000):
        n = bn.generate_sensible_name("sound", f"key{i}", existing_names=names)
        assert n not in names, "names must stay unique"
        assert not bn.is_malformed_fusion(n), n
        assert n.isalpha() and n[0].isupper() and n[1:].islower(), n
        names.add(n)
    assert len(names) == 3000


def test_invent_word_is_not_a_fixed_list():
    words = {bn._invent_word(s) for s in range(0, 200000, 37)}
    assert len(words) > 1500
    assert not any(bn.is_malformed_fusion(w) for w in words)


def test_humanize_splits_glued_color_names():
    assert bn.humanize_name("DarkTangerine") == "Dark Tangerine"
    assert bn.humanize_name("darktangerine") == "dark tangerine"
    assert bn.humanize_name("Slate") == "Slate"
    assert bn.humanize_name("dark") == "dark"
    assert bn.clean_name_for_prompt("ivoryum") is None
    assert bn.clean_name_for_prompt("CoolPlum") == "Cool Plum"


def test_sanitize_prompt_words():
    assert bn.sanitize_prompt_words("shadowed with DarkTangerine style") == "shadowed with Dark Tangerine style"
    assert bn.sanitize_prompt_words("darktangerine feeling night style") == "dark tangerine feeling night style"
    assert bn.has_malformed_word("a Slate palette waveow")
    assert not bn.has_malformed_word("a Slate palette wave")


def test_prompts_from_dirty_registries_are_clean_and_use_correct_articles():
    knowledge = {
        "learned_colors": {
            "a": {"name": "ivoryum", "count": 1},
            "b": {"name": "DarkTangerine", "count": 1},
            "c": {"name": "Slate", "count": 2},
        },
        "by_keyword": {"waveow": {"count": 3}, "ember": {"count": 3}},
        "by_palette": {"darktangerine": {"count": 2}},
        "learned_motion": [{"name": "Valeow", "count": 1}, {"name": "Drift", "count": 1}],
    }
    prompts = generate_interpretation_prompt_batch(60, knowledge=knowledge)
    assert prompts
    for p in prompts:
        low = p.lower()
        assert not bn.has_malformed_word(p), p
        for bad in ("ivoryum", "waveow", "valeow", "darktangerine"):
            assert bad not in low, p
        assert "a ivory" not in low and "an slate" not in low, p

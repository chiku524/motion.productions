# Procedural video engine: our algorithms and data only — no external "model"

from .parser import parse_prompt_to_spec, SceneSpec

__all__ = ["parse_prompt_to_spec", "SceneSpec", "ProceduralVideoGenerator"]


def __getattr__(name: str):
    if name == "ProceduralVideoGenerator":
        from .generator import ProceduralVideoGenerator
        return ProceduralVideoGenerator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

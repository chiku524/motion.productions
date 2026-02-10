"""
Cinematography: shot types, transitions, scene structure.
Phase 2 of the roadmap.
"""
from .schema import ShotSpec, SceneScript
from .shot_types import get_shot_params
from .transitions import apply_transition

__all__ = ["ShotSpec", "SceneScript", "get_shot_params", "apply_transition"]

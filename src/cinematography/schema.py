"""
Scene script schema: shots and transitions.
"""
from dataclasses import dataclass, field


@dataclass
class ShotSpec:
    """Single shot specification."""
    shot_type: str = "medium"      # wide | medium | close | pov
    transition_in: str = "cut"     # cut | fade | dissolve | wipe
    transition_out: str = "cut"
    pacing: float = 1.0            # 1 = normal; <1 = slow; >1 = fast
    duration_seconds: float = 6.0


@dataclass
class SceneScript:
    """Sequence of shots with transitions."""
    shots: list[ShotSpec] = field(default_factory=list)
    total_duration: float = 0.0

    def __post_init__(self) -> None:
        if self.total_duration == 0 and self.shots:
            self.total_duration = sum(s.duration_seconds for s in self.shots)

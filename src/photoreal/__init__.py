"""
Photoreal path (Phase 7.4) — same SceneSpec / registries contract as procedural.

Today this package exposes a pluggable backend protocol. The default
``enhanced`` backend is the procedural renderer with film_look + depth
planes enabled (Tiers A–E). A future generative/asset photoreal backend
can implement PhotorealBackend without changing interpretation or creation.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np

from ..procedural.parser import SceneSpec


@runtime_checkable
class PhotorealBackend(Protocol):
    """Render one frame from an already-built SceneSpec."""

    name: str

    def render_frame(
        self,
        spec: SceneSpec,
        t: float,
        width: int,
        height: int,
        *,
        seed: int = 0,
        duration_seconds: float | None = None,
    ) -> np.ndarray:
        ...


class EnhancedProceduralBackend:
    """
    Procedural path with Tier A–E realism aids forced on.

    Not photoreal photography — bridges toward 7.4 while registries grow.
    """

    name = "enhanced"

    def render_frame(
        self,
        spec: SceneSpec,
        t: float,
        width: int,
        height: int,
        *,
        seed: int = 0,
        duration_seconds: float | None = None,
    ) -> np.ndarray:
        from ..procedural.renderer import render_frame

        # Force film + depth without mutating caller's long-lived spec permanently
        # by copying shallow flags onto a thin wrapper object.
        class _SpecView:
            def __init__(self, base: SceneSpec):
                self._base = base

            def __getattr__(self, item: str) -> Any:
                if item == "film_look":
                    return True
                if item == "depth_parallax":
                    return True
                if item == "render_engine":
                    return "enhanced"
                return getattr(self._base, item)

        return render_frame(
            _SpecView(spec),  # type: ignore[arg-type]
            t,
            width,
            height,
            seed=seed,
            duration_seconds=duration_seconds,
        )


class ProceduralBackend:
    """Stock procedural renderer (honors spec flags as-is)."""

    name = "procedural"

    def render_frame(
        self,
        spec: SceneSpec,
        t: float,
        width: int,
        height: int,
        *,
        seed: int = 0,
        duration_seconds: float | None = None,
    ) -> np.ndarray:
        from ..procedural.renderer import render_frame

        return render_frame(
            spec, t, width, height, seed=seed, duration_seconds=duration_seconds,
        )


def get_render_backend(engine: str | None = None) -> PhotorealBackend:
    """
    Resolve a frame backend by engine name.

    - procedural (default): stock path
    - enhanced | photoreal: enhanced procedural (placeholder until true 7.4)
    """
    name = (engine or "procedural").strip().lower()
    if name in ("enhanced", "photoreal", "realistic"):
        return EnhancedProceduralBackend()
    return ProceduralBackend()

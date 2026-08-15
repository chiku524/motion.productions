"""
Photoreal path (Phase 7.4) — same SceneSpec / registries contract as procedural.

- ``enhanced``: procedural renderer with film_look + depth planes (Tiers A–E).
- ``photoreal``: registry consumer — binds named colors, then grades atmosphere
  from those values. Still NumPy / no external model; this is the destination
  contract loops fill dictionaries for.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..procedural.parser import SceneSpec
from .consumer import apply_photoreal_grade, bind_spec_to_registries, catalog_from_knowledge
from .environment import composite_environment, render_environment_plate
from .mesh import mesh_recipe_for_kind, overlay_mesh_subjects, rasterize_mesh
from .obj import Mesh, load_mesh, parse_gltf, parse_obj, tessellate_parts, write_obj

__all__ = [
    "PhotorealBackend",
    "EnhancedProceduralBackend",
    "PhotorealRegistryBackend",
    "ProceduralBackend",
    "apply_photoreal_grade",
    "bind_spec_to_registries",
    "catalog_from_knowledge",
    "composite_environment",
    "get_render_backend",
    "Mesh",
    "load_mesh",
    "mesh_recipe_for_kind",
    "overlay_mesh_subjects",
    "parse_gltf",
    "parse_obj",
    "rasterize_mesh",
    "render_environment_plate",
    "tessellate_parts",
    "write_obj",
]


class PhotorealBackend:
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
        t_content: float | None = None,
    ) -> np.ndarray:
        raise NotImplementedError


class EnhancedProceduralBackend(PhotorealBackend):
    """
    Procedural path with Tier A–E realism aids forced on.

    Bridge toward 7.4 while registries grow. Not the photoreal consumer.
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
        t_content: float | None = None,
    ) -> np.ndarray:
        from ..procedural.renderer import render_frame

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
            t_content=t_content,
        )


class PhotorealRegistryBackend(PhotorealBackend):
    """
    Photoreal consumer: enhanced film/depth path, then a grade that uses
    named registry colors bound onto the spec (sky haze, bounce fill).
    """

    name = "photoreal"

    def render_frame(
        self,
        spec: SceneSpec,
        t: float,
        width: int,
        height: int,
        *,
        seed: int = 0,
        duration_seconds: float | None = None,
        t_content: float | None = None,
    ) -> np.ndarray:
        from ..procedural.renderer import render_frame

        class _SpecView:
            def __init__(self, base: SceneSpec):
                self._base = base

            def __getattr__(self, item: str) -> Any:
                if item == "film_look":
                    return True
                if item == "depth_parallax":
                    return True
                if item == "render_engine":
                    return "photoreal"
                return getattr(self._base, item)

        t_abs = t_content if t_content is not None else t
        frame = render_frame(
            _SpecView(spec),  # type: ignore[arg-type]
            t,
            width,
            height,
            seed=seed,
            duration_seconds=duration_seconds,
            t_content=t_content,
        )
        return apply_photoreal_grade(frame, spec, t=float(t_abs))


class ProceduralBackend(PhotorealBackend):
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
        t_content: float | None = None,
    ) -> np.ndarray:
        from ..procedural.renderer import render_frame

        return render_frame(
            spec, t, width, height,
            seed=seed, duration_seconds=duration_seconds, t_content=t_content,
        )


def get_render_backend(engine: str | None = None) -> PhotorealBackend:
    """
    Resolve a frame backend by engine name.

    - procedural (default): stock path
    - enhanced: film + depth stand-in
    - photoreal | realistic: registry-bound consumer
    """
    name = (engine or "procedural").strip().lower()
    if name in ("photoreal", "realistic"):
        return PhotorealRegistryBackend()
    if name == "enhanced":
        return EnhancedProceduralBackend()
    return ProceduralBackend()

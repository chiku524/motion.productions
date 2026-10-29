"""
Colour survey clips: 1-second clips that are a grid of flat patches of the next batch of *target* colour cells.

Why a separate render mode (decision, documented in docs/COLOR_SURVEY.md)
------------------------------------------------------------------------
Creative clips almost never contain a given exact RGB value as a flat area, so covering 16,777,216 cells from
creative clips alone is hopeless. A survey clip is built to contain exactly the colours we still lack, one per
tile (default 16 x 16 tiles of 32 px, 24 frames = 6,144 cells per 1 s clip).

* Survey clips **skip the content-novelty gate** (they are deliberately repetitive flat grids) and are **never
  published, uploaded, fingerprinted into the novelty store or given a /api/jobs row**: they live as a temp file
  that is deleted right after verification, and cost zero D1 writes.
* They are encoded with the lossless ``libx264rgb -crf 0`` profile by default, so a decoded tile median equals the
  target **exactly** (measured max error 0 over thousands of random + extreme colours). A target is marked
  ``verified`` when its decoded tile median is within the profile's tolerance of the target (0 for lossless),
  otherwise the decoded colour is recorded as ``observed`` (it really appeared in a decoded frame) and the target
  stays unconfirmed (attempt counted; parked after MAX_ATTEMPTS).
* The production profile (``libx264`` quality 8, yuv420p; what creative clips use) cannot round-trip exact 8-bit RGB:
  limited-range 4:2:0 YUV maps many RGB values to one and measured error reaches 4 per channel. It is kept as a
  selectable profile (``COLOR_SURVEY_CODEC=production``, tolerance 4) and as the automatic fallback when the
  local ffmpeg lacks libx264rgb.
* Every frame is an intra frame (``-g 1``) so frames cannot bleed into each other.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .color_cells import (
    ColorCellStore,
    ColorWorkQueue,
    ids_to_rgb_array,
    rgb_array_to_ids,
)
from .color_tiles import DEFAULT_MIN_FLAT_FRAC, DEFAULT_MIN_PIXELS, grid_tile_colors

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodecProfile:
    name: str
    writer_kwargs: dict
    tol: int  # max per-channel |decoded - target| still accepted as "verified"


PROFILES: dict[str, CodecProfile] = {
    "lossless": CodecProfile(
        "lossless",
        {"codec": "libx264rgb", "pixelformat": "rgb24", "macro_block_size": 1, "quality": None,
         "output_params": ["-crf", "0", "-preset", "ultrafast", "-g", "1"]},
        tol=0,
    ),
    "production": CodecProfile(
        "production",
        {"codec": "libx264", "quality": 8, "macro_block_size": 16, "output_params": ["-g", "1"]},
        tol=4,
    ),
}
_BROKEN_PROFILES: set[str] = set()


@dataclass(frozen=True)
class SurveySettings:
    tile: int = 32
    rows: int = 16
    cols: int = 16
    fps: int = 24
    seconds: float = 1.0
    profile: str = "lossless"
    min_pixels: int = DEFAULT_MIN_PIXELS
    min_flat_frac: float = DEFAULT_MIN_FLAT_FRAC

    @property
    def frames(self) -> int:
        return max(1, int(round(self.fps * self.seconds)))

    @property
    def per_frame(self) -> int:
        return self.rows * self.cols

    @property
    def slots(self) -> int:
        return self.frames * self.per_frame

    @property
    def size(self) -> tuple[int, int]:
        return self.cols * self.tile, self.rows * self.tile

    @classmethod
    def from_env(cls) -> "SurveySettings":
        def _i(name: str, d: int) -> int:
            v = (os.environ.get(name) or "").strip()
            return int(v) if v.isdigit() else d

        def _f(name: str, d: float) -> float:
            try:
                return float(os.environ.get(name) or d)
            except ValueError:
                return d

        grid = max(1, _i("COLOR_SURVEY_GRID", 16))
        prof = (os.environ.get("COLOR_SURVEY_CODEC") or "lossless").strip().lower()
        return cls(
            tile=max(8, _i("COLOR_SURVEY_TILE", 32)),
            rows=grid,
            cols=grid,
            fps=max(1, _i("COLOR_SURVEY_FPS", 24)),
            seconds=max(1 / 24, _f("COLOR_SURVEY_SECONDS", 1.0)),
            profile=prof if prof in PROFILES else "lossless",
        )


def survey_enabled() -> bool:
    return (os.environ.get("LOOP_COLOR_SURVEY") or "").strip().lower() in ("1", "true", "on", "yes")


# ---------------------------------------------------------------------------------------------------------------
# build / encode / decode / score
# ---------------------------------------------------------------------------------------------------------------
def layout_cells(cell_ids: np.ndarray, st: SurveySettings) -> tuple[np.ndarray, np.ndarray]:
    """Pack ``cell_ids`` (<= st.slots) into (frames, rows, cols) target ids + a validity mask (pad slots invalid)."""
    ids = np.zeros(st.slots, dtype=np.int64)
    valid = np.zeros(st.slots, dtype=bool)
    n = min(len(cell_ids), st.slots)
    ids[:n] = cell_ids[:n]
    valid[:n] = True
    shape = (st.frames, st.rows, st.cols)
    return ids.reshape(shape), valid.reshape(shape)


def build_frames(target_ids: np.ndarray, valid: np.ndarray, st: SurveySettings) -> np.ndarray:
    """(F, rows, cols) ids -> (F, H, W, 3) uint8 frames of flat tiles (pad tiles are mid-grey)."""
    rgb = ids_to_rgb_array(target_ids)
    rgb[~valid] = 128
    out = np.repeat(np.repeat(rgb, st.tile, axis=1), st.tile, axis=2)
    return np.ascontiguousarray(out)


def encode_frames(frames: np.ndarray, path: Path, profile: CodecProfile, fps: int) -> None:
    import imageio.v2 as imageio

    writer = imageio.get_writer(str(path), fps=fps, **profile.writer_kwargs)
    try:
        for fr in frames:
            writer.append_data(fr)
    finally:
        writer.close()


def decode_frames(path: Path) -> np.ndarray:
    import imageio.v2 as imageio

    reader = imageio.get_reader(str(path))
    try:
        frames = [np.asarray(fr)[..., :3] for fr in reader]
    finally:
        reader.close()
    if not frames:
        raise RuntimeError("decoded zero frames")
    return np.stack(frames)


def score_frames(
    decoded: np.ndarray,
    target_ids: np.ndarray,
    valid: np.ndarray,
    st: SurveySettings,
    profile: CodecProfile,
) -> dict[str, np.ndarray]:
    """Compare decoded tile medians with their targets. All arrays are (F, rows, cols)."""
    f_target = target_ids.shape[0]
    qual = np.zeros(target_ids.shape, dtype=bool)
    med = np.zeros(target_ids.shape + (3,), dtype=np.uint8)
    for f in range(min(f_target, decoded.shape[0])):
        g = grid_tile_colors(
            decoded[f], st.tile, tol=profile.tol, min_pixels=st.min_pixels, min_flat_frac=st.min_flat_frac,
        )
        if g.median.shape[:2] != (st.rows, st.cols):
            raise RuntimeError(f"decoded frame size {decoded.shape[1:3]} does not match the survey layout")
        qual[f], med[f] = g.qualifies, g.median
    tgt_rgb = ids_to_rgb_array(target_ids)
    err = np.abs(med.astype(np.int16) - tgt_rgb.astype(np.int16)).max(axis=-1)
    return {"qualifies": qual & valid, "median": med, "err": err, "valid": valid}


@dataclass
class SurveyResult:
    targets: int = 0
    verified: int = 0
    observed_new: int = 0
    failed: int = 0
    mismatches: int = 0     # qualifying tiles whose decoded colour differs from the target by more than tol
    inexact: int = 0        # qualifying tiles whose decoded colour is not exactly the target (observed, never verified)
    max_err: int = 0        # max per-channel |decoded - target| over qualifying tiles
    profile: str = ""
    fallback: bool = False
    frames_decoded: int = 0
    elapsed_s: float = 0.0
    covered: int = 0
    pct_covered: float = 0.0
    total_clips: int = 0    # clips ever recorded in this store (``clips`` of a loop summary is only this iteration's)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _active_profile(st: SurveySettings) -> tuple[CodecProfile, bool]:
    name = st.profile
    if name in _BROKEN_PROFILES:
        return PROFILES["production"], True
    return PROFILES[name], False


def run_survey_clip(
    store: ColorCellStore,
    queue: ColorWorkQueue,
    st: SurveySettings | None = None,
    tmp_dir: Path | str | None = None,
    cells: np.ndarray | None = None,
) -> SurveyResult | None:
    """Render, encode, decode and verify one survey clip; record the outcome in the store. None if no cells are left."""
    st = st or SurveySettings.from_env()
    t0 = time.monotonic()
    targets = np.asarray(cells, dtype=np.int64) if cells is not None else queue.next_cells(st.slots)
    if targets.size == 0:
        return None
    target_ids, valid = layout_cells(targets, st)
    frames = build_frames(target_ids, valid, st)
    work = Path(tempfile.mkdtemp(prefix="color_survey_", dir=str(tmp_dir) if tmp_dir else None))
    path = work / "survey.mp4"
    try:
        profile, fallback = _active_profile(st)
        try:
            encode_frames(frames, path, profile, st.fps)
        except Exception as e:  # e.g. an ffmpeg without libx264rgb
            if profile.name == "production":
                raise
            logger.warning("survey profile %s failed (%s); falling back to production profile", profile.name, e)
            _BROKEN_PROFILES.add(profile.name)
            profile, fallback = PROFILES["production"], True
            encode_frames(frames, path, profile, st.fps)
        decoded = decode_frames(path)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    sc = score_frames(decoded, target_ids, valid, st, profile)
    q, v, err = sc["qualifies"], sc["valid"], sc["err"]
    # "verified" means the target colour itself was decoded from the clip: the flat tile's median is EXACTLY the target.
    # ``profile.tol`` is only the flatness tolerance of the tile and never a licence to call a +/-4 colour exact
    # (a lossy fallback used to mark such targets verified, inflating coverage with colours that were never seen).
    ok_target = q & (err == 0)
    seen_off = q & (err > 0)                       # decoded colour differs from target: a real observation of ITS colour
    # A lossy codec cannot reproduce targets, so its misses say nothing about the cell: do not count attempts/quarantine.
    failed_mask = (v & ~ok_target) if profile.tol == 0 else np.zeros_like(v)
    dec_ids = rgb_array_to_ids(sc["median"])
    res = SurveyResult(
        targets=int(v.sum()),
        verified=int(ok_target.sum()),
        observed_new=int(len(np.unique(dec_ids[seen_off]))) if seen_off.any() else 0,
        failed=int(failed_mask.sum()),
        inexact=int(seen_off.sum()),
        mismatches=int((q & (err > profile.tol)).sum()),
        max_err=int(err[q].max()) if q.any() else 0,
        profile=profile.name,
        fallback=fallback,
        frames_decoded=int(decoded.shape[0]),
    )
    counts = store.record_outcome(
        verified=target_ids[ok_target],
        observed=dec_ids[seen_off],
        failed=target_ids[failed_mask],
        ledger={"k": "survey", "n": res.targets, "ok": res.verified, "obs": res.observed_new,
                "fail": res.failed, "p": profile.name, "me": res.max_err,
                "w": [queue.index, queue.count]},
    )
    res.covered, res.pct_covered = counts["covered"], counts["pct_covered"]
    res.total_clips = counts.get("survey_clips", 0)
    res.elapsed_s = round(time.monotonic() - t0, 2)
    return res


# ---------------------------------------------------------------------------------------------------------------
# codec tolerance measurement
# ---------------------------------------------------------------------------------------------------------------
def measure_codec_tolerance(
    profile: str = "lossless", n_colors: int = 3072, seed: int = 0, st: SurveySettings | None = None,
) -> dict[str, Any]:
    """Round-trip random + extreme colours through ``profile`` and report the per-channel absolute error of
    the decoded tile medians. This is how the ``tol`` of each profile was measured."""
    base = st or SurveySettings()
    st = SurveySettings(**{**base.__dict__, "profile": profile, "seconds": 1.0})
    rng = np.random.default_rng(seed)
    corners = [(r, g, b) for r in (0, 255) for g in (0, 255) for b in (0, 255)]
    greys = [(v, v, v) for v in range(0, 256, 5)]
    near = [(r, g, b) for r in (0, 1, 16, 17, 235, 236, 254, 255) for g in (0, 128, 255) for b in (1, 254)]
    fixed = np.array(corners + greys + near, dtype=np.uint8)
    rand = rng.integers(0, 256, size=(max(0, n_colors - len(fixed)), 3), dtype=np.uint8)
    ids = np.unique(rgb_array_to_ids(np.concatenate([fixed, rand]))).astype(np.int64)
    ids = ids[: st.slots]
    target_ids, valid = layout_cells(ids, st)
    frames = build_frames(target_ids, valid, st)
    work = Path(tempfile.mkdtemp(prefix="color_codec_"))
    try:
        prof = PROFILES[profile]
        encode_frames(frames, work / "m.mp4", prof, st.fps)
        decoded = decode_frames(work / "m.mp4")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # tol=255 so every flat tile qualifies and we see the true error
    wide = CodecProfile(profile, PROFILES[profile].writer_kwargs, tol=255)
    sc = score_frames(decoded, target_ids, valid, st, wide)
    m = sc["qualifies"]
    tgt = ids_to_rgb_array(target_ids)[m].astype(np.int16)
    got = sc["median"][m].astype(np.int16)
    d = np.abs(got - tgt)
    return {
        "profile": profile,
        "colors": int(m.sum()),
        "max_abs_err": int(d.max()) if d.size else None,
        "max_abs_err_per_channel": d.max(axis=0).tolist() if d.size else None,
        "p99_abs_err": float(np.percentile(d, 99)) if d.size else None,
        "mean_abs_err": round(float(d.mean()), 3) if d.size else None,
        "exact_fraction": round(float((d.max(axis=1) == 0).mean()), 4) if d.size else None,
    }


# ---------------------------------------------------------------------------------------------------------------
# loop glue
# ---------------------------------------------------------------------------------------------------------------
def run_survey_iteration(api_base: str = "", clips: int | None = None, sync: bool = True) -> dict[str, Any]:
    """Run ``clips`` survey clips for this container's stride (env-configured) and maybe sync. Never raises."""
    summary: dict[str, Any] = {"clips": 0, "targets": 0, "verified": 0, "observed_new": 0, "failed": 0}
    try:
        n = clips if clips is not None else max(1, int((os.environ.get("LOOP_COLOR_SURVEY_CLIPS") or "4").strip() or 4))
        st = SurveySettings.from_env()
        store = ColorCellStore()
        queue = ColorWorkQueue(store, stream="survey")
        last: SurveyResult | None = None
        for _ in range(n):
            res = run_survey_clip(store, queue, st)
            if res is None:
                summary["exhausted"] = True
                break
            last = res
            summary["clips"] += 1
            for k in ("targets", "verified", "observed_new", "failed"):
                summary[k] += getattr(res, k)
            if res.mismatches:
                logger.warning("survey: %d tiles off by > tol (max err %d, profile %s)", res.mismatches, res.max_err, res.profile)
        if last is not None:
            summary.update(covered=last.covered, pct_covered=last.pct_covered, profile=last.profile,
                           total_clips=last.total_clips,
                           stride=[queue.index, queue.count], elapsed_s=round(last.elapsed_s * summary["clips"], 1))
        if sync and summary["clips"] and api_base:
            from .color_sync import maybe_sync

            summary["sync"] = maybe_sync(store, api_base, clips_done=summary["clips"])
    except Exception as e:  # the survey must never break the creative loop
        logger.warning("colour survey iteration failed: %s", e)
        summary["error"] = str(e)[:200]
    return summary


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Colour survey tools")
    ap.add_argument("--measure", choices=sorted(PROFILES), nargs="*", help="measure codec round-trip error")
    ap.add_argument("--colors", type=int, default=3072)
    ap.add_argument("--run", type=int, default=0, help="run N survey clips against the local store")
    args = ap.parse_args(argv)
    if args.measure is not None:
        for p in args.measure or sorted(PROFILES):
            print(json.dumps(measure_codec_tolerance(p, n_colors=args.colors)))
    if args.run:
        print(json.dumps(run_survey_iteration("", clips=args.run, sync=False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
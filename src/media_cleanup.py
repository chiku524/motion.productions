"""Drop local render files after discovery has read them.

Registries live in D1 (and the uploaded MP4 in R2). The on-disk file is scratch.
Keeping every loop MP4 grows the Docker disk without adding discoveries.
"""
from __future__ import annotations

from pathlib import Path

_SCRATCH_GLOBS = (
    "loop_*.mp4",
    "job_*.mp4",
    "auto_*.mp4",
    "video_*.mp4",
    "_seg_*.mp4",
    "sound_loop_*.wav",
)


def discard_rendered_media(path: Path | None) -> None:
    """Delete one render file. Missing files are fine."""
    if path is None:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def prune_render_scratch(directory: Path, *, keep: int = 1) -> int:
    """
    Delete old scratch renders in directory.

    keep=0 removes every matching file. keep=1 leaves the newest so a failed
    run can still be inspected, and older ones cannot pile up.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    files: list[Path] = []
    for pattern in _SCRATCH_GLOBS:
        files.extend(p for p in directory.glob(pattern) if p.is_file())
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for path in files[max(0, keep) :]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed

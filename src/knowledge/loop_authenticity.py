"""
Per-iteration authenticity: a loop run is authentic when it is a real
learn cycle for that worker's slice — novel prompt, knowledge used,
extract/grow actually ran. Zero novel rows is honest, not fake progress.
"""
from __future__ import annotations

from typing import Any

from ..automation.prompt_gen import _is_near_duplicate

# Sources that count as a real prompt for their worker (not a replay catalog).
AUTHENTIC_SOURCES = frozenset({
    "pixel_pairing_frame",
    "pixel_pairing_window",
    "mission_frame_color",
    "mission_frame_sound",
    "mission_window_color",
    "mission_window_sound",
    "targeted_color_family",
    "targeted_narrative",
    "targeted_blended",
    "mini_scene",
    "procedural",
    "interpretation",
    "sound_pairing",
})

# User-like scenes that must exercise the photoreal consumer.
PHOTOREAL_SOURCES = frozenset({
    "mini_scene",
    "targeted_narrative",
    "targeted_blended",
})


def prompt_is_novel(prompt: str, recent: list[str] | set[str] | None) -> bool:
    text = (prompt or "").strip()
    if not text:
        return False
    avoid = set(recent or [])
    if text in avoid:
        return False
    return not _is_near_duplicate(text, avoid)


def evaluate_iteration(
    *,
    source: str,
    prompt: str,
    recent: list[str] | set[str] | None,
    knowledge: dict[str, Any] | None,
    growth_ran: bool,
    growth_added: dict[str, Any] | None = None,
    render_engine: str | None = None,
    worker: str = "video",
    content_novel: bool | None = None,
    require_content_novelty: bool = False,
    content_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return a structured authenticity record.

    authentic is True only when the iteration did real work for its slice.
    When ``require_content_novelty`` is set (rendered-video loops), the clip's
    content fingerprint (frame hash + palette + audio spectrum) must also have
    been checked and found far from recent clips: ``content_novel`` must be True.
    A different prompt string alone no longer counts as authentic.
    novel_rows may be 0 (already-known values) — that is still authentic if
    growth ran; it is not a new registry row.
    """
    src = (source or "").strip() or "unknown"
    novel = prompt_is_novel(prompt, recent)
    knowledge_used = bool(knowledge)
    added = growth_added or {}
    novel_rows = 0
    for v in added.values():
        try:
            novel_rows += int(v or 0)
        except (TypeError, ValueError):
            continue

    engine = (render_engine or "").strip().lower()
    needs_photoreal = src in PHOTOREAL_SOURCES
    photoreal_bound = (not needs_photoreal) or engine in ("photoreal", "enhanced", "realistic")

    content_ok = (not require_content_novelty) or (content_novel is True)

    authentic = (
        src in AUTHENTIC_SOURCES
        and novel
        and content_ok
        and knowledge_used
        and growth_ran
        and photoreal_bound
    )
    return {
        "authentic": authentic,
        "source": src,
        "worker": worker,
        "novel_prompt": novel,
        "knowledge_used": knowledge_used,
        "growth_ran": growth_ran,
        "novel_rows": novel_rows,
        "photoreal_bound": photoreal_bound,
        "content_novel": content_novel,
        "content_checked": content_novel is not None,
        "content_check": content_check,
        "needs_photoreal": needs_photoreal,
        "render_engine": engine or None,
    }

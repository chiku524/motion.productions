"""Free-tier sync of the exact-colour bitset to the Worker (``POST /api/coverage/color/chunks``).

Budget (Cloudflare free: 100k D1 writes/day, 100k Worker requests/day, 10 ms CPU per request):

* never one row per colour: the registry is **32 rows** (64 KiB chunks, three bit planes each);
* at most ``COLOR_SYNC_MAX_CHUNKS`` (default 32) chunks and ``ceil(32 / 8) = 4`` requests per sync;
* infrequent: due every ``COLOR_SYNC_INTERVAL_S`` (default 1 h) or after ``COLOR_SYNC_EVERY_CLIPS`` survey clips
  (default 2000) but never more often than ``COLOR_SYNC_MIN_GAP_S`` (default 5 min);
* only chunks whose planes changed since the last successful sync are sent (sha1 digest per chunk), and the Worker
  writes only chunks whose merged bits actually changed, so a quiet hour costs 0 D1 writes;
* a full resend every 24 h heals a lost update (two syncs racing on one chunk: the Worker does read-OR-write, not a
  SQL-level atomic OR);
* shared state + lock in the store directory, so N containers sharing the volume produce ONE sync, not N;
* ``COLOR_SYNC=0`` disables; a free-tier cooldown, a missing table (Worker says ``available:false``) or a version
  mismatch back the sync off for hours. A failure never raises.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from .color_cells import (
    CHUNK_BYTES,
    N_CHUNKS,
    PLANES,
    SPACE_ID,
    SPACE_VERSION,
    ColorCellStore,
    _FileLock,
    atomic_write_bytes,
    chunk_bytes,
    chunk_pack,
)

logger = logging.getLogger(__name__)

CHUNKS_PER_REQUEST = 8      # mirrors MAX_CHUNKS_PER_REQUEST in cloudflare/src/routes/coverage.ts
FULL_RESEND_S = 24 * 3600
TABLE_MISSING_BACKOFF_S = 6 * 3600
VERSION_BACKOFF_S = 24 * 3600
PUSH_PATH = "/api/coverage/color/chunks"
REPORT_PATH = "/api/coverage/color"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def sync_enabled() -> bool:
    return (os.environ.get("COLOR_SYNC", "1").strip().lower() not in ("0", "false", "no", "off"))


def _state_path(store: ColorCellStore) -> Path:
    return store.dir / "sync_state.json"


def load_state(store: ColorCellStore) -> dict:
    try:
        st = json.loads(_state_path(store).read_text(encoding="utf-8"))
        if isinstance(st, dict):
            return st
    except (OSError, ValueError):
        pass
    return {}


def _save_state(store: ColorCellStore, st: dict) -> None:
    try:
        atomic_write_bytes(_state_path(store), json.dumps(st, sort_keys=True).encode("utf-8"))
    except OSError as e:
        logger.warning("color sync: could not save state: %s", e)


def chunk_digest(store: ColorCellStore, idx: int) -> str:
    h = hashlib.sha1()
    for p in PLANES:
        h.update(chunk_bytes(store.planes[p], idx))
    return h.hexdigest()


def changed_chunks(store: ColorCellStore, st: dict, *, full: bool = False) -> dict[int, str]:
    """{chunk idx: digest} for chunks that hold any bit and differ from the last successfully synced digest."""
    synced = st.get("digests") or {}
    out: dict[int, str] = {}
    for idx in range(N_CHUNKS):
        if not any(chunk_bytes(store.planes[p], idx).count(0) != CHUNK_BYTES for p in PLANES):
            continue  # nothing recorded in this chunk
        d = chunk_digest(store, idx)
        if full or synced.get(str(idx)) != d:
            out[idx] = d
    return out


def build_request(store: ColorCellStore, idxs: list[int]) -> dict:
    chunks = []
    for idx in idxs:
        entry: dict[str, Any] = {"idx": idx}
        for p in PLANES:
            raw = chunk_bytes(store.planes[p], idx)
            if raw.count(0) != CHUNK_BYTES:  # skip empty planes entirely
                entry[p] = chunk_pack(raw)
        chunks.append(entry)
    return {"space": SPACE_ID, "version": SPACE_VERSION, "enc": "zlib", "chunks": chunks}


def is_due(st: dict, clips_since: int, now: float) -> bool:
    last = float(st.get("last_attempt") or 0.0)
    elapsed = now - last
    if elapsed < _env_float("COLOR_SYNC_MIN_GAP_S", 300.0):
        return False
    if elapsed >= _env_float("COLOR_SYNC_INTERVAL_S", 3600.0):
        return True
    return clips_since >= _env_float("COLOR_SYNC_EVERY_CLIPS", 2000.0)


def maybe_sync(
    store: ColorCellStore,
    api_base: str,
    *,
    clips_done: int = 0,
    force: bool = False,
    now: float | None = None,
    post: Callable[..., dict] | None = None,
) -> dict:
    """Push changed chunks if a sync is due. Always returns a status dict; never raises."""
    t = time.time() if now is None else now
    try:
        if not sync_enabled():
            return {"status": "disabled"}
        if not api_base:
            return {"status": "no_api"}
        if post is None:
            from ..api_client import api_post, free_tier_cooldown_remaining

            if free_tier_cooldown_remaining() > 0:
                return {"status": "cooldown", "remaining_s": round(free_tier_cooldown_remaining())}
            post = api_post
        lock = _FileLock(store.dir / "sync.lock", timeout=0.2, stale=900.0)
        try:
            lock.__enter__()
        except TimeoutError:
            return {"status": "busy"}
        try:
            return _sync_locked(store, api_base, clips_done, force, t, post)
        finally:
            lock.__exit__(None, None, None)
    except Exception as e:  # sync is best-effort
        logger.warning("color sync failed: %s", e)
        return {"status": "error", "error": str(e)[:200]}


def _sync_locked(store: ColorCellStore, api_base: str, clips_done: int, force: bool, t: float, post: Callable[..., dict]) -> dict:
    st = load_state(store)
    st["clips_since"] = int(st.get("clips_since") or 0) + int(clips_done)
    if not force:
        if t < float(st.get("backoff_until") or 0.0):
            _save_state(store, st)
            return {"status": "backoff", "reason": st.get("backoff_reason"), "remaining_s": round(float(st["backoff_until"]) - t)}
        if not is_due(st, st["clips_since"], t):
            _save_state(store, st)
            return {"status": "not_due", "clips_since": st["clips_since"]}
    store.refresh()  # other containers' bits (their planes are on the shared volume)
    full = force or (t - float(st.get("last_full") or 0.0) >= FULL_RESEND_S)
    todo = changed_chunks(store, st, full=full)
    st["last_attempt"] = t
    if not todo:
        st["clips_since"] = 0
        _save_state(store, st)
        return {"status": "nothing_changed", "chunks_sent": 0}

    cap = max(1, min(N_CHUNKS, int(_env_float("COLOR_SYNC_MAX_CHUNKS", float(N_CHUNKS)))))
    idxs = sorted(todo)[:cap]
    digests = dict(st.get("digests") or {})
    out: dict[str, Any] = {"status": "synced", "chunks_sent": 0, "requests": 0, "rows_written": 0, "new_bits": {"observed": 0, "verified": 0, "declared": 0}}
    for i in range(0, len(idxs), CHUNKS_PER_REQUEST):
        batch = idxs[i:i + CHUNKS_PER_REQUEST]
        try:
            res = post(api_base, PUSH_PATH, build_request(store, batch), timeout=120)
        except Exception as e:  # APIError or network: keep digests so the batch is retried next time
            code = getattr(e, "status_code", None)
            body = getattr(e, "body", "") or ""
            if code == 409 or "version_mismatch" in body:
                st["backoff_until"], st["backoff_reason"] = t + VERSION_BACKOFF_S, "version_mismatch"
                out["status"] = "version_mismatch"
            else:
                out["status"], out["error"] = "error", str(e)[:200]
            break
        out["requests"] += 1
        if not isinstance(res, dict) or res.get("recorded") is not True:
            if isinstance(res, dict) and res.get("reason") == "table_missing":
                st["backoff_until"], st["backoff_reason"] = t + TABLE_MISSING_BACKOFF_S, "table_missing"
                out["status"] = "table_missing"
            else:
                out["status"] = "not_recorded"  # degraded / db full: api_client already started the cooldown
            break
        for idx in batch:
            digests[str(idx)] = todo[idx]
        out["chunks_sent"] += len(batch)
        out["rows_written"] += int(res.get("rows_written") or 0)
        for k, v in (res.get("new_bits") or {}).items():
            if k in out["new_bits"]:
                out["new_bits"][k] += int(v or 0)
    st["digests"] = digests
    if out["status"] == "synced":
        st["clips_since"] = 0
        st["last_ok"] = t
        if full:
            st["last_full"] = t
        if len(todo) > len(idxs):
            out["deferred_chunks"] = len(todo) - len(idxs)  # sent on the next sync
    _save_state(store, st)
    return out


def fetch_remote_report(api_base: str, *, per_chunk: bool = False, get: Callable[..., dict] | None = None) -> dict | None:
    """The Worker's cached coverage report (counts only), or None when unreachable."""
    try:
        if get is None:
            from ..api_client import api_get

            get = api_get
        return get(api_base, REPORT_PATH + ("?chunks=1" if per_chunk else ""), timeout=30)
    except Exception as e:
        logger.debug("color sync: report unavailable: %s", e)
        return None
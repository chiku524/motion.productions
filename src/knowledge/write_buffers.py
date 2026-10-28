"""
Local write buffers: aggregate before anything touches D1.

Every row the Worker writes counts against Cloudflare's free 100k rows/day, and index entries count too, so
the cheapest write is the one that is merged into another or never sent. These buffers sit between the loops
and ``api_client`` (which enforces the shared daily budget, see ``write_budget.py``):

* ``DiscoverySpool``      - discoveries merged by identity with summed ``count_delta``; flushed novel-first
                            (colors, sound, motion, then the rest) on an interval, in chunks, only while the
                            budget allows. Whatever is denied or fails stays in the spool (persisted), so a
                            budget-exhausted container keeps working locally and flushes after the reset.
* ``LinguisticCoalescer`` - ``linguistic_registry`` bumps merged by (domain, span) with summed counts; unseen
                            spans first; one batched POST per interval.
* ``InterpretationOutbox``- an interpretation is POSTed only if its prompt AND instruction shape are new locally;
                            everything else lands in a local JSONL.

State lives under ``WRITE_BUFFER_DIR`` (default ``knowledge/write_buffer/``), one file per container name, written
atomically. Nothing in here raises into a loop.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Flush order: the discoveries that grow the registries (colors, sound, motion) go first when the budget is short.
CATEGORY_RANK = {
    "static_colors": 0, "colors": 0, "static_sound": 1, "motion": 2, "blends": 3, "narrative": 4,
}
_DEFAULT_RANK = 3
MAX_COUNT_DELTA = 1000  # the Worker clamps to the same value


def _env_float(name: str, default: float) -> float:
    try:
        raw = (os.environ.get(name) or "").strip()
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, default))


def buffer_dir() -> Path:
    env = (os.environ.get("WRITE_BUFFER_DIR") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent / "knowledge" / "write_buffer"


def _container_name() -> str:
    from .write_budget import budget_name
    return budget_name()


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":"), default=str), encoding="utf-8")
    os.replace(tmp, path)


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _h(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def _clamp_delta(n: Any) -> int:
    try:
        return max(1, min(MAX_COUNT_DELTA, int(n)))
    except (TypeError, ValueError):
        return 1


# =============================================================================================================
# Discoveries
# =============================================================================================================
def discovery_identity(category: str, aspect: str | None, item: Any) -> str:
    """Stable identity of one discovery: what the Worker would upsert onto the same row."""
    if isinstance(item, dict):
        if item.get("key") is not None:
            ident = str(item["key"])
        elif category == "blends" and "output" in item:
            ident = f"{item.get('domain', '')}|{json.dumps(item.get('output'), sort_keys=True, default=str)}"
        elif item.get("name") is not None:
            ident = str(item["name"])
        else:
            ident = json.dumps(item, sort_keys=True, default=str)
    else:
        ident = str(item)
    return f"{category}|{aspect or ''}|{ident}"


class DiscoverySpool:
    """Persistent merge/dedupe buffer for ``/api/knowledge/discoveries`` payloads."""

    def __init__(
        self,
        name: str | None = None,
        *,
        flush_interval: float | None = None,
        flush_max_items: int | None = None,
        max_spool_items: int | None = None,
        path: Path | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.name = name or _container_name()
        self.clock = clock
        self.flush_interval = _env_float("DISCOVERY_FLUSH_INTERVAL_S", 0.0) if flush_interval is None else flush_interval
        self.flush_max_items = _env_int("DISCOVERY_FLUSH_MAX_ITEMS", 72) if flush_max_items is None else flush_max_items
        self.max_spool_items = _env_int("DISCOVERY_SPOOL_MAX_ITEMS", 5000) if max_spool_items is None else max_spool_items
        self.path = path or buffer_dir() / f"{self.name}.discoveries.json"
        self._lock = threading.RLock()
        data = _load(self.path, {})
        self._entries: dict[str, dict[str, Any]] = data.get("entries", {}) if isinstance(data, dict) else {}
        self._last_flush: float = float(data.get("last_flush", 0.0)) if isinstance(data, dict) else 0.0
        if self._last_flush <= 0:
            self._last_flush = self.clock()  # first interval starts now, not at the epoch
        self._seq = int(data.get("seq", 0)) if isinstance(data, dict) else 0

    # -- state -------------------------------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._entries)

    def _save(self) -> None:
        try:
            _atomic_write(self.path, {"entries": self._entries, "last_flush": self._last_flush, "seq": self._seq})
        except OSError as e:
            logger.warning("discovery spool not persisted: %s", e)

    def add(self, discoveries: dict[str, Any]) -> int:
        """Merge a discoveries payload into the spool (summing ``count_delta`` per identity). Returns items added."""
        from .remote_sync import _flatten_discovery_items

        n = 0
        with self._lock:
            for category, aspect, item in _flatten_discovery_items(discoveries):
                ident = discovery_identity(category, aspect, item)
                delta = _clamp_delta(item.get("count_delta", 1) if isinstance(item, dict) else 1)
                cur = self._entries.get(ident)
                if cur is None:
                    self._seq += 1
                    body = dict(item) if isinstance(item, dict) else item
                    if isinstance(body, dict):
                        body.pop("count_delta", None)
                    self._entries[ident] = {"cat": category, "aspect": aspect, "item": body, "delta": delta, "seq": self._seq}
                else:
                    cur["delta"] = _clamp_delta(cur["delta"] + delta)
                    if isinstance(item, dict) and isinstance(cur["item"], dict):
                        fresh = {k: v for k, v in item.items() if k != "count_delta"}
                        cur["item"] = {**cur["item"], **fresh}
                n += 1
            self._trim()
            self._save()
        return n

    def _rank(self, e: dict[str, Any]) -> tuple:
        return (CATEGORY_RANK.get(e["cat"], _DEFAULT_RANK), -int(e["delta"]), int(e["seq"]))

    def _trim(self) -> None:
        over = len(self._entries) - self.max_spool_items
        if over > 0:  # drop the least valuable (lowest rank, then smallest count, then oldest)
            worst = sorted(self._entries.items(), key=lambda kv: self._rank(kv[1]), reverse=True)[:over]
            for ident, _ in worst:
                self._entries.pop(ident, None)
            logger.warning("discovery spool full: dropped %d lowest-priority items", over)

    def ordered(self) -> list[tuple[str, dict[str, Any]]]:
        return sorted(self._entries.items(), key=lambda kv: self._rank(kv[1]))

    # -- flushing ----------------------------------------------------------------------------------------
    def due(self, force: bool = False) -> bool:
        if not self._entries:
            return False
        if force or self.flush_interval <= 0:
            return True
        if len(self._entries) >= self.flush_max_items:
            return True
        return self.clock() - self._last_flush >= self.flush_interval

    @staticmethod
    def _payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for e in entries:
            item = e["item"]
            if isinstance(item, dict) and e["delta"] > 1:
                item = {**item, "count_delta": int(e["delta"])}
            if e["cat"] == "narrative":
                payload.setdefault("narrative", {}).setdefault(e["aspect"] or "themes", []).append(item)
            else:
                payload.setdefault(e["cat"], []).append(item)
        return payload

    def flush(
        self,
        api_base: str,
        *,
        job_id: str | None = None,
        force: bool = False,
        chunk_size: int | None = None,
        max_chunks: int = 12,
        pause: float = 0.0,
        poster: Callable[..., dict] | None = None,
    ) -> dict[str, Any]:
        """Send due items in priority order, chunk by chunk, stopping at the first denial/failure.

        Returns ``{"status", "results", "posted", "deferred", "chunks", "skipped": reason|None}``. Items that were
        not acknowledged stay in the spool. ``job_id`` rides on the last chunk only when the spool drains fully.
        """
        from ..api_client import APIError, WriteBudgetSkipped, api_request_with_retry
        from .remote_sync import _flatten_discovery_items, _max_items, _post_stats

        post = poster or api_request_with_retry
        out: dict[str, Any] = {"status": "recorded", "results": {}, "posted": 0, "deferred": 0, "chunks": 0, "skipped": None}
        with self._lock:
            if not self.due(force):
                out["deferred"] = len(self._entries)
                out["skipped"] = "not_due" if self._entries else None
                return out
            size = chunk_size or _max_items()
            order = self.ordered()
            sent_all = True
            chunks = 0
            idx = 0
            while idx < len(order) and chunks < max_chunks:
                part = order[idx: idx + size]
                payload = self._payload([e for _, e in part])
                last = idx + size >= len(order)
                if job_id and last:
                    payload["job_id"] = job_id
                if chunks and pause > 0:
                    time.sleep(pause)
                try:
                    resp = post(api_base, "POST", "/api/knowledge/discoveries", data=payload, timeout=90, max_retries=8)
                except WriteBudgetSkipped:
                    out["skipped"] = "budget"
                    sent_all = False
                    break
                except APIError as e:
                    logger.warning("discoveries flush failed (%s): %s; %d items stay buffered", e.status_code, e, len(order) - idx)
                    out["skipped"] = f"error:{e.status_code}"
                    sent_all = False
                    break
                chunks += 1
                n_part = len(part)
                done = part
                if isinstance(resp, dict) and resp.get("truncated"):
                    processed = max(0, int(resp.get("items_processed") or 0))
                    flat = _flatten_discovery_items(self._payload([e for _, e in part]))
                    done = part[: min(processed, len(flat), n_part)]
                    sent_all = False
                for ident, _ in done:
                    self._entries.pop(ident, None)
                out["posted"] += len(done)
                _post_stats["items"] += len(done)
                _post_stats["requests"] += 1
                for k, v in ((resp or {}).get("results") or {}).items():
                    out["results"][k] = out["results"].get(k, 0) + v
                idx += n_part if len(done) == n_part else len(done)
                if len(done) < n_part:
                    break
            if idx < len(order):
                sent_all = False
            out["chunks"] = chunks
            out["deferred"] = len(self._entries)
            if out["posted"] or not self._entries:
                self._last_flush = self.clock()
            elif out["skipped"] is None:
                self._last_flush = self.clock()
            out["job_id_sent"] = bool(job_id and sent_all and chunks)
            self._save()
        return out

    def pending_counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for e in self._entries.values():
            c[e["cat"]] = c.get(e["cat"], 0) + 1
        return c


# =============================================================================================================
# Linguistic registry bumps
# =============================================================================================================
class LinguisticCoalescer:
    """Merge ``linguistic_registry`` bumps per (domain, span) with summed counts; one batched upsert per interval."""

    SEEN_CAP = 100_000

    def __init__(
        self,
        name: str | None = None,
        *,
        flush_interval: float | None = None,
        flush_max_items: int | None = None,
        path: Path | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.name = name or _container_name()
        self.clock = clock
        self.flush_interval = _env_float("LINGUISTIC_FLUSH_INTERVAL_S", 0.0) if flush_interval is None else flush_interval
        self.flush_max_items = _env_int("LINGUISTIC_FLUSH_MAX_ITEMS", 40) if flush_max_items is None else flush_max_items
        self.path = path or buffer_dir() / f"{self.name}.linguistic.json"
        self._lock = threading.RLock()
        data = _load(self.path, {})
        self._pending: dict[str, dict[str, Any]] = data.get("pending", {}) if isinstance(data, dict) else {}
        self._seen: set[str] = set(data.get("seen", [])) if isinstance(data, dict) else set()
        self._last_flush: float = float(data.get("last_flush", 0.0)) if isinstance(data, dict) else 0.0
        if self._last_flush <= 0:
            self._last_flush = self.clock()  # first interval starts now, not at the epoch

    def __len__(self) -> int:
        return len(self._pending)

    def _save(self) -> None:
        try:
            _atomic_write(self.path, {"pending": self._pending, "seen": sorted(self._seen), "last_flush": self._last_flush})
        except OSError as e:
            logger.warning("linguistic buffer not persisted: %s", e)

    @staticmethod
    def _key(item: dict[str, Any]) -> str:
        return f"{str(item.get('domain', '')).strip().lower()}|{str(item.get('span', '')).strip().lower()}"

    def add(self, items: list[dict[str, Any]]) -> int:
        n = 0
        with self._lock:
            for it in items:
                if not isinstance(it, dict) or not it.get("span") or not it.get("canonical") or not it.get("domain"):
                    continue
                k = self._key(it)
                cnt = _clamp_delta(it.get("count", 1))
                cur = self._pending.get(k)
                if cur is None:
                    self._pending[k] = {
                        "span": it["span"], "canonical": it["canonical"], "domain": it["domain"],
                        "variant_type": it.get("variant_type", "synonym"), "count": cnt,
                    }
                else:
                    cur["count"] = _clamp_delta(cur["count"] + cnt)
                n += 1
            self._save()
        return n

    def due(self, force: bool = False) -> bool:
        if not self._pending:
            return False
        if force or self.flush_interval <= 0 or len(self._pending) >= self.flush_max_items:
            return True
        return self.clock() - self._last_flush >= self.flush_interval

    def flush(self, api_base: str, *, force: bool = False, batch_max: int = 100,
              poster: Callable[..., dict] | None = None) -> dict[str, Any]:
        from ..api_client import APIError, WriteBudgetSkipped, api_request_with_retry

        post = poster or api_request_with_retry
        out: dict[str, Any] = {"inserted": 0, "updated": 0, "queued": 0, "skipped": None}
        with self._lock:
            if not self.due(force):
                out["queued"] = len(self._pending)
                return out
            # unseen spans (a real INSERT, 5 rows) before known ones (a 1-row count bump)
            order = sorted(self._pending.items(), key=lambda kv: (kv[0] in self._seen, -int(kv[1]["count"])))
            for i in range(0, len(order), batch_max):
                part = order[i: i + batch_max]
                try:
                    resp = post(api_base, "POST", "/api/linguistic-registry/batch",
                                data={"items": [e for _, e in part]}, timeout=30)
                except WriteBudgetSkipped:
                    out["skipped"] = "budget"
                    break
                except APIError as e:
                    logger.warning("linguistic flush failed (%s): %s", e.status_code, e)
                    out["skipped"] = f"error:{e.status_code}"
                    break
                for k, _ in part:
                    self._pending.pop(k, None)
                    if len(self._seen) < self.SEEN_CAP:
                        self._seen.add(k)
                out["inserted"] += int((resp or {}).get("inserted", 0))
                out["updated"] += int((resp or {}).get("updated", 0))
            if out["skipped"] is None:
                self._last_flush = self.clock()
            out["queued"] = len(self._pending)
            self._save()
        return out


# =============================================================================================================
# Interpretations
# =============================================================================================================
def instruction_signature(instruction: Any) -> str:
    """Shape of an interpretation, ignoring free text: two prompts that parse to the same instruction are one."""
    def norm(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 2)
        if isinstance(v, dict):
            return {k: norm(x) for k, x in sorted(v.items()) if k not in ("prompt", "raw_prompt", "original_prompt", "id")}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v
    return _h(json.dumps(norm(instruction), sort_keys=True, default=str))


class InterpretationOutbox:
    """Record an interpretation in D1 only if it is novel by a local check; keep the rest in a local JSONL."""

    SEEN_CAP = 200_000

    def __init__(
        self,
        name: str | None = None,
        *,
        flush_interval: float | None = None,
        flush_max_items: int | None = None,
        path: Path | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.name = name or _container_name()
        self.clock = clock
        self.flush_interval = _env_float("INTERPRET_FLUSH_INTERVAL_S", 0.0) if flush_interval is None else flush_interval
        self.flush_max_items = _env_int("INTERPRET_FLUSH_MAX_ITEMS", 10) if flush_max_items is None else flush_max_items
        self.path = path or buffer_dir() / f"{self.name}.interpretations.json"
        self.jsonl_path = self.path.with_name(f"{self.name}.interpretations.local.jsonl")
        self._lock = threading.RLock()
        data = _load(self.path, {})
        self._prompts: set[str] = set(data.get("prompts", [])) if isinstance(data, dict) else set()
        self._sigs: set[str] = set(data.get("sigs", [])) if isinstance(data, dict) else set()
        self._outbox: list[dict[str, Any]] = data.get("outbox", []) if isinstance(data, dict) else []
        self._last_flush: float = float(data.get("last_flush", 0.0)) if isinstance(data, dict) else 0.0
        if self._last_flush <= 0:
            self._last_flush = self.clock()  # first interval starts now, not at the epoch

    def __len__(self) -> int:
        return len(self._outbox)

    def _save(self) -> None:
        try:
            _atomic_write(self.path, {
                "prompts": sorted(self._prompts), "sigs": sorted(self._sigs),
                "outbox": self._outbox, "last_flush": self._last_flush,
            })
        except OSError as e:
            logger.warning("interpretation outbox not persisted: %s", e)

    def _to_jsonl(self, item: dict[str, Any]) -> None:
        try:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self.jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": int(self.clock()), **item}, default=str) + "\n")
        except OSError as e:
            logger.warning("local interpretation log not written: %s", e)

    def record(self, prompt: str, instruction: Any, source: str = "generate") -> str:
        """Returns ``"dropped"`` (prompt already seen), ``"queued"`` (novel, will be POSTed) or ``"local"`` (JSONL only)."""
        prompt = (prompt or "").strip()
        if not prompt:
            return "dropped"
        ph = _h(prompt.lower())
        sig = instruction_signature(instruction)
        item = {"prompt": prompt, "instruction": instruction, "source": source}
        with self._lock:
            if ph in self._prompts:
                return "dropped"
            novel = sig not in self._sigs
            if len(self._prompts) < self.SEEN_CAP:
                self._prompts.add(ph)
            if len(self._sigs) < self.SEEN_CAP:
                self._sigs.add(sig)
            if novel:
                self._outbox.append(item)
            else:
                self._to_jsonl(item)
            self._save()
        return "queued" if novel else "local"

    def seen(self, prompt: str) -> bool:
        return _h((prompt or "").strip().lower()) in self._prompts

    def due(self, force: bool = False) -> bool:
        if not self._outbox:
            return False
        if force or self.flush_interval <= 0 or len(self._outbox) >= self.flush_max_items:
            return True
        return self.clock() - self._last_flush >= self.flush_interval

    def flush(self, api_base: str, *, force: bool = False, batch_max: int = 50,
              poster: Callable[..., dict] | None = None) -> dict[str, Any]:
        from ..api_client import APIError, WriteBudgetSkipped, api_request_with_retry

        post = poster or api_request_with_retry
        out: dict[str, Any] = {"inserted": 0, "queued": 0, "skipped": None}
        with self._lock:
            if not self.due(force):
                out["queued"] = len(self._outbox)
                return out
            while self._outbox:
                part = self._outbox[:batch_max]
                try:
                    resp = post(api_base, "POST", "/api/interpretations/batch", data={"items": part}, timeout=30)
                except WriteBudgetSkipped:
                    out["skipped"] = "budget"
                    break
                except APIError as e:
                    logger.warning("interpretation flush failed (%s): %s", e.status_code, e)
                    out["skipped"] = f"error:{e.status_code}"
                    break
                del self._outbox[: len(part)]
                out["inserted"] += int((resp or {}).get("inserted", 0))
            if out["skipped"] is None:
                self._last_flush = self.clock()
            out["queued"] = len(self._outbox)
            self._save()
        return out


# =============================================================================================================
# Process-wide instances + one call for the loops
# =============================================================================================================
_instances: dict[str, Any] = {}
_instances_lock = threading.Lock()


def _get(kind: str, factory: Callable[[], Any]) -> Any:
    key = f"{kind}|{buffer_dir()}|{_container_name()}"
    with _instances_lock:
        if key not in _instances:
            _instances[key] = factory()
        return _instances[key]


def get_discovery_spool(name: str | None = None) -> DiscoverySpool:
    return _get(f"disc:{name}", lambda: DiscoverySpool(name))


def get_linguistic_coalescer() -> LinguisticCoalescer:
    return _get("ling", LinguisticCoalescer)


def get_interpretation_outbox() -> InterpretationOutbox:
    return _get("interp", InterpretationOutbox)


def reset_buffers() -> None:
    with _instances_lock:
        _instances.clear()


def flush_all(api_base: str, *, force: bool = False) -> dict[str, Any]:
    """Flush every buffer that is due (called at loop start/end). Never raises."""
    out: dict[str, Any] = {}
    try:
        out["discoveries"] = get_discovery_spool().flush(api_base, force=force)
    except Exception as e:
        logger.warning("discovery flush skipped: %s", e)
    try:
        out["linguistic"] = get_linguistic_coalescer().flush(api_base, force=force)
    except Exception as e:
        logger.warning("linguistic flush skipped: %s", e)
    try:
        out["interpretations"] = get_interpretation_outbox().flush(api_base, force=force)
    except Exception as e:
        logger.warning("interpretation flush skipped: %s", e)
    return out


def idle_when_exhausted() -> float:
    """Seconds a loop should sleep because its daily D1 allowance is used up (0 = keep working locally).

    ``WRITE_BUDGET_SLEEP_WHEN_EXHAUSTED_S`` (default 0): rendering/extraction keep running against the local
    registry either way; sleeping only saves CPU. A shared back-off (Worker degraded / 429) always waits out
    the remaining Retry-After (capped by the same setting when it is > 0).
    """
    cap = _env_float("WRITE_BUDGET_SLEEP_WHEN_EXHAUSTED_S", 0.0)
    if cap <= 0:
        return 0.0
    try:
        from .write_budget import get_budget
        b = get_budget()
        if not b.enabled:
            return 0.0
        if b.backoff_remaining() > 0:
            return min(cap, b.backoff_remaining())
        if b.remaining("high") <= 0:
            return min(cap, b.seconds_until_reset())
    except Exception:
        return 0.0
    return 0.0

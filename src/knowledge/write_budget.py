"""
Shared hard daily D1 write budget for every motion.productions container.

Cloudflare's free D1 plan allows 100k *rows written* per UTC day (index entries count). The Worker is
the only thing that can measure that exactly, but a Worker-side counter would itself cost D1/KV writes,
so the budget is enforced on the client: every container shares one small JSON ledger on the mounted
``knowledge/`` volume and asks it before each non-GET API call.

* ``D1_DAILY_WRITE_BUDGET`` (default 50000 REAL rows/day = a hard cap of 50% of the 100k free limit, <= 0 disables
  the gate) is the total for ALL containers; the other 50% is headroom for Worker-side retention, web users and
  estimate error.  Real means index entries included: the Worker reports D1's own ``meta.rows_written`` on every
  write route, and that number (not an estimate) is what the ledger books.
* It is split by weight (``D1_BUDGET_WEIGHTS``): explorer 30, balanced 30, interpret 15, sound 10, other 5.
  Any container not listed (webjobs, procedural-render, exploiter, ...) shares the ``other`` pool.
* A container's name is ``D1_BUDGET_NAME`` (else ``LOOP_METRICS_NAME``, else derived from the start script).
* ``reserve()`` charges a worst-case estimate before a POST; ``record_response()`` replaces it with the Worker's
  reported ``rows_written`` afterwards.  A response WITHOUT ``rows_written`` (old Worker, new unreported route)
  keeps the estimate plus a 25% surcharge and counts as *unreported*; ``UNREPORTED_TRIP`` unreported answers in a
  row mean the estimates cannot be trusted, so the ledger fails closed: it refuses every post except one probe per
  ``PROBE_SECONDS`` until a response reports ``rows_written`` again.
* Two priorities: ``high`` (novel discoveries) may use the whole allowance; ``low`` (job/learning/interpretation
  logs, count bumps) only the first ``D1_BUDGET_LOW_FRACTION`` (0.5) of it, paced across the day, so logs can
  never starve discoveries.
* The ledger resets at 00:00 UTC. It also carries one shared back-off deadline (Worker X-Degraded / 429 / D1
  errors => every container stops posting for ``Retry-After``, default 900 s).

Nothing here raises into a loop. If the ledger cannot be read or locked the gate fails closed (the container
keeps working locally and retries on the next call): wasting a few minutes is cheaper than blowing the free tier.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)


def _now() -> float:
    return time.time()  # looked up at call time so a simulated clock (dry-run harness) can replace time.time

DEFAULT_DAILY_BUDGET = 50000  # real D1 rows/day: a hard 50% cap of the 100k free limit
UNREPORTED_SURCHARGE = 0.25  # extra charge on an estimate nobody confirmed (index writes / retries we cannot see)
UNREPORTED_TRIP = 10  # consecutive unreported answers after which the ledger stops trusting its estimates
PROBE_SECONDS = 300.0  # while untrusted, one probe post is let through this often to detect a fixed Worker
DEFAULT_WEIGHTS: dict[str, float] = {"explorer": 30, "balanced": 30, "interpret": 15, "sound": 10, "other": 5}
OTHER = "other"
DEFAULT_LOW_FRACTION = 0.5
DEFAULT_PACE_BURST = 0.15
DEFAULT_BACKOFF_SECONDS = 900.0
HIGH = "high"
LOW = "low"

# Containers whose posts are user-facing or tiny: all of their writes count as high priority.
HIGH_ALWAYS = {"webjobs", "procedural-render"}

# ---------------------------------------------------------------------------------------------------------
# Row-cost model. D1 counts one row per table row written plus one per index entry written, so an INSERT costs
# 1 + (#indexes incl. PK/UNIQUE autoindexes); an UPDATE of an indexed column rewrites that index entry (old + new).
# The per-table index counts are DERIVED FROM THE MIGRATIONS and pinned by tests/test_write_budget_calibration.py
# (PRAGMA index_list over every migrations/*.sql), then checked against D1 itself with the Worker harness
# (cloudflare/test/writeBudget.test.mjs). Estimates are worst case (every item is new); the Worker's reported
# ``rows_written`` replaces them in record_response().
# ---------------------------------------------------------------------------------------------------------
NAME_RESERVE_ROWS = 3  # name_reserve: row + PK autoindex, ~1.3 reserved per named item, rounded up
INSERT_ROWS: dict[str, int] = {
    "jobs": 5,                 # row + PK + idx_status + idx_created_at + idx_workflow_type
    "learning_runs": 4,        # row + PK + job_id + created_at
    "interpretations": 4,      # row + PK + idx_status + idx_updated_at
    "linguistic_registry": 5,  # row + PK + UNIQUE(span,domain) + domain + canonical
    "static_colors": 7 + NAME_RESERVE_ROWS,   # row + 6 indexes (7), + the reserved display name
    "static_sound": 5,
    "learned_blends": 4 + 2 * NAME_RESERVE_ROWS,  # row + 3 indexes; measured 1.7 names reserved per blend
    "learned_colors": 4 + NAME_RESERVE_ROWS,
    "learned_profile": 4,      # learned_motion/lighting/... : row + PK + UNIQUE(profile_key) + created_at
    "narrative": 5,            # row + PK + UNIQUE(aspect, entry_key) + aspect + created_at
    "discovery_runs": 3,
    "color_coverage": 2,       # one row per changed 64 KiB chunk, no secondary index (worst case +1)
    "events": 5,               # row + 4 indexes (the old estimate of 4 under-counted every event)
    "interpret_queue": 4,      # POST /api/interpret/queue: an interpretations insert
}
# UPDATEs: only the touched columns' indexes count. jobs complete: status + completed_at; interpret PATCH: status.
UPDATE_ROWS = {"jobs_complete": 2, "jobs_upload": 3, "interpretation_patch": 3, "count_bump": 1}
UNKNOWN_WRITE_ROWS = 5  # any other non-GET: a typical 1 + 4 indexes insert

_DISCOVERY_CATEGORY_TABLE = {
    "static_colors": "static_colors", "static_sound": "static_sound", "colors": "learned_colors", "blends": "learned_blends",
}
_ID = r"[A-Za-z0-9_-]+"


def _item_key(item: Any) -> str:
    if isinstance(item, Mapping):
        k = item.get("key")
        if k is not None:
            return str(k)
        return json.dumps(item, sort_keys=True, default=str)[:200]
    return str(item)


def estimate_discoveries_rows(data: Mapping[str, Any] | None) -> int:
    """Worst-case rows for one /api/knowledge/discoveries body (unique keys only: the Worker dedupes a batch)."""
    if not isinstance(data, Mapping):
        return INSERT_ROWS["learned_profile"]
    total = 0
    for cat, items in data.items():
        if cat == "job_id":
            continue
        if cat == "narrative" and isinstance(items, Mapping):
            for aspect, arr in items.items():
                if isinstance(arr, list):
                    total += INSERT_ROWS["narrative"] * len({(aspect, _item_key(i)) for i in arr})
            continue
        if not isinstance(items, list):
            continue
        table = _DISCOVERY_CATEGORY_TABLE.get(cat, "learned_profile")
        total += INSERT_ROWS[table] * len({_item_key(i) for i in items})
    if isinstance(data.get("job_id"), str) and data.get("job_id"):
        total += INSERT_ROWS["discovery_runs"]
    return total


def estimate_rows(method: str, path: str, data: Mapping[str, Any] | None = None) -> tuple[int, str]:
    """(worst-case D1 rows written, priority) for one API call. GETs and KV-only writes cost 0."""
    method = (method or "GET").upper()
    path = (path or "").split("?", 1)[0]
    if method in ("GET", "HEAD", "OPTIONS"):
        return 0, HIGH
    if path.startswith("/api/knowledge/discoveries"):
        return estimate_discoveries_rows(data), HIGH
    if path.startswith("/api/coverage/color"):
        n = len((data or {}).get("chunks") or (data or {}).get("rows") or []) if isinstance(data, Mapping) else 0
        return INSERT_ROWS["color_coverage"] * min(max(n, 1), 32), HIGH
    if path == "/api/loop/state":
        return 0, LOW  # KV only
    if path == "/api/jobs":
        return INSERT_ROWS["jobs"], LOW
    if re.fullmatch(rf"/api/jobs/{_ID}/complete", path):
        return UPDATE_ROWS["jobs_complete"], LOW
    if re.fullmatch(rf"/api/jobs/{_ID}/upload", path):
        return UPDATE_ROWS["jobs_upload"], LOW
    if path == "/api/interpret/queue":
        return INSERT_ROWS["interpret_queue"], LOW
    if re.fullmatch(rf"/api/interpret/{_ID}", path):
        return UPDATE_ROWS["interpretation_patch"], LOW
    if path == "/api/learning":
        return INSERT_ROWS["learning_runs"], LOW
    if path == "/api/interpretations/batch" or path == "/api/interpretations/backfill":
        items = (data or {}).get("items") if isinstance(data, Mapping) else None
        return INSERT_ROWS["interpretations"] * max(1, len(items) if isinstance(items, list) else 1), LOW
    if path == "/api/interpretations":
        return INSERT_ROWS["interpretations"], LOW
    if path.startswith("/api/interpretations/"):
        return UPDATE_ROWS["interpretation_patch"], LOW
    if path.startswith("/api/linguistic-registry"):
        items = (data or {}).get("items") if isinstance(data, Mapping) else None
        n = len(items) if isinstance(items, list) else 1
        return INSERT_ROWS["linguistic_registry"] * max(1, n), LOW
    if path == "/api/events":
        return INSERT_ROWS["events"], LOW
    return UNKNOWN_WRITE_ROWS, LOW


# ---------------------------------------------------------------------------------------------------------
# Naming / configuration
# ---------------------------------------------------------------------------------------------------------
_SCRIPT_NAMES = {
    "sound_loop": "sound", "interpret_loop": "interpret", "generate_bridge": "webjobs", "webjobs": "webjobs",
    "procedural_render": "procedural-render",
}


def budget_name() -> str:
    for var in ("D1_BUDGET_NAME", "LOOP_METRICS_NAME"):
        v = (os.environ.get(var) or "").strip()
        if v:
            return re.sub(r"[^A-Za-z0-9_.-]+", "_", v)[:48]
    script = (os.environ.get("WORKER_START_SCRIPT") or "").strip().lower()
    if script in _SCRIPT_NAMES:
        return _SCRIPT_NAMES[script]
    wf = (os.environ.get("LOOP_WORKFLOW_TYPE") or "").strip().lower()
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", wf)[:48] if wf else OTHER


def default_budget_dir() -> Path:
    env = (os.environ.get("WRITE_BUDGET_DIR") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent / "knowledge" / "write_budget"


def daily_budget_from_env() -> int:
    raw = (os.environ.get("D1_DAILY_WRITE_BUDGET") or "").strip().lower()
    if not raw:
        return DEFAULT_DAILY_BUDGET
    if raw in ("off", "none", "unlimited"):
        return 0
    try:
        return int(float(raw))
    except ValueError:
        return DEFAULT_DAILY_BUDGET


def parse_weights(raw: str | None) -> dict[str, float]:
    """``"explorer=30,balanced=30,other=5"`` -> dict; unparsable parts fall back to the defaults."""
    out = dict(DEFAULT_WEIGHTS)
    if not raw:
        return out
    parsed: dict[str, float] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            w = float(v)
        except ValueError:
            continue
        if k.strip() and w >= 0:
            parsed[k.strip()] = w
    if parsed:
        parsed.setdefault(OTHER, DEFAULT_WEIGHTS[OTHER])
        return parsed
    return out


def _float_env(name: str, default: float) -> float:
    try:
        raw = (os.environ.get(name) or "").strip()
        return float(raw) if raw else default
    except ValueError:
        return default


def utc_day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def seconds_into_utc_day(now: float) -> float:
    t = time.gmtime(now)
    return t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec + (now - int(now))


class _FileLock:
    """O_EXCL lock file with stale takeover (same scheme as color_cells._FileLock; no heavy imports)."""

    def __init__(self, path: Path, timeout: float = 10.0, stale: float = 30.0):
        self.path, self.timeout, self.stale = path, timeout, stale
        self._fd: int | None = None

    def __enter__(self) -> "_FileLock":
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        os.unlink(self.path)
                        continue
                except OSError:
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"lock timeout: {self.path}")
                time.sleep(0.01)

    def __exit__(self, *exc: object) -> None:
        try:
            if self._fd is not None:
                os.close(self._fd)
        finally:
            self._fd = None
            try:
                os.unlink(self.path)
            except OSError:
                pass


def _empty_ledger(day: str) -> dict[str, Any]:
    return {
        "version": 1, "day": day, "containers": {}, "backoff_until": 0.0, "backoff_reason": "",
        "calib": {"reported": 0, "unreported": 0, "est_reported": 0, "act_reported": 0, "surcharge": 0},
        "consec_unreported": 0, "probe_after": 0.0,
    }


class WriteBudget:
    """One container's view of the shared ledger. All mutations are read-modify-write under the file lock."""

    def __init__(
        self,
        name: str | None = None,
        directory: str | Path | None = None,
        daily_budget: int | None = None,
        weights: Mapping[str, float] | None = None,
        low_fraction: float | None = None,
        pace_burst: float | None = None,
        clock: Callable[[], float] = _now,
    ):
        self.name = name or budget_name()
        self.dir = Path(directory) if directory else default_budget_dir()
        self.daily_budget = daily_budget_from_env() if daily_budget is None else int(daily_budget)
        self.weights = dict(weights) if weights is not None else parse_weights(os.environ.get("D1_BUDGET_WEIGHTS"))
        self.low_fraction = _float_env("D1_BUDGET_LOW_FRACTION", DEFAULT_LOW_FRACTION) if low_fraction is None else low_fraction
        self.pace_burst = _float_env("D1_BUDGET_PACE_BURST", DEFAULT_PACE_BURST) if pace_burst is None else pace_burst
        self.clock = clock
        self.path = self.dir / "ledger.json"
        self._lock_path = self.dir / "ledger.lock"
        self._mutex = threading.Lock()

    # -- config -------------------------------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self.daily_budget > 0

    def bucket_of(self, name: str) -> str:
        return name if name in self.weights and name != OTHER else OTHER

    def allowance(self, bucket: str | None = None) -> int:
        b = bucket or self.bucket_of(self.name)
        # Weights are percentages; weights that add up to more than 100 are normalised so shares never exceed the budget.
        denom = max(sum(self.weights.values()), 100.0)
        return int(self.daily_budget * self.weights.get(b, self.weights.get(OTHER, 0.0)) / denom)

    def priority_for(self, default: str) -> str:
        return HIGH if self.bucket_of(self.name) == OTHER and self.name in HIGH_ALWAYS else default

    # -- ledger io ----------------------------------------------------------------------------------------
    def _read(self, now: float) -> dict[str, Any]:
        day = utc_day(now)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("day") == day and isinstance(data.get("containers"), dict):
                return data
        except (OSError, ValueError):
            pass
        # New UTC day (or no ledger yet): counters restart. A back-off deadline is a wall-clock time so it survives.
        fresh = _empty_ledger(day)
        try:
            old = json.loads(self.path.read_text(encoding="utf-8"))
            fresh["backoff_until"] = float(old.get("backoff_until") or 0.0)
            fresh["backoff_reason"] = str(old.get("backoff_reason") or "")
            fresh["consec_unreported"] = int(old.get("consec_unreported") or 0)  # trust is not reset by the clock
            fresh["probe_after"] = float(old.get("probe_after") or 0.0)
        except (OSError, ValueError, TypeError):
            pass
        return fresh

    def _write(self, data: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, self.path)

    def _mutate(self, fn: Callable[[dict[str, Any], float], Any]) -> Any:
        with self._mutex, _FileLock(self._lock_path):
            now = self.clock()
            data = self._read(now)
            result = fn(data, now)
            self._write(data)
            return result

    def _entry(self, data: dict[str, Any], name: str | None = None) -> dict[str, Any]:
        return data["containers"].setdefault(
            name or self.name,
            {"used": 0, "posts": 0, "denied_rows": 0, "denied_posts": 0, "first_t": None, "last_t": None},
        )

    def _bucket_used(self, data: dict[str, Any], bucket: str) -> int:
        return sum(int(e.get("used", 0)) for n, e in data["containers"].items() if self.bucket_of(n) == bucket)

    def _total_used(self, data: dict[str, Any]) -> int:
        return sum(int(e.get("used", 0)) for e in data["containers"].values())

    # -- accounting ---------------------------------------------------------------------------------------
    def low_cap(self, now: float) -> float:
        """Rows (as a share of the allowance) low-priority posts may use right now: paced across the UTC day."""
        frac = min(1.0, seconds_into_utc_day(now) / 86400.0 + self.pace_burst)
        return self.allowance() * min(1.0, max(0.0, self.low_fraction)) * frac

    def reserve(self, rows: int, priority: str = HIGH) -> bool:
        """Charge ``rows`` (worst case) to this container. False (and the refusal is recorded) if it does not fit."""
        rows = max(0, int(rows))
        if not self.enabled or rows == 0:
            return True
        priority = self.priority_for(priority)
        bucket = self.bucket_of(self.name)
        allowance = self.allowance(bucket)

        def op(data: dict[str, Any], now: float) -> bool:
            e = self._entry(data)
            used_bucket = self._bucket_used(data, bucket)
            cap = allowance if priority == HIGH else min(allowance, self.low_cap(now))
            ok = used_bucket + rows <= cap and self._total_used(data) + rows <= self.daily_budget
            if ok and int(data.get("consec_unreported") or 0) >= UNREPORTED_TRIP:
                # Untrusted estimates: fail closed, let one probe through per PROBE_SECONDS to see if the Worker reports again.
                if now >= float(data.get("probe_after") or 0.0):
                    data["probe_after"] = now + PROBE_SECONDS
                else:
                    ok = False
            if ok:
                e["used"] = int(e["used"]) + rows
                e["posts"] = int(e["posts"]) + 1
                e["first_t"] = e["first_t"] or now
                e["last_t"] = now
            else:
                e["denied_rows"] = int(e["denied_rows"]) + rows
                e["denied_posts"] = int(e["denied_posts"]) + 1
            return ok

        try:
            return bool(self._mutate(op))
        except Exception as exc:  # fail closed: keep working locally, retry on the next call
            logger.warning("write budget ledger unavailable (%s); holding writes", exc)
            return False

    def settle(self, reserved: int, actual: int | None) -> None:
        """Replace the worst-case charge by the Worker's reported rows (never below 0). No-op without ``actual``."""
        if not self.enabled or actual is None or reserved <= 0:
            return
        delta = int(actual) - int(reserved)
        if delta == 0:
            return

        def op(data: dict[str, Any], now: float) -> None:
            e = self._entry(data)
            e["used"] = max(0, int(e["used"]) + delta)

        try:
            self._mutate(op)
        except Exception as exc:
            logger.debug("write budget settle skipped: %s", exc)

    def record_response(self, reserved: int, actual: int | None) -> None:
        """Book the outcome of a post that reached D1: the Worker's real ``rows_written`` if it sent one, else
        the estimate plus a surcharge, counted as *unreported* (UNREPORTED_TRIP in a row => fail closed)."""
        if not self.enabled or reserved <= 0:
            return

        def op(data: dict[str, Any], now: float) -> None:
            e = self._entry(data)
            calib = data.setdefault("calib", {})
            if actual is not None:
                e["used"] = max(0, int(e["used"]) + int(actual) - int(reserved))
                calib["reported"] = int(calib.get("reported", 0)) + 1
                calib["est_reported"] = int(calib.get("est_reported", 0)) + int(reserved)
                calib["act_reported"] = int(calib.get("act_reported", 0)) + int(actual)
                data["consec_unreported"] = 0
            else:
                extra = int(math.ceil(reserved * UNREPORTED_SURCHARGE))
                e["used"] = int(e["used"]) + extra
                calib["unreported"] = int(calib.get("unreported", 0)) + 1
                calib["surcharge"] = int(calib.get("surcharge", 0)) + extra
                data["consec_unreported"] = int(data.get("consec_unreported") or 0) + 1
                if data["consec_unreported"] == UNREPORTED_TRIP:
                    logger.warning("write budget: %d answers in a row without rows_written; estimates untrusted, posting paused (1 probe / %.0fs)", UNREPORTED_TRIP, PROBE_SECONDS)

        try:
            self._mutate(op)
        except Exception as exc:
            logger.debug("write budget record skipped: %s", exc)

    def trust(self) -> dict[str, Any]:
        """Calibration summary for metrics: how well the estimates matched the Worker's real rows today."""
        data = self.snapshot()
        c = dict(data.get("calib") or {})
        est, act = int(c.get("est_reported", 0)), int(c.get("act_reported", 0))
        return {
            "trusted": int(data.get("consec_unreported") or 0) < UNREPORTED_TRIP,
            "consec_unreported": int(data.get("consec_unreported") or 0),
            "reported_posts": int(c.get("reported", 0)), "unreported_posts": int(c.get("unreported", 0)),
            "estimated_rows_of_reported": est, "actual_rows_of_reported": act,
            "estimate_over_actual": round(est / act, 3) if act else None,
            "surcharge_rows": int(c.get("surcharge", 0)),
        }

    def refund(self, rows: int) -> None:
        """Give back a reservation for a call that never reached D1 (connection error, skipped)."""
        self.settle(rows, 0)

    def snapshot(self) -> dict[str, Any]:
        try:
            return self._read(self.clock())
        except Exception:
            return _empty_ledger(utc_day(self.clock()))

    def used(self) -> int:
        data = self.snapshot()
        return self._bucket_used(data, self.bucket_of(self.name))

    def remaining(self, priority: str = HIGH) -> int:
        if not self.enabled:
            return 1 << 30
        priority = self.priority_for(priority)
        data = self.snapshot()
        now = self.clock()
        cap = self.allowance() if priority == HIGH else min(self.allowance(), self.low_cap(now))
        return max(0, int(min(cap - self._bucket_used(data, self.bucket_of(self.name)), self.daily_budget - self._total_used(data))))

    def can_afford(self, rows: int, priority: str = HIGH) -> bool:
        """Read-only check (no charge, no denial record) - for deciding whether a flush is worth attempting."""
        return self.remaining(priority) >= rows and self.backoff_remaining() <= 0

    def seconds_until_reset(self) -> float:
        return 86400.0 - seconds_into_utc_day(self.clock())

    # -- shared back-off ----------------------------------------------------------------------------------
    def backoff_remaining(self) -> float:
        try:
            until = float(self._read(self.clock()).get("backoff_until") or 0.0)
        except Exception:
            return 0.0
        return max(0.0, until - self.clock())

    def clear_backoff(self) -> None:
        def op(data: dict[str, Any], now: float) -> None:
            data["backoff_until"] = 0.0
            data["backoff_reason"] = ""

        try:
            self._mutate(op)
        except Exception as exc:
            logger.debug("write budget backoff not cleared: %s", exc)

    def start_backoff(self, seconds: float = DEFAULT_BACKOFF_SECONDS, reason: str = "") -> None:
        def op(data: dict[str, Any], now: float) -> None:
            data["backoff_until"] = max(float(data.get("backoff_until") or 0.0), now + max(1.0, seconds))
            data["backoff_reason"] = reason

        try:
            self._mutate(op)
        except Exception as exc:
            logger.debug("write budget backoff not persisted: %s", exc)


# ---------------------------------------------------------------------------------------------------------
# Process-wide instance (env-configured). Tests call reset_budget().
# ---------------------------------------------------------------------------------------------------------
_instance: WriteBudget | None = None
_instance_lock = threading.Lock()


def get_budget() -> WriteBudget:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = WriteBudget()
        return _instance


def reset_budget(instance: WriteBudget | None = None) -> None:
    global _instance
    with _instance_lock:
        _instance = instance


def budget_gate_enabled() -> bool:
    return daily_budget_from_env() > 0

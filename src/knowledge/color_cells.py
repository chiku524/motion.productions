"""
Exact 8-bit colour cells: the 2^24 key space (every RGB value), its local coverage store, and the
deterministic work queue that walks it.

This is Phase 1 of docs/EXHAUSTIVE_REGISTRY_PLAN.md ("exact 8-bit from the start"):

* **Cell id** = ``(r << 16) | (g << 8) | b`` (0 .. 16,777,215). Chunk = ``id >> 19`` (32 chunks of 524,288 cells,
  which is also ``r >> 3``). Bit ``i`` of a plane lives in byte ``i >> 3`` at mask ``1 << (i & 7)`` (LSB first),
  the same layout the Worker (``cloudflare/src/colorCells.ts``) uses, so a 64 KiB chunk is portable as raw bytes.
* **Three planes** (2 MiB each, local files on the shared ``knowledge/`` volume):
  ``observed`` (tier T1: the exact colour was decoded from a rendered clip), ``verified`` (tier T2: a *target* colour
  survived encode/decode within the codec tolerance), ``declared`` (tier T3: targeted or asserted, never confirmed).
  Only observed|verified count as coverage (``src/knowledge/evidence.py``).
* **Merge-safe**: ``save()`` OR-merges with the file on disk under a portable lock (O_EXCL, works on Docker bind
  mounts where fcntl does not) and writes atomically (tmp + ``os.replace``), so containers sharing the volume
  only ever add bits.
* **Deterministic queue**: a seeded 6-round Feistel network is a bijection on 24 bits; position ``p`` of the
  permuted sequence maps to cell ``perm(p)``. Container ``w`` of ``n`` owns positions ``p % n == w`` so strides are
  disjoint by construction, cells already covered are skipped, and nothing is read from D1.

Pure numpy + stdlib; no network.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import time
import zlib
from pathlib import Path
from typing import Iterable

import numpy as np

logger = logging.getLogger(__name__)

SPACE_ID = "color.L2.a20"        # exact 8-bit RGB, no opacity plane yet
SPACE_VERSION = 1
SPACE_BITS = 24
SPACE_SIZE = 1 << SPACE_BITS      # 16,777,216
PLANE_BYTES = SPACE_SIZE // 8     # 2 MiB
CHUNK_BYTES = 64 * 1024
CHUNK_CELLS = CHUNK_BYTES * 8     # 524,288
N_CHUNKS = SPACE_SIZE // CHUNK_CELLS  # 32
PLANES = ("observed", "verified", "declared")
MAX_ATTEMPTS = 3                  # a cell that fails verification this often is parked ("quarantined")
ATTEMPTS_CAP = 200_000            # entries kept in attempts.json
LEDGER_MAX_BYTES = 512 * 1024
DEFAULT_SEED = int.from_bytes(
    hashlib.blake2b(b"motion.productions/color.L2.a20/v1", digest_size=8).digest(), "big"
)

_POP8 = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


# ---------------------------------------------------------------------------------------------------------------
# id helpers
# ---------------------------------------------------------------------------------------------------------------
def rgb_to_id(r: int, g: int, b: int) -> int:
    for v in (r, g, b):
        if not 0 <= int(v) <= 255:
            raise ValueError(f"channel out of range: {(r, g, b)}")
    return (int(r) << 16) | (int(g) << 8) | int(b)


def id_to_rgb(cell_id: int) -> tuple[int, int, int]:
    cid = int(cell_id)
    if not 0 <= cid < SPACE_SIZE:
        raise ValueError(f"cell id out of range: {cell_id}")
    return (cid >> 16) & 255, (cid >> 8) & 255, cid & 255


def id_to_hex(cell_id: int) -> str:
    r, g, b = id_to_rgb(cell_id)
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_array_to_ids(rgb: np.ndarray) -> np.ndarray:
    """(..., 3) uint8 -> (...) uint32 cell ids."""
    a = np.asarray(rgb)
    if a.shape[-1] != 3:
        raise ValueError("last axis must be 3 (RGB)")
    a = a.astype(np.uint32)
    return (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]


def ids_to_rgb_array(ids: np.ndarray) -> np.ndarray:
    """(...) ids -> (..., 3) uint8."""
    a = np.asarray(ids).astype(np.uint32)
    return np.stack([(a >> 16) & 255, (a >> 8) & 255, a & 255], axis=-1).astype(np.uint8)


def chunk_of(cell_id: int) -> int:
    return int(cell_id) >> 19


def l1_key(cell_id: int) -> tuple[int, int, int]:
    """Coarse rollup used by the legacy registry (floor(v / 5)): 52 bins per channel."""
    r, g, b = id_to_rgb(cell_id)
    return r // 5, g // 5, b // 5


def l0_key(cell_id: int) -> tuple[int, int, int]:
    """Coarsest rollup (floor(v / 25)): 11 bins per channel."""
    r, g, b = id_to_rgb(cell_id)
    return r // 25, g // 25, b // 25


# ---------------------------------------------------------------------------------------------------------------
# bit helpers (numpy, LSB-first per byte)
# ---------------------------------------------------------------------------------------------------------------
def popcount(buf: np.ndarray | bytes | bytearray) -> int:
    arr = np.frombuffer(buf, dtype=np.uint8) if isinstance(buf, (bytes, bytearray)) else buf
    return int(_POP8[arr].sum(dtype=np.int64))


def bits_test(plane: np.ndarray, ids: np.ndarray) -> np.ndarray:
    ids = np.asarray(ids).astype(np.int64)
    return ((plane[ids >> 3] >> (ids & 7).astype(np.uint8)) & 1).astype(bool)


def bits_set(plane: np.ndarray, ids: np.ndarray) -> None:
    ids = np.unique(np.asarray(ids).astype(np.int64))
    if ids.size == 0:
        return
    np.bitwise_or.at(plane, ids >> 3, (1 << (ids & 7)).astype(np.uint8))


def chunk_bytes(plane: np.ndarray, idx: int) -> bytes:
    if not 0 <= idx < N_CHUNKS:
        raise ValueError(f"chunk out of range: {idx}")
    return plane[idx * CHUNK_BYTES:(idx + 1) * CHUNK_BYTES].tobytes()


def chunk_pack(raw: bytes) -> str:
    """zlib + base64 (what the sync endpoint accepts as ``enc: "zlib"``)."""
    import base64

    return base64.b64encode(zlib.compress(raw, 6)).decode("ascii")


# ---------------------------------------------------------------------------------------------------------------
# seeded Feistel permutation over 2^24
# ---------------------------------------------------------------------------------------------------------------
_M64 = (1 << 64) - 1


class FeistelPermutation:
    """Format-preserving bijection on [0, 2^24): balanced Feistel, 12-bit halves, ``rounds`` rounds.

    A Feistel network is a permutation for ANY round function, and 24 bits splits into two equal halves,
    so no cycle-walking is needed. ``permute``/``invert`` are exact inverses.
    """

    def __init__(self, seed: int = DEFAULT_SEED, rounds: int = 6):
        self.seed = int(seed) & _M64
        self.rounds = int(rounds)
        self.keys = [
            int.from_bytes(
                hashlib.blake2b(f"{self.seed}:{i}".encode(), digest_size=8).digest(), "big"
            )
            for i in range(self.rounds)
        ]

    @staticmethod
    def _f(x: np.ndarray, key: int) -> np.ndarray:
        with np.errstate(over="ignore"):
            z = (x.astype(np.uint64) ^ np.uint64(key)) * np.uint64(0x9E3779B97F4A7C15)
            z ^= z >> np.uint64(29)
            z = z * np.uint64(0xBF58476D1CE4E5B9)
            z ^= z >> np.uint64(32)
        return ((z >> np.uint64(20)) & np.uint64(0xFFF)).astype(np.uint32)

    def permute_array(self, values: np.ndarray) -> np.ndarray:
        v = np.asarray(values).astype(np.uint32)
        left, right = (v >> 12) & 0xFFF, v & 0xFFF
        for k in self.keys:
            left, right = right, left ^ self._f(right, k)
        return ((left << 12) | right).astype(np.uint32)

    def invert_array(self, values: np.ndarray) -> np.ndarray:
        v = np.asarray(values).astype(np.uint32)
        left, right = (v >> 12) & 0xFFF, v & 0xFFF
        for k in reversed(self.keys):
            left, right = right ^ self._f(left, k), left
        return ((left << 12) | right).astype(np.uint32)

    def permute(self, x: int) -> int:
        return int(self.permute_array(np.array([x], dtype=np.uint32))[0])

    def invert(self, y: int) -> int:
        return int(self.invert_array(np.array([y], dtype=np.uint32))[0])


# ---------------------------------------------------------------------------------------------------------------
# local store
# ---------------------------------------------------------------------------------------------------------------
def default_store_dir() -> Path:
    env = (os.environ.get("COLOR_CELLS_DIR") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent / "knowledge" / "color_cells"


class _FileLock:
    """Same O_EXCL + stale-timeout lock as content_novelty._DirLock, as a single lock file."""

    def __init__(self, path: Path, timeout: float = 15.0, stale: float = 60.0):
        self.path, self.timeout, self.stale = path, timeout, stale
        self._fd: int | None = None

    def __enter__(self):
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
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            if self._fd is not None:
                os.close(self._fd)
        finally:
            self._fd = None
            try:
                os.unlink(self.path)
            except OSError:
                pass


def atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    last: Exception | None = None
    for _ in range(40):  # Windows: the destination can be briefly held open by a reader
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            last = e
            time.sleep(0.05)
    try:
        tmp.unlink()
    except OSError:
        pass
    raise last or OSError("replace failed")


class ColorCellStore:
    """In-memory view of the three planes, persisted as ``<dir>/{observed,verified,declared}.bits``."""

    def __init__(self, directory: Path | str | None = None):
        self.dir = Path(directory) if directory else default_store_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.dir / "store.lock"
        self.planes: dict[str, np.ndarray] = {p: np.zeros(PLANE_BYTES, dtype=np.uint8) for p in PLANES}
        self.meta = self._load_meta()
        self.refresh()

    # -- files ------------------------------------------------------------------------------------------------
    def _plane_path(self, plane: str) -> Path:
        return self.dir / f"{plane}.bits"

    def _read_plane(self, plane: str) -> np.ndarray | None:
        try:
            raw = self._plane_path(plane).read_bytes()
        except FileNotFoundError:
            return None
        except OSError as e:
            logger.warning("color store: cannot read %s: %s", plane, e)
            return None
        if len(raw) != PLANE_BYTES:
            logger.warning("color store: %s has %d bytes (want %d); ignoring", plane, len(raw), PLANE_BYTES)
            return None
        return np.frombuffer(raw, dtype=np.uint8).copy()

    def _load_meta(self) -> dict:
        path = self.dir / "meta.json"
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(meta, dict) and "seed" in meta:
                return meta
        except (OSError, ValueError):
            pass
        env_seed = (os.environ.get("COLOR_QUEUE_SEED") or "").strip()
        seed = int(env_seed) if env_seed.lstrip("-").isdigit() else DEFAULT_SEED
        meta = {"space": SPACE_ID, "version": SPACE_VERSION, "seed": seed, "created": int(time.time())}
        try:
            with _FileLock(self._lock_path):
                # another container may have won the race: honour its seed so every stride shares one permutation
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(existing, dict) and "seed" in existing:
                        return existing
                except (OSError, ValueError):
                    pass
                atomic_write_bytes(path, json.dumps(meta).encode("utf-8"))
        except (TimeoutError, OSError) as e:
            logger.warning("color store: could not persist meta.json: %s", e)
        return meta

    @property
    def seed(self) -> int:
        return int(self.meta["seed"])

    def permutation(self) -> FeistelPermutation:
        return FeistelPermutation(self.seed)

    def refresh(self) -> None:
        """OR the on-disk planes into memory (cheap; picks up other containers' bits)."""
        for p in PLANES:
            disk = self._read_plane(p)
            if disk is not None:
                np.bitwise_or(self.planes[p], disk, out=self.planes[p])

    # -- queries ----------------------------------------------------------------------------------------------
    def covered_mask(self, ids: np.ndarray) -> np.ndarray:
        return bits_test(self.planes["observed"], ids) | bits_test(self.planes["verified"], ids)

    def tier_of(self, cell_id: int) -> str:
        """'verified' > 'observed' > 'declared' > 'none'."""
        ids = np.array([cell_id], dtype=np.int64)
        for p in ("verified", "observed", "declared"):
            if bits_test(self.planes[p], ids)[0]:
                return p
        return "none"

    def counts(self) -> dict:
        obs, ver, dec = (popcount(self.planes[p]) for p in PLANES)
        covered = popcount(self.planes["observed"] | self.planes["verified"])
        declared_only = popcount(self.planes["declared"] & ~(self.planes["observed"] | self.planes["verified"]))
        return {
            "space": SPACE_ID,
            "size": SPACE_SIZE,
            "observed": obs,
            "verified": ver,
            "declared": dec,
            "covered": covered,
            "declared_only": declared_only,
            "pct_covered": round(100.0 * covered / SPACE_SIZE, 6),
            "quarantined": len(self._quarantined()),
            **self._totals(),
        }

    # -- cumulative survey totals (so a log line can show "clips this iteration" next to "clips ever") --------------
    def _totals_path(self) -> Path:
        return self.dir / "totals.json"

    def _totals(self) -> dict:
        """{'survey_clips', 'survey_cells'}: cumulative, kept in totals.json; bootstrapped once from the ledger."""
        try:
            d = json.loads(self._totals_path().read_text(encoding="utf-8"))
            return {"survey_clips": int(d["clips"]), "survey_cells": int(d["cells"])}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        clips = cells = 0
        for name in ("ledger.jsonl.1", "ledger.jsonl"):
            try:
                for line in (self.dir / name).read_text(encoding="utf-8").splitlines():
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("k") == "survey":
                        clips += 1
                        cells += int(rec.get("ok") or 0)
            except OSError:
                pass
        return {"survey_clips": clips, "survey_cells": cells}

    def chunk_counts(self) -> list[dict]:
        out = []
        for i in range(N_CHUNKS):
            sl = slice(i * CHUNK_BYTES, (i + 1) * CHUNK_BYTES)
            o, v, d = self.planes["observed"][sl], self.planes["verified"][sl], self.planes["declared"][sl]
            out.append({
                "idx": i,
                "observed": popcount(o),
                "verified": popcount(v),
                "declared": popcount(d),
                "covered": popcount(o | v),
            })
        return out

    # -- mutation ---------------------------------------------------------------------------------------------
    def mark(self, plane: str, ids: Iterable[int] | np.ndarray) -> None:
        if plane not in PLANES:
            raise ValueError(f"unknown plane: {plane}")
        arr = np.asarray(list(ids) if not isinstance(ids, np.ndarray) else ids, dtype=np.int64)
        if arr.size == 0:
            return
        if arr.min() < 0 or arr.max() >= SPACE_SIZE:
            raise ValueError("cell id out of range")
        bits_set(self.planes[plane], arr)

    def merge_chunks(self, plane: str, chunks: dict[int, bytes]) -> None:
        """OR raw 64 KiB chunks (e.g. pulled from the Worker) into memory (call save() to persist)."""
        if plane not in PLANES:
            raise ValueError(f"unknown plane: {plane}")
        for idx, raw in chunks.items():
            if not 0 <= int(idx) < N_CHUNKS or len(raw) != CHUNK_BYTES:
                raise ValueError(f"bad chunk {idx}: {len(raw)} bytes")
            sl = slice(int(idx) * CHUNK_BYTES, (int(idx) + 1) * CHUNK_BYTES)
            np.bitwise_or(self.planes[plane][sl], np.frombuffer(raw, dtype=np.uint8), out=self.planes[plane][sl])

    def save(self) -> bool:
        """OR-merge with disk under the lock, then write atomically. Returns True if any file was written."""
        wrote = False
        with _FileLock(self._lock_path):
            for p in PLANES:
                disk = self._read_plane(p)
                if disk is not None:
                    np.bitwise_or(self.planes[p], disk, out=self.planes[p])
                if disk is None or not np.array_equal(disk, self.planes[p]):
                    atomic_write_bytes(self._plane_path(p), self.planes[p].tobytes())
                    wrote = True
        return wrote

    # -- attempts (sparse; quarantine for cells that keep failing) ------------------------------------------------
    def _attempts_path(self) -> Path:
        return self.dir / "attempts.json"

    def _read_attempts(self) -> dict[str, int]:
        try:
            data = json.loads(self._attempts_path().read_text(encoding="utf-8"))
            return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _quarantined(self) -> list[int]:
        return [int(k) for k, v in self._read_attempts().items() if v >= MAX_ATTEMPTS]

    def attempts_for(self, ids: np.ndarray) -> np.ndarray:
        att = self._read_attempts()
        if not att:
            return np.zeros(len(ids), dtype=np.int32)
        return np.array([att.get(str(int(i)), 0) for i in ids], dtype=np.int32)

    def record_outcome(
        self,
        *,
        verified: Iterable[int] = (),
        observed: Iterable[int] = (),
        failed: Iterable[int] = (),
        ledger: dict | None = None,
    ) -> dict:
        """One locked read-merge-write for a whole clip: mark planes, bump/clear attempts, append the ledger."""
        verified_a = np.asarray(list(verified), dtype=np.int64)
        observed_a = np.asarray(list(observed), dtype=np.int64)
        failed_a = np.asarray(list(failed), dtype=np.int64)
        self.mark("verified", verified_a)
        self.mark("observed", observed_a)
        self.mark("declared", failed_a)
        self.mark("declared", verified_a)  # a verified target was also declared/targeted first
        with _FileLock(self._lock_path):
            for p in PLANES:
                disk = self._read_plane(p)
                if disk is not None:
                    np.bitwise_or(self.planes[p], disk, out=self.planes[p])
                if disk is None or not np.array_equal(disk, self.planes[p]):
                    atomic_write_bytes(self._plane_path(p), self.planes[p].tobytes())
            att = self._read_attempts()
            for c in failed_a.tolist():
                att[str(c)] = att.get(str(c), 0) + 1
            for c in np.concatenate([verified_a, observed_a]).tolist():
                att.pop(str(c), None)
            if len(att) > ATTEMPTS_CAP:
                for k in sorted(att, key=att.get)[: len(att) - ATTEMPTS_CAP]:  # drop the least-failed first
                    att.pop(k, None)
            atomic_write_bytes(self._attempts_path(), json.dumps(att).encode("utf-8"))
            if ledger is not None:
                if ledger.get("k") == "survey":
                    tot = self._totals()
                    try:
                        atomic_write_bytes(self._totals_path(), json.dumps(
                            {"clips": tot["survey_clips"] + 1, "cells": tot["survey_cells"] + int(ledger.get("ok") or 0)}
                        ).encode("utf-8"))
                    except OSError as e:
                        logger.debug("color totals write failed: %s", e)
                self._append_ledger(ledger)
        return self.counts()

    def _append_ledger(self, rec: dict) -> None:
        path = self.dir / "ledger.jsonl"
        try:
            if path.exists() and path.stat().st_size > LEDGER_MAX_BYTES:
                os.replace(path, self.dir / "ledger.jsonl.1")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": int(time.time()), **rec}, separators=(",", ":")) + "\n")
        except OSError as e:
            logger.debug("color ledger append failed: %s", e)


# ---------------------------------------------------------------------------------------------------------------
# worker identity + stride queue
# ---------------------------------------------------------------------------------------------------------------
def worker_identity(index: int | None = None, count: int | None = None) -> tuple[int, int]:
    """(index, count) from args, else CONTAINER_INDEX / CONTAINER_COUNT, else a hostname hash modulo
    ``COLOR_WORKER_COUNT`` (default 8). Explicit indices are disjoint; the hash fallback can collide (harmless:
    cells covered by the other worker are skipped, but the same cell may be surveyed twice)."""
    def _int(name: str) -> int | None:
        v = (os.environ.get(name) or "").strip()
        return int(v) if v.lstrip("-").isdigit() else None

    n = count if count is not None else _int("CONTAINER_COUNT")
    i = index if index is not None else _int("CONTAINER_INDEX")
    if i is None:
        n = n or _int("COLOR_WORKER_COUNT") or 8
        h = int.from_bytes(hashlib.blake2b(socket.gethostname().encode(), digest_size=4).digest(), "big")
        i = h % n
    n = max(1, int(n or 1))
    return int(i) % n, n


class ColorWorkQueue:
    """Deterministic, disjoint-stride walk over unseen cells. No D1 reads, no randomness at pick time."""

    CHUNK = 4096

    def __init__(
        self,
        store: ColorCellStore,
        index: int | None = None,
        count: int | None = None,
        stream: str = "survey",
    ):
        self.store = store
        self.index, self.count = worker_identity(index, count)
        self.stream = stream
        self.perm = store.permutation()
        self._path = store.dir / f"cursor_{stream}_{self.index}of{self.count}.json"
        self.cursor = self._load()

    def _load(self) -> int:
        try:
            return max(0, int(json.loads(self._path.read_text(encoding="utf-8")).get("next", 0)))
        except (OSError, ValueError, AttributeError):
            return 0

    def _save(self) -> None:
        try:
            atomic_write_bytes(self._path, json.dumps({"next": self.cursor, "stride": [self.index, self.count]}).encode())
        except OSError as e:
            logger.debug("cursor save failed: %s", e)

    def positions(self, start: int, n: int) -> np.ndarray:
        """Permutation positions owned by this worker: p = index + count * j for j in [start, start+n)."""
        j = np.arange(start, start + n, dtype=np.int64)
        p = self.index + self.count * j
        return p[p < SPACE_SIZE]

    def next_cells(self, n: int, *, consume: bool = True, refresh: bool = True) -> np.ndarray:
        """Next ``n`` uncovered, not-quarantined cells of this worker's stride (fewer if the stride is exhausted)."""
        if refresh:
            self.store.refresh()
        out: list[np.ndarray] = []
        got = 0
        j = self.cursor
        wrapped = False
        while got < n:
            pos = self.positions(j, self.CHUNK)
            if pos.size == 0:
                if wrapped or j == 0:
                    break
                j, wrapped = 0, True  # second pass: retry cells that failed earlier (attempt-capped)
                continue
            cells = self.perm.permute_array(pos).astype(np.int64)
            ok = ~self.store.covered_mask(cells)
            if ok.any():
                att = self.store.attempts_for(cells[ok])
                keep = np.zeros(len(cells), dtype=bool)
                keep[np.flatnonzero(ok)[att < MAX_ATTEMPTS]] = True
                ok = keep
            idxs = np.flatnonzero(ok)
            need = n - got
            if idxs.size > need:
                idxs = idxs[:need]
                j += int(idxs[-1]) + 1
                out.append(cells[idxs])
                got += need
                break
            out.append(cells[idxs])
            got += idxs.size
            j += self.CHUNK
        if consume:
            self.cursor = j
            self._save()
        return np.concatenate(out).astype(np.int64) if out else np.zeros(0, dtype=np.int64)

    def exhausted(self) -> bool:
        return self.positions(self.cursor, 1).size == 0
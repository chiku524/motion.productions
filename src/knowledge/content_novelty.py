"""
Content-level novelty gate.

Prompt text can differ while the rendered clip looks and sounds the same.
This module fingerprints the *clip itself* and compares it with a bounded
rolling store of recent fingerprints:

* perceptual hash (16x16 dHash, 256 bits) of ~3 frames  -> layout / structure
* coarse RGB histogram (4x4x4 = 64 bins, mean over those frames) -> palette
* audio band-energy spectrum (12 log-spaced bands) + loudness   -> sound

A clip that is too close to something in the store is rejected and the caller
re-rolls the seed (``render_until_novel``). Fingerprints and tiny thumbnails are
kept (bounded) instead of throwing everything away with the scratch mp4.

Everything is local: an append-only JSONL file plus ~48px JPEG thumbnails, meant to live on
a volume shared by every loop container (``NOVELTY_STORE_DIR``). No API calls.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

logger = logging.getLogger(__name__)

HASH_SIDE = 16                # dHash grid: 16 x 16 = 256 bits per frame
HIST_BINS = 4                 # 4 levels per channel
AUDIO_BANDS = 12
AUDIO_SR = 22050
AUDIO_LO_HZ, AUDIO_HI_HZ = 60.0, 10000.0
THUMB_SIDE = 48
STORE_VERSION = 1

# Thresholds on the 0..1 distances below. A clip is a near-duplicate of a
# stored clip when its *combined* distance is below `combined`, or when it is
# a visual twin (hash AND palette both nearly identical) regardless of audio.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "combined": 0.10,
    "visual_hash": 0.06,
    "palette": 0.08,
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, "") or default))
    except ValueError:
        return default


def novelty_enabled() -> bool:
    return (os.environ.get("NOVELTY_GATE", "1").strip().lower() not in ("0", "false", "off", "no"))


def default_thresholds() -> dict[str, float]:
    return {
        "combined": _env_float("NOVELTY_COMBINED_MIN", DEFAULT_THRESHOLDS["combined"]),
        "visual_hash": _env_float("NOVELTY_HASH_MIN", DEFAULT_THRESHOLDS["visual_hash"]),
        "palette": _env_float("NOVELTY_PALETTE_MIN", DEFAULT_THRESHOLDS["palette"]),
    }


# ---------------------------------------------------------------- fingerprints
@dataclass
class ClipFingerprint:
    phash: list[str]            # one hex string per sampled frame
    hist: list[float]           # 64 normalized bins
    audio: list[float]          # AUDIO_BANDS normalized band energies ([] = no audio)
    loudness: float = 0.0       # RMS 0..1 (informational; not part of the distance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phash": list(self.phash),
            "hist": [round(float(x), 4) for x in self.hist],
            "audio": [round(float(x), 4) for x in self.audio],
            "loudness": round(float(self.loudness), 4),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClipFingerprint":
        return cls(
            phash=[str(h) for h in d.get("phash", [])],
            hist=[float(x) for x in d.get("hist", [])],
            audio=[float(x) for x in d.get("audio", [])],
            loudness=float(d.get("loudness", 0.0)),
        )


def _gray(frame: np.ndarray) -> np.ndarray:
    f = np.asarray(frame, dtype=np.float32)
    if f.ndim == 2:
        return f
    return f[..., :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def _resize_mean(img: np.ndarray, h: int, w: int) -> np.ndarray:
    """Area-average resize (no PIL needed): crop to a multiple, then block mean."""
    ih, iw = img.shape[:2]
    ys = np.linspace(0, ih, h + 1).astype(int)
    xs = np.linspace(0, iw, w + 1).astype(int)
    out = np.empty((h, w) + img.shape[2:], dtype=np.float32)
    for i in range(h):
        for j in range(w):
            blk = img[ys[i]:max(ys[i] + 1, ys[i + 1]), xs[j]:max(xs[j] + 1, xs[j + 1])]
            out[i, j] = blk.mean(axis=(0, 1))
    return out


def dhash_hex(frame: np.ndarray, side: int = HASH_SIDE) -> str:
    """Difference hash: compare horizontally adjacent cells of a (side) x (side+1) grid."""
    small = _resize_mean(_gray(frame), side, side + 1)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return format(value, f"0{side * side // 4}x")


def hamming_hex(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def color_histogram(frames: Sequence[np.ndarray], bins: int = HIST_BINS) -> list[float]:
    acc = np.zeros(bins ** 3, dtype=np.float64)
    for fr in frames:
        a = np.asarray(fr)[..., :3].astype(np.int32)
        q = np.clip(a * bins // 256, 0, bins - 1)
        idx = (q[..., 0] * bins + q[..., 1]) * bins + q[..., 2]
        acc += np.bincount(idx.ravel(), minlength=bins ** 3)
    total = acc.sum()
    return (acc / total).tolist() if total > 0 else acc.tolist()


def audio_band_energy(samples: np.ndarray, sr: int = AUDIO_SR, bands: int = AUDIO_BANDS) -> tuple[list[float], float]:
    """Normalized log-spaced band energies (sum to 1) and RMS loudness."""
    x = np.asarray(samples, dtype=np.float64).ravel()
    if x.size < 256:
        return [], 0.0
    rms = float(np.sqrt(np.mean(x * x)))
    if rms < 1e-5:
        return [0.0] * bands, rms
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size))) ** 2
    freqs = np.fft.rfftfreq(x.size, 1.0 / sr)
    edges = np.geomspace(AUDIO_LO_HZ, min(AUDIO_HI_HZ, sr / 2.0 - 1), bands + 1)
    e = np.array([spec[(freqs >= edges[i]) & (freqs < edges[i + 1])].sum() for i in range(bands)])
    s = e.sum()
    return ((e / s).tolist() if s > 0 else [0.0] * bands), min(1.0, rms)


def fingerprint_arrays(
    frames: Sequence[np.ndarray],
    audio: np.ndarray | None = None,
    sr: int = AUDIO_SR,
) -> ClipFingerprint:
    """Fingerprint already-decoded frames (uint8 HxWx3) and mono audio samples."""
    if not len(frames):
        raise ValueError("no frames to fingerprint")
    idx = sorted({0, len(frames) // 2, len(frames) - 1})
    picked = [frames[i] for i in idx]
    bands, rms = ([], 0.0)
    if audio is not None:
        bands, rms = audio_band_energy(audio, sr)
    return ClipFingerprint(
        phash=[dhash_hex(f) for f in picked],
        hist=color_histogram(picked),
        audio=bands,
        loudness=rms,
    )


def _ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def decode_audio(path: str | Path, sr: int = AUDIO_SR) -> np.ndarray | None:
    exe = _ffmpeg_exe()
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
            capture_output=True, timeout=60, check=False,
        )
    except Exception as e:  # pragma: no cover - environment dependent
        logger.debug("audio decode failed: %s", e)
        return None
    if not proc.stdout:
        return None
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def read_sample_frames(path: str | Path, n: int = 3) -> list[np.ndarray]:
    import imageio.v2 as imageio
    reader = imageio.get_reader(str(path))
    try:
        try:
            total = reader.count_frames()
        except Exception:
            total = 0
        if not total or total == float("inf"):
            frames = [np.asarray(f) for f in reader]
            total = len(frames)
            if not total:
                return []
            pick = sorted({0, total // 2, total - 1})
            return [frames[i] for i in pick][:max(n, 1)]
        pick = sorted({0, total // 2, max(0, total - 1)})
        return [np.asarray(reader.get_data(i)) for i in pick]
    finally:
        reader.close()


def fingerprint_video(path: str | Path) -> tuple[ClipFingerprint, np.ndarray]:
    """Return (fingerprint, middle frame) for an mp4."""
    frames = read_sample_frames(path)
    fp = fingerprint_arrays(frames, decode_audio(path))
    return fp, frames[len(frames) // 2]


# ------------------------------------------------------------------- distance
def _tv(a: Sequence[float], b: Sequence[float]) -> float:
    """Total-variation distance between two normalized distributions, 0..1."""
    if not a or not b or len(a) != len(b):
        return 1.0
    return float(0.5 * np.abs(np.asarray(a) - np.asarray(b)).sum())


def fingerprint_distance(a: ClipFingerprint, b: ClipFingerprint) -> dict[str, float]:
    """All components are 0 (identical) .. 1 (unrelated)."""
    n = min(len(a.phash), len(b.phash))
    if n:
        bits = HASH_SIDE * HASH_SIDE
        vis = sum(hamming_hex(a.phash[i], b.phash[i]) for i in range(n)) / (n * bits)
    else:
        vis = 1.0
    pal = _tv(a.hist, b.hist)
    if a.audio and b.audio:
        aud = _tv(a.audio, b.audio)
        combined = 0.4 * min(1.0, vis * 2) + 0.35 * pal + 0.25 * aud
    else:
        aud = 0.0
        combined = 0.55 * min(1.0, vis * 2) + 0.45 * pal
    return {"visual_hash": vis, "palette": pal, "audio": aud, "combined": combined}


@dataclass
class NoveltyVerdict:
    novel: bool
    nearest_id: str | None = None
    distance: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    checked: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "novel": self.novel, "checked": self.checked, "reason": self.reason,
            "nearest_id": self.nearest_id,
            "distance": {k: round(v, 4) for k, v in self.distance.items()},
        }


def is_too_close(dist: dict[str, float], thresholds: dict[str, float] | None = None) -> str:
    """Empty string when far enough apart, else the reason it is a near-duplicate."""
    t = thresholds or default_thresholds()
    if dist["combined"] < t["combined"]:
        return f"combined {dist['combined']:.3f} < {t['combined']}"
    if dist["visual_hash"] < t["visual_hash"] and dist["palette"] < t["palette"]:
        return f"visual twin (hash {dist['visual_hash']:.3f}, palette {dist['palette']:.3f})"
    return ""


# ---------------------------------------------------------------------- store
class _DirLock:
    """Cross-process (and cross-container) lock via atomic O_EXCL file creation.

    Works on Windows, Linux and Docker bind mounts, where flock/fcntl is unreliable.
    A lock older than ``stale_s`` is assumed to belong to a crashed process and is stolen.
    """

    def __init__(self, path: Path, timeout_s: float = 20.0, stale_s: float = 30.0):
        self.path = Path(path)
        self.timeout_s = timeout_s
        self.stale_s = stale_s
        self._held = False

    def __enter__(self) -> "_DirLock":
        deadline = time.monotonic() + self.timeout_s
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self._held = True
                return self
            except (FileExistsError, PermissionError):  # PermissionError: Windows, file being deleted
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale_s:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"novelty store lock busy: {self.path}")
                time.sleep(0.02 + (os.getpid() % 7) * 0.003)

    def __exit__(self, *exc: Any) -> None:
        if self._held:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            self._held = False


DEFAULT_STORE_MAX = 5000


class NoveltyStore:
    """Bounded rolling store of fingerprints (+ tiny thumbnails), safe for many writers.

    Layout (all under ``directory``, meant to be a volume shared by every loop container):

    * ``fingerprints.jsonl`` - line 1 is a header ``{"gen": ..}``; every other line is one entry.
      Writers append under a lock, so concurrent processes never overwrite each other.
      When the file holds well over ``max_entries`` lines it is compacted (atomic replace +
      new ``gen`` so readers know to reload from scratch).
    * ``thumbs/<id>.jpg`` - 48px previews, pruned together with their entries.

    Readers tail the file by byte offset, so ``check()`` only parses entries other
    processes added since the previous call. Distances are computed with numpy over an
    in-memory index (palette / audio matrices), which keeps a 5000-clip window cheap.
    A legacy ``fingerprints.json`` is imported once.
    """

    COMPACT_FACTOR = 1.25

    def __init__(self, directory: str | Path, max_entries: int | None = None):
        self.dir = Path(directory)
        self.max_entries = max(1, int(max_entries or _env_int("NOVELTY_STORE_MAX", DEFAULT_STORE_MAX)))
        self.path = self.dir / "fingerprints.jsonl"
        self.legacy_path = self.dir / "fingerprints.json"
        self.lock_path = self.dir / "fingerprints.lock"
        self.thumb_dir = self.dir / "thumbs"
        self._entries: list[dict[str, Any]] = []
        self._evicted: list[str] = []  # ids trimmed from memory; thumbs are dropped on compaction
        self._gen: str | None = None
        self._offset = 0
        self._lines_on_disk = 0
        self._index_dirty = True
        self._fps: list[ClipFingerprint] = []
        self._hist = np.zeros((0, HIST_BINS ** 3), dtype=np.float32)
        self._hist_ok = np.zeros(0, dtype=bool)
        self._audio = np.zeros((0, AUDIO_BANDS), dtype=np.float32)
        self._audio_state = np.zeros(0, dtype=np.int8)  # 0 no audio, 1 usable, 2 wrong length
        self._hash_ints: list[list[int]] = []
        self._refresh()

    # ------------------------------------------------------------ disk <-> memory
    def _lock(self) -> _DirLock:
        return _DirLock(self.lock_path)

    def _read_header(self, f) -> str | None:
        first = f.readline()
        try:
            h = json.loads(first.decode("utf-8"))
            return str(h.get("gen")) if isinstance(h, dict) and "gen" in h else None
        except (ValueError, UnicodeDecodeError):
            return None

    def _refresh(self) -> None:
        """Pick up entries other processes appended (or reload after a compaction)."""
        try:
            size = self.path.stat().st_size
        except OSError:
            if self.legacy_path.exists() and not self._entries:
                self._import_legacy()
            return
        try:
            with open(self.path, "rb") as f:
                gen = self._read_header(f)
                if gen is None:
                    # Unreadable header (corrupt file): start empty; next write replaces it.
                    if self._entries:
                        self._reset_memory()
                    return
                if gen != self._gen or size < self._offset:
                    self._reset_memory()
                    self._gen = gen
                    f.seek(0)
                    f.readline()
                    self._offset = f.tell()
                else:
                    f.seek(self._offset)
                added = 0
                while True:
                    line = f.readline()
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        break  # partial line from a writer in progress; pick up next time
                    self._offset += len(line)
                    self._lines_on_disk += 1
                    try:
                        e = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(e, dict) and "fp" in e:
                        self._entries.append(e)
                        added += 1
        except OSError:
            return
        if added:
            self._index_dirty = True
        if len(self._entries) > self.max_entries:
            cut = len(self._entries) - self.max_entries
            self._evicted.extend(str(e.get("id")) for e in self._entries[:cut])
            del self._entries[:cut]
            self._index_dirty = True

    def _reset_memory(self) -> None:
        self._entries = []
        self._gen = None
        self._offset = 0
        self._lines_on_disk = 0
        self._index_dirty = True

    def _import_legacy(self) -> None:
        try:
            data = json.loads(self.legacy_path.read_text(encoding="utf-8"))
            items = data.get("entries", []) if isinstance(data, dict) else []
        except (OSError, ValueError):
            return
        keep = [e for e in items if isinstance(e, dict) and "fp" in e][-self.max_entries:]
        if not keep:
            return
        try:
            with self._lock():
                if not self.path.exists():  # another process may have imported already
                    self._write_file(keep)
        except (OSError, TimeoutError) as e:
            logger.warning("novelty legacy import skipped: %s", e)
            return
        self._refresh()

    def _write_file(self, entries: list[dict[str, Any]]) -> None:
        """Atomically (re)write the whole store with a fresh generation. Caller holds the lock."""
        self.dir.mkdir(parents=True, exist_ok=True)
        gen = f"{os.getpid()}-{int(time.time() * 1000)}"
        lines = [json.dumps({"gen": gen, "version": STORE_VERSION}, separators=(",", ":"))]
        lines += [json.dumps(e, separators=(",", ":")) for e in entries]
        payload = "\n".join(lines) + "\n"
        fd, tmp = tempfile.mkstemp(dir=str(self.dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(payload)
            for attempt in range(50):  # Windows refuses to replace a file another process has open
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if attempt == 49:
                        raise
                    time.sleep(0.02)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # --------------------------------------------------------------------- index
    def _rebuild_index(self) -> None:
        n = len(self._entries)
        bins = HIST_BINS ** 3
        self._fps = [ClipFingerprint.from_dict(e["fp"]) for e in self._entries]
        self._hist = np.zeros((n, bins), dtype=np.float32)
        self._hist_ok = np.zeros(n, dtype=bool)
        self._audio = np.zeros((n, AUDIO_BANDS), dtype=np.float32)
        self._audio_state = np.zeros(n, dtype=np.int8)
        self._hash_ints = []
        for i, fp in enumerate(self._fps):
            if len(fp.hist) == bins:
                self._hist[i] = fp.hist
                self._hist_ok[i] = True
            if fp.audio:
                if len(fp.audio) == AUDIO_BANDS:
                    self._audio[i] = fp.audio
                    self._audio_state[i] = 1
                else:
                    self._audio_state[i] = 2
            self._hash_ints.append([int(h, 16) for h in fp.phash])
        self._index_dirty = False

    def _distances(self, fp: ClipFingerprint) -> dict[str, np.ndarray]:
        """Vectorised ``fingerprint_distance`` of ``fp`` against every stored clip."""
        if self._index_dirty:
            self._rebuild_index()
        n = len(self._entries)
        bits = HASH_SIDE * HASH_SIDE
        q_hashes = [int(h, 16) for h in fp.phash]
        vis = np.ones(n, dtype=np.float64)
        for i, hs in enumerate(self._hash_ints):
            m = min(len(q_hashes), len(hs))
            if m:
                vis[i] = sum(bin(q_hashes[k] ^ hs[k]).count("1") for k in range(m)) / (m * bits)
        pal = np.ones(n, dtype=np.float64)
        if len(fp.hist) == HIST_BINS ** 3 and n:
            q = np.asarray(fp.hist, dtype=np.float32)
            tv = 0.5 * np.abs(self._hist - q).sum(axis=1)
            pal = np.where(self._hist_ok, tv, 1.0).astype(np.float64)
        aud = np.zeros(n, dtype=np.float64)
        has_audio = np.zeros(n, dtype=bool)
        if fp.audio and n:
            has_audio = self._audio_state > 0
            if len(fp.audio) == AUDIO_BANDS:
                q = np.asarray(fp.audio, dtype=np.float32)
                tv = 0.5 * np.abs(self._audio - q).sum(axis=1)
                aud = np.where(self._audio_state == 1, tv, 1.0).astype(np.float64)
            else:
                aud = np.ones(n, dtype=np.float64)
            aud = np.where(has_audio, aud, 0.0)
        with_audio = 0.4 * np.minimum(1.0, vis * 2) + 0.35 * pal + 0.25 * aud
        without = 0.55 * np.minimum(1.0, vis * 2) + 0.45 * pal
        combined = np.where(has_audio, with_audio, without)
        return {"visual_hash": vis, "palette": pal, "audio": aud, "combined": combined}

    # ------------------------------------------------------------------ queries
    def __len__(self) -> int:
        self._refresh()
        return len(self._entries)

    def entries(self) -> list[dict[str, Any]]:
        self._refresh()
        return list(self._entries)

    def _dist_at(self, d: dict[str, np.ndarray], i: int) -> dict[str, float]:
        return {k: float(v[i]) for k, v in d.items()}

    def nearest(self, fp: ClipFingerprint) -> tuple[str | None, dict[str, float] | None]:
        self._refresh()
        if not self._entries:
            return None, None
        d = self._distances(fp)
        i = int(np.argmin(d["combined"]))
        return self._entries[i].get("id"), self._dist_at(d, i)

    def check(self, fp: ClipFingerprint, thresholds: dict[str, float] | None = None) -> NoveltyVerdict:
        t = thresholds or default_thresholds()
        self._refresh()
        if not self._entries:
            return NoveltyVerdict(True, None, {}, "store empty")
        d = self._distances(fp)
        close = (d["combined"] < t["combined"]) | ((d["visual_hash"] < t["visual_hash"]) & (d["palette"] < t["palette"]))
        if close.any():
            i = int(np.nonzero(close)[0][-1])  # most recent offender
            dist = self._dist_at(d, i)
            return NoveltyVerdict(False, self._entries[i].get("id"), dist, is_too_close(dist, t))
        i = int(np.argmin(d["combined"]))
        return NoveltyVerdict(True, self._entries[i].get("id"), self._dist_at(d, i), "far from every stored clip")

    # ------------------------------------------------------------------- writes
    def add(
        self,
        fp: ClipFingerprint,
        *,
        entry_id: str,
        prompt: str = "",
        seed: int | None = None,
        thumbnail: np.ndarray | None = None,
    ) -> None:
        """Append one entry, merging with whatever other processes wrote (never last-writer-wins)."""
        if thumbnail is not None:
            self._write_thumb(entry_id, thumbnail)
        entry = {
            "id": entry_id, "t": int(time.time()), "seed": seed,
            "prompt": (prompt or "")[:80], "fp": fp.to_dict(),
        }
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        self.dir.mkdir(parents=True, exist_ok=True)
        with self._lock():
            self._refresh()  # see everyone else's entries before we decide how to write
            if not self.path.exists() or self._gen is None:
                self._write_file(self._entries + [entry])
            else:
                with open(self.path, "ab") as f:
                    f.write(line.encode("utf-8"))
            self._refresh()
            if self._lines_on_disk > self.max_entries * self.COMPACT_FACTOR:
                self._compact()

    def _compact(self) -> None:
        """Keep the newest ``max_entries``; drop thumbnails of the rest. Caller holds the lock."""
        self._refresh()
        keep = self._entries[-self.max_entries:]
        self._write_file(keep)
        for entry_id in self._evicted:
            self._drop_thumb(entry_id)
        self._evicted = []
        self._reset_memory()
        self._refresh()

    def save(self) -> None:
        """Rewrite the store from the merged view (rarely needed; ``add`` already persists)."""
        with self._lock():
            self._refresh()
            self._write_file(self._entries[-self.max_entries:])
            self._reset_memory()
            self._refresh()

    def _thumb_path(self, entry_id: str) -> Path:
        safe = "".join(c for c in entry_id if c.isalnum() or c in "-_")[:64] or "clip"
        return self.thumb_dir / f"{safe}.jpg"

    def _write_thumb(self, entry_id: str, frame: np.ndarray) -> None:
        try:
            from PIL import Image
            self.thumb_dir.mkdir(parents=True, exist_ok=True)
            Image.fromarray(np.asarray(frame)[..., :3].astype("uint8")).resize(
                (THUMB_SIDE, THUMB_SIDE)).save(self._thumb_path(entry_id), "JPEG", quality=55)
        except Exception as e:
            logger.debug("thumbnail skipped: %s", e)

    def _drop_thumb(self, entry_id: str) -> None:
        try:
            self._thumb_path(entry_id).unlink(missing_ok=True)
        except OSError:
            pass


def default_store_dir() -> Path:
    env = (os.environ.get("NOVELTY_STORE_DIR") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent / "data" / "novelty"

def reroll_seed(seed: int, attempt: int) -> int:
    """Deterministic, well-mixed new seed for re-roll #attempt (attempt >= 1)."""
    x = (int(seed) * 6364136223846793005 + attempt * 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 29
    return int(x % 2_147_483_647)


@dataclass
class GateResult:
    path: Path
    seed: int
    attempts: int
    verdict: NoveltyVerdict
    fingerprint: ClipFingerprint | None = None
    thumbnail: np.ndarray | None = None

    @property
    def content_novel(self) -> bool | None:
        """True/False when checked, None when the check could not run."""
        return self.verdict.novel if self.verdict.checked else None

    @property
    def rejected(self) -> bool:
        """True when the clip was fingerprinted and is STILL a near-duplicate after every re-roll.

        Callers must not publish such a clip or post discoveries extracted from it.
        """
        return bool(self.verdict.checked and not self.verdict.novel)


def render_until_novel(
    render_fn: Callable[[int], Path],
    store: NoveltyStore,
    *,
    seed: int,
    max_attempts: int | None = None,
    fingerprint_fn: Callable[[Path], tuple[ClipFingerprint, np.ndarray | None]] = fingerprint_video,
    thresholds: dict[str, float] | None = None,
) -> GateResult:
    """
    Call ``render_fn(seed)``; if the clip is too close to a stored one, re-roll the
    seed and render again (up to ``max_attempts``). The last render is returned
    either way: the verdict says whether it is novel (``GateResult.rejected`` is True when it
    is still a duplicate, and the caller must then skip it). If fingerprinting itself
    fails the render is returned unchecked (``content_novel`` is None).
    """
    attempts_cap = max(1, int(max_attempts or _env_int("NOVELTY_MAX_ATTEMPTS", 4)))
    cur = int(seed)
    last: GateResult | None = None
    for attempt in range(attempts_cap):
        path = Path(render_fn(cur))
        try:
            fp, thumb = fingerprint_fn(path)
        except Exception as e:
            logger.warning("Novelty fingerprint failed (%s); clip left unchecked", e)
            return GateResult(path, cur, attempt + 1, NoveltyVerdict(False, reason=f"fingerprint error: {e}", checked=False))
        verdict = store.check(fp, thresholds)
        last = GateResult(path, cur, attempt + 1, verdict, fp, thumb)
        if verdict.novel:
            return last
        logger.info("Too close to %s (%s): re-rolling seed (attempt %d/%d)",
                    verdict.nearest_id, verdict.reason, attempt + 1, attempts_cap)
        cur = reroll_seed(cur, attempt + 1)
    assert last is not None
    return last


def record_result(store: NoveltyStore, result: GateResult, *, entry_id: str, prompt: str = "") -> None:
    """Persist the accepted clip's fingerprint + thumbnail (no-op if it was unchecked)."""
    if result.fingerprint is None:
        return
    store.add(result.fingerprint, entry_id=entry_id, prompt=prompt, seed=result.seed, thumbnail=result.thumbnail)
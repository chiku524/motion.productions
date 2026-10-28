"""Registry access for video generation: "is colour cell X recorded, and at what evidence tier?".

Answers come from the local exact-colour bitsets (``color_cells.ColorCellStore``) or from a compact exported
snapshot, so a generator can query millions of cells with zero network and zero D1 reads. The Worker serves the
same question remotely at ``GET /api/coverage/color/cell`` (see docs/COLOR_SURVEY.md).

Tiers (strongest first): ``verified`` (decoded back within codec tolerance) > ``observed`` (seen in a decoded
frame) > ``declared`` (named but not measured). Only verified/observed count as *recorded* (coverage).

Snapshot format ``MPCS1`` (~ a few KiB while sparse, <= 6 MiB worst case):
    magic(5) | header_len(u32 LE) | header JSON | zlib(observed || verified || declared)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import time
import zlib
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .color_cells import (
    PLANE_BYTES,
    PLANES,
    SPACE_ID,
    SPACE_SIZE,
    SPACE_VERSION,
    ColorCellStore,
    bits_test,
    id_to_hex,
    id_to_rgb,
    popcount,
    rgb_to_id,
)

SNAPSHOT_MAGIC = b"MPCS1"
TIER_NONE, TIER_DECLARED, TIER_OBSERVED, TIER_VERIFIED = 0, 1, 2, 3
TIER_NAMES = {TIER_NONE: "none", TIER_DECLARED: "declared", TIER_OBSERVED: "observed", TIER_VERIFIED: "verified"}

CellLike = int | str | Sequence[int]


def parse_cell(cell: CellLike) -> int:
    """Accept an int cell id, ``"id:N"``, ``#rrggbb`` / ``rrggbb`` hex, ``"r,g,b"`` or an (r, g, b) sequence.\n\n    Bare decimal strings are rejected: ``"123456"`` is hex, and an id must be an int or ``"id:N"``.\n    """
    if isinstance(cell, (int, np.integer)):
        cid = int(cell)
    elif isinstance(cell, str):
        s = cell.strip()
        if "," in s:
            parts = [int(x) for x in s.split(",")]
            if len(parts) != 3 or any(not 0 <= p <= 255 for p in parts):
                raise ValueError(f"bad rgb triple: {cell!r}")
            return rgb_to_id(*parts)
        s = s.lstrip("#")
        if len(s) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in s):
            return int(s, 16)
        if s.lower().startswith("id:") and s[3:].strip().isdigit():
            cid = int(s[3:])
        else:
            raise ValueError(f"unrecognised colour cell: {cell!r}")
    else:
        parts = [int(x) for x in cell]
        if len(parts) != 3 or any(not 0 <= p <= 255 for p in parts):
            raise ValueError(f"bad rgb triple: {cell!r}")
        return rgb_to_id(*parts)
    if not 0 <= cid < SPACE_SIZE:
        raise ValueError(f"cell id out of range: {cid}")
    return cid


class RegistryLookup:
    """Read-only view over the three planes (from a live store or a snapshot)."""

    def __init__(self, planes: dict[str, np.ndarray], *, meta: dict[str, Any] | None = None):
        for p in PLANES:
            if planes[p].dtype != np.uint8 or planes[p].size != PLANE_BYTES:
                raise ValueError(f"plane {p!r} must be {PLANE_BYTES} uint8 bytes")
        self.planes = planes
        self.meta = meta or {}

    # -- constructors -----------------------------------------------------------------------------------------
    @classmethod
    def from_store(cls, store: ColorCellStore | None = None, *, refresh: bool = True) -> "RegistryLookup":
        store = store or ColorCellStore()
        if refresh:
            store.refresh()
        return cls(store.planes, meta={"source": "store", "seed": store.seed})

    @classmethod
    def from_snapshot(cls, path: str | Path) -> "RegistryLookup":
        raw = Path(path).read_bytes()
        if raw[: len(SNAPSHOT_MAGIC)] != SNAPSHOT_MAGIC:
            raise ValueError("not an MPCS1 snapshot")
        off = len(SNAPSHOT_MAGIC)
        (hlen,) = struct.unpack_from("<I", raw, off)
        off += 4
        header = json.loads(raw[off : off + hlen].decode("utf-8"))
        off += hlen
        if header.get("space") != SPACE_ID or int(header.get("version", -1)) != SPACE_VERSION:
            raise ValueError(f"snapshot is for {header.get('space')} v{header.get('version')}, not {SPACE_ID} v{SPACE_VERSION}")
        body = zlib.decompress(raw[off:])
        if len(body) != PLANE_BYTES * len(PLANES):
            raise ValueError("snapshot body has the wrong size")
        if hashlib.sha1(body).hexdigest() != header.get("sha1"):
            raise ValueError("snapshot checksum mismatch")
        arr = np.frombuffer(body, dtype=np.uint8)
        planes = {p: arr[i * PLANE_BYTES : (i + 1) * PLANE_BYTES].copy() for i, p in enumerate(PLANES)}
        return cls(planes, meta={"source": "snapshot", **header})

    # -- queries ----------------------------------------------------------------------------------------------
    def tier_codes(self, ids: np.ndarray | Iterable[int]) -> np.ndarray:
        """Vectorised: int8 array of TIER_* codes (strongest tier wins)."""
        ids = np.asarray(list(ids) if not isinstance(ids, np.ndarray) else ids, dtype=np.int64)
        out = np.zeros(ids.shape, dtype=np.int8)
        out[bits_test(self.planes["declared"], ids)] = TIER_DECLARED
        out[bits_test(self.planes["observed"], ids)] = TIER_OBSERVED
        out[bits_test(self.planes["verified"], ids)] = TIER_VERIFIED
        return out

    def recorded_mask(self, ids: np.ndarray | Iterable[int]) -> np.ndarray:
        """True where the cell is observed or verified (declared alone does not count)."""
        return self.tier_codes(ids) >= TIER_OBSERVED

    def tier(self, cell: CellLike) -> str:
        return TIER_NAMES[int(self.tier_codes(np.array([parse_cell(cell)]))[0])]

    def is_recorded(self, cell: CellLike) -> bool:
        return self.tier(cell) in ("observed", "verified")

    def lookup(self, cells: Iterable[CellLike]) -> list[dict[str, Any]]:
        ids = np.array([parse_cell(c) for c in cells], dtype=np.int64)
        codes = self.tier_codes(ids)
        return [
            {
                "id": int(i),
                "rgb": list(id_to_rgb(int(i))),
                "hex": id_to_hex(int(i)),
                "tier": TIER_NAMES[int(c)],
                "recorded": bool(c >= TIER_OBSERVED),
            }
            for i, c in zip(ids, codes)
        ]

    def palette_coverage(self, rgb: np.ndarray) -> dict[str, Any]:
        """Coverage of an (N, 3) uint8 palette/frame sample: how much of it is recorded, per tier."""
        arr = np.asarray(rgb)
        if arr.ndim != 3 and arr.ndim != 2:
            raise ValueError("rgb must be (N,3) or (H,W,3)")
        arr = arr.reshape(-1, 3).astype(np.int64)
        ids = np.unique((arr[:, 0] << 16) | (arr[:, 1] << 8) | arr[:, 2])
        codes = self.tier_codes(ids)
        n = int(ids.size)
        rec = int((codes >= TIER_OBSERVED).sum())
        return {
            "distinct": n,
            "recorded": rec,
            "verified": int((codes == TIER_VERIFIED).sum()),
            "observed": int((codes == TIER_OBSERVED).sum()),
            "declared": int((codes == TIER_DECLARED).sum()),
            "none": int((codes == TIER_NONE).sum()),
            "fraction_recorded": (rec / n) if n else 0.0,
        }

    def counts(self) -> dict[str, Any]:
        obs, ver, dec = (popcount(self.planes[p]) for p in PLANES)
        covered = popcount(self.planes["observed"] | self.planes["verified"])
        return {
            "space": SPACE_ID,
            "size": SPACE_SIZE,
            "observed": obs,
            "verified": ver,
            "declared": dec,
            "covered": covered,
            "pct_covered": round(100.0 * covered / SPACE_SIZE, 6),
        }

    # -- export -----------------------------------------------------------------------------------------------
    def export_snapshot(self, path: str | Path) -> dict[str, Any]:
        """Write a compact, checksummed snapshot (atomic). Returns the header."""
        from .color_cells import atomic_write_bytes

        body = b"".join(self.planes[p].tobytes() for p in PLANES)
        header = {
            "space": SPACE_ID,
            "version": SPACE_VERSION,
            "planes": list(PLANES),
            "exported_at": int(time.time()),
            "sha1": hashlib.sha1(body).hexdigest(),
            **self.counts(),
        }
        hb = json.dumps(header, sort_keys=True).encode("utf-8")
        blob = SNAPSHOT_MAGIC + struct.pack("<I", len(hb)) + hb + zlib.compress(body, 6)
        atomic_write_bytes(Path(path), blob)
        header["bytes"] = len(blob)
        return header


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Look up exact colour cells in the local registry")
    ap.add_argument("cells", nargs="*", help="cell id, #rrggbb or r,g,b")
    ap.add_argument("--snapshot", help="read from this MPCS1 snapshot instead of the live store")
    ap.add_argument("--export", help="write a compact snapshot to this path")
    args = ap.parse_args(argv)
    reg = RegistryLookup.from_snapshot(args.snapshot) if args.snapshot else RegistryLookup.from_store()
    out: dict[str, Any] = {"counts": reg.counts()}
    if args.cells:
        out["cells"] = reg.lookup(args.cells)
    if args.export:
        out["snapshot"] = reg.export_snapshot(args.export)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
/**
 * Exact 8-bit colour cells ("color.L2.a20"), TypeScript mirror of src/knowledge/color_cells.py.
 *
 * Cell id = (r << 16) | (g << 8) | b. The id space (2^24 cells) is stored as three bit planes (observed, verified,
 * declared) of 2 MiB each, cut into 32 chunks of 64 KiB (524,288 cells; chunk = id >> 19 = r >> 3). Bit i of a plane
 * is byte i >> 3, mask 1 << (i & 7) (LSB first). The parity vectors in tests/vectors/color_cells_vectors.json are
 * asserted by pytest and by cloudflare/test/colorCoverage.test.mjs.
 *
 * Pure functions, no I/O (decompression uses the platform's DecompressionStream).
 */
export const COLOR_SPACE_ID = "color.L2.a20";
export const COLOR_SPACE_NO = 1; // numeric namespace for row ids (id = no * 1024 + chunk_idx)
export const COLOR_SPACE_VERSION = 1;
export const COLOR_SPACE_SIZE = 1 << 24;
export const COLOR_CHUNK_BYTES = 64 * 1024;
export const COLOR_CHUNK_CELLS = COLOR_CHUNK_BYTES * 8;
export const COLOR_N_CHUNKS = COLOR_SPACE_SIZE / COLOR_CHUNK_CELLS; // 32
export const COLOR_PLANES = ["observed", "verified", "declared"] as const;
export type ColorPlane = (typeof COLOR_PLANES)[number];
export type ColorTier = "verified" | "observed" | "declared" | "none";

export interface ChunkPlanes {
  observed: Uint8Array;
  verified: Uint8Array;
  declared: Uint8Array;
}

export interface ChunkCounts {
  observed_n: number;
  verified_n: number;
  declared_n: number;
  covered_n: number;
  declared_only_n: number;
}

export function rgbToId(r: number, g: number, b: number): number {
  for (const v of [r, g, b]) if (!Number.isInteger(v) || v < 0 || v > 255) throw new RangeError("channel out of range");
  return (r << 16) | (g << 8) | b;
}

export function idToRgb(id: number): [number, number, number] {
  if (!Number.isInteger(id) || id < 0 || id >= COLOR_SPACE_SIZE) throw new RangeError("cell id out of range");
  return [(id >> 16) & 255, (id >> 8) & 255, id & 255];
}

export function idToHex(id: number): string {
  return "#" + idToRgb(id).map((v) => v.toString(16).padStart(2, "0")).join("");
}

export function chunkOf(id: number): number {
  return id >> 19;
}

export function rowId(chunkIdx: number): number {
  return COLOR_SPACE_NO * 1024 + chunkIdx;
}

/** Parse ?id= / ?rgb=r,g,b / ?hex=#rrggbb into a cell id, or null when invalid. */
export function parseCell(params: { id?: string | null; rgb?: string | null; hex?: string | null }): number | null {
  try {
    if (params.id != null && params.id !== "") {
      const n = Number(params.id);
      if (!Number.isInteger(n) || n < 0 || n >= COLOR_SPACE_SIZE) return null;
      return n;
    }
    if (params.rgb) {
      const p = params.rgb.split(",").map((s) => Number(s.trim()));
      return p.length === 3 ? rgbToId(p[0], p[1], p[2]) : null;
    }
    if (params.hex) {
      const m = /^#?([0-9a-fA-F]{6})$/.exec(params.hex.trim());
      return m ? parseInt(m[1], 16) : null;
    }
  } catch {
    return null;
  }
  return null;
}

/** D1 returns BLOB columns as number[] (older runtimes), ArrayBuffer or Uint8Array depending on the binding. */
export function toBytes(v: unknown, length = COLOR_CHUNK_BYTES): Uint8Array {
  const out = new Uint8Array(length); // always a fresh, 4-byte-aligned buffer
  if (v == null) return out;
  if (v instanceof ArrayBuffer) out.set(new Uint8Array(v).subarray(0, length));
  else if (ArrayBuffer.isView(v)) out.set(new Uint8Array(v.buffer, v.byteOffset, v.byteLength).subarray(0, length));
  else if (Array.isArray(v)) out.set((v as number[]).slice(0, length));
  return out;
}

export function emptyChunk(): ChunkPlanes {
  return { observed: new Uint8Array(COLOR_CHUNK_BYTES), verified: new Uint8Array(COLOR_CHUNK_BYTES), declared: new Uint8Array(COLOR_CHUNK_BYTES) };
}

function words(a: Uint8Array): Uint32Array {
  return new Uint32Array(a.buffer, a.byteOffset, a.byteLength >> 2);
}

/** dst |= src (word-wise: 16k ops per plane). Returns true when dst changed. */
export function orInto(dst: Uint8Array, src: Uint8Array): boolean {
  const d = words(dst);
  const s = words(src);
  let changed = false;
  for (let i = 0; i < d.length; i++) {
    const m = (d[i] | s[i]) >>> 0;
    if (m !== d[i]) {
      d[i] = m;
      changed = true;
    }
  }
  return changed;
}

function pop32(x: number): number {
  x = x - ((x >>> 1) & 0x55555555);
  x = (x & 0x33333333) + ((x >>> 2) & 0x33333333);
  return (((x + (x >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
}

export function popcount(a: Uint8Array): number {
  const w = words(a);
  let n = 0;
  for (let i = 0; i < w.length; i++) if (w[i]) n += pop32(w[i]);
  return n;
}

export function chunkCounts(c: ChunkPlanes): ChunkCounts {
  const o = words(c.observed);
  const v = words(c.verified);
  const d = words(c.declared);
  let covered = 0;
  let declaredOnly = 0;
  for (let i = 0; i < o.length; i++) {
    const cov = (o[i] | v[i]) >>> 0;
    if (cov) covered += pop32(cov);
    const only = (d[i] & ~cov) >>> 0;
    if (only) declaredOnly += pop32(only);
  }
  return { observed_n: popcount(c.observed), verified_n: popcount(c.verified), declared_n: popcount(c.declared), covered_n: covered, declared_only_n: declaredOnly };
}

export function testBit(plane: Uint8Array, idInChunk: number): boolean {
  return ((plane[idInChunk >> 3] >> (idInChunk & 7)) & 1) === 1;
}

export function tierOf(c: ChunkPlanes, id: number): { tier: ColorTier; observed: boolean; verified: boolean; declared: boolean } {
  const i = id & (COLOR_CHUNK_CELLS - 1);
  const observed = testBit(c.observed, i);
  const verified = testBit(c.verified, i);
  const declared = testBit(c.declared, i);
  const tier: ColorTier = verified ? "verified" : observed ? "observed" : declared ? "declared" : "none";
  return { tier, observed, verified, declared };
}

/** Merge incoming planes into existing ones (OR). Missing incoming planes are treated as empty. */
export function mergeChunk(existing: ChunkPlanes | null, incoming: Partial<ChunkPlanes>): { merged: ChunkPlanes; changed: boolean; counts: ChunkCounts } {
  const merged = existing ?? emptyChunk();
  let changed = existing == null;
  for (const p of COLOR_PLANES) {
    const src = incoming[p];
    if (src && orInto(merged[p], src)) changed = true;
  }
  return { merged, changed, counts: chunkCounts(merged) };
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Decode one plane of a sync payload: base64 of raw bytes ("raw") or of a zlib stream ("zlib"). Must be exactly 64 KiB. */
export async function decodePlane(b64: unknown, enc: string): Promise<Uint8Array | null> {
  if (b64 == null || b64 === "") return null;
  if (typeof b64 !== "string") throw new Error("plane must be a base64 string");
  let bytes = b64ToBytes(b64);
  if (enc === "zlib") {
    const ds = new DecompressionStream("deflate");
    const stream = new Blob([bytes]).stream().pipeThrough(ds);
    bytes = new Uint8Array(await new Response(stream).arrayBuffer());
  } else if (enc !== "raw") {
    throw new Error("unsupported enc: " + enc);
  }
  if (bytes.length !== COLOR_CHUNK_BYTES) throw new Error(`plane must be ${COLOR_CHUNK_BYTES} bytes, got ${bytes.length}`);
  return toBytes(bytes);
}
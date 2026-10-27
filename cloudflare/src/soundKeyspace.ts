/**
 * Sound v2 ("sound.L1") key space, TypeScript mirror of src/knowledge/keyspace.py.
 *
 * amp(12 log bins) x band(8 octaves) x flatness(4) x attack(4) x zcr(4) = 6144 cells. A cell key looks like
 * `s2.07-3-1-2-0`; its ordinal (cell id) is mixed-radix with amp most significant. Edges are frozen under
 * version 2; the parity vectors in tests/vectors/sound_v2_vectors.json are asserted by pytest and by
 * cloudflare/test/soundKeyspace.test.mjs so the two halves cannot drift.
 *
 * Pure functions, no I/O. v2 rows are ordinary static_sound rows whose sound_key starts with `s2.`.
 */
export const SOUND_V2_VERSION = 2;
export const SOUND_V2_PREFIX = "s2.";
export const SOUND_V2_AMP_MIN = 0.001;
export const SOUND_V2_AMP_BINS = 12;
export const SOUND_V2_BAND_EDGES = [100, 200, 400, 800, 1600, 3200, 6400] as const;
export const SOUND_V2_FLAT_EDGES = [0.15, 0.3, 0.5] as const;
export const SOUND_V2_ATTACK_EDGES = [0.35, 0.5, 0.65] as const;
export const SOUND_V2_ZCR_EDGES = [0.02, 0.06, 0.15] as const;
export const SOUND_V2_RADICES = [12, 8, 4, 4, 4] as const;
export const SOUND_V2_SPACE_SIZE = 12 * 8 * 4 * 4 * 4; // 6144

const KEY_RE = /^s2\.(\d{2})-(\d)-(\d)-(\d)-(\d)$/;

function num(v: unknown, d = 0): number {
  const f = typeof v === "number" ? v : Number(v);
  return Number.isFinite(f) ? f : d;
}

function edgeBin(value: number, edges: readonly number[]): number {
  for (let i = 0; i < edges.length; i++) if (value < edges[i]) return i;
  return edges.length;
}

export function ampBin(amplitude: unknown): number {
  const a = num(amplitude);
  if (a < SOUND_V2_AMP_MIN) return 0;
  const span = Math.log(1 / SOUND_V2_AMP_MIN);
  const idx = 1 + Math.floor((Math.log(Math.min(a, 1) / SOUND_V2_AMP_MIN) / span) * (SOUND_V2_AMP_BINS - 1));
  return Math.min(SOUND_V2_AMP_BINS - 1, idx);
}

export function soundV2Bins(
  amplitude: unknown, peakHz: unknown, flatness: unknown, attack: unknown, zcr: unknown,
): [number, number, number, number, number] {
  return [
    ampBin(amplitude),
    edgeBin(Math.max(0, num(peakHz)), SOUND_V2_BAND_EDGES),
    edgeBin(num(flatness, 0.5), SOUND_V2_FLAT_EDGES),
    edgeBin(num(attack), SOUND_V2_ATTACK_EDGES),
    edgeBin(num(zcr), SOUND_V2_ZCR_EDGES),
  ];
}

export function soundV2Ordinal(bins: readonly number[]): number {
  if (bins.length !== SOUND_V2_RADICES.length) throw new Error("expected 5 bins");
  let n = 0;
  bins.forEach((b, i) => {
    if (!Number.isInteger(b) || b < 0 || b >= SOUND_V2_RADICES[i]) throw new Error(`bin ${b} out of range`);
    n = n * SOUND_V2_RADICES[i] + b;
  });
  return n;
}

export function decodeSoundV2Ordinal(ordinal: number): [number, number, number, number, number] {
  if (!Number.isInteger(ordinal) || ordinal < 0 || ordinal >= SOUND_V2_SPACE_SIZE) {
    throw new Error(`ordinal ${ordinal} outside 0..${SOUND_V2_SPACE_SIZE - 1}`);
  }
  let n = ordinal;
  const out: number[] = [];
  for (let i = SOUND_V2_RADICES.length - 1; i >= 0; i--) {
    out.unshift(n % SOUND_V2_RADICES[i]);
    n = Math.floor(n / SOUND_V2_RADICES[i]);
  }
  return out as [number, number, number, number, number];
}

export function soundV2KeyFromBins(bins: readonly number[]): string {
  soundV2Ordinal(bins);
  const [a, b, f, k, z] = bins;
  return `${SOUND_V2_PREFIX}${String(a).padStart(2, "0")}-${b}-${f}-${k}-${z}`;
}

export function soundV2Key(amplitude: unknown, peakHz: unknown, flatness: unknown, attack: unknown, zcr: unknown): string {
  return soundV2KeyFromBins(soundV2Bins(amplitude, peakHz, flatness, attack, zcr));
}

/** Bins of a valid v2 key, or null (wrong shape or a bin outside its radix). */
export function parseSoundV2Key(key: unknown): [number, number, number, number, number] | null {
  if (typeof key !== "string") return null;
  const m = KEY_RE.exec(key);
  if (!m) return null;
  const bins = m.slice(1).map((g) => Number(g));
  if (bins.some((b, i) => b >= SOUND_V2_RADICES[i])) return null;
  return bins as [number, number, number, number, number];
}

/** Cheap prefix test for SQL-free routing; use parseSoundV2Key to validate. */
export function hasSoundV2Prefix(key: unknown): boolean {
  return typeof key === "string" && key.startsWith(SOUND_V2_PREFIX);
}

export function isSoundV2Key(key: unknown): boolean {
  return parseSoundV2Key(key) !== null;
}

export function soundV2KeyToOrdinal(key: string): number {
  const bins = parseSoundV2Key(key);
  if (!bins) throw new Error(`not a sound v2 key: ${JSON.stringify(key)}`);
  return soundV2Ordinal(bins);
}

export function soundV2OrdinalToKey(ordinal: number): string {
  return soundV2KeyFromBins(decodeSoundV2Ordinal(ordinal));
}

export function soundV2CellId(keyOrOrdinal: string | number): string {
  const n = typeof keyOrOrdinal === "number" ? keyOrOrdinal : soundV2KeyToOrdinal(keyOrOrdinal);
  return `sound.L1#${String(n).padStart(5, "0")}`;
}

/**
 * Hex bitmap of seen cells, identical to sound_v2.encode_bitmap in Python: the hex of the integer whose bit
 * `ordinal` is set (so ordinal 0 is bit 0 of the LAST hex digit), zero-padded to 1536 chars.
 */
export function encodeSeenBitmap(ordinals: Iterable<number>): string {
  const len = SOUND_V2_SPACE_SIZE / 4;
  const nibbles = new Array<number>(len).fill(0);
  for (const o of ordinals) {
    if (Number.isInteger(o) && o >= 0 && o < SOUND_V2_SPACE_SIZE) nibbles[len - 1 - (o >> 2)] |= 1 << (o & 3);
  }
  return nibbles.map((n) => n.toString(16)).join("");
}

export function decodeSeenBitmap(hex: unknown): Set<number> {
  const out = new Set<number>();
  const len = SOUND_V2_SPACE_SIZE / 4;
  if (typeof hex !== "string" || hex.length !== len || !/^[0-9a-f]+$/.test(hex)) return out;
  for (let i = 0; i < len; i++) {
    const n = parseInt(hex[len - 1 - i], 16);
    for (let b = 0; b < 4; b++) if (n & (1 << b)) out.add(i * 4 + b);
  }
  return out;
}
/**
 * Deterministic ids for learned_blends so repeats are free.
 *
 * Before: every blend was `INSERT ... VALUES (uuid(), ...)`, so the same (domain, output) was stored again on every
 * clip (13 rows + 2 index rows each, ~65% of the D1 file). Now id = "bl_" + sha256(domain + normalized output_json)
 * truncated to 128 bits, and the writer uses INSERT OR IGNORE on the existing PRIMARY KEY: an already-known blend
 * writes 0 rows. No schema change is needed.
 */

/** Stable JSON: sorted keys, numbers rounded to 3 decimals, strings trimmed, null/undefined dropped from objects. */
export function normalizeForHash(v: unknown): string {
  const norm = (x: unknown): unknown => {
    if (x === null || x === undefined) return null;
    if (typeof x === "number") return Number.isFinite(x) ? Math.round(x * 1000) / 1000 : null;
    if (typeof x === "string") return x.trim();
    if (typeof x === "boolean") return x;
    if (Array.isArray(x)) return x.map(norm);
    if (typeof x === "object") {
      const o = x as Record<string, unknown>;
      const out: Record<string, unknown> = {};
      for (const k of Object.keys(o).sort()) {
        const nv = norm(o[k]);
        if (nv !== null) out[k] = nv;
      }
      return out;
    }
    return String(x);
  };
  return JSON.stringify(norm(v));
}

function toHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function blendId(domain: unknown, output: unknown): Promise<string> {
  const text = `${String(domain ?? "").trim().toLowerCase()}\u0000${normalizeForHash(output)}`;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return "bl_" + toHex(digest).slice(0, 32);
}
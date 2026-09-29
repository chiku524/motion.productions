import type { VideoRecipe } from "../schema/recipe";

function randomUint32(): number {
  const c = globalThis.crypto;
  if (c?.getRandomValues) {
    const buf = new Uint32Array(1);
    c.getRandomValues(buf);
    return buf[0] ?? 0;
  }
  return Math.floor(Math.random() * 0x100000000);
}

/** Snap a channel onto the discovery color grid (tolerance 25). */
function binStep(base: number, steps: number): number {
  const start = Math.max(0, Math.min(10, Math.round(base / 25)));
  return ((start + steps) % 11) * 25;
}

function parseHex(hex: string): [number, number, number] | null {
  const raw = hex.trim().replace(/^#/, "");
  if (!/^[0-9A-Fa-f]{6}$/.test(raw)) return null;
  const n = parseInt(raw, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function toHex(r: number, g: number, b: number): string {
  const h = (v: number) => v.toString(16).padStart(2, "0");
  return `#${h(r)}${h(g)}${h(b)}`;
}

/**
 * Shift each scene onto a fresh grid cell and stamp meta.seed.
 * Same prompt planned twice does not reuse the same discovery colors.
 */
export function withUniqueSceneColors(recipe: VideoRecipe): VideoRecipe {
  const seed = randomUint32() % 0x7fffffff;
  const scenes = recipe.scenes.map((sc, i) => {
    const rgb = parseHex(sc.background.hex) ?? [25, 25, 46];
    const salt = (seed + i * 997) >>> 0;
    const r = binStep(rgb[0], 1 + (salt % 7));
    const g = binStep(rgb[1], 1 + ((salt >>> 8) % 5));
    const b = binStep(rgb[2], 1 + ((salt >>> 16) % 6));
    return { ...sc, background: { hex: toHex(r, g, b) } };
  });
  return {
    ...recipe,
    meta: { ...recipe.meta, seed },
    scenes,
  };
}

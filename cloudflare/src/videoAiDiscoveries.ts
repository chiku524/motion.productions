/**
 * Store Video AI recipe scene colors in the static color discovery table.
 * Procedural renders record their own stamps from the Python render service.
 */
import type { Env } from "./env";
import { writeDiscoveries } from "./discoveryWriter";

function binChannel(v: number): number {
  if (!Number.isFinite(v)) return 0;
  return Math.max(0, Math.min(250, Math.floor(v / 25) * 25));
}

function parseHex(hex: string): [number, number, number] | null {
  const raw = hex.trim().replace(/^#/, "");
  if (!/^[0-9A-Fa-f]{6}$/.test(raw)) return null;
  const n = parseInt(raw, 16);
  return [binChannel((n >> 16) & 255), binChannel((n >> 8) & 255), binChannel(n & 255)];
}

type SceneRecipe = {
  scenes?: { background?: { hex?: string } }[];
};

export async function recordRecipeColorDiscoveries(
  env: Env,
  recipe: unknown,
  sourcePrompt: string,
): Promise<number> {
  if (!recipe || typeof recipe !== "object") return 0;
  const scenes = (recipe as SceneRecipe).scenes;
  if (!Array.isArray(scenes) || !scenes.length) return 0;

  const seen = new Set<string>();
  const colors: { key: string; r: number; g: number; b: number }[] = [];
  for (const sc of scenes) {
    const hex = sc?.background?.hex;
    if (typeof hex !== "string") continue;
    const rgb = parseHex(hex);
    if (!rgb) continue;
    const key = `${rgb[0]}_${rgb[1]}_${rgb[2]}_1.0`;
    if (seen.has(key)) continue;
    seen.add(key);
    colors.push({ key, r: rgb[0], g: rgb[1], b: rgb[2] });
    if (colors.length >= 4) break;
  }
  if (!colors.length) return 0;

  // Shared batched upsert writer (one D1 batch, no lease/KV/cache invalidation).
  const prompt = sourcePrompt.trim().slice(0, 80);
  const out = await writeDiscoveries(env, {
    static_colors: colors.map((c) => ({ key: c.key, r: c.r, g: c.g, b: c.b, opacity: 1, source_prompt: prompt || undefined })),
  });
  const novel = (out.body.novel as { static_colors?: number } | undefined)?.static_colors ?? 0;
  return novel;
}

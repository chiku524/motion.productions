/**
 * Store Video AI recipe scene colors in the static color discovery table.
 * Procedural renders record their own stamps from the Python render service.
 */
import type { Env } from "./env";
import { bumpRegistryCounts, ensureStaticColorsFamilyColumns, getPrimaryDb } from "./db";
import { uuid } from "./http";
import { generateUniqueName } from "./naming";
import { classifyColorFamily, classifyColorShade } from "./colorBrowse";
import { acquireDiscoveryLease, releaseDiscoveryLease } from "./discoveryLease";
import { invalidateRegistryReadCaches } from "./browseCache";

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

  const lease = await acquireDiscoveryLease(env);
  if (!lease.ok) return 0;
  const db = getPrimaryDb(env);
  let novel = 0;
  try {
    const familyColsOk = await ensureStaticColorsFamilyColumns(db);
    const prompt = sourcePrompt.trim().slice(0, 80);
    for (const c of colors) {
      const existing = await db
        .prepare("SELECT id FROM static_colors WHERE color_key = ?")
        .bind(c.key)
        .first();
      if (existing) {
        await db.prepare("UPDATE static_colors SET count = count + 1 WHERE color_key = ?").bind(c.key).run();
        continue;
      }
      const name = await generateUniqueName(env);
      try {
        await db.prepare("INSERT OR IGNORE INTO name_reserve (name) VALUES (?)").bind(name).run();
      } catch {
        /* reserve is best-effort */
      }
      const sources = prompt ? JSON.stringify([prompt]) : null;
      if (familyColsOk) {
        const family = classifyColorFamily(c.r, c.g, c.b);
        const shade = classifyColorShade(c.r, c.g, c.b, family);
        await db
          .prepare(
            "INSERT INTO static_colors (id, color_key, r, g, b, opacity, count, sources_json, name, family, shade) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?)",
          )
          .bind(uuid(), c.key, c.r, c.g, c.b, sources, name, family, shade)
          .run();
      } else {
        await db
          .prepare(
            "INSERT INTO static_colors (id, color_key, r, g, b, opacity, count, sources_json, name) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)",
          )
          .bind(uuid(), c.key, c.r, c.g, c.b, sources, name)
          .run();
      }
      novel++;
    }
    if (novel > 0) {
      await bumpRegistryCounts(env, { static_colors: novel });
      await invalidateRegistryReadCaches(env);
    }
    return novel;
  } finally {
    await releaseDiscoveryLease(env, lease.holder);
  }
}

/**
 * Semantic naming helpers for registry backfill and discovery naming.
 */
import type { Env } from "./env";
import { getDb } from "./db";
import { SOUND_ORIGIN_PRIMARIES as GENERATED_SOUND_ORIGIN_PRIMARIES } from "./registryConstants.generated";

/** Everyday pure-sound origin primitives (sync with src/knowledge/blend_depth.py via gen_registry_constants_ts.py). */
export const SOUND_ORIGIN_PRIMARIES = [...GENERATED_SOUND_ORIGIN_PRIMARIES] as readonly string[];

export async function resolveUniqueBlendName(env: Env, base: string): Promise<string> {
  const db = getDb(env);
  let candidate = base;
  for (let i = 0; i < 100; i++) {
    const inReserve = await db.prepare("SELECT name FROM name_reserve WHERE name = ?").bind(candidate).first();
    const inBlends = await db.prepare("SELECT name FROM learned_blends WHERE name = ?").bind(candidate).first();
    if (!inReserve && !inBlends) return candidate;
    candidate = i === 0 ? base + "2" : base + (i + 2);
  }
  return base + (Math.floor(Math.random() * 9000) + 1000);
}

// Semantic name parts (mirrors Python blend_names.py) — no gibberish
export const SEMANTIC_START = ["am", "vel", "cor", "sil", "riv", "mist", "dawn", "dusk", "wave", "drift", "soft", "deep", "cool", "warm", "star", "sky", "sea", "frost", "dew", "rose", "gold", "pearl", "sage", "mint", "vine", "bloom", "shade", "glow", "flow", "haze", "vale", "storm", "leaf", "cloud", "wind", "rain", "brook", "sun", "lune", "slate", "flax", "iron", "stone", "oak", "pine", "cedar", "willow", "maple", "ivory", "copper", "bronze", "chalk", "linen", "wool"];
export const SEMANTIC_END = ["ber", "vet", "al", "ver", "er", "en", "ow", "or", "um", "in", "ar", "ace", "ine", "ure", "ish", "ing", "lyn", "tor", "nel", "ton", "ley", "well", "brook", "field", "wood", "light", "fall", "rise", "ford", "dale", "mont", "view", "crest", "haven", "mere", "stone", "vale", "mist", "glow", "bloom", "stream", "ridge", "shore"];
export const SEMANTIC_WORDS = ["amber", "velvet", "coral", "silver", "river", "mist", "dawn", "dusk", "wave", "drift", "soft", "deep", "cool", "warm", "calm", "star", "sky", "sea", "frost", "dew", "rose", "gold", "pearl", "sage", "mint", "vine", "bloom", "shade", "glow", "flow", "haze", "vale", "storm", "leaf", "cloud", "wind", "rain", "brook", "sun", "ember", "azure", "lark", "fern", "cliff", "marsh", "glen", "haven", "fall", "rise", "ford", "dale", "mont", "view", "crest", "mere", "worth", "slate", "stone", "iron", "flax", "oak", "pine", "cedar", "willow", "maple", "ivory", "copper", "bronze", "chalk", "linen", "wool", "silk", "jade"];

export function inventSemanticWord(seed: number): string {
  const r = Math.abs(seed) % 0x7fffffff;
  const wordIdx = r % SEMANTIC_WORDS.length;
  const candidate = SEMANTIC_WORDS[wordIdx];
  if (candidate.length >= 4 && candidate.length <= 18) return candidate;
  const sIdx = (r >> 7) % SEMANTIC_START.length;
  const start = SEMANTIC_START[sIdx];
  for (let k = 0; k < SEMANTIC_END.length; k++) {
    const rr = (r * 7919 + 1237 + k) % 0x7fffffff;
    const eIdx = rr % SEMANTIC_END.length;
    const end = SEMANTIC_END[eIdx];
    if (start && end && start[start.length - 1] === end[0]) continue;
    let word = start + end;
    if (word.length > 18) word = word.slice(0, 18);
    if (word.length < 4) word = word + end.slice(0, Math.min(end.length, 4 - word.length));
    return word.slice(0, 18);
  }
  return (start + SEMANTIC_END[0]).slice(0, 18);
}

export function toTitleCase(s: string): string {
  return s.length > 1 ? s[0].toUpperCase() + s.slice(1).toLowerCase() : s.toUpperCase();
}

export function isGibberishName(name: string | null): boolean {
  if (!name || typeof name !== "string") return false;
  const n = name.trim().toLowerCase();
  if (n.length < 4) return false;
  if (/^dsc_[a-f0-9]+$/i.test(n)) return true;
  if (n.startsWith("novel") && /^\d+$/.test(n.slice(5))) return true;
  if (/^(theme|plot|setting|scene|genre|mood|style)_/.test(n)) return true;
  if (/\d{2,}/.test(n)) return true;
  if (SEMANTIC_WORDS.some((w) => w === n)) return false;
  if (SEMANTIC_START.some((s) => n.startsWith(s))) return false;
  if (SEMANTIC_END.some((e) => n.endsWith(e))) return false;
  if (n.length <= 8) return false;
  return true;
}

export function titleCaseLabel(value: string): string {
  const v = (value || "").trim();
  if (!v) return "";
  return v.split(/[\s_-]+/).filter(Boolean).map((w) => (w.length > 1 ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w.toUpperCase())).join(" ");
}

export function shouldBackfillNarrativeName(name: string | null, entryKey: string, value: string): boolean {
  const readable = titleCaseLabel(value || entryKey);
  if (!name || !name.trim()) return true;
  const n = name.trim();
  if (n === readable) return false;
  if (isGibberishName(n)) return true;
  const ek = (entryKey || "").toLowerCase();
  if (ek.length >= 3 && !n.toLowerCase().includes(ek)) return true;
  return false;
}

// Gibberish prompt detection (mirrors Python interpretation/gibberish.py)
export const KNOWN_WORDS = new Set([
  "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
  "is", "was", "are", "were", "be", "been", "have", "has", "had", "do", "does", "did", "will", "would",
  "could", "should", "can", "may", "might", "must", "shall", "video", "motion", "flow", "calm", "slow",
  "fast", "bright", "dark", "soft", "dreamy", "abstract", "cinematic", "minimal", "realistic", "style",
  "feel", "look", "vibe", "mood", "tone", "color", "colours", "blue", "red", "green", "ocean", "sunset",
  "night", "day", "golden", "hour", "warm", "cool", "gradient", "smooth", "gentle", "peaceful",
  "energetic", "dynamic", "static", "pan", "zoom", "tilt", "tracking", "handheld", "documentary",
  "neon", "pastel", "vintage", "modern", "retro", "nostalgic", "melancholic", "serene", "dramatic",
  "subtle", "bold", "muted", "vibrant", "intense", "explainer", "tutorial", "explain", "gradual",
  "symmetric", "silence", "ambient", "music", "sfx", "balanced", "slight", "bilateral", "centered",
  "lit", "chill", "vibing", "vibes", "lowkey", "glowy", "mellow",
]);
export const GIBBERISH_RE = /(?:[bcdfghjklmnpqrstvwxz]{4,}|([a-z]{2})\1{2,}|[qxjz]{2,})/i;

// RGB → semantic color vocabulary (mirrors Python blend_names.py)
export const RGB_COLOR_VOCAB: Record<string, string[]> = {
  shadow: ["shadow", "charcoal", "obsidian", "onyx", "raven", "coal", "ink"],
  graphite: ["graphite", "iron", "lead", "pewter", "gunmetal"],
  slate: ["slate", "stone", "flint", "ash", "steel", "silver"],
  mist: ["mist", "fog", "haze", "pearl", "cloud", "frost"],
  ember: ["ember", "rust", "copper", "terracotta", "brick"],
  sunset: ["sunset", "coral", "salmon", "blush", "apricot", "tangerine"],
  rust: ["rust", "sienna", "ochre", "bronze", "umber"],
  moss: ["moss", "sage", "fern", "olive", "jade"],
  forest: ["forest", "pine", "cedar", "evergreen", "laurel"],
  olive: ["olive", "khaki", "sand", "tan", "taupe"],
  teal: ["teal", "turquoise", "aqua", "cyan", "mint"],
  violet: ["violet", "lavender", "lilac", "plum", "amethyst"],
  ocean: ["ocean", "navy", "indigo", "sapphire", "azure"],
  midnight: ["midnight", "twilight", "dusk", "deep", "abyss"],
  neutral: ["stone", "sand", "linen", "ivory", "cream"],
};

export function rgbToSemanticHint(r: number, g: number, b: number): string {
  const mx = Math.max(r, g, b);
  const mn = Math.min(r, g, b);
  if (mx < 50) return "shadow";
  if (mx - mn < 40) {
    const lum = (r + g + b) / 3;
    if (lum < 80) return "graphite";
    if (lum < 140) return "slate";
    return "mist";
  }
  if (r >= g && r >= b && r > 0) return b > g ? "ember" : r > 180 ? "sunset" : "rust";
  if (g >= r && g >= b && g > 0) return r > b ? "moss" : g > 120 ? "forest" : "olive";
  if (b >= r && b >= g && b > 0) return g > r ? "teal" : r > g ? "violet" : b > 140 ? "ocean" : "midnight";
  return "neutral";
}

/** Cascade oldName→newName to prompts and sources when backfilling registry names. */
export async function cascadeNameUpdate(env: Env, oldName: string, newName: string): Promise<void> {
  if (!oldName || oldName === newName) return;
  const db = getDb(env);
  const like = "%" + oldName.replace(/[%_]/g, "\\$&") + "%";
  const tables: { table: string; col: string }[] = [
    { table: "learning_runs", col: "prompt" },
    { table: "interpretations", col: "prompt" },
    { table: "interpretations", col: "instruction_json" },
    { table: "jobs", col: "prompt" },
    { table: "learned_blends", col: "source_prompt" },
    { table: "learned_blends", col: "inputs_json" },
    { table: "learned_blends", col: "output_json" },
    { table: "learned_blends", col: "primitive_depths_json" },
    { table: "static_colors", col: "sources_json" },
    { table: "static_sound", col: "sources_json" },
    { table: "learned_colors", col: "sources_json" },
    { table: "learned_motion", col: "sources_json" },
    { table: "learned_lighting", col: "sources_json" },
    { table: "learned_composition", col: "sources_json" },
    { table: "learned_graphics", col: "sources_json" },
    { table: "learned_temporal", col: "sources_json" },
    { table: "learned_technical", col: "sources_json" },
    { table: "learned_gradient", col: "sources_json" },
    { table: "learned_camera", col: "sources_json" },
    { table: "learned_time", col: "sources_json" },
    { table: "narrative_entries", col: "sources_json" },
  ];
  for (const { table, col } of tables) {
    try {
      await db.prepare(
        `UPDATE ${table} SET ${col} = REPLACE(${col}, ?, ?) WHERE ${col} LIKE ? ESCAPE '\\'`
      )
        .bind(oldName, newName, like)
        .run();
    } catch {
      /* table/col may not exist */
    }
  }
}

export function shouldBackfillColorName(name: string | null): boolean {
  if (!name || typeof name !== "string") return true;
  const n = name.trim().toLowerCase();
  if (n.length < 4) return false;
  const realColorWords = new Set([
    "amber", "velvet", "coral", "silver", "river", "mist", "dawn", "dusk", "wave",
    "slate", "stone", "iron", "oak", "pine", "cedar", "jade", "shadow", "graphite",
    "ember", "rust", "sienna", "sage", "fern", "olive", "teal", "ocean", "navy",
    "violet", "lavender", "pearl", "cloud", "frost", "ink", "coal", "ash",
  ]);
  if (realColorWords.has(n)) return false;
  if (n.startsWith("color_")) return true;
  if (SEMANTIC_WORDS.some((w) => w === n)) return false;
  if (SEMANTIC_START.some((s) => n.startsWith(s)) && SEMANTIC_END.some((e) => n.endsWith(e))) return true;
  return isGibberishName(name);
}

export function isGibberishPrompt(prompt: string, strict = false): boolean {
  if (!prompt || typeof prompt !== "string") return true;
  const text = prompt.trim();
  if (text.length < 3) return false;
  const lower = text.toLowerCase();
  if (GIBBERISH_RE.test(lower)) return true;
  const words = lower.match(/[a-z]{3,}/g) || [];
  if (!words.length) return false;
  const known = words.filter((w) => KNOWN_WORDS.has(w)).length;
  const ratio = known / words.length;
  const longUnknown = words.filter((w) => w.length >= 10 && !KNOWN_WORDS.has(w));
  if (longUnknown.length > 0) return true;
  const avgLen = words.reduce((s, w) => s + w.length, 0) / words.length;
  if (strict) {
    if (ratio < 0.25 && avgLen > 6) return true;
    if (ratio < 0.15) return true;
  } else if (ratio < 0.15 && avgLen > 7) return true;
  return false;
}

export const PRIMITIVE_TONES = new Set(["silent", "silence", "low", "mid", "high", "neutral"]);
export const SEMANTIC_TONE_TO_PRIMITIVE: Record<string, string> = {
  calm: "mid", tense: "mid", dark: "low", uplifting: "high", dreamy: "mid",
  bright: "high", moody: "mid", energetic: "high", ambient: "mid", music: "mid",
  full: "mid", sfx: "high", neutral: "mid", peaceful: "mid", dramatic: "mid",
  melancholy: "low", happy: "high", sad: "low", scary: "mid", angry: "high",
};
export const TONE_TO_NOISE: Record<string, string> = {
  silent: "silence", silence: "silence",
  low: "rumble", mid: "tone", high: "hiss", neutral: "tone",
};

export function normalizeToneToPrimitive(tone: string): string {
  const t = (tone || "").trim().toLowerCase();
  if (!t || t === "unknown") return "mid";
  if (PRIMITIVE_TONES.has(t)) return t === "silent" || t === "silence" ? "silent" : t;
  return SEMANTIC_TONE_TO_PRIMITIVE[t] ?? "mid";
}

export function classifySoundPrimitive(amplitude: number, tone: string): string {
  const toneLower = normalizeToneToPrimitive(tone);
  const strength = Math.min(1, Math.max(0, amplitude));
  if (strength < 0.01 || toneLower === "silent" || toneLower === "silence") return "silence";
  return TONE_TO_NOISE[toneLower] ?? "tone";
}

export function normalizeTimbreToPrimitive(timbre: string, amplitude = 0.5, tone = "mid"): string {
  const t = (timbre || "").trim().toLowerCase();
  if ((SOUND_ORIGIN_PRIMARIES as readonly string[]).includes(t)) return t;
  const band = normalizeToneToPrimitive(t || tone);
  return classifySoundPrimitive(amplitude, band);
}

export function sanitizePureSoundKey(key: string): string {
  if (!key || !key.includes("_")) return key;
  const parts = key.split("_");
  if (parts.length < 3) return key;
  const amp = Math.round((parseFloat(parts[0]) || 0) * 100) / 100;
  const tone = normalizeToneToPrimitive(parts[1]);
  const timbre = normalizeTimbreToPrimitive(parts.slice(2).join("_"), amp, tone);
  return `${amp}_${tone}_${timbre}`;
}

export function pureSoundKeyHasLeak(key: string): boolean {
  return sanitizePureSoundKey(key) !== key;
}

export function computeMotionDepth(motionLevel: number): Record<string, number> {
  const speeds = ["static", "slow", "medium", "fast"] as const;
  const levels = [0, 5, 12, 25];
  const w = [0, 0, 0, 0];
  for (let i = 0; i < 4; i++) {
    if (i === 0) w[i] = Math.max(0, 1 - motionLevel / 5);
    else if (i === 3) w[i] = Math.max(0, (motionLevel - 15) / 15);
    else w[i] = Math.max(0, 1 - Math.abs(motionLevel - levels[i]) / 10);
  }
  let total = w.reduce((a, b) => a + b, 0);
  if (total <= 0) { w[1] = 1; total = 1; }
  const out: Record<string, number> = {};
  for (let i = 0; i < 4; i++) {
    if (w[i] > 0.01) out[speeds[i]] = Math.round((w[i] / total) * 1000) / 1000;
  }
  return out;
}

export async function generateUniqueName(env: Env): Promise<string> {
  const db = getDb(env);
  for (let attempt = 0; attempt < 50; attempt++) {
    const seed = Math.floor(Math.random() * 1000000) + attempt * 7919;
    const word = inventSemanticWord(seed);
    if (word.length >= 4) {
      const name = toTitleCase(word);
      const inReserve = await db.prepare("SELECT name FROM name_reserve WHERE name = ?").bind(name).first();
      const inBlends = await db.prepare("SELECT name FROM learned_blends WHERE name = ?").bind(name).first();
      const inStatic = await db.prepare("SELECT name FROM static_colors WHERE name = ?").bind(name).first();
      const inLearned = await db.prepare("SELECT name FROM learned_colors WHERE name = ?").bind(name).first();
      if (!inReserve && !inBlends && !inStatic && !inLearned) return name;
    }
  }
  const n = (Math.floor(Math.random() * 100000) + 1) % 100000;
  return "Novel" + n.toString().padStart(5, "0");
}

export async function logEvent(env: Env, eventType: string, jobId: string | null, payload: Record<string, unknown> | null): Promise<void> {
  const db = getDb(env);
  const id = crypto.randomUUID();
  await db.prepare("INSERT INTO events (id, event_type, job_id, payload_json) VALUES (?, ?, ?, ?)")
    .bind(id, eventType, jobId, payload ? JSON.stringify(payload) : null)
    .run();
}

export function aggregateLearningRuns(
  rows: { prompt: string; spec_json: string; analysis_json: string }[]
): Record<string, unknown> {
  if (rows.length === 0) return { total_runs: 0, by_palette: {}, by_keyword: {}, overall: {} };
  const byPalette: Record<string, { count: number; motion: number[]; brightness: number[] }> = {};
  const byKeyword: Record<string, { count: number; motion: number[]; brightness: number[] }> = {};
  const allMotion: number[] = [];
  const allBrightness: number[] = [];
  const allContrast: number[] = [];

  const words = (s: string) => new Set((s || "").toLowerCase().match(/[a-z]+/g) || []);

  for (const r of rows) {
    const spec = JSON.parse(r.spec_json) as Record<string, unknown>;
    const analysis = JSON.parse(r.analysis_json) as Record<string, unknown>;
    const palette = (spec.palette_name as string) || "default";
    byPalette[palette] = byPalette[palette] || { count: 0, motion: [], brightness: [] };
    byPalette[palette].count++;
    byPalette[palette].motion.push((analysis.motion_level as number) ?? 0);
    byPalette[palette].brightness.push((analysis.mean_brightness as number) ?? 0);

    for (const w of words(r.prompt)) {
      byKeyword[w] = byKeyword[w] || { count: 0, motion: [], brightness: [] };
      byKeyword[w].count++;
      byKeyword[w].motion.push((analysis.motion_level as number) ?? 0);
      byKeyword[w].brightness.push((analysis.mean_brightness as number) ?? 0);
    }
    allMotion.push((analysis.motion_level as number) ?? 0);
    allBrightness.push((analysis.mean_brightness as number) ?? 0);
    allContrast.push((analysis.mean_contrast as number) ?? 0);
  }

  const summarize = (v: { count: number; motion: number[]; brightness: number[] }) => ({
    count: v.count,
    mean_motion_level: v.motion.reduce((a, b) => a + b, 0) / v.motion.length || 0,
    mean_brightness: v.brightness.reduce((a, b) => a + b, 0) / v.brightness.length || 0,
  });

  const reportByPalette: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(byPalette)) reportByPalette[k] = summarize(v);
  const reportByKeyword: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(byKeyword)) reportByKeyword[k] = summarize(v);

  const n = rows.length;
  return {
    total_runs: n,
    by_palette: reportByPalette,
    by_keyword: reportByKeyword,
    overall: {
      mean_motion_level: allMotion.reduce((a, b) => a + b, 0) / n,
      mean_brightness: allBrightness.reduce((a, b) => a + b, 0) / n,
      mean_contrast: allContrast.reduce((a, b) => a + b, 0) / n,
    },
  };
}

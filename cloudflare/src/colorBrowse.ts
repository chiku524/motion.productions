/**
 * Hue-family / shade classification for the public color registry explorer.
 * Computed from RGB at request time (no D1 hue columns).
 */

export type ColorFamilyId =
  | "red"
  | "orange"
  | "yellow"
  | "green"
  | "teal"
  | "blue"
  | "purple"
  | "pink"
  | "brown"
  | "gray"
  | "white"
  | "black";

export type ColorShadeId = "deep" | "mid" | "light" | "muted";

export const COLOR_FAMILY_META: ReadonlyArray<{ id: ColorFamilyId; label: string }> = [
  { id: "red", label: "Red" },
  { id: "orange", label: "Orange" },
  { id: "yellow", label: "Yellow" },
  { id: "green", label: "Green" },
  { id: "teal", label: "Teal" },
  { id: "blue", label: "Blue" },
  { id: "purple", label: "Purple" },
  { id: "pink", label: "Pink" },
  { id: "brown", label: "Brown" },
  { id: "gray", label: "Gray" },
  { id: "white", label: "White" },
  { id: "black", label: "Black" },
];

export const COLOR_SHADE_META: ReadonlyArray<{ id: ColorShadeId; label: string }> = [
  { id: "deep", label: "Deep" },
  { id: "mid", label: "Mid" },
  { id: "light", label: "Light" },
  { id: "muted", label: "Muted" },
];

export type Hsl = { h: number; s: number; l: number };

/** r,g,b in 0–255 → HSL with h in [0,360), s/l in [0,1]. */
export function rgbToHsl(r: number, g: number, b: number): Hsl {
  const R = Math.max(0, Math.min(255, Number(r) || 0)) / 255;
  const G = Math.max(0, Math.min(255, Number(g) || 0)) / 255;
  const B = Math.max(0, Math.min(255, Number(b) || 0)) / 255;
  const max = Math.max(R, G, B);
  const min = Math.min(R, G, B);
  const l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0, l };
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h = 0;
  switch (max) {
    case R:
      h = ((G - B) / d + (G < B ? 6 : 0)) / 6;
      break;
    case G:
      h = ((B - R) / d + 2) / 6;
      break;
    default:
      h = ((R - G) / d + 4) / 6;
      break;
  }
  return { h: h * 360, s, l };
}

/** Representative RGB for empty family cards / UI samples. */
export const FAMILY_SAMPLE_RGB: Record<ColorFamilyId, [number, number, number]> = {
  red: [200, 48, 48],
  orange: [230, 130, 40],
  yellow: [230, 200, 50],
  green: [50, 160, 70],
  teal: [30, 160, 160],
  blue: [50, 100, 210],
  purple: [130, 70, 190],
  pink: [220, 100, 160],
  brown: [140, 90, 50],
  gray: [140, 140, 140],
  white: [245, 245, 245],
  black: [30, 30, 30],
};

export function classifyColorFamily(r: number, g: number, b: number): ColorFamilyId {
  const { h, s, l } = rgbToHsl(r, g, b);
  if (l >= 0.92 && s < 0.2) return "white";
  if (l <= 0.08) return "black";
  if (s < 0.12) return "gray";
  // Brown: low-mid lightness oranges/reds
  if (l < 0.45 && s >= 0.12 && h >= 15 && h < 55) return "brown";
  if (h < 15 || h >= 345) return "red";
  if (h < 40) return "orange";
  if (h < 70) return "yellow";
  if (h < 160) return "green";
  if (h < 195) return "teal";
  if (h < 255) return "blue";
  if (h < 290) return "purple";
  if (h < 345) return "pink";
  return "red";
}

/**
 * Shade within a family. Muted wins when saturation is low (but not gray/white/black families).
 */
export function classifyColorShade(r: number, g: number, b: number, family?: ColorFamilyId): ColorShadeId {
  const { s, l } = rgbToHsl(r, g, b);
  const fam = family ?? classifyColorFamily(r, g, b);
  if (fam !== "gray" && fam !== "white" && fam !== "black" && s < 0.28 && l > 0.15 && l < 0.85) {
    return "muted";
  }
  if (l < 0.35) return "deep";
  if (l > 0.68) return "light";
  return "mid";
}

export type ClassifiedColor = {
  key: string;
  name: string;
  r: number;
  g: number;
  b: number;
  count: number;
  family: ColorFamilyId;
  shade: ColorShadeId;
  depth_breakdown: Record<string, number>;
  primitives: string[];
};

const PRIMITIVE_MIN_PCT = 5;

/** Parse depth_breakdown_json into percent map of color primitives (≥ PRIMITIVE_MIN_PCT). */
export function parseColorPrimitives(depthJson: string | null | undefined): {
  depth_breakdown: Record<string, number>;
  primitives: string[];
} {
  const depth_breakdown: Record<string, number> = {};
  if (!depthJson) return { depth_breakdown, primitives: [] };
  try {
    const stored = JSON.parse(depthJson) as Record<string, unknown>;
    const raw: Record<string, number> = {};
    const oc = stored.origin_colors as Record<string, number> | undefined;
    if (oc && typeof oc === "object") {
      for (const [k, v] of Object.entries(oc)) {
        if (k === "opacity" || typeof v !== "number") continue;
        raw[k] = v <= 1 ? Math.round(v * 100) : Math.round(v);
      }
    }
    for (const [k, v] of Object.entries(stored)) {
      if (k === "origin_colors" || k === "opacity" || typeof v !== "number") continue;
      raw[k] = v <= 1 ? Math.round(v * 100) : Math.round(v);
    }
    for (const [k, v] of Object.entries(raw)) {
      if (v >= PRIMITIVE_MIN_PCT) depth_breakdown[k] = v;
    }
  } catch {
    /* ignore */
  }
  const primitives = Object.keys(depth_breakdown).sort();
  return { depth_breakdown, primitives };
}

export function classifyStaticColorRow(row: {
  color_key: string;
  r: number;
  g: number;
  b: number;
  name: string | null;
  count: number;
  depth_breakdown_json?: string | null;
}): ClassifiedColor {
  const key = (() => {
    const k = row.color_key || "";
    const i = k.indexOf("_");
    return i > 0 ? k.slice(0, i) : k;
  })();
  const family = classifyColorFamily(row.r, row.g, row.b);
  const shade = classifyColorShade(row.r, row.g, row.b, family);
  const { depth_breakdown, primitives } = parseColorPrimitives(row.depth_breakdown_json);
  return {
    key,
    name: (row.name || key).trim() || key,
    r: row.r,
    g: row.g,
    b: row.b,
    count: row.count || 1,
    family,
    shade,
    depth_breakdown,
    primitives,
  };
}

export function colorMatchesPrimitives(item: ClassifiedColor, required: string[]): boolean {
  if (!required.length) return true;
  const set = new Set(item.primitives.map((p) => p.toLowerCase()));
  return required.every((p) => set.has(p.toLowerCase()));
}

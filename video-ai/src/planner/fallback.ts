import type { VideoRecipe } from "../schema/recipe";

function fnv1a32(input: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

function hueToHex(h: number): string {
  const s = 0.65;
  const l = 0.45;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let rp = 0,
    gp = 0,
    bp = 0;
  if (h < 60) [rp, gp, bp] = [c, x, 0];
  else if (h < 120) [rp, gp, bp] = [x, c, 0];
  else if (h < 180) [rp, gp, bp] = [0, c, x];
  else if (h < 240) [rp, gp, bp] = [0, x, c];
  else if (h < 300) [rp, gp, bp] = [x, 0, c];
  else [rp, gp, bp] = [c, 0, x];
  const to = (v: number) =>
    Math.round((v + m) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${to(rp)}${to(gp)}${to(bp)}`;
}

/**
 * Deterministic recipe when no LLM key is configured (local demos / tests).
 */
export function planFallback(prompt: string, targetDurationSec: number): VideoRecipe {
  const h = fnv1a32(prompt);
  const sceneCount = 4 + (h % 3);
  const per = Math.max(2, Math.min(8, Math.floor(targetDurationSec / sceneCount)));
  const scenes: VideoRecipe["scenes"] = [];
  for (let i = 0; i < sceneCount; i++) {
    const hue = (h >>> (i * 5)) % 360;
    const dur =
      i === sceneCount - 1
        ? Math.max(2, targetDurationSec - per * (sceneCount - 1))
        : per;
    const snippet = prompt.trim().slice(0, 72) + (prompt.length > 72 ? "…" : "");
    scenes.push({
      durationSec: Math.min(120, Math.max(2, dur)),
      background: { hex: hueToHex(hue) },
      caption: i === 0 ? snippet || "Video AI" : undefined,
      captionMotion:
        i === 0
          ? {
              keyframes: [
                { tSec: 0, xNorm: 0.5, yNorm: 0.45, opacity: 0, scale: 0.98 },
                { tSec: 0.35, xNorm: 0.5, yNorm: 0.45, opacity: 1, scale: 1 },
              ],
            }
          : undefined,
    });
  }
  return {
    meta: { width: 1080, height: 1920, fps: 30, title: "Demo" },
    scenes,
  };
}

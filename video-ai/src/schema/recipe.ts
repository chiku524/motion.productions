import { z } from "zod";

const hexColor = z
  .string()
  .regex(/^#[0-9A-Fa-f]{6}$/, "Expected #RRGGBB");

export const KeyframeSchema = z.object({
  tSec: z.number().min(0),
  xNorm: z.number().min(0).max(1).optional(),
  yNorm: z.number().min(0).max(1).optional(),
  scale: z.number().positive().max(3).optional(),
  opacity: z.number().min(0).max(1).optional(),
});

export const SceneSchema = z.object({
  durationSec: z.number().positive().max(120),
  background: z.object({
    hex: hexColor,
  }),
  caption: z.string().max(800).optional(),
  /** Optional motion hints for the caption layer (normalized 0–1 = fraction of frame). */
  captionMotion: z
    .object({
      keyframes: z.array(KeyframeSchema).min(1).max(32),
    })
    .optional(),
});

export const VideoRecipeSchema = z.object({
  meta: z.object({
    width: z.number().int().min(320).max(3840),
    height: z.number().int().min(320).max(3840),
    fps: z.number().int().min(12).max(60).default(30),
    title: z.string().max(200).optional(),
  }),
  scenes: z.array(SceneSchema).min(1).max(80),
});

export type VideoRecipe = z.infer<typeof VideoRecipeSchema>;
export type Scene = z.infer<typeof SceneSchema>;
export type Keyframe = z.infer<typeof KeyframeSchema>;

export function totalDurationSec(recipe: VideoRecipe): number {
  return recipe.scenes.reduce((s, sc) => s + sc.durationSec, 0);
}

export function clampRecipeToMaxDuration(
  recipe: VideoRecipe,
  maxSec: number,
): VideoRecipe {
  let remaining = maxSec;
  const scenes: Scene[] = [];
  for (const sc of recipe.scenes) {
    if (remaining <= 0) break;
    const d = Math.min(sc.durationSec, remaining);
    if (d > 0) scenes.push({ ...sc, durationSec: d });
    remaining -= d;
  }
  if (scenes.length === 0) {
    return {
      ...recipe,
      scenes: [{ durationSec: Math.min(2, maxSec), background: { hex: "#1a1a2e" } }],
    };
  }
  return { ...recipe, scenes };
}

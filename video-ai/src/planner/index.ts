import { planFallback } from "./fallback";
import { withUniqueSceneColors } from "./unique";
import { planWithOpenAI } from "./openai";
import {
  VideoRecipeSchema,
  clampRecipeToMaxDuration,
  type VideoRecipe,
} from "../schema/recipe";

export type PlanOptions = {
  prompt: string;
  targetDurationSec?: number;
  maxDurationSec?: number;
  openaiApiKey?: string;
  openaiModel?: string;
};

const DEFAULT_TARGET = 32;
const DEFAULT_MAX = 300;

export async function planRecipe(opts: PlanOptions): Promise<{
  recipe: VideoRecipe;
  source: "openai" | "fallback";
}> {
  const target = Math.min(
    opts.maxDurationSec ?? DEFAULT_MAX,
    Math.max(4, opts.targetDurationSec ?? DEFAULT_TARGET),
  );
  const maxDur = Math.min(opts.maxDurationSec ?? DEFAULT_MAX, 600);

  const finish = (recipe: VideoRecipe, source: "openai" | "fallback") => {
    const unique = withUniqueSceneColors(recipe);
    const prompt = opts.prompt.trim().slice(0, 2000);
    return {
      recipe: {
        ...unique,
        meta: { ...unique.meta, prompt: unique.meta.prompt || prompt },
      },
      source,
    };
  };

  if (opts.openaiApiKey) {
    const recipe = await planWithOpenAI(opts.openaiApiKey, opts.openaiModel ?? "gpt-4o-mini", {
      prompt: opts.prompt,
      targetDurationSec: target,
      maxDurationSec: maxDur,
    });
    return finish(recipe, "openai");
  }

  const raw = planFallback(opts.prompt, target);
  const recipe = VideoRecipeSchema.parse(raw);
  return finish(clampRecipeToMaxDuration(recipe, maxDur), "fallback");
}

export { planWithOpenAI } from "./openai";
export { planFallback } from "./fallback";
export { RECIPE_JSON_INSTRUCTIONS } from "./system-prompt";

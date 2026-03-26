import { planFallback } from "./fallback";
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

  if (opts.openaiApiKey) {
    const recipe = await planWithOpenAI(opts.openaiApiKey, opts.openaiModel ?? "gpt-4o-mini", {
      prompt: opts.prompt,
      targetDurationSec: target,
      maxDurationSec: maxDur,
    });
    return { recipe, source: "openai" };
  }

  const raw = planFallback(opts.prompt, target);
  const recipe = VideoRecipeSchema.parse(raw);
  return {
    recipe: clampRecipeToMaxDuration(recipe, maxDur),
    source: "fallback",
  };
}

export { planWithOpenAI } from "./openai";
export { planFallback } from "./fallback";
export { RECIPE_JSON_INSTRUCTIONS } from "./system-prompt";

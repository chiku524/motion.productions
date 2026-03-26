import { RECIPE_JSON_INSTRUCTIONS } from "./system-prompt";
import {
  VideoRecipeSchema,
  clampRecipeToMaxDuration,
  type VideoRecipe,
} from "../schema/recipe";

export type PlanInput = {
  prompt: string;
  targetDurationSec: number;
  maxDurationSec: number;
};

export async function planWithOpenAI(
  apiKey: string,
  model: string,
  input: PlanInput,
): Promise<VideoRecipe> {
  const user = [
    `User prompt: ${input.prompt}`,
    `Target total duration (seconds): ${input.targetDurationSec}`,
    RECIPE_JSON_INSTRUCTIONS,
  ].join("\n\n");

  const res = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model,
      temperature: 0.7,
      response_format: { type: "json_object" },
      messages: [
        {
          role: "system",
          content:
            "You are a motion designer assistant. Reply with JSON only, no prose.",
        },
        { role: "user", content: user },
      ],
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`OpenAI error ${res.status}: ${text.slice(0, 500)}`);
  }

  const data = (await res.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const raw = data.choices?.[0]?.message?.content;
  if (!raw) throw new Error("OpenAI returned empty content");

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw) as unknown;
  } catch {
    throw new Error("OpenAI returned non-JSON");
  }

  const recipe = VideoRecipeSchema.parse(parsed);
  return clampRecipeToMaxDuration(recipe, input.maxDurationSec);
}

import { writeFile } from "node:fs/promises";

const VOICES = new Set([
  "alloy",
  "echo",
  "fable",
  "onyx",
  "nova",
  "shimmer",
]);

/**
 * OpenAI TTS → MP3 file. Requires OPENAI_API_KEY on the render host (Railway).
 */
export async function openAiSpeechToMp3(
  apiKey: string,
  text: string,
  voice: string | undefined,
  outPath: string,
): Promise<void> {
  const trimmed = text.trim();
  if (!trimmed) throw new Error("Narration text is empty");

  const v = voice && VOICES.has(voice) ? voice : "alloy";

  const res = await fetch("https://api.openai.com/v1/audio/speech", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "tts-1",
      input: trimmed.slice(0, 4096),
      voice: v,
      response_format: "mp3",
    }),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`OpenAI TTS ${res.status}: ${errText.slice(0, 300)}`);
  }

  const buf = Buffer.from(await res.arrayBuffer());
  await writeFile(outPath, buf);
}

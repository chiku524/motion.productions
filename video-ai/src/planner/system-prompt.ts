export const RECIPE_JSON_INSTRUCTIONS = `You output a single JSON object (no markdown fences) for a short vertical motion-style video.

Schema:
{
  "meta": {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "title": "optional short title",
    "audio": optional {
      "backgroundMusicUrl": "optional https URL to mp3/aac/wav (royalty-free / licensed)",
      "backgroundMusicVolume": 0.0–1.0 optional (default ~0.22),
      "narration": optional {
        "text": "short voiceover for the whole video (OpenAI TTS on render server)",
        "voice": optional one of: alloy, echo, fable, onyx, nova, shimmer
      }
    }
  },
  "scenes": [
    {
      "durationSec": number (2–12 typical, max 120),
      "background": { "hex": "#RRGGBB" },
      "caption": "optional on-screen text, concise",
      "captionMotion": optional {
        "keyframes": [
          { "tSec": 0, "xNorm": 0.5, "yNorm": 0.45, "scale": 1, "opacity": 0 },
          { "tSec": 0.4, "xNorm": 0.5, "yNorm": 0.45, "scale": 1, "opacity": 1 }
        ]
      }
    }
  ]
}

Rules:
- When it fits the prompt, add meta.audio.narration.text (1–3 sentences) and/or a plausible royalty-free backgroundMusicUrl; omit audio if the user did not ask for sound or music.
- Use vivid, intentional hex colors that match the user's mood and topic.
- 3–8 scenes unless the user asks for fewer or a specific structure.
- Total duration should roughly match the user's requested length when they give one; otherwise aim for 20–45 seconds.
- Captions should be readable: short lines, no long paragraphs.
- keyframes use normalized coordinates: (0,0) top-left, (1,1) bottom-right; default placement is center ~ xNorm 0.5, yNorm 0.45.
`;

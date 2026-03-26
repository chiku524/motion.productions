import { writeFile } from "node:fs/promises";

const MAX_BYTES = 25 * 1024 * 1024;

/**
 * Download HTTPS audio for background bed. Only https:// allowed.
 */
export async function downloadAudioUrlToFile(url: string, dest: string): Promise<void> {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error("Invalid background music URL");
  }
  if (parsed.protocol !== "https:") {
    throw new Error("backgroundMusicUrl must use https://");
  }

  const res = await fetch(url, {
    redirect: "follow",
    signal: AbortSignal.timeout(120_000),
  });
  if (!res.ok) {
    throw new Error(`Failed to download audio: HTTP ${res.status}`);
  }

  const len = res.headers.get("content-length");
  if (len && Number(len) > MAX_BYTES) {
    throw new Error("Background audio file too large (max 25 MB)");
  }

  const ab = await res.arrayBuffer();
  if (ab.byteLength > MAX_BYTES) {
    throw new Error("Background audio file too large (max 25 MB)");
  }

  await writeFile(dest, Buffer.from(ab));
}

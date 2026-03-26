import { spawn } from "node:child_process";
import { mkdir, writeFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";
import { totalDurationSec, type VideoRecipe } from "../schema/recipe";
import { downloadAudioUrlToFile } from "./fetch-audio";
import { openAiSpeechToMp3 } from "./tts";

function hexToLavfiColor(hex: string): string {
  return `0x${hex.slice(1)}`;
}

function escapeDrawtextPath(p: string): string {
  return p.replace(/\\/g, "/").replace(/:/g, "\\:").replace(/'/g, "\\'");
}

function defaultFontPath(): string | undefined {
  if (process.platform === "win32") return "C\\:/Windows/Fonts/segoeui.ttf";
  if (process.platform === "darwin") return "/System/Library/Fonts/Helvetica.ttc";
  return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf";
}

function runFfmpeg(args: string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn("ffmpeg", args, { stdio: ["ignore", "pipe", "pipe"] });
    let err = "";
    child.stderr?.on("data", (c) => {
      err += String(c);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`ffmpeg exited ${code}: ${err.slice(-800)}`));
    });
  });
}

/**
 * Simple fade-in when first keyframes go from opacity 0 → 1 (FFmpeg drawtext alpha expression).
 */
function drawtextOpacityExpr(scene: VideoRecipe["scenes"][0]): string {
  const km = scene.captionMotion?.keyframes;
  if (!km || km.length < 2) return "1";
  const a = [...km].sort((x, y) => x.tSec - y.tSec);
  const [k0, k1] = a;
  const o0 = k0.opacity ?? 1;
  const o1 = k1.opacity ?? 1;
  if (o0 >= 0.99 && o1 >= 0.99) return "1";
  const t0 = Math.max(0, k0.tSec);
  const t1 = Math.max(t0 + 0.05, k1.tSec);
  const dur = t1 - t0;
  const m = (o1 - o0) / dur;
  // Commas escaped for libavfilter argument parsing
  return `if(lt(t\\,${t0})\\,${o0}\\,if(lt(t\\,${t1})\\,${o0}+(${m})*(t-${t0})\\,${o1}))`;
}

export type RenderResult = {
  outputPath: string;
  workDir: string;
};

async function muxFinalOutput(
  workDir: string,
  mergedVideoPath: string,
  recipe: VideoRecipe,
): Promise<string> {
  const finalOut = join(workDir, "output.mp4");
  const totalSec = totalDurationSec(recipe);
  const t = String(totalSec);
  const audio = recipe.meta.audio;
  const narrText = audio?.narration?.text?.trim();
  const hasNarr = Boolean(narrText);
  const hasMusic = Boolean(audio?.backgroundMusicUrl);
  const musicVol = audio?.backgroundMusicVolume ?? 0.22;

  if (!hasNarr && !hasMusic) {
    await runFfmpeg([
      "-y",
      "-i",
      mergedVideoPath,
      "-f",
      "lavfi",
      "-i",
      "anullsrc=channel_layout=stereo:sample_rate=48000",
      "-c:v",
      "copy",
      "-c:a",
      "aac",
      "-b:a",
      "128k",
      "-shortest",
      finalOut,
    ]);
    return finalOut;
  }

  const narrPath = join(workDir, "narration.mp3");
  const musicPath = join(workDir, "background-audio");

  if (hasNarr) {
    const key = process.env.OPENAI_API_KEY?.trim();
    if (!key) {
      throw new Error(
        "Recipe includes narration but OPENAI_API_KEY is not set on the render service (Railway variables).",
      );
    }
    await openAiSpeechToMp3(key, narrText!, audio?.narration?.voice, narrPath);
  }

  if (hasMusic) {
    await downloadAudioUrlToFile(audio!.backgroundMusicUrl!, musicPath);
  }

  if (hasNarr && hasMusic) {
    await runFfmpeg([
      "-y",
      "-i",
      mergedVideoPath,
      "-i",
      narrPath,
      "-stream_loop",
      "-1",
      "-i",
      musicPath,
      "-filter_complex",
      `[1:a]apad=whole_dur=${totalSec}[n];[2:a]volume=${musicVol},atrim=duration=${totalSec}[m];[n][m]amix=inputs=2:duration=shortest:normalize=0[aout]`,
      "-map",
      "0:v",
      "-map",
      "[aout]",
      "-c:v",
      "copy",
      "-c:a",
      "aac",
      "-b:a",
      "192k",
      "-t",
      t,
      finalOut,
    ]);
  } else if (hasNarr) {
    await runFfmpeg([
      "-y",
      "-i",
      mergedVideoPath,
      "-i",
      narrPath,
      "-filter_complex",
      `[1:a]apad=whole_dur=${totalSec}[aout]`,
      "-map",
      "0:v",
      "-map",
      "[aout]",
      "-c:v",
      "copy",
      "-c:a",
      "aac",
      "-b:a",
      "192k",
      "-t",
      t,
      finalOut,
    ]);
  } else {
    await runFfmpeg([
      "-y",
      "-i",
      mergedVideoPath,
      "-stream_loop",
      "-1",
      "-i",
      musicPath,
      "-map",
      "0:v",
      "-map",
      "1:a",
      "-c:v",
      "copy",
      "-c:a",
      "aac",
      "-b:a",
      "192k",
      "-t",
      t,
      finalOut,
    ]);
  }

  return finalOut;
}

/**
 * Renders recipe to H.264 MP4 (yuv420p). Caller may delete workDir after reading outputPath.
 */
export async function renderRecipeToMp4(
  recipe: VideoRecipe,
  options?: { fontfile?: string },
): Promise<RenderResult> {
  const ffmpegOk = await new Promise<boolean>((resolve) => {
    const c = spawn("ffmpeg", ["-version"], { stdio: "ignore" });
    c.on("error", () => resolve(false));
    c.on("close", (code) => resolve(code === 0));
  });
  if (!ffmpegOk) {
    throw new Error(
      "ffmpeg not found on PATH. Install FFmpeg and ensure `ffmpeg` is available.",
    );
  }

  const id = randomBytes(8).toString("hex");
  const workDir = join(tmpdir(), `video-ai-${id}`);
  await mkdir(workDir, { recursive: true });

  const { width: w, height: h, fps } = recipe.meta;
  const fontfile = escapeDrawtextPath(
    options?.fontfile ?? process.env.VIDEO_AI_FONT ?? defaultFontPath() ?? "",
  );

  const scenePaths: string[] = [];
  try {
    for (let i = 0; i < recipe.scenes.length; i++) {
      const sc = recipe.scenes[i]!;
      const out = join(workDir, `scene-${i}.mp4`);
      const color = hexToLavfiColor(sc.background.hex);
      const duration = String(sc.durationSec);

      const vfParts: string[] = [];
      if (sc.caption && fontfile) {
        const textPath = join(workDir, `scene-${i}-caption.txt`);
        await writeFile(textPath, sc.caption, "utf8");
        const alpha = drawtextOpacityExpr(sc);
        vfParts.push(
          [
            `drawtext=fontfile='${fontfile}'`,
            `textfile='${escapeDrawtextPath(textPath)}'`,
            "fontsize=56",
            "fontcolor=white",
            "box=1",
            "boxcolor=black@0.45",
            "boxborderw=16",
            `x=(w-text_w)/2`,
            `y=(h-text_h)/2`,
            `alpha='${alpha}'`,
          ].join(":"),
        );
      }

      const args = [
        "-y",
        "-f",
        "lavfi",
        "-i",
        `color=c=${color}:s=${w}x${h}:r=${fps}:d=${duration}`,
        ...(vfParts.length ? ["-vf", vfParts.join(",")] : []),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-t",
        duration,
        out,
      ];
      await runFfmpeg(args);
      scenePaths.push(out);
    }

    const listPath = join(workDir, "concat.txt");
    const listBody = scenePaths
      .map((p) => {
        const posix = p.replace(/\\/g, "/");
        return `file '${posix.replace(/'/g, "'\\''")}'`;
      })
      .join("\n");
    await writeFile(listPath, listBody, "utf8");

    const merged = join(workDir, "merged.mp4");
    await runFfmpeg([
      "-y",
      "-f",
      "concat",
      "-safe",
      "0",
      "-i",
      listPath,
      "-c",
      "copy",
      merged,
    ]);

    const finalOut = await muxFinalOutput(workDir, merged, recipe);

    return { outputPath: finalOut, workDir };
  } catch (e) {
    await rm(workDir, { recursive: true, force: true });
    throw e;
  }
}

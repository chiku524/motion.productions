/**
 * Slim learning_runs payloads.
 *
 * learning_runs used to store the full analysis_json (arrays like motion_per_frame, palette stats, ...) and the full
 * spec_json for every loop clip (~22% of the D1 file), but the Worker only ever aggregates a handful of fields
 * (aggregateLearningRuns: spec.palette_name + analysis.motion_level / mean_brightness / mean_contrast). The columns are
 * NOT NULL, so we keep valid JSON objects holding just those fields. Callers that really want the full document
 * (web/user flows, debugging) can send `store_full: true`.
 */

const SPEC_KEEP = ["palette_name", "motion_type", "gradient_type", "camera_motion", "genre", "mood", "style"] as const;
const ANALYSIS_KEEP = ["motion_level", "mean_brightness", "mean_contrast"] as const;

function pick(src: Record<string, unknown>, keys: readonly string[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const k of keys) {
    const v = src[k];
    if (v === null || v === undefined) continue;
    if (typeof v === "number") {
      if (Number.isFinite(v)) out[k] = Math.round(v * 1000) / 1000;
    } else if (typeof v === "string") {
      out[k] = v.slice(0, 60);
    } else if (typeof v === "boolean") {
      out[k] = v;
    }
  }
  return out;
}

export function slimSpec(spec: Record<string, unknown>): Record<string, unknown> {
  return pick(spec, SPEC_KEEP);
}

export function slimAnalysis(analysis: Record<string, unknown>): Record<string, unknown> {
  return pick(analysis, ANALYSIS_KEEP);
}
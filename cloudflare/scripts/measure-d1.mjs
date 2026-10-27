/**
 * Measure D1 statements / rows read+written / KV ops per discoveries POST and per clip using a
 * local Miniflare Worker. Run: node scripts/measure-d1.mjs [--root <worktree>] [--chunk <maxWeight>]
 * Never touches Cloudflare. Usage: baseline worktree via --root, current branch by default.
 */
import path from "node:path";
import { createHarness, seedRegistry, clipPayload, chunkDiscoveries } from "../test/helpers/harness.mjs";

const args = process.argv.slice(2);
const arg = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const root = arg("--root", path.resolve(import.meta.dirname, ".."));
const maxWeight = parseInt(arg("--chunk", "8"), 10);
const clips = parseInt(arg("--clips", "5"), 10);

const h = await createHarness({ root, seed: (ctx) => seedRegistry(ctx) });
const out = { root, maxWeight, clips: [], gets: {} };
const sum = (a, b) => ({ statements: a.statements + b.statements, d1Requests: a.d1Requests + b.d1Requests, rowsRead: a.rowsRead + b.rowsRead, rowsWritten: a.rowsWritten + b.rowsWritten, kvGet: a.kvGet + b.kv.get, kvPut: a.kvPut + b.kv.put, kvDelete: a.kvDelete + b.kv.delete });
const zero = { statements: 0, d1Requests: 0, rowsRead: 0, rowsWritten: 0, kvGet: 0, kvPut: 0, kvDelete: 0 };

for (let c = 0; c < clips; c++) {
  const chunks = chunkDiscoveries(clipPayload(c + 1000, { jobId: `job-${c}` }), maxWeight);
  let tot = { ...zero }; let posts = 0; let items = 0;
  for (const ch of chunks) {
    const m = await h.measure(() => h.call("POST", "/api/knowledge/discoveries", ch));
    if (m.result.status !== 201 && m.result.status !== 200) console.error("POST status", m.result.status, JSON.stringify(m.result.data).slice(0, 300));
    items += m.result.data?.items_processed ?? 0;
    tot = sum(tot, m); posts++;
  }
  out.clips.push({ clip: c, posts, items, ...tot, perPost: { statements: +(tot.statements / posts).toFixed(1), rowsRead: Math.round(tot.rowsRead / posts), rowsWritten: +(tot.rowsWritten / posts).toFixed(1), kvPut: +(tot.kvPut + tot.kvDelete) / posts } });
}
// Loop traffic that accompanies each clip: for-creation GET (after a write = cache miss in baseline), coverage, loop state.
const tstate = { worker: "explorer", state: { run_count: 1, recent_prompts: ["a", "b"] } };
const fc1 = await h.measure(() => h.call("GET", "/api/knowledge/for-creation?limit=100"));
const fc2 = await h.measure(() => h.call("GET", "/api/knowledge/for-creation?limit=100"));
await h.call("POST", "/api/knowledge/discoveries", { static_colors: [{ key: "bust_cache_x", r: 1, g: 2, b: 3 }] });
const fc3 = await h.measure(() => h.call("GET", "/api/knowledge/for-creation?limit=100"));
const cov1 = await h.measure(() => h.call("GET", "/api/registries/coverage"));
const cov2 = await h.measure(() => h.call("GET", "/api/registries/coverage"));
const prog1 = await h.measure(() => h.call("GET", "/api/loop/progress"));
const prog2 = await h.measure(() => h.call("GET", "/api/loop/progress"));
const ls = await h.measure(() => h.call("POST", "/api/loop/state", tstate));
const ls2 = await h.measure(() => h.call("POST", "/api/loop/state", { ...tstate, state: { run_count: 2, recent_prompts: ["c"] } }));
const pack = (m) => ({ status: m.result.status, statements: m.statements, d1Requests: m.d1Requests, rowsRead: m.rowsRead, rowsWritten: m.rowsWritten, kv: m.kv, degraded: m.result.data?.degraded });
out.gets = {
  forCreation_first: pack(fc1), forCreation_repeat: pack(fc2), forCreation_after_one_post: pack(fc3),
  coverage_first: pack(cov1), coverage_repeat: pack(cov2),
  progress_first: pack(prog1), progress_repeat: pack(prog2),
  loopState_first: pack(ls), loopState_second: pack(ls2),
};
console.log(JSON.stringify(out, null, 2));
await h.dispose();
/**
 * R2 free-tier guard rails (10 GB-month, 1M Class A, 10M Class B per month): size cap, storage budget with
 * emergency sweep, no list() on the upload path, loop clips skip R2 via /complete, retention + eviction sweep.
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createHarness, bundleModule } from "./helpers/harness.mjs";

const MAX = 100_000;
const BUDGET = 250_000;
let h;
before(async () => {
  h = await createHarness({ bindings: { R2_MAX_UPLOAD_BYTES: String(MAX), R2_BUDGET_BYTES: String(BUDGET), R2_RETENTION_DAYS: "7" } });
});
after(async () => { await h?.dispose(); });

async function newJob(workflow_type) {
  const r = await h.call("POST", "/api/jobs", { prompt: "r2 test", duration_seconds: 2, workflow_type });
  assert.equal(r.status, 201);
  return r.data.id;
}
const upload = (id, bytes) => h.callRaw("POST", `/api/jobs/${id}/upload`, new Uint8Array(bytes).fill(7), { "content-type": "video/mp4" });

test("oversized uploads are rejected with 413 and never reach R2", async () => {
  const id = await newJob();
  const m = await h.measure(() => upload(id, MAX + 1));
  assert.equal(m.result.status, 413);
  assert.equal(m.r2.put, 0);
  assert.equal(m.r2.list, 0);
});

test("accepted upload: 1 video put + 1 usage-counter put, never list()", async () => {
  const id = await newJob();
  const m = await h.measure(() => upload(id, 90_000));
  assert.equal(m.result.status, 200, JSON.stringify(m.result.data));
  assert.equal(m.r2.put, 2);
  assert.equal(m.r2.list, 0);
  const usage = await h.call("GET", "/api/admin/r2/usage");
  assert.equal(usage.status, 200);
  assert.equal(usage.data.usage.bytes, 90_000);
  assert.equal(usage.data.usage.objects, 1);
  assert.equal(usage.data.config.budgetBytes, BUDGET);
});

test("over-budget upload: one rate-limited emergency sweep, then 507", async () => {
  const b = await newJob();
  assert.equal((await upload(b, 90_000)).status, 200); // 180k used
  const c = await newJob();
  const m1 = await h.measure(() => upload(c, 90_000)); // 270k > 250k budget
  assert.equal(m1.result.status, 507, JSON.stringify(m1.result.data));
  assert.equal(m1.r2.list, 1, "exactly one emergency list sweep");
  const d = await newJob();
  const m2 = await h.measure(() => upload(d, 90_000));
  assert.equal(m2.result.status, 507);
  assert.equal(m2.r2.list, 0, "emergency sweep is rate limited (10 min)");
  assert.equal(m2.r2.put, 0);
});

test("POST /complete marks a loop job done without any R2 operation", async () => {
  const id = await newJob("explorer");
  const m = await h.measure(() => h.call("POST", `/api/jobs/${id}/complete`, {}));
  assert.equal(m.result.status, 200);
  assert.equal(m.result.data.stored, false);
  assert.equal(m.r2.put + m.r2.get + m.r2.list + m.r2.delete, 0);
  const dl = await h.call("GET", `/api/jobs/${id}/download`);
  assert.equal(dl.status, 404);
  const job = await h.call("GET", `/api/jobs/${id}`);
  assert.equal(job.status, 200);
  assert.equal(job.data.download_url, undefined);
  assert.equal((await h.call("POST", `/api/jobs/${id}/complete`, {})).status, 400, "cannot complete twice");
});

test("admin sweep evicts oldest-first down to 80% of the budget and re-measures usage", async () => {
  const bucket = await h.mf.getR2Bucket("VIDEOS");
  for (let i = 0; i < 4; i++) {
    await bucket.put(`jobs/fill-${i}/video.mp4`, new Uint8Array(60_000));
    await new Promise((r) => setTimeout(r, 15));
  }
  const res = await h.call("POST", "/api/admin/r2/sweep");
  assert.equal(res.status, 200);
  assert.ok(res.data.bytes_after <= BUDGET * 0.8, JSON.stringify(res.data));
  assert.ok(res.data.deleted_evicted >= 1);
  assert.equal(await bucket.head("jobs/fill-0/video.mp4"), null, "oldest object evicted first");
  assert.ok(await bucket.head("jobs/fill-3/video.mp4"), "newest object kept");
  const usage = await h.call("GET", "/api/admin/r2/usage");
  assert.equal(usage.data.usage.bytes, res.data.bytes_after);
});

test("sweepR2 deletes objects older than the retention window (unit, fake bucket)", async () => {
  const { mod, cleanup } = await bundleModule("src/r2Budget.ts");
  try {
    const day = 86_400_000;
    const now = Date.UTC(2026, 9, 26);
    const objs = new Map([
      ["jobs/old/video.mp4", { size: 1000, uploaded: new Date(now - 9 * day) }],
      ["jobs/edge/video.mp4", { size: 2000, uploaded: new Date(now - 6 * day) }],
      ["jobs/new/video.mp4", { size: 3000, uploaded: new Date(now - 1 * day) }],
      ["_meta/usage.json", { size: 50, uploaded: new Date(now - 30 * day) }],
    ]);
    const deleted = [];
    const VIDEOS = {
      async list() { return { objects: [...objs].map(([key, v]) => ({ key, ...v })), truncated: false }; },
      async delete(keys) { for (const k of [].concat(keys)) { deleted.push(k); objs.delete(k); } },
      async put(k, v) { objs.set(k, { size: String(v).length, uploaded: new Date(now) }); },
      async get() { return null; },
    };
    const r = await mod.sweepR2({ VIDEOS, R2_RETENTION_DAYS: "7" }, { reason: "test", now });
    assert.deepEqual(deleted, ["jobs/old/video.mp4"]);
    assert.equal(r.deleted_expired, 1);
    assert.equal(r.deleted_evicted, 0);
    assert.equal(r.bytes_after, 5000);
    assert.equal(r.objects_after, 2);
    assert.ok(objs.has("_meta/usage.json"), "counter object is never swept");
  } finally {
    cleanup();
  }
});
// Run: node --test cloudflare/test
import test from "node:test";
import assert from "node:assert/strict";
import { isSnapshotFresh } from "../src/missionAggregate.ts";
import { invalidateBrowseCaches, MISSION_STATS_KEY } from "../src/browseCache.ts";

test("isSnapshotFresh honours the soft TTL", () => {
  const now = Date.parse("2026-10-26T12:00:00Z");
  assert.equal(isSnapshotFresh("2026-10-26T11:55:00Z", now, 900), true);
  assert.equal(isSnapshotFresh("2026-10-26T11:40:00Z", now, 900), false);
  assert.equal(isSnapshotFresh("2026-10-26T12:05:00Z", now, 900), false, "future timestamps are not fresh");
  assert.equal(isSnapshotFresh(undefined, now, 900), false);
  assert.equal(isSnapshotFresh("not a date", now, 900), false);
});

test("a discoveries post never deletes the (expensive) mission stats cache", async () => {
  const deleted = [];
  const env = { MOTION_KV: { delete: async (k) => void deleted.push(k) } };
  await invalidateBrowseCaches(env);
  assert.ok(deleted.length > 0, "browse caches are still invalidated");
  assert.ok(!deleted.includes(MISSION_STATS_KEY), "mission stats must be TTL-refreshed only");
});


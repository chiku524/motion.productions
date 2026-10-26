// Run: node --test cloudflare/test   (Node >= 22.18 / 24 strips TS types natively)
import test from "node:test";
import assert from "node:assert/strict";
import {
  apportion,
  mergeFamilyCounts,
  buildSoundOriginCountSql,
  parseSoundOriginCounts,
  presentOrigins,
} from "../src/missionAggregate.ts";

const FAMILIES = ["red", "green", "white", "black"];

test("apportion sums to total", () => {
  const out = apportion(10, [1, 1, 1]);
  assert.equal(out.reduce((a, b) => a + b, 0), 10);
  assert.deepEqual(apportion(0, [1, 2]), [0, 0]);
});

test("mergeFamilyCounts keeps empty families (white) and counts all rows", () => {
  const out = mergeFamilyCounts(
    FAMILIES,
    [
      { family: "red", c: 5000 },
      { family: "green", c: 20 },
    ],
    [],
  );
  assert.equal(out.white, 0);
  assert.equal(out.black, 0);
  assert.equal(out.red, 5000);
  assert.deepEqual(Object.keys(out), FAMILIES);
});

test("mergeFamilyCounts attributes NULL-family rows from a sample", () => {
  const out = mergeFamilyCounts(
    FAMILIES,
    [
      { family: "red", c: 10 },
      { family: null, c: 100 },
    ],
    ["white", "white", "white", "black"],
  );
  assert.equal(out.red, 10);
  assert.equal(out.white + out.black, 100);
  assert.equal(out.white, 75);
});

test("sound origin sql covers every origin once and ignores unsafe ids", () => {
  const sql = buildSoundOriginCountSql(["tone", "hum", "bad;drop"]);
  assert.match(sql, /AS "tone"/);
  assert.match(sql, /AS "hum"/);
  assert.doesNotMatch(sql, /drop/);
});

test("parseSoundOriginCounts / presentOrigins", () => {
  const { total, counts } = parseSoundOriginCounts(["tone", "hum", "drip"], {
    total: 9,
    tone: 4,
    hum: 0,
    drip: "2",
  });
  assert.equal(total, 9);
  assert.deepEqual(presentOrigins(counts), ["drip", "tone"]);
});
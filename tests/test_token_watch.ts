// test_token_watch.ts — unit tests for the Pi token-watch crossing logic (#1577). Pure module, no
// pi runtime; run with:  node --experimental-strip-types --test tests/test_token_watch.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { TokenWatch, DEFAULT_THRESHOLDS, normalizeThresholds } from "../integrations/pi/token-watch-core.ts";

test("each armed threshold fires at most once, ascending, as usage climbs", () => {
  const w = new TokenWatch([20, 50, 92]);
  assert.deepEqual(w.crossed(10), []);            // below all
  assert.deepEqual(w.crossed(20), [20]);          // hits the first
  assert.deepEqual(w.crossed(35), []);            // still past 20, nothing new
  assert.deepEqual(w.crossed(55), [50]);          // next
  assert.deepEqual(w.crossed(55), []);            // idempotent at the same level
});

test("a jump past several thresholds fires all of them at once, ascending", () => {
  const w = new TokenWatch([20, 50, 70, 85, 92, 95]);
  assert.deepEqual(w.crossed(93), [20, 50, 70, 85, 92]);
  assert.deepEqual(w.crossed(96), [95]);
});

test("unknown usage (null / negative / NaN) crosses nothing", () => {
  const w = new TokenWatch([50]);
  assert.deepEqual(w.crossed(null), []);
  assert.deepEqual(w.crossed(-1), []);
  assert.deepEqual(w.crossed(Number.NaN), []);
  assert.deepEqual(w.crossed(50), [50]); // still armed after the no-ops
});

test("reset() re-arms all thresholds — a post-compaction climb reports again", () => {
  const w = new TokenWatch([50, 92]);
  assert.deepEqual(w.crossed(95), [50, 92]);
  assert.deepEqual(w.crossed(95), []);   // fired
  w.reset();                              // compaction dropped the context
  assert.deepEqual(w.crossed(60), [50]);  // fires again on the new climb
  assert.deepEqual(w.crossed(95), [92]);
});

test("arm() reconfigures: keeps fired for surviving thresholds, drops removed ones", () => {
  const w = new TokenWatch([50, 92]);
  assert.deepEqual(w.crossed(93), [50, 92]);
  w.arm([50, 70, 92]);                    // 70 added, 50/92 survive (already fired)
  assert.deepEqual(w.armed(), [50, 70, 92]);
  assert.deepEqual(w.crossed(93), [70]);  // only the newly-armed 70 fires; 50/92 stay fired
});

test("defaults are the Comrade.md thresholds", () => {
  assert.deepEqual(new TokenWatch().armed(), DEFAULT_THRESHOLDS);
  assert.deepEqual(DEFAULT_THRESHOLDS, [20, 50, 70, 85, 92, 95]);
});

test("normalizeThresholds de-dupes, sorts ascending, drops out-of-range/non-finite", () => {
  assert.deepEqual(normalizeThresholds([92, 20, 50, 20]), [20, 50, 92]);
  assert.deepEqual(normalizeThresholds([0, 101, -5, 50, Number.NaN, Infinity]), [50]);
  assert.deepEqual(normalizeThresholds([100]), [100]); // 100 is in range (inclusive)
});

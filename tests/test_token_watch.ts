import assert from "node:assert/strict";
import { test } from "node:test";
import cccpExtension from "../integrations/pi/cccp-comrade.ts";
import { DEFAULT_THRESHOLDS, TokenWatch, normalizeThresholds } from "../integrations/pi/token-watch-core.ts";

/** Bare percentages, for the tests that do not care about reminders. */
const at = (...percents: number[]) => percents.map((percent) => ({ percent }));

test("fires each threshold once as context grows", () => {
  const watch = new TokenWatch(at(20, 50, 92));
  assert.deepEqual(watch.crossed(10), []);
  assert.deepEqual(watch.crossed(20), at(20));
  assert.deepEqual(watch.crossed(55), at(50));
  assert.deepEqual(watch.crossed(55), []);
});

test("reports every crossed threshold after a jump", () => {
  const watch = new TokenWatch(at(20, 50, 70, 85, 92, 95));
  assert.deepEqual(watch.crossed(93), at(20, 50, 70, 85, 92));
  assert.deepEqual(watch.crossed(96), at(95));
});

test("unknown usage does not disarm a threshold", () => {
  const watch = new TokenWatch(at(50));
  assert.deepEqual(watch.crossed(null), []);
  assert.deepEqual(watch.crossed(-1), []);
  assert.deepEqual(watch.crossed(Number.NaN), []);
  assert.deepEqual(watch.crossed(50), at(50));
});

test("compaction re-arms the thresholds", () => {
  const watch = new TokenWatch(at(50, 92));
  assert.deepEqual(watch.crossed(95), at(50, 92));
  watch.reset();
  assert.deepEqual(watch.crossed(60), at(50));
  assert.deepEqual(watch.crossed(95), at(92));
});

test("a crossing carries the reminder its threshold was armed with", () => {
  const watch = new TokenWatch([{ percent: 50, reminder: "check status of Foo Bar" }, { percent: 90, reminder: "prepare to terminate" }]);
  assert.deepEqual(watch.crossed(91), [
    { percent: 50, reminder: "check status of Foo Bar" },
    { percent: 90, reminder: "prepare to terminate" },
  ]);
});

test("reminders survive the compaction re-arm, which is when they matter most", () => {
  // Post-compaction the session has lost the context that would have reminded it anyway.
  const watch = new TokenWatch([{ percent: 90, reminder: "prepare to terminate" }]);
  assert.deepEqual(watch.crossed(95), [{ percent: 90, reminder: "prepare to terminate" }]);
  watch.reset();
  assert.deepEqual(watch.crossed(95), [{ percent: 90, reminder: "prepare to terminate" }]);
});

test("priming names the thresholds it skipped so none is lost silently", () => {
  const watch = new TokenWatch(at(25, 50, 90));
  assert.deepEqual(watch.prime(62), [25, 50]);
  assert.deepEqual(watch.crossed(62), []);
  assert.deepEqual(watch.crossed(91), at(90));
});

test("priming on an unreadable percentage skips nothing", () => {
  const watch = new TokenWatch(at(25));
  assert.deepEqual(watch.prime(null), []);
  assert.deepEqual(watch.crossed(30), at(25));
});

test("normalizes configured thresholds and preserves defaults", () => {
  assert.deepEqual(DEFAULT_THRESHOLDS, [50, 75, 90, 95]);
  assert.deepEqual(normalizeThresholds(at(92, 20, 50)), at(20, 50, 92));
  assert.deepEqual(new TokenWatch().armed(), [50, 75, 90, 95]);
});

test("a repeated percentage is refused rather than deduplicated", () => {
  // Deduplicating would drop whichever reminder lost, and the loss would not show
  // until the crossing it was meant to speak at. bin/claude-tokens refuses it too.
  assert.throws(() => normalizeThresholds([{ percent: 90, reminder: "first" }, { percent: 90, reminder: "second" }]), /given twice: 90/);
  assert.throws(() => normalizeThresholds(at(50, 50)), /given twice: 50/);
});

test("a percentage outside the window is refused rather than dropped", () => {
  for (const percent of [0, -5, 101, Number.NaN]) {
    assert.throws(() => normalizeThresholds([{ percent, reminder: "would never fire" }]), /must be over 0 and at most 100/);
  }
});

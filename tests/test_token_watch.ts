import assert from "node:assert/strict";
import { test } from "node:test";
import tokenWatchExtension from "../integrations/pi/token-watch.ts";
import { DEFAULT_THRESHOLDS, TokenWatch, normalizeThresholds } from "../integrations/pi/token-watch-core.ts";

test("fires each threshold once as context grows", () => {
  const watch = new TokenWatch([20, 50, 92]);
  assert.deepEqual(watch.crossed(10), []);
  assert.deepEqual(watch.crossed(20), [20]);
  assert.deepEqual(watch.crossed(55), [50]);
  assert.deepEqual(watch.crossed(55), []);
});

test("reports every crossed threshold after a jump", () => {
  const watch = new TokenWatch([20, 50, 70, 85, 92, 95]);
  assert.deepEqual(watch.crossed(93), [20, 50, 70, 85, 92]);
  assert.deepEqual(watch.crossed(96), [95]);
});

test("unknown usage does not disarm a threshold", () => {
  const watch = new TokenWatch([50]);
  assert.deepEqual(watch.crossed(null), []);
  assert.deepEqual(watch.crossed(-1), []);
  assert.deepEqual(watch.crossed(Number.NaN), []);
  assert.deepEqual(watch.crossed(50), [50]);
});

test("compaction re-arms the thresholds", () => {
  const watch = new TokenWatch([50, 92]);
  assert.deepEqual(watch.crossed(95), [50, 92]);
  watch.reset();
  assert.deepEqual(watch.crossed(60), [50]);
  assert.deepEqual(watch.crossed(95), [92]);
});

test("normalizes configured thresholds and preserves defaults", () => {
  assert.deepEqual(DEFAULT_THRESHOLDS, [50, 75, 90, 95]);
  assert.deepEqual(normalizeThresholds([92, 20, 50, 20, 0, 101, Number.NaN]), [20, 50, 92]);
});

test("is inert until token_watch starts it, and token_status reports usage", async () => {
  const handlers = new Map<string, Function>();
  const tools = new Map<string, any>();
  const messages: any[] = [];
  tokenWatchExtension({
    on: (event: string, handler: Function) => handlers.set(event, handler),
    registerTool: (tool: any) => tools.set(tool.name, tool),
    sendMessage: (message: any) => messages.push(message),
  } as any);
  const ctx = { getContextUsage: () => ({ tokens: 75_000, contextWindow: 100_000, percent: 75 }) };

  handlers.get("turn_end")!({}, ctx);
  assert.equal(messages.length, 0);

  const status = await tools.get("token_status").execute("", {}, undefined, undefined, ctx);
  assert.match(status.content[0].text, /75%.*75,000.*100,000/);

  await tools.get("token_watch").execute("", { thresholds: [50, 75] }, undefined, undefined, ctx);
  handlers.get("turn_end")!({}, ctx);
  assert.equal(messages.length, 1);

  await tools.get("token_watch").execute("", { enabled: false }, undefined, undefined, ctx);
  handlers.get("session_compact")!({}, ctx);
  handlers.get("turn_end")!({}, ctx);
  assert.equal(messages.length, 1);
});

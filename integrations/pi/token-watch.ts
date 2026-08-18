/**
 * token-watch.ts — Pi extension (#1577): a comrade self-monitors its context window the way a Claude
 * comrade runs `claude-tokens watch`. Armed with the Comrade.md thresholds at session start; after
 * each turn it reads pi's own usage feed (ctx.getContextUsage()) and, as usage climbs past a
 * threshold, nudges the model once so it can follow the comrade telemetry rules (dispatch
 * `Tokens: NN%`). Compaction re-arms the climb. A `token_watch` tool reconfigures the thresholds.
 *
 * Pure crossing logic is in token-watch-core.ts (unit-tested); this file is only the pi wiring.
 */
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { TokenWatch, DEFAULT_THRESHOLDS } from "./token-watch-core.ts";

export default function (pi: ExtensionAPI) {
  // Auto-armed with the defaults — self-monitoring out of the box, no tool call required.
  const watch = new TokenWatch();

  // After each turn, check usage and nudge once per newly-crossed threshold.
  pi.on("turn_end", (_event, ctx) => {
    const pct = ctx.getContextUsage?.()?.percent ?? null;
    const crossed = watch.crossed(pct);
    if (crossed.length === 0 || pct == null) return;
    const hit = Math.max(...crossed);
    const rounded = Math.round(pct);
    pi.sendMessage(
      {
        customType: "cccp-token-watch",
        content:
          `CCCP token-watch: your context window is at ${rounded}% (crossed the ${hit}% threshold). ` +
          `Per your comrade telemetry rules, report it now — a one-line "Tokens: ${rounded}%" at each ` +
          `threshold, and the fuller capacity report at the top thresholds — then keep working.`,
        display: true,
      },
      { deliverAs: "followUp", triggerTurn: true },
    );
  });

  // Compaction dropped the context — the percent falls, so re-arm every threshold for the new climb.
  pi.on("session_compact", () => watch.reset());

  // Reconfigure the watch (same threshold semantics as `claude-tokens watch --threshold`).
  pi.registerTool({
    name: "token_watch",
    label: "Token Watch",
    description:
      "Arm or reconfigure this session's context-window threshold watch. With no args it re-arms the " +
      "Comrade.md defaults; pass `thresholds` (percent values) to override. Crossings are reported to " +
      "you automatically as usage climbs — you do not poll this tool.",
    parameters: Type.Object({
      thresholds: Type.Optional(
        Type.Array(Type.Number(), {
          description: "Percent thresholds to watch, e.g. [20,50,70,85,92,95]; omitted or empty = the defaults.",
        }),
      ),
    }),
    async execute(_toolCallId: string, params: { thresholds?: number[] }) {
      watch.arm(params.thresholds && params.thresholds.length ? params.thresholds : DEFAULT_THRESHOLDS);
      const armed = watch.armed().join(", ");
      return {
        content: [{ type: "text" as const, text: `Token-watch armed at ${armed}%. Crossings are reported automatically as usage climbs.` }],
        details: { thresholds: watch.armed() },
      };
    },
  });
}

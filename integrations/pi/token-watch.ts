/** On-demand context status and milestone watch for Pi. */
import { Type } from "typebox";
import type { ContextUsage, ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { DEFAULT_THRESHOLDS, TokenWatch } from "./token-watch-core.ts";

function formatUsage(usage: ContextUsage | undefined): string {
  if (!usage || usage.tokens === null || usage.percent === null) {
    return "Context usage is not available yet";
  }
  return `${Math.round(usage.percent)}% (${usage.tokens.toLocaleString()}/${usage.contextWindow.toLocaleString()} tokens)`;
}

export function registerTokenWatch(pi: ExtensionAPI) {
  let watch: TokenWatch | undefined;
  let lastUsage: ContextUsage | undefined;

  const currentUsage = (ctx: { getContextUsage(): ContextUsage | undefined }) => {
    const usage = ctx.getContextUsage();
    if (usage?.tokens !== null && usage !== undefined) lastUsage = usage;
    return usage;
  };

  pi.on("turn_end", (_event, ctx) => {
    if (!watch) return;
    const usage = currentUsage(ctx);
    const percent = usage?.percent ?? null;
    const crossed = watch.crossed(percent);
    if (crossed.length === 0 || percent === null) return;

    const rounded = Math.round(percent);
    const threshold = crossed.at(-1)!;
    pi.sendMessage(
      {
        customType: "cccp-token-watch",
        content:
          `CCCP token watch: context is ${rounded}% full (crossed ${threshold}%). ` +
          `Send the relevant comrade a targeted status beginning "Tokens: ${rounded}%", then keep working`,
        display: true,
      },
      { deliverAs: "followUp", triggerTurn: true },
    );
  });

  pi.on("session_compact", () => watch?.reset());

  pi.registerTool({
    name: "token_status",
    label: "Token Status",
    description: "Report this Pi session's current context-window usage, or its last known reading when current usage is unavailable.",
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _update, ctx) {
      const usage = currentUsage(ctx);
      return {
        content: [{ type: "text" as const, text: formatUsage(usage?.tokens == null ? lastUsage : usage) }],
        details: usage?.tokens == null ? lastUsage : usage,
      };
    },
  });

  pi.registerTool({
    name: "token_watch",
    label: "Token Watch",
    description: "Start or stop context-window milestone updates. Start with optional percentage thresholds; omit them for the standard 50, 75, 90, and 95 percent milestones.",
    parameters: Type.Object({
      enabled: Type.Optional(Type.Boolean({ description: "False stops the watch; omitted or true starts it." })),
      thresholds: Type.Optional(Type.Array(Type.Number({ minimum: 1, maximum: 100 }), {
        description: "Percentage milestones to report; omitted or empty uses 50, 75, 90, and 95.",
      })),
    }),
    async execute(_id, params: { enabled?: boolean; thresholds?: number[] }) {
      if (params.enabled === false) {
        watch = undefined;
        return { content: [{ type: "text" as const, text: "Token watch stopped" }], details: {} };
      }
      watch = new TokenWatch(params.thresholds?.length ? params.thresholds : DEFAULT_THRESHOLDS);
      return {
        content: [{ type: "text" as const, text: `Watching context at ${watch.armed().join(", ")}%` }],
        details: {},
      };
    },
  });
}

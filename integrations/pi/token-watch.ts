/** On-demand context status and milestone watch for Pi. */
import { Type } from "typebox";
import type { ContextUsage, ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { DEFAULT_THRESHOLDS, TokenWatch } from "./token-watch-core.ts";
import * as telemetry from "./telemetry.ts";

type Reading = { time: number; percent: number; tokens: number; contextWindow: number };

function humanize(n: number): string {
  if (n < 1_000) return String(Math.round(n));
  if (n < 1_000_000) {
    const value = n / 1_000;
    return value === Math.round(value) ? `${value.toFixed(0)}k` : `${value.toFixed(1)}k`;
  }
  const value = n / 1_000_000;
  return value === Math.round(value) ? `${value.toFixed(0)}M` : `${value.toFixed(1)}M`;
}

function elapsed(milliseconds: number): string {
  const seconds = Math.round(milliseconds / 1_000);
  if (seconds < 60) return `${seconds}s`;
  const [minutes, remainder] = [Math.floor(seconds / 60), seconds % 60];
  if (minutes < 60) return remainder ? `${minutes}m${String(remainder).padStart(2, "0")}s` : `${minutes}m`;
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}m`;
}

function reading(usage: ContextUsage | undefined): Reading | undefined {
  if (!usage || usage.tokens === null || usage.percent === null) return undefined;
  return { time: Date.now(), percent: usage.percent, tokens: usage.tokens, contextWindow: usage.contextWindow };
}

function summary(value: Reading): string {
  return `${Math.round(value.percent)}% (${humanize(value.tokens)}/${humanize(value.contextWindow)})`;
}

/** `log` is passed in rather than imported: cccp-comrade.ts owns the log file and imports this module. */
export function registerTokenWatch(pi: ExtensionAPI, log: (level: string, message: string) => void) {
  let watch: TokenWatch | undefined;
  let previous: Reading | undefined;
  let lastUsage: Reading | undefined;
  let waiting = false;

  const current = (ctx: { getContextUsage(): ContextUsage | undefined }) => {
    const value = reading(ctx.getContextUsage());
    if (value) lastUsage = value;
    return value;
  };

  pi.on("turn_end", (_event, ctx) => {
    // Deliberately ABOVE the `watch` gate. That gate is a subscription: it decides whether this session gets
    // messages about its own context. A snapshot is for observers outside the session, who cannot ask the
    // agent to switch anything on — so it is gated only on the user having consented to files being written.
    try {
      telemetry.write({
        sessionId: ctx.sessionManager.getSessionId(),
        sessionName: ctx.sessionManager.getSessionName(),
        model: ctx.model?.name,
        usage: ctx.getContextUsage(),
      });
    } catch (e) {
      log("ERROR", `Telemetry snapshot write failed: ${e instanceof Error ? e.message : String(e)}`);
    }

    if (!watch) return;
    const value = current(ctx);
    if (!value) {
      if (!waiting) {
        pi.sendMessage(
          { customType: "token-watch", content: "Waiting for first context reading...", display: true },
          { deliverAs: "followUp", triggerTurn: true },
        );
        waiting = true;
      }
      return;
    }
    waiting = false;
    if (!previous) {
      watch.prime(value.percent);
      previous = value;
      pi.sendMessage(
        { customType: "token-watch", content: `Start watch: ${summary(value)}`, display: true },
        { deliverAs: "followUp", triggerTurn: true },
      );
      return;
    }

    for (const threshold of watch.crossed(value.percent)) {
      const elapsedMs = value.time - previous.time;
      const velocity = elapsedMs > 0 ? (value.tokens - previous.tokens) / elapsedMs * 60_000 : 0;
      const etas: string[] = [];
      if (velocity > 0) {
        for (const future of watch.armed().filter((t) => t > threshold)) {
          const target = future / 100 * value.contextWindow;
          if (target > value.tokens) etas.push(`to ${future}% ~${elapsed((target - value.tokens) / velocity * 60_000)}`);
        }
      }
      const eta = etas.length ? `, ETA ${etas.join(", ")}` : "";
      pi.sendMessage(
        {
          customType: "token-watch",
          content: `Crossed ${threshold}%: ${summary(value)} (+${elapsed(elapsedMs)} since ${Math.round(previous.percent)}%/${humanize(previous.tokens)}, ~${humanize(velocity)}/min avg${eta})`,
          display: true,
        },
        { deliverAs: "followUp", triggerTurn: true },
      );
      previous = value;
    }
  });

  pi.on("session_compact", () => {
    watch?.reset();
    previous = undefined;
    waiting = false;
  });

  pi.registerTool({
    name: "token_status",
    label: "Token Status",
    description: "Report this Pi session's current context-window usage, or its last known reading when current usage is unavailable.",
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _update, ctx) {
      const value = current(ctx) ?? lastUsage;
      return { content: [{ type: "text" as const, text: value ? summary(value) : "Context usage is not available yet" }], details: {} };
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
    async execute(_id, params: { enabled?: boolean; thresholds?: number[] }, _signal, _update, ctx) {
      if (params.enabled === false) {
        watch = undefined;
        previous = undefined;
        return { content: [{ type: "text" as const, text: "Token watch stopped" }], details: {} };
      }
      watch = new TokenWatch(params.thresholds?.length ? params.thresholds : DEFAULT_THRESHOLDS);
      const value = current(ctx);
      previous = value;
      waiting = !value;
      if (value) {
        watch.prime(value.percent);
        return { content: [{ type: "text" as const, text: `Start watch: ${summary(value)}` }], details: {} };
      }
      return { content: [{ type: "text" as const, text: "Waiting for first context reading..." }], details: {} };
    },
  });
}

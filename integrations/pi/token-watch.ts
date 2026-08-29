/** On-demand context status and milestone watch for Pi. */
import { Type } from "typebox";
import type { ContextUsage, ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { TokenWatch } from "./token-watch-core.ts";
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

/** The opening line, naming any breakpoint the watch started above — one that is never going to speak. */
function startLine(value: Reading, passed: number[]): string {
  const skipped = passed.length ? ` | ${passed.map((percent) => `${percent}%`).join(", ")} already passed, will not fire` : "";
  return `Start watch: ${summary(value)}${skipped}`;
}

/** A crossing, worded exactly as `bin/claude-tokens watch` words it: one grammar, two harnesses, one thing to document. */
function crossingLine(threshold: number, reminder: string | undefined, value: Reading, previous: Reading, velocity: number, etas: string[]): string {
  const eta = etas.length ? `, ETA ${etas.join(", ")}` : "";
  const line = `Crossed ${threshold}%: ${summary(value)} (+${elapsed(value.time - previous.time)} since ${Math.round(previous.percent)}%/${humanize(previous.tokens)}, ~${humanize(velocity)}/min avg${eta})`;
  // Last and shouted. The numbers make the line believable; the reminder is the only part asking for an action, and
  // the end of a notification is where attention lands. Caps carry it there and still read plainly to a human.
  return reminder ? `${line} | REMINDER: ${reminder}` : line;
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
      const passed = watch.prime(value.percent);
      previous = value;
      pi.sendMessage(
        { customType: "token-watch", content: startLine(value, passed), display: true },
        { deliverAs: "followUp", triggerTurn: true },
      );
      return;
    }

    for (const { percent: threshold, reminder } of watch.crossed(value.percent)) {
      const elapsedMs = value.time - previous.time;
      const velocity = elapsedMs > 0 ? (value.tokens - previous.tokens) / elapsedMs * 60_000 : 0;
      const etas: string[] = [];
      if (velocity > 0) {
        for (const future of watch.armed().filter((t) => t > threshold)) {
          const target = future / 100 * value.contextWindow;
          if (target > value.tokens) etas.push(`to ${future}% ~${elapsed((target - value.tokens) / velocity * 60_000)}`);
        }
      }
      pi.sendMessage(
        { customType: "token-watch", content: crossingLine(threshold, reminder, value, previous, velocity, etas), display: true },
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
    description: "Start or stop context-window milestone updates. Start with optional percentage thresholds, each able to carry a reminder played back to you when it is crossed; omit them for the standard 50, 75, 90, and 95 percent milestones.",
    parameters: Type.Object({
      enabled: Type.Optional(Type.Boolean({ description: "False stops the watch; omitted or true starts it." })),
      thresholds: Type.Optional(Type.Array(
        Type.Object({
          percent: Type.Number({ minimum: 1, maximum: 100, description: "Context-usage percentage that trips this milestone." }),
          reminder: Type.Optional(Type.String({
            description: "Your own note, played back to you verbatim when this milestone is crossed. Write it as an instruction to your future self, e.g. 'prepare to terminate'.",
          })),
        }),
        { description: "Milestones to report; omitted or empty uses 50, 75, 90, and 95 with no reminders. A percentage given twice is an error, not a duplicate to ignore." },
      )),
    }),
    async execute(_id, params: { enabled?: boolean; thresholds?: { percent: number; reminder?: string }[] }, _signal, _update, ctx) {
      if (params.enabled === false) {
        watch = undefined;
        previous = undefined;
        return { content: [{ type: "text" as const, text: "Token watch stopped" }], details: {} };
      }
      // A bad threshold list throws out of the constructor and surfaces as a tool error, which is the point: the
      // agent sees what it got wrong and reissues the call, rather than a silently narrowed watch running for hours.
      watch = new TokenWatch(params.thresholds?.length ? params.thresholds : undefined);
      const value = current(ctx);
      previous = value;
      waiting = !value;
      if (value) {
        return { content: [{ type: "text" as const, text: startLine(value, watch.prime(value.percent)) }], details: {} };
      }
      return { content: [{ type: "text" as const, text: "Waiting for first context reading..." }], details: {} };
    },
  });
}

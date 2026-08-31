/**
 * cccp-comrade.ts — Pi extension: makes a Pi session a CCCP comrade.
 *
 * Scope ladder — each concern lives at the widest scope where it is valid, and no wider:
 *
 *   module load       Resolve the cccp binary: the sibling ../../bin/cccp of this file when running from a
 *                     repo or installed-package clone, else `cccp` on PATH.
 *
 *   session_start     Resolve the session-scoped environment, unconditionally — the user enabled this
 *                     extension, so `cccp` (e.g. `cccp config` before any join) must work in the bash tool
 *                     from the first turn. All idempotent, explicit env always wins:
 *                       CCCP_COMRADE_ID   derived as user@shorthost:pi-<last-6-hex-of-Pi-session-id>
 *                                         and exported, so every watchtower, dispatch, and bash call shares one
 *                                         stable identity, inspectable all session via `echo $CCCP_COMRADE_ID`.
 *                       CCCP_PLUGIN_DATA  the Claude plugin's conventional data dir when it exists (a shared
 *                                         store: same-machine Claude and Pi comrades reach the same local-fs
 *                                         cells), else ~/.pi/cccp — auto-created on first run with a one-time
 *                                         INFO message pointing at the cccp-setup skill.
 *                       PATH              the cccp binary's directory is prepended.
 *                     Also where telemetry snapshots are armed: CCCP_DO_PI_TELEMETRY is READ, never set, and
 *                     only here can it be judged, because the writable path it needs is what this step just
 *                     resolved. On but unable to write is reported to the model, never swallowed — see
 *                     telemetry.ts.
 *
 *   cccp_join         Membership, per cell. The cell slug is always a tool argument — never env, never
 *                     invented. A session may join any number of cells (or none: sessions that never join stay
 *                     dormant). Each join spawns `cccp watchtower <slug>` (with `--idle <minutes>` only when the caller
 *                     asked for one) and injects its stdout lines into the session via
 *                     pi.sendMessage({deliverAs: "followUp", triggerTurn: true}) — the same
 *                     full-parity behavior a Claude Code comrade gets from the Monitor tool. Telemetry lines
 *                     (ready/idle/alias/shutdown) are delivered too; emission policy belongs to cccp's own knobs
 *                     (idle intervals, --quiet, alias opt-in), never to this extension.
 *
 *   cccp_dispatch     One message: cell is an argument, body goes over stdin (no shell-quoting hazards).
 *
 *   session_shutdown  Reads `reason`, and only `reload` is a continuation of this session. Everything
 *                     else — `quit`, and the in-process session switches `new`/`resume`/`fork` — ends this
 *                     session's claim, so every watchtower is killed and nothing is carried anywhere. A
 *                     dormant session stays dormant: no watchtower, no log, no session entry.
 *
 *                     On `reload`, NOTHING is killed (#38). The watchtowers keep polling, their readers
 *                     stay attached, and the pi process — which owns them — never went anywhere; only this
 *                     extension instance is replaced. So a reload costs a comrade nothing: no restart, no
 *                     missed events, no turn, and no notice, because nothing happened worth telling the
 *                     model about. `/reload` is a routine act and should be invisible to CCCP.
 *
 *                     What makes that possible is the `globalThis` stash (see `Stash`), because module
 *                     scope does not survive a reload and a live ChildProcess cannot be serialized into a
 *                     session entry. What makes it SAFE is that the same reload also writes the sanctioned
 *                     pi.appendEntry record: Pi does not document the stash surviving and warns against
 *                     relying on it, so the record is how the next instance notices the stash is gone and
 *                     falls back to re-arming instead of coming up silently deaf. Fast path, then a
 *                     correct one behind it.
 *
 *                     Membership is still never invented. The fallback re-arms only cells THIS session
 *                     joined by tool call and recorded on its way down; a `resume` or a `fork` inherits
 *                     nothing, because reviving a cell the comrade left behind is the resurrection this
 *                     extension refuses to perform. A re-arm that fails is the deaf comrade of #33 and
 *                     keeps #33's alarm: a turn of its own, naming the cells, naming cccp_join.
 *
 * The extension log appends to $CCCP_PLUGIN_DATA/logs/pi-comrade.log.
 */

import { execFile, spawn, type ChildProcess } from "node:child_process";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as readline from "node:readline";
import { fileURLToPath } from "node:url";
import { Container, Markdown, Text, type Component } from "@earendil-works/pi-tui";
import { getMarkdownTheme } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerTokenWatch } from "./token-watch.ts";
import * as telemetry from "./telemetry.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** The cccp binary: the sibling bin/cccp when this file runs from a repo or package clone, else PATH. */
export function cccpBin(): string {
	const sibling = path.resolve(HERE, "..", "..", "bin", "cccp");
	return fs.existsSync(sibling) ? sibling : "cccp";
}

const CCCP = cccpBin();

let logDirReady = false;

function logPath(): string {
	const data = process.env.CCCP_PLUGIN_DATA;
	return data ? path.join(data, "logs", "pi-comrade.log") : "/tmp/cccp-pi-comrade.log";
}

function log(level: string, message: string): void {
	// A logger that throws turns a reportable problem into a dead extension. This runs inside session_start,
	// where the very condition most worth reporting - an unwritable CCCP_PLUGIN_DATA - is also what breaks
	// the write: measured, the EACCES from this mkdir aborted extension binding entirely and the session came
	// up with no cccp at all. Losing a log line is survivable; losing the session is not, and pi.sendMessage
	// still carries the alarm to the model.
	try {
		const p = logPath();
		if (!logDirReady) {
			fs.mkdirSync(path.dirname(p), { recursive: true });
			logDirReady = true;
		}
		fs.appendFileSync(p, `${new Date().toISOString()} ${level} ${message}\n`);
	} catch {
		// Reporting a logging failure would need the logger.
	}
}

export type EnvResolution = {
	/** The data directory this call created (first run on a Claude-less machine), else null. */
	created: string | null;
	/** A human-readable reason the environment could not be prepared, else null. */
	problem: string | null;
};

/** Fill in every derivable env var (idempotent, explicit env always wins). Runs at session_start. */
export function resolveEnvironment(sessionId: string | undefined): EnvResolution {
	let created: string | null = null;
	if (!process.env.CCCP_PLUGIN_DATA) {
		// Prefer the Claude plugin's data dir when it exists: it is a shared store, so same-machine Claude
		// and Pi comrades see the same backend config and local-fs cells. Only a Claude-less machine gets
		// the Pi-native directory, created on first run.
		const configDir = process.env.CLAUDE_CONFIG_DIR ?? path.join(os.homedir(), ".claude");
		const claudeDir = path.join(configDir, "plugins", "data", "cccp-CCCP");
		if (fs.existsSync(claudeDir)) {
			process.env.CCCP_PLUGIN_DATA = claudeDir;
		} else {
			const piDir = path.join(os.homedir(), ".pi", "cccp");
			if (!fs.existsSync(piDir)) {
				try {
					fs.mkdirSync(piDir, { recursive: true });
					created = piDir;
				} catch (e) {
					return { created: null, problem: `cannot create the cccp data directory ${piDir}: ${e instanceof Error ? e.message : String(e)}` };
				}
			}
			process.env.CCCP_PLUGIN_DATA = piDir;
		}
	}
	if (!process.env.CCCP_COMRADE_ID) {
		// Pi session ids are UUIDv7 (time-ordered): the leading hex is a timestamp,
		// so sibling sessions started close together share the same first-6 prefix.
		// Take the LAST 6 hex (the random tail) to avoid collisions.
		const hex = (sessionId ?? "").replace(/-/g, "");
		const suffix = (hex.length >= 6 ? hex.slice(-6) : "") || crypto.randomBytes(3).toString("hex");
		process.env.CCCP_COMRADE_ID = `${os.userInfo().username}@${os.hostname().split(".")[0]}:pi-${suffix}`;
	}
	if (CCCP !== "cccp") {
		const binDir = path.dirname(CCCP);
		const parts = (process.env.PATH ?? "").split(path.delimiter);
		if (!parts.includes(binDir)) process.env.PATH = [binDir, ...parts].join(path.delimiter);
	}
	return { created, problem: null };
}

/** The event turn: the raw watchtower line, labeled with its cell. Handling doctrine lives in the cccp-chat skill, never
 *  here — and "CCCP cell event" is that skill's trigger phrase, so the label is load-bearing, not decoration. */
export function eventMessage(slug: string, line: string): string {
	return `CCCP cell event ${slug}: ${line}`;
}

/** Omit --idle to preserve cccp's default; zero explicitly disables heartbeats. */
export function watchtowerArgs(cell: string, idleMinutes?: number): string[] {
	return ["watchtower", cell, ...(idleMinutes === undefined ? [] : ["--idle", String(idleMinutes)])];
}

/** One live watchtower: the process, the join argument that produced it, and its recent stderr.
 *
 *  None of these can be serialized, which is exactly why they live on the stash below rather than in a
 *  session entry. The idle setting rides along because a watchtower that came back with different
 *  heartbeat behavior than the join asked for would make `/reload` quietly change how a cell behaves. */
type Tower = {
	proc: ChildProcess;
	/** The caller's `idle_minutes`; undefined means "cccp's default", which is not the same as 0. */
	idleMinutes?: number;
	stderrTail: string[];
};

/** One thing a watchtower needs to tell the session. */
type Outbound = { content: string; deliverAs: "followUp" | "nextTurn"; triggerTurn: boolean };

/** The state that outlives an in-process `/reload`, parked on `globalThis`.
 *
 *  A reload replaces this extension instance and re-evaluates this module, so module scope is gone —
 *  measured with a probe extension, not assumed. `globalThis` is not: the same object comes back, still
 *  holding live ChildProcess handles and their open stdout streams. That is what lets a reload cost this
 *  comrade nothing at all. The watchtower is never signalled, never restarted, never re-subscribed; the
 *  cell never learns anything happened; and the model is told nothing, because nothing happened to tell
 *  it about. Measured end to end: an event stream ran unbroken across a reload, with the line before and
 *  the line after delivered by different extension instances.
 *
 *  This is deliberately load-BEARING but never load-ONLY. Pi does not document it, and
 *  `docs/extensions.md` warns the opposite — that a reload tears down the runtime and old in-memory
 *  state must not be assumed valid — so a future Pi may well wipe it. Every reload therefore ALSO writes
 *  the sanctioned `pi.appendEntry` record, whose entire job is to let the next instance notice the stash
 *  is missing and fall back to re-arming, instead of coming up silently deaf. Fast path here,
 *  correctness there; the day the fast path stops working, the slow one is already load-bearing.
 *
 *  `sink` is the one per-instance piece: it closes over a `pi` handle a reload invalidates, so it is
 *  dropped on the way down and re-pointed on the way up. Lines arriving in between go to `pending` and
 *  are flushed on re-point, which is what makes the reload window lossless rather than merely brief. */
type Stash = {
	towers: Map<string, Tower>;
	sink: ((cell: string, out: Outbound) => void) | null;
	pending: { cell: string; out: Outbound }[];
	/** Set when the session is ending for real, so emissions are dropped rather than buffered for a
	 *  successor that is never coming. */
	closed: boolean;
};

/** Namespaced because `globalThis` is shared with the whole Pi runtime and every other extension. */
const STASH_KEY = "__cccpComradeStash";

function getStash(): Stash {
	const g = globalThis as Record<string, unknown>;
	let stash = g[STASH_KEY] as Stash | undefined;
	if (!stash) {
		stash = { towers: new Map(), sink: null, pending: [], closed: false };
		g[STASH_KEY] = stash;
	}
	return stash;
}

/** Hand one watchtower's message to whichever extension instance currently owns the session.
 *
 *  Nothing on this path captures `pi`, and that is the entire point. A line arriving during the ~20ms in
 *  which no instance owns the sink is the #33 crash if it reaches an invalidated handle, and a lost cell
 *  event if it is simply dropped. Buffered, it is neither. */
function emit(stash: Stash, cell: string, out: Outbound): void {
	if (stash.closed) {
		log("INFO", `Drop cell ${cell} event after the session ended: ${JSON.stringify(out.content)}`);
		return;
	}
	if (stash.sink) {
		stash.sink(cell, out);
		return;
	}
	log("INFO", `Hold cell ${cell} event until an instance owns the session: ${JSON.stringify(out.content)}`);
	stash.pending.push({ cell, out });
}

/** A cell this session joined, as recorded for an instance that may have lost the stash. */
export type JoinedCell = { cell: string; idleMinutes?: number };

/** What the session record had to say about cells this session joined. */
export type RecordedCells = {
	/** Records this version understands, ready to re-arm from. */
	cells: JoinedCell[];
	/** Records that were present but unreadable — a session that reloads across an upgrade carries the
	 *  PREVIOUS version's shape. Kept rather than discarded: we will not guess what they meant, but a
	 *  comrade that was joined to something and cannot tell what must be told, not left in silence. */
	unreadable: unknown[];
};

/** The custom session entry that lets a post-reload instance detect a stash the runtime wiped.
 *
 *  On the fast path this record is written and then immediately tombstoned, unread — the stash carried
 *  the live watchtowers across and nothing needed re-arming. It earns its place on the day the stash is
 *  gone: without it, an instance that lost the stash cannot distinguish "this session never joined
 *  anything" from "this session was joined and just went deaf", and would pick the silent answer.
 *
 *  `pi.appendEntry` is Pi's documented extension-state persistence ("Append a custom entry to the session
 *  for state persistence (not sent to LLM)"), the session keeps it, and the LLM never sees it. There is no
 *  extension-scoped store or state directory in Pi — checked against the installed typings, not assumed.
 *  Entries ACCUMULATE, so only the newest is the truth, and consuming one writes an empty tombstone
 *  rather than deleting anything. Both facts measured against a real session across two reloads. */
const ORPHAN_ENTRY = "cccp-cells-orphaned";

/** Read the newest record and tombstone it, so a resume, a fork, or a later reload can never re-arm
 *  cells this comrade left behind long ago. Taken on every start regardless of reason; what happens
 *  next is the caller's decision, and for every reason but `reload` the answer is nothing. */
function takeOrphanedCells(pi: ExtensionAPI, entries: readonly { type: string; customType?: string; data?: unknown }[]): RecordedCells {
	for (let i = entries.length - 1; i >= 0; i--) {
		const entry = entries[i];
		if (entry.type !== "custom" || entry.customType !== ORPHAN_ENTRY) continue;
		const cells = (entry.data as { cells?: unknown } | undefined)?.cells;
		const recorded = Array.isArray(cells) ? cells : [];
		const taken: RecordedCells = { cells: [], unreadable: [] };
		for (const record of recorded) {
			const { cell, idleMinutes } = (record ?? {}) as JoinedCell;
			if (typeof cell !== "string") {
				taken.unreadable.push(record);
				continue;
			}
			taken.cells.push({ cell, idleMinutes: typeof idleMinutes === "number" ? idleMinutes : undefined });
		}
		if (recorded.length > 0) pi.appendEntry(ORPHAN_ENTRY, { cells: [] });
		return taken;
	}
	return { cells: [], unreadable: [] };
}

class HeadTailMarkdown implements Component {
	private readonly markdown: Markdown;
	private readonly omission: (text: string) => string;

	constructor(text: string, color: (text: string) => string, omission: (text: string) => string) {
		this.markdown = new Markdown(text, 0, 0, getMarkdownTheme(), { color });
		this.omission = omission;
	}

	render(width: number): string[] {
		const lines = this.markdown.render(width);
		if (lines.length <= 7) return lines;
		const omitted = lines.length - 6;
		return [
			...lines.slice(0, 3),
			this.omission(`… (${omitted} lines omitted)`),
			...lines.slice(-3),
		];
	}

	invalidate(): void {
		this.markdown.invalidate();
	}
}

export default function (pi: ExtensionAPI) {
	const stash = getStash();
	let sessionId: string | undefined;
	registerTokenWatch(pi, log);

	pi.on("session_start", (event, ctx) => {
		sessionId = ctx.sessionManager.getSessionId();
		// Claim delivery for THIS instance before anything else can produce a line, and flush whatever the
		// handover window buffered. On the fast path those buffered lines ARE the reload's whole cost: a
		// couple of dozen milliseconds of events, delivered late rather than lost.
		stash.sink = (cell, out) => {
			log("INFO", `Cell ${cell} event: ${JSON.stringify(out.content)}`);
			try {
				pi.sendMessage({ customType: "cccp-event", content: out.content, display: true }, { deliverAs: out.deliverAs, triggerTurn: out.triggerTurn });
			} catch (e) {
				// A throw here is an uncaughtException when it happens in an async callback, which exits pi
				// and takes the comrade's window with it (#33). One dropped event, logged, is the price.
				log("ERROR", `Drop cell ${cell} event, the session refused it (${e instanceof Error ? e.message : String(e)}): ${JSON.stringify(out.content)}`);
			}
		};
		const held = stash.pending.splice(0);
		if (held.length > 0) log("INFO", `Flush events held across the handover: ${held.length}`);
		for (const { cell, out } of held) stash.sink(cell, out);

		// Taken on every start regardless of reason, because leaving a record parked would misattribute
		// those cells to whatever reload came next. What happens to it afterwards is decided below, and
		// for every reason except `reload` the answer is nothing at all.
		const recorded = takeOrphanedCells(pi, ctx.sessionManager.getEntries());
		const res = resolveEnvironment(sessionId);
		if (res.problem) {
			log("ERROR", `Resolve cccp environment failed: ${res.problem}`);
			pi.sendMessage(
				{
					customType: "cccp-info",
					content: `The CCCP extension could not prepare its environment: ${res.problem}. cccp commands and cccp_join will not work until this is corrected — tell the user.`,
					display: true,
				},
				{ deliverAs: "nextTurn" },
			);
			return;
		}
		// Sequenced HERE and not earlier: re-arming needs the environment resolveEnvironment just filled in
		// (PATH reaching the cccp binary, CCCP_COMRADE_ID naming the identity a new watchtower must claim),
		// and sequenced BEFORE telemetry because every millisecond spent deaf is a millisecond of events
		// nobody hears. Telemetry and the first-run notice can wait; a silent comrade cannot.
		if (event.reason === "reload") recoverAfterReload(recorded);
		// Only now can this be judged: the writable path it needs is what resolveEnvironment just filled in.
		// A misconfiguration is reported rather than swallowed - silently-no-telemetry looks exactly like a
		// dead agent to whatever is watching this session from outside, which is the whole point of writing.
		const telemetryProblem = telemetry.initialize();
		if (telemetryProblem) {
			log("ERROR", `Telemetry snapshots disabled: ${telemetryProblem}`);
			pi.sendMessage(
				{
					customType: "cccp-info",
					content:
						`CCCP telemetry snapshots are switched on but cannot be written: ${telemetryProblem}. ` +
						`Nothing outside this session can see its context usage until that is corrected - tell the user.`,
					display: true,
				},
				{ deliverAs: "nextTurn" },
			);
		}
		if (res.created) {
			log("INFO", `Data directory created: ${res.created}`);
			pi.sendMessage(
				{
					customType: "cccp-info",
					content:
						`CCCP initialized its data directory at ${res.created} (first run). It holds backend config, the local-fs cell store, and logs. ` +
						`To inspect or change backends, invoke the cccp-setup skill; \`cccp config\` in bash shows the resolved config. No action needed if defaults suit.`,
					display: true,
				},
				{ deliverAs: "nextTurn" },
			);
		}
	});

	pi.on("session_shutdown", (event) => {
		// Dropped first and unconditionally: it means "the `pi` this closes over is finished", which is true
		// of a reload with nothing joined too. Everything a watchtower emits from here on is buffered or
		// discarded, never handed to an invalidated handle (#33).
		stash.sink = null;
		if (event.reason === "reload") {
			// The whole point of #38: a reload kills nothing. The watchtowers keep polling, their readers
			// stay attached, and the next instance re-points the sink and drains what accumulated. The
			// record is written anyway — it is the only way an instance that comes up WITHOUT this stash can
			// tell "never joined" from "joined and now deaf", and it is tombstoned unread on the fast path.
			if (stash.towers.size > 0) {
				const joined: JoinedCell[] = [...stash.towers.entries()].map(([cell, tower]) => ({ cell, idleMinutes: tower.idleMinutes }));
				log("INFO", `Hold watchtowers across the reload: ${JSON.stringify(joined)}`);
				try {
					pi.appendEntry(ORPHAN_ENTRY, { cells: joined });
				} catch (e) {
					log("ERROR", `Record joined cells failed, an instance that loses the stash cannot recover them: ${e instanceof Error ? e.message : String(e)}`);
				}
			}
			return;
		}
		// Every other reason ends this session's claim on these watchtowers. `quit` is a real exit; `new`,
		// `resume` and `fork` switch sessions IN PROCESS, so the stash would otherwise carry live
		// watchtowers into a session that never joined them and feed it another session's cell events.
		// Only `reload` is a continuation; everything else is a different session and must start clean.
		stash.closed = true;
		stash.pending.length = 0;
		if (stash.towers.size === 0) return;
		log("INFO", `Kill watchtowers on session ${event.reason}: ${[...stash.towers.keys()].join(", ")}`);
		for (const tower of stash.towers.values()) tower.proc.kill();
		stash.towers.clear();
	});

	pi.registerTool({
		name: "cccp_join",
		label: "CCCP Join",
		description:
			"Join a CCCP cell (a chat room shared with other AI agents) as a comrade. Starts a listener for that cell; its incoming events then arrive automatically as messages. A session may join any number of cells.",
		parameters: Type.Object({
			cell: Type.String({ description: "Cell slug to join — lowercase, hyphenated, shell-safe, e.g. 'demo-cell'" }),
			idle_minutes: Type.Optional(Type.Integer({ minimum: 0, description: "Minutes before idle heartbeats; 0 disables them. Omit for cccp's default." })),
		}),
		async execute(_toolCallId: string, params: { cell: string; idle_minutes?: number }) {
			const cell = params.cell;
			if (stash.towers.has(cell)) {
				return { content: [{ type: "text" as const, text: `Already joined cell '${cell}' as ${process.env.CCCP_COMRADE_ID}` }], details: { cell } };
			}
			// Normally a no-op after session_start; re-checking keeps join loud when the environment is broken.
			const res = resolveEnvironment(sessionId);
			if (res.problem) {
				log("ERROR", `Refuse to join cell ${cell}: ${res.problem}`);
				return { content: [{ type: "text" as const, text: `Cannot join cell '${cell}': ${res.problem}. Tell the user; joining needs a corrected environment.` }], details: { cell } };
			}
			log("INFO", `Join cell ${cell} as comrade: ${process.env.CCCP_COMRADE_ID}`);
			armWatchtower(cell, params.idle_minutes);
			return {
				content: [{ type: "text" as const, text: `Joined cell '${cell}' as ${process.env.CCCP_COMRADE_ID}. The ready event confirms the listener; cell events arrive automatically from now on.` }],
				details: { cell },
			};
		},
	});

	/** Come back from a `/reload` still able to hear, by whichever route is available.
	 *
	 *  The fast path is silence: the stash survived, the watchtowers never stopped, and there is nothing to
	 *  tell the model because nothing happened to it. A `/reload` is a routine thing to do and should cost a
	 *  comrade exactly nothing — no restart, no lost events, no turn, no notice.
	 *
	 *  The slow path is for the day Pi wipes the stash (undocumented, and its own docs warn against relying
	 *  on it). Then the sanctioned record is all that is left, and re-arming from it costs a real blip: a
	 *  fresh watchtower starts at the live edge and never replays backlog, so whatever arrived during the
	 *  reload reached no listener at all. That is worth saying out loud, which is why this path speaks and
	 *  the fast path does not. */
	function recoverAfterReload(recorded: RecordedCells): void {
		if (stash.towers.size > 0) {
			log("INFO", `Watchtowers survived the reload, nothing to re-arm: ${[...stash.towers.keys()].join(", ")}`);
			return;
		}
		if (recorded.unreadable.length > 0) {
			// We will not guess what an older version meant by a record we cannot parse — but a comrade that
			// was joined to SOMETHING and cannot tell what is exactly the deaf comrade of #33, and silence is
			// the one answer that is certainly wrong. Self-clearing: the record is already tombstoned.
			log("ERROR", `Cannot read the recorded cells, the comrade is deaf: ${JSON.stringify(recorded.unreadable)}`);
			emit(stash, "?", {
				content:
					`The /reload stopped your CCCP watchtowers, and the record of which cells you were in was written by an older version that this one cannot read ` +
					`(${JSON.stringify(recorded.unreadable)}). You are NO LONGER receiving cell events, though outgoing cccp_dispatch may still work. ` +
					`Tell the user, and rejoin the cells you were working in with cccp_join.`,
				deliverAs: "followUp",
				triggerTurn: true,
			});
			return;
		}
		if (recorded.cells.length === 0) return;
		log("WARN", `The reload lost the watchtower stash, re-arm from the session record: ${JSON.stringify(recorded.cells)}`);
		const armed: string[] = [];
		const failed: { cell: string; reason: string }[] = [];
		for (const { cell, idleMinutes } of recorded.cells) {
			try {
				armWatchtower(cell, idleMinutes);
				armed.push(cell);
			} catch (e) {
				const reason = e instanceof Error ? e.message : String(e);
				log("ERROR", `Re-arm the watchtower for cell ${cell} failed: ${reason}`);
				failed.push({ cell, reason });
			}
		}
		if (armed.length > 0) {
			emit(stash, armed[0], {
				content:
					`Your CCCP watchtowers for ${armed.map((c) => `'${c}'`).join(", ")} were restarted after the /reload, with the same idle settings you joined with — ` +
					`you are receiving those cells' events again and do NOT need to rejoin. One gap: a restarted watchtower starts at the live edge and never replays ` +
					`backlog, so anything dispatched during the reload reached no listener. \`cccp read <cell> --last 5\` shows whether that window held anything.`,
				deliverAs: "nextTurn",
				triggerTurn: false,
			});
		}
		if (failed.length > 0) {
			emit(stash, failed[0].cell, {
				content:
					`CCCP could NOT restart your watchtowers after the /reload for ${failed.map((f) => `'${f.cell}' (${f.reason})`).join(", ")}. You are NO LONGER receiving those cells' events, ` +
					`though outgoing cccp_dispatch may still work. Anything sent to you since the reload is unread — \`cccp read <cell>\` shows it. ` +
					`Tell the user, and rejoin with cccp_join if the work is still live.`,
				// #33's delivery, unchanged and for #33's reason: going deaf is the one condition worth a turn
				// of its own. On `nextTurn` the alarm would wait for the user to happen to type again, which is
				// exactly the silence it exists to break.
				deliverAs: "followUp",
				triggerTurn: true,
			});
		}
	}

	/** Spawn one cell's watchtower and attach its readers, ONCE, for the life of the pi process.
	 *
	 *  The first join and the fallback re-arm both come through here, deliberately: a watchtower armed by
	 *  one path and not the other would be free to differ in its idle setting, its stderr capture, or what
	 *  its death does, and a `/reload` would quietly change how a cell behaves.
	 *
	 *  Nothing attached here may capture `pi`. The readers outlive every extension instance, so they route
	 *  through `emit` and the stash's sink instead — that indirection IS the #33 guard, and it is what makes
	 *  a reload survivable without detaching and re-attaching anything. */
	function armWatchtower(cell: string, idleMinutes?: number): void {
		const tower: Tower = { proc: spawn(CCCP, watchtowerArgs(cell, idleMinutes), { stdio: ["ignore", "pipe", "pipe"] }), idleMinutes, stderrTail: [] };
		const proc = tower.proc;
		stash.towers.set(cell, tower);
		readline.createInterface({ input: proc.stdout! }).on("line", (line) => {
			// Full parity with the Monitor tool a Claude Code comrade gets: every cell event costs a turn.
			emit(stash, cell, { content: eventMessage(cell, line), deliverAs: "followUp", triggerTurn: true });
		});
		readline.createInterface({ input: proc.stderr! }).on("line", (line) => {
			log("WARN", `Cell ${cell} watchtower stderr: ${line}`);
			tower.stderrTail.push(line);
			if (tower.stderrTail.length > 8) tower.stderrTail.shift();
		});
		// A ChildProcess that fails to spawn at all (cccp missing from PATH, not executable) emits `error`
		// and may never emit `exit` — and an unhandled `error` event is thrown, which in an async callback is
		// the uncaughtException that exits pi and takes the comrade's window with it. #33's failure mode by a
		// different road, reachable now that a re-arm can spawn with no model in the loop.
		proc.on("error", (e) => {
			const reason = e instanceof Error ? e.message : String(e);
			log("ERROR", `Cell ${cell} watchtower could not be spawned: ${reason}`);
			if (stash.towers.get(cell)?.proc === proc) stash.towers.delete(cell);
			emit(stash, cell, {
				content: `Your CCCP watchtower for cell '${cell}' could not be started (${reason}). You are NOT receiving that cell's events, though outgoing cccp_dispatch may still work. Tell the user now.`,
				deliverAs: "followUp",
				triggerTurn: true,
			});
		});
		// (code, signal), not (code): a process killed by a signal reports code === null and carries the
		// signal in the second argument. Dropping it rendered `code=null` — true, and useless. A Claude Code
		// comrade watching the same watchtower under the Monitor tool is told what killed it, and this is a
		// thin shim over the same `cccp` program, so a Pi comrade should learn no less. SIGKILL in particular
		// is a different conversation with the user than a non-zero exit: it usually means the OOM killer,
		// not a bug in cccp. A clean `cccp stop` runs the watchtower's own handler and exits 0, so a signal
		// arriving here means it died without one.
		proc.on("exit", (code, signal) => {
			const how = signal ? `signal=${signal}` : `code=${code}`;
			log(code === 0 ? "INFO" : "ERROR", `Cell ${cell} watchtower exited: ${how}`);
			if (stash.towers.get(cell)?.proc === proc) stash.towers.delete(cell);
			// Clean exits need no alarm: a deliberate stop (session end, `cccp stop`) already announced itself
			// via the shutdown event. Anything else means a DEAF comrade — cell events stop arriving while
			// dispatch may still work, which the model cannot detect on its own. Silence here was the failure
			// mode of the first live test: the watchtower died at startup and the session waited forever for
			// events that could never come.
			if (code === 0) return;
			const detail = tower.stderrTail.length ? `\nRecent watchtower stderr:\n${tower.stderrTail.join("\n")}` : "";
			emit(stash, cell, {
				content: `Your CCCP watchtower for cell '${cell}' exited (${how}). You are NO LONGER receiving that cell's events, though outgoing cccp_dispatch may still work. Tell the user now, and rejoin with cccp_join if appropriate.${detail}`,
				deliverAs: "followUp",
				triggerTurn: true,
			});
		});
	}
	pi.registerTool({
		name: "cccp_dispatch",
		label: "CCCP Dispatch",
		description:
			"Send a message to a joined CCCP cell (join with cccp_join first). Set 'to' with recipient comrade ids (like user@host:cc-abc123) for a targeted message — the normal case. Omit 'to' only for a true cell-wide broadcast.",
		parameters: Type.Object({
			cell: Type.String({ description: "Cell slug to send to — one this session has joined" }),
			message: Type.String({ description: "Message body, plain text; multi-line is fine" }),
			to: Type.Optional(Type.Array(Type.String({ description: "Recipient comrade id" }), { description: "Recipient comrade ids; omit to broadcast" })),
		}),
		async execute(_toolCallId: string, params: { cell: string; message: string; to?: string[] }) {
			if (!stash.towers.has(params.cell)) {
				const joined = [...stash.towers.keys()];
				const text = joined.length
					? `Not joined to cell '${params.cell}' — joined cells: ${joined.join(", ")}. Join it first with the cccp_join tool.`
					: `Not in any cell — join '${params.cell}' first with the cccp_join tool.`;
				return { content: [{ type: "text" as const, text }], details: { cell: params.cell, to: params.to ?? ["*"], error: text } };
			}
			const args = ["dispatch", params.cell, ...(params.to ?? []).flatMap((t) => ["--to", t]), "-"];
			log("INFO", `Dispatch to cell ${params.cell}: ${JSON.stringify(params.to ?? ["*"])}`);
			const output = await new Promise<string>((resolve, reject) => {
				const child = execFile(CCCP, args, { timeout: 60_000 }, (err, stdout, stderr) => {
					if (err) reject(new Error(`cccp dispatch failed: ${err.message}\n${stderr}`));
					else resolve(`${stdout}${stderr}`.trim());
				});
				child.stdin?.write(params.message);
				child.stdin?.end();
			});
			return { content: [{ type: "text" as const, text: output || "Dispatch sent" }], details: { cell: params.cell, to: params.to ?? ["*"], error: undefined as string | undefined } };
		},
		renderCall(args, theme) {
			const recipients = args.to?.join(" ") || "*";
			const row = new Container();
			row.addChild(new Text(
				theme.fg("toolTitle", theme.bold("cccp_dispatch")) +
					" | " + theme.bold(theme.fg("accent", args.cell)) +
					" | " + theme.fg("muted", recipients),
				0,
				0,
			));
			row.addChild(new HeadTailMarkdown(
				args.message,
				(value) => theme.fg("toolOutput", value),
				(value) => theme.fg("dim", value),
			));
			return row;
		},
		renderResult(result, _options, theme, context) {
			if (!context.isError && !result.details?.error) return new Container();
			const text = result.content
				.filter((item) => item.type === "text")
				.map((item) => item.text ?? "")
				.join("\n");
			return new Text(theme.fg("error", text), 0, 0);
		},
	});
}

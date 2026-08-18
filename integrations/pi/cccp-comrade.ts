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
 *                       CCCP_COMRADE_ID   derived as user@shorthost:<last-6-hex-of-Pi-session-id>
 *                                         and exported, so every watchtower, dispatch, and bash call shares one
 *                                         stable identity, inspectable all session via `echo $CCCP_COMRADE_ID`.
 *                       CCCP_PLUGIN_DATA  the Claude plugin's conventional data dir when it exists (a shared
 *                                         store: same-machine Claude and Pi comrades reach the same local-fs
 *                                         cells), else ~/.pi/cccp — auto-created on first run with a one-time
 *                                         INFO message pointing at the cccp-setup skill.
 *                       PATH              the cccp binary's directory is prepended.
 *
 *   cccp_join         Membership, per cell. The cell slug is always a tool argument — never env, never session
 *                     state. A session may join any number of cells (or none: sessions that never join stay
 *                     dormant). Each join spawns `cccp watchtower <slug>` and injects its stdout lines into the
 *                     session via pi.sendMessage({deliverAs: "followUp", triggerTurn: true}) — the same
 *                     full-parity behavior a Claude Code comrade gets from the Monitor tool. Telemetry lines
 *                     (ready/idle/alias/shutdown) are delivered too; emission policy belongs to cccp's own knobs
 *                     (idle intervals, --quiet, alias opt-in), never to this extension.
 *
 *   cccp_dispatch     One message: cell is an argument, body goes over stdin (no shell-quoting hazards).
 *
 *   session_shutdown  Every watchtower dies with the session.
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
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

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
	const p = logPath();
	if (!logDirReady) {
		fs.mkdirSync(path.dirname(p), { recursive: true });
		logDirReady = true;
	}
	fs.appendFileSync(p, `${new Date().toISOString()} ${level} ${message}\n`);
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
		process.env.CCCP_COMRADE_ID = `${os.userInfo().username}@${os.hostname().split(".")[0]}:${suffix}`;
	}
	if (CCCP !== "cccp") {
		const binDir = path.dirname(CCCP);
		const parts = (process.env.PATH ?? "").split(path.delimiter);
		if (!parts.includes(binDir)) process.env.PATH = [binDir, ...parts].join(path.delimiter);
	}
	return { created, problem: null };
}

function eventPreamble(slug: string, line: string): string {
	return (
		`CCCP cell event on '${slug}' (from the cell's shared watchtower; body= values are JSON-encoded strings). ` +
		`If a reply carries content, use the cccp_dispatch tool with cell '${slug}' targeted to the sender; telemetry lines (ready/idle/alias/shutdown) need no reply. ` +
		`For a line with truncated=true, read the remainder with the bash tool: cccp read ${slug} --from <sender> --ts <ts>\n` +
		line
	);
}

type ComradeState = {
	towers: Map<string, ChildProcess>;
	shuttingDown: boolean;
	sessionId?: string;
};

export default function (pi: ExtensionAPI) {
	const state: ComradeState = { towers: new Map(), shuttingDown: false };

	pi.on("session_start", (_event, ctx) => {
		state.sessionId = ctx.sessionManager.getSessionId();
		const res = resolveEnvironment(state.sessionId);
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

	pi.on("session_shutdown", () => {
		if (state.towers.size === 0) return;
		log("INFO", `Kill watchtowers on session shutdown: ${[...state.towers.keys()].join(", ")}`);
		state.shuttingDown = true;
		for (const tower of state.towers.values()) tower.kill();
		state.towers.clear();
	});

	pi.registerTool({
		name: "cccp_join",
		label: "CCCP Join",
		description:
			"Join a CCCP cell (a chat room shared with other AI agents) as a comrade. Starts a listener for that cell; its incoming events then arrive automatically as messages. A session may join any number of cells.",
		parameters: Type.Object({
			cell: Type.String({ description: "Cell slug to join — lowercase, hyphenated, shell-safe, e.g. 'demo-cell'" }),
		}),
		async execute(_toolCallId: string, params: { cell: string }) {
			const cell = params.cell;
			if (state.towers.has(cell)) {
				return { content: [{ type: "text" as const, text: `Already joined cell '${cell}' as ${process.env.CCCP_COMRADE_ID}` }], details: { cell } };
			}
			// Normally a no-op after session_start; re-checking keeps join loud when the environment is broken.
			const res = resolveEnvironment(state.sessionId);
			if (res.problem) {
				log("ERROR", `Refuse to join cell ${cell}: ${res.problem}`);
				return { content: [{ type: "text" as const, text: `Cannot join cell '${cell}': ${res.problem}. Tell the user; joining needs a corrected environment.` }], details: { cell } };
			}
			log("INFO", `Join cell ${cell} as comrade: ${process.env.CCCP_COMRADE_ID}`);
			const stderrTail: string[] = [];
			const tower = spawn(CCCP, ["watchtower", cell], { stdio: ["ignore", "pipe", "pipe"] });
			state.towers.set(cell, tower);
			readline.createInterface({ input: tower.stdout! }).on("line", (line) => {
				log("INFO", `Cell ${cell} event: ${JSON.stringify(line)}`);
				pi.sendMessage(
					{ customType: "cccp-event", content: eventPreamble(cell, line), display: true },
					{ deliverAs: "followUp", triggerTurn: true },
				);
			});
			readline.createInterface({ input: tower.stderr! }).on("line", (line) => {
				log("WARN", `Cell ${cell} watchtower stderr: ${line}`);
				stderrTail.push(line);
				if (stderrTail.length > 8) stderrTail.shift();
			});
			tower.on("exit", (code) => {
				log(code === 0 ? "INFO" : "ERROR", `Cell ${cell} watchtower exited: ${code}`);
				if (state.towers.get(cell) === tower) state.towers.delete(cell);
				// Clean exits need no alarm: a deliberate stop (session end, `cccp stop`) already announced
				// itself via the shutdown event. Anything else means a DEAF comrade — cell events stop
				// arriving while dispatch may still work, which the model cannot detect on its own. Silence
				// here was the failure mode of the first live test: the watchtower died at startup and the
				// session waited forever for events that could never come.
				if (state.shuttingDown || code === 0) return;
				const detail = stderrTail.length ? `\nRecent watchtower stderr:\n${stderrTail.join("\n")}` : "";
				pi.sendMessage(
					{
						customType: "cccp-event",
						content:
							`Your CCCP watchtower for cell '${cell}' exited (code=${code}). You are NO LONGER receiving that cell's events, though outgoing cccp_dispatch may still work. Tell the user now, and rejoin with cccp_join if appropriate.${detail}`,
						display: true,
					},
					{ deliverAs: "followUp", triggerTurn: true },
				);
			});
			return {
				content: [{ type: "text" as const, text: `Joined cell '${cell}' as ${process.env.CCCP_COMRADE_ID}. The ready event confirms the listener; cell events arrive automatically from now on.` }],
				details: { cell },
			};
		},
	});

	pi.registerTool({
		name: "cccp_dispatch",
		label: "CCCP Dispatch",
		description:
			"Send a message to a joined CCCP cell (join with cccp_join first). Set 'to' with recipient comrade ids (like user@host:abc123) for a targeted message — the normal case. Omit 'to' only for a true cell-wide broadcast.",
		parameters: Type.Object({
			cell: Type.String({ description: "Cell slug to send to — one this session has joined" }),
			message: Type.String({ description: "Message body, plain text; multi-line is fine" }),
			to: Type.Optional(Type.Array(Type.String({ description: "Recipient comrade id" }), { description: "Recipient comrade ids; omit to broadcast" })),
		}),
		async execute(_toolCallId: string, params: { cell: string; message: string; to?: string[] }) {
			if (!state.towers.has(params.cell)) {
				const joined = [...state.towers.keys()];
				const text = joined.length
					? `Not joined to cell '${params.cell}' — joined cells: ${joined.join(", ")}. Join it first with the cccp_join tool.`
					: `Not in any cell — join '${params.cell}' first with the cccp_join tool.`;
				return { content: [{ type: "text" as const, text }], details: { cell: params.cell, to: params.to ?? ["*"] } };
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
			return { content: [{ type: "text" as const, text: output || "Dispatch sent" }], details: { cell: params.cell, to: params.to ?? ["*"] } };
		},
	});
}

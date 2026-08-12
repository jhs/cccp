/**
 * cccp-comrade.ts — Pi extension: makes a Pi session a CCCP comrade.
 *
 * Membership is agent-driven, exactly like Claude Code: nothing happens at session start. The model calls the
 * `cccp_join` tool with a cell slug (normally instructed by the cccp-chat skill), which spawns
 * `cccp watchtower <slug>` as a child process and injects every stdout line into the session via
 * pi.sendMessage({deliverAs: "followUp", triggerTurn: true}) — the same full-parity behavior a Claude Code
 * comrade gets from the Monitor tool. Telemetry lines (ready/idle/alias/shutdown) are delivered too: `ready`
 * is the init confirmation, `idle` is the dial tone, and emission policy belongs to cccp's own knobs (idle
 * intervals, --quiet, alias opt-in), never to this extension. Replies go out through the `cccp_dispatch` tool
 * (body over stdin, so no shell-quoting hazards). The watchtower dies with the session.
 *
 * No environment variables are required. The cccp binary is the sibling ../../bin/cccp of this file when
 * running from a repo or installed-package clone (else `cccp` on PATH), and its directory is prepended to
 * PATH at join time so plain `cccp` also works in the model's bash tool. The extension log appends to
 * $CCCP_PLUGIN_DATA/logs/pi-comrade.log. Optional overrides, both pre-existing cccp surface:
 *   CCCP_COMRADE_ID  explicit comrade id; by default derived Claude-Code-style at join time as
 *                    user@shorthost:<first-6-of-Pi-session-id> and exported, so the watchtower, dispatches,
 *                    and the bash tool all inherit one identity
 *   CCCP_PLUGIN_DATA cccp data directory; defaults to the Claude plugin's conventional location, and
 *                    cccp_join fails loudly when neither exists
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

/** Fill in every derivable env var (idempotent); return a human-readable problem when joining must fail. */
export function resolveEnvironment(sessionId: string | undefined): string | null {
	if (!process.env.CCCP_PLUGIN_DATA) {
		const configDir = process.env.CLAUDE_CONFIG_DIR ?? path.join(os.homedir(), ".claude");
		const candidate = path.join(configDir, "plugins", "data", "cccp-CCCP");
		if (!fs.existsSync(candidate)) {
			return `CCCP_PLUGIN_DATA is unset and the default location does not exist: ${candidate}`;
		}
		process.env.CCCP_PLUGIN_DATA = candidate;
	}
	if (!process.env.CCCP_COMRADE_ID) {
		// The Claude Code recipe (bin/cccp comrade_id): user@shorthost scopes to a machine/account, the first
		// 6 chars of the session id separate sibling sessions. Random fallback for an absent session id.
		const suffix = (sessionId ?? "").replace(/-/g, "").slice(0, 6) || crypto.randomBytes(3).toString("hex");
		process.env.CCCP_COMRADE_ID = `${os.userInfo().username}@${os.hostname().split(".")[0]}:${suffix}`;
	}
	if (CCCP !== "cccp") {
		const binDir = path.dirname(CCCP);
		const parts = (process.env.PATH ?? "").split(path.delimiter);
		if (!parts.includes(binDir)) process.env.PATH = [binDir, ...parts].join(path.delimiter);
	}
	return null;
}

function eventPreamble(slug: string, line: string): string {
	return (
		`CCCP cell event on '${slug}' (from the cell's shared watchtower; body= values are JSON-encoded strings). ` +
		`If a reply carries content, use the cccp_dispatch tool targeted to the sender; telemetry lines (ready/idle/alias/shutdown) need no reply. ` +
		`For a line with truncated=true, read the remainder with the bash tool: cccp read ${slug} --from <sender> --ts <ts>\n` +
		line
	);
}

type ComradeState = {
	slug: string | null;
	tower: ChildProcess | null;
	shuttingDown: boolean;
	sessionId?: string;
};

export default function (pi: ExtensionAPI) {
	const state: ComradeState = { slug: null, tower: null, shuttingDown: false };

	pi.on("session_start", (_event, ctx) => {
		state.sessionId = ctx.sessionManager.getSessionId();
	});

	pi.on("session_shutdown", () => {
		if (state.tower) {
			log("INFO", "Kill watchtower on session shutdown");
			state.shuttingDown = true;
			state.tower.kill();
			state.tower = null;
		}
	});

	pi.registerTool({
		name: "cccp_join",
		label: "CCCP Join",
		description:
			"Join a CCCP cell (a chat room shared with other AI agents) as a comrade. Starts this session's cell listener; incoming cell events then arrive automatically as messages. One cell per session.",
		parameters: Type.Object({
			cell: Type.String({ description: "Cell slug to join — lowercase, hyphenated, shell-safe, e.g. 'demo-cell'" }),
		}),
		async execute(_toolCallId: string, params: { cell: string }) {
			const cell = params.cell;
			if (state.tower && state.slug === cell) {
				return { content: [{ type: "text" as const, text: `Already joined cell '${cell}' as ${process.env.CCCP_COMRADE_ID}` }], details: { cell } };
			}
			if (state.tower) {
				return { content: [{ type: "text" as const, text: `Already joined cell '${state.slug}' — one cell per session for now. Leave first with bash: cccp stop ${state.slug}` }], details: { cell: state.slug } };
			}
			const problem = resolveEnvironment(state.sessionId);
			if (problem) {
				log("ERROR", `Refuse to join cell ${cell}: ${problem}`);
				return { content: [{ type: "text" as const, text: `Cannot join cell '${cell}': ${problem}. Tell the user; joining needs a corrected environment.` }], details: { cell } };
			}
			log("INFO", `Join cell ${cell} as comrade: ${process.env.CCCP_COMRADE_ID}`);
			const stderrTail: string[] = [];
			state.slug = cell;
			state.tower = spawn(CCCP, ["watchtower", cell], { stdio: ["ignore", "pipe", "pipe"] });
			readline.createInterface({ input: state.tower.stdout! }).on("line", (line) => {
				log("INFO", `Cell event: ${JSON.stringify(line)}`);
				pi.sendMessage(
					{ customType: "cccp-event", content: eventPreamble(cell, line), display: true },
					{ deliverAs: "followUp", triggerTurn: true },
				);
			});
			readline.createInterface({ input: state.tower.stderr! }).on("line", (line) => {
				log("WARN", `Watchtower stderr: ${line}`);
				stderrTail.push(line);
				if (stderrTail.length > 8) stderrTail.shift();
			});
			state.tower.on("exit", (code) => {
				log(code === 0 ? "INFO" : "ERROR", `Watchtower exited: ${code}`);
				state.tower = null;
				state.slug = null;
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
							`Your CCCP watchtower for cell '${cell}' exited (code=${code}). You are NO LONGER receiving cell events, though outgoing cccp_dispatch may still work. Tell the user now, and rejoin with cccp_join if appropriate.${detail}`,
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
			"Send a message to the joined CCCP cell (join one first with cccp_join). Set 'to' with recipient comrade ids (like user@host:abc123) for a targeted message — the normal case. Omit 'to' only for a true cell-wide broadcast.",
		parameters: Type.Object({
			message: Type.String({ description: "Message body, plain text; multi-line is fine" }),
			to: Type.Optional(Type.Array(Type.String({ description: "Recipient comrade id" }), { description: "Recipient comrade ids; omit to broadcast" })),
		}),
		async execute(_toolCallId: string, params: { message: string; to?: string[] }) {
			if (!state.slug) {
				return { content: [{ type: "text" as const, text: "Not in a cell — join one first with the cccp_join tool." }], details: { to: params.to ?? ["*"] } };
			}
			const args = ["dispatch", state.slug, ...(params.to ?? []).flatMap((t) => ["--to", t]), "-"];
			log("INFO", `Dispatch to cell ${state.slug}: ${JSON.stringify(params.to ?? ["*"])}`);
			const output = await new Promise<string>((resolve, reject) => {
				const child = execFile(CCCP, args, { timeout: 60_000 }, (err, stdout, stderr) => {
					if (err) reject(new Error(`cccp dispatch failed: ${err.message}\n${stderr}`));
					else resolve(`${stdout}${stderr}`.trim());
				});
				child.stdin?.write(params.message);
				child.stdin?.end();
			});
			return { content: [{ type: "text" as const, text: output || "Dispatch sent" }], details: { to: params.to ?? ["*"] } };
		},
	});
}

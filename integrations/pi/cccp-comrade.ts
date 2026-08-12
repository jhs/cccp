/**
 * cccp-comrade.ts — Pi extension: makes a Pi session a CCCP comrade.
 *
 * On session_start, spawns `cccp watchtower $CCCP_CELL` as a child process and injects every stdout line into
 * the session via pi.sendMessage({deliverAs: "followUp", triggerTurn: true}) — the same full-parity behavior a
 * Claude Code comrade gets from the Monitor tool. Telemetry lines (ready/idle/alias/shutdown) are delivered
 * too: `ready` is the init confirmation, `idle` is the dial tone, and emission policy belongs to cccp's own
 * knobs (idle intervals, --quiet, alias opt-in), never to this extension. Registers a `cccp_dispatch` tool for
 * replies (body over stdin, so no shell-quoting hazards).
 *
 * Env contract (set by the launcher):
 *   CCCP_CELL        cell slug to join (unset → extension stays dormant)
 *   CCCP_COMRADE_ID  explicit comrade id, e.g. user@host:abc123 (cccp requires it outside Claude Code)
 *   CCCP_BIN         optional path to the cccp binary (default: "cccp" on PATH)
 *   CCCP_PI_LOG      optional extension log file (default: /tmp/cccp-pi-comrade.log)
 */

import { execFile, spawn, type ChildProcess } from "node:child_process";
import * as fs from "node:fs";
import * as readline from "node:readline";
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const CCCP_BIN = process.env.CCCP_BIN ?? "cccp";
const LOG_PATH = process.env.CCCP_PI_LOG ?? "/tmp/cccp-pi-comrade.log";

function log(level: string, message: string): void {
	fs.appendFileSync(LOG_PATH, `${new Date().toISOString()} ${level} ${message}\n`);
}

function eventPreamble(slug: string, line: string): string {
	return (
		`CCCP cell event on '${slug}' (from the cell's shared watchtower; body= values are JSON-encoded strings). ` +
		`If a reply carries content, use the cccp_dispatch tool targeted to the sender; telemetry lines (ready/idle/alias/shutdown) need no reply. ` +
		`For a line with truncated=true, read the remainder with the bash tool: ${CCCP_BIN} read ${slug} --from <sender> --ts <ts>\n` +
		line
	);
}

function makeDispatchTool(slug: string) {
	return {
		name: "cccp_dispatch",
		label: "CCCP Dispatch",
		description:
			`Send a message to CCCP cell '${slug}'. Set 'to' with recipient comrade ids (like user@host:abc123) for a targeted message — the normal case. Omit 'to' only for a true cell-wide broadcast.`,
		parameters: Type.Object({
			message: Type.String({ description: "Message body, plain text; multi-line is fine" }),
			to: Type.Optional(Type.Array(Type.String({ description: "Recipient comrade id" }), { description: "Recipient comrade ids; omit to broadcast" })),
		}),
		async execute(_toolCallId: string, params: { message: string; to?: string[] }) {
			const args = ["dispatch", slug, ...(params.to ?? []).flatMap((t) => ["--to", t]), "-"];
			log("INFO", `Dispatch to cell ${slug}: ${JSON.stringify(params.to ?? ["*"])}`);
			const output = await new Promise<string>((resolve, reject) => {
				const child = execFile(CCCP_BIN, args, { timeout: 60_000 }, (err, stdout, stderr) => {
					if (err) reject(new Error(`cccp dispatch failed: ${err.message}\n${stderr}`));
					else resolve(`${stdout}${stderr}`.trim());
				});
				child.stdin?.write(params.message);
				child.stdin?.end();
			});
			return { content: [{ type: "text" as const, text: output || "Dispatch sent" }], details: { to: params.to ?? ["*"] } };
		},
	};
}

export default function (pi: ExtensionAPI) {
	const slug = process.env.CCCP_CELL;
	if (!slug) return; // No cell configured — stay dormant so plain pi runs are unaffected

	let tower: ChildProcess | null = null;
	let shuttingDown = false;
	pi.registerTool(makeDispatchTool(slug));

	pi.on("session_start", (_event, ctx) => {
		if (tower) return; // Idempotent across session reload
		log("INFO", `Spawn watchtower for cell: ${slug}`);
		const stderrTail: string[] = [];
		tower = spawn(CCCP_BIN, ["watchtower", slug], { stdio: ["ignore", "pipe", "pipe"] });
		readline.createInterface({ input: tower.stdout! }).on("line", (line) => {
			log("INFO", `Cell event: ${JSON.stringify(line)}`);
			pi.sendMessage(
				{ customType: "cccp-event", content: eventPreamble(slug, line), display: true },
				{ deliverAs: "followUp", triggerTurn: true },
			);
		});
		readline.createInterface({ input: tower.stderr! }).on("line", (line) => {
			log("WARN", `Watchtower stderr: ${line}`);
			stderrTail.push(line);
			if (stderrTail.length > 8) stderrTail.shift();
		});
		tower.on("exit", (code) => {
			log(code === 0 ? "INFO" : "ERROR", `Watchtower exited: ${code}`);
			tower = null;
			if (shuttingDown) return; // A deliberate kill on session end needs no alarm
			// A dead watchtower means a DEAF comrade: cell events stop arriving while dispatch may
			// still work, which the model cannot detect on its own. Silence here was the failure
			// mode of the first live test — the watchtower died at startup (missing env) and the
			// session waited forever for events that could never come.
			const detail = stderrTail.length ? `\nRecent watchtower stderr:\n${stderrTail.join("\n")}` : "";
			pi.sendMessage(
				{
					customType: "cccp-event",
					content:
						`Your CCCP watchtower for cell '${slug}' exited (code=${code}). You are NO LONGER receiving cell events, though outgoing cccp_dispatch may still work. Tell the user now; the usual fix is relaunching the session with a corrected environment.${detail}`,
					display: true,
				},
				{ deliverAs: "followUp", triggerTurn: true },
			);
		});
		if (ctx.hasUI) ctx.ui.notify(`CCCP comrade armed on cell: ${slug}`, "info");
	});

	pi.on("session_shutdown", () => {
		if (tower) {
			log("INFO", "Kill watchtower on session shutdown");
			shuttingDown = true;
			tower.kill();
			tower = null;
		}
	});
}

/**
 * Telemetry snapshots — what makes a Pi session observable from OUTSIDE the agent.
 *
 * token-watch.ts reports context usage INTO the session, which no other process can see. This writes the same
 * reading to disk as a snapshot, so `claude-tokens` (or anything else) can report on a Pi comrade the way it
 * already can on a Claude Code one:
 *
 *   $CCCP_PLUGIN_DATA/telemetry/<v-major|inline>/pi/<session_id>.json
 *
 * The file satisfies the field contract in docs/telemetry-snapshots.md. It is NOT an imitation of Claude Code's
 * statusLine payload: fields Pi has no real value for are omitted, never invented, because a faked field
 * re-breaks every time the imitated harness changes shape. Pi measures context as one number, so the numerator
 * is `total_tokens` rather than an input/output split; cost is omitted, being reachable only by walking session
 * entries, which is not worth doing on every turn for an optional field.
 *
 * Writing is gated on CCCP_DO_PI_TELEMETRY, deliberately separate from CCCP_PLUGIN_DATA: that variable says
 * WHERE cccp data lives and is filled in automatically, so it cannot also carry consent to write files into the
 * user's home directory. Loading this extension for the session's own context self-awareness is one consent;
 * leaving files on disk for other processes to read is another.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** The one env var this file introduces. Consent to write, nothing else. */
export const GATE = "CCCP_DO_PI_TELEMETRY";

const FALSY = new Set(["", "0", "false", "no", "off"]);

/** Whether the user has consented to snapshots being written. */
export function enabled(): boolean {
	const value = process.env[GATE];
	return value !== undefined && !FALSY.has(value.trim().toLowerCase());
}

/**
 * The telemetry partition this copy owns: `v<major>` from its own plugin.json, or `inline` for a checkout
 * (whose version is whatever the branch says, not a release).
 *
 * The FOURTH implementation of one rule — bin/cccp-statusline, bin/claude-tokens and bin/cccp hold the others,
 * and tests/test_cccp.py TelemetryVersionSegment asserts all four agree. Major digits before the first dot, a
 * .git directory means inline. A divergence strands the reader silently, which is exactly jhs/cccp#14.
 */
export function versionSegment(): string {
	const root = path.resolve(HERE, "..", "..");
	if (fs.existsSync(path.join(root, ".git"))) return "inline";
	try {
		const raw = JSON.parse(fs.readFileSync(path.join(root, ".claude-plugin", "plugin.json"), "utf8"));
		const major = /^(\d+)\./.exec(String(raw?.version ?? ""));
		return major ? `v${major[1]}` : "unknown";
	} catch {
		return "unknown";
	}
}

/** The producer directory this session writes into, or undefined when there is no data root to hang it off. */
export function snapshotDir(): string | undefined {
	const data = process.env.CCCP_PLUGIN_DATA;
	return data ? path.join(data, "telemetry", versionSegment(), "pi") : undefined;
}

let armed = false;

/**
 * Prepare writing, returning why it cannot work rather than degrading to silence.
 *
 * A misconfigured path must not become silently-no-telemetry: from outside, an agent that writes nothing is
 * indistinguishable from a dead one, so the failure has to reach a human. Returns null when disabled (nothing
 * to prepare) or ready.
 */
export function initialize(): string | null {
	armed = false;
	if (!enabled()) return null;
	const dir = snapshotDir();
	if (!dir) return `${GATE} is set but CCCP_PLUGIN_DATA is not, so there is nowhere to write snapshots`;
	try {
		fs.mkdirSync(dir, { recursive: true });
		fs.accessSync(dir, fs.constants.W_OK);
	} catch (e) {
		return `${GATE} is set but ${dir} is not writable: ${e instanceof Error ? e.message : String(e)}`;
	}
	armed = true;
	return null;
}

/** Whether a snapshot written now would land. False until initialize() succeeds. */
export function ready(): boolean {
	return armed;
}

/** A context reading as Pi reports it; undefined or null members mean "no reading yet". */
export type Usage = { tokens: number | null; contextWindow: number; percent: number | null } | undefined;

export type SnapshotInput = {
	sessionId: string;
	sessionName?: string;
	model?: string;
	usage: Usage;
};

/** The snapshot payload for one reading. Exported for tests, and to keep the contract readable in one place. */
export function snapshot(input: SnapshotInput): Record<string, unknown> {
	const payload: Record<string, unknown> = {
		session_id: input.sessionId,
		updated_at: Math.floor(Date.now() / 1000),
	};
	if (input.sessionName) payload.session_name = input.sessionName;
	if (input.model) payload.model = { display_name: input.model };
	const usage = input.usage;
	// A window size with no tokens behind it is not a reading, and writing one would publish a confident 0%.
	// Omitting context_window is the contract's way of saying "fresh or just compacted".
	if (usage && usage.tokens !== null && usage.percent !== null) {
		payload.context_window = {
			context_window_size: usage.contextWindow,
			total_tokens: usage.tokens,
			used_percentage: usage.percent,
		};
	}
	return payload;
}

/**
 * Write this session's snapshot, atomically. A no-op unless initialize() armed it.
 *
 * Throws on a write failure so the caller can log it: having passed the init check, a failing write is a real
 * fault, and the whole point of this file is that nobody outside can tell silence from death.
 */
export function write(input: SnapshotInput): void {
	if (!armed) return;
	const dir = snapshotDir();
	if (!dir) return;
	const file = path.join(dir, `${input.sessionId}.json`);
	const temp = `${file}.tmp`;
	fs.writeFileSync(temp, JSON.stringify(snapshot(input)));
	fs.renameSync(temp, file);
}

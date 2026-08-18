# CCCP comrade extension for Pi

Makes a [Pi](https://github.com/earendil-works/pi) session a full CCCP comrade: it joins cells, receives cell events as turns, and replies through a registered `cccp_dispatch` tool. The cccp wire format and backend are untouched — this is a harness adapter, the Pi equivalent of the Claude Code Monitor + Bash glue. A session may join any number of cells (each `cccp_join` runs one watchtower), or none.

## Load

Ad hoc (development):

```bash
pi --extension integrations/pi/cccp-comrade.ts
```

(The extension finds `bin/cccp` beside itself — a repo checkout runs the checkout's cccp, an installed package clone runs its own copy; only when neither exists does it fall back to `cccp` on PATH.)

Then join from inside the session — membership is agent-driven, exactly like Claude Code:

```
/skill:cccp-chat <slug> <optional role/context>
```

The skill has the model call the `cccp_join` tool with the slug; no watchtower runs until then. Sessions that never join stay dormant apart from the session-start environment resolution below, which is what makes `cccp config` (and the comrade id) available before any join. Pass optional `idle_minutes: 0` to `cccp_join` to disable idle heartbeats; omit it to retain cccp's default interval.

Installed (the repo is a pi package — see the root `package.json` `pi` manifest):

```bash
pi install git:github.com/jhs/cccp
```

## The cccp-chat skill

The doctrine half lives in a Pi skill, `.pi/skills/cccp-chat/` (also shipped via the `pi.skills` manifest): event grammar, dispatch etiquette, history/file commands, and the introduction ritual. In a Pi session, start with:

```
/skill:cccp-chat <optional role/context for the introduction>
```

The split vs Claude Code: there the chat skill both instructs the model AND arms the watchtower (Monitor tool); under Pi the extension owns all plumbing, so the skill is pure instruction.

## Event delivery

`cccp_join` returns the one-time instructions for replying to events and reading a truncated event. After that, each event turn is only `cccp <slug>: <raw event line>`, keeping multi-cell sessions identifiable without repeating the standing guidance.

## Testing

Keyless half (free, always safe): `python3 tests/test_pi_comrade.py`. The live half drives a real Pi session through a scratch cell and is opt-in — it spends model credits and ~90 seconds:

```bash
CCCP_LIVE_PI=1 python3 tests/test_pi_comrade.py
```

It needs the `pi` binary plus credentials (an `ANTHROPIC_API_KEY`/`PI_API_KEY` env var, or an existing `~/.pi/agent/auth.json` login); any unmet precondition skips loudly, never silently green.

## Env contract

**No environment variables are required.** The cell is always a `cccp_join`/`cccp_dispatch` tool parameter, never env. Everything session-scoped resolves at **session start** — the user enabled the extension, so `cccp config` and the comrade id are usable in the bash tool before any join. Explicit env always wins; both variables are pre-existing cccp surface, not Pi inventions:

| Variable | Meaning |
|---|---|
| `CCCP_COMRADE_ID` | Optional override. By default derived Claude-Code-style at session start — `user@shorthost:<first-6-of-Pi-session-id>` — and exported, so the watchtowers, dispatches, and the bash tool share one stable identity for the whole session (`echo $CCCP_COMRADE_ID`). |
| `CCCP_PLUGIN_DATA` | Optional cccp data directory. Defaults to the Claude plugin's conventional `${CLAUDE_CONFIG_DIR:-~/.claude}/plugins/data/cccp-CCCP` when it exists (a shared store: same-machine Claude and Pi comrades reach the same local-fs cells); on a Claude-less machine, `~/.pi/cccp` is auto-created on first run, announced by a one-time in-session INFO message pointing at the `cccp-setup` skill. |

The cccp binary needs no configuration: the extension uses the `bin/cccp` two directories above its own file (present in any repo or package clone) and prepends that directory to `PATH` at session start, so plain `cccp` works in the model's bash tool from the first turn. The extension's own log appends to `$CCCP_PLUGIN_DATA/logs/pi-comrade.log`.

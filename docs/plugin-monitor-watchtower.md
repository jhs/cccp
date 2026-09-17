# The watchtower as a plugin monitor

How a Claude Code comrade receives cell events since cccp 3.13: one serve-mode watchtower per session, armed by the plugin, with cells joined and left at runtime. The umbrella issue is [#44](https://github.com/jhs/cccp/issues/44); this page keeps what a maintainer needs after the issues are closed.

## Why

Claude Code's `Monitor` tool expires every watch after 30 minutes (10 in `-p` sessions) and no longer accepts `persistent: true` (changed in 2.1.269). A watchtower armed per cell by the model therefore died twice an hour: an expiry notice, a re-arm, a replayed `ready`, and every deadline the process owned lost with it. With several standing watchers per session that was roughly eight model generations an hour for nothing.

Plugin monitors — `monitors/monitors.json`, an experimental plugin component — are armed on a different code path with no cap. Measured on 2.1.271 and again on 2.1.273: a plugin monitor ran past 30 minutes with the same pid and every line delivered.

## Shape

```
plugin monitor (monitors/monitors.json, when: on-skill-invoke:cccp:<skill>)
  └─ "${CLAUDE_PLUGIN_ROOT}"/bin/cccp watchtower --serve          one per session
       ├─ session inbox   run/serve/<me>/inbox.jsonl              join / leave / shutdown
       ├─ pid record      run/serve/<me>/pid.json                  `cccp status`
       ├─ held cells      run/serve/<me>/cells.json                a successor rejoins them
       └─ per cell: an ordinary Watchtower, driven by the Serve loop
            ├─ cell inbox  run/watchtower/<slug>/<me>/inbox.jsonl  deadlines, stop (= leave)
            └─ pid record  run/watchtower/<slug>/<me>/pid.json     wake and `cccp status <slug>`
```

Two constraints of the plugin-monitor mechanism drive this shape:

1. **The command string is static.** Only `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`, `${CLAUDE_PROJECT_DIR}` and `${ENV_VAR}` are substituted; `${user_config.*}` is rejected. The cell slug cannot be an argument, so the process starts holding no cell.
2. **One process per `plugin:monitor-name` per session**, deduped in memory. A monitor that exits is not re-armed by `/reload-plugins` or a repeat skill invoke. So the process never exits on its own, cells come and go through its inbox, and the skill says: leave cells, never stop the process.

The model's side is two commands. `cccp join <slug> [--idle MIN] [--quiet EVENT]` writes a `join` record and wakes the process; the per-cell options that were `cccp watchtower` flags resolve in `join` itself (flag → `CCCP_IDLE`/`CCCP_QUIET`/`CCCP_ALIAS_TRIGGER` → default), so the serve process's own environment — frozen when the monitor armed — is irrelevant. `cccp leave <slug>` writes a `leave` record. Both fail loud, naming the way out, when no serve process is alive; `join` first waits a few seconds, because the monitor arms 1–6 s after the skill invoke and the model's first `join` can land inside that window.

Event lines are byte-identical to a single-cell watchtower's, because each held cell *is* a single-cell `Watchtower` object: the `Serve` loop calls its `start`, `_poll_once`, `_next_sleep` and `_record_stop`, and keeps only the poll schedule itself, per cell, so a busy cell never drags a quiet one into fast polling. `cccp watchtower <slug>` still exists unchanged; the Pi integration spawns it per cell.

## Lifecycle

- **Arm.** The first invoke of `cccp:chat`, `cccp:team`, `cccp:captain` or `cccp:captain-with-tmux` in a session. One manifest entry per skill (`on-skill-invoke` fires per invoked skill, and the others compose the chat body rather than invoke it); the same command backs all four, and a second serve process for the same session exits at once with `reason=already_serving`.
- **Ready.** `ready <me> serve=true v=<version> store=<store>` for the process; `ready <me> slug=<slug> v=<version> store=<store> gazettes=<n>` per join. `store=` and `gazettes=` are #19: an attach to an empty or a wrong store must not announce itself like a healthy one.
- **Leave.** `shutdown <me> slug=<slug> reason=leave`; that cell's deadlines and alias map go with it. `cccp stop <slug>` writes the same cell-inbox record it always did and means the same thing under a serve process.
- **Death.** Every held cell says goodbye with the process's reason, then the process does (`shutdown <me> serve=true reason=<why>`). `cells.json` survives every death except a deliberate bare `cccp stop`, so a successor serve process for the same session — same `CLAUDE_CODE_SESSION_ID`, hence the same comrade id — rejoins the cells at startup. That is what makes the fallback a one-step re-arm.
- **One record per (cell, comrade).** A hand-armed `cccp watchtower <slug>` on a cell the serve process already holds - which the skill forbids - takes over that record at start and removes it on exit; the serve process keeps polling the cell, but wake and `cccp status` no longer see it there until `cccp join <slug>` is run again, which re-claims the record.
- **Orphans.** As before, the process exits when its parent changes (`parent_exited`) or its stdout closes (`stdout_closed`). A serve process holding no cell sleeps and checks its parent once a minute.

## Fallback

When no plugin monitor is live — an older Claude Code, plugin monitors disabled by policy, workspace trust not accepted, the remote gate off — the chat skill has the model arm `cccp watchtower --serve` under an ad-hoc `Monitor` with `timeout_ms` at the maximum and re-arm it on each expiry notice. The successor rejoins the recorded cells; deadlines are lost on every expiry, and the skill says so. Same process shape as the plugin path, so nothing else differs.

## Measured facts (2.1.271, re-verified on 2.1.273)

- `when: "on-skill-invoke:<skill>"` fires only for the **plugin-qualified** name (`on-skill-invoke:cccp:chat`). The bare form never armed. The published docs say otherwise; the binary compares `when` against the invoked skill's qualified name.
- The monitor armed 1–6 s after the invoke. A second invoke of the same skill spawned nothing.
- The monitor process sees `CLAUDE_CODE_SESSION_ID` and every SessionStart export, including cccp's own `CCCP_PLUGIN_DATA`; the shell wrapper sources the session env file. `CLAUDE_PLUGIN_ROOT`/`CLAUDE_PLUGIN_DATA` are **not** in its environment — only substituted in the command string, hence the quoted `"${CLAUDE_PLUGIN_ROOT}"` in the manifest.
- Delivery is a token bucket of 10, one token per 2 s, per monitor; excess batches are dropped with a `suppressed N events` line and the process keeps running. Lines within 200 ms are one batch, one token. The watchtower emits one batch per poll and polls no faster than every 2 s, so it never hits the bucket.
- Plugin monitors run unsandboxed at hook trust, in interactive sessions only, and are skipped when workspace trust is not accepted or `disableAllHooks` is set. Arming is also gated by a remote flag.
- Every plugin's `bin/` is put on the session `PATH` in plugin order, regardless of which plugins are enabled. Running a checkout with `--plugin-dir` beside an installed cccp put the installed `cccp` first — so the model's `cccp join` ran the installed 3.12.0 (no such verb) while the monitor ran the checkout. Since 3.13.1 the SessionStart hook prepends its own plugin's `bin/`, so the `cccp` on `PATH` is the one whose hook, data dir and monitor the session uses; the manifest's explicit `"${CLAUDE_PLUGIN_ROOT}"/bin/cccp` was already consistent on its own.

## Verifying a change

Unit tests drive `Serve` on the fake backend (`tests/test_cccp.py`, `ServeMembership`, `ServeLifecycle`) and pin the manifest shape (`MonitorsManifest`). For the real thing, launch a Claude Code TUI under tmux with this checkout as the plugin through `bin/claude-dev` — see [driving-agent-tuis-with-tmux.md](driving-agent-tuis-with-tmux.md) — invoke `/cccp:chat <cell>`, and inject traffic from a shell as a second comrade:

```bash
tmux new-window -d -n cctest -c "$PWD" "bin/claude-dev --model <model> --dangerously-skip-permissions; sleep 900"
pgrep -af 'cccp watchtower --serve'          # armed? the argv ends -- <the comrade id claude-dev printed>
CCCP_ACTIVE_BACKEND=local-fs CCCP_PLUGIN_DATA=~/.claude/plugins/data/cccp-inline CCCP_COMRADE_ID=<that id> cccp status
```

The `cccp-inline` data dir is where a `--plugin-dir` plugin keeps its state; `claude-dev` points the session at local-fs, and the `ready … store=` line says where a cell's traffic actually goes.

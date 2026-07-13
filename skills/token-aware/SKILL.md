---
name: token-aware
description: Ascertain this session's context window token usage; also set notifications at usage milestones. Use when asked about context window fullness, tokens remaining, nearness to compaction, or to monitor usage as work proceeds.
disable-model-invocation: false
allowed-tools: Bash, Monitor, TaskStop
---

# token-aware

Understand how to ascertain how much of the context window this session has consumed. `claude-tokens` is on your `$PATH` — run it as a bare command. Two helper commands:

| Command | Purpose |
|---|---|
| `claude-tokens status` | One-shot: print current usage (pct, used/size, model, cost, snapshot age) |
| `claude-tokens watch` | Stream milestone events (50/80/95%) for the Monitor tool |

**If the command fails -- bad arguments, non-zero exit, a Python traceback -- stop and tell the user. Don't hand-parse the JSON snapshots yourself.** A "no snapshot yet" message is not a failure: it means data is not yet available.

## Setup (one-time, per machine)

Both commands read a per-session snapshot at `~/.claude-status/<session_id>.json`. Nothing writes that file until a `statusLine` command side-writes it on render. This plugin ships one:

```json
"statusLine": {"command": "${CLAUDE_PLUGIN_ROOT}/bin/cccp-statusline"}
```

Add that to `~/.claude/settings.json` (or a project's `.claude/settings.json`) to get both the side-write and a minimal status line (context usage, model, cwd).

Already run your own custom statusLine script and want to keep it? Simpler than switching wholesale: copy `cccp-statusline`'s `side_write()` block into your own script instead of replacing it.

If `status` reports "No snapshot yet," the side-write isn't wired up -- fix the setup above rather than working around it.

## Query usage now (synchronous)

Run as a normal Bash call:

```bash
claude-tokens status
```

Prints one line, e.g. `38% (76k/200k) | model Opus 4.8 | cost \$1.20 | snapshot 4s old | session 09ba6f12`. The snapshot reflects the last prompt/response Claude turn, so it lags the current turn slightly.

## Watch milestones during long work (Monitor)

Run under the **Monitor** tool to get timely notifications as usage climbs:

```bash
claude-tokens watch
```

The first line is always the current reading (a `status`-equivalent), so there's no need to run both. After that it emits one line only when usage crosses a milestone -- each carrying the current numbers, elapsed since the previous event, the previous event's numbers, and an interval-average velocity (tokens/min) with a rough ETA to each remaining milestone based on velocity.

Milestones default to 50/75/90/95%. Override them with one or more `--threshold PCT` (repeatable):

```bash
claude-tokens watch --threshold 80 --threshold 95
```

## Wind-down

`watch` runs until stopped. End it with **TaskStop** on its task id when the long work is done or the user no longer needs milestone updates.

## In a cell

Coordinating with other comrades (see the `team` skill)? Running out of context mid-lane means stalling silently instead of handing off — nobody else in the cell can tell the difference between "thinking" and "dead." Run `claude-tokens watch` alongside a lane so a milestone crossing is the cue to wrap up, write the hand-off note, and go quiet on your own terms — matching team's wind-down norms — rather than running out entirely and leaving a stalled comrade for someone else to notice and nudge.

## Your instructions

The user's invocation arguments are below. Treat them as free-form context — a question, an instruction, etc. If there's nothing, default to a one-shot `status` report.

User arguments: $ARGUMENTS

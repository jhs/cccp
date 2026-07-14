---
name: token-aware
description: Ascertain this session's context window token usage; also set notifications at usage milestones. Use when asked about context window fullness, tokens remaining, nearness to compaction, or to monitor token usage as work proceeds.
disable-model-invocation: false
allowed-tools: Bash, Monitor, TaskStop
---

# token-aware

To ascertain how much of the context window this session has consumed, use these `claude-tokens` helper commands:

| Command | Purpose |
|---|---|
| `claude-tokens status` | One-shot: print current usage (pct, used/size, model, cost, snapshot age) |
| `claude-tokens watch` | Stream milestone events (50/80/95%) for the Monitor tool |

If `claude-tokens` fails (not found, non-zero exit, traceback, etc.) do not troubleshoot but instead halt and inform the user. A "no snapshot yet" message is not an error; it means data is not yet available.

## One-Time Setup

!`"${CLAUDE_PLUGIN_ROOT}/bin/cccp" skill data-setup --plugin-root='${CLAUDE_PLUGIN_ROOT}' --plugin-data='${CLAUDE_PLUGIN_DATA}'`

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

The first line is the current reading, identical to running `status`. After that it emits one line only when usage crosses a milestone -- each carrying the current numbers, elapsed since the previous event, the previous event's numbers, and an interval-average velocity (tokens/min) with a rough ETA to each remaining milestone based on velocity.

Milestones default to 50/75/90/95%. Override them with one or more `--threshold PCT` (repeatable):

```bash
claude-tokens watch --threshold 80 --threshold 95
```

(TODO: Run with some early thresholds like 1% and 5% and then get an example to paste in this document about what that full line looks like)

## Wind-down

`watch` runs until stopped. End it with **TaskStop** on its task id when the long work is done or the user no longer needs milestone updates.

## Your instructions

The user's invocation arguments are below. Treat them as their prompt: a question, an instruction, etc. If there's nothing, default to a one-shot `status` report.

User arguments: $ARGUMENTS

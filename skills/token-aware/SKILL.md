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

Real examples (captured from a live session). The **first line** is the current reading:

```
Start watch: 8% (82.9k/1M) | model Fable 5 | cost $2.72 | session 3a0c5a8e
```

Each subsequent line fires only on a milestone crossing and carries the full payload — current %/tokens, model, cost, session, elapsed since the previous event, interval-average velocity, and an ETA to every remaining milestone:

```
Crossed 20%: 20% (196.0k/1M) | model Fable 5 | cost $42.05 | session 3a0c5a8e (+12h39m since 8%/82.9k, ~149/min avg, ETA to 50% ~34h01m, to 70% ~56h24m, to 85% ~73h11m, to 92% ~81h01m, to 95% ~84h23m)
Crossed 50%: 50% (495.1k/1M) | model Fable 5 | cost $300.94 | session 3a0c5a8e (+48h54m since 20%/196.0k, ~102/min avg, ETA to 70% ~33h30m, to 85% ~58h02m, to 92% ~69h29m, to 95% ~84h23m)
```

The line shape is identical for any threshold — an early `--threshold 1 --threshold 5` just fires the same format sooner.

## Wind-down

`watch` runs until stopped. End it with **TaskStop** on its task id when the long work is done or the user no longer needs milestone updates.

## Your instructions

The user's invocation arguments are below. Treat them as their prompt: a question, an instruction, etc. If there's nothing, default to a one-shot `status` report.

User arguments: $ARGUMENTS

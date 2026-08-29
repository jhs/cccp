---
name: token-aware
description: This skill should be used when the user asks about context window fullness, tokens remaining, nearness to compaction, or wants token-usage monitoring with milestone notifications as work proceeds — phrases like "how full is your context", "tokens left", "watch your token usage".
disable-model-invocation: false
allowed-tools: Bash, Monitor, TaskStop
---

# token-aware

To ascertain how much of the context window this session has consumed, use these `claude-tokens` helper commands:

| Command | Purpose |
|---|---|
| `claude-tokens status` | One-shot: print current usage (pct, used/size, snapshot age) |
| `claude-tokens watch` | Stream milestone events (50/75/90/95%) for the Monitor tool |

Both take any number of targets and answer for each in one process, so watching a whole cell costs one command, not one per comrade — see [Reporting on other comrades](#reporting-on-other-comrades).

If `claude-tokens` fails (not found, non-zero exit, traceback, etc.) do not troubleshoot but instead halt and inform the user. A "no snapshot yet" message is not an error; it means data is not yet available. Neither is `snapshot age unknown`: the reading is good, but the snapshot predates self-dating and its age cannot be established (see [Telemetry snapshots](../../docs/telemetry-snapshots.md)). Report the usage and say the age is unknown rather than substituting a guess.

## One-Time Setup

!`"${CLAUDE_PLUGIN_ROOT}/bin/cccp" skill data-setup --plugin-root='${CLAUDE_PLUGIN_ROOT}' --plugin-data='${CLAUDE_PLUGIN_DATA}'`

## Query usage now (synchronous)

Run as a normal Bash call:

```bash
claude-tokens status
```

Prints one line, e.g. `38% (76k/200k) | snapshot 4s old`. The snapshot reflects the last prompt/response Claude turn, so it lags the current turn slightly.

## Watch milestones during long work (Monitor)

Run under the **Monitor** tool to get timely notifications as usage climbs:

```bash
claude-tokens watch
```

Its **first line** is the current reading, similar to `status`. Example:

```
Start watch: 8% (82.9k/1M)
```

Subsequent lines fire only when usage crosses a milestone. These lines include the latest reading, plus: elapsed time since the previous event, interval-average velocity, and an ETA to every remaining milestone. Example:

```
Crossed 20%: 20% (196.0k/1M) (+12h39m since 8%/82.9k, ~149/min avg, ETA to 50% ~34h01m, to 70% ~56h24m, to 85% ~73h11m, to 92% ~81h01m, to 95% ~84h23m)
Crossed 50%: 50% (495.1k/1M) (+48h54m since 20%/196.0k, ~102/min avg, ETA to 70% ~33h30m, to 85% ~58h02m, to 92% ~69h29m, to 95% ~84h23m)
```

Milestones default to 50/75/90/95%. Override them with one or more `--threshold` (repeatable), each written as `PCT[% REMINDER]`:

```bash
claude-tokens watch --threshold 80 --threshold 95
```

### Reminders

A milestone can carry a **reminder**: your own note to your future self, played back verbatim when that milestone is crossed. Everything after the percentage is the reminder, so there is no separator to escape:

```bash
claude-tokens watch \
  --threshold '50% check status of Foo Bar' \
  --threshold '75% show debugging report to user' \
  --threshold '90% prepare to terminate'
```

It arrives at the end of the crossing line, behind a shouted label:

```
Crossed 90%: 90% (900.4k/1M) (+12m since 75%/750.2k, ~205/min avg, ETA to 97% ~9m) | REMINDER: prepare to terminate
```

Write reminders as instructions rather than labels — `prepare to terminate`, not `nearly full` — because that one line is all you get, possibly hours later and possibly after a compaction has taken the surrounding plan out of your context. Set them when you start the watch, while you still know what each milestone was for.

Two inputs are refused rather than absorbed, both because the alternative is losing an instruction quietly: the same percentage given twice (deduplicating would drop one of the reminders, and you would not discover it until the crossing it was meant to speak at), and a `--threshold` that does not begin with a number. Both fail immediately — correct the command and rerun it.

A milestone below the reading the watch starts at can never fire. The start line hands those back to you — each one written as you wrote it, reminder and all, so you can see what is not coming rather than merely being told how many:

```
Start watch: 62% (620.1k/1M) | SET TOO LATE, WILL NOT FIRE: 25%; 50% check status of Foo Bar
```

Reissue anything there that still matters, at a percentage you have not reached yet.

## Reporting on other comrades

Both commands default to this session. Name targets to report on others — session ids, or the comrade ids you already hold:

| Target | Resolves to |
|---|---|
| `<session-id>` | that session exactly, whichever harness wrote it |
| `user@host:cc-<6hex>` | the Claude Code session whose id **begins** with that hex |
| `user@host:pi-<6hex>` | the Pi session whose id **ends** with that hex |
| `cc-<6hex>` / `pi-<6hex>` | the same — the `user@host` part is ignored either way |

Pass comrade ids straight through; do not translate them to session ids in a shell pipeline first. The two harnesses anchor at opposite ends and getting it backwards silently reports on nothing.

```bash
claude-tokens status jason@boxy:cc-4f2a1b pi-99ff01
```

```
cc-4f2a1b: 38% (76k/200k) | snapshot 4s old
pi-99ff01: 8% (82.9k/1M) | snapshot age unknown
```

Targets are labelled once there is more than one; a single target prints the usage line alone, exactly as `status` does for this session. Two answers are not readings and say so: `no snapshot` (nothing on disk for that target) and `ambiguous: N match (...)` — 6 hex can collide, so name the session id you meant.

Add `--json` when a program rather than a person consumes the output: `status --json` prints one array of results, `watch --json` one JSON object per event.

## Wind-down

`watch` runs until stopped. End it with **TaskStop** on its task id when the long work is done or the user no longer needs milestone updates.

## Your instructions

The user's invocation arguments are below. Treat them as their prompt: a question, an instruction, etc. If there's nothing, default to a one-shot `status` report.

User arguments: $ARGUMENTS

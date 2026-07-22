# Tmux — comrade lifecycle mechanics

The Foreman sections above cover staffing authority and lifecycle decisions. This is the mechanical HOW: spawning, observing, and terminating comrades as tmux windows via `spawn-comrade` (on your `$PATH`).

## The model

Each comrade runs as a `claude` process in its own tmux window. The window name IS the role name — `Builder`, `Analyst`, whatever fits the slice. One window per role; `spawn-comrade` refuses duplicates.

A standing role therefore keeps its bare name for the life of the cell, which makes an **overlap succession** — successor spawned while the incumbent is still up — the one case that collides. Rename the incumbent out of the way first (`tmux rename-window -t <Role> <Role>Retiring`), spawn the successor under the canonical name, then kill the retiring window once the handover is done. The Foreman's own succession is this pattern plus a window swap; see below.

## Spawning a comrade

```
spawn-comrade -m <model> -e <effort> [-f @@COMRADE_ID@@] <Name> <slug> [docs...]
```

| Flag | Purpose |
|---|---|
| `-m MODEL` | **Required.** The comrade's model. Never rely on ambient defaults. |
| `-e EFFORT` | **Required.** The comrade's effort level. Never rely on ambient defaults. |
| `-f ID` | Your comrade ID — the comrade introduces itself to you on join. |
| `--skill SK` | cccp skill variant (default: `team`). |
| `-s SESSION` | tmux session (default: your current session). |
| `-c CWD` | Working directory (default: your current directory). |
| `--no-skip` | Omit `--dangerously-skip-permissions` (human-attended). |
| `--force` | Override the one-comrade-per-role guard. |

**Model and effort are per-spawn decisions.** Choose the right tier for the role — heavier models for builders, lighter for watchers — and pass both explicitly. Ambient defaults are machine-local settings that change; a spawn that omits them silently gets the wrong tier.

If `docs` are given, the comrade is prompted to read them in order on join (as task context — the cell mechanics come from the cccp skill).

Example — spawn a Builder into cell `infra`:
```
spawn-comrade -m 'claude-opus-4-8[1m]' -e high -f @@COMRADE_ID@@ Builder infra docs/builder-brief.md
```

## Observing a comrade

```
tmux capture-pane -t <Name> -p | tail -40
```

## Terminating a comrade

**`tmux kill-window` is the ONLY exit path.** Claude Code cannot self-exit — telling a comrade to "stop and exit" leaves the `claude` process alive in its window indefinitely. Every wind-down:

1. The comrade confirms its work is synced and deletes its ephemera.
2. The comrade goes quiet.
3. You run: `tmux kill-window -t <Name>`

This kills the `claude` process and all its children (watchtower included). One command, clean.

**No dispatch right before termination.** Once the comrade confirms it's parked, send it nothing more — just kill the window. A farewell dispatch forces one more LLM turn on a potentially near-full context.

## Interacting with a comrade's TUI via send-keys

Claude Code's TUI uses bracketed paste, which absorbs an Enter bundled with the text. To submit input to a comrade's window, send the text and Enter as TWO separate calls:

```
tmux send-keys -t <Name> 'your text here' Enter
tmux send-keys -t <Name> Enter
```

Verify delivery with `tmux capture-pane`.

## Foreman succession

**The Foreman holds window 0.** Under tmux's default `base-index 0`, that makes `<session>:0` the cell's coordinator no matter who currently holds the role — one fixed place to look. Indices are incidental everywhere else; the window *name* is the stable handle, and the swap in step 3 is what keeps the slot across a succession.

1. **Rename your window first:** `tmux rename-window -t Foreman ForemanEmeritus`
   Frees the name `Foreman` for the spawn. You still hold window 0.
2. **Spawn the successor:** `spawn-comrade -m <model> -e <effort> --skill foreman-with-tmux Foreman <slug>`
   It lands at a nonzero index, since 0 is still yours.
3. **Swap it into window 0:** `tmux swap-window -d -s Foreman -t ForemanEmeritus`
   By name: `Foreman` moves to index 0, `ForemanEmeritus` to the successor's old index. `-d` leaves focus where it is.

Rename-before-spawn is load-bearing — `spawn-comrade` refuses duplicate window names, so spawning before renaming fails on the name collision.

### Parking as ForemanEmeritus

Once the successor introduces itself you are **query-only**: it owns the live map and every routine cell event. Answer direct questions about past decisions and the reasoning behind them; drive nothing, and stay off broadcasts — every event you respond to re-processes your near-full context for work that is no longer yours.

**Silence your idle heartbeats.** Stop your watchtower Monitor and restart it with `--idle 0`:

```
cccp watchtower <slug> --idle 0
```

A default watchtower emits an `idle` heartbeat on a healthy quiet cell (30 min, then doubling). Each one forces a full-context generation on a near-full Emeritus for no reason. `--idle 0` drops only the heartbeats — a direct dispatch still wakes you.

### Resolving the Emeritus

An Emeritus is a decaying asset, so the successor sets itself a deadline for dealing with one: on joining, it arms an early milestone on its own token watch — `claude-tokens watch --threshold 20 --threshold 50 ...` — as a **forcing point**. When that milestone fires, resolve the Emeritus one of two ways. Don't let it drift past.

- **Kill it — the default.** If it isn't actively adding value: `tmux kill-window -t ForemanEmeritus`. No ceremony and no goodbye dispatch; a quiet comrade is just quiet.
- **Escalate — the exception.** If it *is* still adding value, it holds something the cell never absorbed. Surface that to your principal instead of quietly leaning on it: a near-full session is itself at risk of exhausting its context and losing what it knows, so how to preserve it is their call, not a dependency to take on silently.

Either way, querying an Emeritus is expensive — each input re-processes its whole context. That cost is the reason for the forcing point.

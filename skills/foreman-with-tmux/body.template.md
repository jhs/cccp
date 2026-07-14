# Tmux — comrade lifecycle mechanics

The Foreman sections above cover staffing authority and lifecycle decisions. This is the mechanical HOW: spawning, observing, and terminating comrades as tmux windows via `spawn-comrade` (on your `$PATH`).

## The model

Each comrade runs as a `claude` process in its own tmux window. The window name IS the role name — `Builder`, `Analyst`, whatever fits the slice. One window per role; `spawn-comrade` refuses duplicates.

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

When handing off to a successor Foreman:

1. **Rename your window first:** `tmux rename-window -t Foreman ForemanEmeritus`
2. **Spawn the successor:** `spawn-comrade -m <model> -e <effort> --skill foreman-with-tmux Foreman <slug>`

Rename-before-spawn is load-bearing — `spawn-comrade` refuses duplicate window names, so spawning before renaming fails on the name collision.

After the successor is settled, it terminates you: `tmux kill-window -t ForemanEmeritus`.

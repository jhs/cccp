# Driving agent TUIs with tmux

How to launch another interactive agent, watch its screen, type into it, and prove what it did — from inside an agent session. Every command here has been run in this repo.

## When this applies

- **You are one harness and the work involves another.** A Claude Code session fixing a Pi extension, or vice versa. You cannot reason your way to what the other harness does at runtime; you can run it and look.
- **Reproducing a bug that needs a real TUI.** Crashes on `/reload`, startup races, anything where the harness's own lifecycle is the subject. Non-interactive mode (`-p`) does not run the TUI and cannot exercise slash commands.
- **Verifying a fix in the real app**, not just in tests.
- **Multi-comrade cccp work** where you need a second live agent, or need to watch one.

If a unit test can answer the question, use the test. This is for when the answer only exists in a live process.

## Step 0 — are you even in tmux?

Check before planning any of this. `$TMUX` is inherited by the Bash tool.

```bash
[ -n "$TMUX" ] && tmux display-message -p 'in tmux: #S:#I.#P' || echo "NOT in tmux"
```

**If not in tmux, stop and escalate to the user.** You cannot create the session yourself and attach them to it. Give them a paste-able line:

> I need tmux to drive a live agent TUI for this. Please run this in a new terminal, then re-ask:
> ```
> tmux new-session -s work 'claude --continue'
> ```
> (`--continue` resumes the most recent session in this directory; `--resume` lets you pick one.)

## The core loop

### 1. Launch in a detached window, wrapped so it survives a crash

```bash
tmux new-window -d -n <name> -c <cwd> "<command>; echo \"=== EXITED rc=\$? ===\"; sleep 900"
```

The `echo` + `sleep` tail is load-bearing. A bare command whose process dies takes the window with it, and the stack trace you were trying to capture is gone. With the tail, the window stays and the pane holds both the error and the exit code.

**Do not pipe the command's stdout** (`| tee`, `| cat`). A TUI that finds stdout is not a terminal exits immediately — measured with `pi`. Read the screen with `capture-pane` instead.

### 2. Type into it — text and Enter as two separate calls

```bash
tmux send-keys -t <name> 'your text here'
sleep 1
tmux send-keys -t <name> Enter
```

Never bundle the `Enter` into the first call. It works for short input and silently stops working as the input grows, because the TUI's paste detection eats the trailing `Enter` and the message sits unsent. The skill states the rule and the measurements — see [Citing the skill](#citing-the-skill).

### 3. Wait for it to settle, then look

Fixed sleeps guess. Poll until the screen stops changing:

```bash
# Block until the pane is unchanged for `stable` consecutive polls.
tmux_settle() {
	local target=$1 stable=${2:-3} interval=${3:-2} prev="" same=0 hash
	while :; do
		hash=$(tmux capture-pane -p -t "$target" | md5sum)
		if [ "$hash" = "$prev" ]; then same=$((same + 1)); else same=0; fi
		[ "$same" -ge "$stable" ] && return 0
		prev=$hash
		sleep "$interval"
	done
}
```

```bash
tmux_settle <name> && tmux capture-pane -p -t <name> | tail -30
```

**The pane is not the record.** It holds one screenful, and a TUI redraws over itself. For anything you intend to assert on, read the process's own log file. Use the pane to see *where* it is; use logs to prove *what happened*.

**The input line is not evidence either.** Claude Code renders an LLM auto-suggestion there as faded ghost text that `capture-pane` cannot distinguish from real input. Confirm from the transcript, the token counter, or the reply — never the input line.

## Cheat sheet

| Goal | Command |
|---|---|
| Am I in tmux? | `[ -n "$TMUX" ]` |
| Where am I? | `tmux display-message -p '#S:#I.#P'` |
| List windows | `tmux list-windows -F '#{window_index} #{window_name} #{pane_pid}'` |
| New detached window | `tmux new-window -d -n NAME -c DIR "CMD; echo \"=== EXITED rc=\$? ===\"; sleep 900"` |
| Screenshot a pane | `tmux capture-pane -p -t NAME \| tail -40` |
| Include scrollback | `tmux capture-pane -p -S -200 -t NAME` |
| Send text (then Enter separately) | `tmux send-keys -t NAME 'text'` |
| Submit | `tmux send-keys -t NAME Enter` |
| Kill a window (and its children) | `tmux kill-window -t NAME` |
| New detached session | `tmux new-session -d -s NAME 'CMD'` |

## Citing the skill

The mechanics of driving a comrade's terminal — observing, terminating, `send-keys` and its traps — are owned by `skills/captain-with-tmux/body.template.md` and are **not** restated here. They were, once; the two copies drifted into contradicting each other, which is how the `send-keys` bug survived. Pull them when you need them:

```bash
awk '/^## /{f=0} /^## (Observing a comrade|Terminating a comrade|Driving a comrade TUI)/{f=1} f' \
  skills/captain-with-tmux/body.template.md
```

That is a template, so `@@COMRADE_ID@@` and friends appear unsubstituted — read them as "your own comrade id". Headings are the citation handle: they are unique across every skill and carry no apostrophes (a test enforces both, because an apostrophe breaks the quoted pattern above). Reword a heading and you must re-point its citations.

## Do not spawn a comrade to test a harness

`spawn-comrade` builds a *working comrade*: it joins a cell and loads the cccp skill stack. That is the right tool when the thing under test is genuinely multi-comrade behavior, and the wrong one for isolating harness behavior — it injects a cell join and several thousand tokens of doctrine into the very session whose behavior you are trying to characterize.

For reproduction work, launch the bare harness yourself (`tmux new-window` above, plus `--no-extensions` and a single `--extension`) and inject cell traffic from a shell instead. It has no hidden setup: it checks for `tmux`, the harness binary, a live session, and explicit `--model`/`--effort`, then fails loudly on any of them.

## Harness notes

### Pi

```bash
pi --extension <file.ts>          # load one extension ad hoc
pi --no-extensions --extension X  # ONLY X — isolates a probe from your real config
pi -p --model <id> '<prompt>'     # non-interactive, no TUI
pi --list-models                  # resolve a model name to an id
```

`/reload` re-reads extensions, skills, prompts and themes **in process**. It replaces the extension instance and invalidates any `pi`/`ctx` an extension captured; module scope does not survive it.

### Claude Code

A Claude Code process will not exit because you asked it to; `tmux kill-window` is the only exit path. Wind-down doctrine for a real comrade lives in the skill's `## Terminating a comrade`.

## Zero-cost harness probes

Extension lifecycle hooks (`session_start`, `session_shutdown`) fire without any model call. A throwaway extension that writes to a file from those hooks answers questions about harness internals — what survives a reload, what an event carries, whether an API works at a given moment — for free, in the real TUI.

```bash
# Probe: does module state survive /reload?
cat > /tmp/probe.ts <<'EOF'
import * as fs from "node:fs";
const moduleId = Math.random().toString(36).slice(2, 8);
export default function (pi: any) {
	pi.on("session_start", (e: any, ctx: any) =>
		fs.appendFileSync("/tmp/probe.log", `reason=${e.reason} moduleId=${moduleId}\n`));
}
EOF
tmux new-window -d -n probe "pi --no-extensions --extension /tmp/probe.ts; sleep 60"
sleep 9; tmux send-keys -t probe '/reload'; sleep 1; tmux send-keys -t probe Enter
sleep 8; cat /tmp/probe.log; tmux kill-window -t probe
```

**Run the interesting action twice.** Once proves it happens; twice reveals accumulation, idempotency, and staleness. State that looks correct after one `/reload` often is not after two.

You can also ask a foreign harness about itself — `pi -p --model <id> '<question about its own API>'` — since it can read its own docs and typings. **Verify the answer against the installed typings before building on it.**

## With a cccp cell

Use `local-fs` (`cccp config` to confirm) — cells are free and local, so scratch cells cost nothing.

**Inject traffic without a second agent.** Any shell can act as a comrade by setting the id:

```bash
CCCP_COMRADE_ID="dev@host:cc-probe1" cccp dispatch <cell> --to <target-id> - <<< "message body"
```

**Verify what actually landed**, rather than trusting a pane:

```bash
cccp read <cell> | tail -5          # full history, including messages nobody received
cccp status <cell>                  # is my watchtower alive, and if not, why it stopped
pgrep -af "cccp watchtower <cell>"  # is the process really there
```

A message sitting in `cccp read` that never appeared in the target's pane is proof the target is deaf — the single most useful check when a comrade goes quiet.

A comrade's id is printed when it joins and is in `$CCCP_COMRADE_ID` inside its own session.

## Clean up

Scratch windows, sessions, and cells all outlive the task otherwise.

```bash
tmux kill-window -t <name>
cccp rm <cell> --yes
```

Kill the window before removing the cell — the watchtower is a child of the window's process and dies with it.

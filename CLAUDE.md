# Branching & Releases

`main` is the published state — users install from it. Never commit directly to `main`; do all work on a branch. Cutting a release means bumping both manifests in lockstep and tagging. Full procedure: [docs/branching-and-releases.md](docs/branching-and-releases.md).

# Driving a live agent TUI

Some work can only be settled by running another agent and watching it: reproducing a harness-level bug, verifying a fix in the real app, or anything where you are one harness (Claude Code, Pi) and the subject is another. When that is the situation — or you notice it has become the situation — read [docs/driving-agent-tuis-with-tmux.md](docs/driving-agent-tuis-with-tmux.md) and use those techniques.

Check `[ -n "$TMUX" ]` early. Without tmux none of it is available, and that is a question for the user, not a workaround to invent.

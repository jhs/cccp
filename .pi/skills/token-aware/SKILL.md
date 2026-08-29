---
name: token-aware
description: Report Pi context-window usage or opt in to milestone notifications. Use when the user asks about context fullness, tokens remaining, nearness to compaction, or wants token-usage monitoring.
---

# Token-aware

Pi provides context usage without a statusline or background process. It is inert until you call `token_watch`; merely having the extension installed does not monitor or notify.

## Query usage now

Call `token_status`. It returns the current context usage, or the last known reading when Pi has not yet produced a new one after compaction.

## Watch milestones

Call `token_watch` to opt in to notifications after future turns cross a context threshold:

- Omit `thresholds` for the standard `50`, `75`, `90`, and `95` percent milestones.
- Pass `thresholds` to choose them, each `{percent}` or `{percent, reminder}` — for example `[{percent: 80}, {percent: 95, reminder: "prepare to terminate"}]`.
- A crossing reports the current usage, elapsed time and usage velocity since the prior reading, ETAs for later milestones, and the reminder if the milestone carried one.
- A `reminder` is your own note to your future self, played back verbatim at the end of the crossing line behind `| REMINDER:`. Write it as an instruction rather than a label — `prepare to terminate`, not `nearly full` — because that line is all you get, and it matters most after a compaction, which re-arms every milestone and takes the surrounding plan out of your context at the same time.
- A percentage repeated, or outside 0 to 100, fails the call instead of quietly narrowing the watch. Fix it and call again.
- A milestone below the reading the watch starts at never fires; the opening line names it rather than leaving you expecting it.

Call `token_watch` with `enabled: false` when monitoring is no longer wanted. It sends no more notifications until you start it again.

## Being seen from outside

Both tools above report only to you. When `CCCP_DO_PI_TELEMETRY` is set, each turn also leaves a snapshot on disk, so a coordinator can read this session's context usage with `claude-tokens status $CCCP_COMRADE_ID` without asking you. That is off by default; when it is off, nobody outside this session can see how full your context is, so say so yourself before going quiet.

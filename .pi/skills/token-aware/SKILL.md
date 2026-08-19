---
name: token-aware
description: Report Pi context-window usage or opt in to milestone notifications. Use when the user asks about context fullness, tokens remaining, nearness to compaction, or wants token-usage monitoring.
---

# Token-aware

Pi's CCCP extension provides context usage without a statusline or background process. It is inert until you call `token_watch`; merely having the extension installed does not monitor or notify.

## Query usage now

Call `token_status`. It returns the current context usage, or the last known reading when Pi has not yet produced a new one after compaction.

## Watch milestones

Call `token_watch` to opt in to notifications after future turns cross a context threshold:

- Omit `thresholds` for the standard `50`, `75`, `90`, and `95` percent milestones.
- Pass `thresholds` with percentage values to choose milestones, for example `[80, 95]`.
- After a notification, send the relevant comrade a targeted status beginning `Tokens: NN%`, then continue working.

Call `token_watch` with `enabled: false` when monitoring is no longer wanted. It sends no more notifications until you start it again.

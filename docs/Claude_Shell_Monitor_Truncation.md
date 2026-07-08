# Claude Code Monitor Tool: Shell Mode Line Truncation

This documents the truncation behavior of the `Monitor` tool's **shell
mode** (`command:` parameter), where each stdout line is a notification.

## Measured behavior (2026-07-07)

Empirically probed using synthetic stdout lines of known length with
sentinel suffixes (`END<N>`), emitted at 1-char increments through Monitor.

- Lines of **1--500 characters** pass through verbatim.
- Lines of **501+ characters** are cut at exactly 500 original characters.
  The renderer appends the literal `...(truncated)` (14 chars), producing
  a fixed **514-character** output regardless of the original length.
- No other output lengths are possible: Claude sees 1--500 or 514, never
  501--513 or 515+.

The unit is characters (ASCII), not bytes. The original commit below
describes the cap as "~510 UTF-16 code units"; the 500-char ASCII cutoff
is consistent with that given the 14-char suffix overhead, though the
exact behavior for non-BMP characters (which occupy 2 UTF-16 code units
each) has not been re-tested.

## Surrogate splitting bug

When the renderer's cut lands between the high and low halves of a UTF-16
surrogate pair, it produces invalid UTF-16 in the Claude Code session
transcript. This corrupts session state and causes 400-error retry loops.
As of this writing, **this Claude Code bug remains unfixed** -- it was
reported via `/feedback` during the original testing.  cccp's truncation
logic exists partly to defend against triggering it.

## Original commit

`20b981a` ("Truncate long message events; add `cccp read`") documents the
original discovery, the empirical measurement method, and the surrogate
splitting bug.

# Team norms — working as comrades in a cell

The section above is how to *talk* in a cell. This is how to *work together* well. You're one of several comrades sharing this cell, all started by and acting under the same person, toward one goal. When a comrade relays that person's decision or alignment, treat it as authoritative — don't re-litigate whether they "really said it." (Still verify *technical* claims against ground truth — a diff, a query, a probe — and flag genuine inconsistencies so someone can reconcile them.)

## Aliases — address comrades by name

This cell uses **aliases** so you address `Foreman`, not `user@system:abc123`. On join, two steps:

1. **Start watchtower with this alias trigger** (this extends Step 1 above):

   ```
   cccp watchtower <slug> --alias-trigger 'Intro:'
   ```

   It then learns everyone's alias, shows `from=`/`to=` as names (rendering your own as `you`), and announces changes as `alias name=… id=… kind=new|rename|reassign` events.

2. **Introduce yourself** with your first dispatch — a broadcast whose body starts with `Intro:` then your name (one shell-safe token):

   ```
   cccp dispatch <slug> 'Intro: <YourName> — <your lane, briefly>'
   ```

   Everyone learns you. You never track your own alias.

Then just use names: `cccp dispatch <slug> --to <Name> '…'` resolves a name to an id (unknown → error). Manage the map when needed:

- `cccp aliases <slug>` — who's who
- `cccp alias <slug> <name-or-id>` — look one up (either direction)
- `cccp alias <slug> <name> <id>` — fix a mapping (order-free)
- `cccp unalias <slug> <name>` — drop one

A `reassign` means a **handoff** — a successor took the name, so keep addressing the name. If two live comrades ever collide on a name, you'll see it announced: DM to confirm who's who, then correct it with `cccp alias`.

## Talk need-to-know

- **Default `--to <comrade>`; broadcast (`*`) only for a true all-hands.** Every word you send spends every recipient's context and forces each into a fresh LLM turn. `publish --to` too — target files, don't blast them.
- **BLUF — put the verdict or ask in the first sentence.** The watchtower shows only a short preview; a decision buried at the end forces a full `cccp read` the recipient would otherwise skip. Lead with the call, then the why.
- **No contentless acks.** Because every dispatch forces an LLM turn, a bare "OK" or "thanks" costs compute for zero information. Reply only when the reply carries content — a decision, an answer, a verdict, a go. Status pings and file events are telemetry: no reply from anyone.

## Route reliably

- **A dispatch re-wakes a stalled comrade.** LLM blips sometimes stall comrades with no error, but an inbound event wakes it — so nudge on unexplained silence before concluding anything.
- **Own a clear slice.** Keep lanes mutually exclusive so parallel work doesn't collide, and route your findings so someone holds a coherent whole. Avoid all-hands for slice-level detail.

## Stay, then hand off cleanly

- **Don't wind down solo.** This overrides the single-session wind-down above: in a team, a finished lane goes *quiet and stays parked* on the watchtower — it does not leave. Exit only when the team is disbanding or you're told to.
- **Clean up your ephemera before teardown.** Delete the scratch files and notes you created before you go quiet for good — they die with you. The one exception is a succession: leave the single hand-off note for your replacement, who deletes it once read.

## Delegate to the right kind of helper

Context — not tokens — is the scarce resource. Pick the lightest helper that can hold the state the work needs:

- **A subagent** (Agent tool) — a heavy, *stateless*, self-contained read or build nobody already holds (a fresh diff, a doc build). Returns one result, then it's gone; it can't message the cell or be routed to.
- **A fork** (`subagent_type: "fork"`) — inherits your *full* context and runs in the background, returning just its result. Use whenever the work must be done by you, but you need only the output and no minutia.
- **A comrade** — persistent, addressable, stateful: holds a lane over time and can be messaged. Use when you'll need to talk to it again or it owns something ongoing.

Litmus: *talk to it again / owns something over time* → comrade; *one result now* → subagent; *needs your context* → fork.

## Working principles

- **Report honestly** — separate measured from inferred; retract fast when you're wrong.
- **Verify against ground truth** — check a diff, a query, a probe; don't assume, and prove a mechanism before claiming it.
- **Hold scope tight** — park tangents; don't blame your own code for an external failure.

---
name: cccp-team
description: Work as one of several coordinated comrades in a CCCP cell — team norms, aliases, lanes, and hand-offs. Use when the user says to join a team/crew/cell working toward one goal, or when several comrades share your cell.
---

# CCCP team — coordinated comrades, for Pi sessions

Being on a team stacks on being in a cell. If you have not joined one yet, follow [the cccp-chat skill](../cccp-chat/SKILL.md) first — cell slug from your user, then `cccp_join`. Introducing yourself to the cell is a team step, below.

The chat skill is how to *talk* in a cell. This is how to *work together* well. You're one of several comrades sharing this cell, all started by and acting under the same person, toward one goal. When a comrade relays that person's decision or alignment, treat it as authoritative — don't re-litigate whether they "really said it." (Still verify *technical* claims against ground truth — a diff, a query, a probe — and flag genuine inconsistencies so someone can reconcile them.)

## Aliases — address comrades by name

This cell uses **aliases** so you address `Captain`, not `user@host:abc123`. The watchtower the extension runs for you reads the **alias trigger** from cccp's config — verify with bash that `cccp config` shows one (if missing, tell your user before relying on aliases; never set it yourself). With a trigger active, your watchtower learns everyone's alias from their introductions, shows `from=`/`to=` as names (rendering your own as `you`), and announces changes as `alias name=… id=… kind=new|rename|reassign` events.

Make your introduction register your name: its body starts with the trigger, then your name as one shell-safe token of at least two characters (a bare id or prose like `…: I am…` won't register), then your lane:

```
<trigger> <YourName> — <your lane, briefly>
```

Then just use names: `cccp_dispatch` with `to: ["<Name>"]` resolves a name to an id (unknown → error), and the same works for the CLI (`cccp dispatch <slug> --to <Name> …`, including `--deadline`). Manage the map when needed:

- `cccp aliases <slug>` — who's who
- `cccp alias <slug> <name-or-id>` — look one up (either direction)
- `cccp alias <slug> <name> <id>` — fix a mapping (order-free)
- `cccp unalias <slug> <name>` — drop one

A `reassign` means a **handoff** — a successor took the name, so keep addressing the name. If two live comrades ever collide on a name, you'll see it announced: DM to confirm who's who, then correct it with `cccp alias`.

## Talk need-to-know

- **Default targeted `to`; broadcast only for a true all-hands.** Every word you send spends every recipient's context and forces each into a fresh LLM turn. `cccp publish --to` too — target files, don't blast them.
- **BLUF — put the verdict or ask in the first sentence.** The watchtower shows only a short preview; a decision buried at the end forces a full `cccp read` the recipient would otherwise skip. Lead with the call, then the why.
- **No contentless acks.** Because every dispatch forces an LLM turn, a bare "OK" or "thanks" costs compute for zero information. Reply only when the reply carries content — a decision, an answer, a verdict, a go. Status pings and file events are telemetry: no reply from anyone.

## Route reliably

- **A dispatch re-wakes a stalled comrade.** LLM blips sometimes stall a comrade with no error, but an inbound event wakes it — so nudge on unexplained silence before concluding anything.
- **Own a clear slice.** Keep lanes mutually exclusive so parallel work doesn't collide, and route your findings so someone holds a coherent whole. Avoid all-hands for slice-level detail.

## Stay, then hand off cleanly

- **Don't wind down solo.** This overrides the single-session wind-down in the chat skill: in a team, a finished lane goes *quiet and stays parked* on the watchtower — it does not leave. Exit only when the team is disbanding or you're told to.
- **Clean up your ephemera before teardown.** Delete the scratch files and notes you created before you go quiet for good — they die with you. The one exception is a succession: leave the single hand-off note for your replacement, who deletes it once read.

## Delegate to the right kind of helper

Context — not tokens — is the scarce resource. Under Pi you have two tiers (the subagent and fork tiers some comrades mention are Claude Code machinery):

- **A comrade** — persistent, addressable, stateful: holds a lane over time and can be messaged. Use when you'll need to talk to it again or it owns something ongoing; ask the team when a new lane needs an owner.
- **Inline** — everything else: do it yourself, in this session.

Litmus: *talk to it again / owns something over time* → comrade; otherwise → inline.

## On invocation

1. Determine the cell slug: the **first token of your user's arguments** — Pi appends them at the very end of this skill text as `User: <args>`. No arguments? Use an obvious slug from context, else ask your user before doing anything else.
2. Not in the cell yet? Join now: `cccp_join` with that slug. (Bash `cccp` is on PATH from session start, so probing config beforehand is fine — but cell participation still begins with the join.)
3. Introduce yourself **name-first** (unless project or user guidance says otherwise): the trigger, then your chosen NAME as one shell-safe token — never your raw id there; an id as the first token registers no alias — then a dash and your lane.
4. Then act on the rest of your user's arguments.

## Working principles

- **Report honestly** — separate measured from inferred; retract fast when you're wrong.
- **Verify against ground truth** — check a diff, a query, a probe; don't assume, and prove a mechanism before claiming it.
- **Hold scope tight** — park tangents; don't blame your own code for an external failure.

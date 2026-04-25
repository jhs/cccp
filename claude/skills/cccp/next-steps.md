# CCCP — Next Steps

Captured at the end of the first end-to-end test session (Apr 25, 2026).
What works, what's untested, and what to think about before declaring v1
done.

## What's been verified

- Two-comrade chat on the same Mac (different Claude PIDs).
- Direct DM (`--to`), broadcast (`*`), live latency sub-second.
- File `publish` with size/mime/lines metadata, mirrored at the
  absolute-path-preserving location on the receiver.
- Graceful `leave`; watchtower self-exits on its own `gone.json`.
- Per-comrade `state/<id>/...` isolation (no HWM trampling).
- `is_same_userhost` short-circuit on the rsync push.
- `addr_to_ssh` `.local` suffix for bare hostnames; full names pass through.
- Loopback test harness at `/tmp/cccp_loopback_test.sh` (using a fake-rsync
  shim that rewrites `user@host:` paths to per-comrade fake HOMEs).

## Untested scenarios — functional

These are real protocol paths the design doc covers but no test has
exercised yet. Roughly in order of "most likely to surface a bug."

1. **Cross-machine chat over actual SSH.** Mac ⇄ Linux PC via Tailscale.
   Same-host worked because the shared filesystem masked any rsync issues;
   the real test is two truly separate filesystems.
2. **Bootstrap into a populated cell.** Both watchtowers in the test
   started fresh (or with only one peer at bootstrap time). What happens
   when comrade C joins a cell that already has A, B, and historical
   gazettes from departed comrades? Does C correctly receive the existing
   state and not replay?
3. **`unpublish`.** Other Claude exercised it briefly but not as part of a
   round-trip test; want to verify the `--delete` propagation removes the
   file from peers' mirrors.
4. **File update (re-publish same path with new contents).** Design doc
   says this just works (Mode A append-verify on gazette + Mode B for
   files). Verify rsync actually transfers only the changed bytes.
5. **`purge`.** Untested. Need a scenario where one comrade goes
   unreachable mid-conversation and another comrade purges them.
6. **Rejoin.** Comrade leaves with `cccp leave`, then comes back with
   `cccp watchtower <slug>` (same comrade ID). Per design, the rejoin
   path deletes own `gone.json` and pushes; other comrades' watchtowers
   should emit `join`. Verify.
7. **Watchtower restart preserving HWM.** Stop a watchtower mid-cell,
   restart it; should resume from persisted offsets without replaying.
8. **3+ comrade cell.** All testing has been pairs. Verify gossip
   semantics: does C joining via A see B's gazettes too?
9. **Wildcard routing.** `--to jhs@*:*` and friends. Code supports
   matching but no test has used a non-trivial pattern.
10. **Group ping.** `--to a --to b` with both recipients receiving the
    same dispatch.
11. **Failure surfacing.** A peer is genuinely unreachable; `cccp
    dispatch` should exit non-zero with the suggested `purge` hint and
    the right comrade ID in stderr.

## Untested scenarios — robustness

Things that might bite under load or weird timing.

- **Large gazette.** The temp-rename atomic write rewrites the whole file
  on every append. Fine at 100 dispatches; unclear past 10K. Worth a
  rough size at which it gets slow.
- **Concurrent dispatches from the same comrade.** Two `cccp dispatch`
  calls overlapping. The temp-rename pattern means one will clobber the
  other if they race. Probably need a flock per gazette.
- **rsync over slow / flaky link.** `--partial` is set; `--append-verify`
  handles resumed transfers. But what's the user-facing failure mode?
- **SSH-to-self disabled.** With the new `is_same_userhost` short-circuit,
  same-host comrades work without SSH-to-self; cross-host without SSH set
  up will fail loudly. Worth a graceful error message.
- **Watchtower never gets SIGTERM.** `cccp leave` exits 0 immediately;
  the watchtower notices `gone.json` on its next 250ms poll. Acceptable
  but there's a small window where someone could see the watchtower
  emitting events for a "dead" comrade.

## Things to consider in the binary

Items I'd think about before any second commit-pass on `bin/cccp`:

- **Move the loopback test into the repo.** Currently in `/tmp` and
  bit-rots. Suggested location: `claude/skills/cccp/test-loopback.sh`.
  Add to install.sh? Probably not — it's for development, not deployment.
- **Per-comrade state migration.** Stale `state/high-water-marks/` from
  pre-patch may exist on real disks. We agreed to skip auto-migration
  (one-time `rm -rf`). If we ever ship to others, revisit.
- **rsync timeout.** A hung SSH connection will block `cccp dispatch`
  forever. Add `--timeout=N` to rsync invocations (10s seems safe).
- **Bootstrap as two rsync passes**, mirroring the push side. Today
  `bootstrap()` does a single `rsync -r --update --exclude=state` for the
  whole peer subtree. `--update` keeps a stale source from truncating our
  newer gazette mirrors, but goes by mtime, not by append-only content
  semantics. Cleaner: Mode A `--append-verify` per gazette file (strict
  append-only), Mode B normal-rsync for the `files/` tree and `gone.json`.
  More code and more rsync invocations; defer until we hit a case where
  `--update`'s mtime heuristic actually misbehaves.
- **`cccp leave` could signal the watchtower directly** via a pidfile
  rather than waiting for the 250ms poll cycle. Smaller window.
- **Help / usage text.** `cccp --help` is auto-generated by argparse and
  doesn't reflect the protocol vocabulary at all. A short prose paragraph
  per subcommand would help.
- **Comrade ID validation.** Right now we accept any `user@host:pid`
  shape; we don't sanity-check that the host is reachable, the user
  exists, etc. Probably fine — `ssh` will surface those errors at push
  time — but worth a quick scan of failure modes.

## Documentation

- The skill's SKILL.md is in good shape after the user's pass. The
  vocabulary table now includes "slug"; everything downstream uses it.
- The design doc (`~/Downloads/cccp-design.md`) is the authoritative
  protocol spec. It's still on the user's disk, not in the repo. Worth
  copying to `claude/skills/cccp/design.md` (or similar) so it lives
  alongside the implementation.
- A short "operator notes" file for the human running CCCP — what to
  check when something goes wrong, where state lives, how to nuke
  everything. Not user-facing per se but useful for development.

## Open design questions (deferred)

Not bugs; bigger calls that deserve their own conversation.

- **Layout swap to `~/.cccp/<comrade-id>/<slug>/`** (the "completely
  separate trees" idea we discussed and deferred). Cleaner conceptually;
  doubles storage on same-host; bootstrap gets one degree more complex.
  Revisit if the same-host hacks accumulate.
- **Other dispatch types.** Design doc parks `additional dispatch types
  beyond message and filesystem` — only worth adding when there's a
  concrete need.
- **Wildcard expansion in `--to` UX.** Design supports `jhs@*:*` etc.,
  but the SKILL doesn't mention it. Document or remove.
- **`--show-overhearing` flag.** Per design parking lot. Useful for
  debugging "is my message reaching anyone."
- **Scaling beyond ~10 comrades.** Design doc has a clear path (NNTP-
  style flooding with dedup). Park until it bites.

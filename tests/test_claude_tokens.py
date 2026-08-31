#!/usr/bin/env python3
"""Output-contract tests for the token telemetry helper."""
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin" / "claude-tokens"
loader = SourceFileLoader("claude_tokens", str(BIN))
spec = importlib.util.spec_from_loader(loader.name, loader)
claude_tokens = importlib.util.module_from_spec(spec)
loader.exec_module(claude_tokens)

CC_SID = "4f2a1b8c-1111-4c9a-9f1e-3b7a55d0c2e1"   # comrade cc-4f2a1b
PI_SID = "01920000-2222-7c9a-9f1e-3b7a5599ff01"   # comrade pi-99ff01, UUIDv7


def snapshot(sid, pct=50, used=100_000, size=200_000, updated_at=None, **extra):
    payload = {
        "session_id": sid,
        "session_name": sid[:8],
        "model": {"display_name": "Opus"},
        "context_window": {"context_window_size": size,
                           "total_input_tokens": used,
                           "total_output_tokens": 0,
                           "used_percentage": pct},
    }
    if updated_at is not None:
        payload["updated_at"] = updated_at
    payload.update(extra)
    return payload


class TreeCase(unittest.TestCase):
    """A temporary snapshot tree, with the reader pointed at it."""

    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.data, ignore_errors=True)
        os.environ["CCCP_PLUGIN_DATA"] = str(self.data)
        self.addCleanup(os.environ.pop, "CCCP_PLUGIN_DATA", None)
        self.tele = self.data / "telemetry" / claude_tokens._version_segment()

    def write(self, producer, name, payload):
        d = self.tele / producer
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{name}.json"
        path.write_text(json.dumps(payload))
        return path

    def run_cli(self, *argv):
        """Run the real CLI against the tree, with no session in the ambient env."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")}
        p = subprocess.run([str(BIN), *argv], capture_output=True, text=True, env=env)
        return p


class SnapshotTree(TreeCase):
    """The reader finds snapshots by session id, not by producer directory."""

    def test_finds_a_session_under_any_producer_directory(self):
        for producer in ("claude-code", "pi", "harness-invented-tomorrow"):
            with self.subTest(producer=producer):
                sid = f"sid-{producer}"
                self.write(producer, sid, snapshot(sid))
                hits = claude_tokens.match_target(sid, claude_tokens.scan())
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0][0].parent.name, producer)

    def test_missing_session_is_reported_as_absent_not_guessed(self):
        self.write("claude-code", "present", snapshot("present"))
        r = claude_tokens.report("absent", claude_tokens.scan())
        self.assertEqual(r["error"], "no snapshot")

    def test_newest_session_spans_producers_and_skips_sidecar_files(self):
        self.write("claude-code", "old", snapshot("old", updated_at=1000))
        self.write("pi", "new", snapshot("new", updated_at=2000))
        # auth-status.json shares the directory and is not a snapshot: it carries
        # no session_id, and its mtime is newer than either snapshot's reading.
        self.write("claude-code", "auth-status", {"account": "someone"})
        self.assertEqual(claude_tokens.newest_session(claude_tokens.scan()), "new")

    def test_unreadable_snapshot_does_not_sink_the_scan(self):
        (self.tele / "claude-code").mkdir(parents=True)
        (self.tele / "claude-code" / "truncated.json").write_text("{not json")
        self.write("pi", "good", snapshot("good", updated_at=2000))
        self.assertEqual(claude_tokens.newest_session(claude_tokens.scan()), "good")


class ComradeTargets(TreeCase):
    """Comrade ids anchor at the end their own harness derives them from."""

    def setUp(self):
        super().setUp()
        self.write("claude-code", CC_SID, snapshot(CC_SID))
        self.write("pi", PI_SID, snapshot(PI_SID))
        self.snaps = claude_tokens.scan()

    def matched(self, target):
        return [s["session_id"] for _, s in
                claude_tokens.match_target(target, self.snaps)]

    def test_cc_id_anchors_on_the_leading_hex(self):
        self.assertEqual(self.matched("cc-4f2a1b"), [CC_SID])

    def test_pi_id_anchors_on_the_trailing_hex(self):
        self.assertEqual(self.matched("pi-99ff01"), [PI_SID])

    def test_anchoring_at_the_wrong_end_finds_nothing(self):
        # The whole point of carrying the harness tag: `pi-` on a leading match,
        # or `cc-` on a trailing one, is how a hand-rolled pipeline gets it wrong.
        self.assertEqual(self.matched("pi-4f2a1b"), [])
        self.assertEqual(self.matched("cc-99ff01"), [])

    def test_pi_siblings_sharing_a_timestamp_prefix_stay_distinct(self):
        """Two Pi sessions started minutes apart really do share a leading 6 hex.

        This is the shape observed in ~/.pi/agent/sessions: UUIDv7 leads with a
        timestamp, so anchoring a `pi-` id at the front would answer for either
        session at random. The trailing anchor separates them."""
        a = "019ff6a2-970e-754c-9336-f612f6fc1234"
        b = "019ff6ae-0414-7689-a591-665694de5678"
        self.assertEqual(a[:6], b[:6], "fixture no longer shows the collision")
        self.write("pi", a, snapshot(a))
        self.write("pi", b, snapshot(b))
        snaps = claude_tokens.scan()
        self.assertEqual([s["session_id"] for _, s in
                          claude_tokens.match_target("pi-fc1234", snaps)], [a])
        self.assertEqual([s["session_id"] for _, s in
                          claude_tokens.match_target("pi-de5678", snaps)], [b])
        self.assertEqual(claude_tokens.report("cc-019ff6", snaps)["error"],
                         "ambiguous")

    def test_user_at_host_is_parsed_off_and_ignored(self):
        for target in ("jason@boxy:cc-4f2a1b", "someone@elsewhere:cc-4f2a1b"):
            with self.subTest(target=target):
                self.assertEqual(self.matched(target), [CC_SID])

    def test_full_session_id_still_matches_exactly(self):
        self.assertEqual(self.matched(CC_SID), [CC_SID])

    def test_a_target_is_never_a_glob(self):
        self.assertEqual(self.matched("*"), [])

    def test_ambiguity_is_reported_not_resolved_by_taking_the_first(self):
        twin = CC_SID[:6] + "-dead-4c9a-9f1e-3b7a55d0ffff"
        self.write("pi", twin, snapshot(twin))
        r = claude_tokens.report("cc-4f2a1b", claude_tokens.scan())
        self.assertEqual(r["error"], "ambiguous")
        self.assertEqual(r["matches"], sorted([CC_SID, twin]))


class Identity(TreeCase):
    """Who a target is, and where to go read them (#37).

    The snapshot is already open when a target resolves, so answering "which
    session is this comrade, and where does it live" costs a projection rather
    than the anchored directory glob every caller was hand-rolling."""

    def setUp(self):
        super().setUp()
        self.write("claude-code", CC_SID, snapshot(
            CC_SID,
            transcript_path=f"/home/dev/.claude/projects/-home-dev-src-cccp/{CC_SID}.jsonl",
            cwd="/home/dev/src/cccp"))

    def resolved(self, target):
        return claude_tokens.report(target, claude_tokens.scan())

    def test_a_comrade_id_resolves_to_a_transcript_and_a_working_tree(self):
        """The pain #37 reports: an id in hand, and nowhere supported to take it."""
        r = self.resolved("cc-4f2a1b")
        self.assertEqual(r["session_id"], CC_SID)
        self.assertEqual(r["cwd"], "/home/dev/src/cccp")
        self.assertTrue(r["transcript_path"].endswith(f"{CC_SID}.jsonl"))
        self.assertEqual(Path(r["snapshot_path"]).name, f"{CC_SID}.json")

    def test_a_comrade_id_is_echoed_back_whole(self):
        """Forward lookup already knows the id, `user@host:` head and all - there
        is nothing to derive and nothing to drop."""
        self.assertEqual(self.resolved("dev@fs:cc-4f2a1b")["comrade_id"],
                         "dev@fs:cc-4f2a1b")

    def test_a_session_id_derives_the_comrade_id_at_its_own_anchor(self):
        """The reverse lookup, and the reason the producer directory is read at
        all: the two harnesses anchor at opposite ends and a bare session id
        cannot say which."""
        self.write("pi", PI_SID, snapshot(PI_SID))
        self.assertEqual(self.resolved(CC_SID)["comrade_id"], "cc-4f2a1b")
        self.assertEqual(self.resolved(PI_SID)["comrade_id"], "pi-99ff01")

    def test_a_derived_id_carries_no_user_or_host(self):
        """A snapshot records neither, deliberately - it is portable, and a host
        baked into one becomes a lie the moment it is copied to another machine.
        The bare tag is the honest answer, not a `user@host:` guessed from cwd."""
        r = self.resolved(CC_SID)
        self.assertEqual(r["comrade_id"], "cc-4f2a1b")
        self.assertNotIn("@", r["comrade_id"])

    def test_an_unknown_producer_derives_no_id_rather_than_guessing(self):
        """A harness added tomorrow writes into its own directory and is still
        found by session id (that is the producer glob). What cannot be invented
        for it is which end its ids anchor at, so no id is offered."""
        sid = "aaaaaaaa-2222-4c9a-9f1e-3b7a55d0beef"
        self.write("harness-invented-tomorrow", sid, snapshot(sid))
        r = self.resolved(sid)
        self.assertEqual(r["session_id"], sid)
        self.assertIsNone(r["comrade_id"])

    def test_identity_survives_a_session_with_no_reading_yet(self):
        """WHICH session a target names is known the moment it resolves. A fresh
        or just-compacted session has no usage to report and still has an
        identity, so `no reading` must not take the answer down with it."""
        fresh = "bbbbbbbb-3333-4c9a-9f1e-3b7a55d0cafe"
        self.write("claude-code", fresh,
                   {"session_id": fresh, "cwd": "/home/dev/src/other"})
        r = self.resolved(fresh)
        self.assertEqual(r["error"], "no reading")
        self.assertEqual(r["comrade_id"], "cc-bbbbbb")
        self.assertEqual(r["cwd"], "/home/dev/src/other")

    def test_workspace_supplies_the_directory_when_cwd_is_absent(self):
        sid = "cccccccc-4444-4c9a-9f1e-3b7a55d0f00d"
        self.write("claude-code", sid, snapshot(
            sid, workspace={"current_dir": "/home/dev/src/elsewhere"}))
        self.assertEqual(self.resolved(sid)["cwd"], "/home/dev/src/elsewhere")

    def test_a_producer_with_no_paths_says_so_rather_than_inventing_them(self):
        """Pi writes no cwd and no transcript path today. An absent field is
        reported absent - the contract's own rule - not filled with a plausible
        guess assembled from the session id."""
        self.write("pi", PI_SID, snapshot(PI_SID))
        r = self.resolved("pi-99ff01")
        self.assertEqual(r["comrade_id"], "pi-99ff01")
        self.assertIsNone(r["transcript_path"])
        self.assertIsNone(r["cwd"])

    def test_the_usage_line_is_unchanged_by_any_of_this(self):
        """The identity fields ride in the record, which `--json` emits. The text
        contract that skills/token-aware/SKILL.md documents must not move."""
        p = self.run_cli("status", "cc-4f2a1b")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), "50% (100k/200k) | snapshot age unknown")

    def test_json_carries_the_identity_fields(self):
        p = self.run_cli("status", "cc-4f2a1b", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        [r] = json.loads(p.stdout)
        self.assertEqual(r["comrade_id"], "cc-4f2a1b")
        self.assertEqual(r["cwd"], "/home/dev/src/cccp")
        self.assertTrue(r["transcript_path"])


class Numerator(unittest.TestCase):
    """Two spellings of used tokens, because harnesses genuinely differ."""

    def cw(self, **fields):
        return {"session_id": "s", "context_window": dict(context_window_size=200_000, **fields)}

    def test_a_single_total_is_a_complete_reading(self):
        m = claude_tokens.metrics(self.cw(total_tokens=76_000, used_percentage=38))
        self.assertEqual((m["used"], m["size"], m["pct"]), (76_000, 200_000, 38))

    def test_an_input_output_split_is_summed(self):
        m = claude_tokens.metrics(
            self.cw(total_input_tokens=70_000, total_output_tokens=6_000))
        self.assertEqual(m["used"], 76_000)
        self.assertAlmostEqual(m["pct"], 38)

    def test_total_tokens_wins_when_a_producer_writes_both(self):
        m = claude_tokens.metrics(
            self.cw(total_tokens=76_000, total_input_tokens=1, total_output_tokens=1))
        self.assertEqual(m["used"], 76_000)

    def test_a_window_size_with_no_numerator_is_not_a_reading(self):
        """Nothing counted the tokens, so 0% would be a confident lie."""
        self.assertIsNone(claude_tokens.metrics(self.cw()))
        self.assertIsNone(claude_tokens.metrics(self.cw(used_percentage=38)))


class ReadingAge(unittest.TestCase):
    """Staleness comes from the payload, never from filesystem metadata."""

    def test_age_is_measured_from_updated_at(self):
        age = claude_tokens.reading_age(snapshot("s", updated_at=time.time() - 90))
        self.assertAlmostEqual(age, 90, delta=5)

    def test_age_is_unknown_rather_than_invented_when_updated_at_is_absent(self):
        self.assertIsNone(claude_tokens.reading_age(snapshot("s")))


class Summary(unittest.TestCase):
    def test_usage_summary_excludes_model_cost_and_session(self):
        metric = {
            "pct": 75,
            "used": 150_000,
            "size": 200_000,
            "model": "Opus",
            "cost": 1.20,
        }
        self.assertEqual(claude_tokens.summary(metric), "75% (150k/200k)")
        self.assertEqual(claude_tokens.summary(metric, age=4),
                         "75% (150k/200k) | snapshot 4s old")
        self.assertEqual(claude_tokens.summary(metric, age=claude_tokens.AGE_UNKNOWN),
                         "75% (150k/200k) | snapshot age unknown")


class StatusOutput(TreeCase):
    """What `status` prints, target counts included."""

    def setUp(self):
        super().setUp()
        self.write("claude-code", CC_SID,
                   snapshot(CC_SID, pct=38, used=76_000, updated_at=time.time()))
        self.write("pi", PI_SID,
                   snapshot(PI_SID, pct=8, used=82_900, size=1_000_000))

    def test_one_target_prints_the_bare_line_it_always_has(self):
        out = self.run_cli("status", "cc-4f2a1b").stdout
        self.assertEqual(out, "38% (76k/200k) | snapshot 0s old\n")

    def test_one_missing_target_keeps_the_long_setup_hint(self):
        out = self.run_cli("status", "cc-000000").stdout
        self.assertIn("statusLine side-write may not be wired up", out)

    def test_several_targets_are_labelled_one_line_each(self):
        out = self.run_cli("status", "cc-4f2a1b", "pi-99ff01", "cc-000000").stdout
        self.assertEqual(out.splitlines(), [
            "cc-4f2a1b: 38% (76k/200k) | snapshot 0s old",
            "pi-99ff01: 8% (82.9k/1M) | snapshot age unknown",
            "cc-000000: no snapshot",
        ])

    def test_ambiguity_names_the_sessions_it_could_not_choose_between(self):
        twin = CC_SID[:6] + "-dead-4c9a-9f1e-3b7a55d0ffff"
        self.write("pi", twin, snapshot(twin))
        out = self.run_cli("status", "cc-4f2a1b", "pi-99ff01").stdout
        self.assertEqual(out.splitlines()[0],
                         "cc-4f2a1b: ambiguous: 2 match (4f2a1b-d…, 4f2a1b8c…)")

    def test_json_carries_the_fields_callers_would_otherwise_reformat(self):
        out = self.run_cli("status", "cc-4f2a1b", "cc-000000", "--json").stdout
        got = json.loads(out)
        self.assertEqual(got[0]["target"], "cc-4f2a1b")
        self.assertEqual(got[0]["session_id"], CC_SID)
        self.assertEqual(got[0]["producer"], "claude-code")
        self.assertEqual(got[0]["model"], "Opus")
        self.assertEqual((got[0]["pct"], got[0]["used"], got[0]["size"]),
                         (38, 76_000, 200_000))
        self.assertLess(got[0]["age"], 60)
        self.assertEqual(got[1], {"target": "cc-000000", "error": "no snapshot"})

    def test_json_reports_an_unaged_snapshot_as_null_not_as_now(self):
        got = json.loads(self.run_cli("status", "pi-99ff01", "--json").stdout)
        self.assertIsNone(got[0]["age"])
        self.assertIsNone(got[0]["updated_at"])


class WatchOutput(TreeCase):
    """What `watch` streams, across several targets in one process."""

    def watch(self, *argv, seconds=6):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")}
        p = subprocess.Popen([str(BIN), "watch", *argv, "--interval", "0.2"],
                             stdout=subprocess.PIPE, text=True, env=env)
        self.addCleanup(p.stdout.close)
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        return p

    def test_one_process_labels_every_target_and_follows_each(self):
        self.write("claude-code", CC_SID, snapshot(CC_SID, pct=38, used=76_000))
        p = self.watch("cc-4f2a1b", "pi-99ff01", "--threshold", "60")
        first = [p.stdout.readline() for _ in range(2)]
        self.assertEqual(sorted(first), [
            "cc-4f2a1b: Start watch: 38% (76k/200k)\n",
            "pi-99ff01: Waiting for first snapshot...\n",
        ])
        # A target that appears mid-watch is picked up: nothing was resolved once
        # at startup, and its producer directory was never named.
        self.write("pi", PI_SID, snapshot(PI_SID, pct=8, used=82_900, size=1_000_000))
        self.assertEqual(p.stdout.readline(),
                         "pi-99ff01: Start watch: 8% (82.9k/1M)\n")
        self.write("claude-code", CC_SID, snapshot(CC_SID, pct=70, used=140_000))
        line = p.stdout.readline()
        self.assertTrue(line.startswith("cc-4f2a1b: Crossed 60%: 70% (140k/200k) (+"),
                        line)

    def test_a_single_target_streams_the_unlabelled_lines_it_always_has(self):
        self.write("claude-code", CC_SID, snapshot(CC_SID, pct=38, used=76_000))
        p = self.watch("cc-4f2a1b")
        self.assertEqual(p.stdout.readline(), "Start watch: 38% (76k/200k)\n")

    def test_json_watch_emits_one_object_per_event(self):
        self.write("claude-code", CC_SID, snapshot(CC_SID, pct=38, used=76_000))
        p = self.watch("cc-4f2a1b", "--json", "--threshold", "60")
        start = json.loads(p.stdout.readline())
        self.assertEqual(start["event"], "start")
        self.assertEqual(start["target"], "cc-4f2a1b")
        self.write("claude-code", CC_SID, snapshot(CC_SID, pct=70, used=140_000))
        crossed = json.loads(p.stdout.readline())
        self.assertEqual(crossed["event"], "crossed")
        self.assertEqual(crossed["threshold"], 60)
        self.assertGreater(crossed["velocity_per_min"], 0)


class ThresholdSpecs(unittest.TestCase):
    """The `PCT[% REMINDER]` grammar and the plan it builds."""

    def parse(self, spec):
        return claude_tokens.parse_threshold(spec)

    def test_a_bare_percent_is_an_unlabelled_breakpoint(self):
        for spec in ("90", "90%", " 90 % ", "90.5"):
            self.assertEqual(self.parse(spec)[1], None, spec)
        self.assertEqual(self.parse("90.5")[0], 90.5)

    def test_everything_after_the_percent_is_the_reminder(self):
        self.assertEqual(self.parse("90% prepare to terminate"),
                         (90.0, "prepare to terminate"))
        # No separator punctuation to escape, so a reminder is free to contain any.
        self.assertEqual(self.parse("50% check Foo: then Bar | not Baz")[1],
                         "check Foo: then Bar | not Baz")
        # The percent sign is the agent's habit, not the grammar's requirement.
        self.assertEqual(self.parse("50 check status")[1], "check status")

    def test_a_reminder_that_trails_off_to_nothing_is_simply_unlabelled(self):
        self.assertEqual(self.parse("90%   ")[1], None)

    def test_a_percent_outside_the_window_is_refused(self):
        for spec in ("0", "0%", "101", "120% too late"):
            with self.assertRaises(claude_tokens.argparse.ArgumentTypeError, msg=spec):
                self.parse(spec)

    def test_something_that_does_not_start_with_a_number_is_refused(self):
        for spec in ("", "ninety", "prepare to terminate"):
            with self.assertRaises(claude_tokens.argparse.ArgumentTypeError, msg=spec):
                self.parse(spec)

    def test_the_plan_is_ordered_by_percent_whatever_order_it_was_given(self):
        plan = claude_tokens.threshold_plan(
            [(90.0, "prepare to terminate"), (50.0, None), (75.0, "report")])
        self.assertEqual(list(plan), [50.0, 75.0, 90.0])
        self.assertEqual(plan[90.0], "prepare to terminate")

    def test_a_repeated_percent_is_fatal_rather_than_deduplicated(self):
        # Both reminders survive to the crossing, or the command is refused. What
        # must not happen is one of them being dropped and the run continuing.
        for specs in ([(90.0, "first"), (90.0, "second")],
                      [(90.0, None), (90.0, None)],
                      [(90.0, "text"), (90.0, None)]):
            with self.assertRaises(SystemExit) as caught:
                claude_tokens.threshold_plan(specs)
            self.assertEqual(caught.exception.code, 1)


class ReminderPlayback(TreeCase):
    """What a labelled breakpoint puts on the line, and where."""

    def crossing(self, reminder, pct=90):
        # Re-seeded per call, so a test may build two independent climbs.
        self.write("claude-code", CC_SID, snapshot(CC_SID, pct=38, used=76_000))
        w = {"target": "t", "prev": None, "armed": set(), "problem": None}
        r = claude_tokens.report(CC_SID, claude_tokens.scan())
        plan = {float(pct): reminder}
        events = list(claude_tokens.advance(w, r, 1_000.0, plan))
        self.write("claude-code", CC_SID, snapshot(CC_SID, pct=pct, used=pct * 2_000))
        r = claude_tokens.report(CC_SID, claude_tokens.scan())
        events += list(claude_tokens.advance(w, r, 1_060.0, plan))
        return events

    def setUp(self):
        super().setUp()
        self.write("claude-code", CC_SID, snapshot(CC_SID, pct=38, used=76_000))

    def test_the_reminder_lands_last_behind_a_shouted_label(self):
        crossed = self.crossing("prepare to terminate")[-1]
        line = claude_tokens.watch_line(crossed)
        self.assertTrue(line.startswith("Crossed 90%: 90% (180k/200k) (+"), line)
        self.assertTrue(line.endswith(" | REMINDER: prepare to terminate"), line)

    def test_an_unlabelled_crossing_is_worded_exactly_as_it_always_was(self):
        line = claude_tokens.watch_line(self.crossing(None)[-1])
        self.assertNotIn("REMINDER", line)
        self.assertTrue(line.endswith(")"), line)

    def test_the_event_always_carries_a_reminder_key(self):
        # A --json consumer must never have to tell a missing key from no reminder.
        self.assertIsNone(self.crossing(None)[-1]["reminder"])
        self.assertEqual(self.crossing("do the thing")[-1]["reminder"], "do the thing")

    def test_a_breakpoint_below_the_starting_reading_is_reported_as_never_firing(self):
        start = self.crossing("check status of Foo Bar", pct=20)[0]
        # Whole, not just the percentage: being told something was lost without
        # being told what is the same silent loss, moved to the other end of the run.
        self.assertEqual(start["already_passed"],
                         [{"threshold": 20.0, "reminder": "check status of Foo Bar"}])
        self.assertEqual(claude_tokens.watch_line(start),
                         "Start watch: 38% (76k/200k) | SET TOO LATE, WILL NOT FIRE: "
                         "20% check status of Foo Bar")

    def test_skipped_breakpoints_are_echoed_as_the_caller_wrote_them(self):
        w = {"target": "t", "prev": None, "armed": set(), "problem": None}
        plan = {10.0: None, 20.0: "check status of Foo Bar", 90.0: "prepare to terminate"}
        start = next(claude_tokens.advance(
            w, claude_tokens.report(CC_SID, claude_tokens.scan()), 1_000.0, plan))
        # `PCT[ REMINDER]` each - the --threshold arguments handed straight back,
        # so the words are recognisably the caller's own. `;` separates, because a
        # reminder is free to contain a comma.
        self.assertEqual(claude_tokens.watch_line(start),
                         "Start watch: 38% (76k/200k) | SET TOO LATE, WILL NOT FIRE: "
                         "10%; 20% check status of Foo Bar")

    def test_a_start_below_every_breakpoint_says_nothing_extra(self):
        start = self.crossing("in good time")[0]
        self.assertEqual(start["already_passed"], [])
        self.assertEqual(claude_tokens.watch_line(start), "Start watch: 38% (76k/200k)")


@unittest.skipUnless(shutil.which("jq"), "cccp-statusline needs jq")
class WriterAgreesWithReader(TreeCase):
    """What cccp-statusline writes is what claude-tokens expects to read."""

    def test_statusline_snapshot_is_found_and_self_dated(self):
        payload = json.dumps(snapshot(CC_SID))
        before = time.time()
        subprocess.run([str(REPO / "bin" / "cccp-statusline"),
                        f"--plugin-data={self.data}"],
                       input=payload.encode(), check=True, capture_output=True)

        hits = claude_tokens.match_target("cc-4f2a1b", claude_tokens.scan())
        self.assertEqual(len(hits), 1, "reader did not find the statusline snapshot")
        written = hits[0][1]
        self.assertGreaterEqual(written["updated_at"], int(before))
        self.assertLess(claude_tokens.reading_age(written), 60)
        # Everything else goes through verbatim - no translation, no invention.
        self.assertEqual({k: v for k, v in written.items() if k != "updated_at"},
                         json.loads(payload))


if __name__ == "__main__":
    unittest.main(verbosity=2)

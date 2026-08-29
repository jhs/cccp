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

#!/usr/bin/env python3
"""Output-contract tests for the Claude Code token telemetry helper."""
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
loader = SourceFileLoader("claude_tokens", str(REPO / "bin" / "claude-tokens"))
spec = importlib.util.spec_from_loader(loader.name, loader)
claude_tokens = importlib.util.module_from_spec(spec)
loader.exec_module(claude_tokens)


def snapshot(sid, pct=50, updated_at=None, **extra):
    payload = {
        "session_id": sid,
        "session_name": sid,
        "model": {"display_name": "Opus"},
        "context_window": {"context_window_size": 200_000,
                           "total_input_tokens": 100_000,
                           "total_output_tokens": 0,
                           "used_percentage": pct},
    }
    if updated_at is not None:
        payload["updated_at"] = updated_at
    payload.update(extra)
    return payload


class SnapshotTree(unittest.TestCase):
    """The reader finds snapshots by session id, not by producer directory."""

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

    def test_finds_a_session_under_any_producer_directory(self):
        for producer in ("claude-code", "pi", "harness-invented-tomorrow"):
            with self.subTest(producer=producer):
                self.write(producer, f"sid-{producer}", snapshot(f"sid-{producer}"))
                path, payload = claude_tokens.find_snapshot(f"sid-{producer}")
                self.assertEqual(path.parent.name, producer)
                self.assertEqual(payload["session_id"], f"sid-{producer}")

    def test_missing_session_is_reported_as_absent_not_guessed(self):
        self.write("claude-code", "present", snapshot("present"))
        self.assertEqual(claude_tokens.find_snapshot("absent"), (None, None))

    def test_newest_session_spans_producers_and_skips_sidecar_files(self):
        self.write("claude-code", "old", snapshot("old", updated_at=1000))
        self.write("pi", "new", snapshot("new", updated_at=2000))
        # auth-status.json shares the directory and is not a snapshot: it carries
        # no session_id, and its mtime is newer than either snapshot's reading.
        self.write("claude-code", "auth-status", {"account": "someone"})
        self.assertEqual(claude_tokens.newest_session(), "new")

    def test_unreadable_snapshot_does_not_sink_the_scan(self):
        (self.tele / "claude-code").mkdir(parents=True)
        (self.tele / "claude-code" / "truncated.json").write_text("{not json")
        self.write("pi", "good", snapshot("good", updated_at=2000))
        self.assertEqual(claude_tokens.newest_session(), "good")


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


@unittest.skipUnless(shutil.which("jq"), "cccp-statusline needs jq")
class WriterAgreesWithReader(unittest.TestCase):
    """What cccp-statusline writes is what claude-tokens expects to read."""

    def test_statusline_snapshot_is_found_and_self_dated(self):
        data = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, data, ignore_errors=True)
        payload = json.dumps(snapshot("probe-session"))
        before = time.time()
        subprocess.run([str(REPO / "bin" / "cccp-statusline"),
                        f"--plugin-data={data}"],
                       input=payload.encode(), check=True, capture_output=True)

        os.environ["CCCP_PLUGIN_DATA"] = str(data)
        self.addCleanup(os.environ.pop, "CCCP_PLUGIN_DATA", None)
        path, written = claude_tokens.find_snapshot("probe-session")
        self.assertIsNotNone(path, "reader did not find the statusline snapshot")
        self.assertGreaterEqual(written["updated_at"], int(before))
        self.assertLess(claude_tokens.reading_age(written), 60)
        # Everything else goes through verbatim - no translation, no invention.
        self.assertEqual({k: v for k, v in written.items() if k != "updated_at"},
                         json.loads(payload))


if __name__ == "__main__":
    unittest.main(verbosity=2)

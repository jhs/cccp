#!/usr/bin/env python3
"""Output-contract tests for the Claude Code token telemetry helper."""
import importlib.util
from importlib.machinery import SourceFileLoader
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
loader = SourceFileLoader("claude_tokens", str(REPO / "bin" / "claude-tokens"))
spec = importlib.util.spec_from_loader(loader.name, loader)
claude_tokens = importlib.util.module_from_spec(spec)
loader.exec_module(claude_tokens)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)

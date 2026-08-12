#!/usr/bin/env python3
"""Tests for the Pi comrade extension (keyless half — no model calls).

Run: python3 tests/test_pi_comrade.py   (or: -m unittest -v)

Covers what must hold before any live Pi session is worth launching: the
extension ships at its agreed path, the pi-package manifest points at it, the
version stays in lockstep with the plugin manifest, the TypeScript typechecks,
and a Pi session with CCCP_CELL unset stays completely dormant (no watchtower,
no log). Tests needing the pi binary or node_modules skip LOUDLY when the tool
is absent — a skip must never read as a pass.

The live half (real cell join, targeted round trip) requires model credentials
and is exercised separately; see integrations/pi/README.md.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXTENSION = REPO / "integrations" / "pi" / "cccp-comrade.ts"


class PackageManifest(unittest.TestCase):
    def setUp(self):
        self.pkg = json.loads((REPO / "package.json").read_text())

    def test_extension_exists_at_agreed_path(self):
        self.assertTrue(EXTENSION.is_file(), f"missing: {EXTENSION}")

    def test_pi_manifest_points_at_extension_dir(self):
        dirs = self.pkg["pi"]["extensions"]
        resolved = [REPO / d for d in dirs]
        self.assertTrue(any(EXTENSION.parent == r.resolve() for r in resolved),
                        f"pi.extensions {dirs} does not cover {EXTENSION.parent}")

    def test_pi_package_keyword_present(self):
        self.assertIn("pi-package", self.pkg["keywords"])

    def test_version_lockstep_with_plugin(self):
        plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(self.pkg["version"], plugin["version"],
                         "package.json and .claude-plugin/plugin.json versions "
                         "must be bumped together (see CLAUDE.md)")


class ChatSkill(unittest.TestCase):
    SKILL = REPO / ".pi" / "skills" / "cccp-chat" / "SKILL.md"

    def setUp(self):
        self.text = self.SKILL.read_text()

    def test_skill_exists_with_frontmatter(self):
        head, sep, _body = self.text.partition("\n---\n")
        self.assertTrue(head.startswith("---\n") and sep,
                        "SKILL.md must open with a --- frontmatter block")
        self.assertIn("name: cccp-chat", head)
        self.assertIn("description:", head)

    def test_pi_manifest_covers_skill_dir(self):
        pkg = json.loads((REPO / "package.json").read_text())
        dirs = [(REPO / d).resolve() for d in pkg["pi"]["skills"]]
        self.assertTrue(any(str(self.SKILL).startswith(str(d) + os.sep) for d in dirs),
                        f"pi.skills does not cover {self.SKILL}")

    def test_skill_teaches_the_essentials(self):
        for needle in ("cccp_dispatch", "Comrade Introduction: ", "truncated=true",
                       "CCCP_COMRADE_ID", "never start one"):
            self.assertIn(needle, self.text)


class TypeCheck(unittest.TestCase):
    def test_extension_typechecks(self):
        if not (REPO / "node_modules" / ".bin" / "tsc").exists():
            self.skipTest("SKIPPED LOUDLY: node_modules absent - run `npm install` "
                          "to enable the typecheck test")
        r = subprocess.run(["npm", "run", "typecheck"], cwd=REPO,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, f"tsc failed:\n{r.stdout}\n{r.stderr}")


class Dormancy(unittest.TestCase):
    """CCCP_CELL unset => a plain pi run is completely unaffected."""

    def test_no_watchtower_and_no_log_without_cell(self):
        if shutil.which("pi") is None:
            self.skipTest("SKIPPED LOUDLY: pi binary not on PATH - "
                          "`npm install -g @earendil-works/pi-coding-agent` "
                          "to enable the dormancy test")
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "cccp-pi-comrade.log"
            env = {k: v for k, v in os.environ.items() if k != "CCCP_CELL"}
            env["CCCP_PI_LOG"] = str(log)
            r = subprocess.run(
                ["pi", "--mode", "rpc", "--no-skills",
                 "--extension", str(EXTENSION)],
                cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0,
                             f"pi exited {r.returncode}:\n{r.stderr[-2000:]}")
            self.assertFalse(log.exists(),
                             f"dormant extension wrote a log: {log.read_text() if log.exists() else ''}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

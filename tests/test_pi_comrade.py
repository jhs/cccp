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
import re
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

    def test_version_lockstep_with_cccp_binary(self):
        # The v3.2.0 release shipped with bin/cccp still announcing v=3.1.1 on
        # the ready line - a live Pi comrade caught it. Never again.
        src = (REPO / "bin" / "cccp").read_text()
        m = re.search(r'^CCCP_VERSION = "([^"]+)"', src, re.MULTILINE)
        self.assertIsNotNone(m, "CCCP_VERSION constant not found in bin/cccp")
        self.assertEqual(self.pkg["version"], m.group(1),
                         "bin/cccp CCCP_VERSION must join the version bump")


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
        for needle in ("cccp_join", "cccp_dispatch", "Comrade Introduction: ", "truncated=true",
                       "CCCP_COMRADE_ID", "never start one"):
            self.assertIn(needle, self.text)


class EnvSurface(unittest.TestCase):
    """The extension invents NO env vars: cell is a tool parameter, the binary
    self-locates, the log path is fixed. Only pre-existing cccp surface
    (CCCP_COMRADE_ID, CCCP_PLUGIN_DATA) may appear."""

    def test_retired_env_vars_stay_gone(self):
        src = EXTENSION.read_text()
        for retired in ("CCCP_CELL", "CCCP_BIN", "CCCP_PI_LOG"):
            self.assertNotIn(retired, src,
                             f"{retired} was deliberately removed; do not reintroduce")

    def test_bin_resolution_id_derivation_and_path_prepend(self):
        """Import the extension with Node's native type stripping and exercise
        the exported resolvers: cccp resolves to this repo's bin/cccp, the
        comrade id derives from the session id, and PATH gains the bin dir."""
        script = (
            'import("./integrations/pi/cccp-comrade.ts").then(m => {'
            '  const bin = m.cccpBin();'
            '  const problem = m.resolveEnvironment("abcdef99-1111-2222-3333-444444444444");'
            '  console.log(JSON.stringify({bin, problem,'
            '    id: process.env.CCCP_COMRADE_ID,'
            '    pathHead: process.env.PATH.split(":")[0]}));'
            '}, e => { console.error(e.message); process.exit(1); });'
        )
        with tempfile.TemporaryDirectory() as td:
            env = {k: v for k, v in os.environ.items() if k != "CCCP_COMRADE_ID"}
            env["CCCP_PLUGIN_DATA"] = td
            r = subprocess.run(["node", "--no-warnings", "-e", script], cwd=REPO,
                               env=env, capture_output=True, text=True, timeout=60)
        if r.returncode != 0 and "Unknown file extension" in r.stderr + r.stdout:
            self.skipTest("SKIPPED LOUDLY: this node cannot import TypeScript "
                          "natively (needs Node >= 23) - resolver test not run")
        self.assertEqual(r.returncode, 0, f"node failed:\n{r.stderr}")
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["bin"], str(REPO / "bin" / "cccp"))
        self.assertIsNone(out["problem"])
        self.assertRegex(out["id"], r"^[^@\s]+@[^:\s]+:abcdef$")
        self.assertEqual(out["pathHead"], str(REPO / "bin"))


class TypeCheck(unittest.TestCase):
    def test_extension_typechecks(self):
        if not (REPO / "node_modules" / ".bin" / "tsc").exists():
            self.skipTest("SKIPPED LOUDLY: node_modules absent - run `npm install` "
                          "to enable the typecheck test")
        r = subprocess.run(["npm", "run", "typecheck"], cwd=REPO,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, f"tsc failed:\n{r.stdout}\n{r.stderr}")


class Dormancy(unittest.TestCase):
    """No cccp_join call => a plain pi run is completely unaffected."""

    def test_no_watchtower_and_no_log_without_join(self):
        if shutil.which("pi") is None:
            self.skipTest("SKIPPED LOUDLY: pi binary not on PATH - "
                          "`npm install -g @earendil-works/pi-coding-agent` "
                          "to enable the dormancy test")
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "logs" / "pi-comrade.log"
            env = dict(os.environ)
            env["CCCP_PLUGIN_DATA"] = td
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

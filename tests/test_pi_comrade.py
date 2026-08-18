#!/usr/bin/env python3
"""Tests for the Pi comrade extension, in two halves (issue #22).

Run (keyless half only):        python3 tests/test_pi_comrade.py
Run everything, incl. live:     CCCP_LIVE_PI=1 python3 tests/test_pi_comrade.py

Keyless half — no model calls. Covers what must hold before any live Pi session
is worth launching: the extension ships at its agreed path, the pi-package
manifest points at it, the version stays in lockstep with the plugin manifest
and bin/cccp, the TypeScript typechecks, and a Pi session that never joins stays
completely dormant (no watchtower, no log). Tests needing the pi binary or
node_modules skip LOUDLY — a skip must never read as a pass.

Live half — a real Pi session joins a real (scratch) cell, so it spends model
credits and ~90s of wall clock. Its gate is a TRIPLE, all three required:
  1. CCCP_LIVE_PI=1            explicit opt-in; off by default
  2. `pi` on PATH
  3. credentials: ANTHROPIC_API_KEY or PI_API_KEY or ~/.pi/agent/auth.json
The auth.json arm is deliberate and NOT an oversight: issue #22 said "skips
without ANTHROPIC_API_KEY", but a subscription install of Pi authenticates from
its own auth store with no such variable in env (measured), so an env-key-only
gate would skip on every developer machine that can actually run the test. Do
not "fix" it back. Every unmet precondition skips LOUDLY.
"""
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXTENSION = REPO / "integrations" / "pi" / "cccp-comrade.ts"
CCCP = REPO / "bin" / "cccp"
ALIAS_TRIGGER = "Comrade Introduction:"


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
        for needle in ("cccp_join", "cccp_dispatch", "truncated=true",
                       "CCCP_COMRADE_ID", "never start one"):
            self.assertIn(needle, self.text)


class SetupSkill(unittest.TestCase):
    SKILL = REPO / ".pi" / "skills" / "cccp-setup" / "SKILL.md"

    def setUp(self):
        self.text = self.SKILL.read_text()

    def test_skill_exists_with_frontmatter(self):
        head, sep, _body = self.text.partition("\n---\n")
        self.assertTrue(head.startswith("---\n") and sep,
                        "SKILL.md must open with a --- frontmatter block")
        self.assertIn("name: cccp-setup", head)
        self.assertIn("description:", head)

    def test_pi_manifest_covers_skill_dir(self):
        pkg = json.loads((REPO / "package.json").read_text())
        dirs = [(REPO / d).resolve() for d in pkg["pi"]["skills"]]
        self.assertTrue(any(str(self.SKILL).startswith(str(d) + os.sep) for d in dirs),
                        f"pi.skills does not cover {self.SKILL}")

    def test_skill_teaches_the_essentials(self):
        for needle in ("cccp config", "cccp backend", "local-fs", "azure-blob",
                       "never read, echo", "CCCP_PLUGIN_DATA"):
            self.assertIn(needle, self.text)


class TeamSkill(unittest.TestCase):
    SKILL = REPO / ".pi" / "skills" / "cccp-team" / "SKILL.md"

    def setUp(self):
        self.text = self.SKILL.read_text()

    def test_skill_exists_with_frontmatter(self):
        head, sep, _body = self.text.partition("\n---\n")
        self.assertTrue(head.startswith("---\n") and sep)
        self.assertIn("name: cccp-team", head)
        self.assertIn("description:", head)

    def test_doctrine_headings_stay_in_sync(self):
        # Self-contained by design: a skill must NOT initialize an agent by
        # sending it into repo source files, so the Pi team skill carries an
        # adapted copy of the Claude team doctrine. This guard forces a manual
        # re-sync whenever the canonical doctrine restructures.
        doctrine = (REPO / "skills" / "team" / "body.template.md").read_text()
        for heading in re.findall(r"^## .+$", doctrine, re.MULTILINE):
            self.assertIn(heading, self.text,
                          f"doctrine heading {heading!r} missing from the Pi "
                          f"team skill - re-sync the adapted copy")
        self.assertIn("../cccp-chat/SKILL.md", self.text)


class EnvSurface(unittest.TestCase):
    """The extension invents NO env vars: cell is a tool parameter, the binary
    self-locates, the log path is fixed. Only pre-existing cccp surface
    (CCCP_COMRADE_ID, CCCP_PLUGIN_DATA) may appear, resolved at session start
    so identity and `cccp config` work before any join."""

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
            '  const res = m.resolveEnvironment("abcdef99-1111-2222-3333-444444444444");'
            '  console.log(JSON.stringify({bin, problem: res.problem, created: res.created,'
            '    id: process.env.CCCP_COMRADE_ID,'
            '    pathHead: process.env.PATH.split(":")[0]}));'
            '}, e => { console.error(e.message); process.exit(1); });'
        )
        with tempfile.TemporaryDirectory() as td:
            env = {k: v for k, v in os.environ.items() if k != "CCCP_COMRADE_ID"}
            env["CCCP_PLUGIN_DATA"] = td
            # Run from a PATH that does NOT already contain the repo's bin dir:
            # inside a Pi comrade session it does (the extension prepended it),
            # which would make the prepend assertion below vacuously pass or
            # fail depending on who ran the suite.
            binstr = str(REPO / "bin")
            env["PATH"] = os.pathsep.join(
                p for p in env.get("PATH", "").split(os.pathsep)
                if p and os.path.abspath(p) != binstr)
            r = subprocess.run(["node", "--no-warnings", "-e", script], cwd=REPO,
                               env=env, capture_output=True, text=True, timeout=60)
        if r.returncode != 0 and "Unknown file extension" in r.stderr + r.stdout:
            self.skipTest("SKIPPED LOUDLY: this node cannot import TypeScript "
                          "natively (needs Node >= 23) - resolver test not run")
        self.assertEqual(r.returncode, 0, f"node failed:\n{r.stderr}")
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["bin"], str(REPO / "bin" / "cccp"))
        self.assertIsNone(out["problem"])
        self.assertIsNone(out["created"])
        self.assertRegex(out["id"], r"^[^@\s]+@[^:\s]+:pi-444444$")
        self.assertEqual(out["pathHead"], str(REPO / "bin"))

    def test_data_dir_auto_creation_on_claude_less_machine(self):
        """No CCCP_PLUGIN_DATA, no Claude plugin data dir => resolveEnvironment
        creates ~/.pi/cccp (HOME-scoped), exports it, and reports the creation
        exactly once — the signal for the one-time first-run INFO message."""
        script = (
            'import("./integrations/pi/cccp-comrade.ts").then(m => {'
            '  const first = m.resolveEnvironment("abcdef99-1111-2222-3333-444444444444");'
            '  const second = m.resolveEnvironment("abcdef99-1111-2222-3333-444444444444");'
            '  console.log(JSON.stringify({first, second, data: process.env.CCCP_PLUGIN_DATA}));'
            '}, e => { console.error(e.message); process.exit(1); });'
        )
        with tempfile.TemporaryDirectory() as td:
            env = {k: v for k, v in os.environ.items()
                   if k not in ("CCCP_COMRADE_ID", "CCCP_PLUGIN_DATA", "CLAUDE_CONFIG_DIR")}
            env["HOME"] = td
            r = subprocess.run(["node", "--no-warnings", "-e", script], cwd=REPO,
                               env=env, capture_output=True, text=True, timeout=60)
            if r.returncode != 0 and "Unknown file extension" in r.stderr + r.stdout:
                self.skipTest("SKIPPED LOUDLY: this node cannot import TypeScript "
                              "natively (needs Node >= 23) - creation test not run")
            self.assertEqual(r.returncode, 0, f"node failed:\n{r.stderr}")
            out = json.loads(r.stdout.strip().splitlines()[-1])
            expected = os.path.join(td, ".pi", "cccp")
            self.assertEqual(out["first"], {"created": expected, "problem": None})
            self.assertEqual(out["second"], {"created": None, "problem": None},
                             "second resolution must not re-report creation")
            self.assertEqual(out["data"], expected)
            self.assertTrue(os.path.isdir(expected), f"not created: {expected}")

    def test_existing_claude_data_dir_is_preferred(self):
        """When the Claude plugin's data dir exists, Pi shares it (same-machine
        Claude and Pi comrades must reach the same local-fs cells) and creates
        nothing under ~/.pi."""
        script = (
            'import("./integrations/pi/cccp-comrade.ts").then(m => {'
            '  const res = m.resolveEnvironment(undefined);'
            '  console.log(JSON.stringify({res, data: process.env.CCCP_PLUGIN_DATA}));'
            '}, e => { console.error(e.message); process.exit(1); });'
        )
        with tempfile.TemporaryDirectory() as td:
            claude = Path(td) / "cfg" / "plugins" / "data" / "cccp-CCCP"
            claude.mkdir(parents=True)
            env = {k: v for k, v in os.environ.items()
                   if k not in ("CCCP_COMRADE_ID", "CCCP_PLUGIN_DATA")}
            env["HOME"] = td
            env["CLAUDE_CONFIG_DIR"] = str(Path(td) / "cfg")
            r = subprocess.run(["node", "--no-warnings", "-e", script], cwd=REPO,
                               env=env, capture_output=True, text=True, timeout=60)
            if r.returncode != 0 and "Unknown file extension" in r.stderr + r.stdout:
                self.skipTest("SKIPPED LOUDLY: this node cannot import TypeScript "
                              "natively (needs Node >= 23) - preference test not run")
            self.assertEqual(r.returncode, 0, f"node failed:\n{r.stderr}")
            out = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual(out["res"], {"created": None, "problem": None})
            self.assertEqual(out["data"], str(claude))
            self.assertFalse((Path(td) / ".pi" / "cccp").exists(),
                             "must not create ~/.pi/cccp when the Claude dir exists")


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


# --------------------------------------------------------------------------
# Live half - a real Pi session joins a real cell. Opt-in, credentialed, slow.
# --------------------------------------------------------------------------


def _live_skip_reason():
    """Why the live half cannot run, or None. Never returns None optimistically:
    a live test that quietly turns green without ever reaching a model would be
    worse than no test at all."""
    if os.environ.get("CCCP_LIVE_PI") != "1":
        return ("CCCP_LIVE_PI is not 1 - the live half spends model credits and "
                "~1 minute of wall clock, so it is opt-in. Run with "
                "CCCP_LIVE_PI=1 to exercise a real Pi comrade.")
    if shutil.which("pi") is None:
        return ("pi binary not on PATH - `npm install -g "
                "@earendil-works/pi-coding-agent` to enable the live half")
    # Pi authenticates from an API key in env OR from its own auth store; the
    # issue text named ANTHROPIC_API_KEY alone, which is not how a subscription
    # install actually authenticates.
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("PI_API_KEY")
            or (Path.home() / ".pi" / "agent" / "auth.json").exists()):
        return ("no Pi credentials found (ANTHROPIC_API_KEY / PI_API_KEY / "
                "~/.pi/agent/auth.json) - the live half cannot reach a model")
    return None


class _Observer:
    """A plain `cccp watchtower` on the scratch cell, standing in for a peer
    comrade: everything the Pi comrade does must be visible HERE, in the wire
    format, not merely inside Pi's own transcript."""

    def __init__(self, slug, env):
        self.lines = []
        self._q = queue.Queue()
        self.proc = subprocess.Popen(
            [str(CCCP), "watchtower", slug], env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self._q.put(line.rstrip("\n"))

    def await_line(self, predicate, timeout, what):
        """Block until a watchtower line satisfies predicate; return it."""
        deadline = time.monotonic() + timeout
        while True:
            for line in self.lines:
                if predicate(line):
                    return line
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(
                    f"timed out after {timeout}s waiting for {what}.\n"
                    f"Observer saw:\n" + ("\n".join(self.lines) or "  (nothing)"))
            try:
                self.lines.append(self._q.get(timeout=min(remaining, 1.0)))
            except queue.Empty:
                pass

    def drain(self):
        while True:
            try:
                self.lines.append(self._q.get_nowait())
            except queue.Empty:
                return list(self.lines)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        for pipe in (self.proc.stdout, self.proc.stderr):
            if pipe:
                pipe.close()


class _LiveHarness:
    """Scratch cell + peer observer watchtower + a Pi session over RPC.
    Mixed into the TestCases below; not collected on its own."""

    JOIN_TIMEOUT = 120
    REPLY_TIMEOUT = 120

    def setUp(self):
        reason = _live_skip_reason()
        if reason:
            self.skipTest("SKIPPED LOUDLY: " + reason)
        self.slug = f"pitest-{uuid.uuid4().hex[:8]}"
        self._td = tempfile.TemporaryDirectory()
        data = Path(self._td.name)
        # Scratch data dir + explicit local-fs backend: the live test must never
        # touch the developer's real cells or a shared remote backend.
        self.env = dict(os.environ)
        self.env.update(
            CCCP_PLUGIN_DATA=str(data),
            CCCP_ACTIVE_BACKEND="local-fs",
            CCCP_LOCAL_FS_ROOT=str(data / "backend" / "local-fs"),
            CCCP_ALIAS_TRIGGER=ALIAS_TRIGGER,
            # Strip the repo's bin dir from PATH: with the extension the join
            # puts it back (that is the extension's job), and without it the
            # control below is only honest if the session truly has no route to
            # the cell - no cccp tool AND no cccp binary.
            PATH=os.pathsep.join(
                p for p in os.environ.get("PATH", "").split(os.pathsep)
                if p and os.path.abspath(p) != str(REPO / "bin")),
        )
        self.observer_id = "observer@pitest:obs001"
        obs_env = dict(self.env, CCCP_COMRADE_ID=self.observer_id)
        self.observer = _Observer(self.slug, obs_env)
        self.observer.await_line(lambda l: l.startswith("ready "), 30,
                                 "the observer watchtower's own ready event")
        self.pi = None
        self.addCleanup(self._teardown)

    def _teardown(self):
        if self.pi:
            if self.pi.poll() is None:
                self.pi.kill()
                self.pi.wait(timeout=15)
            for pipe in (self.pi.stdin, self.pi.stdout, self.pi.stderr):
                if pipe and not pipe.closed:
                    pipe.close()
        self.observer.stop()
        self._sweep_scratch_processes()
        subprocess.run([str(CCCP), "rm", self.slug, "--yes"], env=self.env,
                       capture_output=True, text=True)
        self._td.cleanup()

    def _sweep_scratch_processes(self):
        """Kill anything still mentioning this run's slug. The model under test
        holds a real bash tool and WILL improvise: an early draft of this test
        (cwd=repo) had it nohup its own `./bin/cccp watchtower <slug>`, which
        then outlived the Pi session as an orphan polling a deleted cell. The
        neutral cwd and scrubbed PATH make that route impossible now; this sweep
        is the belt to that suspenders, because a leaked watchtower is exactly
        the #12 nuisance these tests exist to prevent."""
        r = subprocess.run(["pgrep", "-f", self.slug],
                           capture_output=True, text=True)
        for pid in (int(p) for p in r.stdout.split()):
            if pid == os.getpid():
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    # -- Pi RPC plumbing ---------------------------------------------------

    def _launch_pi(self, with_extension=True):
        """Start `pi --mode rpc`, with or without the cccp extension. RPC mode
        is strict JSONL over stdin/stdout: commands in, events out."""
        argv = ["pi", "--mode", "rpc", "--no-session", "--no-extensions",
                "--no-skills", "--no-prompt-templates", "--no-context-files"]
        if with_extension:
            argv += ["--extension", str(EXTENSION),
                     "--tools", "bash,cccp_join,cccp_dispatch"]
        else:
            argv += ["--tools", "bash"]
        # Neutral cwd, never the repo: from a checkout the model could reach the
        # cell by shelling out to ./bin/cccp, which would make the control below
        # meaningless (measured: it does exactly that). It also proves the
        # extension self-locates its binary rather than relying on cwd.
        self.pi = subprocess.Popen(
            argv, cwd=self._td.name,
            env=dict(self.env, CCCP_COMRADE_ID=self.pi_id),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1)
        self._events = queue.Queue()
        threading.Thread(target=self._pump_pi, daemon=True).start()
        return self.pi

    def _pump_pi(self):
        for line in self.pi.stdout:
            line = line.strip("\r\n")
            if not line:
                continue
            try:
                self._events.put(json.loads(line))
            except json.JSONDecodeError:
                pass

    def _prompt(self, message):
        self.pi.stdin.write(json.dumps(
            {"type": "prompt", "message": message,
             "streamingBehavior": "followUp"}) + "\n")
        self.pi.stdin.flush()

    @property
    def pi_id(self):
        return "pi@pitest:pilive"

    def _from_pi(self, line):
        """A message event sent by the Pi comrade. An armed watchtower renders
        `from=` as the learned ALIAS once the introduction registers, so both
        spellings count."""
        return line.startswith("message ") and (
            f"from={self.pi_id}" in line or "from=PiTester" in line)

    def _watchtower_children(self):
        """pids of watchtower processes parented by the Pi session."""
        if self.pi is None or self.pi.poll() is not None:
            return []
        r = subprocess.run(["pgrep", "-P", str(self.pi.pid)],
                           capture_output=True, text=True)
        pids = [int(p) for p in r.stdout.split()]
        out = []
        for pid in pids:
            try:
                cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(
                    errors="replace").replace("\0", " ")
            except OSError:
                continue
            if "watchtower" in cmdline and self.slug in cmdline:
                out.append(pid)
        return out

    @staticmethod
    def _alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def joining_instructions(self):
        """The one prompt both the live test and its control send, verbatim: a
        control is only a control if the ONLY difference is --extension."""
        return (
            f"You are a CCCP comrade under test. Do exactly this, using tools, "
            f"with no questions asked:\n"
            f"1. Call the cccp_join tool with cell '{self.slug}'.\n"
            f"2. Then call cccp_dispatch with cell '{self.slug}', NO 'to' "
            f"parameter (a broadcast), and message starting exactly "
            f"'{ALIAS_TRIGGER} PiTester' followed by one short sentence.\n"
            f"3. Then stop and wait. When a cell event arrives asking you "
            f"something, answer it with cccp_dispatch targeted to the sender "
            f"(the 'to' parameter set to the sender's comrade id).")


class LivePiComrade(_LiveHarness, unittest.TestCase):
    """Definition of done #3: a Pi comrade launched with the extension appears
    in the cell (intro + alias contract), receives targeted dispatches as turns,
    replies via cccp_dispatch, and its watchtower dies with the session.

    Asserted from the OUTSIDE, through a peer watchtower, because that is the
    only surface other comrades actually see.
    """

    def test_join_intro_targeted_round_trip_and_no_orphan(self):
        nonce = uuid.uuid4().hex[:10]
        self._launch_pi(with_extension=True)
        self._prompt(self.joining_instructions())

        # 1) The alias contract: the peer's armed watchtower learns the Pi
        #    comrade's name with zero special handling.
        alias = self.observer.await_line(
            lambda l: l.startswith("alias ") and "kind=new" in l
            and self.pi_id in l, self.JOIN_TIMEOUT,
            "an `alias ... kind=new` event naming the Pi comrade")
        self.assertIn("name=PiTester", alias)

        # 2) The introduction itself, on the wire, as a message event.
        intro = self.observer.await_line(
            lambda l: self._from_pi(l) and ALIAS_TRIGGER in l,
            self.JOIN_TIMEOUT, "the Pi comrade's broadcast introduction")
        self.assertIn('body="' + ALIAS_TRIGGER, intro)
        self.assertIn("to=*", intro, f"introduction was not a broadcast: {intro}")

        # 3) The watchtower child exists and belongs to the Pi session.
        towers = self._watchtower_children()
        self.assertEqual(len(towers), 1,
                         f"expected exactly one watchtower child of the Pi "
                         f"session, found {towers}")
        tower_pid = towers[0]

        # 4) Targeted in, targeted out, with a machine-checkable payload that
        #    only a real bash tool call can produce.
        r = subprocess.run(
            [str(CCCP), "dispatch", self.slug, "--to", self.pi_id, "-"],
            input=f"Run this in bash and reply to me with its output verbatim, "
                  f"nothing else: echo cccp-proof-{nonce}",
            env=dict(self.env, CCCP_COMRADE_ID=self.observer_id),
            capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, f"dispatch failed: {r.stderr}")

        reply = self.observer.await_line(
            lambda l: self._from_pi(l) and f"cccp-proof-{nonce}" in l,
            self.REPLY_TIMEOUT,
            "a targeted reply from the Pi comrade carrying the proof nonce")
        # Targeted, not broadcast. The observer's own id renders as `to=you`.
        self.assertNotIn("to=*", reply,
                         f"reply was broadcast, not targeted: {reply}")
        self.assertTrue("to=you" in reply or self.observer_id in reply,
                        f"reply was not addressed to the sender: {reply}")

        # 5) The #12 orphan rule: the watchtower dies with the session.
        self.pi.stdin.close()
        self.pi.send_signal(signal.SIGTERM)
        try:
            self.pi.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.pi.kill()
            self.pi.wait(timeout=15)
        for _ in range(100):  # 10s grace for the child to reap
            if not self._alive(tower_pid):
                break
            time.sleep(0.1)
        self.assertFalse(self._alive(tower_pid),
                         f"orphaned watchtower {tower_pid} survived the Pi "
                         f"session (issue #12)")


class LiveControl(_LiveHarness, unittest.TestCase):
    """The RED half made permanent: without the extension a Pi session cannot
    reach the cell at all, so the assertions above are testing the extension
    and not some ambient effect."""

    SILENCE = 60

    def test_without_extension_the_session_never_reaches_the_cell(self):
        self._launch_pi(with_extension=False)
        self._prompt(self.joining_instructions())
        self.assertNotIn(str(REPO / "bin"), self.env["PATH"])
        try:
            leaked = self.observer.await_line(
                lambda l: l.startswith(("message ", "alias ")), self.SILENCE,
                "any cell event at all (there must be none)")
        except AssertionError:
            return  # the silence we want
        self.fail("a Pi session WITHOUT the extension reached the cell, so the "
                  f"live assertions prove nothing. Leaked event: {leaked}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

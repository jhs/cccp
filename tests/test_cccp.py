#!/usr/bin/env python3
"""Unit tests for cccp's preview/continuation split (stdlib only).

Run: python3 tests/test_cccp.py   (or: -m unittest -v)

Covers the invariants that would silently corrupt a read if they drift: the
watchtower preview and the `read` continuation must split the body at the SAME
byte, the truncated event must fit the Monitor envelope, and escapes must never
be split. cccp is an executable script (no .py), so load it by path.
"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock


def _find_cccp():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, os.pardir, "bin", "cccp")


# cccp is an extensionless executable script; load it by path via an explicit
# source loader (spec_from_file_location can't infer a loader without a suffix).
_loader = SourceFileLoader("cccp_mod", _find_cccp())
_spec = importlib.util.spec_from_loader("cccp_mod", _loader)
cccp = importlib.util.module_from_spec(_spec)
_loader.exec_module(cccp)


def msg(body, frm="alice@hostA:aaaaaa", ts="2026-06-11T17:00:00.000000Z", to=None):
    if to is None:
        to = ["alice@hostA:bbbbbb"]
    return {"type": "message", "from": frm, "ts": ts, "to": to, "body": body}


class PreviewSplit(unittest.TestCase):
    def test_split_is_byte_exact_and_escape_safe(self):
        body = 'line one with "quotes"\nline two\twith tabs\n' + "x" * 600
        budget = cccp.preview_budget("alice@hostA:aaaaaa", "2026-06-11T17:00:00Z",
                                     "alice@hostA:bbbbbb", len(body))
        inner, n = cccp.preview_split(body, budget)
        # inner is a valid JSON string-inner that decodes to exactly body[:n]
        self.assertEqual(json.loads(f'"{inner}"'), body[:n])
        # the preview never overflows the budget
        self.assertLessEqual(len(inner), budget)

    def test_short_body_renders_full_no_truncation(self):
        d = msg("just a short note")
        line = cccp.render_message_event(d)
        self.assertIn("body=", line)
        self.assertNotIn("truncated=true", line)
        self.assertLessEqual(len(line), cccp.TRUNCATE_THRESHOLD)


class TruncatedEvent(unittest.TestCase):
    def setUp(self):
        self.body = "DECISION: " + "alpha bravo charlie delta " * 60  # ~1500 chars
        self.d = msg(self.body)
        self.line = cccp.render_message_event(self.d)

    def test_truncated_line_fits_monitor_envelope(self):
        self.assertIn("truncated=true", self.line)
        self.assertLessEqual(len(self.line), cccp.TRUNCATE_THRESHOLD)

    def test_preview_fills_available_budget(self):
        preview = self.line.split('preview="', 1)[1].rsplit('"', 1)[0]
        self.assertGreater(len(preview), 150)


class HugeHeader(unittest.TestCase):
    """Edge cases when the to-list is so long the header dominates the line."""

    def test_truncated_line_fits_with_large_to(self):
        """Many recipients still produce a line within the threshold."""
        body = "important " * 80
        to_list = [f"comrade{i}@host{i}:{'a' * 6}" for i in range(12)]
        d = msg(body, to=to_list)
        line = cccp.render_message_event(d)
        self.assertLessEqual(len(line), cccp.TRUNCATE_THRESHOLD)

    def test_short_body_huge_header_prefers_full_form(self):
        """When truncation syntax costs more bytes than the full body, use full."""
        body = "hi"
        to_list = [f"comrade{i}@host{i}:{'a' * 6}" for i in range(14)]
        d = msg(body, to=to_list)
        line = cccp.render_message_event(d)
        self.assertIn("body=", line)
        self.assertNotIn("truncated=true", line)
        self.assertLessEqual(len(line), cccp.TRUNCATE_THRESHOLD)


class Overflow(unittest.TestCase):
    """When even the header exceeds the threshold, the overflow form kicks in."""

    def _overflow_msg(self, n_recipients=30, body="hello world"):
        to_list = [f"comrade{i}@host{i}:{'a' * 6}" for i in range(n_recipients)]
        return msg(body, to=to_list)

    def test_overflow_always_fits_threshold(self):
        d = self._overflow_msg(n_recipients=50, body="x" * 1000)
        line = cccp.render_message_event(d)
        self.assertLessEqual(len(line), cccp.TRUNCATE_THRESHOLD)

    def test_overflow_has_marker(self):
        d = self._overflow_msg()
        line = cccp.render_message_event(d)
        self.assertIn("overflow=true", line)

    def test_overflow_has_recipient_count(self):
        d = self._overflow_msg(n_recipients=30)
        line = cccp.render_message_event(d)
        self.assertIn("recipients=30", line)

    def test_overflow_preserves_from_and_ts(self):
        d = self._overflow_msg()
        line = cccp.render_message_event(d)
        self.assertIn(f"from={d['from']}", line)
        self.assertIn(f"ts={d['ts']}", line)

    def test_overflow_has_chars(self):
        d = self._overflow_msg(body="x" * 200)
        line = cccp.render_message_event(d)
        self.assertIn("chars=200", line)

    def test_overflow_read_returns_full_body(self):
        """message_read_output on an overflow message returns the full body."""
        d = self._overflow_msg(body="the full text here")
        out = cccp.message_read_output(d, full=False)
        self.assertEqual(out, "the full text here")

    def test_guarantee_no_message_ever_exceeds_threshold(self):
        """Sweep across a range of recipient counts and body sizes. Every
        rendered message line must fit within TRUNCATE_THRESHOLD."""
        for n_recip in (1, 5, 10, 20, 50, 100):
            for body_len in (0, 2, 100, 500, 2000):
                to_list = [f"c{i}@h{i}:{'a'*6}" for i in range(n_recip)]
                d = msg("x" * body_len, to=to_list)
                line = cccp.render_message_event(d)
                self.assertLessEqual(
                    len(line), cccp.TRUNCATE_THRESHOLD,
                    f"recipients={n_recip} body={body_len} len={len(line)}")

    def test_guarantee_no_filesystem_event_ever_exceeds_threshold(self):
        """Sweep across recipient counts and path lengths. Every rendered
        filesystem line must fit within TRUNCATE_THRESHOLD."""
        for n_recip in (1, 10, 50):
            for path_len in (20, 200, 600):
                to_list = [f"c{i}@h{i}:{'a'*6}" for i in range(n_recip)]
                d = {"type": "filesystem", "from": "alice@boxA:abc123",
                     "op": "publish", "path": "x" * path_len,
                     "size": 1234, "to": to_list}
                line = cccp.render_filesystem_event(d)
                self.assertLessEqual(
                    len(line), cccp.TRUNCATE_THRESHOLD,
                    f"recipients={n_recip} path={path_len} len={len(line)}")


class Continuation(unittest.TestCase):
    def setUp(self):
        self.body = "RULING: " + "one two three four five six seven " * 50
        self.d = msg(self.body)

    def test_continuation_plus_preview_reconstructs_body(self):
        budget = cccp.preview_budget(self.d["from"], self.d["ts"],
                                     "alice@hostA:bbbbbb", len(self.body))
        _, n = cccp.preview_split(self.body, budget)
        out = cccp.message_read_output(self.d, full=False)
        marker, _, remainder = out.partition("\n")
        self.assertTrue(marker.startswith("[…from char"))
        self.assertEqual(remainder, self.body[n:])
        self.assertEqual(self.body[:n] + remainder, self.body)  # nothing lost/dup

    def test_full_returns_whole_body(self):
        self.assertEqual(cccp.message_read_output(self.d, full=True), self.body)

    def test_untruncated_message_has_no_marker(self):
        short = msg("short enough to arrive whole")
        out = cccp.message_read_output(short, full=False)
        self.assertEqual(out, "short enough to arrive whole")
        self.assertNotIn("…from char", out)


class ComradeId(unittest.TestCase):
    """Identity is a pure local function - no network, no cell, no claim."""

    def test_env_override_wins(self):
        with mock.patch.dict(os.environ, {"CCCP_COMRADE_ID": "custom@id:xyz"}):
            self.assertEqual(cccp.comrade_id(), "custom@id:xyz")

    def test_format_is_user_at_host_colon_six_hex(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "abcdef1234567890"}):
            os.environ.pop("CCCP_COMRADE_ID", None)   # ensure override is off
            cid = cccp.comrade_id()
        # user@host:<first-6-of-session> - always suffixed, never bare
        self.assertRegex(cid, r"^[^@]+@[^:]+:abcdef$")


class SkillRender(unittest.TestCase):
    """render_skill_body must resolve every @@token@@ and touch nothing else - its
    output is spliced verbatim into Claude's view and is NOT re-rendered, so a
    leftover token would reach the reader literally. The cell slug is deliberately
    a literal <slug> placeholder the reader fills from its args, NOT a token."""

    TEMPLATE = (
        "run: cccp watchtower <slug>\n"
        "You are `@@COMRADE_ID@@`.\n"
        "still you: `@@COMRADE_ID@@`\n"
        "shell note: `$vars` and `{\"json\": 1}` stay literal; email a@b unchanged\n"
    )

    def _render(self):
        return cccp.render_skill_body(self.TEMPLATE, {"COMRADE_ID": "alice@hostA:aaaaaa"})

    def test_all_tokens_resolved(self):
        self.assertNotIn("@@", self._render())  # no token delimiter survives

    def test_values_substituted(self):
        self.assertIn("You are `alice@hostA:aaaaaa`.", self._render())

    def test_bare_cccp_command_untouched(self):
        """`cccp` is a bare $PATH command now, not a token - it passes through
        verbatim with no path injected."""
        self.assertIn("run: cccp watchtower <slug>", self._render())

    def test_non_token_content_untouched(self):
        """Shell `$vars`, JSON braces, bare single-@ emails, and the <slug>
        placeholder must all pass through unchanged - only @@...@@ is a token."""
        out = self._render()
        self.assertIn('`$vars` and `{"json": 1}` stay literal', out)
        self.assertIn("email a@b unchanged", out)
        self.assertIn("<slug>", out)

    def test_repeated_token_all_occurrences(self):
        """@@COMRADE_ID@@ appears 2x in the template; every one is replaced."""
        self.assertEqual(self._render().count("alice@hostA:aaaaaa"), 2)

    def test_multiple_tokens_from_dict(self):
        """Every token in the subs dict is substituted (COMRADE_ID and BACKEND)."""
        out = cccp.render_skill_body(
            "id=@@COMRADE_ID@@ backend=@@BACKEND@@",
            {"COMRADE_ID": "u@h:aaa", "BACKEND": "local-fs is active"})
        self.assertEqual(out, "id=u@h:aaa backend=local-fs is active")


class SkillTemplateFile(unittest.TestCase):
    """The shipped cccp skill template must render with no leftover tokens and must
    not smuggle in a substitution Claude would choke on (it is not re-rendered)."""

    def _template(self):
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, os.pardir, "skills", "chat", "body.template.md")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_ships_and_renders_clean(self):
        rendered = cccp.render_skill_body(
            self._template(),
            {"COMRADE_ID": "bob@hostB:1a2b3c", "BACKEND": "backend info"})
        self.assertNotIn("@@", rendered)                     # no unresolved token
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", rendered)  # no path token in body
        self.assertNotIn("$ARGUMENTS", rendered)             # args come from SKILL.md
        self.assertIn("bob@hostB:1a2b3c", rendered)
        self.assertIn("backend info", rendered)              # @@BACKEND@@ substituted
        self.assertIn("cccp watchtower <slug>", rendered)    # bare command, no path
        self.assertIn("<slug>", rendered)                    # slug stays a placeholder

    def test_template_declares_backend_token(self):
        """The shipped chat template carries the @@BACKEND@@ variable that
        compose_skill fills with the live backend-status section body."""
        self.assertIn("@@BACKEND@@", self._template())


class SkillCompose(unittest.TestCase):
    """compose_skill stacks a skill's templates base-first and appends the shared
    args outro exactly once, with every token resolved."""

    def test_team_is_chat_then_team_then_outro(self):
        with mock.patch.dict(os.environ, {"CCCP_COMRADE_ID": "x@y:zzzzzz"}):
            out = cccp.compose_skill("team")
        self.assertNotIn("@@", out)                     # every token resolved
        i_chat = out.index("# CCCP")                    # chat base
        i_team = out.index("Team norms")                # team layer
        i_args = out.index("Your instructions")         # shared outro
        self.assertLess(i_chat, i_team)                 # base before layer
        self.assertLess(i_team, i_args)                 # outro last
        self.assertEqual(out.count("## Your instructions"), 1)  # outro exactly once

    def test_chat_is_chat_plus_outro_only(self):
        with mock.patch.dict(os.environ, {"CCCP_COMRADE_ID": "x@y:zzzzzz"}):
            out = cccp.compose_skill("chat")
        self.assertIn("# CCCP", out)
        self.assertNotIn("Team norms", out)             # no team layer for plain chat
        self.assertIn("## Your instructions", out)      # outro still appended

    def test_foreman_is_three_layer_stack(self):
        """foreman = [chat, team, foreman] - transitive composition, base-first,
        outro still exactly once."""
        with mock.patch.dict(os.environ, {"CCCP_COMRADE_ID": "x@y:zzzzzz"}):
            out = cccp.compose_skill("foreman")
        self.assertNotIn("@@", out)
        i_chat = out.index("# CCCP")
        i_team = out.index("Team norms")
        i_fore = out.index("owning the cell's coordination")
        i_args = out.index("Your instructions")
        self.assertTrue(i_chat < i_team < i_fore < i_args)   # base → L1 → L2 → outro
        self.assertEqual(out.count("## Your instructions"), 1)

    def test_unknown_skill_exits(self):
        with self.assertRaises(SystemExit):
            cccp.compose_skill("nope")

    def test_chat_renders_backend_section(self):
        """The chat base's 'CCCP Data Backend' section is present with @@BACKEND@@
        resolved to the live status (both healthy and not-ready forms name
        `cccp backend`), and the outro is still rendered as the implied last part."""
        with tempfile.TemporaryDirectory() as d, \
                _isolated_env(d, CCCP_COMRADE_ID="x@y:zzzzzz"):
            out = cccp.compose_skill("chat")
        self.assertIn("## CCCP Data Backend", out)   # header from the template
        self.assertNotIn("@@BACKEND@@", out)          # token resolved
        self.assertNotIn("@@", out)                   # nothing left unresolved
        self.assertIn("cccp backend", out)            # backend body rendered
        self.assertEqual(out.count("## Your instructions"), 1)  # outro still once


class Aliases(unittest.TestCase):
    """Pure alias logic: id/name disambiguation, parsing, learn/classify, render."""

    def test_id_vs_alias(self):
        self.assertTrue(cccp.is_comrade_id("co@fs:abc123"))
        self.assertFalse(cccp.is_comrade_id("Alice"))
        self.assertFalse(cccp.is_comrade_id("also-not-1"))

    def test_parse_alias(self):
        self.assertEqual(cccp.parse_alias("Alias: Foreman — hi", "Alias:"), "Foreman")
        self.assertEqual(cccp.parse_alias("Alias:   Bob_1 reporting", "Alias:"), "Bob_1")
        self.assertIsNone(cccp.parse_alias("just a normal message", "Alias:"))
        self.assertIsNone(cccp.parse_alias("Alias: hi", None))       # no trigger -> off
        self.assertIsNone(cccp.parse_alias("Alias: !!!", "Alias:"))  # no token after

    def test_learn_new_rename_reassign(self):
        m = {}
        self.assertIn("kind=new", cccp.learn_alias(m, "u@h:aaa", "Alice"))
        self.assertEqual(m, {"u@h:aaa": "Alice"})
        self.assertIsNone(cccp.learn_alias(m, "u@h:aaa", "Alice"))   # no-op

        # rename: same id, new name
        ev = cccp.learn_alias(m, "u@h:aaa", "Ada")
        self.assertIn("kind=rename", ev)
        self.assertIn("was=Alice", ev)
        self.assertEqual(m, {"u@h:aaa": "Ada"})

        # reassign: name taken by a new id (handoff) -> old holder drops it
        ev = cccp.learn_alias(m, "u@h:bbb", "Ada")
        self.assertIn("kind=reassign", ev)
        self.assertIn("was_id=u@h:aaa", ev)
        self.assertEqual(m, {"u@h:bbb": "Ada"})   # one name -> one id

    def test_alias_or_id(self):
        m = {"u@h:bbb": "Bob"}
        self.assertEqual(cccp.alias_or_id(m, "u@h:me", "u@h:me"), "you")
        self.assertEqual(cccp.alias_or_id(m, "u@h:me", "u@h:bbb"), "Bob")
        self.assertEqual(cccp.alias_or_id(m, "u@h:me", "u@h:ccc"), "u@h:ccc")

    def test_resolve_recipient(self):
        m = {"u@h:bbb": "Bob"}
        self.assertEqual(cccp.resolve_recipient(m, "Bob"), ("u@h:bbb", None))
        self.assertEqual(cccp.resolve_recipient(m, "u@h:ccc"), ("u@h:ccc", None))
        self.assertEqual(cccp.resolve_recipient(m, "*"), ("*", None))
        cid, err = cccp.resolve_recipient(m, "Nobody")
        self.assertIsNone(cid)
        self.assertIn("unknown alias", err)

    def test_watchtower_translates_metadata_only(self):
        wt = cccp.Watchtower(None, "p", "demo", "me@h:mmm", 0, trigger="Alias:")
        wt.aliases = {"u@h:bbb": "Bob"}
        d = {"type": "message", "from": "u@h:bbb",
             "ts": "2026-01-01T00:00:00.000000Z",
             "to": ["me@h:mmm", "u@h:ccc"], "body": "u@h:bbb in the body stays"}
        out = cccp.render_message_event(wt._aliased(d))
        self.assertIn("from=Bob", out)          # known id -> alias
        self.assertIn("you", out)               # self -> you
        self.assertIn("u@h:ccc", out)           # unknown -> raw id
        self.assertIn("u@h:bbb in the body stays", out)  # body untouched

    def test_watchtower_aliased_is_noop_when_off(self):
        wt = cccp.Watchtower(None, "p", "demo", "me@h:mmm", 0)   # no trigger
        d = {"type": "message", "from": "u@h:bbb", "to": ["*"], "body": "hi"}
        self.assertIs(wt._aliased(d), d)        # empty map -> same object, no work


class DispatchBody(unittest.TestCase):
    """`-` reads the body from stdin verbatim; anything else is the literal arg."""

    def test_dash_reads_stdin_verbatim(self):
        piped = "line1 with 'quotes'\n`backticks` and $vars\nline3\n"
        with mock.patch.object(cccp.sys, "stdin", io.StringIO(piped)):
            self.assertEqual(cccp.read_dispatch_body("-"), piped)  # nothing stripped

    def test_plain_arg_passes_through(self):
        self.assertEqual(cccp.read_dispatch_body("just 'text'"), "just 'text'")


@contextlib.contextmanager
def _isolated_env(data_dir, **cccp_vars):
    """Run with a clean CCCP_* environment: only CCCP_PLUGIN_DATA (=data_dir) plus
    explicit overrides, so resolve_config is deterministic regardless of whatever
    the developer's shell exports (e.g. a stray CCCP_DEBUG)."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("CCCP_")}
    for k in list(os.environ):
        if k.startswith("CCCP_"):
            del os.environ[k]
    os.environ["CCCP_PLUGIN_DATA"] = str(data_dir)
    os.environ.update(cccp_vars)
    try:
        yield
    finally:
        for k in list(os.environ):
            if k.startswith("CCCP_"):
                del os.environ[k]
        os.environ.update(saved)


class ConfigResolution(unittest.TestCase):
    """Two sources, self-namespacing: settings < backend/<active>/config < process
    env, with local-fs the zero-config default. No .env walk-up."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.data, True))

    def _write(self, path, text):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def test_defaults_to_local_fs_with_no_config(self):
        with _isolated_env(self.data):
            cfg = cccp.resolve_config()
        self.assertEqual(cfg["BACKEND"], "local-fs")
        self.assertEqual(cfg["PREFIX"], "")          # local-fs uses no prefix
        self.assertEqual(cfg["PARAMS"], {})

    def test_settings_selects_backend_and_reads_namespaced_params(self):
        self._write(f"{self.data}/settings", "CCCP_ACTIVE_BACKEND=azure-blob\n")
        self._write(f"{self.data}/backend/azure-blob/config",
                    "CCCP_AZURE_BLOB_ACCOUNT=acct\nCCCP_AZURE_BLOB_CONTAINER=cont\n"
                    "CCCP_AZURE_BLOB_SAS=sig123\n")
        with _isolated_env(self.data):
            cfg = cccp.resolve_config()
        self.assertEqual(cfg["BACKEND"], "azure-blob")
        self.assertEqual(cfg["PARAMS"]["account"], "acct")
        self.assertEqual(cfg["PARAMS"]["container"], "cont")
        self.assertEqual(cfg["PARAMS"]["sas"], "sig123")
        self.assertEqual(cfg["PREFIX"], "__default__")   # azure's prefix default

    def test_env_selects_backend_over_settings(self):
        self._write(f"{self.data}/settings", "CCCP_ACTIVE_BACKEND=azure-blob\n")
        with _isolated_env(self.data, CCCP_ACTIVE_BACKEND="local-fs"):
            cfg = cccp.resolve_config()
        self.assertEqual(cfg["BACKEND"], "local-fs")     # env beats settings

    def test_env_overrides_backend_config_param(self):
        self._write(f"{self.data}/settings", "CCCP_ACTIVE_BACKEND=azure-blob\n")
        self._write(f"{self.data}/backend/azure-blob/config",
                    "CCCP_AZURE_BLOB_ACCOUNT=file-acct\n"
                    "CCCP_AZURE_BLOB_CONTAINER=cont\nCCCP_AZURE_BLOB_SAS=s\n")
        with _isolated_env(self.data, CCCP_AZURE_BLOB_ACCOUNT="env-acct"):
            cfg = cccp.resolve_config()
        self.assertEqual(cfg["PARAMS"]["account"], "env-acct")  # env beats the file

    def test_unknown_backend_exits(self):
        with _isolated_env(self.data, CCCP_ACTIVE_BACKEND="bogus"):
            with self.assertRaises(SystemExit):
                cccp.resolve_config()


class BackendPaths(unittest.TestCase):
    """cell_head/comrade_path tolerate an empty prefix (local-fs) with no leading
    slash or empty segment; backend keys are self-namespacing."""

    def test_cell_head_empty_vs_prefixed(self):
        self.assertEqual(cccp.cell_head("", "demo"), "demo/")
        self.assertEqual(cccp.cell_head("__default__", "demo"), "__default__/demo/")

    def test_comrade_and_gazette_paths(self):
        self.assertEqual(cccp.comrade_path("", "demo", "u@h:aaa", "files/x"),
                         "demo/u@h:aaa/files/x")
        self.assertEqual(cccp.gazette_path("__default__", "demo", "u@h:aaa"),
                         "__default__/demo/u@h:aaa/gazette.jsonl")

    def test_backend_key_namespacing(self):
        self.assertEqual(cccp._backend_key("azure-blob", "SAS"), "CCCP_AZURE_BLOB_SAS")
        self.assertEqual(cccp._backend_key("local-fs", "PREFIX"), "CCCP_LOCAL_FS_PREFIX")


class MakeBackend(unittest.TestCase):
    def test_local_fs_builds(self):
        with tempfile.TemporaryDirectory() as d, _isolated_env(d):
            b = cccp.make_backend({"BACKEND": "local-fs", "PARAMS": {}})
        self.assertIsInstance(b, cccp.LocalFilesBackend)

    def test_azure_missing_params_exits_no_downgrade(self):
        with self.assertRaises(SystemExit):
            cccp.make_backend({"BACKEND": "azure-blob", "PARAMS": {}})


class PluginDataDir(unittest.TestCase):
    """$CCCP_PLUGIN_DATA has no default and must never grow one. backend/local-fs/ IS
    the authoritative cell store, so a guessed root silently sends messages to a
    store nobody reads - failure wearing success's face. The name also encodes the
    marketplace the plugin came from, so there is nothing correct to guess."""

    @contextlib.contextmanager
    def _no_plugin_data(self, **extra):
        saved = {k: v for k, v in os.environ.items()
                 if k.startswith("CCCP_") or k == "XDG_STATE_HOME"}
        for k in list(os.environ):
            if k.startswith("CCCP_") or k == "XDG_STATE_HOME":
                del os.environ[k]
        os.environ.update(extra)
        try:
            yield
        finally:
            for k in list(os.environ):
                if k.startswith("CCCP_") or k == "XDG_STATE_HOME":
                    del os.environ[k]
            os.environ.update(saved)

    def test_unset_exits_rather_than_guessing(self):
        with self._no_plugin_data():
            with self.assertRaises(SystemExit) as cm:
                cccp.plugin_data_dir()
        self.assertIn("CCCP_PLUGIN_DATA", str(cm.exception))

    def test_never_falls_back_to_xdg_or_home(self):
        # The old behaviour invented $XDG_STATE_HOME/cccp (or ~/.local/state/cccp).
        # Neither may ever come back: both are roots the plugin does not read.
        with self._no_plugin_data(XDG_STATE_HOME="/tmp/should-never-be-used"):
            with self.assertRaises(SystemExit) as cm:
                cccp.plugin_data_dir()
        msg = str(cm.exception)
        self.assertNotIn("should-never-be-used", msg)
        self.assertNotIn(".local/state", msg)

    def test_error_carries_the_fix(self):
        with self._no_plugin_data():
            with self.assertRaises(SystemExit) as cm:
                cccp.plugin_data_dir()
        msg = str(cm.exception)
        self.assertIn("export CCCP_PLUGIN_DATA", msg)   # how to fix it by hand
        self.assertIn("SessionStart", msg)              # why it is normally set

    def test_skill_header_surfaces_the_error_to_claude(self):
        # @@BACKEND@@ is the only place a chat session would ever see this, so the
        # actionable text must survive into the skill body rather than flatten to a
        # generic line. Rendering must still not raise.
        with self._no_plugin_data():
            block = cccp.backend_status_block()
        self.assertIn("NOT READY", block)
        self.assertIn("CCCP_PLUGIN_DATA", block)

    def test_set_is_used_verbatim(self):
        with self._no_plugin_data(CCCP_PLUGIN_DATA="/tmp/explicit-root"):
            self.assertEqual(cccp.plugin_data_dir(), Path("/tmp/explicit-root"))


class ConfigProvenance(unittest.TestCase):
    """SOURCES records every layer that set a key, low -> high, so `cccp backend` can
    name the winner and flag a shadowed one. It must stay in lockstep with the merge
    that produces the values - the two are built from one ordered layer list."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.data, True))

    def _write(self, path, text):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def _azure(self, account="file-acct"):
        self._write(f"{self.data}/settings", "CCCP_ACTIVE_BACKEND=azure-blob\n")
        self._write(f"{self.data}/backend/azure-blob/config",
                    f"CCCP_AZURE_BLOB_ACCOUNT={account}\n"
                    "CCCP_AZURE_BLOB_CONTAINER=cont\nCCCP_AZURE_BLOB_SAS=s\n")

    def test_single_layer_reports_that_layer(self):
        self._azure()
        with _isolated_env(self.data):
            cfg = cccp.resolve_config()
        self.assertEqual(cfg["SOURCES"]["CCCP_AZURE_BLOB_ACCOUNT"], ["config"])

    def test_env_shadowing_records_both_layers_in_order(self):
        self._azure()
        with _isolated_env(self.data, CCCP_AZURE_BLOB_ACCOUNT="env-acct"):
            cfg = cccp.resolve_config()
        # Winner last, shadowed first - and the winner agrees with the merged value.
        self.assertEqual(cfg["SOURCES"]["CCCP_AZURE_BLOB_ACCOUNT"], ["config", "env"])
        self.assertEqual(cfg["PARAMS"]["account"], "env-acct")

    def test_unset_key_has_no_source(self):
        with _isolated_env(self.data):
            cfg = cccp.resolve_config()
        self.assertNotIn("CCCP_AZURE_BLOB_ACCOUNT", cfg["SOURCES"])


class BackendConfigWrite(unittest.TestCase):
    """_write_kv is the one writer behind both `settings` and backend/<name>/config:
    it preserves unrelated lines and comments, removes on None, and keeps the file
    owner-only because an azure config holds a SAS."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "backend" / "azure-blob" / "config"

    def test_creates_parents_and_writes(self):
        cccp._write_kv(self.path, "CCCP_AZURE_BLOB_ACCOUNT", "acct")
        self.assertEqual(cccp._read_kv_file(self.path),
                         {"CCCP_AZURE_BLOB_ACCOUNT": "acct"})

    def test_file_is_owner_only(self):
        cccp._write_kv(self.path, "CCCP_AZURE_BLOB_SAS", "sig")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_replace_preserves_comments_and_other_keys(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("# hand-written\nCCCP_AZURE_BLOB_ACCOUNT=old\n"
                             "CCCP_AZURE_BLOB_CONTAINER=cont\n")
        cccp._write_kv(self.path, "CCCP_AZURE_BLOB_ACCOUNT", "new")
        text = self.path.read_text()
        self.assertIn("# hand-written", text)
        self.assertIn("CCCP_AZURE_BLOB_CONTAINER=cont", text)
        self.assertEqual(cccp._read_kv_file(self.path)["CCCP_AZURE_BLOB_ACCOUNT"],
                         "new")
        self.assertNotIn("old", text)

    def test_none_removes_only_that_key(self):
        cccp._write_kv(self.path, "CCCP_AZURE_BLOB_ACCOUNT", "acct")
        cccp._write_kv(self.path, "CCCP_AZURE_BLOB_CONTAINER", "cont")
        cccp._write_kv(self.path, "CCCP_AZURE_BLOB_ACCOUNT", None)
        self.assertEqual(cccp._read_kv_file(self.path),
                         {"CCCP_AZURE_BLOB_CONTAINER": "cont"})


class BackendConfigKeys(unittest.TestCase):
    """`cccp backend config` accepts either spelling of a key and refuses unknown
    ones - a typo'd key is invisible until the backend mysteriously fails to
    validate. local-fs is isolated by its own root dir, so it has no keys at all."""

    def test_bare_and_qualified_spellings_agree(self):
        self.assertEqual(cccp._config_key("azure-blob", "SAS"), "CCCP_AZURE_BLOB_SAS")
        self.assertEqual(cccp._config_key("azure-blob", "CCCP_AZURE_BLOB_SAS"),
                         "CCCP_AZURE_BLOB_SAS")
        self.assertEqual(cccp._config_key("azure-blob", "sas"), "CCCP_AZURE_BLOB_SAS")

    def test_unknown_key_exits(self):
        with self.assertRaises(SystemExit):
            cccp._config_key("azure-blob", "ACCONT")

    def test_local_fs_has_nothing_to_configure(self):
        self.assertEqual(cccp._config_keys("local-fs"), ())
        self.assertEqual(cccp._config_keys("azure-blob"),
                         ("ACCOUNT", "CONTAINER", "SAS", "PREFIX"))


class SecretRedaction(unittest.TestCase):
    """A secret param is never printed - only whether it is set and how long - so
    `cccp backend` output is safe to paste into an issue or leave in a transcript."""

    def test_sas_value_never_rendered(self):
        out = cccp._fmt_param("azure-blob", "SAS", "sig-abcdef123456")
        self.assertNotIn("sig-abcdef", out)
        self.assertEqual(out, "<set, 16 chars>")

    def test_non_secret_shown_verbatim(self):
        self.assertEqual(cccp._fmt_param("azure-blob", "ACCOUNT", "hub"), "hub")

    def test_missing_marked_not_redacted(self):
        self.assertEqual(cccp._fmt_param("azure-blob", "SAS", None), "<missing>")

    def test_every_declared_secret_is_a_real_param(self):
        # A typo in `secrets` would silently un-redact the key it meant to protect.
        for name, spec in cccp.BACKENDS.items():
            for key in spec.get("secrets", ()):
                self.assertIn(key, spec["params"], f"{name}: {key} is not a param")


class AsActiveBackend(unittest.TestCase):
    """`check` and `use` both resolve a backend they have not switched to by
    overriding the env selector - the highest-precedence layer. It must restore the
    previous value, or one check leaks into the next resolution."""

    def test_restores_previous_selector(self):
        with tempfile.TemporaryDirectory() as d, _isolated_env(d,
                                                CCCP_ACTIVE_BACKEND="local-fs"):
            with cccp._as_active("azure-blob") as cfg:
                self.assertEqual(cfg["BACKEND"], "azure-blob")
            self.assertEqual(os.environ["CCCP_ACTIVE_BACKEND"], "local-fs")
            self.assertEqual(cccp.resolve_config()["BACKEND"], "local-fs")

    def test_unsets_when_there_was_no_selector(self):
        with tempfile.TemporaryDirectory() as d, _isolated_env(d):
            with cccp._as_active("azure-blob"):
                pass
            self.assertNotIn("CCCP_ACTIVE_BACKEND", os.environ)


class SetupSkillFile(unittest.TestCase):
    """The setup skill is deliberately standalone: it must NOT join the chat family's
    stack, or it would drag in cells, comrades and the watchtower - the exact
    opposite of a skill whose only job is the backend."""

    def _skill(self):
        here = os.path.dirname(os.path.abspath(__file__))
        return Path(here, os.pardir, "skills", "setup", "SKILL.md")

    def test_ships(self):
        self.assertTrue(self._skill().is_file())

    def test_not_in_the_chat_stack(self):
        self.assertNotIn("setup", cccp.SKILL_STACK)

    def test_is_static_no_render_time_include(self):
        # It must not call `cccp skill setup` (there is no such renderer), and it
        # must not `!`-include the network healthcheck - a 30s urlopen timeout would
        # block skill render. It tells Claude to run `cccp backend` instead.
        text = self._skill().read_text()
        self.assertNotIn("cccp skill setup", text)
        self.assertNotIn("!`", text)
        self.assertIn("cccp backend", text)
        self.assertIn("$ARGUMENTS", text)


class LocalFilesRoundTrip(unittest.TestCase):
    """LocalFilesBackend returns Azure-shaped status codes so every caller branches
    identically. Exercises the whole verb set on one gazette."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.b = cccp.LocalFilesBackend(self._tmp.name)

    def test_full_verb_set(self):
        p = "demo/u@h:aaa/gazette.jsonl"
        self.assertEqual(self.b.ensure_append_blob(p), 201)
        self.assertEqual(self.b.ensure_append_blob(p), 409)      # exists now
        self.assertEqual(self.b.append_block(p, b"line1\n"), 201)
        self.assertEqual(self.b.append_block(p, b"line2\n"), 201)
        self.assertEqual(self.b.get(p), (200, b"line1\nline2\n"))
        self.assertEqual(self.b.get_range(p, 6), (206, b"line2\n"))
        self.assertEqual(self.b.get_range(p, 0), (200, b"line1\nline2\n"))
        self.assertEqual(self.b.get_head(p, 5), (206, b"line1"))
        names = self.b.list("demo/")
        self.assertIn(p, names)
        self.assertEqual(names[p]["size"], 12)
        self.assertEqual(self.b.get("demo/nope")[0], 404)        # absent read
        self.assertEqual(self.b.put_block("demo/u@h:aaa/files/x", b"hi"), 201)
        self.assertEqual(self.b.delete("demo/u@h:aaa/files/x"), 202)
        self.assertEqual(self.b.delete("demo/u@h:aaa/files/x"), 404)  # already gone

    def test_list_missing_prefix_is_empty(self):
        self.assertEqual(self.b.list("nothing/"), {})

    def test_get_range_past_eof(self):
        p = "c/x/gazette.jsonl"
        self.b.append_block(p, b"abc")
        self.assertEqual(self.b.get_range(p, 10), (416, b""))


if __name__ == "__main__":
    unittest.main(verbosity=2)

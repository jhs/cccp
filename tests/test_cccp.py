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
        self.assertEqual(cccp.parse_alias("Alias: Foreman", "Alias:"), "Foreman")  # at EOL
        self.assertIsNone(cccp.parse_alias("just a normal message", "Alias:"))
        self.assertIsNone(cccp.parse_alias("Alias: hi", None))       # no trigger -> off
        self.assertIsNone(cccp.parse_alias("Alias: !!!", "Alias:"))  # no token after

    def test_parse_alias_rejects_prose_and_ids(self):
        # Prose intro: "I" is a pronoun, not a name (issue #1 garbage alias).
        self.assertIsNone(cccp.parse_alias("Alias: I am the new Foreman", "Alias:"))
        # Id-first intro: the token is a comrade-id prefix, not a name (issue #1).
        self.assertIsNone(cccp.parse_alias("Alias: omni@fs:abc123 here", "Alias:"))
        self.assertIsNone(cccp.parse_alias("Alias: co@fs:abc123 is me", "Alias:"))
        # Two chars is the floor, not collateral damage.
        self.assertEqual(cccp.parse_alias("Alias: Bo — hi", "Alias:"), "Bo")

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


class _FakeBlobClient:
    """In-memory blob store speaking the watchtower's client interface
    (list/get_range/get_head). Records every fetched path so a test can assert a
    gazette was NOT read."""

    def __init__(self):
        self.blobs = {}     # path -> bytes
        self.lm = {}        # path -> RFC 1123 last_modified (absent -> None)
        self.fetched = []   # paths passed to get_range/get_head

    def append(self, path, record):
        self.blobs[path] = self.blobs.get(path, b"") + \
            (json.dumps(record) + "\n").encode()

    def list(self, prefix):
        return {p: {"size": len(b), "last_modified": self.lm.get(p)}
                for p, b in self.blobs.items() if p.startswith(prefix)}

    def get_range(self, path, offset):
        self.fetched.append(path)
        b = self.blobs.get(path)
        return (404, b"") if b is None else (206, b[offset:])

    def get_head(self, path, nbytes):
        self.fetched.append(path)
        b = self.blobs.get(path)
        return (404, b"") if b is None else (206, b[:nbytes])


class AzureListPagination(unittest.TestCase):
    """list() must follow NextMarker: Azure caps List Blobs at 5000 results per
    page, and a truncated view silently hides comrades past the marker."""

    PAGE1 = (b'<?xml version="1.0" encoding="utf-8"?>'
             b'<EnumerationResults><Blobs>'
             b'<Blob><Name>cell/a/gazette.jsonl</Name><Properties>'
             b'<Content-Length>10</Content-Length>'
             b'<Last-Modified>Fri, 17 Jul 2026 00:00:00 GMT</Last-Modified>'
             b'</Properties></Blob>'
             b'</Blobs><NextMarker>tok1</NextMarker></EnumerationResults>')
    PAGE2 = (b'<?xml version="1.0" encoding="utf-8"?>'
             b'<EnumerationResults><Blobs>'
             b'<Blob><Name>cell/b/gazette.jsonl</Name><Properties>'
             b'<Content-Length>20</Content-Length>'
             b'<Last-Modified>Fri, 17 Jul 2026 00:00:01 GMT</Last-Modified>'
             b'</Properties></Blob>'
             b'</Blobs><NextMarker /></EnumerationResults>')

    def test_follows_next_marker(self):
        be = cccp.AzureBlobBackend("acct", "cont", "sig=x")
        pages = [self.PAGE1, self.PAGE2]
        queries = []

        def fake_request(method, path, query="", **kw):
            queries.append(query)
            return 200, {}, pages.pop(0)

        be.request = fake_request
        out = be.list("cell/")
        self.assertEqual(
            set(out), {"cell/a/gazette.jsonl", "cell/b/gazette.jsonl"})
        self.assertEqual(out["cell/b/gazette.jsonl"]["size"], 20)
        self.assertEqual(len(queries), 2)
        self.assertNotIn("marker=", queries[0])
        self.assertIn("marker=tok1", queries[1])


class SelfAliasLearning(unittest.TestCase):
    """Issue #1: an armed watchtower must learn its OWN comrade's intro - the
    declaring comrade appends to its own gazette, so skipping self entirely made
    self-aliases structurally unregistrable (and stale predecessors immortal).
    Own dispatches must still never echo back as events."""

    ME = "co@fs:d1f4b6"
    DEAD = "co@fs:5e84d0"
    OTHER = "bb@fs:b1b1b1"
    SLUG = "demo"

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.data, True))
        self.env = _isolated_env(self.data)
        self.env.__enter__()
        self.addCleanup(lambda: self.env.__exit__(None, None, None))
        self.client = _FakeBlobClient()

    def _gazette(self, comrade):
        return cccp.gazette_path("", self.SLUG, comrade)

    def _intro(self, frm, alias, ts):
        return {"type": "message", "from": frm, "ts": ts, "to": ["*"],
                "body": f"Alias: {alias} — reporting"}

    def _watchtower(self, trigger="Alias:"):
        wt = cccp.Watchtower(self.client, "", self.SLUG, self.ME, 0,
                             trigger=trigger)
        wt.emitted = []
        wt._emit = wt.emitted.append
        return wt

    def test_poll_learns_own_intro(self):
        wt = self._watchtower()
        wt.initial_scan()
        self.client.append(self._gazette(self.ME),
                           self._intro(self.ME, "Foreman",
                                       "2026-07-17T15:35:00.000000Z"))
        wt._poll_once()
        self.assertEqual(wt.aliases.get(self.ME), "Foreman")
        self.assertTrue(any(l.startswith("alias name=Foreman") for l in wt.emitted))
        # The intro itself must not echo back as a message event.
        self.assertFalse(any(l.startswith("message") for l in wt.emitted))

    def test_poll_own_intro_evicts_dead_predecessor(self):
        cccp.save_aliases(self.SLUG, self.ME, {self.DEAD: "Foreman"})
        wt = self._watchtower()
        wt.initial_scan()
        self.client.append(self._gazette(self.ME),
                           self._intro(self.ME, "Foreman",
                                       "2026-07-17T15:35:00.000000Z"))
        wt._poll_once()
        self.assertEqual(wt.aliases, {self.ME: "Foreman"})

    def test_seed_learns_own_intro(self):
        # A restarted armed watchtower re-learns its own alias from backlog
        # instead of only resurrecting the dead predecessor's.
        self.client.append(self._gazette(self.DEAD),
                           self._intro(self.DEAD, "Foreman",
                                       "2026-07-13T00:00:00.000000Z"))
        self.client.append(self._gazette(self.ME),
                           self._intro(self.ME, "Foreman",
                                       "2026-07-17T15:35:00.000000Z"))
        wt = self._watchtower()
        wt.seed_aliases()
        self.assertEqual(wt.aliases, {self.ME: "Foreman"})

    def test_seed_skips_stale_gazettes(self):
        # A gazette idle past ALIAS_SEED_MAX_AGE_SECONDS gets no head read at
        # seed time; one with no last_modified at all is still seeded.
        gaz = self._gazette(self.OTHER)
        self.client.append(gaz, self._intro(self.OTHER, "Buddy",
                                            "2026-01-01T00:00:00.000000Z"))
        self.client.lm[gaz] = "Thu, 01 Jan 2026 00:00:00 GMT"
        self.client.append(self._gazette(self.ME),
                           self._intro(self.ME, "Foreman",
                                       "2026-07-17T15:35:00.000000Z"))
        wt = self._watchtower()
        wt.seed_aliases()
        self.assertEqual(wt.aliases, {self.ME: "Foreman"})
        self.assertNotIn(gaz, self.client.fetched)

    def test_poll_skips_own_gazette_when_unarmed(self):
        wt = self._watchtower(trigger=None)
        wt.initial_scan()
        self.client.append(self._gazette(self.ME),
                           self._intro(self.ME, "Foreman",
                                       "2026-07-17T15:35:00.000000Z"))
        wt._poll_once()
        self.assertNotIn(self._gazette(self.ME), self.client.fetched)
        self.assertEqual(wt.emitted, [])

    def test_poll_still_learns_inbound_intros(self):
        wt = self._watchtower()
        wt.initial_scan()
        self.client.append(self._gazette(self.OTHER),
                           self._intro(self.OTHER, "Buddy",
                                       "2026-07-17T15:36:00.000000Z"))
        wt._poll_once()
        self.assertEqual(wt.aliases.get(self.OTHER), "Buddy")
        # Inbound broadcasts DO render as message events.
        self.assertTrue(any(l.startswith("message") for l in wt.emitted))


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
    """Two sources, self-namespacing: config < backend/<active>/config < process
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
        # ROOT is optional-with-default, so it is always resolved - never missing.
        self.assertEqual(cfg["PARAMS"],
                         {"root": str(Path(self.data, "backend", "local-fs"))})

    def test_local_fs_root_override_reaches_params(self):
        with _isolated_env(self.data, CCCP_LOCAL_FS_ROOT="/tmp/cccp-hub"):
            cfg = cccp.resolve_config()
        self.assertEqual(cfg["PARAMS"]["root"], "/tmp/cccp-hub")

    def test_config_file_selects_backend_and_reads_namespaced_params(self):
        self._write(f"{self.data}/config", "CCCP_ACTIVE_BACKEND=azure-blob\n")
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

    def test_env_selects_backend_over_config_file(self):
        self._write(f"{self.data}/config", "CCCP_ACTIVE_BACKEND=azure-blob\n")
        with _isolated_env(self.data, CCCP_ACTIVE_BACKEND="local-fs"):
            cfg = cccp.resolve_config()
        self.assertEqual(cfg["BACKEND"], "local-fs")     # env beats the file

    def test_env_overrides_backend_config_param(self):
        self._write(f"{self.data}/config", "CCCP_ACTIVE_BACKEND=azure-blob\n")
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

    def test_gazette_and_published_paths(self):
        self.assertEqual(cccp.gazette_path("__default__", "demo", "u@h:aaa"),
                         "__default__/demo/gazettes/u@h:aaa.jsonl")
        self.assertEqual(cccp.gazettes_head("", "demo"), "demo/gazettes/")
        # The wire path keeps its files/ prefix; the blob key regroups it under
        # the cell-level files/ area, outside the polled gazettes/ prefix.
        self.assertEqual(cccp.published_blob("", "demo", "u@h:aaa", "files/x"),
                         "demo/files/u@h:aaa/x")
        self.assertEqual(cccp.published_blob("p", "demo", "u@h:aaa", "files/a/b"),
                         "p/demo/files/u@h:aaa/a/b")

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
        self._write(f"{self.data}/config", "CCCP_ACTIVE_BACKEND=azure-blob\n")
        self._write(f"{self.data}/backend/azure-blob/config",
                    f"CCCP_AZURE_BLOB_ACCOUNT={account}\n"
                    "CCCP_AZURE_BLOB_CONTAINER=cont\nCCCP_AZURE_BLOB_SAS=s\n")

    def test_single_layer_reports_that_layer(self):
        self._azure()
        with _isolated_env(self.data):
            cfg = cccp.resolve_config()
        self.assertEqual(cfg["SOURCES"]["CCCP_AZURE_BLOB_ACCOUNT"],
                         ["backend/azure-blob/config"])

    def test_env_shadowing_records_both_layers_in_order(self):
        self._azure()
        with _isolated_env(self.data, CCCP_AZURE_BLOB_ACCOUNT="env-acct"):
            cfg = cccp.resolve_config()
        # Winner last, shadowed first - and the winner agrees with the merged value.
        self.assertEqual(cfg["SOURCES"]["CCCP_AZURE_BLOB_ACCOUNT"],
                         ["backend/azure-blob/config", "env"])
        self.assertEqual(cfg["PARAMS"]["account"], "env-acct")

    def test_unset_key_has_no_source(self):
        with _isolated_env(self.data):
            cfg = cccp.resolve_config()
        self.assertNotIn("CCCP_AZURE_BLOB_ACCOUNT", cfg["SOURCES"])


class BarePlumbing(unittest.TestCase):
    """`cccp backend` is plumbing: the active name on stdout and nothing else, so
    $(cccp backend) is a value a script can branch on. It must also stay off the
    network - `which backend am I on` should never wait on a container LIST."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.data, True))

    def _bare(self, **env):
        args = cccp.build_parser().parse_args(["backend"])
        with _isolated_env(self.data, **env):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cccp.cmd_backend(args)
            return buf.getvalue()

    def test_prints_only_the_name(self):
        self.assertEqual(self._bare(), "local-fs\n")

    def test_names_a_selected_backend_without_validating_it(self):
        # azure-blob with no credentials at all: still just the name. Health is
        # `check`'s job, and this must not probe (or fail) to answer the question.
        with mock.patch.object(cccp, "validate_backend",
                               side_effect=AssertionError("must not validate")):
            self.assertEqual(self._bare(CCCP_ACTIVE_BACKEND="azure-blob"),
                             "azure-blob\n")


class ConfigDump(unittest.TestCase):
    """`cccp config` is the config authority: one dump - globals, then every
    backend, [active]/[inactive] - resolving the merge rather than any one file,
    with `Set by` naming the winning layer BY ITS data-dir-relative file path so
    a reader can go straight from the dump to the file."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.data, True))

    def _dump(self, **env):
        with _isolated_env(self.data, **env):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cccp._print_config_dump()
            return buf.getvalue()

    def _header(self, **kw):
        for line in self._dump(**kw).splitlines():
            if "Config key" in line:
                return line
        self.fail("no table header printed")

    def test_columns_are_labelled(self):
        head = self._header()
        self.assertIn("Config key", head)
        self.assertIn("Set by", head)
        self.assertIn("Value", head)

    def test_value_column_is_last_so_long_paths_cannot_misalign(self):
        self.assertTrue(self._header().rstrip().endswith("Value"), self._header())

    def test_globals_lead_with_the_data_root(self):
        rows = [l for l in self._dump().splitlines() if l.startswith("  CCCP_")]
        self.assertTrue(rows[0].startswith("  CCCP_PLUGIN_DATA"), rows)
        self.assertIn(self.data, rows[0])
        self.assertIn("env", rows[0])

    def test_debug_renders_as_effective_boolean(self):
        row = [l for l in self._dump().splitlines() if "CCCP_DEBUG" in l][0]
        self.assertIn("unset", row)
        self.assertIn("off", row)
        row = [l for l in self._dump(CCCP_DEBUG="1").splitlines()
               if "CCCP_DEBUG" in l][0]
        self.assertIn("env", row)
        self.assertIn("on", row)

    def test_every_backend_appears_active_first_and_tagged(self):
        out = self._dump(CCCP_ACTIVE_BACKEND="azure-blob")
        self.assertIn("Active backend: azure-blob", out)
        self.assertIn("Inactive backend: local-fs", out)
        self.assertLess(out.index("Active backend: azure-blob"),
                        out.index("Inactive backend: local-fs"))

    def test_local_fs_root_defaults_to_its_backend_dir(self):
        row = [l for l in self._dump().splitlines()
               if "CCCP_LOCAL_FS_ROOT" in l][0]
        self.assertIn("default", row)
        self.assertIn(str(Path(self.data, "backend", "local-fs")), row)

    def test_secret_stays_redacted(self):
        out = self._dump(CCCP_AZURE_BLOB_SAS="sig-do-not-print")
        self.assertNotIn("sig-do-not-print", out)
        self.assertIn("<set, 16 chars>", out)

    def test_set_by_names_the_file_path(self):
        Path(self.data, "backend", "azure-blob").mkdir(parents=True)
        Path(self.data, "backend", "azure-blob", "config").write_text(
            "CCCP_AZURE_BLOB_CONTAINER=cont\n")
        row = [l for l in self._dump().splitlines() if "CONTAINER" in l][0]
        self.assertIn("backend/azure-blob/config", row)

    def test_resolves_the_merge_and_shows_the_shadow(self):
        Path(self.data, "backend", "azure-blob").mkdir(parents=True)
        Path(self.data, "backend", "azure-blob", "config").write_text(
            "CCCP_AZURE_BLOB_CONTAINER=from-file\n")
        row = [l for l in
               self._dump(CCCP_AZURE_BLOB_CONTAINER="from-env").splitlines()
               if "CONTAINER" in l][0]
        self.assertIn("from-env", row)          # what cccp actually resolves
        self.assertNotIn("from-file", row)
        self.assertIn("shadows backend/azure-blob/config", row)

    def test_skill_names_the_column_the_cli_prints(self):
        here = os.path.dirname(os.path.abspath(__file__))
        skill = Path(here, os.pardir, "skills", "setup", "SKILL.md").read_text()
        self.assertIn("`Set by`", skill)
        self.assertIn("Set by", self._header())


class BackendConfigWrite(unittest.TestCase):
    """_write_kv is the one writer behind both the global `config` file and every
    backend/<name>/config:
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


class ConfigSet(unittest.TestCase):
    """`cccp config KEY=VALUE` routes each canonical key to its proper file via
    the registry map, refuses what it must, and never leaves 'which file did
    that touch' a mystery."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.data, True))

    def _set(self, assignments, **env):
        with _isolated_env(self.data, **env):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cccp._config_set(assignments)
            return buf.getvalue()

    def test_destinations_cover_globals_and_every_backend(self):
        dest = cccp._config_destinations()
        self.assertEqual(dest["CCCP_DEBUG"], "config")
        self.assertEqual(dest["CCCP_AZURE_BLOB_SAS"], "backend/azure-blob/config")
        self.assertNotIn("CCCP_ACTIVE_BACKEND", dest)   # refused, not routed
        self.assertNotIn("CCCP_PLUGIN_DATA", dest)

    def test_routes_to_the_named_file_and_says_so(self):
        out = self._set(["CCCP_AZURE_BLOB_ACCOUNT=hub", "CCCP_DEBUG=1"])
        self.assertIn("Set CCCP_AZURE_BLOB_ACCOUNT (backend/azure-blob/config)",
                      out)
        self.assertIn("Set CCCP_DEBUG (config)", out)
        self.assertEqual(
            cccp._read_kv_file(
                Path(self.data, "backend", "azure-blob", "config")),
            {"CCCP_AZURE_BLOB_ACCOUNT": "hub"})
        self.assertEqual(cccp._read_kv_file(Path(self.data, "config")),
                         {"CCCP_DEBUG": "1"})

    def test_backend_write_suggests_validation(self):
        out = self._set(["CCCP_AZURE_BLOB_ACCOUNT=hub"])
        self.assertIn("cccp backend check azure-blob", out)

    def test_empty_value_removes(self):
        self._set(["CCCP_DEBUG=1"])
        out = self._set(["CCCP_DEBUG="])
        self.assertIn("Removed CCCP_DEBUG (config)", out)
        self.assertEqual(cccp._read_kv_file(Path(self.data, "config")), {})

    def test_unknown_key_exits_listing_known(self):
        with _isolated_env(self.data):
            with self.assertRaises(SystemExit) as cm:
                cccp._config_set(["CCCP_AZURE_BLOB_ACCUONT=hub"])
        self.assertIn("CCCP_AZURE_BLOB_ACCOUNT", str(cm.exception))

    def test_active_backend_refused_toward_backend_use(self):
        with _isolated_env(self.data):
            with self.assertRaises(SystemExit) as cm:
                cccp._config_set(["CCCP_ACTIVE_BACKEND=local-fs"])
        self.assertIn("cccp backend use", str(cm.exception))

    def test_plugin_data_refused_as_env_only(self):
        with _isolated_env(self.data):
            with self.assertRaises(SystemExit) as cm:
                cccp._config_set(["CCCP_PLUGIN_DATA=/x"])
        self.assertIn("environment-only", str(cm.exception))

    def test_env_shadowed_write_warns(self):
        out = self._set(["CCCP_DEBUG=0"], CCCP_DEBUG="1")
        self.assertIn("Set CCCP_DEBUG (config)", out)
        self.assertIn("shadows this write", out)

    def test_empty_stdin_explains_why_an_agent_cannot_supply_it(self):
        with _isolated_env(self.data), \
                mock.patch.object(cccp.sys, "stdin", io.StringIO("")):
            with self.assertRaises(SystemExit) as cm:
                cccp._config_set(["CCCP_AZURE_BLOB_SAS=-"])
        msg = str(cm.exception)
        self.assertIn("not a terminal", msg)
        self.assertIn("run this command themselves", msg)

    def test_config_keys_cover_secrets_and_optionals(self):
        self.assertEqual(cccp._config_keys("local-fs"), ("ROOT",))
        self.assertEqual(cccp._config_keys("azure-blob"),
                         ("ACCOUNT", "CONTAINER", "SAS", "PREFIX"))


class SetupGuidance(unittest.TestCase):
    """_backend_setup_guidance is the one place a stuck reader looks - it must
    name commands that exist, resolve paths, and carry the money caveat."""

    def test_guidance_names_the_command_to_run(self):
        with tempfile.TemporaryDirectory() as d, _isolated_env(d):
            guidance = cccp._backend_setup_guidance("azure-blob")
        self.assertIn("cccp config CCCP_AZURE_BLOB_ACCOUNT", guidance)
        self.assertNotIn("backend config", guidance)
        self.assertNotIn("  ", guidance)      # no double space from concatenation

    def test_guidance_hands_the_secret_to_the_user(self):
        with tempfile.TemporaryDirectory() as d, _isolated_env(d):
            guidance = cccp._backend_setup_guidance("azure-blob")
        self.assertIn("SAS=-", guidance)
        self.assertIn("hand them that command", guidance)

    def test_guidance_flags_the_cost_of_provisioning(self):
        with tempfile.TemporaryDirectory() as d, _isolated_env(d):
            guidance = cccp._backend_setup_guidance("azure-blob")
        self.assertIn("apply.sh", guidance)
        self.assertIn("confirm with the user first", guidance)

    def test_user_facing_text_never_prints_a_literal_env_var_name(self):
        with tempfile.TemporaryDirectory() as d, _isolated_env(d):
            guidance = cccp._backend_setup_guidance("local-fs")
        self.assertIn(d, guidance)                       # the resolved path
        self.assertNotIn("`$CCCP_PLUGIN_DATA` is set and writable", guidance)


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

    def test_secrets_are_params_declared_exactly_once(self):
        # A secret IS a param (see _backend_params); repeating it in `params`
        # would double it in every key listing.
        for name, spec in cccp.BACKENDS.items():
            for key in spec.get("secrets", ()):
                self.assertNotIn(key, spec["params"],
                                 f"{name}: {key} declared twice")
                self.assertIn(key, cccp._backend_params(spec))


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
        self.assertEqual(self.b.append_block(p, b"line1\n"), (201, 0))
        self.assertEqual(self.b.append_block(p, b"line2\n"), (201, 6))
        self.assertEqual(self.b.stat(p), (200, 12))
        self.assertEqual(self.b.stat("demo/nope"), (404, None))
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


class AppendDispatchReadBack(unittest.TestCase):
    """append_dispatch must verify the line against the store, not trust the
    write status (#7): a 201 whose bytes are not readable back is NOT delivered
    and must raise."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.b = cccp.LocalFilesBackend(self._tmp.name)

    def test_honest_store_round_trips(self):
        cccp.append_dispatch(self.b, "p", "cell", "u@h:aaa", {"type": "message"})
        st, body = self.b.get("p/cell/gazettes/u@h:aaa.jsonl")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body), {"type": "message"})

    def test_forged_201_without_persist_raises(self):
        # A store (or middlebox) that says 201 but never persists: the #7
        # incident shape. The read-back must catch it at send time.
        self.b.append_block = lambda path, data: (201, 0)
        with self.assertRaises(cccp.BlobError) as ctx:
            cccp.append_dispatch(self.b, "p", "cell", "u@h:aaa", {"t": 1})
        self.assertIn(b"NOT delivered", ctx.exception.body)

    def test_201_without_offset_raises(self):
        self.b.append_block = lambda path, data: (201, None)
        with self.assertRaises(cccp.BlobError):
            cccp.append_dispatch(self.b, "p", "cell", "u@h:aaa", {"t": 1})

    def test_truncated_persist_raises(self):
        # Store keeps only a prefix of the line: read-back mismatch.
        real = self.b.append_block
        self.b.append_block = lambda path, data: real(path, data[: len(data) // 2])
        with self.assertRaises(cccp.BlobError):
            cccp.append_dispatch(self.b, "p", "cell", "u@h:aaa", {"t": 1})


class InboxShutdown(unittest.TestCase):
    """#16: `cccp stop` ends a watchtower through its (cell, comrade)-keyed
    inbox - kill-free, so it can never reach a peer's watchtower - and the
    stdout reader sees a deliberate `shutdown` event, not a dead stream."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.data, True))
        self.env = _isolated_env(self.data)
        self.env.__enter__()
        self.addCleanup(lambda: self.env.__exit__(None, None, None))
        self.wt = cccp.Watchtower(_FakeBlobClient(), "", "demo", "me@h:mmm", 0)
        self.wt.emitted = []
        self.wt._emit = self.wt.emitted.append

    def test_shutdown_record_stops(self):
        self.wt._apply_inbox({"ev": "shutdown", "ts": "2026-07-18T00:00:00Z"})
        self.assertTrue(self.wt.stop)
        self.assertEqual(self.wt.stop_reason, "inbox_shutdown")

    def test_record_stop_emits_reason(self):
        self.wt.stop_reason = "inbox_shutdown"
        self.wt._record_stop()
        self.assertIn("shutdown me@h:mmm slug=demo reason=inbox_shutdown",
                      self.wt.emitted)

    def test_poll_after_shutdown_skips_network(self):
        self.wt.client.blobs = None   # any scan would raise
        cccp.inbox_path("demo", "me@h:mmm").parent.mkdir(parents=True,
                                                         exist_ok=True)
        self.wt._reset_inbox()
        with mock.patch.object(cccp, "wake_watchtowers",
                               lambda slug: mock.Mock(returncode=1)):
            cccp.inbox_send("demo", "me@h:mmm", [{"ev": "shutdown"}])
        self.wt._poll_once()   # drains, stops, and must not touch the client
        self.assertTrue(self.wt.stop)

    def test_unknown_ev_still_ignored(self):
        self.wt._apply_inbox({"ev": "frobnicate"})
        self.assertFalse(self.wt.stop)


class WakePattern(unittest.TestCase):
    """The wake pkill pattern must hit watchtowers and NEVER the Monitor bash
    wrapper - SIGUSR1 terminates an unsuspecting bash, and the watchtower then
    follows via the ppid watchdog. The flags-after-slug wrapper (a space, not
    a quote, after the slug) is the exact cmdline that beheaded #5's cells on
    every wake/deadline-arm broadcast."""

    WT_BARE = "/usr/bin/python3 /x/bin/cccp watchtower demo -- u@h:aaaaaa"
    WT_FLAGS = ("/usr/bin/python3 /x/bin/cccp watchtower demo "
                "--alias-trigger Intro: -- u@h:aaaaaa")
    WRAP_BARE = ("bash -c cd /x && eval 'bin/cccp watchtower demo' "
                 "< /dev/null && echo done")
    WRAP_FLAGS = ("bash -c cd /x && eval 'bin/cccp watchtower demo "
                  "--alias-trigger 'Intro:'' < /dev/null && echo done")

    def _hits(self, cmdline, slug="demo"):
        import re as _re
        return bool(_re.search(cccp.wake_pattern(slug), cmdline))

    def test_matches_bare_watchtower(self):
        self.assertTrue(self._hits(self.WT_BARE))

    def test_matches_flagged_watchtower(self):
        self.assertTrue(self._hits(self.WT_FLAGS))

    def test_spares_bare_wrapper(self):
        self.assertFalse(self._hits(self.WRAP_BARE))

    def test_spares_flagged_wrapper(self):
        self.assertFalse(self._hits(self.WRAP_FLAGS))

    def test_slug_is_word_bounded(self):
        other = self.WT_BARE.replace("watchtower demo", "watchtower demo-x")
        self.assertFalse(self._hits(other))


class DeadlineEventAttribution(unittest.TestCase):
    """#13: deadline events resolve comrade= through the alias map, which can be
    stale - so whenever the rendered name is not the raw id, the id must ride
    along, keeping the event attributable regardless of the map."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.data, True))
        self.env = _isolated_env(self.data)
        self.env.__enter__()
        self.addCleanup(lambda: self.env.__exit__(None, None, None))
        self.wt = cccp.Watchtower(_FakeBlobClient(), "", "demo", "me@h:mmm", 0)

    def test_alias_rendering_carries_id(self):
        self.wt.aliases = {"peer@h:ppp": "Deputy"}
        line = self.wt._deadline_head("peer@h:ppp", {"limit": "10m"}, "missed")
        self.assertIn("comrade=Deputy id=peer@h:ppp ", line)

    def test_raw_id_carries_no_id_field(self):
        line = self.wt._deadline_head("peer@h:ppp", {"limit": "10m"}, "met")
        self.assertIn("comrade=peer@h:ppp ", line)
        self.assertNotIn(" id=", line)

    def test_self_renders_you_with_id(self):
        line = self.wt._deadline_head("me@h:mmm", {"limit": "5m"}, "missed")
        self.assertIn("comrade=you id=me@h:mmm ", line)


class WatchtowerStatus(unittest.TestCase):
    """#18: `cccp status` must distinguish alive, stopped-with-reason, and
    died-hard (stale pid record) - a dead watchtower must never be mistaken
    for a quiet cell."""

    SLUG, ME = "demo", "me@h:mmm"

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.data, True))
        self.env = _isolated_env(self.data)
        self.env.__enter__()
        self.addCleanup(lambda: self.env.__exit__(None, None, None))
        self.wt = cccp.Watchtower(_FakeBlobClient(), "", self.SLUG, self.ME, 0)
        self.wt.emitted = []
        self.wt._emit = self.wt.emitted.append

    def test_absent_before_any_run(self):
        state, detail = cccp.watchtower_status(self.SLUG, self.ME)
        self.assertEqual(state, "absent")
        self.assertIn("no watchtower record", detail)

    def test_alive_requires_matching_argv(self):
        self.wt._write_pidfile()
        my_argv = (f"/usr/bin/python3 /x/bin/cccp watchtower {self.SLUG} "
                   f"-- {self.ME}")
        with mock.patch.object(cccp, "process_argv", lambda pid: my_argv):
            state, detail = cccp.watchtower_status(self.SLUG, self.ME)
        self.assertEqual(state, "alive")
        self.assertIn(f"pid={os.getpid()}", detail)

    def test_recycled_pid_is_stale_not_alive(self):
        self.wt._write_pidfile()
        with mock.patch.object(cccp, "process_argv",
                               lambda pid: "/usr/bin/vim notes.txt"):
            state, detail = cccp.watchtower_status(self.SLUG, self.ME)
        self.assertEqual(state, "stale")
        self.assertIn("died without a clean exit", detail)

    def test_hard_death_is_stale(self):
        self.wt._write_pidfile()
        with mock.patch.object(cccp, "process_argv", lambda pid: None):
            state, _ = cccp.watchtower_status(self.SLUG, self.ME)
        self.assertEqual(state, "stale")

    def test_clean_stop_reports_reason_and_clears_pidfile(self):
        self.wt._write_pidfile()
        self.wt.stop_reason = "parent_exited"
        self.wt._record_stop()
        self.assertFalse(cccp.pid_path(self.SLUG, self.ME).exists())
        state, detail = cccp.watchtower_status(self.SLUG, self.ME)
        self.assertEqual(state, "stopped")
        self.assertIn("reason=parent_exited", detail)

    def test_crash_in_run_records_crash_reason(self):
        self.wt.initial_scan = mock.Mock(side_effect=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            self.wt.run()
        state, detail = cccp.watchtower_status(self.SLUG, self.ME)
        self.assertEqual(state, "stopped")
        self.assertIn("reason=crash_RuntimeError", detail)


class JournalRecordsOnBad(unittest.TestCase):
    """Malformed journal lines are skipped-but-consumed; on_bad makes the skip
    observable so data loss and parse bugs stop looking identical (#7)."""

    def test_on_bad_sees_each_malformed_line(self):
        bad = []
        data = b'{"a":1}\nnot json\n{"b":2}\n'
        records, consumed = cccp.journal_records(data, on_bad=bad.append)
        self.assertEqual(records, [{"a": 1}, {"b": 2}])
        self.assertEqual(consumed, len(data))
        self.assertEqual(bad, [b"not json\n"])

    def test_on_bad_omitted_still_skips(self):
        records, consumed = cccp.journal_records(b"junk\n{\"a\":1}\n")
        self.assertEqual(records, [{"a": 1}])


if __name__ == "__main__":
    unittest.main(verbosity=2)

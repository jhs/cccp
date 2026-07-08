#!/usr/bin/env python3
"""Unit tests for cccp's preview/continuation split (stdlib only).

Run: python3 tests/test_cccp.py   (or: -m unittest -v)

Covers the invariants that would silently corrupt a read if they drift: the
watchtower preview and the `read` continuation must split the body at the SAME
byte, the truncated event must fit the Monitor envelope, and escapes must never
be split. cccp is an executable script (no .py), so load it by path.
"""
import importlib.util
import json
import os
import unittest
from importlib.machinery import SourceFileLoader
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
        return cccp.render_skill_body(self.TEMPLATE, "alice@hostA:aaaaaa")

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


class SkillTemplateFile(unittest.TestCase):
    """The shipped cccp skill template must render with no leftover tokens and must
    not smuggle in a substitution Claude would choke on (it is not re-rendered)."""

    def _template(self):
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, os.pardir, "skills", "chat", "body.template.md")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_ships_and_renders_clean(self):
        rendered = cccp.render_skill_body(self._template(), "bob@hostB:1a2b3c")
        self.assertNotIn("@@", rendered)                     # no unresolved token
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", rendered)  # no path token in body
        self.assertNotIn("$ARGUMENTS", rendered)             # args come from SKILL.md
        self.assertIn("bob@hostB:1a2b3c", rendered)
        self.assertIn("cccp watchtower <slug>", rendered)    # bare command, no path
        self.assertIn("<slug>", rendered)                    # slug stays a placeholder


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


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_token_audit.py
# Purpose : Exam for tools/token_audit.py in a fake home and project (temp folder, offline, standard library):
#           memory files with @imports (one level, code spans and e-mail addresses are not imports), the 5k / 10k
#           flags, settings hooks and model / effort, proxy variables reported by name and never by value, .mcp.json
#           names, subagent models, the session log summed once per message id with first / last context, model
#           switches and cache lifetimes, no message text printed, log discovery by folder name, exit codes.
# Usage   : python tools/test_token_audit.py
#           uv run -q --python 3.8 python -B tools/test_token_audit.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import token_audit  # noqa: E402

SECRET = "sk-proxy-VALUE-must-never-print"
TEXT = "PRIVATE MESSAGE TEXT that must never print"
# names cp1252 cannot decode (a right double quote) plus an accented capital
PROJECT_NAME = "Gäme Í”"


def usage(read, write, inp, out, ttl="1h"):
    u = {"cache_read_input_tokens": read, "cache_creation_input_tokens": write, "input_tokens": inp,
         "output_tokens": out}
    u["cache_creation"] = {"ephemeral_1h_input_tokens": write if ttl == "1h" else 0,
                           "ephemeral_5m_input_tokens": write if ttl == "5m" else 0}
    return u


def assistant(mid, u, model="claude-opus-5-5", effort="high"):
    return json.dumps({"type": "assistant", "effort": effort,
                       "message": {"id": mid, "model": model, "role": "assistant", "usage": u,
                                   "content": [{"type": "text", "text": TEXT}]}})


# one API response is written as several lines repeating its usage: m1 x3, m2 x2, m3 once (a model switch)
LOG_LINES = [
    json.dumps({"type": "user", "message": {"role": "user", "content": TEXT}}),
    assistant("m1", usage(0, 1000, 10, 50)),
    assistant("m1", usage(0, 1000, 10, 50)),
    assistant("m1", usage(0, 1000, 10, 50)),
    '{"type": "assistant", "message": {cut off mid-write',
    assistant("m2", usage(1000, 200, 5, 100, ttl="5m"), effort="xhigh"),
    assistant("m2", usage(1000, 200, 5, 100, ttl="5m"), effort="xhigh"),
    assistant("synthetic", usage(0, 0, 0, 0), model="<synthetic>"),
    assistant("m3", usage(1200, 300, 2, 40), model="claude-sonnet-5-5"),
]
# totals counted once per id: read 2200, write 1500, input 17, output 190 -> 3907
EXPECTED = {"cache_read_input_tokens": 2200, "cache_creation_input_tokens": 1500, "input_tokens": 17,
            "output_tokens": 190}


class Fake:
    """A fake home and project: tmp/home/.claude, tmp/work/parent/<project>."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        self.claude = self.home / ".claude"
        self.work = self.tmp / "work"
        self.parent = self.work / "parent"
        self.root = self.parent / PROJECT_NAME
        for d in (self.claude / "agents", self.root / ".claude" / "agents", self.root / "docs",
                  self.root / ".claude" / "skills" / "demo"):
            d.mkdir(parents=True)
        self.write(self.claude / "CLAUDE.md", "# user memory\n" + "u" * 386)                      # 400 chars
        self.write(self.home / "shared.md", "s" * 40)
        self.write(self.parent / "CLAUDE.md", "p" * 80)
        self.write(self.root / "CLAUDE.md",
                   "# project\n@docs/extra.md\nAlso see @~/shared.md and @docs/missing.md.\n"
                   "Not imports: `@docs/ignored.md`, mail me at dev@example.com, ask @someone.\n"
                   "```\n@docs/fenced.md\n```\n")
        self.write(self.root / "docs" / "extra.md", "e" * 120)
        self.write(self.root / "docs" / "ignored.md", "i" * 4000)
        self.write(self.root / "docs" / "fenced.md", "f" * 4000)
        self.write(self.root / "CLAUDE.local.md", "l" * 20)
        self.write(self.root / ".claude" / "settings.json", json.dumps({
            "model": "opusplan", "effortLevel": "xhigh",
            "env": {"ANTHROPIC_BASE_URL": SECRET, "HARMLESS": "x"},
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "trim " + SECRET}]}],
                      "SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))
        self.write(self.root / ".mcp.json", json.dumps({"mcpServers": {"godot": {"command": "x", "env": {
            "TOKEN": SECRET}}}}))
        self.write(self.root / ".claude" / "agents" / "fast.md", "---\nname: fast\nmodel: haiku\n---\nbody\n")
        self.write(self.root / ".claude" / "agents" / "plain.md", "---\nname: plain\ndescription: x\n---\nbody\n")
        self.write(self.claude / "agents" / "inherit.md", "---\nname: inherit\nmodel: inherit\n---\nbody\n")
        self.write(self.root / ".claude" / "skills" / "demo" / "SKILL.md",
                   "---\nname: demo\ndescription: " + "d" * 40 + "\n---\nbody\n")
        # the log folder Claude Code would name after the project path, in another case than the path
        self.logs = self.claude / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(self.root)).upper()
        self.logs.mkdir(parents=True)
        self.write(self.logs / "memory" / "MEMORY.md", "m" * 60)

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def add_log(self, name, lines, age_s=0):
        path = self.logs / name
        self.write(path, "\n".join(lines) + "\n")
        t = time.time() - age_s
        os.utime(str(path), (t, t))
        return path

    def audit(self, env=None, log=None):
        return token_audit.audit(self.root, home=self.home, env=env or {}, log=log, stop_at=self.work)

    def cli(self, *args, env=None):
        """main() in a clean environment; never searches parent CLAUDE.md files above the fake tree (#220)."""
        args = list(args) + ([] if "--stop-at" in [str(a) for a in args] else ["--stop-at", self.work])
        out, err = io.StringIO(), io.StringIO()
        clean = {k: v for k, v in os.environ.items()
                 if k not in token_audit.PROXY_VARS + token_audit.GATEWAY_VARS + ("CLAUDE_CONFIG_DIR",)}
        clean.update(env or {})
        with mock.patch.dict(os.environ, clean, clear=True), redirect_stdout(out), redirect_stderr(err):
            code = token_audit.main([str(a) for a in args])
        return code, out.getvalue(), err.getvalue()

    def cleanup(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)


class TokenAudit(unittest.TestCase):
    def setUp(self):
        self.f = Fake()
        self.addCleanup(self.f.cleanup)

    def findings(self, rep, name):
        return [x for x in rep["findings"] if x["finding"] == name]

    # --- memory ---
    def test_memory_files_and_one_level_imports(self):
        rep = self.f.audit()
        by_path = {Path(m["path"]).name + ":" + m["kind"]: m for m in rep["memory"]}
        self.assertIn("CLAUDE.md:user", by_path)
        self.assertIn("CLAUDE.md:parent", by_path)
        self.assertIn("CLAUDE.md:project", by_path)
        self.assertIn("CLAUDE.local.md:project", by_path)
        self.assertIn("extra.md:import from CLAUDE.md", by_path)
        self.assertIn("shared.md:import from CLAUDE.md", by_path)
        self.assertIn("MEMORY.md:auto memory", by_path)
        names = [Path(m["path"]).name for m in rep["memory"]]
        self.assertNotIn("ignored.md", names)                        # a code span is not an import
        self.assertNotIn("fenced.md", names)                         # nor a fenced block
        project = by_path["CLAUDE.md:project"]
        self.assertEqual(project["imports_missing"], ["docs/missing.md"])   # not "example.com", not "someone"
        self.assertEqual(by_path["CLAUDE.md:user"]["est_tokens"], 100)       # 400 chars / 4
        self.assertEqual(by_path["extra.md:import from CLAUDE.md"]["est_tokens"], 30)
        self.assertEqual(self.findings(rep, "Memory files loaded at start")[0]["severity"], "GREEN")
        self.assertEqual(self.findings(rep, "@import not found")[0]["severity"], "AMBER")

    def test_parents_stop_where_asked(self):
        self.f.write(self.f.tmp / "CLAUDE.md", "above the stop")
        rep = self.f.audit()
        self.assertNotIn(str(self.f.tmp / "CLAUDE.md"), [m["path"] for m in rep["memory"]])

    def test_import_shared_by_two_files_counts_once(self):
        self.f.write(self.f.root / "CLAUDE.local.md", "@docs/extra.md\n")
        rep = self.f.audit()
        self.assertEqual(sum(1 for m in rep["memory"] if m["path"].endswith("extra.md")), 1)

    def test_thresholds_flag_a_big_file_and_total(self):
        self.f.write(self.f.root / "docs" / "extra.md", "x" * (4 * 5001))     # 5,001 est tokens
        self.f.write(self.f.parent / "CLAUDE.md", "y" * (4 * 5000))           # 5,000: not over
        rep = self.f.audit()
        big = self.findings(rep, "Large memory file")
        self.assertEqual(len(big), 1)
        self.assertIn("extra.md", big[0]["evidence"])
        self.assertEqual(self.findings(rep, "Memory files loaded at start")[0]["severity"], "RED")
        self.assertEqual(rep["findings"][0]["severity"], "RED")             # sorted by severity first

    # --- settings ---
    def test_proxy_variable_by_name_never_by_value(self):
        code, out, err = self.f.cli("--root", self.f.root, "--home", self.f.home, "--stop-at", self.f.work)
        self.assertEqual(code, 0, err)
        self.assertIn("ANTHROPIC_BASE_URL", out)
        self.assertNotIn(SECRET, out + err)
        code, js, err = self.f.cli("--root", self.f.root, "--home", self.f.home, "--json")
        self.assertEqual(code, 0, err)
        self.assertNotIn(SECRET, js + err)
        rep = json.loads(js)
        red = [x for x in rep["findings"] if x["finding"] == "Proxy or gateway variable set"]
        self.assertEqual(red[0]["severity"], "RED")

    def test_proxy_variable_in_the_shell(self):
        os.remove(str(self.f.root / ".claude" / "settings.json"))
        rep = self.f.audit(env={"ANTHROPIC_AUTH_TOKEN": SECRET})
        hits = rep["settings"]["proxy_vars"]
        self.assertEqual([(h["name"], h["where"]) for h in hits], [("ANTHROPIC_AUTH_TOKEN", "this shell's environment")])
        self.assertNotIn(SECRET, json.dumps(rep) + token_audit.render(rep))
        self.assertEqual(self.findings(rep, "No PreToolUse hook")[0]["severity"], "AMBER")

    def test_hooks_model_effort_and_mcp(self):
        rep = self.f.audit()
        proj = rep["settings"]["files"][0]
        self.assertEqual(proj["hooks"], [{"event": "PreToolUse", "matcher": "Bash", "count": 1},
                                         {"event": "SessionStart", "matcher": "(any)", "count": 1}])
        self.assertEqual(self.findings(rep, "PreToolUse hooks")[0]["severity"], "GREEN")
        self.assertEqual(self.findings(rep, "Automatic model switching")[0]["severity"], "AMBER")
        self.assertEqual(self.findings(rep, "High effort setting")[0]["severity"], "AMBER")
        mcp = self.findings(rep, "MCP servers named in files")[0]
        self.assertEqual((mcp["severity"], mcp["evidence"]), ("UNKNOWN", "1 in .mcp.json (godot)"))
        self.assertNotIn(SECRET, token_audit.render(rep))           # hook commands and MCP env are not printed

    def test_broken_settings_file_is_reported_not_fatal(self):
        self.f.write(self.f.root / ".claude" / "settings.local.json", "{ not json")
        rep = self.f.audit()
        self.assertTrue(rep["settings"]["files"][1]["error"])
        self.assertIn("cannot parse", token_audit.render(rep))

    # --- agents and skills ---
    def test_subagent_models(self):
        rep = self.f.audit()
        models = {a["name"]: a["model"] for a in rep["agents"]}
        self.assertEqual(models, {"fast": "haiku", "plain": "inherits", "inherit": "inherits"})
        row = self.findings(rep, "Subagents without a model")[0]
        self.assertTrue(row["evidence"].startswith("2 of 3: "))
        self.assertEqual(rep["skills"][0]["est_tokens"], 10)

    # --- the session log ---
    def test_log_counts_each_message_id_once(self):
        self.f.add_log("s.jsonl", LOG_LINES)
        log = self.f.audit()["session"]
        self.assertEqual(log["totals"], EXPECTED)
        self.assertEqual(log["total"], 3907)
        self.assertEqual(log["responses"], 3)
        self.assertEqual(log["duplicate_lines"], 3)
        self.assertEqual(log["unreadable_lines"], 1)
        self.assertEqual(log["percent"]["cache_read_input_tokens"], round(100.0 * 2200 / 3907, 1))
        self.assertEqual(log["first_context"], 1010)                   # 10 + 0 + 1000
        self.assertEqual(log["last_context"], 1502)                    # 2 + 1200 + 300
        self.assertEqual(log["model_switches"], 1)
        self.assertEqual(log["cache_written_after_switches"], 300)
        self.assertEqual(log["cache_writes_by_ttl"], {"5m": 200, "1h": 1300})
        self.assertEqual(log["efforts"], {"high": 2, "xhigh": 1})

    def test_later_line_of_a_response_wins(self):
        self.f.add_log("s.jsonl", [assistant("m1", usage(0, 100, 1, 5)), assistant("m1", usage(0, 100, 1, 9))])
        self.assertEqual(self.f.audit()["session"]["totals"]["output_tokens"], 9)

    def test_no_message_text_is_printed(self):
        self.f.add_log("s.jsonl", LOG_LINES)
        code, out, err = self.f.cli("--root", self.f.root, "--home", self.f.home, "--debug")
        self.assertEqual(code, 0, err)
        code2, js, _ = self.f.cli("--root", self.f.root, "--home", self.f.home, "--json")
        self.assertNotIn(TEXT, out + err + js)
        self.assertIn("3 API responses", out)
        self.assertIn(PROJECT_NAME, out)

    def test_newest_log_is_found_by_folder_name(self):
        self.f.add_log("old.jsonl", [assistant("a", usage(1, 1, 1, 1))], age_s=3600)
        self.f.add_log("new.jsonl", LOG_LINES)
        log = self.f.audit()["session"]
        self.assertTrue(log["path"].endswith("new.jsonl"))
        self.assertIn("newest in", log["found_by"])

    def test_subagent_logs_are_summed_apart(self):
        main = self.f.add_log("s.jsonl", LOG_LINES)
        self.f.write(main.with_suffix("") / "subagents" / "agent-1.jsonl",
                     assistant("x", usage(10, 20, 30, 40)) + "\n" + assistant("x", usage(10, 20, 30, 40)) + "\n")
        log = self.f.audit()["session"]
        self.assertEqual(log["totals"], EXPECTED)
        self.assertEqual((log["subagents"]["logs"], log["subagents"]["total"]), (1, 100))

    def test_explicit_log_and_missing_log(self):
        other = self.f.tmp / "elsewhere.jsonl"
        self.f.write(other, "\n".join(LOG_LINES))
        rep = self.f.audit(log=str(other))
        self.assertEqual((rep["session"]["found_by"], rep["session"]["total"]), ("--log", 3907))
        code, _, err = self.f.cli("--root", self.f.root, "--home", self.f.home, "--log", self.f.tmp / "nope.jsonl")
        self.assertEqual(code, 2)
        self.assertIn("[error]", err)
        self.assertNotIn("Traceback", err)

    def test_no_log_is_unknown(self):
        rep = self.f.audit()
        row = self.findings(rep, "Prompt cache")[0]
        self.assertEqual(row["severity"], "UNKNOWN")
        self.assertIn("--log", row["cost"])

    def test_cache_severity_from_read_share(self):
        self.f.add_log("s.jsonl", [assistant("a", usage(900, 50, 50, 10))])     # 90% read
        self.assertEqual(self.findings(self.f.audit(), "Prompt cache")[0]["severity"], "GREEN")
        self.f.add_log("s.jsonl", [assistant("a", usage(100, 850, 50, 10))])    # 10% read
        self.assertEqual(self.findings(self.f.audit(), "Prompt cache")[0]["severity"], "RED")

    # --- CLI ---
    def test_bad_root_is_usage(self):
        code, _, err = self.f.cli("--root", self.f.tmp / "no-such-folder")
        self.assertEqual(code, 2)
        self.assertIn("[error]", err)

    def test_claude_config_dir_replaces_dot_claude(self):
        other = self.f.tmp / "cfg"
        self.f.write(other / "CLAUDE.md", "c" * 8)
        code, js, err = self.f.cli("--root", self.f.root, "--stop-at", self.f.work, "--json",
                                   env={"CLAUDE_CONFIG_DIR": str(other)})
        self.assertEqual(code, 0, err)
        rep = json.loads(js)
        # the folder it points at is read, but shown by the variable's name, never its value (#217)
        self.assertEqual(rep["claude_dir"], "$CLAUDE_CONFIG_DIR")
        self.assertIn(str(Path("$CLAUDE_CONFIG_DIR") / "CLAUDE.md"), [m["path"] for m in rep["memory"]])
        self.assertNotIn(str(other), js + err)
        code, out, err = self.f.cli("--root", self.f.root, env={"CLAUDE_CONFIG_DIR": str(other)})
        self.assertNotIn(str(other), out + err)

    def test_home_imports_ignore_the_config_dir(self):
        """#219: @~/ resolves against the user's home even when CLAUDE_CONFIG_DIR moves .claude elsewhere."""
        other = self.f.tmp / "cfg"
        self.f.write(other / "CLAUDE.md", "c" * 8)
        with mock.patch.object(token_audit.Path, "home", classmethod(lambda cls: self.f.home)):
            rep = token_audit.audit(self.f.root, home=None, env={"CLAUDE_CONFIG_DIR": str(other)}, stop_at=self.f.work)
        shared = [m for m in rep["memory"] if m["path"].endswith("shared.md")]
        self.assertEqual(len(shared), 1)
        self.assertTrue(shared[0]["exists"] if "exists" in shared[0] else shared[0]["bytes"] == 40, shared[0])

    # --- the review fixes (#217, #218, #220) ---
    def test_a_value_in_a_malformed_usage_field_is_never_printed(self):
        """#217: a string where a token count should be is a malformed line; its value never reaches any output."""
        bad = json.loads(assistant("m9", usage(1, 1, 1, 1)))
        bad["message"]["usage"]["input_tokens"] = SECRET
        self.f.add_log("s.jsonl", LOG_LINES + [json.dumps(bad)])
        for extra in ([], ["--json"], ["--debug"]):
            code, out, err = self.f.cli("--root", self.f.root, "--home", self.f.home, *extra)
            self.assertEqual(code, 0, err)
            self.assertNotIn(SECRET, out + err, extra)
        self.assertEqual(self.f.audit()["session"]["unreadable_lines"], 2)    # the old broken line and this one

    def test_unexpected_errors_print_the_type_only(self):
        """#217: the last-resort handler never echoes an exception's text (it can quote a file's contents)."""
        with mock.patch.object(token_audit, "audit", side_effect=ValueError("quoted " + SECRET)):
            code, out, err = self.f.cli("--root", self.f.root, "--home", self.f.home)
        self.assertEqual(code, 2)
        self.assertIn("ValueError", err)
        self.assertNotIn(SECRET, out + err)

    def test_settings_of_the_wrong_shape_are_reported_not_fatal(self):
        """#218: valid JSON of the wrong shape (a list, numbers where objects go) is a per-file error."""
        self.f.write(self.f.root / ".claude" / "settings.local.json", "[]")
        self.f.write(self.f.claude / "settings.json", json.dumps(
            {"hooks": {"Stop": [{"hooks": 1}], "Odd": 5}, "modelSettings": [1], "env": "x", "enabledPlugins": 3}))
        self.f.write(self.f.root / ".mcp.json", "[1, 2]")
        code, out, err = self.f.cli("--root", self.f.root, "--home", self.f.home)
        self.assertEqual(code, 0, err)
        rep = self.f.audit()
        self.assertIn("not a JSON object", rep["settings"]["files"][1]["error"])
        self.assertEqual(rep["settings"]["files"][2]["hooks"], [{"event": "Stop", "matcher": "(any)", "count": 0}])
        self.assertIn("not a JSON object", rep["settings"]["mcp_json_error"])

    def test_an_oversized_log_record_is_skipped_unread(self):
        """#220: a record over the line limit is skipped, the rest of the log still counts."""
        huge = '{"type": "assistant", "pad": "' + "x" * 5000 + '"}'
        self.f.add_log("s.jsonl", [huge] + LOG_LINES)
        with mock.patch.object(token_audit, "MAX_LINE_BYTES", 1024):
            log = self.f.audit()["session"]
        self.assertEqual(log["totals"], EXPECTED)
        self.assertEqual(log["unreadable_lines"], 2)

    def test_folded_and_literal_descriptions_are_counted(self):
        """#220: description: >- (or |) with indented lines is the whole text, not '>-'."""
        for marker in (">-", "|"):
            self.f.write(self.f.root / ".claude" / "skills" / "demo" / "SKILL.md",
                         f"---\nname: demo\ndescription: {marker}\n  " + "a" * 40 + "\n  " + "b" * 40 + "\n---\nbody\n")
            skill = self.f.audit()["skills"][0]
            self.assertEqual(skill["description_chars"], 81, marker)
        meta = token_audit.frontmatter("---\nname: x\ndescription: plain start\n  wrapped end\n---\n")
        self.assertEqual(meta["description"], "plain start wrapped end")

    def test_no_network_and_no_writes(self):
        """The promises in the header: no socket is opened and no file under the fake tree changes."""
        self.f.add_log("s.jsonl", LOG_LINES)
        before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in self.f.tmp.rglob("*") if p.is_file()}

        def no_net(*a, **k):
            raise AssertionError("token_audit opened a socket")
        with mock.patch("socket.socket", no_net), mock.patch("socket.create_connection", no_net):
            for extra in ([], ["--json"]):
                code, out, err = self.f.cli("--root", self.f.root, "--home", self.f.home, *extra)
                self.assertEqual(code, 0, err)
        after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in self.f.tmp.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_unknowns_and_help(self):
        code, out, _ = self.f.cli("--root", self.f.root, "--home", self.f.home)
        for cmd in ("/context", "/usage", "/mcp", "claude mcp list"):
            self.assertIn(cmd, out)
        self.assertIn("| FINDING | SEVERITY | EVIDENCE | WHAT IT IS COSTING |", out)
        with self.assertRaises(SystemExit) as cm, redirect_stdout(io.StringIO()) as buf:
            token_audit.main(["-h"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("CLAUDE_CONFIG_DIR", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=1)

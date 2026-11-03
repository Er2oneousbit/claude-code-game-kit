#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_new_game.py
# Purpose : Exam for new_game.py, the scaffolder, against a tiny fake kit (the real new_game.py, a small core, one
#           fake engine) under a temp folder. New: placeholders filled, the engine's docs and skeleton land (a skeleton
#           file beats the core file at the same path), CRLF kit text comes out LF, .gitignore and settings.json are
#           composed, the recorded hashes match the files, a {{FOOTER}} line follows the profile. Adopt: never
#           overwrites (a .gold copy and the engine's adopt hint instead), appends the .gitignore block once, merges
#           settings keeping the project's rules, a second adopt adds nothing. Upgrade: replaces untouched kit files,
#           keeps edited ones (.gold), leaves out files the project deleted, adds new kit files, a second upgrade is
#           quiet, the recorded name, slug and engine are reused and a different one is refused. Exit codes: 1 for an unresolved placeholder, 2 for every refusal; --dry-run writes nothing.
# Usage   : python scripts/test_new_game.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only, offline. The real engines are checked by scaffolding them (CLAUDE.md, "Verify a
#           change"); this exam pins the scaffolder's own rules, which no engine run checks one by one.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import new_game  # noqa: E402  (pure helpers only; scaffolding runs the copy in the fake kit)

NAME = "Fake Game"
CORE = {
    "CLAUDE.md": "# {{GAME_NAME}} ({{GAME_SLUG}})\nEngine: {{ENGINE_LABEL}}, made {{DATE}} by {{AUTHOR}}.\n",
    "docs/GDD.md": "# {{GAME_NAME}} design\nFill this in.\n",
    "docs/README.md": "core readme\n",
    "tools/kit_tool.py": "print('kit tool v1')\n",
    "tools/old_tool.py": "print('old tool v1')\n",
    ".gitignore": "*.tmp\n",
}
CORE_CRLF = ("docs/crlf.md", b"line one\r\nline two for {{GAME_NAME}}\r\n")
CORE_SETTINGS = {"permissions": {"allow": ["Bash(python tools/dev.py check)"], "deny": ["Read(.env)"]},
                 "model": "core"}
PATCH = {"permissions": {"allow": ["Bash(python tools/dev.py check)", "Bash(fake-engine *)"]}, "model": "engine"}
ENGINE = {"id": "fake", "label": "Fake Engine", "summary": "for the exam", "skeleton_dir": "skeleton",
          "gitignore_append": "gitignore.append", "settings_patch": "settings.patch.json",
          "engine_md": "ENGINE.md", "flow_md": "FLOW.md", "assets_dir": "assets",
          "adopt_hints": {"CLAUDE.md": "keep your notes and add the kit's imports"}}
SKELETON = {
    "docs/README.md": "engine readme for {{GAME_NAME}}\n",
    "src/main.py": "print('{{GAME_NAME}}')\n\n# {{FOOTER}}\n",
}


def write(path, text):
    """UTF-8, LF line ends on every OS (write_bytes: Path.write_text has no newline= before Python 3.10)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NewGameExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.kit = self.root / "kit"
        (self.kit / "scripts").mkdir(parents=True)
        shutil.copy2(HERE / "new_game.py", self.kit / "scripts" / "new_game.py")
        for rel, text in CORE.items():
            write(self.kit / "core" / rel, text)
        (self.kit / "core" / CORE_CRLF[0]).write_bytes(CORE_CRLF[1])
        write(self.kit / "core" / ".claude" / "settings.json", json.dumps(CORE_SETTINGS, indent=2))
        eng = self.kit / "engines" / "fake"
        write(eng / "engine.json", json.dumps(ENGINE, indent=2))
        write(eng / "ENGINE.md", "# {{ENGINE_LABEL}} notes for {{GAME_NAME}}\n")
        write(eng / "FLOW.md", "# Flow\n")
        write(eng / "gitignore.append", "fake_cache/\n")
        write(eng / "settings.patch.json", json.dumps(PATCH, indent=2))
        for rel, text in SKELETON.items():
            write(eng / "skeleton" / rel, text)
        write(self.kit / "engines" / "_template" / "engine.json", json.dumps(dict(ENGINE, id="template")))
        write(self.kit / "profiles" / "default.json", json.dumps({"author": "", "footer": "", "style": []}))
        self.dest = self.root / "game"

    def tearDown(self):
        self.tmp.cleanup()

    # ---- helpers ------------------------------------------------------------
    def ng(self, *extra, dest=None, name=NAME, engine="fake", author="Tester"):
        """Run the fake kit's scaffolder; name=None or engine=None leaves that option out."""
        ident = (["--name", name] if name is not None else []) + (["--engine", engine] if engine is not None else [])
        args = [sys.executable, "-B", str(self.kit / "scripts" / "new_game.py"), *ident,
                "--dest", str(dest or self.dest), "--author", author, *[str(a) for a in extra]]
        r = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace")
        return r.returncode, r.stdout + r.stderr

    def text(self, rel, base=None):
        return ((base or self.dest) / rel).read_bytes().decode("utf-8")

    def meta(self):
        return json.loads(self.text(".game-kit.json"))

    def new(self):
        code, out = self.ng()
        self.assertEqual(code, 0, out)
        return out

    # ---- helpers in the module ----------------------------------------------
    def test_make_slug(self):
        self.assertEqual(new_game.make_slug("My Cool Game!"), "my_cool_game")
        self.assertEqual(new_game.make_slug("Café Über"), "cafe_uber")
        self.assertEqual(new_game.make_slug("1942 Redux"), "game_1942_redux")
        with contextlib.redirect_stdout(io.StringIO()) as said:                 # it explains the suffix
            self.assertEqual(new_game.make_slug("Test"), "test_game")       # a CMake reserved target
        self.assertIn("reserved", said.getvalue())
        self.assertEqual(new_game.make_slug("anything", "my_game"), "my_game")
        for bad_name, override in (("東方", None), ("x", "My-Game"), ("x", "bevy")):
            with self.assertRaises(new_game.ScaffoldError):
                new_game.make_slug(bad_name, override)

    def test_deep_merge(self):
        merged = new_game.deep_merge({"a": [1, 2], "d": {"x": 1}, "s": "base"}, {"a": [2, 3], "d": {"y": 2}, "s": "p"})
        self.assertEqual(merged, {"a": [1, 2, 3], "d": {"x": 1, "y": 2}, "s": "p"})

    # ---- new ----------------------------------------------------------------
    def test_new_project_is_composed_and_recorded(self):
        out = self.new()
        self.assertIn("[ OK ] created", out)
        self.assertEqual(self.text("CLAUDE.md").splitlines()[0], "# Fake Game (fake_game)")
        self.assertIn("Engine: Fake Engine", self.text("CLAUDE.md"))
        self.assertIn("by Tester.", self.text("CLAUDE.md"))
        self.assertEqual(self.text("docs/ENGINE.md"), "# Fake Engine notes for Fake Game\n")
        self.assertEqual(self.text("docs/ENGINE_FLOW.md"), "# Flow\n")
        self.assertEqual(self.text("docs/README.md"), "engine readme for Fake Game\n", "skeleton beats core")
        self.assertEqual((self.dest / CORE_CRLF[0]).read_bytes(), b"line one\nline two for Fake Game\n")
        self.assertTrue((self.dest / "assets" / ".gitkeep").is_file())
        self.assertEqual(self.text("src/main.py"), "print('Fake Game')\n", "no footer: the line and blank go")
        ignore = self.text(".gitignore")
        self.assertTrue(ignore.startswith(new_game.GITIGNORE_MARKER + "\n"))
        self.assertIn("*.tmp", ignore)
        self.assertIn("fake_cache/", ignore)
        settings = json.loads(self.text(".claude/settings.json"))
        self.assertEqual(settings["permissions"]["allow"], ["Bash(python tools/dev.py check)", "Bash(fake-engine *)"])
        self.assertEqual(settings["permissions"]["deny"], ["Read(.env)"])
        self.assertEqual(settings["model"], "engine")
        meta = self.meta()
        self.assertEqual((meta["engine"], meta["game_name"], meta["author"]), ("fake", NAME, "Tester"))
        self.assertEqual([h["mode"] for h in meta["history"]], ["new"])
        self.assertNotIn(".gitignore", meta["files"])
        self.assertNotIn(".claude/settings.json", meta["files"])
        self.assertIn("tools/kit_tool.py", meta["files"])
        for rel, recorded in meta["files"].items():
            self.assertEqual(sha(self.dest / rel), recorded, rel)

    def test_profile_footer_line(self):
        prof = self.root / "me.json"
        write(prof, json.dumps({"author": "Prof Author", "footer": "Made by the exam", "style": []}))
        code, out = self.ng("--profile", prof, author="")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.text("src/main.py"), "print('Fake Game')\n\n# Made by the exam\n")

    def test_dry_run_writes_nothing(self):
        code, out = self.ng("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("[dry-run] would create", out)
        self.assertFalse(self.dest.exists())

    # ---- exit codes ---------------------------------------------------------
    def test_unresolved_placeholder_exits_1(self):
        write(self.kit / "core" / "docs" / "BROKEN.md", "{{NOT_A_KEY}}\n")
        code, out = self.ng()
        self.assertEqual(code, 1, out)
        self.assertIn("[WARN] unresolved placeholder: docs/BROKEN.md", out)

    def test_refusals_exit_2(self):
        cases = [
            (dict(dest=self.kit / "inside"), "inside the kit"),
            (dict(engine="nope"), "unknown engine"),
            (dict(engine="template"), "unknown engine"),               # engines/_* are templates, never offered
            (dict(name='Bad "Name"'), "must not contain quotes"),
        ]
        for kwargs, needle in cases:
            code, out = self.ng(**kwargs)
            self.assertEqual(code, 2, f"{kwargs}: {out}")
            self.assertIn(needle, out, kwargs)
            self.assertNotIn("Traceback", out)
        code, out = self.ng("--upgrade")
        self.assertEqual(code, 2, out)
        self.assertIn("needs an existing folder", out)
        self.dest.mkdir()
        write(self.dest / "mine.txt", "x\n")
        code, out = self.ng()
        self.assertEqual(code, 2, out)
        self.assertIn("is not empty", out)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ["mine.txt"])

    # ---- adopt --------------------------------------------------------------
    def test_adopt_never_overwrites(self):
        write(self.dest / "CLAUDE.md", "my own notes\n")
        write(self.dest / ".gitignore", "mine/\n")
        write(self.dest / ".claude" / "settings.json", json.dumps({"permissions": {"allow": ["Bash(my-tool)"]}}))
        code, out = self.ng("--adopt")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.text("CLAUDE.md"), "my own notes\n")
        self.assertTrue(self.text("CLAUDE.md.gold").startswith("# Fake Game (fake_game)"))
        self.assertIn("[merge] CLAUDE.md differs from the kit; wrote CLAUDE.md.gold", out)
        self.assertIn("-> keep your notes and add the kit's imports", out)
        ignore = self.text(".gitignore")
        self.assertTrue(ignore.startswith("mine/\n"))
        self.assertIn("fake_cache/", ignore)
        allow = json.loads(self.text(".claude/settings.json"))["permissions"]["allow"]
        self.assertIn("Bash(my-tool)", allow)
        self.assertIn("Bash(fake-engine *)", allow)
        self.assertTrue(self.text("tools/kit_tool.py"))
        # Second adopt: no new .gold copy, no second .gitignore block, nothing rewritten
        code, out = self.ng("--adopt")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.dest / "CLAUDE.md.gold2").exists())
        self.assertNotIn("wrote CLAUDE.md.gold", out)
        self.assertEqual(self.text(".gitignore").count(new_game.GITIGNORE_MARKER), 1)

    def test_adopt_a_fresh_scaffold_has_no_conflicts(self):
        self.new()
        code, out = self.ng("--adopt")
        self.assertEqual(code, 0, out)
        self.assertNotIn("[merge]", out)
        self.assertEqual(list(self.dest.rglob("*.gold*")), [])

    # ---- upgrade ------------------------------------------------------------
    def test_upgrade_replaces_only_untouched_files(self):
        self.new()
        write(self.dest / "docs" / "GDD.md", "# Fake Game design\nOur plan.\n")     # the game's edit
        (self.dest / "tools" / "old_tool.py").unlink()                               # deleted on purpose
        write(self.kit / "core" / "tools" / "kit_tool.py", "print('kit tool v2')\n")
        write(self.kit / "core" / "tools" / "old_tool.py", "print('old tool v2')\n")
        write(self.kit / "core" / "tools" / "new_tool.py", "print('new tool')\n")
        write(self.kit / "core" / "docs" / "GDD.md", "# {{GAME_NAME}} design\nFill this in. New section.\n")
        code, out = self.ng("--upgrade")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.text("tools/kit_tool.py"), "print('kit tool v2')\n")
        self.assertEqual(self.text("tools/new_tool.py"), "print('new tool')\n")
        self.assertFalse((self.dest / "tools" / "old_tool.py").exists(), "a deleted kit file came back")
        self.assertIn("left out 1 kit file(s) you deleted", out)
        self.assertEqual(self.text("docs/GDD.md"), "# Fake Game design\nOur plan.\n")
        self.assertEqual(self.text("docs/GDD.md.gold"), "# Fake Game design\nFill this in. New section.\n")
        meta = self.meta()
        self.assertEqual([h["mode"] for h in meta["history"]], ["new", "upgrade"])
        self.assertEqual(meta["history"][-1]["unmerged"], ["docs/GDD.md"])
        self.assertEqual(meta["files"]["tools/kit_tool.py"], sha(self.dest / "tools" / "kit_tool.py"))
        # Nothing changed in the kit since: a second upgrade conflicts on nothing and writes no .gold2
        code, out = self.ng("--upgrade")
        self.assertEqual(code, 0, out)
        self.assertNotIn("[merge]", out)
        self.assertFalse((self.dest / "docs" / "GDD.md.gold2").exists())
        self.assertEqual(self.text("docs/GDD.md"), "# Fake Game design\nOur plan.\n")

    def test_upgrade_keeps_the_recorded_name_slug_and_engine(self):
        """#97: --upgrade without the original --slug rewrote the slug; another --engine or --name was taken as is."""
        code, out = self.ng("--slug", "fg_custom")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.meta()["slug"], "fg_custom")
        claude_md = self.text("CLAUDE.md")
        self.assertEqual(claude_md.splitlines()[0], "# Fake Game (fg_custom)")
        code, out = self.ng("--upgrade")                                    # the README's command, slug forgotten
        self.assertEqual(code, 0, out)
        self.assertEqual(self.text("CLAUDE.md"), claude_md, "the slug was re-derived from --name")
        self.assertNotIn("upgraded", out)
        code, out = self.ng("--upgrade", name=None, engine=None)            # everything from the record
        self.assertEqual(code, 0, out)
        self.assertEqual(self.text("CLAUDE.md"), claude_md)
        shutil.copytree(self.kit / "engines" / "fake", self.kit / "engines" / "other")
        write(self.kit / "engines" / "other" / "engine.json", json.dumps(dict(ENGINE, id="other"), indent=2))
        before = self.text(".game-kit.json")
        for kwargs, extra, needle in (
                (dict(engine="other"), (), "made for engine 'fake'"),
                (dict(name="Other Name"), (), "named 'Fake Game'"),
                (dict(), ("--slug", "fake_game"), "slug is 'fg_custom'")):
            code, out = self.ng("--upgrade", *extra, **kwargs)
            self.assertEqual(code, 2, f"{kwargs} {extra}: {out}")
            self.assertIn(needle, out)
            self.assertEqual(self.text(".game-kit.json"), before, f"{kwargs} {extra} wrote the record")
        self.assertEqual(self.text("CLAUDE.md"), claude_md)
        code, out = self.ng("--upgrade", "--rename", engine="other")         # --rename never covers the engine
        self.assertEqual(code, 2, out)
        code, out = self.ng("--upgrade", "--rename", name="Other Name")      # a new title, same slug
        self.assertEqual(code, 0, out)
        self.assertEqual(self.text("CLAUDE.md").splitlines()[0], "# Other Name (fg_custom)")
        self.assertEqual((self.meta()["game_name"], self.meta()["slug"]), ("Other Name", "fg_custom"))
        code, out = self.ng("--rename")                                       # only with --adopt/--upgrade
        self.assertEqual(code, 2, out)

    def test_upgrade_of_a_record_without_a_slug_derives_it(self):
        """A project made before the slug was recorded keeps working: the slug comes from the recorded name."""
        self.new()
        meta = self.meta()
        del meta["slug"]
        write(self.dest / ".game-kit.json", json.dumps(meta, indent=2))
        code, out = self.ng("--upgrade", name=None, engine=None)
        self.assertEqual(code, 0, out)
        self.assertIn("records no slug", out)
        self.assertEqual(self.meta()["slug"], "fake_game")
        self.assertNotIn("upgraded", out)

    def test_upgrade_appends_only_new_gitignore_rules(self):
        self.new()
        write(self.dest / ".gitignore", self.text(".gitignore") + "game_only/\n")
        write(self.kit / "core" / ".gitignore", "*.tmp\n*.bak\n")
        code, out = self.ng("--upgrade")
        self.assertEqual(code, 0, out)
        ignore = self.text(".gitignore")
        self.assertIn("game_only/", ignore)
        self.assertEqual(ignore.count("*.bak"), 1)
        self.assertEqual(ignore.count("*.tmp"), 1)
        self.ng("--upgrade")
        self.assertEqual(self.text(".gitignore"), ignore, "a second upgrade appended again")


if __name__ == "__main__":
    unittest.main(verbosity=2)

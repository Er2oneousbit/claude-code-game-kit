#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_kit_docs.py
# Purpose : Exam for the kit's docs against the kit's own tree: claims a doc makes about what the overlays, tools and
#           folders hold, checked against what is there. Each case is named after the issue it guards.
#           - the juice and shell coverage lines (SOP-18, SOP-19, /game-feel, /game-shell, KNOWN_ISSUES) name every
#             engine, and every engine without a juice port is named where the module is promised (#103)
#           - an ENGINE.md whose overlay has no juice port says so (#103)
#           - the web and web-3d ENGINE.md layout names every src/core module the skeleton holds (#117)
# Usage   : python scripts/test_kit_docs.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only, offline, reads the kit tree read-only. The engines and their doc names are in the
#           constants block: a new overlay adds a row there, and these cases then say which docs still miss it.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import re
import sys
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
# engine id -> the regex that finds the name the docs use for it ("web" must not match "web-3d")
ENGINE_NAMES = {
    "bevy": r"Bevy",
    "cpp-sdl2": r"C\+\+/SDL2",
    "godot": r"Godot",
    "love2d": r"LÖVE",
    "rpgmaker-mz": r"RPG Maker MZ",
    "unity": r"Unity",
    "unreal": r"Unreal",
    "web": r"\bweb\b(?!-3d)",
    "web-3d": r"\bweb-3d\b",
}
GOLDEN_JUICE = "juice.json"   # a skeleton that names this file has a juice port with golden tests
SKIP_DIRS = {"node_modules", "target", "Library", "build", "dist"}
# web and web-3d src/core module -> the words its ENGINE.md layout line uses for it (None: a helper, need not be named)
WEB_CORE_WORDS = {
    "log": "log", "shake": "shake", "hitstop": "hitstop", "ease": "ease", "followCamera": "follow",
    "follow": "follow spring", "inputBuffer": "buffer", "coyoteTimer": "coyote", "spring": "spring",
    "flashLimiter": "flash limiter", "holdToggle": "hold toggle", "settings": "settings", "bindings": "bindings",
    "saveStore": "saves", "i18n": "i18n", "userData": "user data", "dialogue": "dialogue",
    "audioDirector": "audio director", "musicDirector": "music director", "audioAccess": "audio access",
    "atomicFile": None, "textStore": None, "jsonUtil": None,
}


def read(rel):
    return (KIT / rel).read_text(encoding="utf-8")


def engines():
    """Every overlay the scaffolder offers (folders starting with _ are templates)."""
    return sorted(p.parent.name for p in KIT.glob("engines/*/engine.json") if not p.parent.name.startswith("_"))


def has_juice_port(engine):
    for p in (KIT / "engines" / engine / "skeleton").rglob("*"):
        if p.is_file() and not SKIP_DIRS.intersection(p.parts) and p.suffix not in (".png", ".wav", ".ogg"):
            try:
                if GOLDEN_JUICE in p.read_text(encoding="utf-8", errors="replace"):
                    return True
            except OSError:
                continue
    return False


def section(text, start, end):
    """The text from the first match of start up to (not including) the next match of end after it."""
    m = re.search(start, text, re.M)
    if not m:
        raise AssertionError("section not found: " + start)
    rest = text[m.end():]
    n = re.search(end, rest, re.M)
    return text[m.start():m.end() + (n.start() if n else len(rest))]


def layout_entry(engine_md, name):
    """One entry of an ENGINE.md layout block: its line and the indented lines under it, whitespace folded."""
    m = re.search(r"^" + re.escape(name) + r" .*\n(?:[ \t]+\S.*\n)*", engine_md, re.M)
    if not m:
        raise AssertionError("no layout entry for " + name)
    return " ".join(m.group(0).split())


def missing_engines(text, wanted):
    return [e for e in wanted if not re.search(ENGINE_NAMES[e], text)]


class OverlayCoverageExam(unittest.TestCase):
    def test_every_engine_has_a_doc_name(self):
        self.assertEqual(sorted(ENGINE_NAMES), engines(), "add the new overlay to ENGINE_NAMES")

    def test_shell_coverage_lines_name_every_engine(self):
        # #103: the shell lines named seven of the nine engines; web-3d and RPG Maker MZ were left out
        lines = {
            "SOP-19 section 1": section(read("core/docs/sop/SOP-19-front-end-and-settings.md"),
                                        r"^## 1\. ", r"^\|"),
            "/game-shell step 1": section(read("core/.claude/skills/game-shell/SKILL.md"),
                                          r"^1\. \*\*See what is there", r"^2\. "),
            "KNOWN_ISSUES Shell screens": section(read("KNOWN_ISSUES.md"), r"^- \*\*Shell screens\*\*", r"^- "),
        }
        for where, text in lines.items():
            self.assertEqual(missing_engines(text, engines()), [], where)

    def test_engines_without_a_juice_port_are_named_where_the_module_is_promised(self):
        # #103: SOP-18 said every overlay ships the juice module; RPG Maker MZ ships none
        without = [e for e in engines() if not has_juice_port(e)]
        lines = {
            "SOP-18 step 2": section(read("core/docs/sop/SOP-18-game-feel.md"), r"^## 2\. ", r"^\|"),
            "/game-feel step 3": section(read("core/.claude/skills/game-feel/SKILL.md"), r"^3\. ", r"^4\. "),
        }
        for where, text in lines.items():
            self.assertEqual(missing_engines(text, without), [], where)

    def test_the_juice_probe_sees_a_port(self):
        self.assertTrue(has_juice_port("web"))

    def test_an_engine_without_a_juice_port_says_so_in_engine_md(self):
        # #103: the MZ ENGINE.md, which every session imports, never said it has no juice module
        quiet = [e for e in engines() if not has_juice_port(e)
                 and not re.search(r"no juice", read("engines/%s/ENGINE.md" % e), re.I)]
        self.assertEqual(quiet, [])


class LayoutExam(unittest.TestCase):
    def test_web_core_modules_are_named_in_the_layout(self):
        # #117: web-3d's layout named timers, math, RNG and state machines (none exist) and none of its 23 modules
        for engine in ("web", "web-3d"):
            line = layout_entry(read("engines/%s/ENGINE.md" % engine), "src/core/").lower()
            stems = sorted(p.stem for p in (KIT / "engines" / engine / "skeleton" / "src" / "core").glob("*.ts"))
            unknown = [s for s in stems if s not in WEB_CORE_WORDS]
            self.assertEqual(unknown, [], engine + ": a new module, add it to WEB_CORE_WORDS and the layout")
            unnamed = [s for s in stems if WEB_CORE_WORDS[s] and WEB_CORE_WORDS[s] not in line]
            self.assertEqual(unnamed, [], engine + " ENGINE.md src/core/ line")

    def test_layout_entry_takes_the_continuation_lines(self):
        text = "src/core/   one,\n            two.\nsrc/game/   three\n"
        self.assertEqual(layout_entry(text, "src/core/"), "src/core/ one, two.")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)

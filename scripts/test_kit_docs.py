#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_kit_docs.py
# Purpose : Exam for the kit's docs against the kit's own tree: claims a doc makes about what the overlays, tools and
#           folders hold, checked against what is there. Each case is named after the issue it guards.
#           - the juice and shell coverage lines (SOP-18, SOP-19, /game-feel, /game-shell, KNOWN_ISSUES) name every
#             engine, and every engine without a juice port is named where the module is promised (#103)
#           - an ENGINE.md whose overlay has no juice port says so (#103)
#           - the web and web-3d ENGINE.md layout names every src/core module the skeleton holds (#117)
#           - web and web-3d share their shell (src/shell/, data/) and src/core/ file for file, as CLAUDE.md says, so a
#             fix in one carries to the other by copying (#175)
#           - every Wavesmith command the docs give names a real subcommand, and `vectors` always says whose (#118)
#           - the PixelLab commands run live are the same in README and SOP-16, and ai-tools.md points there (#119)
#           - every source ID the shipped docs cite (E##, F##, K##) has a row in EVIDENCE.md (#120)
#           - README's SOP count, START_HERE's example count and README's "one game per engine" match the tree, and
#             every skill is named in the SOP index (in the row of the SOP it follows) (#121)
#           - no kit file an example's .game-kit.json lists is hidden by the repo's .gitignore (the MZ example's
#             GameAudio.js never reached the repo, so a fresh clone's `check` failed) (#259)
# Usage   : python scripts/test_kit_docs.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only, offline, reads the kit tree read-only (the .gitignore case asks git, skipped
#           without it). The engines and their doc names are in the
#           constants block: a new overlay adds a row there, and these cases then say which docs still miss it.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
# engine id -> the regex that finds the name the docs use for it ("web" must not match "web-3d")
ENGINE_NAMES = {
    "bevy": r"Bevy",
    "cpp-sdl2": r"C\+\+/SDL3",
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
    "flashLimiter": "flash limiter", "holdToggle": "hold toggle", "autoRepeat": "auto repeat", "settings": "settings", "bindings": "bindings",
    "saveStore": "saves", "i18n": "i18n", "userData": "user data", "dialogue": "dialogue",
    "audioDirector": "audio director", "musicDirector": "music director", "audioAccess": "audio access",
    "analog": "analog", "atomicFile": None, "textStore": None, "jsonUtil": None,
}
WAVESMITH = "core/tools/audio/wavesmith"
WAVESMITH_BUILTINS = {"list", "check", "test"}   # handled by wavesmith.py itself, not in SUBCOMMANDS
DOC_ROOTS = ["README.md", "START_HERE.md", "CLAUDE.md", "core", "engines"]
EVIDENCE = "core/docs/EVIDENCE.md"
EVIDENCE_ROOTS = ["core/docs", "core/CLAUDE.md", "core/.claude", "engines"]   # where docs cite sources
# a source ID as the docs cite it: E01..E999, F1..F99, K01..K99 (not "Kimi K3", "E2E" or "F12-key")
CITATION = re.compile(r"(?<![\w-])(E\d{2,3}|F\d{1,2}|K\d{2})(?![\w-])")
NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
SKILLS_OUTSIDE_THE_INDEX = {"adr"}   # decision records belong to no single SOP


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


def kit_markdown(roots=DOC_ROOTS):
    """(relative path, text) of every markdown file under roots (files or folders; vendored trees skipped)."""
    for root in roots:
        base = KIT / root
        paths = [base] if base.is_file() else base.rglob("*.md")
        for p in paths:
            if not SKIP_DIRS.intersection(p.relative_to(KIT).parts):
                yield p.relative_to(KIT).as_posix(), p.read_text(encoding="utf-8", errors="replace")


def wavesmith_subcommands():
    """{subcommand: module file} from the SUBCOMMANDS table in wavesmith.py (read as text, nothing imported)."""
    src = read(WAVESMITH + "/wavesmith.py")
    table = src[src.index("SUBCOMMANDS = {"):]
    table = table[:table.index("\n}\n")]
    return dict(re.findall(r'^    "([a-z]+)":\s*\("(\w+)"', table, re.M))


def example_engines():
    """{example folder: engine id} from each example's .game-kit.json."""
    import json
    found = {}
    for record in sorted(KIT.glob("examples/*/.game-kit.json")):
        found[record.parent.name] = json.loads(record.read_text(encoding="utf-8"))["engine"]
    return found


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


class SharedWebShellExam(unittest.TestCase):
    """#175: web-3d runs the web overlay's shell over Three.js; the two copies must not drift apart."""
    SHARED = ["src/shell", "src/core", "data"]
    ONLY_WEB_3D = {"src/core/follow.ts"}   # the 3D spring: web-3d's own module

    def files(self, engine):
        base = KIT / "engines" / engine / "skeleton"
        return {p.relative_to(base).as_posix(): p.read_bytes() for d in self.SHARED for p in (base / d).rglob("*")
                if p.is_file()}

    def test_the_shared_folders_are_the_same_file_for_file(self):
        web, web3d = self.files("web"), self.files("web-3d")
        self.assertEqual(sorted(set(web) ^ (set(web3d) - self.ONLY_WEB_3D)), [], "a file only one overlay has")
        self.assertEqual(sorted(f for f in web if web[f] != web3d[f]), [], "copy the change to the other overlay")

    def test_the_shell_imports_no_renderer(self):
        base = KIT / "engines" / "web" / "skeleton" / "src" / "shell"
        bad = [p.name for p in base.glob("*.ts") if re.search(r'from "(phaser|three)', p.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [], "the shell meets the renderer through host.ts only")


class CommandExam(unittest.TestCase):
    def test_wavesmith_commands_in_the_docs_exist(self):
        subs = wavesmith_subcommands()
        self.assertIn("events", subs)
        known = set(subs) | WAVESMITH_BUILTINS
        owners = {name for name, mod in subs.items() if '"vectors"' in read("%s/%s.py" % (WAVESMITH, mod))}
        self.assertEqual(owners, {"events", "music", "access", "dialogue"})
        owners |= {subs[name] + ".py" for name in list(owners)}   # the module run on its own: `music.py vectors`
        bad = []
        for rel, text in kit_markdown():
            for word in re.findall(r"wavesmith\.py ([a-z][a-z-]*)", text):
                if word not in known:
                    bad.append("%s: wavesmith.py %s" % (rel, word))
            for span in re.findall(r"`([^`\n]+)`", text):
                # #118: Bevy's FLOW.md gave a bare `vectors --write`, which wavesmith.py refuses
                m = re.match(r"(?:python \S*wavesmith\.py )?(\S+) vectors\b", span)
                if span.startswith("vectors ") or (m and m.group(1) not in owners):
                    bad.append("%s: `%s`" % (rel, span))
        self.assertEqual(bad, [])


class AgreementExam(unittest.TestCase):
    def test_pixellab_live_lists_agree(self):
        # #119: ai-tools.md said the live service was never run while README and SOP-16 listed live commands
        def spans(text):
            return {" ".join(s.split()) for s in re.findall(r"`([^`\n]+)`", text)}
        readme = section(read("README.md"), r"^\| `tools/art/pixellab\.py`", r"$")
        sop = " ".join(read("core/docs/sop/SOP-16-2d-art-pipeline.md").split())
        live_readme = spans(readme[readme.index("Live ("):readme.index("Not yet live")])
        live_sop = spans(sop[sop.index("live so far:"):sop.index("the rest **(verify)** live")])
        self.assertIn("character --legacy", live_readme)
        self.assertEqual(live_sop, live_readme, "SOP-16 and the README 'What was tested' row")
        row = section(read("core/docs/resources/ai-tools.md"), r"^\| \*\*PixelLab\*\*", r"$")
        self.assertIn("SOP-16", row)
        self.assertNotRegex(row, r"(?i)not yet run|never run", "ai-tools.md defers the live status to SOP-16")


class EvidenceExam(unittest.TestCase):
    def test_every_cited_source_has_a_ledger_row(self):
        # #120: audio.md and the E134 row cited K02, which had no row in EVIDENCE.md
        rows = set(re.findall(r"^\| ([EFK]\d+) \|", read(EVIDENCE), re.M))
        self.assertIn("K01", rows)
        missing = []
        for rel, text in kit_markdown(EVIDENCE_ROOTS):
            for tok in sorted(set(CITATION.findall(text)) - rows):
                missing.append("%s: %s" % (rel, tok))
        self.assertEqual(missing, [], "cite only IDs with a row in " + EVIDENCE)

    def test_the_citation_pattern_skips_names(self):
        self.assertEqual(CITATION.findall("(E09, F4; K02) Kimi K3, F12-key, E2E"), ["E09", "F4", "K02"])


class CountExam(unittest.TestCase):
    def test_readme_sop_count_matches_the_folder(self):
        # #121: README said 17 short SOPs while core/docs/sop held 23
        sops = sorted(p.name[:6] for p in (KIT / "core/docs/sop").glob("SOP-*.md"))
        said = re.search(r"\*\*(\d+) short SOPs:\*\*", read("README.md"))
        self.assertIsNotNone(said, "README's SOP line")
        self.assertEqual(int(said.group(1)), len(sops))
        index = read("core/docs/sop/README.md")
        self.assertEqual(sorted(set(re.findall(r"^\| (SOP-\d\d) ", index, re.M))), sops, "one index row per SOP")

    def test_example_counts_match_the_folder(self):
        # #121: START_HERE said nine small games (there are ten); README said one per engine (LÖVE has none)
        examples = example_engines()
        said = re.search(r"`examples/` folder has (\w+) small games", read("START_HERE.md"))
        self.assertIsNotNone(said, "START_HERE's examples line")
        self.assertEqual(NUMBER_WORDS.index(said.group(1)), len(examples))
        lead = section(read("README.md"), r"^## Made with the kit", r"^(<table>|\||## )")
        without = [e for e in engines() if e not in examples.values()]
        if without:
            self.assertNotIn("per engine", lead)
            self.assertEqual(missing_engines(lead, without), [], "README names the engines without an example")

    def test_every_skill_is_reachable_from_the_sop_index(self):
        # #121: SOP-16's row did not name /dotwork, which runs its largest section
        index = read("core/docs/sop/README.md")
        rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| (SOP-\d\d) .*$", index, re.M)}
        unlisted, wrong_row = [], []
        for skill in sorted((KIT / "core/.claude/skills").glob("*/SKILL.md")):
            name = skill.parent.name
            if name in SKILLS_OUTSIDE_THE_INDEX:
                continue
            if not any("`/%s`" % name in row for row in rows.values()):
                unlisted.append(name)
            for sop in set(re.findall(r"Follows? (?:`docs/sop/)?(SOP-\d\d)", skill.read_text(encoding="utf-8"))):
                if "`/%s`" % name not in rows.get(sop, ""):
                    wrong_row.append("%s (follows %s)" % (name, sop))
        self.assertEqual(unlisted, [], "skills no SOP index row names")
        self.assertEqual(wrong_row, [], "skills missing from the row of the SOP they follow")

    def test_the_skill_counts_match_the_skills_folder(self):
        # 0.14.5 verify: /file-issue made 24 skills; README and the kit's CLAUDE.md still said 23 and README's list
        # left it out
        names = sorted(p.parent.name for p in (KIT / "core/.claude/skills").glob("*/SKILL.md"))
        line = next(l for l in read("README.md").splitlines() if "skills (slash commands):" in l)
        self.assertIn("**%d skills" % len(names), line)
        self.assertEqual(sorted(re.findall(r"`/([\w-]+)`", line)), names, "README's skill list")
        self.assertIn("%d skills" % len(names), read("CLAUDE.md"))

    def test_a_check_that_compiles_shaders_names_the_bevy_exception(self):
        # second-model review: SOP-24 and /shader said `check` compiles every recipe, but Bevy compiles WESL only
        # when it builds a pipeline (`smoke --shaders`), as Bevy's ENGINE.md and SOP-24 section 3 say
        unqualified = []
        for doc in ("core/docs/sop/SOP-24-shaders.md", "core/.claude/skills/shader/SKILL.md"):
            for para in re.split(r"\n\s*\n|\n(?=\s*\d+\. )", read(doc)):
                if "dev.py check" in para and "compil" in para and "Bevy" not in para:
                    unqualified.append("%s: %s" % (doc, para.strip()[:80]))
        self.assertEqual(unqualified, [], "says `check` compiles the shaders without Bevy's exception")


@unittest.skipUnless(shutil.which("git") and (KIT / ".git").exists(), "needs git and the kit's own clone")
class ExampleTrackingExam(unittest.TestCase):
    def test_no_kit_file_of_an_example_is_git_ignored(self):
        # #259: examples/lockpick-mz/game/** was ignored but for two plugins, so GameAudio.js (a kit file since 0.8)
        # was never committed and a fresh clone of the MZ example failed `check`
        hidden = []
        for manifest in sorted((KIT / "examples").glob("*/.game-kit.json")):
            files = json.loads(manifest.read_text(encoding="utf-8")).get("files", {})
            paths = [(manifest.parent / f).relative_to(KIT).as_posix() for f in files]
            r = subprocess.run(["git", "check-ignore", "-z", "--stdin"], cwd=KIT, input="\0".join(paths).encode("utf-8"),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertIn(r.returncode, (0, 1), r.stderr.decode("utf-8", "replace"))
            hidden += [h for h in r.stdout.decode("utf-8", "replace").split("\0") if h]
        self.assertEqual(hidden, [], "kit files the root .gitignore keeps out of the repo")


class ShippedNamesExam(unittest.TestCase):
    def test_bare_file_names_in_core_docs_are_files_the_kit_ships(self):
        # 0.15.0 verify: `doctor` in every fresh scaffold warned "broken doc reference in tools/bozzetto/README.md:
        # path: rig_finish.json": the README named a report the rig step writes at run time as if it were a kit file.
        # A backticked bare file name (no slash) in core's docs must exist somewhere in core/ or an overlay, or be
        # written with its run-time folder (`rig/<route>/rig_finish.json`), which the link check reads as an example.
        sys.path.insert(0, str(KIT / "core/tools"))
        import check_links
        shipped = {p.name for root in ("core", "engines") for p, _ in check_links.walk(KIT / root)}
        unshipped = []
        for md, rel in check_links.walk(KIT / "core"):
            if md.suffix != ".md":
                continue
            for kind, target in check_links.references(check_links.read_text(md)):
                if kind == "path" and "/" not in target and target not in shipped \
                        and target not in check_links.LATER_FILES:   # CREDITS.md and co: made later, by design
                    unshipped.append(f"core/{rel}: {target}")
        self.assertEqual(unshipped, [], "bare file names core's docs name that no kit file carries")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)

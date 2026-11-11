#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# run_exams.py
# Purpose : Run the kit's tool exams (the test_*.py files under core/tools and scripts) from one table that also
#           records what each exam needs beyond the standard library, and print one line per exam: passed, failed
#           or skipped, how many unique tests ran, how long it took. The EXAMS table below is the source of truth
#           CLAUDE.md points to (`--list` prints it).
#           - unique tests are counted from unittest's verbose lines (one name per test method), never from its
#             `Ran N tests` line: a test class loaded twice once doubled that number
#           - an exam whose tool is missing (Pillow, numpy, bpy, GIMP, Inkscape, git, uv) is reported skipped
#             naming the tool, not failed; an exam that exits 2 for a missing tool counts as skipped too
#           - `--python 3.8,3.14` runs every exam once per version through `uv run --python`, or once on the
#             current interpreter when uv is not installed (a release runs the oldest supported Python this way)
#           - the live exams (a real REAPER, Aseprite, Pixelorama, ComfyUI/TRELLIS, a Blender Cycles render) run
#             only with --live; without it their env vars are hidden from the exams so nothing live runs by accident
# Usage   : python scripts/run_exams.py                       # the default set on this Python
#           python scripts/run_exams.py --python 3.8,3.14     # once per version through uv
#           python scripts/run_exams.py --only doctor --only new_game
#           python scripts/run_exams.py --changed main        # just the exams for files changed since that ref
#           python scripts/run_exams.py --live --jobs 4
#           python scripts/run_exams.py --list                # the table: name, path, needs, note
# Exit    : 0 every exam that ran passed (skips are fine), 1 an exam failed or timed out, 2 a setup problem
#           (unknown --only name, bad --changed ref, bad --python)
# Notes   : Standard library only, Python 3.8+. A kit maintainer's tool: it does not ship into games. Runs from any
#           folder (the kit is found from this file); the exams themselves run from the kit root, as CLAUDE.md
#           gives them. The Dotwork lane exams (test_uikit, test_pixelorama, ...) are loaded by test_dotwork.py,
#           so they have no row of their own; `wavesmith.py test` is the same set as the Wavesmith rows.
# Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   rows = EXAMS filtered by --only / --changed (a changed file selects the exams whose `covers` paths hold it)
#   for each Python asked (or just the current one):
#     for each row (in --jobs threads, printed in table order):
#       live-only row without --live -> SKIP
#       a tool need not on PATH -> SKIP naming it
#       pick the interpreter: the row's pinned version or the asked one through uv (`--with` for its modules),
#         else sys.executable; a module this interpreter lacks -> through uv with --with, or SKIP naming it
#       run the exam (-v for unittest rows) with the live env vars hidden unless --live
#       exit 0 -> OK (SKIP when the exam printed a [SKIP] line); exit 2 with declared needs -> SKIP; else FAIL
#       count unique test names (unittest rows) or [PASS]/[FAIL]/[ OK ] case lines (cases rows)
#   print the failed exams' output tails and a summary line per Python; exit 1 if anything failed
import argparse
import concurrent.futures
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---- constants -------------------------------------------------------------------------------------------------
KIT = Path(__file__).resolve().parents[1]
TIMEOUT_S = 1800              # one exam; the longest offline ones (Wavesmith loudness, Dotwork) take a few minutes
TAIL_LINES = 25               # of a failed exam's output, printed after the table
UV = [shutil.which("uv")] if shutil.which("uv") else None       # a command prefix, so a test can swap in a fake
PYTHON_RE = re.compile(r"^3\.\d{1,2}$")
MODULES = {"pillow": "PIL", "numpy": "numpy", "bpy": "bpy"}     # pip name -> import name
# unittest's verbose line, on 3.8 ("test_x (mod.Class) ... ok") and 3.11+ ("test_x (mod.Class.test_x) ... ok");
# with a docstring the "... ok" is on the next line, so only the name part is matched
TEST_LINE = re.compile(r"^(test\w*) \(([\w.]+)\)")
SKIPPED_RE = re.compile(r"\.\.\. skipped")
RAN_RE = re.compile(r"^Ran (\d+) tests?", re.M)
CASE_LINE = re.compile(r"^\[(?:PASS|FAIL| OK )\] ")
CASES_RE = re.compile(r"^\d+/(\d+) cases passed|^score: \d+/(\d+)", re.M)   # a cases exam's own total
SKIP_LINE = re.compile(r"^\[SKIP\] (.*)$", re.M)              # an exam that chose not to run (exit 0)
ENV_LINE = re.compile(r"^\[ENV \] (.*)$", re.M)               # an exam that exits 2 for a missing tool
OK, FAIL, SKIP = " OK ", "FAIL", "SKIP"


# ---- the table -------------------------------------------------------------------------------------------------
def tool(name):
    """A program that must be on PATH (checked here before the exam runs)."""
    return ("tool", name)


def module(pip_name):
    """A Python package the exam imports (checked on the interpreter; `uv run --with` supplies it when uv is here)."""
    return ("module", pip_name)


def exam_checks(what):
    """Something the exam looks for itself and exits 2 with an [ENV ] line when it is missing."""
    return ("exam", what)


class Exam:
    """One row: an exam file, what it needs, how it reports, which files it covers (for --changed)."""

    def __init__(self, path, note="", needs=(), style="unittest", live=False, python=None, env=(), covers=None):
        self.path = path                       # kit-relative, posix
        self.name = Path(path).stem[len("test_"):]
        self.note = note
        self.needs = tuple(needs)
        self.style = style                     # "unittest" (gets -v, names counted) or "cases" ([PASS] lines counted)
        self.live = live                       # runs only with --live
        self.python = python                   # pinned interpreter version (through uv), e.g. "3.13" for bpy
        self.env = tuple(env)                  # env vars that turn on a live part; hidden without --live
        if covers is None:
            folder = Path(path).parent
            if folder.name == "tests":
                folder = folder.parent
            covers = (folder.as_posix() + "/",)
        self.covers = tuple(covers)            # "folder/" prefixes or fnmatch patterns, kit-relative

    def modules(self):
        return [n for k, n in self.needs if k == "module"]

    def needs_text(self):
        parts = [n for k, n in self.needs]
        if self.python:
            parts = [p + " on Python " + self.python if p in self.modules() else p for p in parts]
        parts += [v + " (live part)" for v in self.env]
        if self.live:
            parts.append("--live")
        return ", ".join(parts) or "standard library"


BPY = dict(needs=(module("bpy"),), python="3.13", style="cases")   # bpy wheels lag the newest Python
EXAMS = [
    # core/tools
    Exam("core/tools/test_check_links.py", "the link checker", covers=("core/tools/check_links.py",)),
    Exam("core/tools/test_doctor.py", "the asset-log check per overlay layout", covers=("core/tools/doctor.py", "core/tools/check_links.py", "engines/*/engine.json")),
    Exam("core/tools/test_publish_check.py", "the pre-publish scan", needs=(tool("git"),), covers=("core/tools/publish_check.py",)),
    Exam("core/tools/test_fetch_asset.py", "offline (file:// URLs)", covers=("core/tools/fetch_asset.py",)),
    Exam("core/tools/test_second_opinion.py", "offline (canned CLI results)", covers=("core/tools/second_opinion.py", "core/tools/second_opinion/")),
    Exam("core/tools/test_issues.py", "offline (canned gh output)", covers=("core/tools/issues.py",)),
    Exam("core/tools/test_golden_vectors.py", "the juice and shell reference; data/golden/*.json must be current", covers=("core/tools/golden_vectors.py", "core/data/golden/")),
    Exam("core/tools/test_image_diff.py", "visual regression", covers=("core/tools/image_diff.py",)),
    Exam("core/tools/test_credits.py", "the credits builder", covers=("core/tools/credits.py",)),
    Exam("core/tools/test_yt_transcript.py", "offline (canned WebVTT, faked caption methods)", covers=("core/tools/yt_transcript.py",)),
    Exam("core/tools/test_token_audit.py", "a fake home, project and session log", covers=("core/tools/token_audit.py",)),
    Exam("core/tools/test_session_context.py", "the SessionStart hook, as Claude Code runs it", covers=("core/tools/hooks/", "core/.claude/settings.json")),
    Exam("core/tools/test_seed_sweep.py", "the seed and settings sweep (#183), a fake dev.py", covers=("core/tools/seed_sweep.py",)),
    Exam("core/tools/test_check_i18n.py", "the translation check; the overlays' French tables in the kit", covers=("core/tools/check_i18n.py", "engines/*/skeleton/data/i18n/*.json")),
    # core/tools/access
    Exam("core/tools/access/test_colour.py", "colour-blind pairs, CIEDE2000, WCAG contrast"),
    Exam("core/tools/access/test_sweep.py", "the accessibility sweep's rules, canned drive logs"),
    Exam("core/tools/access/test_presets.py", "the one-handed layouts: complete, no conflicts, one side", covers=("core/tools/access/", "core/data/input/")),
    # core/tools/cloud, shaders
    Exam("core/tools/cloud/test_ship.py", "real-OpenTofu cases when TOFU_BIN or tofu is found"),
    Exam("core/tools/shaders/test_shader_ref.py", "the shader recipes' reference; data/golden/shaders must be current", covers=("core/tools/shaders/", "core/data/golden/shaders/")),
    # core/tools/audio/wavesmith (`wavesmith.py test` runs the same files)
    Exam("core/tools/audio/wavesmith/test_wavesmith.py", "the front door: subcommands, --help, check"),
    Exam("core/tools/audio/wavesmith/test_sfx_synth.py"),
    Exam("core/tools/audio/wavesmith/test_chiptune.py"),
    Exam("core/tools/audio/wavesmith/test_wavfile.py"),
    Exam("core/tools/audio/wavesmith/test_babble.py"),
    Exam("core/tools/audio/wavesmith/test_loudness.py", "EBU Tech 3341/3342 cases, about a minute"),
    Exam("core/tools/audio/wavesmith/test_audio_events.py", "also checks data/golden/audio.json is current", covers=("core/tools/audio/wavesmith/", "core/data/golden/audio.json")),
    Exam("core/tools/audio/wavesmith/test_dialogue.py", "also checks data/golden/dialogue.json is current", covers=("core/tools/audio/wavesmith/", "core/data/golden/dialogue.json")),
    Exam("core/tools/audio/wavesmith/test_sound_sets.py"),
    Exam("core/tools/audio/wavesmith/test_music.py", "also checks data/golden/music.json is current", covers=("core/tools/audio/wavesmith/", "core/data/golden/music.json")),
    Exam("core/tools/audio/wavesmith/test_access.py", "also checks data/golden/access.json is current", covers=("core/tools/audio/wavesmith/", "core/data/golden/access.json")),
    Exam("core/tools/audio/wavesmith/test_flacfile.py", "real encoder fixtures"),
    Exam("core/tools/audio/wavesmith/test_oggvorbis.py", "libvorbis fixtures, hand-built streams"),
    Exam("core/tools/audio/wavesmith/test_audioio.py", "a stand-in ffmpeg; the real round trip runs when ffmpeg is on PATH"),
    Exam("core/tools/audio/wavesmith/test_local_sfx.py", "offline (a stand-in ComfyUI)"),
    Exam("core/tools/audio/wavesmith/test_local_tts.py", "offline (a fake TTS worker)"),
    Exam("core/tools/audio/wavesmith/test_eleven_audio.py", "offline (canned API responses)"),
    Exam("core/tools/audio/wavesmith/test_fish_tts.py", "offline (canned API responses)"),
    Exam("core/tools/audio/wavesmith/test_daw.py", "a stand-in REAPER; ReaperLiveExam runs the real one (about 3.5 min)", env=("REAPER_BIN",)),
    Exam("core/tools/audio/wavesmith/test_midifile.py"),
    # core/tools/art
    Exam("core/tools/art/test_pixellab.py", "offline (canned API responses)", covers=("core/tools/art/pixellab.py",)),
    Exam("core/tools/art/test_comfy_local.py", "offline (a stand-in ComfyUI server on 127.0.0.1)", covers=("core/tools/art/comfy_local.py",)),
    Exam("core/tools/art/dotwork/tests/test_dotwork.py", "offline; loads the lane exams (uikit, store, screens, bdf, diorama, shipped, vfx, animpolish, lighting, qapack, fonts, defaults_cvd, pixelorama); AsepriteLiveExam and PixeloramaLiveExam run the real programs",
         needs=(module("pillow"), module("numpy")), env=("ASEPRITE_BIN", "PIXELORAMA_BIN")),
    Exam("core/tools/art/test_chroma_key.py", "keying, despill, overwrite guards", needs=(module("pillow"),), style="cases", covers=("core/tools/art/chroma_key.py",)),
    Exam("core/tools/art/test_pixel_sprite.py", "the code-drawn sprites", covers=("core/tools/art/pixel_sprite.py",)),
    Exam("core/tools/art/test_gimp_batch.py", "exit 2 when GIMP is missing", needs=(exam_checks("GIMP 3"),), style="cases", covers=("core/tools/art/gimp_batch.py",)),
    Exam("core/tools/art/test_svg_export.py", "exit 2 when Inkscape is missing", needs=(exam_checks("Inkscape 1.x"),), style="cases", covers=("core/tools/art/svg_export.py",)),
    # core/tools/bozzetto
    Exam("core/tools/bozzetto/test_bozzetto.py", "a stand-in ComfyUI, a canned mesh; its Blender part runs when Blender or bpy is found (BOZZETTO_TEST_BLENDER=skip|bpy|<path>)"),
    Exam("core/tools/bozzetto/test_rig.py", "UniRig and Tripo routes offline; its Blender part runs when Blender or bpy is found"),
    Exam("core/tools/bozzetto/test_bozzetto_live.py", "one real TRELLIS.2 run (about 5 min); [SKIP] without ComfyUI", style="cases", live=True),
    # core/tools/blender (bpy on uv's Python 3.13)
    Exam("core/tools/blender/test_validate_asset.py", "builds fixtures with bpy", **BPY),
    Exam("core/tools/blender/test_prep_export.py", "builds fixtures with bpy", **BPY),
    Exam("core/tools/blender/test_render_sprites.py", "renders with Cycles on the CPU, a few minutes", live=True, **BPY),
    # scripts (the kit's own)
    Exam("scripts/test_sync_examples.py", "a fake kit and example in a temp folder", covers=("scripts/sync_examples.py", "scripts/new_game.py")),
    Exam("scripts/test_check_examples.py", "fake examples in a temp git repo", needs=(tool("git"),), covers=("scripts/check_examples.py", "engines/*/skeleton/tools/dev.py")),
    Exam("scripts/test_new_game.py", "a fake kit in a temp folder", covers=("scripts/new_game.py", "core/", "engines/", "profiles/")),
    Exam("scripts/test_codename.py", covers=("scripts/codename.py",)),
    Exam("scripts/test_dev_py.py", "every engine's dev.py, engine calls faked", covers=("engines/",)),
    Exam("scripts/test_shader_ports.py", "every engine's generated shader files current", covers=("core/tools/shaders/", "engines/")),
    Exam("scripts/test_kit_docs.py", "the docs' claims against the kit tree (one case asks git)", covers=("*.md", "core/", "engines/", "examples/*/.game-kit.json")),
    Exam("scripts/test_run_exams.py", "this runner, on fake exams in a temp folder", covers=("scripts/run_exams.py",)),
]
# exam files in the tree that need no row: loaded by another exam
LOADED_BY_ANOTHER = {
    "core/tools/art/dotwork/tests/test_%s.py" % n for n in
    ("uikit", "store", "screens", "bdf", "diorama", "shipped", "vfx", "animpolish", "lighting", "qapack", "fonts",
     "defaults_cvd", "pixelorama")
}
EXAM_ROOTS = ("core/tools", "scripts")


# ---- selection ---------------------------------------------------------------------------------------------------
def select_only(rows, names):
    """Rows named by --only (the name, the path, or a path suffix). Raises ValueError on an unknown name."""
    chosen = []
    for want in names:
        want = want.replace("\\", "/")
        hits = [r for r in rows if want in (r.name, r.path) or r.path.endswith("/" + want)]
        if not hits:
            raise ValueError("no exam named %r (have: %s)" % (want, ", ".join(r.name for r in rows)))
        chosen += [r for r in hits if r not in chosen]
    return chosen


def covers(row, rel):
    if rel == row.path:
        return True
    for pat in row.covers:
        if pat.endswith("/"):
            if rel.startswith(pat):
                return True
        elif fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(Path(rel).name, pat):
            return True
    return False


def select_changed(rows, files):
    """Rows whose covers hold one of the changed files (kit-relative posix paths)."""
    return [r for r in rows if any(covers(r, f) for f in files)]


def changed_files(ref, kit):
    """Files changed since ref in the working tree (committed, staged or not) plus untracked ones; None when
    git refuses (bad ref, not a clone)."""
    kw = dict(cwd=str(kit), capture_output=True, encoding="utf-8", errors="replace")
    diff = subprocess.run(["git", "diff", "--name-only", ref, "--"], **kw)
    if diff.returncode != 0:
        return None
    others = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], **kw)
    names = diff.stdout.splitlines() + (others.stdout.splitlines() if others.returncode == 0 else [])
    return sorted({n.strip().replace("\\", "/") for n in names if n.strip()})


def untracked_exams(kit=None, rows=None):
    """test_*.py files under the exam roots that have no row and are not loaded by another exam."""
    kit = kit or KIT
    known = {r.path for r in (EXAMS if rows is None else rows)} | LOADED_BY_ANOTHER
    found = []
    for root in EXAM_ROOTS:
        if not (kit / root).is_dir():
            continue
        for p in (kit / root).rglob("test_*.py"):
            rel = p.relative_to(kit).as_posix()
            if rel not in known:
                found.append(rel)
    return sorted(found)


# ---- running -----------------------------------------------------------------------------------------------------
class Result:
    def __init__(self, row, status, detail="", tests=0, skipped=0, seconds=0.0, output="", note=""):
        self.row, self.status, self.detail = row, status, detail
        self.tests, self.skipped, self.seconds, self.output, self.note = tests, skipped, seconds, output, note

    def line(self):
        head = "[%s] %-52s" % (self.status, self.row.path)
        if self.status == SKIP:
            return "%s %s" % (head, self.detail)
        body = "%4d tests" % self.tests if self.row.style == "unittest" else "%4d cases" % self.tests
        if self.skipped:
            body += " (%d skipped)" % self.skipped
        tail = "  %s" % self.detail if self.detail else ""
        note = "  [%s]" % self.note if self.note else ""
        return "%s %s %7.1f s%s%s" % (head, body, self.seconds, tail, note)


def uv_prefix(version, modules):
    cmd = list(UV) + ["run", "--no-project", "--python", version]
    for m in modules:
        cmd += ["--with", m]
    return cmd + ["python"]


def missing_modules(interpreter, modules, cache):
    """pip names of `modules` the interpreter cannot import (one probe per interpreter and module set)."""
    if not modules:
        return []
    key = (interpreter, tuple(modules))
    if key not in cache:
        probe = "\n".join("import " + MODULES.get(m, m) for m in modules)
        r = subprocess.run([interpreter, "-c", probe], capture_output=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            cache[key] = []
        else:
            cache[key] = [m for m in modules
                          if subprocess.run([interpreter, "-c", "import " + MODULES.get(m, m)],
                                            capture_output=True).returncode != 0] or list(modules)
    return cache[key]


def interpreter_for(row, version, cache):
    """(command prefix, note) for this row on the asked version, or (None, why it is skipped)."""
    want = row.python or version
    mods = row.modules()
    if want is None:
        missing = missing_modules(sys.executable, mods, cache)
        if not missing:
            return [sys.executable], ""
        if not UV:
            return None, "needs %s (pip install it, or install uv)" % ", ".join(missing)
        want = "%d.%d" % sys.version_info[:2]
    if not UV:
        return None, "needs uv to run Python %s with %s" % (want, ", ".join(mods) or "the standard library")
    return uv_prefix(want, mods), "Python " + want


def count_tests(row, text):
    """(unique tests or cases, skipped tests). Never `Ran N` unless no verbose line was printed at all."""
    if row.style == "cases":
        m = CASES_RE.search(text)          # the exam's own total when it prints one, else its case lines
        return (int(m.group(1) or m.group(2)) if m else len([ln for ln in text.splitlines() if CASE_LINE.match(ln)])), 0
    names = set()
    for ln in text.splitlines():
        m = TEST_LINE.match(ln)
        if m:
            method, qual = m.group(1), m.group(2)
            names.add(qual if qual.endswith("." + method) else qual + "." + method)
    if not names:
        m = RAN_RE.search(text)
        return (int(m.group(1)) if m else 0), len(SKIPPED_RE.findall(text))
    return len(names), len(SKIPPED_RE.findall(text))


def reason_from(text, fallback):
    """The exam's own [ENV ] or [SKIP] line when it printed one, else fallback."""
    m = ENV_LINE.search(text) or SKIP_LINE.search(text)
    return m.group(1).strip()[:100] if m else fallback


def run_one(row, version, opts, cache, hidden_env, first_pass=True):
    """Run one exam on one interpreter and judge it."""
    if row.live and not opts.live:
        return Result(row, SKIP, "live exam: runs with --live")
    if row.python and version and row.python != version and not first_pass:
        return Result(row, SKIP, "pinned to Python %s: ran on the first pass" % row.python)
    for kind, name in row.needs:
        if kind == "tool" and not shutil.which(name):
            return Result(row, SKIP, "needs %s (not on PATH)" % name)
    prefix, note = interpreter_for(row, version, cache)
    if prefix is None:
        return Result(row, SKIP, note)
    cmd = prefix + ["-B", str(KIT / row.path)] + (["-v"] if row.style == "unittest" else [])
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    unset = []
    for var in hidden_env:
        if opts.live:
            if var in row.env and not env.get(var):
                unset.append(var)
        else:
            env.pop(var, None)
    if unset:
        note = (note + "; " if note else "") + "%s unset: live part skipped" % ", ".join(unset)
    if opts.debug:
        print("[debug] " + " ".join(cmd), flush=True)
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, cwd=str(KIT), env=env, capture_output=True, encoding="utf-8", errors="replace",
                           timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return Result(row, FAIL, "timed out after %d s" % TIMEOUT_S, seconds=time.monotonic() - t0, output=out,
                      note=note)
    took = time.monotonic() - t0
    out = (r.stdout or "") + (r.stderr or "")
    tests, skipped = count_tests(row, out)
    if r.returncode == 0:
        m = SKIP_LINE.search(out)
        if m and tests == 0:
            return Result(row, SKIP, m.group(1).strip()[:100], seconds=took, output=out, note=note)
        return Result(row, OK, "", tests, skipped, took, out, note)
    if r.returncode == 2 and row.needs:
        return Result(row, SKIP, reason_from(out, "needs " + row.needs_text()) + " (exam exit 2)", seconds=took,
                      output=out, note=note)
    return Result(row, FAIL, "exit %d" % r.returncode, tests, skipped, took, out, note)


def run_rows(rows, version, opts, hidden_env, first_pass=True):
    """Every row on one interpreter, --jobs at a time, lines printed in table order. -> (results, wall seconds)"""
    cache, lock, results = {}, threading.Lock(), {}
    printed = [0]
    t0 = time.monotonic()

    def flush():
        with lock:
            while printed[0] < len(rows) and printed[0] in results:
                res = results[printed[0]]
                print(res.line(), flush=True)
                if opts.debug and res.output:
                    print(res.output.rstrip())
                printed[0] += 1

    def job(i):
        results[i] = run_one(rows[i], version, opts, cache, hidden_env, first_pass)
        flush()

    if opts.jobs <= 1:
        for i in range(len(rows)):
            job(i)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=opts.jobs) as pool:
            list(pool.map(job, range(len(rows))))
    return [results[i] for i in range(len(rows))], time.monotonic() - t0


def summarize(results, label, wall):
    failed = [r for r in results if r.status == FAIL]
    for res in failed:
        print("---- %s (%s) ----" % (res.row.path, res.detail))
        lines = res.output.rstrip().splitlines()
        print("\n".join(lines[-TAIL_LINES:]) if lines else "(no output)")
    passed = sum(1 for r in results if r.status == OK)
    skipped = sum(1 for r in results if r.status == SKIP)
    tests = sum(r.tests for r in results if r.status == OK)
    print("[%s] %s: %d exams, %d passed, %d failed, %d skipped; %d unique tests; %.0f s"
          % (FAIL if failed else OK, label, len(results), passed, len(failed), skipped, tests, wall), flush=True)
    return not failed


def print_table(rows):
    print("%-14s %-52s %s" % ("name", "exam", "needs; note"))
    for r in rows:
        print("%-14s %-52s %s%s" % (r.name, r.path, r.needs_text(), "; " + r.note if r.note else ""))
    extra = untracked_exams()
    for rel in extra:
        print("[warn] no row for %s: add it to EXAMS (or LOADED_BY_ANOTHER)" % rel)


# ---- main --------------------------------------------------------------------------------------------------------
def parse_args(argv):
    ap = argparse.ArgumentParser(
        description="Run the kit's tool exams from one table and print one line per exam (pass/fail/skipped, "
                    "unique tests, time). Exit 0 when every exam that ran passed, 1 when one failed, 2 on a setup "
                    "problem.",
        epilog="Skipped is not failed: an exam whose tool is missing (Pillow, numpy, bpy, GIMP, Inkscape, git, uv) "
               "says so and the run still exits 0. The exams run from the kit root with the live env vars "
               "(REAPER_BIN, ASEPRITE_BIN, PIXELORAMA_BIN) hidden unless --live is given.")
    ap.add_argument("--only", action="append", default=[], metavar="NAME",
                    help="run just this exam (its name as --list shows it, or its path); repeatable")
    ap.add_argument("--changed", metavar="REF",
                    help="run just the exams covering files changed since this git ref (plus untracked files)")
    ap.add_argument("--python", metavar="VERSIONS",
                    help="comma-separated versions, e.g. 3.8,3.14: run everything once per version through "
                         "`uv run --python`; without uv, once on this interpreter")
    ap.add_argument("--live", action="store_true",
                    help="also run the live exams (a real ComfyUI/TRELLIS, a Cycles render) and pass REAPER_BIN, "
                         "ASEPRITE_BIN and PIXELORAMA_BIN through to the exams that have a live part")
    ap.add_argument("--jobs", type=int, default=1, metavar="N", help="exams run at once (default 1)")
    ap.add_argument("--list", action="store_true", help="print the table (name, path, needs, note) and exit")
    ap.add_argument("--debug", action="store_true", help="print every command and every exam's full output")
    return ap.parse_args(argv)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    opts = parse_args(argv)
    rows = list(EXAMS)
    if opts.list:
        print_table(rows)
        return 0
    try:
        if opts.only:
            rows = select_only(rows, opts.only)
        if opts.changed:
            files = changed_files(opts.changed, KIT)
            if files is None:
                raise ValueError("git could not diff against %r (is it a ref of this clone?)" % opts.changed)
            rows = select_changed(rows, files)
            print("[info] %d file(s) changed since %s: %d exam(s) cover them" % (len(files), opts.changed, len(rows)))
        versions = [None]
        if opts.python is not None:
            versions = [v.strip() for v in opts.python.split(",") if v.strip()]
            bad = [v for v in versions if not PYTHON_RE.match(v)]
            if bad or not versions:
                raise ValueError("--python wants versions like 3.8,3.14, not %r" % opts.python)
            if not UV:
                print("[warn] uv not found: running once on this interpreter (Python %d.%d) instead of %s"
                      % (sys.version_info[0], sys.version_info[1], ", ".join(versions)))
                versions = [None]
        if opts.jobs < 1:
            raise ValueError("--jobs wants a number of 1 or more")
    except ValueError as exc:
        print("[error] %s" % exc, file=sys.stderr)
        return 2
    if not rows:
        print("[info] nothing to run")
        return 0
    hidden_env = sorted({v for r in EXAMS for v in r.env})
    all_ok = True
    for n, version in enumerate(versions):
        label = ("Python %s via uv" % version) if version else "Python %d.%d" % sys.version_info[:2]
        if len(versions) > 1 or version:
            print("== %s ==" % label)
        try:
            results, wall = run_rows(rows, version, opts, hidden_env, first_pass=(n == 0))
        except KeyboardInterrupt:
            print("[error] interrupted", file=sys.stderr)
            return 1
        all_ok = summarize(results, label, wall) and all_ok
    extra = untracked_exams()
    for rel in extra:
        print("[warn] no row for %s: add it to EXAMS (or LOADED_BY_ANOTHER)" % rel)
    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:   # noqa: BLE001  (a maintainer's tool: say what broke, traceback only with --debug)
        if "--debug" in sys.argv:
            raise
        print("[error] %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        sys.exit(2)

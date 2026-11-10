#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# check_examples.py
# Purpose : Kit maintenance: run every example's tools/doctor.py and tools/dev.py check, test and smoke in place, and
#           print one table of the results (#159). Replaces the one-off shell scripts of earlier release and review
#           passes; pairs with scripts/sync_examples.py (sync first, then check).
#           - the engine comes from each example's .game-kit.json
#           - the toolchain comes from the environment variables the example's own dev.py documents (its header's
#             "Env" lines; "optional" ones are not required) or the program dev.py falls back to on PATH; when it is
#             missing, check/test/smoke are reported SKIP naming the variable to set (doctor still runs)
#           - Godot examples get GUT for the run: copied from GUT_DIR (a folder holding addons/gut/, or the gut
#             folder itself) into addons/gut/ and removed afterwards; without GUT_DIR their `test` is SKIP
#           - an exit recorded in EXPECTED for that example and command (a known gap, such as Lockpick's smoke
#             without RPG Maker MZ's own files) is shown as expected, not as a failure
#           - after the run, any change under examples/ that git sees and that was not there before (a modified
#             tracked file, a new file that is not ignored) fails the run
# Usage   : python scripts/check_examples.py                          # every example, every command
#           python scripts/check_examples.py --only coyote-hop --only rune-delve
#           python scripts/check_examples.py --engine godot --skip-smoke
#           python scripts/check_examples.py --timeout 900 --debug      # per-command limit; --debug prints output
#           python scripts/check_examples.py --list                     # examples, engines, toolchain found or not
# Env     : GUT_DIR  a GUT release's addons/gut/ (or the folder holding addons/), for the Godot examples' tests
#           plus each engine's own variables, as its dev.py documents them: GODOT_BIN, LOVE_BIN, UNITY_EDITOR,
#           UE_ROOT, VCPKG_ROOT (and cmake on PATH), cargo for Bevy (CARGO_TARGET_DIR optional), node and npm
# Exit    : 0 every command that ran passed or gave its expected exit (skips are fine), 1 a command failed or timed
#           out, or examples/ was left with changes, 2 usage or setup problem (unknown --only name or --engine,
#           no examples folder, git missing or not a git checkout, GUT_DIR without GUT in it)
# Notes   : Standard library only, Python 3.8+. A kit maintainer's tool: it does not ship into games. Commands run
#           one after another (engines share GPUs, caches and editors). Unity and Unreal need their first import or
#           C++ build in a fresh checkout, which takes minutes; the C++ example needs a short path on Windows
#           (vcpkg). The examples' own heavy folders (node_modules, .godot, Library, Binaries ...) are gitignored and
#           stay after the run.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   examples = examples/*/.game-kit.json, filtered by --only / --engine
#   baseline = git status --porcelain of examples/
#   for each example:
#     doctor -> python tools/doctor.py
#     missing = the toolchain check (dev.py's required Env variables, else its PATH fallback; tools it always needs)
#     Godot: GUT_DIR set -> copy GUT into addons/gut/ (only when the example has none), else test is SKIP
#     for command in check, test, smoke (no smoke with --skip-smoke):
#       missing -> SKIP naming the variable; else run python tools/dev.py <command> with the per-command timeout
#       result = exit code, compared with EXPECTED; keep the last [ OK ] / [FAIL] / [error] line
#     finally remove the GUT copy
#   print the table, then the last line of every command that did not pass
#   new = git status now - baseline -> [FAIL] when not empty
#   exit 1 when a command failed or new is not empty, else 0
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# ---- constants -------------------------------------------------------------------------------------------------
KIT = Path(__file__).resolve().parents[1]
EXAMPLES = KIT / "examples"
COMMANDS = ("doctor", "check", "test", "smoke")
TIMEOUT_S = 1800                 # one command; a fresh Unity import or Unreal C++ build takes minutes
KILL_TIMEOUT_S = 15
GUT_ENV = "GUT_DIR"
GUT_ADDON = "addons/gut"
GUT_MARK = "gut_cmdln.gd"        # the file dev.py test looks for (addons/gut/gut_cmdln.gd)
# What dev.py falls back to on PATH when its variable is unset, and programs it always needs (not in its Env lines)
PATH_FALLBACK = {"godot": ("godot", "godot4"), "love2d": ("lovec", "love")}
TOOLS = {"cpp-sdl2": ("cmake",), "bevy": ("cargo",), "web": ("node", "npm"), "web-3d": ("node", "npm"),
         "rpgmaker-mz": ("node", "npm")}
TOOL_HINT = {"cmake": "put cmake on PATH (VS Build Tools ship one: Common7/IDE/CommonExtensions/Microsoft/CMake/"
                      "CMake/bin)",
             "cargo": "install Rust (rustup) or put %USERPROFILE%/.cargo/bin on PATH",
             "node": "install Node.js", "npm": "install Node.js (npm comes with it)"}
# Known gaps: (example, command) -> (exit code, why). Shown as expected instead of failed.
EXPECTED = {
    ("lockpick-mz", "smoke"): (2, "RPG Maker MZ's own files are not in the repo (dev.py setup --from <an MZ project>)"),
}
RESULT_LINE = re.compile(r"^\s*\[( OK |FAIL|error|ERROR|SKIP|WARN)\]")
ENV_BLOCK = re.compile(r"^#\s*Env\s*:(.*)$")
ENV_ITEM = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})\b\s*(.*)$")
DEBUG = False


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


# ---- toolchains ------------------------------------------------------------------------------------------------
def documented_env(dev_py):
    """[(name, optional?)] from the "# Env :" lines of a dev.py header (the first line and its indented
    continuation lines). An item whose description starts with "optional" is not required."""
    try:
        lines = dev_py.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    found, inside = [], False
    for line in lines[:80]:
        m = ENV_BLOCK.match(line)
        if m:
            inside, rest = True, m.group(1)
        elif inside and re.match(r"^#\s{3,}\S", line) and not re.match(r"^#\s*\w+\s*:", line):
            rest = line[1:]
        else:
            if inside:
                break
            continue
        item = ENV_ITEM.match(rest)
        if item:
            found.append((item.group(1), item.group(2).lower().startswith("optional")))
    return found


def on_path(name):
    """A program on PATH; cargo also in ~/.cargo/bin (Bevy's dev.py looks there too)."""
    hit = shutil.which(name)
    if hit or name != "cargo":
        return hit
    home = Path.home() / ".cargo" / "bin" / ("cargo.exe" if os.name == "nt" else "cargo")
    return str(home) if home.is_file() else None


def missing_toolchain(example, engine):
    """None when the example's toolchain is here, else what to set or install."""
    for name, optional in documented_env(example / "tools" / "dev.py"):
        if optional:
            continue
        value = os.environ.get(name, "")
        if value and Path(value).exists():
            continue
        if any(on_path(p) for p in PATH_FALLBACK.get(engine, ())):
            continue
        if value:
            return f"{name}={value} does not exist"
        return f"set {name}"
    for tool in TOOLS.get(engine, ()):
        if not on_path(tool):
            return TOOL_HINT.get(tool, f"put {tool} on PATH")
    return None


# ---- GUT for the Godot examples ----------------------------------------------------------------------------------
def gut_source():
    """(folder to copy as addons/gut, None) from GUT_DIR, (None, None) when unset, (None, error) when wrong."""
    given = os.environ.get(GUT_ENV, "")
    if not given:
        return None, None
    base = Path(given)
    for cand in (base, base / "gut", base / GUT_ADDON):
        if (cand / GUT_MARK).is_file():
            return cand, None
    return None, f"{GUT_ENV}={given} holds no {GUT_MARK} (point it at a GUT release's addons/gut/)"


def add_gut(example, source):
    """Copy GUT into the example. Returns what to remove afterwards ([] when the example has its own GUT)."""
    target = example / GUT_ADDON
    if target.exists():
        dbg(f"{example.name}: has its own {GUT_ADDON}, left alone")
        return []
    remove = [target]
    if not target.parent.exists():
        remove.append(target.parent)          # addons/ too, when this run made it (only if empty afterwards)
    shutil.copytree(source, target)
    return remove


def remove_gut(paths):
    """Undo add_gut: GUT's folder, then addons/ when it is empty."""
    for p in paths:
        if p.name == "gut":
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    left = [p for p in paths if p.name == "gut" and p.exists()]
    if left:
        print(f"[warn] could not remove {left[0]} (close Godot), remove it by hand")


# ---- running ---------------------------------------------------------------------------------------------------
def kill_tree(proc):
    """End a timed-out command and everything it started (an engine editor must not outlive it)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=KILL_TIMEOUT_S)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run(cmd, cwd, timeout):
    """(exit code or None on a timeout, output, seconds)."""
    dbg(f"{cwd.name}: {' '.join(str(c) for c in cmd)}")
    start = time.time()
    try:
        proc = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8",
                                errors="replace", start_new_session=os.name != "nt")
    except OSError as exc:
        return 2, f"[error] cannot run {cmd[0]}: {exc}", 0.0
    try:
        out, _ = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, _ = proc.communicate(timeout=KILL_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            out = ""
        rc = None
    if DEBUG:
        print(out or "")
    return rc, out or "", time.time() - start


def last_result(out):
    """The last [ OK ] / [FAIL] / [error] line of a command's output, else its last line."""
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    hits = [l for l in lines if RESULT_LINE.match(l)]
    fails = [l for l in hits if not l.startswith(("[ OK ]", "[SKIP]", "[WARN]"))]
    pick = (fails or hits or lines or [""])[-1]
    return pick[:160]


class Cell:
    """One command's result: status OK, FAIL, SKIP or EXP (its expected exit)."""

    def __init__(self, status, rc=None, line="", seconds=0.0):
        self.status, self.rc, self.line, self.seconds = status, rc, line, seconds

    def text(self):
        if self.status == "SKIP":
            return "SKIP"
        if self.rc is None:
            return "T/O FAIL"
        return f"{self.rc} {'exp' if self.status == 'EXP' else 'FAIL' if self.status == 'FAIL' else ''}".strip()


def judge(name, command, rc, out, seconds):
    """A Cell from an exit code, with EXPECTED applied."""
    line = last_result(out) if rc is not None else "timed out (raise --timeout?)"
    want = EXPECTED.get((name, command))
    if want and rc == want[0]:
        return Cell("EXP", rc, f"{line}  [expected: {want[1]}]", seconds)
    if want:
        return Cell("FAIL", rc, f"{line}  [expected exit {want[0]}]", seconds)
    return Cell("OK" if rc == 0 else "FAIL", rc, line, seconds)


def check_example(example, engine, commands, timeout, gut):
    """{command: Cell} for one example."""
    cells = {}
    rc, out, sec = run([sys.executable, "tools/doctor.py"], example, timeout)
    cells["doctor"] = judge(example.name, "doctor", rc, out, sec)
    missing = missing_toolchain(example, engine)
    added = []
    try:
        if engine == "godot" and gut and not missing:
            added = add_gut(example, gut)
        for command in commands:
            if command == "doctor":
                continue
            if missing:
                cells[command] = Cell("SKIP", line=missing)
                continue
            if engine == "godot" and command == "test" and not gut and not (example / GUT_ADDON).exists():
                cells[command] = Cell("SKIP", line=f"set {GUT_ENV} (a GUT release's addons/gut/)")
                continue
            rc, out, sec = run([sys.executable, "tools/dev.py", command], example, timeout)
            cells[command] = judge(example.name, command, rc, out, sec)
            print(f"  {example.name:<18} {command:<7} {cells[command].text():<8} {sec:6.0f} s  {cells[command].line}")
    finally:
        remove_gut(added)
    return cells


# ---- the examples folder -----------------------------------------------------------------------------------------
def find_examples(root, only, engines):
    """[(folder, engine)] sorted by name; raises ValueError naming an unknown --only or --engine."""
    found = []
    for meta in sorted(root.glob("*/.game-kit.json")):
        try:
            engine = json.loads(meta.read_text(encoding="utf-8")).get("engine", "")
        except (OSError, ValueError) as exc:
            raise ValueError(f"{meta}: {exc}")
        found.append((meta.parent, engine))
    if only:
        unknown = sorted(set(only) - {p.name for p, _ in found})
        if unknown:
            raise ValueError(f"not an example: {', '.join(unknown)} (have: {', '.join(p.name for p, _ in found)})")
        found = [(p, e) for p, e in found if p.name in only]
    if engines:
        unknown = sorted(set(engines) - {e for _, e in found})
        if unknown:
            raise ValueError(f"no example uses engine {', '.join(unknown)}")
        found = [(p, e) for p, e in found if e in engines]
    return found


def git_changes(root):
    """The set of `git status --porcelain` lines under root (new untracked files listed one by one), or None when
    git cannot answer (not installed, not a checkout)."""
    git = shutil.which("git")
    if not git:
        return None
    try:
        res = subprocess.run([git, "status", "--porcelain", "--untracked-files=all", "--", "."], cwd=str(root),
                             stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace",
                             timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        dbg(res.stderr.strip())
        return None
    return {l for l in res.stdout.splitlines() if l.strip()}


def print_table(rows, commands):
    """One line per example, then the last line of every command that did not pass."""
    width = max([len("example")] + [len(p.name) for p, _, _ in rows])
    print()
    print(f"{'example':<{width}}  {'engine':<12}" + "".join(f"{c:<10}" for c in commands))
    for p, engine, cells in rows:
        print(f"{p.name:<{width}}  {engine:<12}" + "".join(f"{cells[c].text() if c in cells else '-':<10}"
                                                           for c in commands))
    notes = [(p.name, c, cells[c]) for p, _, cells in rows for c in commands
             if c in cells and cells[c].status != "OK"]
    if notes:
        print()
        for name, command, cell in notes:
            print(f"  {name} {command}: [{cell.status}] {cell.line}")


def list_examples(found):
    for p, engine in found:
        missing = missing_toolchain(p, engine)
        print(f"{p.name:<20} {engine:<12} {'toolchain found' if not missing else 'SKIP: ' + missing}")
    gut, err = gut_source()
    print(f"[info] {GUT_ENV}: {err or gut or 'not set (the Godot examples test is SKIP)'}")
    return 0


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="Run every example's doctor, check, test and smoke in place and print one table. Each example's "
                    "engine comes from its .game-kit.json; a missing toolchain is SKIP naming the variable to set.",
        epilog=f"Env: {GUT_ENV} (a GUT release's addons/gut/, for the Godot examples' tests) and each engine's own "
               "variables as its dev.py documents them (GODOT_BIN, UNITY_EDITOR, UE_ROOT, VCPKG_ROOT, LOVE_BIN ...). "
               "Exit codes: 0 all passed or gave their expected exit (skips are fine), 1 a command failed or timed "
               "out or examples/ was left with changes, 2 usage or setup problem.")
    ap.add_argument("--only", action="append", default=[], metavar="NAME",
                    help="an example folder name (repeat for more); default: every example")
    ap.add_argument("--engine", action="append", default=[], metavar="ID",
                    help="only examples on this engine (repeat for more), e.g. godot, unity, web")
    ap.add_argument("--skip-smoke", action="store_true", help="doctor, check and test only")
    ap.add_argument("--timeout", type=int, default=TIMEOUT_S, metavar="SECONDS",
                    help=f"limit for each command (default {TIMEOUT_S}); a command over it is killed and fails")
    ap.add_argument("--examples", default=str(EXAMPLES), metavar="DIR",
                    help="the examples folder (default: this kit's examples/); it must be inside a git checkout")
    ap.add_argument("--list", action="store_true", help="list the examples, their engines and toolchains, run nothing")
    ap.add_argument("--debug", action="store_true", help="print every command and its whole output")
    args = ap.parse_args(argv)
    DEBUG = args.debug
    root = Path(args.examples).resolve()
    if not root.is_dir():
        print(f"[error] no examples folder at {root}", file=sys.stderr)
        return 2
    if args.timeout < 1:
        print("[error] --timeout must be at least 1 second", file=sys.stderr)
        return 2
    try:
        found = find_examples(root, args.only, args.engine)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    if not found:
        print(f"[error] no example with a .game-kit.json in {root}", file=sys.stderr)
        return 2
    if args.list:
        return list_examples(found)
    gut, err = gut_source()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    before = git_changes(root)
    if before is None:
        print(f"[error] git cannot read {root}: the final check needs git and a checkout", file=sys.stderr)
        return 2
    if before:
        print(f"[info] examples/ already has {len(before)} change(s) before the run; only new ones count")
    commands = [c for c in COMMANDS if not (args.skip_smoke and c == "smoke")]
    rows = []
    for example, engine in found:
        print(f"[info] {example.name} ({engine})")
        rows.append((example, engine, check_example(example, engine, commands, args.timeout, gut)))
    print_table(rows, commands)
    failed = sum(1 for _, _, cells in rows for c in cells.values() if c.status == "FAIL")
    after = git_changes(root)
    new = sorted((after or set()) - before) if after is not None else ["(git could not read examples/ after the run)"]
    if new:
        print(f"\n[FAIL] the run left {len(new)} change(s) in examples/ (git status):")
        for line in new[:30]:
            print(f"  {line}")
    else:
        print("\n[ OK ] examples/ has no new changes (git status)")
    ran = sum(1 for _, _, cells in rows for c in cells.values() if c.status != "SKIP")
    skipped = sum(1 for _, _, cells in rows for c in cells.values() if c.status == "SKIP")
    print(f"[{'FAIL' if failed or new else ' OK '}] {len(rows)} example(s): {ran} command(s) ran, {failed} failed, "
          f"{skipped} skipped")
    return 1 if failed or new else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dev.py  (Godot 4 edition)
# Purpose : The ONE command wrapper for this project. Same subcommands on every
#           engine in the Claude Code Game Kit, so humans and Claude never guess flags.
# Usage   : python tools/dev.py <command> [options]      (add -h for help)
#             import   build the .godot/ import cache (check/test/smoke also run it when needed)
#             check    parse all .gd files for errors
#             test     run GUT unit tests headless
#             smoke    boot the game headless for N frames, fail on errors; --screenshot FILE and --record DIR then
#                      capture it in a real window (tools/capture.gd; GIF: tools/art/frames_to_gif.py)
#             run      launch the game window
#             build    export a release build (--preset Windows Desktop|Linux|Web, from the shipped export_presets.cfg)
#             clean    remove build output (--deep also removes .godot/)
#             doctor   verify the local environment
# Env     : GODOT_BIN  path to the Godot executable (else `godot` on PATH)
# Exit    : 0 ok, 1 task failed, 2 environment/usage problem
# Notes   : Flags mirror the Godot 4 CLI; every command was run against Godot 4.7.2 (see the change log below; build
#           exported Windows, Linux and Web); if a flag errors on another version, run `godot --help` and adjust
#           the constants near the top. Python 3.8+, standard library only.
#
# Pseudocode:
#   parse args -> locate godot binary -> build command list -> run, stream output
#   -> scan output for error markers (Godot often exits 0 even on script errors)
#   -> return 0/1/2
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-19 with Claude (Opus 5.5, claude-opus-5-5): global options accepted after the
#           subcommand (dev.py build --debug)
# Updated : 2026-10-20 with Claude (Opus 5.5, claude-opus-5-5): first run against real Godot 4.7.2;
#           `check` now uses tools/check_scripts.gd so autoloads resolve, skips tests/ without GUT
# Updated : 2026-10-20 (audit pass 2): UTF-8 decoding of engine output; check/test/smoke re-import
#           when the class_name set changed or the cache is missing; test fails when GUT skipped
#           files or ran nothing; import fails on asset errors; check counts scripts broken by a
#           dependency; doctor refuses Godot < 4.3; build --out is relative to the project
# Updated : 2026-10-21 (audit pass 3): stdout/stderr and captured tool output are UTF-8 (Windows
#           pipes defaulted to cp1252 and crashed on non-Latin paths, names and log lines)
# Updated : 2026-10-21 (audit pass 4): timeouts on import/check/test/smoke (the tail of a hung run is
#           printed), --frames bounded, folder/.app/non-executable GODOT_BIN caught, clean verifies
#           deletion, --debug keeps exit 2
# Updated : 2026-10-30 with Claude (Opus 5.5, claude-opus-5-5): a timeout kills the whole process tree
#           (taskkill /T, or the process group), then waits at most KILL_TIMEOUT_S for the pipe
# ---------------------------------------------------------------------------
import argparse
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---- Tunables / constants (edit here if your Godot version differs) ----------
SMOKE_FRAMES = 120                       # frames to run in `smoke`
BOOT_MARKER = "BOOT_OK"                  # printed by scripts/game/main.gd
ERROR_PATTERNS = [                       # any match in output = failure
    r"SCRIPT ERROR", r"Parse Error", r"\bERROR:", r"\[ERROR\]", r"Failed to load",
]
SKIP_DIRS = {".godot", "addons", "build", ".git"}
GUT_CMDLN = "addons/gut/gut_cmdln.gd"
# build: preset for this computer when --preset is not given (macOS needs signing setup, so it is not shipped)
DEFAULT_PRESET = {"Windows": "Windows Desktop", "Linux": "Linux"}
CHECKER = "res://tools/check_scripts.gd" # loads scripts inside the project so autoloads resolve
CHECK_BATCH = 200                        # files per Godot launch (Windows command line limit)
PRESERVE_ON_DEEP_CLEAN = [".godot/export_credentials.cfg"]  # secrets Godot stores inside the cache dir
MIN_GODOT = (4, 3)                       # older 4.x lack --import or exit 1 after a clean quit
CLASS_STAMP = ".godot/dev_class_names.txt"  # class_name set at the last import (stale cache detection)
GUT_NOTHING_RAN = [                      # GUT exits 0 on these, so they must be caught by text
    r"\[GUT ERROR\]", r"Nothing was run", r"Could not find script matching",
    r"Ignoring script .* does not extend GutTest", r"have not been imported", r"SCRIPT ERROR", r"Parse Error",
]
ANSI = re.compile(r"\x1b\[[0-9;]*m")    # GUT colours its summary
SMOKE_TIMEOUT_S = 120                    # a scene that hangs in _ready must fail, not block forever
SMOKE_MIN_FPS = 60                       # headless frames are uncapped; --frames adds frames/60 s to the limit
TEST_TIMEOUT_S = 900
CHECK_TIMEOUT_S = 600                    # per batch of CHECK_BATCH files
IMPORT_TIMEOUT_S = 1800                  # first import of a big project is slow
KILL_TIMEOUT_S = 10                      # after a timeout: seconds to wait for the killed tree's pipe
NO_EXEC = (126, 127)                     # run() codes: not executable / not found -> exit 2

DEBUG = False


def dbg(msg):
    """Verbose output, only with --debug."""
    if DEBUG:
        print(f"[debug] {msg}")


def as_executable(path):
    """Return a runnable file for path, resolving a macOS .app bundle; None if it is not one."""
    p = Path(path)
    if p.is_dir() and p.suffix == ".app":
        inner = p / "Contents" / "MacOS"
        hits = sorted(inner.glob("Godot*")) if inner.is_dir() else []
        p = hits[0] if hits else p
    if p.is_file() and (os.name == "nt" or os.access(p, os.X_OK)):
        return str(p)
    return None


def find_godot(cli_path=None):
    """Locate the Godot executable. Order: --godot flag, GODOT_BIN, PATH names."""
    candidates = [cli_path, os.environ.get("GODOT_BIN")]
    for c in candidates:
        if c:
            p = shutil.which(c) or as_executable(c)
            if p:
                return p
            why = ("is a folder, point at the executable inside it" if Path(c).is_dir()
                   else "is not executable (chmod +x)" if Path(c).is_file() else "was not found")
            print(f"[warn] {c!r} {why}", file=sys.stderr)
    for name in ("godot", "godot4", "Godot", "Godot_v4"):
        p = shutil.which(name)
        if p:
            return p
    return None


# A child run with a timeout leads its own process group on Linux/macOS, so a timeout can kill its whole tree
NEW_SESSION = sys.platform != "win32"


def kill_tree(proc):
    """Kill proc and everything it started. A grandchild still holding our stdout pipe (a test exe, a
    worker, an editor helper) would otherwise keep communicate() waiting after proc itself is dead."""
    if sys.platform == "win32":
        try:                               # /T: the whole tree under proc; Popen holds the handle, so the PID is still ours
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                           timeout=KILL_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as exc:
            dbg(f"taskkill: {exc}")
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)   # proc leads its group (start_new_session)
        except OSError as exc:
            dbg(f"killpg: {exc}")
    try:
        proc.kill()
    except OSError:
        pass


def reap(proc):
    """After kill_tree: the output so far, waiting at most KILL_TIMEOUT_S for the pipe to close."""
    try:
        out, _ = proc.communicate(timeout=KILL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        out = None                         # something outside the tree still holds the pipe: give up on the tail
    return out


def run(cmd, capture=True, echo="fail", timeout=None):
    """Run a command in the project root. Returns (returncode, combined_output).

    echo controls when captured output is printed: "fail" (only if rc != 0),
    "always", or "never" (caller prints its own summary). --debug forces "always".
    124 = timed out (the output so far is returned), 126 = not executable, 127 = not found.
    """
    dbg("run: " + " ".join(str(c) for c in cmd))
    sys.stdout.flush()                     # keep our lines ahead of the child's when piped
    try:
        # Godot writes UTF-8; Windows would decode as cp1252 and crash on names like "Ícaro"
        proc = subprocess.Popen(
            [str(c) for c in cmd], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL if capture else None,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
            start_new_session=NEW_SESSION and timeout is not None,
        )
    except FileNotFoundError as exc:
        print(f"[error] cannot execute {cmd[0]}: {exc}", file=sys.stderr)
        return 127, ""
    except OSError as exc:                 # PermissionError, a folder instead of a binary, ...
        print(f"[error] cannot execute {cmd[0]}: {exc.strerror or exc} (not a file, or not executable: chmod +x)",
              file=sys.stderr)
        return 126, ""
    try:
        raw, _ = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        # Kill, then collect what the engine printed so far: its last lines show where it hung
        kill_tree(proc)
        raw = reap(proc)
        out = ANSI.sub("", raw or "")
        print("\n".join(out.splitlines()[-20:]))
        if isinstance(exc, KeyboardInterrupt):
            raise
        print(f"[FAIL] no exit after {timeout} s: {' '.join(str(c) for c in cmd[1:4])} ...")
        return 124, out
    out = ANSI.sub("", raw or "")
    if capture and (DEBUG or echo == "always" or (echo == "fail" and proc.returncode != 0)):
        print(out)
    return proc.returncode, out


def scan_errors(output):
    """Return the lines that look like Godot errors."""
    hits = []
    for line in output.splitlines():
        if any(re.search(p, line) for p in ERROR_PATTERNS):
            hits.append(line)
    return hits


def class_names():
    """Sorted 'path: ClassName' lines for every class_name script (what Godot's class cache holds)."""
    found = []
    for p in ROOT.rglob("*.gd"):
        rel = p.relative_to(ROOT)
        if rel.parts[0] in (".godot", ".git", "build"):
            continue
        try:
            m = re.search(r"^\s*class_name\s+(\w+)", p.read_text(encoding="utf-8", errors="replace"), re.M)
        except OSError:
            continue
        if m:
            found.append(f"{rel.as_posix()}: {m.group(1)}")
    return "\n".join(sorted(found))


def ensure_imported(godot):
    """Re-run import when the cache is missing or the class_name set changed since the last import.

    Godot resolves class_name globals from .godot/global_script_class_cache.cfg, which only an
    import rebuilds; without this, a new class makes `check` fail on valid code and `test` skip files.
    Returns 0 when the cache is current, else the import's exit code.
    """
    stamp = ROOT / CLASS_STAMP
    current = class_names()
    if stamp.is_file() and stamp.read_text(encoding="utf-8") == current:
        return 0
    why = "no import cache yet" if not (ROOT / ".godot").is_dir() else "class_name scripts changed"
    print(f"[info] {why}: running `dev.py import` first")
    return cmd_import(None, godot)


# ---- Commands -----------------------------------------------------------------
def cmd_import(args, godot):
    names = class_names()
    rc, out = run([godot, "--headless", "--path", ".", "--import"], timeout=IMPORT_TIMEOUT_S)
    if rc in NO_EXEC:
        return 2
    # Godot exits 0 even when an asset fails to import. Script errors are check's job (and the
    # starter test's "Could not find base class GutTest" is expected until GUT is installed)
    errors = [l for l in scan_errors(out) if "Error importing" in l or "Error loading" in l]
    if rc != 0 or errors:
        if errors and not DEBUG:
            print("\n".join(errors[:15]))
        print("[FAIL] import failed" + (f" ({len(errors)} error line(s))" if errors else f" (exit {rc})"))
        return 1
    (ROOT / CLASS_STAMP).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / CLASS_STAMP).write_text(names, encoding="utf-8")
    print("[ OK ] import finished")
    return 0


def cmd_check(args, godot):
    """Compile-check .gd files via tools/check_scripts.gd (one Godot launch per CHECK_BATCH files).

    Not `--check-only --script`: that runs outside the project's autoloads, so every
    autoload use fails with "Identifier not found" (Godot 4.7.2).
    """
    if args.files:
        files = [Path(f) for f in args.files]
    else:
        files = [p for p in ROOT.rglob("*.gd") if not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)]
        if not (ROOT / GUT_CMDLN).exists():
            # Test scripts extend GutTest, which only exists once GUT is installed
            files = [p for p in files if p.relative_to(ROOT).parts[0] != "tests"]
            print("[info] GUT not installed, skipping tests/")
    if not files:
        print("[warn] no .gd files found")
        return 0
    rc = ensure_imported(godot)
    if rc:
        return rc
    # The checker must not load itself: recompiling the running script crashes Godot (4.7.2)
    res_paths = [p for p in ("res://" + f.resolve().relative_to(ROOT).as_posix() for f in files) if p != CHECKER]
    failed = []
    for i in range(0, len(res_paths), CHECK_BATCH):
        batch = res_paths[i:i + CHECK_BATCH]
        rc, out = run([godot, "--headless", "--path", ".", "-s", CHECKER, "--"] + batch, echo="never",
                      timeout=CHECK_TIMEOUT_S)
        if rc in NO_EXEC:
            return 2
        if "CHECK_DONE" not in out:
            print(out)
            print(f"[FAIL] checker did not finish (exit {rc}). Is {CHECKER} present?")
            return 1
        bad = [l.split(" ", 1)[1].strip() for l in out.splitlines() if l.startswith("CHECK_FAIL ")]
        # A script whose dependency is broken still loads, but Godot logs "Failed to load script"
        bad += [m for m in re.findall(r'Failed to load script "(res://[^"]+)"', out) if m in batch and m not in bad]
        dbg(f"batch {i // CHECK_BATCH}: rc={rc} failed={bad}")
        if bad and not DEBUG:
            print("\n".join(l for l in out.splitlines() if any(re.search(p, l) for p in ERROR_PATTERNS)))
        failed += bad
    for path in failed:
        print(f"[FAIL] {path[len('res://'):]}")
    print(f"[{'FAIL' if failed else ' OK '}] checked {len(res_paths)} file(s), {len(failed)} failed")
    return 1 if failed else 0


def cmd_test(args, godot):
    if not (ROOT / GUT_CMDLN).exists():
        print("[error] GUT not found at addons/gut/. See docs/ENGINE_FLOW.md > Setting up tests.", file=sys.stderr)
        return 2
    rc = ensure_imported(godot)
    if rc:
        return rc
    cmd = [godot, "--headless", "--path", ".", "-s", GUT_CMDLN, "-gdir=res://tests", "-gexit"]
    if args.filter:
        cmd.append(f"-gselect={args.filter}")
    rc, out = run(cmd, echo="always", timeout=TEST_TIMEOUT_S)
    if rc in NO_EXEC:
        return 2
    if rc != 0 or re.search(r"(Failing Tests|Failed:\s*[1-9])", out):
        print("[FAIL] tests failed")
        return 1
    # GUT exits 0 when it skipped files or ran nothing; demand proof that every test file ran
    problems = [l.strip() for l in out.splitlines() if any(re.search(p, l) for p in GUT_NOTHING_RAN)]
    ran = re.search(r"^Tests\s+(\d+)", out, re.M)
    if problems or not ran or int(ran.group(1)) == 0:
        for l in problems[:10]:
            print("  " + l)
        why = "a test file was skipped" if problems and ran else f"no tests ran (filter {args.filter!r})" if args.filter else "no tests ran"
        print(f"[FAIL] {why}; see the lines above")
        return 1 if any("SCRIPT ERROR" in l or "Parse Error" in l for l in problems) else 2
    print(f"[ OK ] {ran.group(1)} test(s) passed")
    return 0


def cmd_smoke(args, godot):
    frames = args.frames
    rc = ensure_imported(godot)
    if rc:
        return rc
    rc, out = run([godot, "--headless", "--path", ".", "--quit-after", str(frames)], echo="never",
                  timeout=SMOKE_TIMEOUT_S + frames // SMOKE_MIN_FPS)
    if rc in NO_EXEC:
        return 2
    errors = scan_errors(out)
    booted = BOOT_MARKER in out
    if rc != 0 or errors or not booted:
        if errors:
            print("[FAIL] errors during boot:\n  " + "\n  ".join(errors[:10]))
        if not booted:
            print(f"[FAIL] marker {BOOT_MARKER!r} not seen (did the main scene start?)")
        if rc != 0:
            print(f"[FAIL] exit code {rc}")
        return 1
    print(f"[ OK ] smoke passed ({frames} frames)")
    if args.screenshot or args.record:
        return capture(args, godot, frames)
    return 0


def capture(args, godot, frames):
    """Run the game in a real window (headless has no renderer) and save a screenshot and/or a frame burst."""
    cmd = [godot, "--path", ".", "-s", "res://tools/capture.gd", "--", "--frames", str(frames),
           "--every-ms", str(args.record_every)]
    shot = (ROOT / args.screenshot).resolve() if args.screenshot else None
    rec = (ROOT / args.record).resolve() if args.record else None
    if shot:
        cmd += ["--shot", shot.as_posix()]
    if rec:
        for old in rec.glob("f*.png"):          # frames from an earlier run would end up in the GIF
            old.unlink()
        cmd += ["--record", rec.as_posix()]
    rc, out = run(cmd, echo="never", timeout=SMOKE_TIMEOUT_S + frames // SMOKE_MIN_FPS)
    if rc in NO_EXEC:
        return 2
    if rc != 0 or "CAPTURE_DONE" not in out:
        print(f"[FAIL] capture did not finish (exit {rc}): it needs a window, so run it from a desktop session")
        if DEBUG:
            print(out[-2000:])
        return 1
    if shot:
        print(f"[ OK ] screenshot: {shot}")
    if rec:
        count = len(list(rec.glob("f*.png")))
        print(f"[ OK ] {count} frame(s) in {rec} (make a GIF: python tools/art/frames_to_gif.py {args.record} out.gif)")
    return 0


def cmd_run(args, godot):
    cmd = [godot, "--path", "."]
    if args.debug:
        cmd += ["--", "--debug"]          # picked up by Log autoload
    rc, _ = run(cmd, capture=False)
    return 2 if rc in NO_EXEC else 0 if rc == 0 else 1


def export_presets():
    """{preset name: export_path} from export_presets.cfg (the kit ships Windows Desktop, Linux and Web)."""
    presets, name = {}, None
    for line in (ROOT / "export_presets.cfg").read_text(encoding="utf-8", errors="replace").splitlines():
        if re.match(r"^\[preset\.\d+\]$", line.strip()):
            name = None
        m = re.match(r'^(name|export_path)="(.*)"$', line.strip())
        if m and m.group(1) == "name":
            name = m.group(2)
            presets[name] = ""
        elif m and name is not None:
            presets[name] = m.group(2)
    return presets


def cmd_build(args, godot):
    if not (ROOT / "export_presets.cfg").exists():
        print("[error] export_presets.cfg missing. The kit ships one (Windows Desktop, Linux, Web); restore it from a fresh "
              "scaffold, or create presets in Project > Export.", file=sys.stderr)
        return 2
    presets = export_presets()
    preset = args.preset or DEFAULT_PRESET.get(platform.system(), "Linux")
    if preset not in presets:
        print(f"[error] no export preset named {preset!r}; export_presets.cfg has: {', '.join(presets) or 'none'}", file=sys.stderr)
        return 2
    if not (args.out or presets[preset]):
        print(f"[error] preset {preset!r} has no export_path: pass --out", file=sys.stderr)
        return 2
    args.preset = preset
    out_path = Path(args.out or presets[preset])
    if not out_path.is_absolute():
        out_path = ROOT / out_path          # Godot resolves relative paths inside the project, not our cwd
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rc, _ = run([godot, "--headless", "--path", ".", "--export-release", args.preset, str(out_path)])
    print(f"[{' OK ' if rc == 0 else 'FAIL'}] export {'done: ' + str(out_path) if rc == 0 else 'failed'}")
    return 2 if rc in NO_EXEC else 0 if rc == 0 else 1


def remove_tree(path):
    """Delete a folder for real. Returns None on success, else a reason (nothing is reported as removed)."""
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return "it is a link/junction; remove the link by hand if that is what you want"
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        left = sum(1 for _ in path.rglob("*"))
        return f"{left} item(s) could not be deleted (close the Godot editor or game holding them)"
    return None


def cmd_clean(args, godot):
    targets = [ROOT / "build"] + ([ROOT / ".godot"] if args.deep else [])
    # Godot 4 keeps export passwords and the PCK key in .godot/; they are git-ignored and not rebuildable
    keep = {p: p.read_bytes() for p in (ROOT / rel for rel in PRESERVE_ON_DEEP_CLEAN) if p.is_file()} if args.deep else {}
    failed = 0
    for t in targets:
        if t.exists():
            why = remove_tree(t)
            if why:
                print(f"[FAIL] {t.relative_to(ROOT)} not removed: {why}")
                failed += 1
            else:
                print(f"[ OK ] removed {t.relative_to(ROOT)}")
    for p, data in keep.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        print(f"[ OK ] kept {p.relative_to(ROOT).as_posix()}")
    if args.deep and not failed:
        print("[info] the next check/test/smoke re-imports automatically")
    return 1 if failed else 0


def cmd_doctor(args, godot):
    problems = 0
    print(f"[info] python {sys.version.split()[0]}")
    if godot:
        rc, out = run([godot, "--version"], echo="never", timeout=60)
        ver = tuple(int(n) for n in re.findall(r"^(\d+)\.(\d+)", out.strip())[0]) if re.match(r"\d+\.\d+", out.strip()) else None
        if ver and ver < MIN_GODOT:
            print(f"[FAIL] godot {out.strip()} is older than {MIN_GODOT[0]}.{MIN_GODOT[1]} (import and smoke hang or misreport)")
            problems += 1
        else:
            print(f"[ OK ] godot: {godot} ({out.strip() or 'version unknown'})")
    else:
        print("[FAIL] godot not found. Set GODOT_BIN or add godot to PATH.")
        problems += 1
    for rel, hint in [("project.godot", "wrong directory?"),
                      (GUT_CMDLN, "GUT not installed, tests will not run: docs/ENGINE_FLOW.md 'Setting up tests'"),
                      (".godot", "import cache missing; check/test/smoke run `dev.py import` automatically")]:
        ok = (ROOT / rel).exists()
        print(f"[{' OK ' if ok else 'WARN'}] {rel}" + ("" if ok else f"  ({hint})"))
    doctor = ROOT / "tools" / "doctor.py"
    if doctor.exists():
        rc, _ = run([sys.executable, doctor], capture=False)
        problems += 1 if rc else 0
    return 1 if problems else 0


def positive_int(text):
    """argparse type: 1..100000, so a typo cannot ask for a smoke run that never ends."""
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number")
    if not 1 <= n <= 100000:
        raise argparse.ArgumentTypeError("must be between 1 and 100000")
    return n


def build_parser():
    ap = argparse.ArgumentParser(
        prog="dev.py",
        description="Project command wrapper (Godot 4). Same commands on every engine in the Claude Code Game Kit.",
        epilog="Set GODOT_BIN to your Godot executable. Exit codes: 0 ok, 1 failed, 2 environment/usage problem.",
    )
    ap.add_argument("--debug", action="store_true", help="verbose output; for `run`, also enables in-game debug logging")
    ap.add_argument("--godot", metavar="PATH", help="path to Godot executable (overrides GODOT_BIN)")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    sub.add_parser("import", help="build the .godot/ import cache (check/test/smoke run it automatically when stale)").set_defaults(fn=cmd_import)

    p = sub.add_parser("check", help="parse .gd files for errors")
    p.add_argument("files", nargs="*", help="limit to these .gd files (default: all outside addons/)")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("test", help="run GUT unit tests headless")
    p.add_argument("--filter", help="run only test files matching this name, e.g. test_coyote_timer.gd")
    p.set_defaults(fn=cmd_test)

    p = sub.add_parser("smoke", help="boot headless for N frames; fail on errors or missing boot marker")
    p.add_argument("--frames", type=positive_int, default=SMOKE_FRAMES,
                   help=f"frames to run, 1 to 100000 (default {SMOKE_FRAMES}; the run allows frames/{SMOKE_MIN_FPS} s extra)")
    p.add_argument("--screenshot", default="", help="after the smoke, save a PNG of the last frame from a real window (path relative to the project)")
    p.add_argument("--record", default="", help="after the smoke, save PNG frames to this folder from a real window (GIF: tools/art/frames_to_gif.py)")
    p.add_argument("--record-every", type=positive_int, default=66, help="milliseconds between recorded frames (default 66)")
    p.set_defaults(fn=cmd_smoke)

    sub.add_parser("run", help="launch the game window").set_defaults(fn=cmd_run)

    p = sub.add_parser("build", help="export a release build (needs export_presets.cfg)")
    p.add_argument("--preset", help='export preset name (default: "Windows Desktop" on Windows, else "Linux"; also "Web")')
    p.add_argument("--out", help="output path (default: the preset's export_path, under build/)")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("clean", help="remove build output")
    p.add_argument("--deep", action="store_true", help="also remove .godot/ (forces reimport)")
    p.add_argument("--yes", action="store_true", help="accepted on every engine; Godot clean never asks anyway")
    p.set_defaults(fn=cmd_clean)

    sub.add_parser("doctor", help="verify the local environment").set_defaults(fn=cmd_doctor)
    return ap


def hoist_global_options(parser, argv):
    """
    Let global options sit anywhere: `dev.py build --debug` works like `dev.py --debug build`.
    Pseudocode: collect the top-level option names (and whether they take a value) from the
    parser, then move every occurrence in argv (plus its value) to the front, keeping order.
    Uses argparse's _actions list (stable for years, but private), so failures fall back to argv.
    """
    try:
        takes_value = {}
        for action in parser._actions:
            if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
                continue
            for opt in action.option_strings:
                takes_value[opt] = action.nargs != 0
    except AttributeError:
        return argv
    front, rest, i = [], [], 0
    while i < len(argv):
        tok = argv[i]
        name = tok.split("=", 1)[0]
        if name in takes_value:
            front.append(tok)
            if takes_value[name] and "=" not in tok and i + 1 < len(argv):
                front.append(argv[i + 1])
                i += 1
        else:
            rest.append(tok)
        i += 1
    return front + rest


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # any script, in order
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else list(argv)
    args = parser.parse_args(hoist_global_options(parser, argv))
    DEBUG = args.debug
    needs_godot = args.command != "clean"
    godot = find_godot(args.godot)
    if needs_godot and not godot and args.command != "doctor":
        print("[error] Godot executable not found. Set GODOT_BIN or use --godot PATH.", file=sys.stderr)
        return 2
    try:
        return args.fn(args, godot)
    except KeyboardInterrupt:
        print("\n[abort] interrupted")
        return 1
    except OSError as exc:
        # Name the file (e.g. a log or results file still held by an orphaned editor)
        where = f" {exc.filename}" if exc.filename else ""
        print(f"[error] {exc.strerror or exc}{where} (close any program holding it and retry)", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2
    except Exception as exc:                      # last-resort guard with context
        print(f"[error] unexpected failure in '{args.command}': {exc!r}. Re-run with --debug.", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()           # still exit 2: --debug must not change the verdict
        return 2


if __name__ == "__main__":
    sys.exit(main())

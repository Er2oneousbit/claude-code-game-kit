#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dev.py  (C++ / SDL2 / CMake edition)
# Purpose : The ONE command wrapper for this project. Same subcommands on every
#           engine in the Claude Code Game Kit, so humans and Claude never guess flags.
# Usage   : python tools/dev.py [--preset debug|release] <command> [options]
#             check    configure + compile
#             test     build + run unit tests (CTest)
#             smoke    run the game headless for N frames, fail on errors; scenario runs:
#                      smoke --frames 20000 --until RUN_WON --fail-on CAUGHT -- --autoplay careful
#                      (after `--`: arguments for the game; --screenshot / --record capture frames)
#             build    configure + compile (use --preset release for shipping)
#             run      launch the game
#             clean    remove build/
#             doctor   verify the local environment
# Env     : VCPKG_ROOT  path to your vcpkg checkout (required by CMakePresets.json)
# Exit    : 0 ok, 1 task failed, 2 environment/usage problem
# Notes   : Works with single-config (Ninja/Make) and multi-config (Visual Studio)
#           generators. Python 3.8+, standard library only.
#
# Pseudocode:
#   parse args -> verify cmake + VCPKG_ROOT -> configure preset -> build preset
#   -> (test) ctest preset  |  (smoke) find exe, run with --smoke N, scan output
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-19 with Claude (Opus 5.5, claude-opus-5-5): global options accepted after the
#           subcommand (dev.py build --debug)
# Updated : 2026-10-21 (audit pass 3): stdout/stderr and captured tool output are UTF-8 (Windows
#           pipes defaulted to cp1252 and crashed on non-Latin paths, names and log lines)
# Updated : 2026-10-21 (audit pass 4): timeouts on test/smoke, no-tests and not-executable exit 2,
#           clean verifies deletion, --frames bounded, doctor splits cmake/vcpkg, warns on long paths
# Updated : 2026-10-21 (kit 0.4.0): smoke scenario options like the web overlays: game arguments after
#           `--`, --until, --fail-on, --timeout, --screenshot, --record (BMP frames for frames_to_gif.py)
# Updated : 2026-10-30 with Claude (Opus 5.5, claude-opus-5-5): a timeout kills the whole process tree
#           (taskkill /T, or the process group), then waits at most KILL_TIMEOUT_S for the pipe
# ---------------------------------------------------------------------------
import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---- Tunables / constants ----------------------------------------------------
SMOKE_FRAMES = 120
BOOT_MARKER = "BOOT_OK"
ERROR_MARKERS = ["[ERROR]", "Assertion failed", "terminate called"]
SMOKE_TIMEOUT_S = 120                    # a game that hangs at boot must fail, not block forever
TEST_TIMEOUT_S = 600
KILL_TIMEOUT_S = 10                      # after a timeout: seconds to wait for the killed tree's pipe
NO_EXEC = (126, 127)                     # run() codes: not executable / not found -> environment problem (exit 2)
DEBUG = False


def dbg(msg):
    """Verbose output, only with --debug."""
    if DEBUG:
        print(f"[debug] {msg}")


def project_slug():
    """Executable name = project() name in CMakeLists.txt (falls back to folder name)."""
    try:
        text = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        m = re.search(r"^\s*project\(\s*([A-Za-z0-9_\-]+)", text, re.MULTILINE | re.IGNORECASE)
        if m:
            return m.group(1)
    except OSError:
        pass
    return ROOT.name


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


def run(cmd, env=None, capture=False, timeout=None):
    """Run a command in the project root. Returns (returncode, output_or_empty).

    124 = timed out (output so far is returned), 126 = not executable, 127 = not found.
    """
    dbg("run: " + " ".join(str(c) for c in cmd))
    sys.stdout.flush()                     # keep our lines ahead of the child's when piped
    try:
        proc = subprocess.Popen(
            [str(c) for c in cmd], cwd=ROOT, env=env, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
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
        out, _ = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        # Kill, then keep what the game printed so far: its last lines show where it hung
        kill_tree(proc)
        out = reap(proc)
        if isinstance(exc, KeyboardInterrupt):
            print("\n".join((out or "").splitlines()[-20:]))
            raise
        return 124, out or ""
    return proc.returncode, (out or "")


def check_cmake():
    """Return an error string if cmake is missing, else None."""
    if shutil.which("cmake"):
        return None
    return ("cmake not found on PATH. VS Build Tools ship one: add <BuildTools>/Common7/IDE/CommonExtensions/"
            "Microsoft/CMake/CMake/bin to PATH, or install CMake 3.21+.")


def check_vcpkg():
    """Return an error string if VCPKG_ROOT is unusable, else None."""
    vcpkg = os.environ.get("VCPKG_ROOT")
    if not vcpkg:
        return "VCPKG_ROOT is not set. Point it at your vcpkg checkout (see docs/ENGINE_FLOW.md)."
    if not (Path(vcpkg) / "scripts" / "buildsystems" / "vcpkg.cmake").exists():
        return f"VCPKG_ROOT={vcpkg} does not contain scripts/buildsystems/vcpkg.cmake"
    return None


def preflight():
    """Return an error string if the build environment is unusable, else None."""
    return check_cmake() or check_vcpkg()


def configure_and_build(preset):
    """cmake --preset X ; cmake --build --preset X. Returns 0 or 1."""
    rc, _ = run(["cmake", "--preset", preset])
    if rc != 0:
        print(f"[FAIL] configure failed (preset {preset})")
        return 2 if rc in NO_EXEC else 1
    rc, _ = run(["cmake", "--build", "--preset", preset])
    if rc != 0:
        print(f"[FAIL] build failed (preset {preset})")
        return 2 if rc in NO_EXEC else 1
    return 0


def find_exe(preset):
    """Find the built game executable under build/<preset>/bin/ (handles Debug/ subfolders)."""
    slug = project_slug()
    names = {slug, slug + ".exe"}
    base = ROOT / "build" / preset / "bin"
    if base.exists():
        for p in base.rglob("*"):
            if p.is_file() and p.name in names:
                return p
    return None


# ---- Commands -----------------------------------------------------------------
def cmd_check(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    rc = configure_and_build(args.preset)
    if rc == 0:
        print(f"[ OK ] compiled ({args.preset})")
    return rc


cmd_build = cmd_check  # same steps today; `build --preset release` is the shipping path


def cmd_test(args):
    rc = cmd_check(args)
    if rc != 0:
        return rc
    # No `--no-tests=error`: it needs CMake 3.26 and the kit supports 3.21. CTest exits 0 when nothing is registered
    # (e.g. BUILD_TESTS=OFF in the cache), so the "No tests were found" text below catches that case instead.
    rc, out = run(["ctest", "--preset", args.preset, "--output-on-failure"], capture=True, timeout=TEST_TIMEOUT_S)
    print(out)
    if rc in NO_EXEC:
        return 2
    if "No tests were found" in out:
        print("[FAIL] no tests registered (configured with -DBUILD_TESTS=OFF? run `dev.py clean` and retry)")
        return 2
    if rc == 124:
        print(f"[FAIL] tests did not finish within {TEST_TIMEOUT_S} s")
        return 1
    print("[ OK ] tests passed" if rc == 0 else "[FAIL] tests failed")
    return 0 if rc == 0 else 1


def cmd_smoke(args):
    rc = cmd_check(args)
    if rc != 0:
        return rc
    exe = find_exe(args.preset)
    if not exe:
        print(f"[FAIL] game executable not found under build/{args.preset}/bin/", file=sys.stderr)
        return 1
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    cmd = [exe, "--smoke", str(args.frames)]
    if args.screenshot:
        shot = (ROOT / args.screenshot).resolve()
        shot.parent.mkdir(parents=True, exist_ok=True)
        cmd += ["--screenshot", str(shot)]
    if args.record:
        rec = (ROOT / args.record).resolve()
        rec.mkdir(parents=True, exist_ok=True)
        cmd += ["--record", str(rec), "--record-every", str(args.record_every)]
    if args.game_args:
        cmd += ["--"] + args.game_args
    rc, out = run(cmd, env=env, capture=True, timeout=args.timeout)
    if DEBUG or rc != 0:
        print(out)
    if rc in NO_EXEC:
        return 2
    if rc == 124:
        print(f"[FAIL] game did not exit within {args.timeout} s (hang, a Debug assert dialog, or raise --timeout)")
        return 1
    lines = out.splitlines()
    errors = [l for l in lines if any(m in l for m in ERROR_MARKERS)]
    fail_on = [m for m in (args.fail_on or "").split(",") if m]
    bad = [l for l in lines if any(m in l for m in fail_on)]
    missing_until = bool(args.until) and not any(args.until in l for l in lines)
    if rc != 0 or errors or bad or missing_until or BOOT_MARKER not in out:
        if errors:
            print("[FAIL] errors during smoke:\n  " + "\n  ".join(errors[:10]))
        if bad:
            print("[FAIL] --fail-on marker seen:\n  " + "\n  ".join(bad[:5]))
        if missing_until:
            print(f"[FAIL] marker {args.until!r} not seen within {args.frames} frames")
        if BOOT_MARKER not in out:
            print(f"[FAIL] marker {BOOT_MARKER!r} not seen")
        if rc != 0:
            print(f"[FAIL] exit code {rc}")
        return 1
    what = f"marker {args.until!r} reached" if args.until else f"{args.frames} frames"
    print(f"[ OK ] smoke passed ({what})")
    if args.screenshot:
        print(f"[ OK ] screenshot: {(ROOT / args.screenshot).resolve()}")
    if args.record:
        n = len(list((ROOT / args.record).glob("*.bmp")))
        print(f"[ OK ] {n} frame(s) in {(ROOT / args.record).resolve()} (GIF: python tools/art/frames_to_gif.py <dir> out.gif)")
    return 0


def cmd_run(args):
    rc = cmd_check(args)
    if rc != 0:
        return rc
    exe = find_exe(args.preset)
    if not exe:
        print("[FAIL] game executable not found", file=sys.stderr)
        return 2                           # a setup problem (wrong preset or exe path), not a failing game
    cmd = [exe] + (["--debug"] if args.debug else [])
    rc, _ = run(cmd)                       # cwd = project root so assets/ resolve
    return 2 if rc in NO_EXEC else 0 if rc == 0 else 1


def remove_tree(path):
    """Delete a folder for real. Returns None on success, else a reason (nothing is reported as removed)."""
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return "it is a link/junction; remove the link by hand if that is what you want"
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        left = sum(1 for _ in path.rglob("*"))
        return f"{left} item(s) could not be deleted (close the editor, game or IDE holding them)"
    return None


def cmd_clean(args):
    target = ROOT / "build"
    if not target.exists():
        print("[info] nothing to clean")
        return 0
    why = remove_tree(target)
    if why:
        print(f"[FAIL] build/ not removed: {why}")
        return 1
    print("[ OK ] removed build/")
    return 0


def cmd_doctor(args):
    problems = 0
    print(f"[info] python {sys.version.split()[0]}")
    for tool in ("cmake", "git"):
        p = shutil.which(tool)
        print(f"[{' OK ' if p else 'FAIL'}] {tool}: {p or 'not found'}")
        problems += 0 if p else 1
    compilers = [c for c in ("cl", "g++", "clang++") if shutil.which(c)]
    print(f"[{' OK ' if compilers else 'WARN'}] compilers on PATH: {', '.join(compilers) or 'none (VS may supply one via CMake)'}")
    print(f"[{' OK ' if shutil.which('ninja') else 'info'}] ninja: {shutil.which('ninja') or 'not found (optional)'}")
    err = check_vcpkg()
    print(f"[{'FAIL' if err else ' OK '}] vcpkg: {err or os.environ['VCPKG_ROOT']}")
    problems += 1 if err else 0
    if os.name == "nt" and len(str(ROOT)) > 100:
        print(f"[WARN] project path is {len(str(ROOT))} characters; vcpkg builds hit the 260-character limit "
              "(error C1083). Move the project to a shorter path.")
    try:
        if '"builtin-baseline"' not in (ROOT / "vcpkg.json").read_text(encoding="utf-8"):
            print("[WARN] vcpkg.json has no builtin-baseline (builds are not reproducible yet)")
    except OSError:
        pass
    doctor = ROOT / "tools" / "doctor.py"
    if doctor.exists():
        rc, _ = run([sys.executable, doctor])
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
        description="Project command wrapper (C++/SDL2/CMake). Same commands on every engine in the Claude Code Game Kit.",
        epilog="Env: VCPKG_ROOT must point at your vcpkg checkout. Exit codes: 0 ok, 1 failed, 2 environment/usage problem.",
    )
    ap.add_argument("--debug", action="store_true", help="verbose output; for `run`, also passes --debug to the game")
    ap.add_argument("--preset", default="debug", choices=["debug", "release"], help="CMake preset (default: debug)")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    sub.required = True
    sub.add_parser("check", help="configure and compile").set_defaults(fn=cmd_check)
    sub.add_parser("build", help="configure and compile (use --preset release to ship)").set_defaults(fn=cmd_build)
    sub.add_parser("test", help="build then run unit tests via CTest").set_defaults(fn=cmd_test)
    p = sub.add_parser("smoke", help="run the game headless for N frames; fail on errors",
                       epilog="Arguments after `--` go to the game, e.g. smoke --until RUN_WON -- --autoplay careful")
    p.add_argument("--frames", type=positive_int, default=SMOKE_FRAMES,
                   help=f"frames to run at most, 1 to 100000 (default {SMOKE_FRAMES}); one game tick per frame")
    p.add_argument("--until", help="fail unless the game prints this marker (scenario runs, e.g. RUN_WON)")
    p.add_argument("--fail-on", help="comma-separated markers that fail the run (e.g. CAUGHT,TIME_UP)")
    p.add_argument("--timeout", type=positive_int, default=SMOKE_TIMEOUT_S,
                   help=f"seconds before a hung game is killed (default {SMOKE_TIMEOUT_S})")
    p.add_argument("--screenshot", help="save the last frame as BMP (path relative to the project)")
    p.add_argument("--record", help="save BMP frames into this folder (GIF: tools/art/frames_to_gif.py)")
    p.add_argument("--record-every", type=positive_int, default=4, help="record every Nth frame (default 4)")
    p.set_defaults(fn=cmd_smoke)
    sub.add_parser("run", help="build then launch the game").set_defaults(fn=cmd_run)
    p = sub.add_parser("clean", help="remove build/")
    p.add_argument("--yes", action="store_true", help="accepted on every engine; C++ clean never asks anyway")
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
    game_args = []
    if "--" in argv:                       # everything after `--` is for the game itself (smoke)
        cut = argv.index("--")
        argv, game_args = argv[:cut], argv[cut + 1:]
    args = parser.parse_args(hoist_global_options(parser, argv))
    args.game_args = game_args
    DEBUG = args.debug
    try:
        return args.fn(args)
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
    except Exception as exc:
        print(f"[error] unexpected failure in '{args.command}': {exc!r}. Re-run with --debug.", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()           # still exit 2: --debug must not change the verdict
        return 2


if __name__ == "__main__":
    sys.exit(main())

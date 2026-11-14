#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dev.py  (C++ / SDL3 / CMake edition)
# Purpose : The ONE command wrapper for this project. Same subcommands on every
#           engine in the Claude Code Game Kit, so humans and Claude never guess flags.
# Usage   : python tools/dev.py [--preset debug|release] <command> [options]
#             check    configure + compile (the build also compiles the kit's shader recipes with shadercross;
#                      check first makes sure the generated shader files match their recipes)
#             test     build + run unit tests (CTest)
#             smoke    run the game headless for N frames, fail on errors; scenario runs:
#                      smoke --frames 20000 --until RUN_WON --fail-on CAUGHT -- --autoplay careful
#                      (after `--`: arguments for the game; --screenshot / --record capture frames);
#                      --drive SCENARIO runs a scripted path through the shell's screens (menus, crash, pseudo,
#                      bug, display, access, show:<screen>) with --data-dir DIR and --locale LANG; without --drive the run walks
#                      title -> menu -> play; settings always go to a smoke data folder, never the player's;
#                      --shaders also draws every kit shader recipe on the GPU (kit_shader_check) and compares
#                      it with its golden image (SDL_GPU_DRIVER=vulkan|direct3d12|metal picks the backend)
#             build    configure + compile (use --preset release for shipping)
#             run      launch the game
#             clean    remove build/
#             doctor   verify the local environment
#             ship     put the game online (tools/cloud/ship.py): ship --target aws|azure|gcp|linode|do
#                      --kind static|container --plan, then --apply / --destroy; or upload to itch.io:
#                      ship --target itch --project user/game --dry-run, then without it; ship -h for its options
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
# Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): smoke needs main.cpp's end-of-run line (an early
#           quit passes only after --until's marker); each --screenshot / --record is checked after the run
# Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): on Windows a command with a timeout runs in a
#           job object (WinJob), so a timeout also ends a grandchild whose parent already exited
# Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): on Linux and macOS, killing an untimed command
#           (Ctrl+C) also kills what it started, found through ps (it shares our process group)
# Updated : 2026-11-06 with Claude (Opus 5.5, claude-opus-5-5): SDL3; the kit's shader recipes (shaders/kit): check
#           checks the generated files, smoke --shaders runs kit_shader_check and compares its pictures
# Updated : 2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): smoke --drive / --data-dir / --locale for the shell's
#           screens (#168), passed to the game after `--`; the proof lines (SETTINGS_WRITTEN, DRIVE_, ACCESS_) are
#           echoed; a drive ends at DRIVE_DONE, so --until defaults to it
# Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): the crash, pseudo, pseudo-plant and bug drives and
#           show:juice (#275); CRASH_WRITTEN, PSEUDO_ and BUG_REPORT lines are echoed
# Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): smoke reports the run's FRAME_TIMES line (mean,
#           p95, p99, worst) and fails a p95 over --frame-budget MS, or over the "Smoke frame time" row of
#           docs/ARCHITECTURE.md; a run that measured nothing says so (#90) and --no-build (one build for
#           every run of tools/seed_sweep.py, #183)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): smoke --drive show:credits (#284)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): `ship --target itch` uploads to itch.io with
#           butler (tools/cloud/ship.py, #86); the engine's web build is its default --site, like a static site
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): smoke --drive display, show:apply, show:confirm in
#           the help (the Display tab's Apply, #308)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): check fails on a TEST_CASE name holding ';' (CMake splits
#           it, so doctest_discover_tests registers a test that matches nothing and passes)
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
DRIVE_FRAMES = 6000                       # a --drive run's frame budget (the drive's own limit, Drive.hpp)
BOOT_MARKER = "BOOT_OK"
END_RE = re.compile(r"smoke complete after (\d+) frames|smoke ended early: the game quit after (\d+) of")  # main.cpp
ERROR_MARKERS = ["[ERROR]", "Assertion failed", "terminate called"]
SMOKE_TIMEOUT_S = 120                    # a game that hangs at boot must fail, not block forever
SMOKE_UNMEASURED = "main.cpp printed no FRAME_TIMES line (a main.cpp from before kit 0.15 does not measure)"
TEST_TIMEOUT_S = 600
TEST_NAME_RE = re.compile(r'\b(?:TEST_CASE|SCENARIO)\s*\(\s*"([^"]*)"')  # doctest test names in tests/
SHADER_DIR = "shaders/kit"                # the kit's shader recipes, generated by tools/shaders/shader_gen.py
SHADER_CHECK_EXE = "kit_shader_check"     # built with the game; draws every recipe
SHADER_TIMEOUT_S = 120
SMOKE_DATA = "build/smoke-data"           # a smoke run's settings folder (wiped each run) unless --data-dir is given
PROOF_PREFIXES = ("SETTINGS_WRITTEN", "DRIVE_", "ACCESS_", "CRASH_WRITTEN", "PSEUDO_",
                  "BUG_REPORT")         # the shell scenarios' proof lines, echoed
DRIVE_DONE = "DRIVE_DONE"                 # a drive's last line (--until defaults to it)
KILL_TIMEOUT_S = 10                      # after a timeout: seconds to wait for the killed tree's pipe
NO_EXEC = (126, 127)                     # run() codes: not executable / not found -> environment problem (exit 2)
SHIP_SITE = None   # the web build `ship --kind static` publishes unless --site is given (None: none)
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


class WinJob:
    """Windows: a job object holding proc and every process it starts from then on, so kill_tree can end a
    grandchild whose parent already exited (taskkill /T only finds children through living parents). Made for
    commands with a timeout, like the process group on Linux and macOS; elsewhere, or when a call fails, it does
    nothing. A process proc starts before it joins the job (its first moments) stays outside: taskkill /T covers it."""
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001

    def __init__(self, proc, timeout):
        self.handle = None
        if sys.platform != "win32" or timeout is None:
            return
        try:
            k32 = kernel32()
            job = k32.CreateJobObjectW(None, None)
            child = k32.OpenProcess(self.PROCESS_SET_QUOTA | self.PROCESS_TERMINATE, False, proc.pid) if job else None
            if child and k32.AssignProcessToJobObject(job, child):
                self.handle = job
            elif job:
                dbg(f"job object: could not add pid {proc.pid}")
                k32.CloseHandle(job)
            if child:
                k32.CloseHandle(child)
        except (OSError, AttributeError, ImportError) as exc:
            dbg(f"job object: {exc}")

    def kill(self):
        """End every process in the job, then close it."""
        if self.handle:
            kernel32().TerminateJobObject(self.handle, 1)
        self.close()

    def close(self):
        """Let go of the job; its processes keep running (a normal exit changes nothing)."""
        if self.handle:
            kernel32().CloseHandle(self.handle)
            self.handle = None


def kernel32():
    """kernel32 with the job object calls typed (Windows only)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k32


def kill_tree(proc, job=None):
    """Kill proc and everything it started. A grandchild still holding our stdout pipe (a test exe, a
    worker, an editor helper) would otherwise keep communicate() waiting after proc itself is dead."""
    if job is not None:
        job.kill()                         # Windows: the whole job, also orphaned grandchildren
    if sys.platform == "win32":
        try:                               # /T: the whole tree under proc; Popen holds the handle, so the PID is still ours
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                           timeout=KILL_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as exc:
            dbg(f"taskkill: {exc}")
    else:
        try:
            if os.getpgid(proc.pid) == proc.pid:
                os.killpg(proc.pid, signal.SIGKILL)   # proc leads its group (start_new_session)
            else:
                # An untimed command shares our group (so a terminal's Ctrl+C reaches it as before): kill what it
                # started one by one, found through the parent ids ps lists, or a build server outlives us
                for pid in descendants(proc.pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass                  # it ended on its own meanwhile
        except OSError as exc:
            dbg(f"killpg: {exc}")
    try:
        proc.kill()
    except OSError:
        pass


def ps_pairs():
    """(pid, parent pid) of every process, from ps (Linux and macOS). Empty when ps cannot run."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=", "-o", "ppid="], stdin=subprocess.DEVNULL,
                             capture_output=True, encoding="utf-8", errors="replace", timeout=KILL_TIMEOUT_S).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        dbg(f"ps: {exc}")
        return []
    pairs = []
    for line in out.splitlines():
        cols = line.split()
        if len(cols) == 2 and cols[0].isdigit() and cols[1].isdigit():
            pairs.append((int(cols[0]), int(cols[1])))
    return pairs


def descendants(root):
    """Every process below root (children, grandchildren, ...), parents before their children."""
    children = {}
    for pid, ppid in ps_pairs():
        children.setdefault(ppid, []).append(pid)
    found, todo = [], list(children.get(root, []))
    while todo:
        pid = todo.pop(0)
        if pid != root and pid not in found:
            found.append(pid)
            todo.extend(children.get(pid, []))
    return found


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
    job = WinJob(proc, timeout)
    try:
        out, _ = proc.communicate(timeout=timeout)
        job.close()                        # a normal exit: anything it left running keeps running
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        # Kill, then keep what the game printed so far: its last lines show where it hung
        kill_tree(proc, job)
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


def find_exe(preset, name=None):
    """Find the built game executable (or another target, `name`) under build/<preset>/bin/ (handles Debug/
    subfolders)."""
    slug = name or project_slug()
    names = {slug, slug + ".exe"}
    base = ROOT / "build" / preset / "bin"
    if base.exists():
        for p in base.rglob("*"):
            if p.is_file() and p.name in names:
                return p
    return None


# ---- Commands -----------------------------------------------------------------
def unrunnable_test_names():
    """TEST_CASE names CTest cannot run: CMake reads ';' as a list separator, so doctest_discover_tests splits
    such a name into filters that match no test, and CTest reports them as passed. Returns 'file: name' lines."""
    found = []
    for path in sorted((ROOT / "tests").rglob("*.cpp")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in TEST_NAME_RE.findall(text):
            if ";" in name:
                found.append(f"{path.relative_to(ROOT).as_posix()}: {name}")
    return found


def cmd_check(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    if (ROOT / SHADER_DIR).is_dir():
        rc, out = run([sys.executable, ROOT / "tools" / "shaders" / "shader_gen.py", "--check"], capture=True,
                      timeout=60)
        if rc != 0:
            print(out.rstrip())
            if rc == 2:                       # the recipes themselves cannot be read: not a stale file
                print("[error] tools/shaders/shader_gen.py could not read the recipes (see above)")
                return 2
            print("[FAIL] the shader files do not match their recipes: python tools/shaders/shader_gen.py")
            return 1
    bad = unrunnable_test_names()
    if bad:
        for line in bad:
            print(f"[FAIL] {line}")
        print("[FAIL] a test name with ';' never runs (CMake splits it and CTest reports it passed): use ',' or 'and'")
        return 1
    rc = configure_and_build(args.preset)
    if rc == 0:
        print(f"[ OK ] compiled ({args.preset})" + (", shader recipes included" if (ROOT / SHADER_DIR).is_dir() else ""))
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
    if data_dir_in_build(getattr(args, "data_dir", "")):
        return 2
    if data_dir_in_pack(getattr(args, "data_dir", "")):   # #271: a folder the packaged game carries
        return 2
    rc = 0 if getattr(args, "no_build", False) else cmd_check(args)   # --no-build: tools/seed_sweep.py reuses one build
    if rc != 0:
        return rc
    exe = find_exe(args.preset)
    if not exe:
        print(f"[FAIL] game executable not found under build/{args.preset}/bin/", file=sys.stderr)
        return 1
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    drive = getattr(args, "drive", "") or ""
    if getattr(args, "frames", None) is None:            # a drive ends itself: give it its own budget
        args.frames = DRIVE_FRAMES if drive else SMOKE_FRAMES
    cmd = [exe, "--smoke", str(args.frames)]
    shot = (ROOT / args.screenshot).resolve() if args.screenshot else None
    rec = (ROOT / args.record).resolve() if args.record else None
    if shot:
        shot.parent.mkdir(parents=True, exist_ok=True)
        if shot.is_file():
            shot.unlink()                   # a picture from an earlier run must not pass for this one
        cmd += ["--screenshot", str(shot)]
    if rec:
        rec.mkdir(parents=True, exist_ok=True)
        for old in rec.glob("frame_*.bmp"):  # frames from an earlier run would end up in the GIF
            old.unlink()
        cmd += ["--record", str(rec), "--record-every", str(args.record_every)]
    # the shell's options go to the game after `--` (Game::configure takes them), then the game's own
    try:
        data = smoke_data_dir(args)
    except OSError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    dbg(f"data folder {data}")
    shell_args = ["--data-dir", str(data)]
    if drive:
        shell_args += ["--drive", drive]
    if getattr(args, "locale", ""):
        shell_args += ["--locale", args.locale]
    cmd += ["--"] + shell_args + args.game_args
    until = args.until or (DRIVE_DONE if drive else None)   # a drive ends itself at DRIVE_DONE
    rc, out = run(cmd, env=env, capture=True, timeout=args.timeout)
    if DEBUG or rc != 0:
        print(out)
    if rc in NO_EXEC:
        return 2
    if rc == 124:
        print(f"[FAIL] game did not exit within {args.timeout} s (hang, a Debug assert dialog, or raise --timeout)")
        return 1
    lines = out.splitlines()
    for line in lines:                       # the proof lines the shell scenarios print
        if line.startswith(PROOF_PREFIXES):
            print(line)
    errors = [l for l in lines if any(m in l for m in ERROR_MARKERS)]
    fail_on = [m for m in (args.fail_on or "").split(",") if m]
    bad = [l for l in lines if any(m in l for m in fail_on)]
    missing_until = bool(until) and not any(until in l for l in lines)
    problems = smoke_end_problems(out, args.frames, until_seen=bool(until) and not missing_until)
    problems += capture_problems(shot, rec)
    if rc != 0 or errors or bad or missing_until or problems or BOOT_MARKER not in out:
        if errors:
            print("[FAIL] errors during smoke:\n  " + "\n  ".join(errors[:10]))
        if bad:
            print("[FAIL] --fail-on marker seen:\n  " + "\n  ".join(bad[:5]))
        if missing_until:
            print(f"[FAIL] marker {until!r} not seen within {args.frames} frames"
                  + (f" (the drive {drive!r} did not finish)" if drive and until == DRIVE_DONE else ""))
        if BOOT_MARKER not in out:
            print(f"[FAIL] marker {BOOT_MARKER!r} not seen")
        for p in problems:
            print(f"[FAIL] {p}")
        if rc != 0:
            print(f"[FAIL] exit code {rc}")
        if drive == "crash" and "CRASH_WRITTEN" in out:
            print("[info] --drive crash fails on purpose: the CRASH_WRITTEN file above is the proof")
        if drive == "pseudo-plant" and "PSEUDO_FAIL" in out:
            print("[info] --drive pseudo-plant fails on purpose: the PSEUDO_FAIL line names the planted label")
        return 1
    what = f"drive {drive}" if drive and not args.until else f"marker {until!r} reached" if until else f"{args.frames} frames"
    print(f"[ OK ] smoke passed ({what}; data in {data})")
    if shot:
        print(f"[ OK ] screenshot: {shot}")
    if rec:
        n = len(list(rec.glob("frame_*.bmp")))
        print(f"[ OK ] {n} frame(s) in {rec} (GIF: python tools/art/frames_to_gif.py <dir> out.gif)")
    rc = frame_budget_report(out, getattr(args, "frame_budget", None), SMOKE_UNMEASURED)   # #90
    if rc:
        return rc
    if getattr(args, "shaders", False):
        return shader_pass(args.preset)
    return 0


def build_outputs():
    """The CMake build trees (#263): build/<preset> for each configure preset in CMakePresets.json (its binaryDir),
    or build/debug and build/release when the file cannot be read."""
    import json
    try:
        data = json.loads((ROOT / "CMakePresets.json").read_text(encoding="utf-8"))
        names = [p["name"] for p in data.get("configurePresets", []) if not p.get("hidden")]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        names = []
    return ["build/" + n for n in names] or ["build/debug", "build/release"]


def data_dir_in_build(given):
    """#263: print an error and return True when --data-dir lies inside a build tree (build/<preset>/, whose bin/
    is the shipped game). Letter case is ignored (build/ and Build/ are one folder on Windows and macOS)."""
    if not given:
        return False
    p = Path(given)
    where = os.path.realpath(str(p if p.is_absolute() else ROOT / p)).lower()
    for out in build_outputs():
        folder = os.path.realpath(str(ROOT / out)).lower()
        if where == folder or where.startswith(folder.rstrip("\\/") + os.sep):
            print(f"[error] --data-dir {given} is inside {out}/, the build output: its files would ship with the game "
                  f"or be wiped by clean. Use a folder of its own, e.g. captures/{p.name or 'run'}", file=sys.stderr)
            return True
    return False


SHELL_SOURCE = "src/shell/Shell.cpp"   # #271: its "data/..." paths are the shell's data, read from the game's folder


def packed_folders():
    """#271: the folders a packaged game carries next to the exe: assets/ (docs/ENGINE_FLOW.md > Packaging) and the
    shell's data folders, read from the "data/..." paths in SHELL_SOURCE (a file's folder for a file path). The CMake
    build itself copies only inside the build tree (compiled shaders), which data_dir_in_build covers."""
    folders = ["assets"]
    try:
        text = (ROOT / SHELL_SOURCE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for rel in re.findall(r"\"(data/[^\"]+)\"", text):
        rel = rel.rstrip("/")
        folder = rel.rsplit("/", 1)[0] if "." in rel.rsplit("/", 1)[-1] else rel
        if folder not in folders:
            folders.append(folder)
    return folders


def data_dir_in_pack(given):
    """#271: print an error and return True when --data-dir lies inside a folder the packaged game carries
    (packed_folders()). Letter case is ignored."""
    if not given:
        return False
    p = Path(given)
    where = os.path.realpath(str(p if p.is_absolute() else ROOT / p)).lower()
    for rel in packed_folders():
        folder = os.path.realpath(str(ROOT / rel)).lower()
        if where == folder or where.startswith(folder.rstrip("\\/") + os.sep):
            print(f"[error] --data-dir {given} is inside {rel}/, which ships next to the exe (docs/ENGINE_FLOW.md > "
                  f"Packaging): its files would ship with the game. Use a folder of its own, e.g. "
                  f"captures/{p.name or 'run'}", file=sys.stderr)
            return True
    return False


def smoke_data_dir(args):
    """The game's settings folder for this smoke run: --data-dir as given (never wiped), else a fresh SMOKE_DATA/.
    A test run never touches the player's own preferences folder."""
    given = getattr(args, "data_dir", "") or ""
    if given:
        d = Path(given)
        d = (d if d.is_absolute() else ROOT / d).resolve()
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = ROOT / SMOKE_DATA
    if d.exists():
        why = remove_tree(d)
        if why:
            raise OSError(f"{d} not cleared: {why}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def shader_pass(preset):
    """smoke --shaders: kit_shader_check draws every recipe (a GPU), then shader_ref.py compares. Returns 0, 1 or 2."""
    exe = find_exe(preset, SHADER_CHECK_EXE)
    if not exe:
        print(f"[FAIL] {SHADER_CHECK_EXE} not found under build/{preset}/bin/ (is it in CMakeLists.txt?)")
        return 1
    out_dir = ROOT / "build" / preset / "shader_check"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    rc, out = run([exe, out_dir], capture=True, timeout=SHADER_TIMEOUT_S)
    lines = out.splitlines()
    for line in lines:
        if line.startswith(("SHADER_FAIL ", "[error]", "[info]")) or any(m in line for m in ERROR_MARKERS):
            print(("[FAIL] shader " + line[len("SHADER_FAIL "):]) if line.startswith("SHADER_FAIL ") else line)
    if rc in NO_EXEC:
        return 2
    if rc == 124:
        print(f"[FAIL] {SHADER_CHECK_EXE} did not finish within {SHADER_TIMEOUT_S} s")
        return 1
    if rc == 2:
        return 2                            # no GPU renderer on this machine: an environment problem
    if rc != 0 or not any(l.startswith("SHADER_CHECK_DONE ") for l in lines):
        print(f"[FAIL] {SHADER_CHECK_EXE} failed (exit {rc})")
        return 1
    rc, out = run([sys.executable, ROOT / "tools" / "shaders" / "shader_ref.py", "compare", out_dir], capture=True,
                  timeout=SHADER_TIMEOUT_S)
    print(out.rstrip())
    if rc:
        print("[FAIL] a shader recipe differs from its golden image (see the lines above)" if rc == 1 else
              "[error] shader_ref.py compare could not run")
    return rc


def smoke_end_problems(out, frames, until_seen):
    """The end-of-run line main.cpp prints: a run must reach its frame count, unless --until's marker was seen (a
    scenario may end itself there). Without the line the game crashed or exited before its loop ended.
    Returns a list of reasons (empty = fine)."""
    if until_seen:
        return []
    m = None
    for m in END_RE.finditer(out):
        pass                                # the last end line counts
    if m is None:
        return ["no end-of-run line (\"smoke complete after N frames\"): the game exited before its loop ended"]
    if m.group(2) is not None:
        return [f"the game quit after {m.group(2)} of {frames} frames (a run that ends itself needs --until <marker>)"]
    return []


def capture_problems(shot, rec):
    """Each capture asked for must exist after the run (stale ones were deleted before it)."""
    problems = []
    if shot and not (shot.is_file() and shot.stat().st_size > 0):
        problems.append(f"no screenshot written to {shot}")
    if rec and not any(rec.glob("frame_*.bmp")):
        problems.append(f"no frames recorded in {rec}")
    return problems


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


# ---- Frame-time budget (#90): the same block in every engine's dev.py -----------------------------------------
# The game (or smoke.mjs) prints one line at the end of a smoke run:
#   FRAME_TIMES frames=N mean=MS p95=MS p99=MS worst=MS mode=render|software|logic
# smoke prints it as numbers, and fails a run whose p95 is over the budget (--frame-budget, else the "Smoke frame
# time" row of docs/ARCHITECTURE.md). A run that measured nothing says so, and why, instead of passing a budget.
FRAME_LINE = re.compile(r"\bFRAME_TIMES((?:[ \t]+\w+=[^\s=]+)+)")
FRAME_MODES = {                           # what the numbers mean, by the mode= the game reported
    "render": "drawn in a window: a render budget",
    "software": "drawn on the CPU without a display: not a GPU budget",
    "logic": "headless, nothing drawn: a logic budget, not a render budget",
}
BUDGET_DOC = "docs/ARCHITECTURE.md"       # its Budgets table: smoke reads the "Smoke frame time" row
BUDGET_ROW = re.compile(r"^\|\s*Smoke frame time[^|]*\|([^|]*)\|", re.M | re.I)
FRAME_BUDGET_HELP = (f"fail the run when its p95 frame time is over MS milliseconds (default: the 'Smoke frame time' row "
                     f"in {BUDGET_DOC}, when it holds a number); the run prints mean, p95, p99 and worst frame time "
                     "whenever the game measured them")


def frame_times(text):
    """The last FRAME_TIMES line in text as a dict: frames, mean, p95, p99, worst (ms) and mode. None without one."""
    found = None
    for m in FRAME_LINE.finditer(text or ""):
        fields = dict(pair.split("=", 1) for pair in m.group(1).split())
        try:
            stats = {"frames": int(fields["frames"]), "mode": fields.get("mode", "render")}
            for key in ("mean", "p95", "worst"):
                stats[key] = float(fields[key])
            stats["p99"] = float(fields.get("p99", fields["worst"]))
        except (KeyError, ValueError):
            continue                          # a broken line is no measurement
        if stats["frames"] > 0:
            found = stats
    return found


def doc_frame_budget():
    """The frame budget in ms from BUDGET_DOC's "Smoke frame time" row, or None: no file, no row, the template's
    "e.g." placeholder, or no "<number> ms" in the cell."""
    try:
        text = (ROOT / BUDGET_DOC).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = BUDGET_ROW.search(text)
    cell = m.group(1).strip() if m else ""
    if not cell or cell.lower().startswith("e.g"):
        return None
    n = re.search(r"(\d+(?:\.\d+)?)\s*ms\b", cell)
    return float(n.group(1)) if n and float(n.group(1)) > 0 else None


def frame_budget_report(text, budget=None, unmeasured=""):
    """Print the run's frame times and check the p95 against the budget (budget from --frame-budget, else
    doc_frame_budget()). Returns 1 when the p95 is over it, else 0. Without a FRAME_TIMES line it prints why nothing
    was measured (unmeasured) and, with a budget, that the budget was not checked: never a silent pass."""
    source = "--frame-budget" if budget else BUDGET_DOC
    budget = budget or doc_frame_budget()
    stats = frame_times(text)
    if not stats:
        print(f"[info] frame time: not measured ({unmeasured or 'the game printed no FRAME_TIMES line'})")
        if budget:
            print(f"[WARN] frame budget {budget:g} ms ({source}) not checked: this run measured no frame time")
        return 0
    mode = stats["mode"]
    numbers = (f"mean {stats['mean']:.2f} ms, p95 {stats['p95']:.2f} ms, p99 {stats['p99']:.2f} ms, "
               f"worst {stats['worst']:.2f} ms")
    print(f"[info] frame time over {stats['frames']} frames ({mode}, {FRAME_MODES.get(mode, 'unknown mode')}): {numbers}")
    if not budget:
        return 0
    if stats["p95"] > budget:
        print(f"[FAIL] frame budget: p95 {stats['p95']:.2f} ms is over {budget:g} ms ({source}); {numbers}")
        return 1
    print(f"[ OK ] frame budget: p95 {stats['p95']:.2f} ms within {budget:g} ms ({source})")
    return 0


def frame_ms(text):
    """argparse type: a frame budget in milliseconds, above 0 and at most 10000."""
    try:
        n = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of milliseconds")
    if not 0 < n <= 10000:
        raise argparse.ArgumentTypeError("must be above 0 and at most 10000 ms")
    return n


def positive_int(text):
    """argparse type: 1..100000, so a typo cannot ask for a smoke run that never ends."""
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number")
    if not 1 <= n <= 100000:
        raise argparse.ArgumentTypeError("must be between 1 and 100000")
    return n



# ---- Cloud deployments (#252) ------------------------------------------------------------
SHIP_TOOL = "tools/cloud/ship.py"


def split_ship(parser, argv):
    """`dev.py [global options] ship <anything>`: what follows `ship` goes to tools/cloud/ship.py untouched (its own
    --target, --plan ... would trip this parser). Returns (argv for this parser, the ship arguments)."""
    takes_value = {s for a in parser._actions if a.option_strings and a.nargs != 0 for s in a.option_strings}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("-"):
            i += 2 if tok in takes_value else 1
            continue
        return (argv[:i + 1], argv[i + 1:]) if tok == "ship" else (argv, [])
    return argv, []


def cmd_ship(args, *_):
    """Put the game online with tools/cloud/ship.py; a static site and an itch.io push (--target itch) default to this
    engine's web build (SHIP_SITE)."""
    tool = ROOT / SHIP_TOOL
    if not tool.is_file():
        print(f"[error] {SHIP_TOOL} is missing (python scripts/new_game.py --upgrade adds it)", file=sys.stderr)
        return 2
    rest = list(getattr(args, "ship_args", []))
    kind = next((r.split("=", 1)[1] for r in rest if r.startswith("--kind=")), "")
    if "--kind" in rest[:-1]:
        kind = rest[rest.index("--kind") + 1]
    target = next((r.split("=", 1)[1] for r in rest if r.startswith("--target=")), "")
    if "--target" in rest[:-1]:
        target = rest[rest.index("--target") + 1]
    has_site = any(r == "--site" or r.startswith("--site=") for r in rest)   # both spellings argparse takes
    itch = target == "itch" and "--status" not in rest                       # a push or dry run uploads a folder
    if (kind == "static" or itch) and not has_site:
        if SHIP_SITE is None:
            what = "the build folder to push" if itch else "a web build folder"
            print(f"[error] this engine makes no web build of its own: pass --site <{what}>", file=sys.stderr)
            return 2
        rest += ["--site", str(ROOT / SHIP_SITE)]
    try:
        return subprocess.call([sys.executable, str(tool), *rest], cwd=ROOT)
    except OSError as exc:
        print(f"[error] cannot run {SHIP_TOOL}: {exc}", file=sys.stderr)
        return 2


def build_parser():
    ap = argparse.ArgumentParser(
        prog="dev.py",
        description="Project command wrapper (C++/SDL3/CMake). Same commands on every engine in the Claude Code Game Kit.",
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
    p.add_argument("--frames", type=positive_int, default=None,
                   help=f"frames to run at most, 1 to 100000 (default {SMOKE_FRAMES}, {DRIVE_FRAMES} with --drive); "
                        "one game tick per frame")
    p.add_argument("--until", help="fail unless the game prints this marker (scenario runs, e.g. RUN_WON)")
    p.add_argument("--fail-on", help="comma-separated markers that fail the run (e.g. CAUGHT,TIME_UP)")
    p.add_argument("--timeout", type=positive_int, default=SMOKE_TIMEOUT_S,
                   help=f"seconds before a hung game is killed (default {SMOKE_TIMEOUT_S})")
    p.add_argument("--screenshot", help="save the last frame as BMP (path relative to the project)")
    p.add_argument("--record", help="save BMP frames into this folder (GIF: tools/art/frames_to_gif.py)")
    p.add_argument("--record-every", type=positive_int, default=4, help="record every Nth frame (default 4)")
    p.add_argument("--drive", default="", metavar="SCENARIO",
                   help="a scripted path through the shell's screens: menus (change two settings, save, quit; prints "
                        "SETTINGS_WRITTEN), crash (a planted exception: CRASH_WRITTEN, exit 1 on purpose), pseudo (with "
                        "--locale pseudo: every label on every screen, PSEUDO_PASS or PSEUDO_FAIL), pseudo-plant (plus "
                        "one label too small: exit 1), bug (F8: the bug report, DRIVE_BUG), display (the Display tab's "
                        "Apply: stage, warn, apply, the 15 s confirm reverts in real time, discard; DRIVE_DISPLAY lines), "
                        "access[:res=WxH,scale=N,pad,read] (the accessibility sweep's tour, tools/access/sweep.py), "
                        "show:<screen> (title, menu, settings, pause, subtitle, play, juice, credits, apply or confirm: "
                        "opens that screen; add "
                        "--screenshot); "
                        "the run ends at DRIVE_DONE")
    p.add_argument("--data-dir", default="", help="keep settings.json in this folder (relative to the project; kept "
                   f"between runs); default: a fresh {SMOKE_DATA}/ each run, never the player's own folder")
    p.add_argument("--locale", default="", help="language for the run (data/i18n/<LANG>.json)")
    p.add_argument("--shaders", action="store_true",
                   help="also draw every kit shader recipe on the GPU and compare it with its golden image "
                        "(kit_shader_check, tools/shaders/)")
    p.add_argument("--frame-budget", type=frame_ms, metavar="MS", help=FRAME_BUDGET_HELP)
    p.add_argument("--no-build", action="store_true", help="skip the build and run the exe as built (tools/seed_sweep.py: many runs, one build)")
    p.set_defaults(fn=cmd_smoke)
    sub.add_parser("run", help="build then launch the game").set_defaults(fn=cmd_run)
    p = sub.add_parser("clean", help="remove build/")
    p.add_argument("--yes", action="store_true", help="accepted on every engine; C++ clean never asks anyway")
    p.set_defaults(fn=cmd_clean)
    sub.add_parser("ship", help="put the game online with OpenTofu, or upload it to itch.io with butler "
                   "(tools/cloud/ship.py; ship -h for its options)").set_defaults(fn=cmd_ship)
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
    argv, ship_args = split_ship(parser, argv)   # ship's own options go to tools/cloud/ship.py untouched
    game_args = []
    if "--" in argv:                       # everything after `--` is for the game itself (smoke)
        cut = argv.index("--")
        argv, game_args = argv[:cut], argv[cut + 1:]
    args = parser.parse_args(hoist_global_options(parser, argv))
    args.ship_args = ship_args
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

#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dev.py  (Web edition: Phaser 4 + TypeScript + Vite)
# Purpose : The ONE command wrapper for this project. Same subcommands on every
#           engine in the Claude Code Game Kit, so humans and Claude never guess flags.
# Usage   : python tools/dev.py <command> [options]
#             setup    npm install + the headless browser smoke needs (first run, new machine)
#             check    TypeScript type check (tsc --noEmit)
#             test     unit tests (Vitest)
#             smoke    production build, then boot it in headless Chromium; fail on errors
#                      (--query autoplay --until ESCAPED --fail-on CAUGHT for scenario runs,
#                       --screenshot FILE, --record DIR for a GIF;
#                       --drive menus|crash|pseudo|pseudo-plant|show:<screen> for the shell's scripted runs,
#                       --data-dir DIR, --locale ID, --compare BASELINE.png [--tolerance N])
#             build    production build into dist/ (relative paths: upload dist/ anywhere)
#             run      Vite dev server with hot reload (opens the browser)
#             clean    remove dist/ and Vite caches (--deep also removes node_modules/)
#             doctor   verify the local environment
#             ship     put the game online (tools/cloud/ship.py): ship --target aws|azure|gcp|linode|do
#                      --kind static|container --plan, then --apply / --destroy; ship -h for its options
# Env     : none required. NODE_OPTIONS is passed through.
# Exit    : 0 ok, 1 task failed, 2 environment/usage problem
# Notes   : Runs the project-local tools with `node node_modules/...` (no npx, no .cmd shims),
#           so it behaves the same on Windows, macOS and Linux. check/test/smoke/build install
#           dependencies first when node_modules/ is missing or older than package.json.
#           Python 3.8+, standard library only.
#
# Pseudocode:
#   verify node (>= MIN_NODE) -> ensure node_modules -> run the tool -> parse its output
#   for proof (TS error count, Vitest test count, smoke marker) -> exit code
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-30 with Claude (Opus 5.5, claude-opus-5-5): a timeout kills the whole process tree
#           (taskkill /T, or the process group), then waits at most KILL_TIMEOUT_S for the pipe
#           2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): smoke --drive, --data-dir, --locale, --compare
# Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): `run` exits 2 when node or the launcher is
#           not found (it gave 1)
# Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): on Windows a command with a timeout runs in a
#           job object (WinJob), so a timeout also ends a grandchild whose parent already exited
# Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): on Linux and macOS, killing an untimed command
#           (Ctrl+C) also kills what it started, found through ps (it shares our process group)
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
MIN_NODE = (22, 12)                       # Vitest 5 needs ^22.12 || ^24 || >=26; Vite 8 needs 20.19+
SMOKE_FRAMES = 120
BOOT_MARKER = "BOOT_OK"                   # logged by src/shell/app.ts once the title screen is up
# --drive, --data-dir, --locale: the shell (src/shell/drive.ts) runs the scenarios and reads both folders
DRIVE_HELP = ("the game plays a scripted run (shell games): menus, crash (exits 1 on purpose), pseudo, "
              "pseudo-plant, show:title|settings|pause|subtitle|juice (with --screenshot); waits for DRIVE_DONE")
DATA_DIR_HELP = ("user-data folder for this run (?data-dir=): loaded before, written back after "
                 "(default build/smoke-data with --drive)")
LOCALE_HELP = "language for this run, e.g. fr or pseudo (?locale=)"
SMOKE_TIMEOUT_S = 180                     # whole smoke run, including browser start
SMOKE_MIN_FPS = 20                        # slowest headless software rendering we allow for: --frames adds frames/20 s
TEST_TIMEOUT_S = 600
INSTALL_TIMEOUT_S = 900
KILL_TIMEOUT_S = 10                       # after a timeout: seconds to wait for the killed tree's pipe
TOOLS = {                                 # project-local entry points, run with node
    "tsc": "node_modules/typescript/bin/tsc",
    "vite": "node_modules/vite/bin/vite.js",
    "vitest": "node_modules/vitest/vitest.mjs",
    "playwright": "node_modules/playwright/cli.js",
}
NO_EXEC = (126, 127)
SHIP_SITE = "dist"   # the web build `ship --kind static` publishes unless --site is given (None: none)
DEBUG = False


def dbg(msg):
    """Verbose output, only with --debug."""
    if DEBUG:
        print(f"[debug] {msg}")


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


def run(cmd, capture=False, timeout=None):
    """Run a command in the project root. Returns (returncode, output_or_empty).

    124 = timed out (output so far is returned), 126 = not executable, 127 = not found.
    """
    dbg("run: " + " ".join(str(c) for c in cmd))
    sys.stdout.flush()
    try:
        proc = subprocess.Popen(
            [str(c) for c in cmd], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
            start_new_session=NEW_SESSION and timeout is not None,
        )
    except FileNotFoundError as exc:
        print(f"[error] cannot execute {cmd[0]}: {exc}", file=sys.stderr)
        return 127, ""
    except OSError as exc:
        print(f"[error] cannot execute {cmd[0]}: {exc.strerror or exc}", file=sys.stderr)
        return 126, ""
    job = WinJob(proc, timeout)
    try:
        out, _ = proc.communicate(timeout=timeout)
        job.close()                        # a normal exit: anything it left running keeps running
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        kill_tree(proc, job)
        out = reap(proc)
        if isinstance(exc, KeyboardInterrupt):
            print("\n".join((out or "").splitlines()[-20:]))
            raise
        return 124, out or ""
    return proc.returncode, (out or "")


def node_problem():
    """Return an error string if node is missing or too old, else None."""
    node = shutil.which("node")
    if not node:
        return "node not found on PATH. Install Node.js 22 LTS or newer from nodejs.org (it includes npm)."
    rc, out = run([node, "--version"], capture=True, timeout=30)
    m = re.match(r"v(\d+)\.(\d+)", out.strip())
    if rc != 0 or not m:
        return f"could not read the node version ({out.strip() or rc})"
    if (int(m.group(1)), int(m.group(2))) < MIN_NODE:
        return f"node {out.strip()} is too old: this project needs {MIN_NODE[0]}.{MIN_NODE[1]} or newer"
    return None


def deps_stale():
    """True when node_modules is missing or older than package.json / package-lock.json."""
    marker = ROOT / "node_modules" / ".package-lock.json"     # npm rewrites it on every install
    if not marker.exists():
        return True
    newest = max((ROOT / f).stat().st_mtime for f in ("package.json", "package-lock.json") if (ROOT / f).exists())
    return marker.stat().st_mtime < newest


def npm_install():
    """npm ci when a lockfile exists (exact, reproducible), else npm install. Returns 0, 1 or 2."""
    npm = shutil.which("npm")
    if not npm:
        print("[error] npm not found on PATH (it ships with Node.js)", file=sys.stderr)
        return 2
    verb = "ci" if (ROOT / "package-lock.json").exists() else "install"
    print(f"[info] installing dependencies (npm {verb}) ...")
    rc, out = run([npm, verb, "--no-audit", "--no-fund"], capture=True, timeout=INSTALL_TIMEOUT_S)
    if rc != 0:
        print(out[-4000:])
        print(f"[FAIL] npm {verb} failed" + (" (timed out)" if rc == 124 else ""))
        return 2 if rc in NO_EXEC + (124,) else 1
    print(f"[ OK ] dependencies installed (npm {verb})")
    return 0


def ready():
    """Node present and dependencies installed. Returns 0, or an exit code to stop with."""
    err = node_problem()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    if deps_stale():
        return npm_install()
    return 0


def tool(name, *args, capture=True, timeout=None):
    """Run a project-local tool through node. Returns (rc, out); rc 2-style codes for a missing tool."""
    entry = ROOT / TOOLS[name]
    if not entry.exists():
        print(f"[error] {TOOLS[name]} missing: run `python tools/dev.py setup`", file=sys.stderr)
        return 127, ""
    return run([shutil.which("node") or "node", entry, *args], capture=capture, timeout=timeout)


# ---- Commands -----------------------------------------------------------------
def cmd_setup(args):
    err = node_problem()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    rc = npm_install()
    if rc:
        return rc
    print("[info] installing the headless Chromium used by `smoke` (Playwright, about 150 MB, once per machine) ...")
    rc, out = tool("playwright", "install", "chromium", timeout=INSTALL_TIMEOUT_S)
    if rc != 0:
        print(out[-3000:])
        print("[FAIL] browser install failed")
        return 2
    print("[ OK ] setup done: try `python tools/dev.py run`")
    return 0


def cmd_check(args):
    rc = ready()
    if rc:
        return rc
    rc, out = tool("tsc", "--noEmit", "-p", "tsconfig.json", timeout=TEST_TIMEOUT_S)
    if rc in NO_EXEC:
        return 2
    errors = [l for l in out.splitlines() if re.search(r"error TS\d+", l)]
    if rc != 0 or errors:
        print(out.rstrip())
        print(f"[FAIL] type check: {len(errors) or 'unknown number of'} error(s)")
        return 1
    print("[ OK ] type check passed")
    if (ROOT / "src" / "shaders" / "kit").is_dir() and not getattr(args, "no_shaders", False):
        # the kit's shader recipes: the generated files current, and every fragment shader compiles (headless Chromium)
        rc, out = run([sys.executable, ROOT / "tools" / "shaders" / "shader_gen.py", "--check"], capture=True, timeout=60)
        if rc != 0:
            print(out.rstrip())
            if rc == 2:                       # the recipes themselves cannot be read: not a stale file
                print("[error] tools/shaders/shader_gen.py could not read the recipes (see above)")
                return 2
            print("[FAIL] the shader files are older than their recipes: python tools/shaders/shader_gen.py")
            return 1
        rc, out = run([shutil.which("node") or "node", ROOT / "tools" / "shader_compile.mjs"], capture=True, timeout=120)
        print(out.rstrip())
        if rc:
            return 2 if rc == 2 else 1
    return 0


def cmd_test(args):
    rc = ready()
    if rc:
        return rc
    rc, out = tool("vitest", "run", "--reporter=default", timeout=TEST_TIMEOUT_S)
    print(out.rstrip())
    if rc in NO_EXEC:
        return 2
    if rc == 124:
        print(f"[FAIL] tests did not finish within {TEST_TIMEOUT_S} s")
        return 1
    if re.search(r"No test files found", out):
        print("[FAIL] no tests ran (nothing matches tests/**/*.test.ts)")
        return 2
    m = re.search(r"Tests\s+(?:(\d+) failed \| )?(\d+) passed", out)
    if rc != 0 or not m:
        print("[FAIL] tests failed")
        return 1
    print(f"[ OK ] {m.group(2)} test(s) passed")
    return 0


def cmd_build(args):
    rc = ready()
    if rc:
        return rc
    rc, out = tool("vite", "build", "--logLevel", "warn" if not DEBUG else "info", timeout=TEST_TIMEOUT_S)
    if rc in NO_EXEC:
        return 2
    if rc != 0 or not (ROOT / "dist" / "index.html").exists():
        print(out.rstrip())
        print("[FAIL] build failed")
        return 1
    if DEBUG and out.strip():
        print(out.rstrip())
    size = sum(p.stat().st_size for p in (ROOT / "dist").rglob("*") if p.is_file())
    print(f"[ OK ] built dist/ ({size // 1024} KB). Upload the dist/ folder (zip its contents for itch.io).")
    return 0


def data_dir_in_build(given):
    """#263: print an error and return True when --data-dir lies inside dist/ (the build `build` writes and players
    get). Letter case is ignored (DIST is dist/ on Windows and macOS). smoke.mjs also refuses the project's own
    folders (src/, public/, ...); this check runs before the build."""
    if not given:
        return False
    p = Path(given)
    where = os.path.realpath(str(p if p.is_absolute() else ROOT / p)).lower()
    folder = os.path.realpath(str(ROOT / "dist")).lower()
    if where == folder or where.startswith(folder.rstrip("\\/") + os.sep):
        print(f"[error] --data-dir {given} is inside dist/, the build output: its files would ship with the game. "
              f"Use a folder of its own, e.g. build/{p.name or 'run'}", file=sys.stderr)
        return True
    return False


VITE_CONFIG = "vite.config.ts"   # #271: its publicDir (default public/) is copied into dist/ as is


def packed_folders():
    """#271: the folders `build` copies into dist/: vite's publicDir (read from VITE_CONFIG; `publicDir: false` turns
    it off) and the folders src/ reads with import.meta.glob (bundled; each up to its first wildcard)."""
    folders = []
    try:
        config = (ROOT / VITE_CONFIG).read_text(encoding="utf-8", errors="replace")
    except OSError:
        config = ""
    m = re.search(r"\bpublicDir\s*:\s*(false\b|[\"'`]([^\"'`]+)[\"'`])", config)
    if not m:
        folders.append("public")
    elif m.group(2):
        folders.append(m.group(2))
    sources = sorted((ROOT / "src").rglob("*")) if (ROOT / "src").is_dir() else []
    for src in sources:
        if src.suffix not in (".ts", ".tsx", ".js", ".mjs", ".jsx") or not src.is_file():
            continue
        text = src.read_text(encoding="utf-8", errors="replace")
        for pattern in re.findall(r"import\.meta\.glob\s*\(\s*[\"'`]([^\"'`]+)[\"'`]", text):
            parts = pattern.split("/")
            fixed = []
            for part in parts:
                if any(c in part for c in "*?[{"):
                    break
                fixed.append(part)
            if len(fixed) == len(parts):
                continue                              # one file, not a folder
            base = ROOT if pattern.startswith("/") else src.parent
            folder = os.path.normpath(str(base / "/".join(fixed).lstrip("/")))
            rel = os.path.relpath(folder, str(ROOT)).replace("\\", "/")
            if rel != "." and not rel.startswith("../") and rel not in folders:
                folders.append(rel)
    return folders


def data_dir_in_pack(given):
    """#271: print an error and return True when --data-dir lies inside a folder `build` copies into dist/
    (packed_folders()), where its files would ship with the next build. Letter case is ignored."""
    if not given:
        return False
    p = Path(given)
    where = os.path.realpath(str(p if p.is_absolute() else ROOT / p)).lower()
    for rel in packed_folders():
        folder = os.path.realpath(str(ROOT / rel)).lower()
        if where == folder or where.startswith(folder.rstrip("\\/") + os.sep):
            print(f"[error] --data-dir {given} is inside {rel}/, which `build` copies into dist/: its files would ship "
                  f"with the game. Use a folder of its own, e.g. build/{p.name or 'run'}", file=sys.stderr)
            return True
    return False


def cmd_smoke(args):
    if data_dir_in_build(args.data_dir):
        return 2
    if data_dir_in_pack(args.data_dir):   # #271: a folder the build copies into dist/
        return 2
    rc = cmd_build(args)
    if rc:
        return rc
    cmd = [shutil.which("node") or "node", ROOT / "tools" / "smoke.mjs", "--frames", str(args.frames),
           "--marker", BOOT_MARKER, "--timeout-ms", str(args.timeout * 1000)] + (["--verbose"] if DEBUG else [])
    for flag, value in (("--query", args.query), ("--until", args.until), ("--fail-on", args.fail_on),
                        ("--screenshot", args.screenshot), ("--record", args.record),
                        ("--record-every", str(args.record_every) if args.record else ""),
                        ("--drive", args.drive), ("--data-dir", args.data_dir), ("--locale", args.locale),
                        ("--compare", args.compare), ("--tolerance", str(args.tolerance) if args.compare else "")):
        if value:
            cmd += [flag, value]
    if args.shaders:
        cmd += ["--shaders"]
    if args.compare or args.shaders:
        cmd += ["--python", sys.executable]           # tools/image_diff.py and shader_ref.py run on this Python
    cmd += (["--headed"] if args.headed else []) + (["--gpu"] if args.gpu else [])
    limit = SMOKE_TIMEOUT_S + args.timeout + args.frames // SMOKE_MIN_FPS   # a long --frames gets the time it needs
    rc, out = run(cmd, capture=True, timeout=limit)
    print(out.rstrip())
    if rc == 124:
        print(f"[FAIL] smoke did not finish within {limit} s")
        return 1
    if rc == 2 or rc in NO_EXEC:
        return 2
    if rc != 0 or "[ OK ]" not in out:
        return 1
    return 0


def cmd_run(args):
    rc = ready()
    if rc:
        return rc
    print("[info] dev server with hot reload; Ctrl+C to stop. Add ?debug to the URL for debug logs.")
    rc, _ = tool("vite", "--open", capture=False)
    if rc in NO_EXEC:
        return 2                            # node or the launcher was not found: an environment problem
    return 0 if rc in (0, 130) else 1


def remove_tree(path):
    """Delete a folder for real. Returns None on success, else a reason."""
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return "it is a link/junction; remove the link by hand if that is what you want"
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        left = sum(1 for _ in path.rglob("*"))
        return f"{left} item(s) could not be deleted (stop the dev server or editor holding them)"
    return None


def cmd_clean(args):
    targets = [ROOT / "dist", ROOT / "node_modules" / ".vite", ROOT / "node_modules" / ".vitest"]
    if args.deep:
        targets.append(ROOT / "node_modules")
    failed = 0
    removed = []
    for t in targets:
        if not t.exists():
            continue
        why = remove_tree(t)
        if why:
            print(f"[FAIL] {t.relative_to(ROOT).as_posix()}/ not removed: {why}")
            failed += 1
        else:
            removed.append(t.relative_to(ROOT).as_posix() + "/")
    print(f"[ OK ] removed {', '.join(removed)}" if removed else "[info] nothing to clean")
    if args.deep and not failed:
        print("[info] node_modules/ is gone: the next command reinstalls it (python tools/dev.py setup)")
    return 1 if failed else 0


def cmd_doctor(args):
    problems = 0
    print(f"[info] python {sys.version.split()[0]}")
    err = node_problem()
    if err:
        print(f"[FAIL] node: {err}")
        problems += 1
    else:
        _, out = run([shutil.which("node"), "--version"], capture=True, timeout=30)
        print(f"[ OK ] node {out.strip()}")
    npm = shutil.which("npm")
    print(f"[{' OK ' if npm else 'FAIL'}] npm: {npm or 'not found'}")
    problems += 0 if npm else 1
    git = shutil.which("git")
    print(f"[{' OK ' if git else 'WARN'}] git: {git or 'not found'}")
    if not (ROOT / "node_modules").exists():
        print("[FAIL] node_modules/ missing: run `python tools/dev.py setup`")
        problems += 1
    elif deps_stale():
        print("[WARN] node_modules/ is older than package.json: the next command reinstalls")
    else:
        print("[ OK ] dependencies installed")
        for name, rel in TOOLS.items():
            if not (ROOT / rel).exists():
                print(f"[FAIL] {name} missing ({rel})")
                problems += 1
        rc, out = run([shutil.which("node") or "node", "-e",
                       "const p=require('playwright').chromium.executablePath();"
                       "console.log(require('fs').existsSync(p)?'ok '+p:'missing '+p)"], capture=True, timeout=60)
        if out.startswith("ok "):
            print(f"[ OK ] headless Chromium for smoke: {out[3:].strip()}")
        else:
            print("[FAIL] headless Chromium for smoke not installed: run `python tools/dev.py setup`")
            problems += 1
    if not (ROOT / "package-lock.json").exists():
        print("[WARN] no package-lock.json yet: the first install creates it. Commit it (exact, reproducible installs).")
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


def channel_delta(text):
    """argparse type: 0..255, a per-channel color difference."""
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number")
    if not 0 <= n <= 255:
        raise argparse.ArgumentTypeError("must be between 0 and 255")
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
    """Put the game online with tools/cloud/ship.py; a static site defaults to this engine's web build (SHIP_SITE)."""
    tool = ROOT / SHIP_TOOL
    if not tool.is_file():
        print(f"[error] {SHIP_TOOL} is missing (python scripts/new_game.py --upgrade adds it)", file=sys.stderr)
        return 2
    rest = list(getattr(args, "ship_args", []))
    kind = next((r.split("=", 1)[1] for r in rest if r.startswith("--kind=")), "")
    if "--kind" in rest[:-1]:
        kind = rest[rest.index("--kind") + 1]
    has_site = any(r == "--site" or r.startswith("--site=") for r in rest)   # both spellings argparse takes
    if kind == "static" and not has_site:
        if SHIP_SITE is None:
            print("[error] this engine makes no web build of its own: pass --site <a web build folder>", file=sys.stderr)
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
        description="Project command wrapper (Web: Phaser 4 + TypeScript + Vite). Same commands on every engine in the Claude Code Game Kit.",
        epilog="Needs Node.js 22.12+ (with npm). Exit codes: 0 ok, 1 failed, 2 environment/usage problem.",
    )
    ap.add_argument("--debug", action="store_true", help="verbose output (full tool output, every console line in smoke)")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    sub.required = True
    sub.add_parser("setup", help="install dependencies and the headless browser (first run)").set_defaults(fn=cmd_setup)
    p = sub.add_parser("check", help="TypeScript type check, and compile the kit's shader recipes (headless Chromium)")
    p.add_argument("--no-shaders", action="store_true", help="skip the shader compile")
    p.set_defaults(fn=cmd_check)
    sub.add_parser("test", help="unit tests (Vitest)").set_defaults(fn=cmd_test)
    p = sub.add_parser("smoke", help="build, then boot in headless Chromium for N frames; fail on errors")
    p.add_argument("--frames", type=positive_int, default=SMOKE_FRAMES,
                   help=f"animation frames to run after boot, 1 to 100000 (default {SMOKE_FRAMES}; the run allows frames/{SMOKE_MIN_FPS} s extra)")
    p.add_argument("--query", default="", help="URL query for the page, e.g. autoplay or autoplay&debug (scenario runs)")
    p.add_argument("--until", default="", help="wait for this console marker instead of --frames (e.g. ESCAPED)")
    p.add_argument("--fail-on", default="", help="comma-separated console markers that fail the run (e.g. CAUGHT)")
    p.add_argument("--timeout", type=positive_int, default=30, help="seconds to wait for each marker; also lengthens the whole run (default 30)")
    p.add_argument("--screenshot", default="", help="save a PNG of the final frame (path relative to the project)")
    p.add_argument("--record", default="", help="save PNG frames to this folder (GIF: tools/art/frames_to_gif.py)")
    p.add_argument("--record-every", type=positive_int, default=66, help="milliseconds between recorded frames (default 66)")
    p.add_argument("--drive", default="", metavar="SCENARIO", help=DRIVE_HELP)
    p.add_argument("--data-dir", default="", metavar="DIR", help=DATA_DIR_HELP)
    p.add_argument("--locale", default="", metavar="ID", help=LOCALE_HELP)
    p.add_argument("--compare", default="", metavar="PNG", help="compare the --screenshot with this baseline (tools/image_diff.py); exit 1 when it differs")
    p.add_argument("--tolerance", type=channel_delta, default=0, help="--compare: per-channel difference allowed, 0-255 (default 0)")
    p.add_argument("--shaders", action="store_true",
                   help="also render every kit shader recipe and compare it with its golden image (tools/shaders/)")
    p.add_argument("--headed", action="store_true", help="visible browser window (real GPU: WebGPU, local AI models)")
    p.add_argument("--gpu", action="store_true", help="headless with Chrome's WebGPU flags (may not work on every machine)")
    p.set_defaults(fn=cmd_smoke)
    sub.add_parser("build", help="production build into dist/").set_defaults(fn=cmd_build)
    sub.add_parser("run", help="dev server with hot reload").set_defaults(fn=cmd_run)
    p = sub.add_parser("clean", help="remove dist/ and Vite caches")
    p.add_argument("--deep", action="store_true", help="also remove node_modules/ (reinstalled on the next command)")
    p.add_argument("--yes", action="store_true", help="accepted on every engine; web clean never asks")
    p.set_defaults(fn=cmd_clean)
    sub.add_parser("ship", help="put the game online with OpenTofu (tools/cloud/ship.py; ship -h for its options)").set_defaults(fn=cmd_ship)
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
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else list(argv)
    argv, ship_args = split_ship(parser, argv)   # ship's own options go to tools/cloud/ship.py untouched
    args = parser.parse_args(hoist_global_options(parser, argv))
    args.ship_args = ship_args
    DEBUG = args.debug
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        print("\n[abort] interrupted")
        return 1
    except OSError as exc:
        where = f" {exc.filename}" if exc.filename else ""
        print(f"[error] {exc.strerror or exc}{where} (close any program holding it and retry)", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2
    except Exception as exc:
        print(f"[error] unexpected failure in '{args.command}': {exc!r}. Re-run with --debug.", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

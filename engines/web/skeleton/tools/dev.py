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
#                       --screenshot FILE, --record DIR for a GIF)
#             build    production build into dist/ (relative paths: upload dist/ anywhere)
#             run      Vite dev server with hot reload (opens the browser)
#             clean    remove dist/ and Vite caches (--deep also removes node_modules/)
#             doctor   verify the local environment
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
# ---------------------------------------------------------------------------
import argparse
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---- Tunables / constants ----------------------------------------------------
MIN_NODE = (22, 12)                       # Vitest 5 needs ^22.12 || ^24 || >=26; Vite 8 needs 20.19+
SMOKE_FRAMES = 120
BOOT_MARKER = "BOOT_OK"                   # logged by src/game/MainScene.ts
SMOKE_TIMEOUT_S = 180                     # whole smoke run, including browser start
SMOKE_MIN_FPS = 20                        # slowest headless software rendering we allow for: --frames adds frames/20 s
TEST_TIMEOUT_S = 600
INSTALL_TIMEOUT_S = 900
TOOLS = {                                 # project-local entry points, run with node
    "tsc": "node_modules/typescript/bin/tsc",
    "vite": "node_modules/vite/bin/vite.js",
    "vitest": "node_modules/vitest/vitest.mjs",
    "playwright": "node_modules/playwright/cli.js",
}
NO_EXEC = (126, 127)
DEBUG = False


def dbg(msg):
    """Verbose output, only with --debug."""
    if DEBUG:
        print(f"[debug] {msg}")


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
        )
    except FileNotFoundError as exc:
        print(f"[error] cannot execute {cmd[0]}: {exc}", file=sys.stderr)
        return 127, ""
    except OSError as exc:
        print(f"[error] cannot execute {cmd[0]}: {exc.strerror or exc}", file=sys.stderr)
        return 126, ""
    try:
        out, _ = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        proc.kill()
        out, _ = proc.communicate()
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


def cmd_smoke(args):
    rc = cmd_build(args)
    if rc:
        return rc
    cmd = [shutil.which("node") or "node", ROOT / "tools" / "smoke.mjs", "--frames", str(args.frames),
           "--marker", BOOT_MARKER, "--timeout-ms", str(args.timeout * 1000)] + (["--verbose"] if DEBUG else [])
    for flag, value in (("--query", args.query), ("--until", args.until), ("--fail-on", args.fail_on),
                        ("--screenshot", args.screenshot), ("--record", args.record),
                        ("--record-every", str(args.record_every) if args.record else "")):
        if value:
            cmd += [flag, value]
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
    sub.add_parser("check", help="TypeScript type check").set_defaults(fn=cmd_check)
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
    p.add_argument("--headed", action="store_true", help="visible browser window (real GPU: WebGPU, local AI models)")
    p.add_argument("--gpu", action="store_true", help="headless with Chrome's WebGPU flags (may not work on every machine)")
    p.set_defaults(fn=cmd_smoke)
    sub.add_parser("build", help="production build into dist/").set_defaults(fn=cmd_build)
    sub.add_parser("run", help="dev server with hot reload").set_defaults(fn=cmd_run)
    p = sub.add_parser("clean", help="remove dist/ and Vite caches")
    p.add_argument("--deep", action="store_true", help="also remove node_modules/ (reinstalled on the next command)")
    p.add_argument("--yes", action="store_true", help="accepted on every engine; web clean never asks")
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
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else list(argv)
    args = parser.parse_args(hoist_global_options(parser, argv))
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

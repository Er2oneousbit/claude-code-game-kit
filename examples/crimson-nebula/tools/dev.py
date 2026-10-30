#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dev.py  (Bevy / Rust / cargo edition)
# Purpose : The ONE command wrapper for this project. Same subcommands on every
#           engine in the Claude Code Game Kit, so humans and Claude never guess flags.
# Usage   : python tools/dev.py [--release] <command> [options]
#             check    cargo fmt --check, then clippy (or cargo check) on every target
#             test     build + run the tests (cargo test: unit tests and tests/ headless Apps)
#             smoke    run the game headless for N frames, fail on errors; scenario runs:
#                      smoke --frames 3000 --until GOAL_REACHED --fail-on CRASHED -- --autoplay right
#                      (after `--`: options for the game; --screenshot / --record open a window and capture PNGs)
#             build    release build (cargo build --release), prints where the exe is
#             run      launch the game in a window (cargo run)
#             clean    remove the cargo target folder (asks first if it lies outside the project; refuses
#                      the project folder itself, its parents and folders without cargo's CACHEDIR.TAG)
#             doctor   verify the local environment
# Env     : CARGO_TARGET_DIR  optional shared build folder (cargo's own variable; dev.py follows it)
#           RUSTUP_TOOLCHAIN  optional, pick a toolchain for one run (rustup's own variable)
# Exit    : 0 ok, 1 task failed, 2 environment/usage problem
# Notes   : Builds run uncaptured (cargo's progress shows; the first Bevy build takes minutes), then the
#           tests or the game run captured with a timeout so the output can be checked. Python 3.8+,
#           standard library only.
#
# Pseudocode:
#   parse args -> verify cargo -> (check) fmt + clippy | (test) cargo test --no-run, then cargo test,
#   count "test result" lines | (smoke) cargo build, then cargo run -- --smoke N, scan the output for
#   BOOT_OK, SMOKE_DONE, error lines and scenario markers
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-30 with Claude (Opus 5.5, claude-opus-5-5): a timeout kills the whole process tree
#           (taskkill /T, or the process group), then waits at most KILL_TIMEOUT_S for the pipe
#           clean refuses a target folder that is the project or above it, or that cargo did not make
#           (no CACHEDIR.TAG), since .cargo/config.toml or CARGO_TARGET_DIR can point it anywhere
# ---------------------------------------------------------------------------
import argparse
import json
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
DONE_MARKER = "SMOKE_DONE"                 # the game prints it after its last frame: proof the frames ran
ERROR_MARKERS = [" ERROR ", "panicked at", "error: process didn't exit successfully"]
SMOKE_TIMEOUT_S = 120                      # a game that hangs must fail, not block forever (build time not included)
TEST_TIMEOUT_S = 600
BUILD_TIMEOUT_S = 3600                     # first Bevy build: 5 to 15 minutes on a fast machine, far more on a slow one
KILL_TIMEOUT_S = 10                        # after a timeout: seconds to wait for the killed tree's pipe
NO_EXEC = (126, 127)                       # run() codes: not executable / not found -> environment problem (exit 2)
MIN_RUST = (1, 97, 1)                      # Bevy 0.20's rust-version (Cargo.toml); keep in step when Bevy moves
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
DEBUG = False


def dbg(msg):
    """Verbose output, only with --debug."""
    if DEBUG:
        print(f"[debug] {msg}")


def quiet_env():
    """Environment for captured runs: no colour codes in the text we scan."""
    return dict(os.environ, CARGO_TERM_COLOR="never", NO_COLOR="1")


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
        print(f"[error] cannot execute {cmd[0]}: {exc.strerror or exc}", file=sys.stderr)
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
    return proc.returncode, ANSI.sub("", out or "")


def cargo():
    """Path to cargo, or None. rustup puts it in ~/.cargo/bin, which a terminal opened before the install lacks."""
    found = shutil.which("cargo")
    if found:
        return found
    home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")) / "bin"
    for name in ("cargo.exe", "cargo"):
        if (home / name).is_file():
            return str(home / name)
    return None


def preflight():
    """Return an error string if the toolchain is unusable, else None."""
    if not cargo():
        return ("cargo not found. Install Rust with rustup (https://rustup.rs), then open a NEW terminal "
                "(or restart Claude Code) so PATH includes ~/.cargo/bin.")
    if not (ROOT / "Cargo.toml").is_file():
        return f"no Cargo.toml in {ROOT}"
    return None


def profile_flags(args):
    return ["--release"] if args.release else []


def build(args, extra=()):
    """cargo build (uncaptured, so progress shows). Returns 0, 1 or 2."""
    rc, _ = run([cargo(), "build", *profile_flags(args), *extra], timeout=BUILD_TIMEOUT_S)
    if rc in NO_EXEC:
        return 2
    if rc == 124:
        print(f"[FAIL] build did not finish within {BUILD_TIMEOUT_S} s")
        return 1
    if rc != 0:
        print("[FAIL] build failed (the compiler's message above names the file and line)")
        return 1
    return 0


def target_dir():
    """The folder cargo builds into (honours CARGO_TARGET_DIR and .cargo/config.toml)."""
    rc, out = run([cargo(), "metadata", "--format-version", "1", "--no-deps"], env=quiet_env(), capture=True,
                  timeout=120)
    if rc == 0:
        try:
            return Path(json.loads(out[out.index("{"):])["target_directory"])
        except (ValueError, KeyError):
            pass
    return ROOT / "target"


def unsafe_target(target):
    """Why `clean` must not delete target, or None. A repo-controlled .cargo/config.toml (target-dir = ".")
    or CARGO_TARGET_DIR can point cargo at the project itself, or at a folder above it."""
    resolved = target.resolve()
    key = os.path.normcase(str(resolved))  # Windows paths compare case-insensitively
    root = ROOT.resolve()
    if key in (os.path.normcase(str(p)) for p in [root, *root.parents]):
        return ("it is the project folder or contains it (check target-dir in .cargo/config.toml and "
                "CARGO_TARGET_DIR; give the build a folder of its own)")
    if not resolved.is_dir():
        return "not a folder"
    # cargo writes CACHEDIR.TAG into every target folder it builds in; an empty folder is safe too
    if not (resolved / "CACHEDIR.TAG").is_file() and any(resolved.iterdir()):
        return "it has no CACHEDIR.TAG, so cargo did not make it (delete it by hand if you are sure)"
    return None


def bin_name():
    """The game's executable name: [package] name in Cargo.toml (cargo keeps hyphens in binary names)."""
    try:
        text = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
        m = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            return m.group(1)
    except OSError:
        pass
    return ROOT.name


# ---- Commands -----------------------------------------------------------------
def cmd_check(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    rc, out = run([cargo(), "fmt", "--check"], env=quiet_env(), capture=True, timeout=300)
    if rc in NO_EXEC or "no such command" in out or "not installed" in out:
        print("[WARN] rustfmt missing (rustup component add rustfmt); formatting not checked")
    elif rc != 0:
        print("\n".join(out.splitlines()[:40]))
        print("[FAIL] code is not formatted: run `cargo fmt`, then check again")
        return 1
    rc, out = run([cargo(), "clippy", "--version"], env=quiet_env(), capture=True, timeout=60)
    tool = ["clippy"] if rc == 0 else ["check"]
    if rc != 0:
        print("[WARN] clippy missing (rustup component add clippy); running cargo check instead")
    rc, out = run([cargo(), *tool, "--all-targets", *profile_flags(args)], env=quiet_env(), capture=True,
                  timeout=BUILD_TIMEOUT_S)
    print(out.rstrip())
    if rc in NO_EXEC:
        return 2
    if rc == 124:
        print(f"[FAIL] cargo {tool[0]} did not finish within {BUILD_TIMEOUT_S} s")
        return 1
    if rc != 0:
        print(f"[FAIL] cargo {tool[0]} found errors")
        return 1
    warnings = len(re.findall(r"^warning: (?!.*generated \d+ warning)", out, re.MULTILINE))
    print(f"[ OK ] compiled (cargo {tool[0]})" + (f", {warnings} warning(s) to look at" if warnings else ""))
    return 0


def cmd_test(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    rc, _ = run([cargo(), "test", "--no-run", *profile_flags(args)], timeout=BUILD_TIMEOUT_S)
    if rc in NO_EXEC:
        return 2
    if rc != 0:
        print("[FAIL] tests do not compile" if rc != 124 else f"[FAIL] test build took over {BUILD_TIMEOUT_S} s")
        return 1
    rc, out = run([cargo(), "test", *profile_flags(args)], env=quiet_env(), capture=True, timeout=TEST_TIMEOUT_S)
    print(out.rstrip())
    if rc in NO_EXEC:
        return 2
    if rc == 124:
        print(f"[FAIL] tests did not finish within {TEST_TIMEOUT_S} s")
        return 1
    results = re.findall(r"test result: (\w+)\. (\d+) passed; (\d+) failed; (\d+) ignored", out)
    passed = sum(int(p) for _, p, _, _ in results)
    failed = sum(int(f) for _, _, f, _ in results)
    if rc != 0 or failed:
        print(f"[FAIL] {failed} test(s) failed" if failed else f"[FAIL] cargo test exit code {rc}")
        return 1
    if passed == 0:
        print("[FAIL] no tests ran (none written, or all ignored)")
        return 2
    print(f"[ OK ] {passed} test(s) passed")
    return 0


def cmd_smoke(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    rc = build(args)
    if rc != 0:
        return rc
    game = ["--smoke", str(args.frames)]
    if args.screenshot:
        shot = (ROOT / args.screenshot).resolve()
        shot.parent.mkdir(parents=True, exist_ok=True)
        game += ["--screenshot", str(shot)]
    if args.record:
        rec = (ROOT / args.record).resolve()
        rec.mkdir(parents=True, exist_ok=True)
        game += ["--record", str(rec), "--record-every", str(args.record_every), "--record-from", str(args.record_from)]
    if args.game_args:
        game += ["--"] + args.game_args
    cmd = [cargo(), "run", "--quiet", *profile_flags(args), "--"] + game
    rc, out = run(cmd, env=quiet_env(), capture=True, timeout=args.timeout)
    if DEBUG or rc != 0:
        print(out)
    if rc in NO_EXEC:
        return 2
    if rc == 124:
        print(f"[FAIL] game did not exit within {args.timeout} s (a hang, or raise --timeout)")
        return 1
    if rc == 2 and BOOT_MARKER not in out:
        print("[error] the game refused its command line (see its message above): a usage problem, not a bug")
        return 2
    lines = out.splitlines()
    errors = [l for l in lines if any(m in l for m in ERROR_MARKERS)]
    fail_on = [m for m in (args.fail_on or "").split(",") if m]
    bad = [l for l in lines if any(m in l for m in fail_on)]
    missing_until = bool(args.until) and not any(args.until in l for l in lines)
    if rc != 0 or errors or bad or missing_until or BOOT_MARKER not in out or DONE_MARKER not in out:
        if errors:
            print("[FAIL] errors during smoke:\n  " + "\n  ".join(errors[:10]))
        if bad:
            print("[FAIL] --fail-on marker seen:\n  " + "\n  ".join(bad[:5]))
        if missing_until:
            print(f"[FAIL] marker {args.until!r} not seen within {args.frames} frames")
        for marker in (BOOT_MARKER, DONE_MARKER):
            if marker not in out:
                print(f"[FAIL] marker {marker!r} not seen")
        if rc != 0:
            print(f"[FAIL] exit code {rc}")
        return 1
    what = f"marker {args.until!r} reached" if args.until else f"{args.frames} frames"
    print(f"[ OK ] smoke passed ({what})")
    if args.screenshot:
        print(f"[ OK ] screenshot: {(ROOT / args.screenshot).resolve()}")
    if args.record:
        n = len(list((ROOT / args.record).glob("*.png")))
        print(f"[ OK ] {n} frame(s) in {(ROOT / args.record).resolve()} (GIF: python tools/art/frames_to_gif.py <dir> out.gif)")
    return 0


def cmd_build(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    args.release = True                    # `build` is the shipping build; `check` covers the debug one
    rc = build(args)
    if rc != 0:
        return rc
    exe = target_dir() / "release" / (bin_name() + (".exe" if os.name == "nt" else ""))
    if not exe.is_file():
        print(f"[FAIL] build reported success but {exe} is missing")
        return 1
    print(f"[ OK ] release build: {exe} (ship it with assets/ next to it, docs/ENGINE_FLOW.md > Packaging)")
    return 0


def cmd_run(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    rc = build(args)
    if rc != 0:
        return rc
    game = (["--debug"] if args.debug else []) + (["--"] + args.game_args if args.game_args else [])
    rc, _ = run([cargo(), "run", "--quiet", *profile_flags(args), "--"] + game)
    return 2 if rc in NO_EXEC else 0 if rc == 0 else 1


def remove_tree(path):
    """Delete a folder for real. Returns None on success, else a reason (nothing is reported as removed)."""
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return "it is a link/junction; remove the link by hand if that is what you want"
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        left = sum(1 for _ in path.rglob("*"))
        return f"{left} item(s) could not be deleted (close the game, rust-analyzer or the IDE holding them)"
    return None


def cmd_clean(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    target = target_dir()
    if not target.exists():
        print("[info] nothing to clean")
        return 0
    why = unsafe_target(target)
    if why:
        print(f"[error] refusing to delete {target}: {why}", file=sys.stderr)
        return 2
    inside = ROOT in target.resolve().parents
    if not inside and not args.yes:
        # A shared CARGO_TARGET_DIR holds other projects' builds too: ask, and never hang waiting for an answer
        if sys.stdin is None or not sys.stdin.isatty():
            print(f"[error] {target} is outside the project (shared by other projects?). Non-interactive shell: "
                  "re-run with clean --yes", file=sys.stderr)
            return 2
        try:
            answer = input(f"{target} is outside the project. Delete it anyway? [y/N] ")
        except EOFError:
            print("\n[error] no answer available (stdin closed). Re-run with: clean --yes", file=sys.stderr)
            return 2
        if answer.strip().lower() != "y":
            print("[abort] nothing deleted")
            return 1
    why = remove_tree(target)
    if why:
        print(f"[FAIL] {target} not removed: {why}")
        return 1
    print(f"[ OK ] removed {target} (the next build compiles Bevy again: minutes)")
    return 0


def version_tuple(text):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def msvc_found():
    """Windows: the MSVC linker rustc needs. rustc finds Visual Studio itself, so look where it looks (vswhere)."""
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / \
        "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.is_file():
        return None
    rc, out = run([vswhere, "-products", "*", "-latest", "-requires",
                   "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                  capture=True, timeout=60)
    return (out.strip() or None) if rc == 0 else None


def cmd_doctor(args):
    problems = 0
    print(f"[info] python {sys.version.split()[0]}")
    c = cargo()
    print(f"[{' OK ' if c else 'FAIL'}] cargo: {c or 'not found (install Rust: https://rustup.rs)'}")
    problems += 0 if c else 1
    if c:
        rustc = Path(c).with_name("rustc.exe" if os.name == "nt" else "rustc")
        rc, out = run([rustc if rustc.is_file() else "rustc", "--version"], env=quiet_env(), capture=True, timeout=60)
        have = version_tuple(out) if rc == 0 else None
        ok = bool(have) and have >= MIN_RUST
        need = ".".join(map(str, MIN_RUST))
        print(f"[{' OK ' if ok else 'FAIL'}] rustc: {out.strip() or 'not runnable'}"
              + ("" if ok else f" (Bevy needs {need}+: rustup update stable)"))
        problems += 0 if ok else 1
        for comp in ("clippy", "fmt"):
            rc, _ = run([c, comp, "--version"], env=quiet_env(), capture=True, timeout=60)
            print(f"[{' OK ' if rc == 0 else 'WARN'}] cargo {comp}: "
                  + ("found" if rc == 0 else f"missing (rustup component add {'rustfmt' if comp == 'fmt' else comp})"))
    p = shutil.which("git")
    print(f"[{' OK ' if p else 'FAIL'}] git: {p or 'not found'}")
    problems += 0 if p else 1
    if os.name == "nt":
        vs = msvc_found()
        print(f"[{' OK ' if vs else 'FAIL'}] MSVC build tools: {vs or 'not found. Install Build Tools for Visual Studio, workload Desktop development with C++'}")
        problems += 0 if vs else 1
    elif sys.platform.startswith("linux"):
        for pkg in ("alsa", "libudev"):
            rc, _ = run(["pkg-config", "--exists", pkg], capture=True, timeout=30)
            print(f"[{' OK ' if rc == 0 else 'WARN'}] {pkg} dev files: "
                  + ("found" if rc == 0 else "missing (Debian/Ubuntu: sudo apt install libasound2-dev libudev-dev pkg-config)"))
    td = os.environ.get("CARGO_TARGET_DIR")
    if td:
        print(f"[info] CARGO_TARGET_DIR={td} (builds land there, not in target/)")
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
        description="Project command wrapper (Bevy/Rust/cargo). Same commands on every engine in the Claude Code Game Kit.",
        epilog="Env: CARGO_TARGET_DIR (optional shared build folder), RUSTUP_TOOLCHAIN (optional). "
               "Exit codes: 0 ok, 1 failed, 2 environment/usage problem.",
    )
    ap.add_argument("--debug", action="store_true", help="verbose output; for `run`, also passes --debug to the game")
    ap.add_argument("--release", action="store_true", help="optimized build for check/test/smoke/run (build always is)")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    sub.required = True
    sub.add_parser("check", help="cargo fmt --check, then clippy on every target").set_defaults(fn=cmd_check)
    sub.add_parser("build", help="release build; prints the exe path").set_defaults(fn=cmd_build)
    sub.add_parser("test", help="build then run cargo test").set_defaults(fn=cmd_test)
    p = sub.add_parser("smoke", help="run the game headless for N frames; fail on errors",
                       epilog="Arguments after `--` go to the game, e.g. smoke --until GOAL_REACHED -- --autoplay right")
    p.add_argument("--frames", type=positive_int, default=SMOKE_FRAMES,
                   help=f"frames to run, 1 to 100000 (default {SMOKE_FRAMES}); one 1/60 s game tick per frame")
    p.add_argument("--until", help="fail unless the game prints this marker (scenario runs, e.g. GOAL_REACHED)")
    p.add_argument("--fail-on", help="comma-separated markers that fail the run (e.g. CRASHED,TIME_UP)")
    p.add_argument("--timeout", type=positive_int, default=SMOKE_TIMEOUT_S,
                   help=f"seconds before a hung game is killed, after the build (default {SMOKE_TIMEOUT_S})")
    p.add_argument("--screenshot", help="open a window and save the last frame as PNG (path relative to the project)")
    p.add_argument("--record", help="open a window and save PNG frames into this folder (GIF: tools/art/frames_to_gif.py)")
    p.add_argument("--record-every", type=positive_int, default=4, help="record every Nth frame (default 4)")
    p.add_argument("--record-from", type=positive_int, default=1,
                   help="first frame to record (default 1): film a moment deep into a run without the frames before it")
    p.set_defaults(fn=cmd_smoke)
    sub.add_parser("run", help="build then launch the game").set_defaults(fn=cmd_run)
    p = sub.add_parser("clean", help="remove the cargo target folder")
    p.add_argument("--yes", action="store_true", help="skip the question asked when the target folder is outside the project")
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
    if "--" in argv:                       # everything after `--` is for the game itself (smoke, run)
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

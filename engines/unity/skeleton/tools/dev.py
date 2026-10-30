#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dev.py  (Unity edition)
# Purpose : The ONE command wrapper for this project. Same subcommands on every
#           engine in the Claude Code Game Kit, so humans and Claude never guess flags.
# Usage   : python tools/dev.py <command> [options]      (add -h for help)
#             check    batchmode compile, fail on C# errors
#             test     run tests (--mode EditMode|PlayMode, --filter NAME)
#             smoke    PlayMode tests named Smoke (you write them); --filter, --graphics, --screenshot,
#                      --record, --until, --fail-on for scenario runs (frames via GameKitCapture)
#             exec     run a static editor method headless (scene builders: exec GameKitScenes.CreateStarterScene)
#             build    headless player build via Assets/Editor/GameKitBuild.cs
#             run      open the project in the editor
#             clean    remove Library/ and Temp/ (asks first, or --yes)
#             doctor   verify the local environment
# Env     : UNITY_EDITOR  full path to the Unity editor executable for this project's version
# Exit    : 0 ok, 1 task failed, 2 environment/usage problem
# Notes   : doctor/check/test/smoke/build/clean run against Unity 6000.6.6f1 on Windows
#           (2026-10-20), including planted failures; `run` launches the editor but waits at licensing until Unity Hub
#           is signed in (docs/ENGINE.md gotcha 10). Close the editor first, a project can only
#           be open once. Python 3.8+, standard library only.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-19 with Claude (Opus 5.5, claude-opus-5-5): global options accepted after the
#           subcommand (dev.py build --debug); unity and unreal clean refuse to hang without --yes
# Updated : 2026-10-20 with Claude (Opus 5.5, claude-opus-5-5): nothing-ran results (no tests, all
#           ignored) exit 2 with the reason; build surfaces [ERROR] lines; clean survives a closed stdin
# Updated : 2026-10-21 (audit pass 3): stdout/stderr and captured tool output are UTF-8 (Windows
#           pipes defaulted to cp1252 and crashed on non-Latin paths, names and log lines)
# Updated : 2026-10-21 (audit pass 4): batchmode timeout, editor-already-open and not-executable exit 2,
#           Unity.app resolved, build target/out default per host OS, clean verifies deletion
# Updated : 2026-10-21 (kit 0.4.0): `exec` for editor methods (scenes from code), smoke scenario options like the
#           other overlays; capture needs a graphics device, so --graphics drops -nographics; captures refused
#           inside Build/; a Package Manager server that never started is exit 2, not "compile failed"
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
DEBUG = False
LOG_FILE = ROOT / "Logs" / "dev_unity.log"
UNITY_TIMEOUT_S = 3600                   # first import of a big project is slow; a hang still ends
KILL_TIMEOUT_S = 10                      # after a timeout: seconds to wait for the killed tree's pipe
NO_EXEC = (126, 127)                     # run_unity codes: not executable / not found -> exit 2
EDITOR_OPEN = re.compile(r"another Unity instance is running with this project open|"
                         r"Multiple Unity instances cannot open the same project", re.I)
# Unity's Package Manager runs a local server; when it does not come up, Unity exits 1 before compiling anything.
# Seen once on 6000.6.6f1 and gone on the next run: an environment problem, not a code one.
UPM_DOWN = re.compile(r"Could not establish a connection with the Unity Package Manager local server", re.I)
# Default player per host OS: a Mac or Linux install has no Windows build support by default
DEFAULT_TARGET = {"Windows": ("StandaloneWindows64", "Build/game.exe"),
                  "Darwin": ("StandaloneOSX", "Build/game.app"),
                  "Linux": ("StandaloneLinux64", "Build/game.x86_64")}.get(platform.system(),
                                                                          ("StandaloneWindows64", "Build/game.exe"))
RESULTS = ROOT / "Logs" / "test_results.xml"


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


def unity_exe():
    """UNITY_EDITOR as a runnable path; a macOS Unity.app bundle is resolved to Contents/MacOS/Unity."""
    v = os.environ.get("UNITY_EDITOR")
    if not v:
        return None
    p = Path(v)
    if p.is_dir() and p.suffix == ".app" and (p / "Contents" / "MacOS" / "Unity").is_file():
        p = p / "Contents" / "MacOS" / "Unity"
    return p


def project_version():
    f = ROOT / "ProjectSettings" / "ProjectVersion.txt"
    try:
        m = re.search(r"m_EditorVersion:\s*(\S+)", f.read_text(encoding="utf-8"))
        return m.group(1) if m else None
    except OSError:
        return None


def preflight():
    if not (ROOT / "ProjectSettings").exists():
        return "No ProjectSettings/ here. Create the project in Unity Hub first, then adopt the kit into it."
    exe = unity_exe()
    if not exe or not exe.exists():
        return "UNITY_EDITOR is not set or does not exist. Point it at the editor executable for this project's version."
    if not exe.is_file():
        return f"UNITY_EDITOR={exe} is a folder; point it at the Unity executable inside it (Editor/Unity.exe on Windows)."
    return None


def project_locked():
    """True when a running Unity holds Temp/UnityLockfile (a stale file left by a crash is not held)."""
    lock = ROOT / "Temp" / "UnityLockfile"
    if not lock.is_file():
        return False
    try:
        if os.name == "nt":
            os.close(os.open(lock, os.O_RDWR))          # Unity opens it exclusively on Windows
            return False
        import fcntl
        with open(lock, "rb") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)  # Unity flocks it on macOS/Linux
            fcntl.flock(fh, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def env_problem(rc, log):
    """Return an exit-2 reason when a batchmode run failed for environment reasons, else None.

    Unity 6.6 prints nothing when the project is already open: it exits 1 right after
    "Successfully changed project path", so the lockfile is checked instead of the log.
    """
    if rc in NO_EXEC:
        return "Unity could not be started (see the error above)"
    if rc != 0 and (EDITOR_OPEN.search(log) or project_locked()):
        return "the project is open in another Unity editor; close it (batchmode needs the project to itself)"
    if rc != 0 and UPM_DOWN.search(log):
        return ("Unity's Package Manager server did not start, so nothing was compiled or tested (often a one-off: run the "
                f"command again; if it keeps happening, see {LOG_FILE})")
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


def run_unity(extra, label, graphics=False, env=None):
    """Run the editor in batchmode with a log file. Returns (rc, log_text).
    graphics=True keeps a graphics device (no -nographics), so cameras can render for screenshots."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(unity_exe()), "-batchmode"] + ([] if graphics else ["-nographics"]) + [
           "-projectPath", str(ROOT), "-logFile", str(LOG_FILE)] + extra
    dbg("run: " + " ".join(cmd))
    sys.stdout.flush()
    try:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL, env=dict(os.environ, **(env or {})),
                                start_new_session=NEW_SESSION)
    except FileNotFoundError as exc:
        print(f"[error] cannot execute Unity: {exc}", file=sys.stderr)
        return 127, ""
    except OSError as exc:
        print(f"[error] cannot execute Unity: {exc.strerror or exc} (not a file, or not executable)", file=sys.stderr)
        return 126, ""
    try:
        rc = proc.wait(timeout=UNITY_TIMEOUT_S)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        # The editor's helpers (shader compiler, package manager) would keep the project locked: kill the tree
        kill_tree(proc)
        reap(proc)
        if isinstance(exc, KeyboardInterrupt):
            raise
        print(f"[FAIL] Unity did not exit within {UNITY_TIMEOUT_S} s ({label}); see {LOG_FILE}")
        rc = 124
    log = LOG_FILE.read_text(encoding="utf-8", errors="ignore") if LOG_FILE.exists() else ""
    if DEBUG or rc != 0:
        print(log[-4000:])
    return rc, log


def compile_errors(log):
    return [l for l in log.splitlines() if re.search(r"error CS\d+", l)]


def cmd_check(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    rc, log = run_unity(["-quit"], "check")
    why = env_problem(rc, log)
    if why:
        print(f"[error] {why}", file=sys.stderr)
        return 2
    errs = compile_errors(log)
    if rc != 0 or errs:
        for e in errs[:15]:
            print("  " + e)
        print("[FAIL] compile failed")
        return 1
    print("[ OK ] compiled")
    return 0


def run_tests(platform, filt, graphics=False, env=None, until=None, fail_on=None):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    extra = ["-runTests", "-testPlatform", platform, "-testResults", str(RESULTS)]
    if filt:
        extra += ["-testFilter", filt]
    if RESULTS.exists():
        RESULTS.unlink()
    rc, log = run_unity(extra, "test", graphics=graphics, env=env)
    why = env_problem(rc, log)
    if why:
        print(f"[error] {why}", file=sys.stderr)
        return 2
    errs = compile_errors(log)
    if errs:
        for e in errs[:15]:
            print("  " + e)
        print("[FAIL] compile errors block tests")
        return 1
    if not RESULTS.exists():
        print("[FAIL] no test results file written. Run with --debug to read the log.")
        return 1
    xml = RESULTS.read_text(encoding="utf-8", errors="ignore")
    run_tag = re.search(r"<test-run[^>]*>", xml)
    run_tag = run_tag.group(0) if run_tag else ""

    def count(name):
        m = re.search(rf'\b{name}="(\d+)"', run_tag)
        return int(m.group(1)) if m else -1

    failed, passed, skipped = count("failed"), count("passed"), count("skipped")
    if failed != 0:
        print(f"[FAIL] {failed} failed, {passed} passed (see {RESULTS})")
        return 1
    if passed <= 0:
        # Nothing ran: a setup problem (no tests match, or all ignored), not a test failure
        # Suites repeat "One or more child tests were ignored"; the test case carries the real reason
        reasons = [r.strip() for r in re.findall(r"<reason>\s*<message><!\[CDATA\[(.*?)\]\]>", xml, re.S)
                   if not r.strip().startswith("One or more child tests")]
        why = reasons[0] if reasons else f"no tests matched {filt or platform!r}"
        print(f"[FAIL] nothing passed ({skipped} skipped): {why}")
        return 2
    # Scenario markers in the log, like the other overlays' smoke (--until must appear, --fail-on must not)
    lines = log.splitlines()
    bad = [l for l in lines if any(m in l for m in (fail_on or []))]
    if bad:
        print("[FAIL] --fail-on marker seen:\n  " + "\n  ".join(bad[:5]))
        return 1
    if until and not any(until in l for l in lines):
        print(f"[FAIL] marker {until!r} not seen in {LOG_FILE}")
        return 1
    print(f"[ OK ] {passed} test(s) passed" + (f", {skipped} skipped" if skipped > 0 else "")
          + (f", marker {until!r} seen" if until else ""))
    return 0


def cmd_test(args):
    return run_tests(args.mode, args.filter)


def in_player_folder(path):
    """True if a capture path lands in the player output folder (Build/). build/ and Build/ are one folder on
    Windows and macOS, so captures there end up next to game.exe. Checked relative to the project root."""
    p = (ROOT / path).resolve()
    try:
        rel = p.relative_to(ROOT.resolve())
    except ValueError:
        return False                        # outside the project: not ours to judge
    player_dir = Path(DEFAULT_TARGET[1]).parts[0].lower()
    return bool(rel.parts) and rel.parts[0].lower() == player_dir


def cmd_smoke(args):
    env = {}
    for path in (args.screenshot, args.record):
        if path and in_player_folder(path):
            print(f"[error] {path} is inside the player build folder (build/ and Build/ are the same folder on Windows). "
                  f"Capture into Logs/ instead, e.g. --screenshot Logs/shot.png or --record Logs/frames", file=sys.stderr)
            return 2
    if args.screenshot:
        shot = (ROOT / args.screenshot).resolve()
        shot.parent.mkdir(parents=True, exist_ok=True)
        env["GAMEKIT_SCREENSHOT"] = str(shot)
    if args.record:
        rec = (ROOT / args.record).resolve()
        rec.mkdir(parents=True, exist_ok=True)
        env["GAMEKIT_RECORD_DIR"] = str(rec)
        env["GAMEKIT_RECORD_EVERY"] = str(args.record_every)
    graphics = args.graphics or bool(env)
    fail_on = [m for m in (args.fail_on or "").split(",") if m]
    rc = run_tests("PlayMode", args.filter, graphics=graphics, env=env, until=args.until, fail_on=fail_on)
    if rc == 0 and args.screenshot:
        shot = ROOT / args.screenshot
        print(f"[ OK ] screenshot: {shot.resolve()}" if shot.exists()
              else "[WARN] no screenshot written: the test must call GameKitCapture.Attach() (Assets/Tests/PlayMode)")
    if rc == 0 and args.record:
        n = len(list((ROOT / args.record).glob("*.png")))
        print(f"[ OK ] {n} frame(s) in {(ROOT / args.record).resolve()} (GIF: python tools/art/frames_to_gif.py <dir> out.gif)")
    return rc


def cmd_exec(args):
    """Run a public static editor method in batchmode (scene builders, asset setup), then quit."""
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    rc, log = run_unity(["-quit", "-executeMethod", args.method], "exec")
    why = env_problem(rc, log)
    if why:
        print(f"[error] {why}", file=sys.stderr)
        return 2
    errs = compile_errors(log)
    if errs:
        for e in errs[:15]:
            print("  " + e)
        print("[FAIL] compile errors: the method cannot run")
        return 1
    if rc != 0:
        shown = [l for l in log.splitlines() if l.startswith("[ERROR]") or "Exception" in l or "executeMethod" in l]
        for line in shown[:10]:
            print("  " + line)
        print(f"[FAIL] {args.method} failed (exit {rc}); the log is {LOG_FILE}")
        return 1
    print(f"[ OK ] ran {args.method}")
    return 0


def cmd_build(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out                    # relative to the project, like every other command
    out.parent.mkdir(parents=True, exist_ok=True)
    rc, log = run_unity(["-quit", "-executeMethod", "GameKitBuild.Build", "-buildTarget", args.target,
                         "-outputPath", str(out)], "build")
    why = env_problem(rc, log)
    if why:
        print(f"[error] {why}", file=sys.stderr)
        return 2
    if rc != 0:
        # GameKitBuild logs "[ERROR][build] ..." and exits 2 for setup problems (no scenes)
        for line in [l for l in log.splitlines() if l.startswith("[ERROR]")][:10]:
            print("  " + line)
        print("[FAIL] build failed")
        return 2 if rc == 2 else 1
    print("[ OK ] build done")
    return 0


def cmd_run(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    subprocess.Popen([str(unity_exe()), "-projectPath", str(ROOT)], cwd=ROOT)
    print("[ OK ] launching editor")
    return 0


def remove_tree(path):
    """Delete a folder for real. Returns None on success, else a reason (nothing is reported as removed)."""
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return "it is a link/junction; remove the link by hand if that is what you want"
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        left = sum(1 for _ in path.rglob("*"))
        return f"{left} item(s) could not be deleted (close the Unity editor or player holding them)"
    return None


def cmd_clean(args):
    targets = [t for t in (ROOT / "Library", ROOT / "Temp") if t.exists()]
    if not targets:
        print("[info] nothing to clean")
        return 0
    if not args.yes and (sys.stdin is None or not sys.stdin.isatty()):
        # Claude Code and CI have nobody to answer the prompt, so refuse instead of hanging.
        print("[error] clean needs confirmation; non-interactive shell detected. Re-run with: clean --yes", file=sys.stderr)
        return 2
    if not args.yes:
        print("Will delete: " + ", ".join(t.name for t in targets) + " (reimport will be slow)")
        try:
            answer = input("Proceed? [y/N] ")
        except EOFError:
            # Some shells (Git Bash under Claude Code) report a TTY but have nobody to answer
            print("\n[error] no answer available (stdin closed). Re-run with: clean --yes", file=sys.stderr)
            return 2
        if answer.strip().lower() != "y":
            print("[abort] nothing deleted")
            return 1
    failed = 0
    for t in targets:
        why = remove_tree(t)
        if why:
            print(f"[FAIL] {t.name}/ not removed: {why}")
            failed += 1
        else:
            print(f"[ OK ] removed {t.name}/")
    return 1 if failed else 0


def cmd_doctor(args):
    problems = 0
    print(f"[info] python {sys.version.split()[0]}")
    ver = project_version()
    print(f"[{' OK ' if ver else 'WARN'}] project editor version: {ver or 'ProjectSettings/ProjectVersion.txt not found (create the project in Unity Hub)'}")
    exe = unity_exe()
    if exe and exe.exists():
        print(f"[ OK ] UNITY_EDITOR: {exe}")
        if ver and ver not in str(exe):
            print(f"[WARN] editor path does not mention version {ver}, make sure it is the right install")
    else:
        print("[FAIL] UNITY_EDITOR not set or invalid")
        problems += 1
    doctor = ROOT / "tools" / "doctor.py"
    if doctor.exists():
        problems += 1 if subprocess.run([sys.executable, str(doctor)], cwd=ROOT).returncode else 0
    return 1 if problems else 0


def build_parser():
    ap = argparse.ArgumentParser(
        prog="dev.py",
        description="Project command wrapper (Unity). Same commands on every engine in the Claude Code Game Kit.",
        epilog="Env: UNITY_EDITOR = editor executable. Close the editor before batchmode commands. Exit codes: 0 ok, 1 failed, 2 environment/usage problem.",
    )
    ap.add_argument("--debug", action="store_true", help="verbose output, show the Unity log")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    sub.required = True
    sub.add_parser("check", help="batchmode compile").set_defaults(fn=cmd_check)
    p = sub.add_parser("test", help="run Unity tests")
    p.add_argument("--mode", default="EditMode", choices=["EditMode", "PlayMode"], help="test platform (default EditMode)")
    p.add_argument("--filter", help="test name filter")
    p.set_defaults(fn=cmd_test)
    p = sub.add_parser("smoke", help="PlayMode tests named Smoke",
                       epilog="Scenario runs: write Smoke_* PlayMode tests that play the game (an autoplay bot) and log markers. "
                              "Capture: call GameKitCapture.Attach() in the test (Assets/Tests/PlayMode/GameKitCapture.cs).")
    p.add_argument("--filter", default="Smoke", help="test name filter (default Smoke: every Smoke test)")
    p.add_argument("--until", help="fail unless the Unity log contains this marker (e.g. RUN_WON)")
    p.add_argument("--fail-on", help="comma-separated markers that fail the run (e.g. CAUGHT)")
    p.add_argument("--graphics", action="store_true", help="keep a graphics device (cameras render); implied by capture")
    p.add_argument("--screenshot", help="save the last frame as PNG (path relative to the project, e.g. Logs/shot.png)")
    p.add_argument("--record", help="save PNG frames into this folder, e.g. Logs/frames (GIF: tools/art/frames_to_gif.py)")
    p.add_argument("--record-every", type=int, default=6, help="record every Nth frame (default 6)")
    p.set_defaults(fn=cmd_smoke)
    p = sub.add_parser("exec", help="run a static editor method headless (e.g. a scene builder)")
    p.add_argument("method", help="Class.Method, public static, in an Editor folder (e.g. GameKitScenes.CreateStarterScene)")
    p.set_defaults(fn=cmd_exec)
    p = sub.add_parser("build", help="headless player build via GameKitBuild")
    p.add_argument("--target", default=DEFAULT_TARGET[0], help=f"Unity build target name (default here: {DEFAULT_TARGET[0]})")
    p.add_argument("--out", default=DEFAULT_TARGET[1], help=f"output path, relative to the project (default here: {DEFAULT_TARGET[1]})")
    p.set_defaults(fn=cmd_build)
    sub.add_parser("run", help="open the project in the editor").set_defaults(fn=cmd_run)
    p = sub.add_parser("clean", help="remove Library/ and Temp/")
    p.add_argument("--yes", action="store_true", help="skip confirmation")
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

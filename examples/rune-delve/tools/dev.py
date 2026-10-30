#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dev.py  (Unreal Engine 5 edition)
# Purpose : The ONE command wrapper for this project. Same subcommands on every
#           engine in the Claude Code Game Kit, so humans and Claude never guess flags.
# Usage   : python tools/dev.py <command> [--config Development] [--platform Win64]
#             check    compile the editor target (UnrealBuildTool)
#             build    same as check (kept for command-contract parity)
#             test     run automation tests headless (--filter, default "<Game>")
#             smoke    run automation tests named <Game>.Smoke (--filter, --until, --fail-on for scenario runs;
#                      screenshots need a renderer, so capture from the game itself, e.g. a -record= option)
#             exec     run an editor Python script headless (asset imports, maps)
#             run      open the project in the editor
#             package  BuildCookRun a packaged build into Packaged/
#             genproj  regenerate IDE project files
#             clean    remove Intermediate/ and Binaries/ (asks first, or --yes)
#             doctor   verify the local environment
# Env     : UE_ROOT  engine install folder (contains Engine/)
# Exit    : 0 ok, 1 task failed, 2 environment/usage problem
# Notes   : Run against UE 5.8 on Windows (2026-10-20) with VS 2022 Build Tools:
#           doctor, check, test, smoke, package, clean verified on a C++ project,
#           including planted failures; check and test also on a Blueprint-only
#           project. `run` and `genproj` not run. Constants near the top are the knobs to turn.
#           Python 3.8+, standard library only.
#
# Pseudocode:
#   parse args -> find uproject + UE_ROOT -> build command for the task
#   -> run, capture log -> parse for Result={Fail}/errors (exit codes unreliable)
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-19 with Claude (Opus 5.5, claude-opus-5-5): global options accepted after the
#           subcommand (dev.py build --debug); unity and unreal clean refuse to hang without --yes
# Updated : 2026-10-20 with Claude (Opus 5.5, claude-opus-5-5): automation results read from
#           -abslog (UnrealEditor-Cmd prints none to stdout); check skips Blueprint-only projects
#           and exits 2 when MSVC/Windows SDK/.NET Framework SDK is missing or Live Coding
#           blocks the build; clean survives a closed stdin
# Updated : 2026-10-20 (audit pass 1): --platform limited to known values, --filter validated so it
#           cannot add -ExecCmds commands, paths with cmd.exe metacharacters refused before .bat calls
#           (the .uproject and Target.cs file names too, since 2026-10-30)
# Updated : 2026-10-21 (audit pass 3): stdout/stderr and captured tool output are UTF-8 (Windows
#           pipes defaulted to cp1252 and crashed on non-Latin paths, names and log lines)
# Updated : 2026-10-21 (audit pass 4): Linux/macOS script paths, genproj via UBT -projectfiles (+ --vscode),
#           missing tools and not-executable exit 2, nothing-ran exits 2, toolchain detection ignores
#           compile errors, doctor counts git, clean verifies deletion, live build output
# Updated : 2026-10-22 (kit 0.4.0): `exec <script.py>` runs editor Python headless (the pythonscript commandlet),
#           the log decides pass/fail as for `test`; smoke --until/--fail-on/--filter like the other overlays;
#           exec/test/smoke exit 2 with "run check first" when the game module is not compiled yet
#           exec passes the script path with forward slashes (backslash escapes in quoted arguments)
# Updated : 2026-10-30 with Claude (Opus 5.5, claude-opus-5-5): a timeout kills the whole process tree
#           (taskkill /T, or the process group), then waits at most KILL_TIMEOUT_S for the pipe; a hung
#           test/smoke/exec exits 1 (was 2), git lfs output decoded as UTF-8
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
SYSTEM = platform.system()  # Windows, Linux, Darwin

# ---- Tunables / constants (edit if your UE version differs) -------------------
SMOKE_GROUP_SUFFIX = "Smoke"                  # tests named <Game>.Smoke.* are the smoke group
TEST_TIMEOUT_S = 1800
FAIL_PATTERNS = [r"Result=\{Fail\}", r"Fatal error", r"LogAutomationController: Error", r"\bTest Failed\b"]
OK_PATTERN = r"Result=\{Success\}"
AUTOMATION_LOG = ROOT / "Saved" / "Logs" / "dev_automation.log"  # UnrealEditor-Cmd does not log to stdout
EXEC_LOG = ROOT / "Saved" / "Logs" / "dev_exec.log"
EXEC_TIMEOUT_S = 3600                         # a first import of many assets is slow; a hang still ends
KILL_TIMEOUT_S = 10                           # after a timeout: seconds to wait for the killed tree's pipe
PYTHON_ERROR_PATTERN = r"\]LogPython: Error"
# Engine plugins' own Python start-up chatter, not the script's output
PYTHON_STARTUP_NOISE = r"Display: |Python enabled|Using Python|registering <class"
NO_PYTHON_PATTERN = r"[Uu]nable to find (a )?commandlet.*pythonscript|Unknown commandlet.*pythonscript"
# A C++ project the editor cannot load yet: the game module was never compiled (fresh clone, after clean)
MODULE_MISSING_PATTERN = r"[Tt]he game module '([^']+)' could not be found"
# Matched per line, and only when the output has no compiler diagnostics: a project folder named
# "Visual Studio 2022" plus an ordinary "identifier not found" error must stay a code failure (exit 1)
SDK_MISSING_PATTERNS = [r"SDK validation failed", r"not a valid platform to build",
                        r"^\s*(ERROR: )?Visual Studio (20\d\d )?(must be installed|is not installed|was not found)",
                        r"No (Visual C\+\+|MSVC) (installation|toolchain)", r"Could not find NetFxSDK"]
COMPILER_DIAGNOSTIC = re.compile(r": (fatal )?error C\d{4}:|: error: ", re.M)
NO_EXEC = (126, 127)                     # run()/run_tee() codes: not executable / not found -> exit 2
LIVE_CODING_PATTERN = r"Unable to build while Live Coding is active"  # any open editor on this engine blocks UBT
LONG_PATH_PATTERN = r"action paths are longer than 260 characters"   # UBT refuses; a shorter project path fixes it
PLATFORMS = ["Win64", "Linux", "Mac"]
TEST_FILTER_PATTERN = r"[A-Za-z0-9_.+ -]+"   # automation test names; nothing that can end the RunTests command
CMD_METACHARS = '&|<>^%!"'                   # cmd.exe syntax characters, unsafe in .bat arguments
DEBUG = False


def dbg(msg):
    """Verbose output, only with --debug."""
    if DEBUG:
        print(f"[debug] {msg}")


# ---- Locating things ----------------------------------------------------------
def find_uproject():
    found = sorted(ROOT.glob("*.uproject"))
    return found[0] if found else None


def ue_root():
    v = os.environ.get("UE_ROOT")
    return Path(v) if v else None


def platform_name(arg):
    if arg:
        return arg
    return {"Windows": "Win64", "Linux": "Linux", "Darwin": "Mac"}.get(SYSTEM, "Win64")


def batch_file(name):
    """Return the engine script for this OS.

    Windows: Engine/Build/BatchFiles/<name>.bat. Linux/macOS keep Build.sh and GenerateProjectFiles.sh in
    BatchFiles/Linux/ or BatchFiles/Mac/; only RunUAT.sh and RunUBT.sh sit at the BatchFiles top level.
    """
    root = ue_root()
    if not root:
        return None
    base = root / "Engine" / "Build" / "BatchFiles"
    if SYSTEM == "Windows":
        return base / (name + ".bat")
    if name in ("RunUAT", "RunUBT"):
        return base / (name + ".sh")
    return base / ("Mac" if SYSTEM == "Darwin" else "Linux") / (name + ".sh")


def missing_tool(path):
    """Print an exit-2 message and return 2 when an engine script or binary is absent, else None."""
    if path and Path(path).is_file():
        return None
    print(f"[error] engine tool not found: {path} (check UE_ROOT, and that this engine version ships it)", file=sys.stderr)
    return 2


def editor_cmd(plat):
    root = ue_root()
    if not root:
        return None
    exe = "UnrealEditor-Cmd.exe" if SYSTEM == "Windows" else "UnrealEditor-Cmd"
    return root / "Engine" / "Binaries" / plat / exe


def editor_gui(plat):
    root = ue_root()
    if not root:
        return None
    exe = "UnrealEditor.exe" if SYSTEM == "Windows" else "UnrealEditor"
    return root / "Engine" / "Binaries" / plat / exe


def target_name():
    """Editor target = Source/<X>Editor.Target.cs, e.g. MyGameEditor."""
    hits = sorted((ROOT / "Source").glob("*Editor.Target.cs"))
    if hits:
        return hits[0].name.replace(".Target.cs", "")
    up = find_uproject()
    return (up.stem + "Editor") if up else None


def game_name():
    up = find_uproject()
    return up.stem if up else "Game"


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


def run(cmd, capture=False, timeout=None):
    """Run a command in the project root. 124 = timed out (output so far is returned), 126 = not executable,
    127 = not found."""
    dbg("run: " + " ".join(str(c) for c in cmd))
    sys.stdout.flush()                     # keep our lines ahead of the child's when piped
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
    except OSError as exc:                 # PermissionError (no exec bit), a folder instead of a binary, ...
        print(f"[error] cannot execute {cmd[0]}: {exc.strerror or exc} (not a file, or not executable: chmod +x)",
              file=sys.stderr)
        return 126, ""
    try:
        out, _ = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        # The editor's children (shader workers, crash reporter) hold the pipe too: kill the tree
        kill_tree(proc)
        out = reap(proc)
        if isinstance(exc, KeyboardInterrupt):
            raise
        print(f"[FAIL] no exit after {timeout} s (a hang): {' '.join(str(c) for c in cmd[:1])} ...")
        return 124, out or ""
    return proc.returncode, (out or "")


def run_tee(cmd):
    """Run cmd, streaming its output live AND keeping a copy. Returns (returncode, output)."""
    dbg("run: " + " ".join(str(c) for c in cmd))
    sys.stdout.flush()
    try:
        proc = subprocess.Popen([str(c) for c in cmd], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError as exc:
        print(f"[error] cannot execute {cmd[0]}: {exc}", file=sys.stderr)
        return 127, ""
    except OSError as exc:
        print(f"[error] cannot execute {cmd[0]}: {exc.strerror or exc} (not a file, or not executable: chmod +x)",
              file=sys.stderr)
        return 126, ""
    lines = []
    for line in proc.stdout:
        print(line, end="", flush=True)    # live, even when piped
        lines.append(line)
    return proc.wait(), "".join(lines)


def preflight(need_uproject=True):
    if need_uproject and not find_uproject():
        return "No *.uproject in the project root. Create the project in the Unreal editor into this folder first."
    if not ue_root():
        return "UE_ROOT is not set. Point it at your engine folder (the one containing Engine/)."
    if not (ue_root() / "Engine").exists():
        return f"UE_ROOT={ue_root()} has no Engine/ folder."
    if SYSTEM == "Windows":
        # The .bat wrappers run under cmd.exe, and subprocess does not escape cmd metacharacters
        bad = sorted(set(CMD_METACHARS) & set(str(ROOT) + str(ue_root())))
        if bad:
            return (f"the project or engine path contains {' '.join(bad)}, which cmd.exe treats as syntax "
                    "(Build.bat/RunUAT.bat would split or run it). Move it to a path without these characters.")
        err = unsafe_bat_names()
        if err:
            return err
    return None


def unsafe_bat_names(uproject=None, target=None):
    """Exit-2 message when the .uproject file name or the editor target name holds a cmd.exe metacharacter,
    else None. Both go on the Build.bat/RunUAT.bat command line next to ROOT, so they need the same check.
    The arguments default to what find_uproject() and target_name() report (tests pass names directly)."""
    up = uproject if uproject is not None else find_uproject()
    tgt = target if target is not None else target_name()
    checks = []
    if up:
        checks.append(("project file", Path(up).name))
    if tgt:
        checks.append(("build target file", f"Source/{tgt}.Target.cs"))   # the target name comes from this file name
    for label, name in checks:
        bad = sorted(set(CMD_METACHARS) & set(Path(name).name))
        if bad:
            return (f"the {label} {name} contains {' '.join(bad)}, which cmd.exe treats as syntax "
                    "(Build.bat/RunUAT.bat would split or run it). Rename it to use only letters, digits and _.")
    return None


def module_missing(text):
    """Exit-2 message when the editor could not load the project because the game module is not built, else None."""
    m = re.search(MODULE_MISSING_PATTERN, text)
    if m:
        return (f"the editor could not load the game module '{m.group(1)}' because it is not compiled yet. "
                "Run `python tools/dev.py check` first (a fresh clone or a clean needs it once).")
    return None


# ---- Commands -----------------------------------------------------------------
def cmd_check(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    if args.config in ("Test", "Shipping"):
        # check builds the Editor target, which UnrealBuildTool only builds as Debug, DebugGame or Development
        print(f"[error] --config {args.config} applies to `package` only; `check` builds the editor (Debug, DebugGame or "
              "Development)", file=sys.stderr)
        return 2
    if not (ROOT / "Source").is_dir():
        # Blueprint-only project: the engine's prebuilt editor runs it, there is no C++ to compile
        print("[ OK ] Blueprint-only project (no Source/), nothing to compile. `test` loads the project.")
        return 0
    plat = platform_name(args.platform)
    bf = batch_file("Build")
    cmd = [bf, target_name(), plat, args.config, f"-Project={find_uproject()}", "-WaitMutex"]
    missing = missing_tool(bf)
    if missing:
        return missing
    rc, out = run_tee(cmd)
    if rc in NO_EXEC:
        return 2
    if rc != 0 and re.search(LONG_PATH_PATTERN, out):
        print("[error] build paths exceed Windows' 260-character limit; move the project to a shorter folder "
              "(e.g. D:/games/<name>)", file=sys.stderr)
        return 2
    if rc != 0 and re.search(LIVE_CODING_PATTERN, out):
        print("[error] an Unreal editor with Live Coding is running on this engine (any project). Close it, "
              "or press Ctrl+Alt+F11 in it to compile there instead.", file=sys.stderr)
        return 2
    if rc != 0 and not COMPILER_DIAGNOSTIC.search(out) and any(re.search(p, out, re.M) for p in SDK_MISSING_PATTERNS):
        print("[error] C++ toolchain incomplete: Build Tools for Visual Studio needs the 'Desktop development with C++' "
              "workload (MSVC + Windows SDK) and the .NET Framework 4.8 SDK component. See docs/ENGINE.md.", file=sys.stderr)
        return 2
    print("[ OK ] compiled" if rc == 0 else "[FAIL] build failed")
    return 0 if rc == 0 else 1


cmd_build = cmd_check


def run_automation(filter_, args, until=None, fail_on=None):
    """Run automation tests matching filter_, parse the log for pass/fail.

    until / fail_on: scenario markers (e.g. DELVE_COMPLETE, MAGE_DOWN) your Smoke tests log; checked in the same log."""
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    if not re.fullmatch(TEST_FILTER_PATTERN, filter_):
        # ';' and ',' separate -ExecCmds commands and '"' breaks UE's quoting: a filter must stay a filter
        print(f"[error] test filter {filter_!r} may only contain letters, digits, spaces and _ . + -", file=sys.stderr)
        return 2
    plat = platform_name(args.platform)
    exe = editor_cmd(plat)
    if not exe or not exe.exists():
        print(f"[error] editor command-line binary not found: {exe}", file=sys.stderr)
        return 2
    AUTOMATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    if AUTOMATION_LOG.exists():
        AUTOMATION_LOG.unlink()
    cmd = [exe, find_uproject(),
           f'-ExecCmds=Automation RunTests {filter_}; Quit',
           "-unattended", "-nopause", "-NullRHI", "-nosplash", f"-abslog={AUTOMATION_LOG}",
           "-TestExit=Automation Test Queue Empty"]
    rc, out = run(cmd, capture=True, timeout=TEST_TIMEOUT_S)
    # Test results only reach the log file, not stdout (verified on UE 5.8)
    if AUTOMATION_LOG.exists():
        out += AUTOMATION_LOG.read_text(encoding="utf-8", errors="ignore")
    if DEBUG:
        print(out)
    fails = [l for l in out.splitlines() if any(re.search(p, l) for p in FAIL_PATTERNS)]
    oks = len(re.findall(OK_PATTERN, out))
    if rc == 124:
        print(f"[FAIL] the editor hung; the log so far is in {AUTOMATION_LOG}")
        return 1
    if rc in NO_EXEC:
        return 2
    why = module_missing(out)
    if why:
        print(f"[error] {why}", file=sys.stderr)
        return 2
    if fails:
        for l in fails[:15]:
            print("  " + l)
        print(f"[FAIL] {len(fails)} failure line(s), {oks} passing")
        return 1
    if oks == 0:
        # Nothing ran: a setup gap (no such tests yet), not a failing test. Same rule as Unity and Godot.
        print(f"[FAIL] no tests matched filter {filter_!r} (exit 2: nothing ran). Run with --debug to see the log.")
        return 2
    hit = [m for m in (fail_on or []) if m in out]
    if hit:
        print(f"[FAIL] marker(s) {', '.join(hit)} seen in {AUTOMATION_LOG}")
        return 1
    if until and until not in out:
        print(f"[FAIL] marker {until!r} not seen in {AUTOMATION_LOG}")
        return 1
    print(f"[ OK ] {oks} test(s) passed (filter {filter_!r})" + (f", marker {until!r} seen" if until else ""))
    return 0


def cmd_test(args):
    return run_automation(args.filter or game_name(), args)


def cmd_smoke(args):
    fail_on = [m for m in (args.fail_on or "").split(",") if m]
    return run_automation(f"{game_name()}.{SMOKE_GROUP_SUFFIX}" + (f".{args.filter}" if args.filter else ""), args,
                          until=args.until, fail_on=fail_on)


def cmd_exec(args):
    """Run an editor Python script headless (the pythonscript commandlet): asset imports, maps, data assets.

    The script's output and errors only reach the log file, so the log decides pass/fail, like `test`."""
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    script = Path(args.script)
    script = script if script.is_absolute() else ROOT / script
    if not script.is_file() or script.suffix != ".py":
        print(f"[error] no Python script at {script}", file=sys.stderr)
        return 2
    if '"' in str(script):
        print("[error] the script path may not contain a double quote (it breaks the -script= argument)", file=sys.stderr)
        return 2
    exe = editor_cmd(platform_name(args.platform))
    missing = missing_tool(exe)
    if missing:
        return missing
    EXEC_LOG.parent.mkdir(parents=True, exist_ok=True)
    if EXEC_LOG.exists():
        EXEC_LOG.unlink()
    # Forward slashes: in a quoted argument (any path with a space) Unreal reads backslashes as escapes, so a
    # folder named rune-delve after a backslash arrives as <CR>une-delve, and tools as <TAB>ools (seen on UE 5.8)
    cmd = [exe, find_uproject(), "-run=pythonscript", f"-script={script.as_posix()}",
           "-unattended", "-nopause", "-nosplash", f"-abslog={EXEC_LOG}"]
    rc, out = run(cmd, capture=True, timeout=EXEC_TIMEOUT_S)
    log = EXEC_LOG.read_text(encoding="utf-8", errors="ignore") if EXEC_LOG.exists() else ""
    if rc == 124:
        print(f"[FAIL] the editor hung; the log so far is in {EXEC_LOG}")
        return 1
    if rc in NO_EXEC:
        return 2
    why = module_missing(log + out)
    if why:
        print(f"[error] {why}", file=sys.stderr)
        return 2
    if re.search(NO_PYTHON_PATTERN, log + out):
        print('[error] the PythonScriptPlugin is not enabled. Add { "Name": "PythonScriptPlugin", "Enabled": true, '
              '"TargetAllowList": [ "Editor" ] } to "Plugins" in the .uproject (docs/ENGINE_FLOW.md, "Content from scripts")', file=sys.stderr)
        return 2
    for line in log.splitlines():
        m = re.search(r"\]LogPython: (.*)", line)   # "LogInit: Display: LogPython:" lines repeat errors
        if m and not re.match(PYTHON_STARTUP_NOISE, m.group(1)):
            print("  " + m.group(1))           # the script's own prints and unreal.log() lines
    errors = [l for l in log.splitlines() if re.search(PYTHON_ERROR_PATTERN, l)]
    if DEBUG:
        print(log[-6000:])
    if errors or rc != 0:
        # The error lines were already echoed above with the script's output
        print(f"[FAIL] {script.name}: {len(errors)} Python error line(s), editor exit code {rc}. Log: {EXEC_LOG}")
        return 1
    print(f"[ OK ] {script.name} ran (log: {EXEC_LOG})")
    return 0


def cmd_run(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    exe = editor_gui(platform_name(args.platform))
    missing = missing_tool(exe)
    if missing:
        return missing
    rc, _ = run([exe, find_uproject()])
    return 2 if rc in NO_EXEC else 0 if rc == 0 else 1


def cmd_package(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    uat = batch_file("RunUAT")
    missing = missing_tool(uat)
    if missing:
        return missing
    # Packaged/, not build/: on Windows build/ and the committed Build/ are the same folder
    out_dir = ROOT / "Packaged"
    cmd = [uat, "BuildCookRun", f"-project={find_uproject()}", "-noP4",
           f"-platform={platform_name(args.platform)}", f"-clientconfig={args.config}",
           "-build", "-cook", "-stage", "-pak", "-archive", f"-archivedirectory={out_dir}"]
    rc, _ = run(cmd)
    print(f"[{' OK ' if rc == 0 else 'FAIL'}] package {'written to Packaged/' if rc == 0 else 'failed'}")
    return 2 if rc in NO_EXEC else 0 if rc == 0 else 1


def cmd_genproj(args):
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    # Launcher (installed) engines have no GenerateProjectFiles script; UBT's -projectfiles mode works on both
    bf = batch_file("Build")
    missing = missing_tool(bf)
    if missing:
        return missing
    cmd = [bf, "-projectfiles", f"-project={find_uproject()}", "-game", "-progress"]
    if (ue_root() / "Engine" / "Build" / "InstalledBuild.txt").is_file():
        cmd.append("-rocket")
    if args.vscode:
        cmd.append("-VSCode")
    rc, _ = run(cmd)
    print(f"[{' OK ' if rc == 0 else 'FAIL'}] project files {'generated' if rc == 0 else 'failed'}")
    return 2 if rc in NO_EXEC else 0 if rc == 0 else 1


def remove_tree(path):
    """Delete a folder for real. Returns None on success, else a reason (nothing is reported as removed)."""
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return "it is a link/junction; remove the link by hand if that is what you want"
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        left = sum(1 for _ in path.rglob("*"))
        return f"{left} item(s) could not be deleted (close the Unreal editor or game holding them)"
    return None


def cmd_clean(args):
    targets = [ROOT / "Intermediate", ROOT / "Binaries"]
    if args.deep:
        targets.append(ROOT / "DerivedDataCache")
    existing = [t for t in targets if t.exists()]
    if not existing:
        print("[info] nothing to clean")
        return 0
    if not args.yes and (sys.stdin is None or not sys.stdin.isatty()):
        # Claude Code and CI have nobody to answer the prompt, so refuse instead of hanging.
        print("[error] clean needs confirmation; non-interactive shell detected. Re-run with: clean --yes", file=sys.stderr)
        return 2
    if not args.yes:
        print("Will delete: " + ", ".join(t.name for t in existing))
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
    for t in existing:
        why = remove_tree(t)
        if why:
            print(f"[FAIL] {t.name}/ not removed: {why}")
            failed += 1
        else:
            print(f"[ OK ] removed {t.name}/")
    return 1 if failed else 0


def cmd_doctor(args):
    problems = 0
    print(f"[info] python {sys.version.split()[0]} on {SYSTEM}")
    up = find_uproject()
    print(f"[{' OK ' if up else 'WARN'}] uproject: {up.name if up else 'none yet (create the project in the editor)'}")
    root = ue_root()
    if root and (root / "Engine").exists():
        print(f"[ OK ] UE_ROOT: {root}")
    else:
        print("[FAIL] UE_ROOT not set or invalid")
        problems += 1
    print(f"[{' OK ' if shutil.which('git') else 'FAIL'}] git")
    problems += 0 if shutil.which("git") else 1
    lfs = subprocess.run(["git", "lfs", "version"], capture_output=True, encoding="utf-8",
                         errors="replace").returncode == 0 if shutil.which("git") else False
    print(f"[{' OK ' if lfs else 'WARN'}] git-lfs {'installed' if lfs else 'NOT installed (needed for Content/)'}")
    print(f"[{' OK ' if (ROOT / '.gitattributes').exists() else 'WARN'}] .gitattributes (LFS rules)")
    doctor = ROOT / "tools" / "doctor.py"
    if doctor.exists():
        rc, _ = run([sys.executable, doctor])
        problems += 1 if rc else 0
    return 1 if problems else 0


def build_parser():
    ap = argparse.ArgumentParser(
        prog="dev.py",
        description="Project command wrapper (Unreal Engine 5). Same commands on every engine in the Claude Code Game Kit.",
        epilog="Env: UE_ROOT = engine folder. Exit codes: 0 ok, 1 failed, 2 environment/usage problem.",
    )
    ap.add_argument("--debug", action="store_true", help="verbose output, show full logs")
    ap.add_argument("--config", default="Development", choices=["Debug", "DebugGame", "Development", "Test", "Shipping"],
                    help="build configuration (default Development)")
    ap.add_argument("--platform", choices=PLATFORMS, help="target platform (default: this OS)")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    sub.required = True
    sub.add_parser("check", help="compile the editor target").set_defaults(fn=cmd_check)
    sub.add_parser("build", help="same as check").set_defaults(fn=cmd_build)
    p = sub.add_parser("test", help="run automation tests headless")
    p.add_argument("--filter", help='automation filter, e.g. "MyGame.Logic" (default: the game name)')
    p.set_defaults(fn=cmd_test)
    p = sub.add_parser("smoke", help="run automation tests named <Game>.Smoke (scenario runs: --until, --fail-on)")
    p.add_argument("--filter", help="only <Game>.Smoke.<filter>, e.g. Boot")
    p.add_argument("--until", help="a marker your Smoke tests must log (e.g. DELVE_COMPLETE)")
    p.add_argument("--fail-on", help="comma-separated markers that fail the run (e.g. MAGE_DOWN)")
    p.set_defaults(fn=cmd_smoke)
    p = sub.add_parser("exec", help="run an editor Python script headless (imports, maps; needs PythonScriptPlugin)")
    p.add_argument("script", help="path to the .py script, relative to the project (e.g. tools/unreal/build_content.py)")
    p.set_defaults(fn=cmd_exec)
    sub.add_parser("run", help="open the project in the editor").set_defaults(fn=cmd_run)
    sub.add_parser("package", help="BuildCookRun a packaged build into Packaged/").set_defaults(fn=cmd_package)
    p = sub.add_parser("genproj", help="regenerate IDE project files (UBT -projectfiles)")
    p.add_argument("--vscode", action="store_true", help="generate a VS Code workspace instead of Visual Studio files")
    p.set_defaults(fn=cmd_genproj)
    p = sub.add_parser("clean", help="remove Intermediate/ and Binaries/")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--deep", action="store_true", help="also remove DerivedDataCache/ (slow to rebuild)")
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

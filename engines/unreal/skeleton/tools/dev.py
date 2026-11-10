#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dev.py  (Unreal Engine 5 edition)
# Purpose : The ONE command wrapper for this project. Same subcommands on every
#           engine in the Claude Code Game Kit, so humans and Claude never guess flags.
# Usage   : python tools/dev.py <command> [--config Development] [--platform Win64]
#             check    compile the editor target (UnrealBuildTool); in a Blueprint-only project, only the
#                      project's code plugins (GameKitShell), through the engine's UnrealEditor target; then the
#                      kit's shader recipes as materials (the full editor off-screen; --no-shaders skips)
#             build    same as check (kept for command-contract parity)
#             test     run automation tests headless (--filter, default "<Game>", plus "GameKit." when the
#                      kit's GameKitShell plugin is enabled)
#             smoke    run automation tests named <Game>.Smoke (--filter, --until, --fail-on for scenario runs;
#                      screenshots need a renderer, so capture from the game itself, e.g. a -record= option);
#                      --shaders first draws every kit shader recipe and compares it with its golden image;
#                      --drive menus|access|show:<screen> walks the kit's shell screens instead (the GameKitShell
#                      plugin), --screenshot FILE draws a show:<screen>, --data-dir and --locale set its run
#             exec     run an editor Python script headless (asset imports, maps)
#             run      open the project in the editor
#             package  BuildCookRun a packaged build into Packaged/
#             genproj  regenerate IDE project files
#             clean    remove Intermediate/ and Binaries/ (asks first, or --yes)
#             doctor   verify the local environment
#             ship     put the game online (tools/cloud/ship.py): ship --target aws|azure|gcp|linode|do
#                      --kind static|container --plan, then --apply / --destroy; ship -h for its options
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
# Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): the kit's GameKitShell plugin (Plugins/,
#           opt-in in the .uproject): `test` also runs its GameKit.* tests when it is enabled and counts them,
#           doctor reports it, check refuses it on a Blueprint-only project (its C++ needs Source/)
# Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): on Windows a command with a timeout runs in a
#           job object (WinJob), so a timeout also ends a grandchild whose parent already exited
# Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): on Linux and macOS, killing an untimed command
#           (Ctrl+C) also kills what it started, found through ps (it shares our process group)
# Updated : 2026-11-06 with Claude (Opus 5.5, claude-opus-5-5): the kit's shader recipes
#           (Content/Python/kit_shaders): `check` compiles them as materials, `smoke --shaders` draws and compares
#           them, both in the full editor off-screen (the pythonscript commandlet has only the Null RHI)
# Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): check builds an enabled GameKitShell in a
#           Blueprint-only project (the UnrealEditor target with -Project puts it in the plugin's Binaries/)
#           instead of refusing it; test/smoke/exec exit 2 with "run check first" while its module is missing
# Updated : 2026-11-03 with Claude (Opus 5.5, claude-opus-5-5): test/smoke exit 1 when the editor exits non-zero
#           before any test passed (a crash), instead of exit 2 "no tests matched"
# Updated : 2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): the shell's screens (#168): smoke --drive runs the
#           plugin's GameKit.Screens.Drive test with -GameKitDrive=, echoes its proof lines (SETTINGS_WRITTEN,
#           ACCESS_*, DRIVE_DONE) and fails without DRIVE_DONE; --screenshot runs GameKit.Screens.Show with a
#           renderer (-RenderOffScreen); --data-dir and --locale
# Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): --screenshot and --data-dir take a path with a
#           space (#267): the value goes in quotes, -Key="a b", passed as is on the Windows command line (UnrealValue)
# Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): every path the editor gets (-abslog=, -script=) goes
#           through unreal_path (forward slashes, -Key="a b" for a space) and the shader check names its script by
#           its place on sys.path, so no project path lands inside -ExecCmds (#273); a quote in the project path is
#           refused up front
# ---------------------------------------------------------------------------
import argparse
import json
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
# Result={Fail} covers every failed test; "Test Failed" alone also matched a test named "Test Failed Handling" (#250)
FAIL_PATTERNS = [r"Result=\{Fail\}", r"Fatal error", r"LogAutomationController: Error"]
OK_PATTERN = r"Result=\{Success\}"
NO_TESTS_PATTERN = r"No automation tests matched"  # logged before the editor exits 255 (UE 5.8)
AUTOMATION_LOG = ROOT / "Saved" / "Logs" / "dev_automation.log"  # UnrealEditor-Cmd does not log to stdout
EXEC_LOG = ROOT / "Saved" / "Logs" / "dev_exec.log"
EXEC_TIMEOUT_S = 3600                         # a first import of many assets is slow; a hang still ends
BUILD_TIMEOUT_S = 4 * 3600                    # build, package, project files: longer than this is a hang (#250)
KILL_TIMEOUT_S = 10                           # after a timeout: seconds to wait for the killed tree's pipe
PYTHON_ERROR_PATTERN = r"\]LogPython: Error"
# Engine plugins' own Python start-up chatter, not the script's output
PYTHON_STARTUP_NOISE = r"Display: |Python enabled|Using Python|registering <class"
NO_PYTHON_PATTERN = r"[Uu]nable to find (a )?commandlet.*pythonscript|Unknown commandlet.*pythonscript"
# A C++ project the editor cannot load yet: the game module was never compiled (fresh clone, after clean)
MODULE_MISSING_PATTERN = r"[Tt]he game module '([^']+)' could not be found"
# An enabled code plugin whose module was never compiled (a Blueprint-only project before its first check)
PLUGIN_MISSING_PATTERN = r"Plugin '([^']+)' failed to load because module '[^']+' could not be found"
# The engine's own editor target: in a project without Source/ it builds only the project's code plugins
ENGINE_EDITOR_TARGET = "UnrealEditor"
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
KIT_PLUGIN = "GameKitShell"                   # Plugins/GameKitShell: the kit's juice and shell logic (opt-in)
KIT_TEST_PREFIX = "GameKit."                  # its automation tests; `test` runs them with the game's own
KIT_OK_PATTERN = r"Result=\{Success\} Name=\{[^}]*\} Path=\{GameKit\."
SHADER_SCRIPT = "Content/Python/kit_shaders/shader_check.py"   # the kit's shader recipes as materials
SHADER_PY = "kit_shaders/shader_check.py"    # the same file as `py` finds it on sys.path (Content/Python is on it)
SHADER_LOG = ROOT / "Saved" / "Logs" / "dev_shaders.log"
SHADER_OUT = "Saved/ShaderCheck"          # smoke --shaders pictures, compared by tools/shaders/shader_ref.py
SHADER_TIMEOUT_S = 1800                   # editor start, material compiles (a fresh shader cache is slow), draws
SHADER_LINE = re.compile(r"LogPython: (SHADER_(?:OK|FAIL|CHECK_DONE)\b.*)$")
SHIP_SITE = None   # the web build `ship --kind static` publishes unless --site is given (None: none)
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


def kit_plugin_state():
    """'enabled', 'disabled' or 'absent': is Plugins/GameKitShell here, and does the .uproject enable it?
    The .uplugin says EnabledByDefault false, so only an entry with "Enabled": true turns it on."""
    if not (ROOT / "Plugins" / KIT_PLUGIN / f"{KIT_PLUGIN}.uplugin").is_file():
        return "absent"
    up = find_uproject()
    try:
        data = json.loads(up.read_text(encoding="utf-8-sig")) if up else {}
    except (OSError, ValueError):
        return "disabled"
    plugins = data.get("Plugins") if isinstance(data, dict) else None
    for entry in plugins if isinstance(plugins, list) else []:
        if isinstance(entry, dict) and entry.get("Name") == KIT_PLUGIN:
            return "enabled" if entry.get("Enabled") is True else "disabled"
    return "disabled"


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


class UnrealValue(str):
    """An editor argument already quoted the way Unreal reads it (-Key="a b"): run() puts it on the Windows command
    line as it is. subprocess would quote the whole argument ("-Key=a b") or escape the inner quotes (\\"), and
    Unreal's FParse::Value then stops the value at the space or keeps the backslash (#267)."""


def unreal_arg(key, value):
    """-Key=value for the editor's command line; a value with whitespace goes in quotes (-Key="a b"), which is the
    one form FParse::Value reads whole. On Linux and macOS the quotes reach the editor as they are and its
    FCommandLine::BuildFromArgV leaves an argument holding a quote alone. The value must not hold a quote."""
    if re.search(r"\s", value):
        return UnrealValue(f'-{key}="{value}"')
    return f"-{key}={value}"


def unreal_path(key, path):
    """unreal_arg for a path the editor reads (-abslog=, -script=, -GameKitDataDir=): forward slashes, since inside
    quotes Unreal reads a backslash as an escape (a folder named rune-delve after one arrived as <CR>une-delve on
    UE 5.8), then quoted when the path holds a space (#273). A double quote cannot be carried: ValueError."""
    value = Path(path).as_posix()
    if '"' in value:
        raise ValueError(f"-{key} holds a double quote, which Unreal's command line cannot carry: {value}")
    return unreal_arg(key, value)


def run(cmd, capture=False, timeout=None, env=None):
    """Run a command in the project root. 124 = timed out (output so far is returned), 126 = not executable,
    127 = not found."""
    dbg("run: " + " ".join(str(c) for c in cmd))
    sys.stdout.flush()                     # keep our lines ahead of the child's when piped
    argv = [str(c) for c in cmd]
    if sys.platform == "win32" and any(isinstance(c, UnrealValue) for c in cmd):
        # Windows hands the editor one command line: quote the usual way, but an UnrealValue goes in as it is
        argv = " ".join(str(c) if isinstance(c, UnrealValue) else subprocess.list2cmdline([str(c)]) for c in cmd)
    try:
        proc = subprocess.Popen(
            argv, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, env=dict(os.environ, **env) if env else None,
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
    job = WinJob(proc, timeout)
    try:
        out, _ = proc.communicate(timeout=timeout)
        job.close()                        # a normal exit: anything it left running keeps running
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        # The editor's children (shader workers, crash reporter) hold the pipe too: kill the tree
        kill_tree(proc, job)
        out = reap(proc)
        if isinstance(exc, KeyboardInterrupt):
            raise
        print(f"[FAIL] no exit after {timeout} s (a hang): {' '.join(str(c) for c in cmd[:1])} ...")
        return 124, out or ""
    return proc.returncode, (out or "")


def run_tee(cmd, timeout=None):
    """Run cmd, streaming its output live AND keeping a copy. Returns (returncode, output); 124 when it ran past
    timeout seconds (the tree is stopped)."""
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
    lines, expired = [], []
    watchdog = None
    if timeout:
        import threading

        def stop():
            expired.append(True)
            kill_tree(proc)
        watchdog = threading.Timer(timeout, stop)
        watchdog.daemon = True
        watchdog.start()
    try:
        for line in proc.stdout:
            print(line, end="", flush=True)    # live, even when piped
            lines.append(line)
        rc = proc.wait()
        if expired:
            print(f"[FAIL] no exit after {timeout} s (a hang): {' '.join(str(c) for c in cmd[:1])} ...")
            return 124, "".join(lines)
        return rc, "".join(lines)
    except KeyboardInterrupt:              # Ctrl+C: stop UBT and its compilers too, then let main() report it
        kill_tree(proc)
        reap(proc)
        raise
    finally:
        if watchdog:
            watchdog.cancel()


def preflight(need_uproject=True):
    if need_uproject and not find_uproject():
        return "No *.uproject in the project root. Create the project in the Unreal editor into this folder first."
    if not ue_root():
        return "UE_ROOT is not set. Point it at your engine folder (the one containing Engine/)."
    if not (ue_root() / "Engine").exists():
        return f"UE_ROOT={ue_root()} has no Engine/ folder."
    if '"' in str(ROOT):
        # every path dev.py gives the editor (-abslog=, -script=, -GameKitDataDir=) comes from this folder (#273)
        return "the project path contains a double quote, which Unreal's command line cannot carry. Move or rename it."
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
    m = re.search(PLUGIN_MISSING_PATTERN, text)
    if m:
        return (f"the editor could not load the {m.group(1)} plugin because it is not compiled yet. "
                "Run `python tools/dev.py check` first (it builds the plugin, also in a Blueprint-only project).")
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
    target = target_name()
    if not (ROOT / "Source").is_dir():
        if kit_plugin_state() != "enabled":
            # Blueprint-only project: the engine's prebuilt editor runs it, there is no C++ to compile
            print("[ OK ] Blueprint-only project (no Source/), nothing to compile. `test` loads the project.")
            return check_shaders(args)
        # Blueprint-only with the kit's C++ plugin: the engine's editor target compiles just the project's plugins
        # into Plugins/<name>/Binaries/ (the engine itself is prebuilt). Needs the same C++ toolchain as a C++ project.
        print(f"[info] Blueprint-only project with the {KIT_PLUGIN} plugin enabled: building its C++ "
              f"({ENGINE_EDITOR_TARGET} target)")
        target = ENGINE_EDITOR_TARGET
    plat = platform_name(args.platform)
    bf = batch_file("Build")
    cmd = [bf, target, plat, args.config, f"-Project={find_uproject()}", "-WaitMutex"]
    missing = missing_tool(bf)
    if missing:
        return missing
    rc, out = run_tee(cmd, timeout=BUILD_TIMEOUT_S)
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
    if rc != 0:
        return 1
    return check_shaders(args)


def check_shaders(args):
    """check: the kit's shader recipes current with their files and compiling as materials. 0 when there are none."""
    if not (ROOT / SHADER_SCRIPT).is_file() or getattr(args, "no_shaders", False):
        return 0
    rc, out = run_tool([sys.executable, ROOT / "tools" / "shaders" / "shader_gen.py", "--check"])
    if rc != 0:
        print(out.rstrip())
        if rc == 2:                       # the recipes themselves cannot be read: not a stale file
            print("[error] tools/shaders/shader_gen.py could not read the recipes (see above)")
            return 2
        print("[FAIL] the shader files do not match their recipes: python tools/shaders/shader_gen.py")
        return 1
    return shader_editor(args, "compile")


def shader_editor(args, mode, out_dir=None):
    """Run SHADER_SCRIPT in the full editor, off-screen (mode compile or render). Returns 0, 1 or 2."""
    exe = editor_cmd(platform_name(args.platform))
    missing = missing_tool(exe)
    if missing:
        return missing
    SHADER_LOG.parent.mkdir(parents=True, exist_ok=True)
    if SHADER_LOG.exists():
        SHADER_LOG.unlink()
    env = {"GAMEKIT_SHADER_MODE": mode, "GAMEKIT_SHADER_OUT": str(out_dir) if out_dir else ""}
    # -ExecCmds=py, not -ExecutePythonScript: that one quits a frame after the script returns, before the
    # materials finish compiling (seen on UE 5.8); the script quits the editor itself when it is done.
    # The script by its name under Content/Python (on the editor's sys.path, where `py` looks for a relative file):
    # an absolute path would split at a space in the project folder, and -ExecCmds splits commands on , and ; (#273)
    cmd = [exe, find_uproject(), f"-ExecCmds=py {SHADER_PY}", "-unattended", "-nopause", "-nosplash", "-RenderOffScreen",
           unreal_path("abslog", SHADER_LOG)]
    rc, out = run(cmd, capture=True, timeout=SHADER_TIMEOUT_S, env=env)
    log = SHADER_LOG.read_text(encoding="utf-8", errors="ignore") if SHADER_LOG.exists() else ""
    if DEBUG:
        print(log[-6000:])
    if rc in NO_EXEC:
        return 2
    if rc == 124:
        print(f"[FAIL] the editor hung during the shader check; the log so far is in {SHADER_LOG}")
        return 1
    why = module_missing(log + out)
    if why:
        print(f"[error] {why}", file=sys.stderr)
        return 2
    lines = [m.group(1) for m in map(SHADER_LINE.search, log.splitlines()) if m]
    done = [l for l in lines if l.startswith("SHADER_CHECK_DONE")]
    fails = [l[len("SHADER_FAIL "):] for l in lines if l.startswith("SHADER_FAIL ")]
    for line in fails:
        print("[FAIL] shader " + line)
    if fails:
        hlsl = [l.strip() for l in log.splitlines() if re.search(r"Material\.ush:\d+:\d+: error", l)]
        for line in list(dict.fromkeys(hlsl))[:10]:
            print("  " + line)
    if not done:
        print(f"[FAIL] the shader check did not report (editor exit {rc}); is the PythonScriptPlugin enabled? "
              f"Log: {SHADER_LOG}")
        return 1
    if fails or done[-1].split()[-1] != "0":
        return 1
    if mode == "compile":
        print(f"[ OK ] {done[-1].split()[1]} shader recipe(s) compile as materials")
    return 0


def shader_pass(args):
    """smoke --shaders: draw every recipe in the editor, then compare with the golden images. Returns 0, 1 or 2."""
    out_dir = ROOT / SHADER_OUT
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    rc = shader_editor(args, "render", out_dir)
    if rc:
        return rc
    rc, out = run_tool([sys.executable, ROOT / "tools" / "shaders" / "shader_ref.py", "compare", out_dir])
    print(out.rstrip())
    if rc:
        print("[FAIL] a shader recipe differs from its golden image (see the lines above)" if rc == 1 else
              "[error] shader_ref.py compare could not run")
    return rc


def run_tool(cmd):
    """A captured run of one of the kit's Python tools. Returns (rc, output); 2 when it cannot run."""
    try:
        r = subprocess.run([str(c) for c in cmd], cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
                           timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 2, str(exc)
    return r.returncode, r.stdout + r.stderr


def cmd_build(args):
    return cmd_check(args)


def run_automation(filter_, args, until=None, fail_on=None, extra_args=None, markers=False, render=False):
    """Run automation tests matching filter_, parse the log for pass/fail.

    until / fail_on: scenario markers (e.g. DELVE_COMPLETE, MAGE_DOWN) your Smoke tests log; checked in the same log.
    extra_args go on the editor's command line (the shell drive's -GameKit*= options); markers echoes the drive's
    proof lines; render keeps a renderer (-RenderOffScreen instead of -NullRHI) so a screenshot can be drawn."""
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
           "-unattended", "-nopause", "-RenderOffScreen" if render else "-NullRHI", "-nosplash",
           unreal_path("abslog", AUTOMATION_LOG),
           "-TestExit=Automation Test Queue Empty"] + list(extra_args or [])
    rc, out = run(cmd, capture=True, timeout=TEST_TIMEOUT_S)
    # Test results only reach the log file, not stdout (verified on UE 5.8)
    if AUTOMATION_LOG.exists():
        out += AUTOMATION_LOG.read_text(encoding="utf-8", errors="ignore")
    if DEBUG:
        print(out)
    if markers:
        echo_markers(out)
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
    if rc != 0 and not re.search(NO_TESTS_PATTERN, out):
        # The editor died: a crash is a task failure (exit 1), not an empty filter (an empty filter also exits
        # non-zero, 255 on UE 5.8, but logs NO_TESTS_PATTERN first). Also after some tests passed: the ones that
        # never ran leave no result line (#250)
        done = "before any test finished" if oks == 0 else f"after {oks} test(s) passed"
        print(f"[FAIL] the editor exited with code {rc} {done}; the log is in {AUTOMATION_LOG}")
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
    kit = len(re.findall(KIT_OK_PATTERN, out))
    if kit:
        print(f"[info] {kit} of them are {KIT_TEST_PREFIX}* tests (the {KIT_PLUGIN} plugin: golden vectors and files)")
    return 0


def default_test_filter():
    """The game's tests, plus the kit plugin's GameKit.* tests when the .uproject enables the plugin."""
    state = kit_plugin_state()
    if state == "disabled":
        print(f"[info] Plugins/{KIT_PLUGIN} is not enabled in the .uproject, so its {KIT_TEST_PREFIX}* tests are skipped "
              "(enable it, or delete the folder if you do not use it: docs/ENGINE_FLOW.md)")
    return game_name() + ("+" + KIT_TEST_PREFIX if state == "enabled" else "")


def cmd_test(args):
    return run_automation(args.filter or default_test_filter(), args)


def cmd_smoke(args):
    fail_on = [m for m in (args.fail_on or "").split(",") if m]
    if getattr(args, "shaders", False):
        err = preflight()
        if err:
            print(f"[error] {err}", file=sys.stderr)
            return 2
        rc = shader_pass(args)
        if rc:
            return rc
    if getattr(args, "screenshot", "") and not getattr(args, "drive", ""):
        print("[error] --screenshot needs --drive show:<screen> (the kit's shell draws the screen; your own Smoke tests "
              "capture from the game, e.g. a -record= option)", file=sys.stderr)
        return 2
    if getattr(args, "drive", ""):
        return drive_run(args)
    return run_automation(f"{game_name()}.{SMOKE_GROUP_SUFFIX}" + (f".{args.filter}" if args.filter else ""), args,
                          until=args.until, fail_on=fail_on)


# ---- The shell's scripted runs (#168): smoke --drive, --screenshot, --data-dir ---------------------------
DRIVE_TEST = "GameKit.Screens.Drive"        # the plugin's automation test that runs a drive on the headless model
SHOW_TEST = "GameKit.Screens.Show"          # the one that also draws the screen to a PNG (needs a renderer)
DRIVE_PATTERN = r"[A-Za-z0-9_:=,.-]+"        # menus, show:settings, access:res=1280x800,scale=2,pad
SMOKE_DATA = "Saved/GameKitSmoke"           # the drive's own settings folder (never the player's Saved/GameKit)
BUILD_OUTPUTS = ("Packaged", "Saved/StagedBuilds", "Binaries")   # package, its staging, compiled modules (#263)
MARKER_LINE = re.compile(r"\b((?:DRIVE_[A-Z]+|SETTINGS_WRITTEN|SCREENSHOT_WRITTEN|ACCESS_[A-Z]+|PSEUDO_[A-Z]+)\b.*)$")
UNSAFE_VALUE_CHARS = '"'                   # a quote ends an Unreal argument (, and ; only matter inside -ExecCmds)


def build_output_of(path):
    """The build output folder (BUILD_OUTPUTS) an absolute path lies in, or None (#263). Letter case is ignored:
    Packaged/ and packaged/ are one folder on Windows and macOS."""
    where = os.path.realpath(str(path)).lower()
    for out in BUILD_OUTPUTS:
        folder = os.path.realpath(str(ROOT / out)).lower()
        if where == folder or where.startswith(folder.rstrip("\\/") + os.sep):
            return out
    return None


def drive_run(args):
    """`smoke --drive <name>`: GameKit.Screens.Drive (or .Show with --screenshot) presses through the shell's
    screens on the kit's model, headless; the proof lines it logs (SETTINGS_WRITTEN, ACCESS_*, DRIVE_DONE) are
    echoed. Exit 1 when the drive fails or never finishes, 2 when the plugin is off or an argument is unsafe."""
    err = preflight()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    if kit_plugin_state() != "enabled":
        print(f"[error] --drive needs the {KIT_PLUGIN} plugin enabled in the .uproject (its GameKitShellUI module holds "
              "the shell's screens: docs/ENGINE_FLOW.md \"Shell screens\")", file=sys.stderr)
        return 2
    if not re.fullmatch(DRIVE_PATTERN, args.drive):
        print(f"[error] drive name {args.drive!r} may only contain letters, digits and _ : = , . -", file=sys.stderr)
        return 2
    shot = (ROOT / args.screenshot).resolve() if args.screenshot else None
    if shot and shot.suffix.lower() != ".png":
        print("[error] --screenshot writes PNG: name the file .png", file=sys.stderr)
        return 2
    if shot and not args.drive.startswith("show:"):
        print("[error] --screenshot goes with --drive show:<screen>", file=sys.stderr)
        return 2
    data = Path(args.data_dir) if args.data_dir else ROOT / SMOKE_DATA
    data = (data if data.is_absolute() else ROOT / data).resolve()
    out = build_output_of(data) if args.data_dir else None
    if out:
        print(f"[error] --data-dir {args.data_dir} is inside {out}/, a build output: its files would ship with or be "
              f"wiped by the next build. Use a folder of its own, e.g. Saved/{data.name}", file=sys.stderr)
        return 2
    if not args.data_dir and data.exists():
        shutil.rmtree(data, ignore_errors=True)   # a fresh folder per run; --data-dir is kept as given
    data.mkdir(parents=True, exist_ok=True)
    values = [("GameKitDrive", args.drive), ("GameKitDataDir", data.as_posix())]
    if args.locale:
        values.append(("GameKitLocale", args.locale))
    if shot:
        values.append(("GameKitScreenshot", shot.as_posix()))
    for key, value in values:
        bad = sorted(set(UNSAFE_VALUE_CHARS) & set(value))
        if bad:
            print(f"[error] -{key} holds {' '.join(bad)!r}, which Unreal's command line cannot carry: "
                  "use a path without double quotes", file=sys.stderr)
            return 2
    if shot:
        shot.parent.mkdir(parents=True, exist_ok=True)
        if shot.is_file():
            shot.unlink()                   # a picture from an earlier run must not pass for this one
    extra = [unreal_arg(key, value) for key, value in values]   # a path with a space goes in quotes (#267)
    rc = run_automation(SHOW_TEST if shot else DRIVE_TEST, args, extra_args=extra, markers=True, render=bool(shot))
    if rc:
        return rc
    text = AUTOMATION_LOG.read_text(encoding="utf-8", errors="ignore") if AUTOMATION_LOG.exists() else ""
    if "DRIVE_DONE" not in text:
        print(f"[FAIL] the drive {args.drive!r} did not finish (no DRIVE_DONE in {AUTOMATION_LOG})")
        return 1
    print(f"[ OK ] drive {args.drive} (data in {data})")
    if shot:
        if not shot.is_file():
            print(f"[FAIL] no screenshot was written to {shot}")
            return 1
        print(f"[ OK ] screenshot: {shot} ({shot.stat().st_size} bytes)")
    return 0


def echo_markers(text):
    """Prints the drive's proof lines from the editor log, without the log's own prefix."""
    for line in text.splitlines():
        m = MARKER_LINE.search(line)
        if m and "LogGameKitShell" in line:
            print(m.group(1))


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
    # unreal_path: forward slashes (in a quoted argument Unreal reads backslashes as escapes, so a folder named
    # rune-delve after a backslash arrives as <CR>une-delve, and tools as <TAB>ools, seen on UE 5.8) and quotes
    # around a path with a space, the form FParse::Value reads whole (#273)
    cmd = [exe, find_uproject(), "-run=pythonscript", unreal_path("script", script),
           "-unattended", "-nopause", "-nosplash", unreal_path("abslog", EXEC_LOG)]
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
    rc, _ = run(cmd, timeout=BUILD_TIMEOUT_S)
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
    rc, _ = run(cmd, timeout=BUILD_TIMEOUT_S)
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
    state = kit_plugin_state()
    if state != "absent":
        print(f"[{' OK ' if state == 'enabled' else 'info'}] {KIT_PLUGIN} plugin {state}"
              + ("" if state == "enabled" else " (optional: docs/ENGINE_FLOW.md)"))
    doctor = ROOT / "tools" / "doctor.py"
    if doctor.exists():
        rc, _ = run([sys.executable, doctor])
        problems += 1 if rc else 0
    return 1 if problems else 0



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
        description="Project command wrapper (Unreal Engine 5). Same commands on every engine in the Claude Code Game Kit.",
        epilog="Env: UE_ROOT = engine folder. Exit codes: 0 ok, 1 failed, 2 environment/usage problem.",
    )
    ap.add_argument("--debug", action="store_true", help="verbose output, show full logs")
    ap.add_argument("--config", default="Development", choices=["Debug", "DebugGame", "Development", "Test", "Shipping"],
                    help="build configuration (default Development)")
    ap.add_argument("--platform", choices=PLATFORMS, help="target platform (default: this OS)")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    sub.required = True
    p = sub.add_parser("check", help="compile the editor target, then the kit's shader recipes as materials")
    p.add_argument("--no-shaders", action="store_true", help="skip the shader recipes (they start the editor)")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("build", help="same as check")
    p.add_argument("--no-shaders", action="store_true", help="skip the shader recipes")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("test", help="run automation tests headless")
    p.add_argument("--filter", help='automation filter, e.g. "MyGame.Logic" (default: the game name, plus GameKit. '
                                    'when the GameKitShell plugin is enabled)')
    p.set_defaults(fn=cmd_test)
    p = sub.add_parser("smoke", help="run automation tests named <Game>.Smoke (scenario runs: --until, --fail-on)")
    p.add_argument("--filter", help="only <Game>.Smoke.<filter>, e.g. Boot")
    p.add_argument("--until", help="a marker your Smoke tests must log (e.g. DELVE_COMPLETE)")
    p.add_argument("--fail-on", help="comma-separated markers that fail the run (e.g. MAGE_DOWN)")
    p.add_argument("--shaders", action="store_true",
                   help="first draw every kit shader recipe in the editor (off-screen, a GPU) and compare it with its "
                        "golden image (tools/shaders/)")
    p.add_argument("--drive", default="", metavar="SCENARIO",
                   help="instead of the Smoke tests, run a scripted path through the kit's shell screens (the GameKitShell "
                        "plugin): menus (settings changed and saved), access[:res=WxH,scale=N,pad,read] (the "
                        "accessibility sweep's tour, tools/access/sweep.py), show:<screen> (title, main_menu, settings, "
                        "pause, help, history, credits, loading, subtitle; add --screenshot)")
    p.add_argument("--screenshot", default="", help="with --drive show:<screen>: save the screen as this PNG (relative to the "
                                                   "project; the editor draws it off-screen, a GPU)")
    p.add_argument("--data-dir", default="", help="with --drive: the settings folder the run reads and writes (default: a fresh "
                                                 f"{SMOKE_DATA})")
    p.add_argument("--locale", default="", help="with --drive: the language the screens show (a data/i18n/<tag>.json)")
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
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # any script, in order
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

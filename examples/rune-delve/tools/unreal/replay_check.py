#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# replay_check.py
# Purpose : Prove a bot delve replays the same with and without a renderer: run one seed rendered (a small
#           window) and under -nullrhi, both -fixedfps, and compare the two runs frame by frame.
# Usage   : python tools/unreal/replay_check.py [--bot weaver|masher] [--seed N] [--exe Packaged/Windows/<Game>.exe]
#                                               [--runs N] [--debug]
#           Exit 0 when every pair of runs is identical, 1 on a divergence or an unfinished run, 2 for a setup problem.
#           Env: UE_ROOT (the engine; not needed with --exe)
# Notes   : Every frame the game logs a [trace] line (-tracedelve: positions, health, orc states) and the first frame
#           whose line differs is reported, so a divergence shows even when both runs still end with the same
#           summary. Before the fix for #8 (RDGameMode::FinishNavBuild) the runs differed from frame 5 on: the
#           runtime NavMesh finished its tiles on a real-time schedule. Without --exe the editor binary plays the
#           project in -game mode (no packaging needed). Logs: Saved/Logs/replay_<rendered|nullrhi>_<bot>_<seed>_<run>.log
#
# Pseudocode:
#   for each run: launch rendered, launch -nullrhi (one after the other: parallel runs would share the CPU)
#   -> read both logs: [MARK] lines and [trace] lines by frame -> first differing frame, or identical
# Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
# ---------------------------------------------------------------------------
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "Saved" / "Logs"
WINDOW = ["-windowed", "-resx=640", "-resy=360"]
COMMON = ["-fixedfps", "-quitatend", "-tracedelve", "-unattended", "-nosplash", "-nopause"]
END_MARKERS = ("DELVE_COMPLETE", "MAGE_DOWN", "TIMEOUT")
RUN_TIMEOUT_S = 900
DEBUG = False


def find_uproject():
    hits = sorted(ROOT.glob("*.uproject"))
    return hits[0] if hits else None


def editor_cmd():
    root = os.environ.get("UE_ROOT")
    if not root:
        return None
    exe = "UnrealEditor-Cmd.exe" if sys.platform == "win32" else "UnrealEditor-Cmd"
    plat = {"win32": "Win64", "linux": "Linux", "darwin": "Mac"}.get(sys.platform, "Win64")
    return Path(root) / "Engine" / "Binaries" / plat / exe


def launch(exe, project, log, extra):
    """One run; the game's log (not stdout) carries the trace. Returns the process exit code or None on a timeout."""
    cmd = [str(exe)] + ([str(project), "-game"] if project else []) + COMMON + extra + [f"-abslog={log}"]
    if DEBUG:
        print("  $ " + " ".join(cmd))
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=RUN_TIMEOUT_S).returncode
    except subprocess.TimeoutExpired:
        return None


def read_log(path):
    """{frame: trace text}, [MARK lines]."""
    traces, marks = {}, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.search(r"\[trace\] f=(\d+) (.*)", line)
            if m:
                traces[int(m.group(1))] = m.group(2).rstrip()
            m = re.search(r"\[MARK\] (.*)", line)
            if m:
                marks.append(m.group(1).rstrip())
    return traces, marks


def compare(a, b):
    """The first frame whose trace differs, or None when the runs are identical."""
    for frame in sorted(set(a) | set(b)):
        if a.get(frame) != b.get(frame):
            return frame
    return None


def main():
    global DEBUG
    ap = argparse.ArgumentParser(description="Run one seed rendered and under -nullrhi, compare them frame by frame.")
    ap.add_argument("--bot", default="weaver", choices=["weaver", "masher"])
    ap.add_argument("--seed", type=int, default=6)
    ap.add_argument("--exe", help="a packaged game to run instead of the editor binary in -game mode")
    ap.add_argument("--runs", type=int, default=1, help="repeat the pair this many times (default 1)")
    ap.add_argument("--debug", action="store_true", help="print the commands and the first differing lines in full")
    args = ap.parse_args()
    DEBUG = args.debug
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")  # cp1252 pipes on Windows

    if args.exe:
        exe, project = Path(args.exe), None
        if not exe.is_file():
            print(f"[error] no game at {exe}", file=sys.stderr)
            return 2
    else:
        exe, project = editor_cmd(), find_uproject()
        if not exe or not exe.is_file():
            print(f"[error] editor binary not found: {exe} (set UE_ROOT, or pass --exe)", file=sys.stderr)
            return 2
        if not project:
            print(f"[error] no .uproject in {ROOT}", file=sys.stderr)
            return 2
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    game = [f"-autoplay={args.bot}", f"-seed={args.seed}"]
    failed = 0
    for run in range(1, args.runs + 1):
        logs = {}
        for mode, extra in (("rendered", WINDOW), ("nullrhi", ["-nullrhi"])):
            log = LOG_DIR / f"replay_{mode}_{args.bot}_{args.seed}_{run}.log"
            if log.exists():
                log.unlink()
            rc = launch(exe, project, log, extra + game)
            if rc is None:
                print(f"[FAIL] {mode} run {run} did not finish in {RUN_TIMEOUT_S} s")
                return 1
            if not log.is_file():
                print(f"[FAIL] {mode} run {run} wrote no log ({log})")
                return 1
            logs[mode] = read_log(log)
        results = {}
        for mode, (traces, marks) in logs.items():
            end = [m for m in marks if m.split(" ")[0] in END_MARKERS]
            results[mode] = end[-1] if end else None
            print(f"  {mode:8s} run {run}: {len(traces)} frames, {results[mode] or 'no end marker'}")
            if not end:
                failed += 1
        frame = compare(logs["rendered"][0], logs["nullrhi"][0])
        if frame is None:
            print(f"[ OK ] run {run}: rendered and -nullrhi traces are identical")
        else:
            failed += 1
            print(f"[FAIL] run {run}: the runs diverge at frame {frame}")
            if DEBUG:
                for mode in ("rendered", "nullrhi"):
                    print(f"    {mode:8s} f={frame}: {logs[mode][0].get(frame)}")
    if failed:
        print(f"[FAIL] {failed} problem(s) over {args.runs} run(s); logs in {LOG_DIR}")
        return 1
    print(f"[ OK ] {args.bot} seed {args.seed}: {args.runs} identical pair(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

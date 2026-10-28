#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# session_context.py
# Purpose : Claude Code SessionStart hook. Prints a tiny status block that
#           Claude Code adds to the session context (git branch, dirty files,
#           ROADMAP "Now" section).
# Usage   : Wired up in .claude/settings.json. Test it by hand:
#               python tools/hooks/session_context.py
# Notes   : MUST fail soft. A broken hook should never block a session, so
#           every step is wrapped and the script always exits 0.
#           Output is UTF-8 (Claude Code reads hook stdout as UTF-8; Windows
#           pipes default to cp1252). The hook input JSON on stdin says why
#           the session started; after compact/resume the /start-session
#           reminder is skipped so Claude does not stop mid-task.
#           Needs Python 3.8+. Uses only the standard library.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-20 with Claude (Opus 5.5, claude-opus-5-5): UTF-8 output, "unknown"
#           instead of "0" when git fails, real untracked file count, source-aware reminder
# ---------------------------------------------------------------------------
import json
import subprocess
import sys
from pathlib import Path

# Repo root = two levels up from tools/hooks/
ROOT = Path(__file__).resolve().parents[2]
NOW_LINES = 8                               # ROADMAP "Now" lines to show
QUIET_SOURCES = {"compact", "resume"}       # mid-task restarts: no /start-session nudge


def run_git(*args):
    """Run a git command in the repo root. Returns stdout text, or None on any failure."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, timeout=5,
            text=True, encoding="utf-8", errors="replace",
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        # git missing, not a repo, timeout: the caller decides what to print
        return None


def session_source():
    """Read the SessionStart source (startup, resume, clear, compact) from stdin JSON, or ''."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""                       # run by hand: no hook input
        return str(json.loads(sys.stdin.read() or "{}").get("source", ""))
    except Exception:
        return ""


def roadmap_now():
    """Return the lines under '## Now' in docs/ROADMAP.md (up to the next '## ')."""
    path = ROOT / "docs" / "ROADMAP.md"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    section, active = [], False
    for line in lines:
        if line.startswith("## "):
            if active:
                break
            active = line.strip().lower().startswith("## now")
            continue
        if active and line.strip():
            section.append(line)
    return section


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass                                # very old or replaced stdout: print what we can
    source = session_source()
    print("== Session context (auto) ==")
    # symbolic-ref works even in a fresh repo with no commits yet (rev-parse HEAD does not)
    branch = run_git("symbolic-ref", "--short", "HEAD") or run_git("rev-parse", "--abbrev-ref", "HEAD")
    if branch:
        print(f"Branch: {branch}")
        dirty = run_git("status", "--porcelain", "--untracked-files=all")
        if dirty is None:
            print("Uncommitted changes: unknown (git status failed or timed out)")
        else:
            print(f"Uncommitted changes: {len(dirty.splitlines())} file(s)")
    now = roadmap_now()
    if now:
        print("ROADMAP Now:")
        for line in now[:NOW_LINES]:
            print(f"  {line}")
    if source in QUIET_SOURCES:
        print("Reminder: use `python tools/dev.py <check|test|smoke|build|run>`; continue the current task.")
    else:
        print("Reminder: use `python tools/dev.py <check|test|smoke|build|run>`; run /start-session.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never block a session
        print(f"(session_context hook skipped: {exc})", file=sys.stderr)
    sys.exit(0)

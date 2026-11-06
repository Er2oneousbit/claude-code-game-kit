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
#           The GDD's "Current tier:" line is printed because every scope check
#           reads it (SOP-08 "Tiers"); after the greenlight, the PRODUCTION.md
#           backlog count too (items, never dates).
#           Needs Python 3.8+. Uses only the standard library.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-20 with Claude (Opus 5.5, claude-opus-5-5): UTF-8 output, "unknown"
#           instead of "0" when git fails, real untracked file count, source-aware reminder
# Updated : 2026-10-28 with Claude (Opus 5.5, claude-opus-5-5): current tier and production backlog count
# Updated : 2026-11-05 with Claude (Opus 5.5, claude-opus-5-5): stdin read with a deadline, docs read with a size
#           cap and long lines cut, headings matched by their whole name (a review, #241)
#
# Pseudocode (tier and backlog)
#   GDD: first line starting "Current tier:" -> text after it, first **bold** part if any
#   PRODUCTION.md: rows of the table under "## Backlog" with any text -> status = last cell
#   print "done of total" (cut items do not count) when the backlog has rows
# ---------------------------------------------------------------------------
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

# Repo root = two levels up from tools/hooks/
ROOT = Path(__file__).resolve().parents[2]
NOW_LINES = 8                               # ROADMAP "Now" lines to show
QUIET_SOURCES = {"compact", "resume"}       # mid-task restarts: no /start-session nudge
TIER_MAX = 80                               # longest tier text to show
STDIN_WAIT_S = 2.0                          # the hook input is a small JSON object: never wait longer for it
STDIN_MAX = 1024 * 1024                     # bytes of hook input read at most
DOC_MAX = 2 * 1024 * 1024                   # bytes of a doc read at most (a real one is a few KB)
LINE_MAX = 200                              # characters of a ROADMAP line shown


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
    """Read the SessionStart source (startup, resume, clear, compact) from stdin JSON, or ''. Stops as soon as the
    JSON is whole, and after STDIN_WAIT_S at most: a writer that keeps the pipe open must not stall the session
    (#241)."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""                       # run by hand: no hook input
    except Exception:
        return ""
    got = {}

    def reader():
        buf = b""
        try:
            stream = getattr(sys.stdin, "buffer", None)
            read = getattr(getattr(stream, "raw", None), "read", None) or (stream.read1 if stream else None)
            while read is not None and len(buf) < STDIN_MAX:
                chunk = read(65536)         # returns what is there, without waiting for the pipe to close
                if not chunk:
                    break
                buf += chunk
                try:
                    got["data"] = json.loads(buf.decode("utf-8", "replace"))
                    return
                except ValueError:
                    continue                # not whole yet
            got["data"] = json.loads(buf.decode("utf-8", "replace") or "{}")
        except Exception:
            pass
    worker = threading.Thread(target=reader, daemon=True)
    worker.start()
    worker.join(STDIN_WAIT_S)
    data = got.get("data")
    return str(data.get("source", "")) if isinstance(data, dict) else ""


def heading(line, name):
    """True for a '## <name>' heading, with an optional note after it ('## Now (max 3 items)'), but not a longer
    name that starts the same ('## Nowhere', '## Backlog archive', #241)."""
    if not line.startswith("## "):
        return False
    text = re.sub(r"\s*[(:].*$", "", line[3:]).strip().lower()
    return text == name


def roadmap_now():
    """Return the lines under '## Now' in docs/ROADMAP.md (up to the next '## ')."""
    section, active = [], False
    for line in read_doc("ROADMAP.md"):
        if line.startswith("## "):
            if active:
                break
            active = heading(line.strip(), "now")
            continue
        if active and line.strip():
            section.append(line if len(line) <= LINE_MAX else line[:LINE_MAX] + " ...")
    return section


def read_doc(name):
    """Return the lines of docs/<name> (its first DOC_MAX bytes), or [] when it is missing or unreadable."""
    try:
        with open(ROOT / "docs" / name, "rb") as fh:
            return fh.read(DOC_MAX).decode("utf-8", "replace").splitlines()
    except Exception:
        return []


def current_tier():
    """Return the GDD's current tier ('Toy', 'Vertical slice', ...) or '' when there is no tier line."""
    for line in read_doc("GDD.md"):
        if line.startswith("Current tier:"):
            text = line[len("Current tier:"):].strip()
            bold = re.search(r"\*\*(.+?)\*\*", text)
            return (bold.group(1) if bold else text)[:TIER_MAX]
    return ""


def backlog_progress():
    """Return (done, total) from the PRODUCTION.md Backlog table, or None when it has no rows yet."""
    done = total = 0
    active = False
    for line in read_doc("PRODUCTION.md"):
        if line.startswith("## "):
            active = heading(line.strip(), "backlog")
            continue
        if not active or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not any(cells) or set("".join(cells)) <= set("-: ") or cells[0].lower() == "item":
            continue                        # empty template row, separator, header
        status = cells[-1].lower()
        if status == "cut":
            continue
        total += 1
        done += status == "done"
    return (done, total) if total else None


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
    tier = current_tier()
    if tier:
        print(f"Tier: {tier} (docs/GDD.md; scope rules in SOP-08 \"Tiers\")")
    progress = backlog_progress()
    if progress:
        print(f"Production backlog: {progress[0]} of {progress[1]} done (docs/PRODUCTION.md)")
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

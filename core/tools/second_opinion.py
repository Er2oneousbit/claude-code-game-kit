#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# second_opinion.py
# Purpose : Ask a different AI model (another vendor's coding CLI) to review files, read-only, and print its
#           answer, so Claude Code can get a second opinion on its own work (SOP-12 "Several agents on one job").
# Usage   : python tools/second_opinion.py --ask "Review this change for real bugs" --files tools/dev.py docs/X.md
#           python tools/second_opinion.py --ask "..." --model kimi-code/k3.1-pro --out docs/reviews/2026-10-22-export.md
#           python tools/second_opinion.py --check          # is the CLI installed and logged in?
# Notes   : Supports the Kimi Code CLI (`kimi`, 2.3+). Its prompt mode (-p) approves tool calls without asking, so
#           the reviewer runs as the agent in tools/second_opinion/kimi-agent.md, whose tool allowlist is only
#           Read, Grep and Glob (enforced by the CLI before every call): it can read the project, never change it,
#           run commands or browse. Whatever it reads is sent to the vendor's servers: keep secrets out of the
#           project folder (they should not be there anyway, SOP-13). Costs your account's usage.
#           The CLI exits 0 even when its login has expired, so this script reads the output to tell.
#           Models are named provider/model (kimi-code/k3, kimi-code/k3.1-pro); a bare name such as k3 works only if
#           your Kimi config defines it, and an unknown one is a usage error (exit 2), not "no answer".
#
# Pseudocode:
#   find the CLI (--cli, then PATH, then ~/.kimi-code/bin) -> build the prompt (question + files to read)
#   -> run it in the project root with the read-only agent -> classify: login problem (exit 2), timeout or
#   empty answer (exit 1), else print the answer (and save it with --out)
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
AGENT_FILE = Path(__file__).resolve().parent / "second_opinion" / "kimi-agent.md"
TIMEOUT_S = 900                       # a careful review of a few files takes minutes
FALLBACK_DIRS = [Path.home() / ".kimi-code" / "bin"]   # the installer's folder, if PATH has not caught up
AUTH_FIRST_LINE = re.compile(r"^\s*Error code: 40[13]\b")   # how the CLI itself reports a rejected login
QUOTA = re.compile(r"\b429\b|usage limit|rate limit|quota", re.I)   # the vendor refused: plan limit or rate limit
CLI_ERROR = re.compile(r"^\s*error:\s*(.+)$", re.M | re.I)            # the CLI's own one-line failure on stderr
UNKNOWN_MODEL = re.compile(r'Model "([^"]+)" is not configured', re.I)   # --model named something the CLI lacks
RESUME_LINE = re.compile(r"^To resume this session:.*$", re.M)   # unindented: the CLI's own line, not a quote
BULLET = re.compile(r"^• ", re.M)     # Kimi starts each message with a bullet
DEBUG = False


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


def find_cli(explicit):
    """Path of the kimi executable, or None."""
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    found = shutil.which("kimi")
    if found:
        return Path(found)
    for d in FALLBACK_DIRS:
        for name in ("kimi.exe", "kimi"):
            if (d / name).is_file():
                return d / name
    return None


def build_prompt(ask, files):
    """The reviewer's task: the question, plus the files to read (paths relative to the project)."""
    lines = [ask.strip()]
    if files:
        lines.append("")
        lines.append("Read these files from the current project folder first:")
        lines += [f"- {f}" for f in files]
    lines.append("")
    lines.append("Report real problems only, most severe first, each with file and line, evidence and a one-line fix. "
                 "Say 'nothing real' if that is the honest answer.")
    return "\n".join(lines)


def build_command(cli, prompt, model, agent_file):
    cmd = [str(cli), "--agent-file", str(agent_file), "-p", prompt]
    if model:
        cmd += ["-m", model]
    return cmd


def classify(rc, out, err):
    """(exit_code, message, answer). 0 = answer, 1 = no usable answer, 2 = environment (login, CLI)."""
    # Only the CLI's own error counts: the first line of its output. A review may quote these strings (reviewing
    # this very file did), and that must not read as a login failure.
    first_line = next((l for l in (out or "").splitlines() if l.strip()), "")
    answer = BULLET.sub("", RESUME_LINE.sub("", out or "")).strip()
    # stderr carries the CLI's thinking and tool activity too (the text of files it read), so an error line there
    # counts only when no answer came back: a real review is never thrown away as "not logged in"
    err_auth = not answer and any(AUTH_FIRST_LINE.match(l) for l in (err or "").splitlines())
    if AUTH_FIRST_LINE.match(first_line) or err_auth:
        return 2, "the reviewer CLI is not logged in (or its login expired): run `kimi` once in a terminal and log in", ""
    if rc in (126, 127):
        return 2, "the reviewer CLI could not be started", ""
    cli_error = CLI_ERROR.search(err or "")
    # A limit can hit mid-review, after the reviewer already wrote progress notes: a failed run (or an empty one) with
    # the CLI's own quota error is the limit, whatever stdout holds. The partial notes are returned, not thrown away.
    if (rc != 0 or not answer) and cli_error and QUOTA.search(cli_error.group(1)):
        return 2, f"the reviewer's account hit a usage or rate limit; wait for it to reset. CLI said: {cli_error.group(1)[:300]}", answer
    unknown = cli_error and UNKNOWN_MODEL.search(cli_error.group(1))
    if (rc != 0 or not answer) and unknown:
        return 2, (f'the reviewer CLI has no model "{unknown.group(1)}": name it as provider/model, e.g. '
                   "--model kimi-code/k3 or kimi-code/k3.1-pro (a bare name works only if your Kimi config defines it)"), ""
    if rc == 124:
        return 1, f"the review did not finish within the timeout ({TIMEOUT_S} s by default, --timeout to change)", answer
    if rc != 0 or not answer:
        said = f" CLI said: {cli_error.group(1)[:300]}" if cli_error else " Rerun with --debug to see its output."
        return 1, f"the reviewer returned no answer (exit code {rc}).{said}", answer
    return 0, "", answer


def save(out_path, ask, answer, note=""):
    """Write the answer as Markdown; a note marks a partial answer (the review stopped early)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    head = f"# Second opinion\n\n> {note}\n\nAsked: {ask}\n\n" if note else f"# Second opinion\n\nAsked: {ask}\n\n"
    out_path.write_text(head + answer + "\n", encoding="utf-8", newline="\n")
    print(f"[ OK ] saved to {out_path}" + (" (incomplete)" if note else ""))


def kill_tree(proc):
    """Stop the CLI and anything it started (a helper holding our pipes would otherwise outlive the timeout)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=30)
        else:
            os.killpg(proc.pid, 9)
    except (OSError, subprocess.SubprocessError):
        pass
    proc.kill()


def run(cmd, cwd, timeout):
    dbg("run: " + " ".join(cmd[:4]) + " ...")
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                encoding="utf-8", errors="replace", **group)
    except FileNotFoundError:
        return 127, "", ""
    except OSError:
        return 126, "", ""
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return 124, out or "", err or ""


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="Ask another AI model (the Kimi Code CLI) for a read-only review and print its answer.",
        epilog="The reviewer can read the project, never change it. Exit codes: 0 answer printed, 1 no usable answer "
               "(timeout, empty), 2 environment (CLI missing or not logged in, bad arguments).")
    ap.add_argument("--ask", help="what to review and what to look for")
    ap.add_argument("--files", nargs="*", default=[], help="files for the reviewer to read (paths relative to the project)")
    ap.add_argument("--model", help="model as the CLI names it, provider/model (default: the CLI's own default), "
                    "e.g. kimi-code/k3 or kimi-code/k3.1-pro")
    ap.add_argument("--cli", help="path to the kimi executable (default: PATH, then ~/.kimi-code/bin)")
    ap.add_argument("--root", default=str(ROOT), help="project folder the reviewer reads (default: this project)")
    ap.add_argument("--out", help="also save the answer to this file (Markdown), relative to the project")
    ap.add_argument("--timeout", type=int, default=TIMEOUT_S, help=f"seconds before giving up (default {TIMEOUT_S})")
    ap.add_argument("--check", action="store_true", help="only check that the CLI is installed and logged in")
    ap.add_argument("--debug", action="store_true", help="print the command and the CLI's raw output")
    args = ap.parse_args(argv)
    DEBUG = args.debug
    try:
        root = Path(args.root).resolve()
        cli = find_cli(args.cli)
        if not cli:
            print("[error] the Kimi Code CLI (`kimi`) was not found. Install it (kimi.com/code), open a new terminal, "
                  "or pass --cli <path to kimi>.", file=sys.stderr)
            return 2
        if not AGENT_FILE.is_file():
            print(f"[error] reviewer definition missing: {AGENT_FILE}", file=sys.stderr)
            return 2
        missing = [f for f in args.files if not (root / f).is_file()]
        if missing:
            print(f"[error] not found in {root}: {', '.join(missing)}", file=sys.stderr)
            return 2
        if not args.check and not args.ask:
            print("[error] --ask is required (or use --check)", file=sys.stderr)
            return 2
        prompt = "Reply with exactly: OK" if args.check else build_prompt(args.ask, args.files)
        rc, out, err = run(build_command(cli, prompt, args.model, AGENT_FILE), root, args.timeout)
        if DEBUG:
            print(f"[debug] exit {rc}\n--- stdout ---\n{out}\n--- stderr ---\n{err}")
        code, message, answer = classify(rc, out, err)
        if code:
            print(f"[error] {message}" if code == 2 else f"[FAIL] {message}", file=sys.stderr)
            if answer:
                print(answer)
                if args.out and not args.check:   # keep what was done before the stop, clearly marked
                    save(root / args.out, args.ask, answer, f"INCOMPLETE: {message}")
            return code
        if args.check:
            print(f"[ OK ] {cli} answers ({answer[:40]})")
            return 0
        print(answer)
        if args.out:
            save(root / args.out, args.ask, answer)
        return 0
    except KeyboardInterrupt:
        print("\n[error] interrupted", file=sys.stderr)
        return 1
    except Exception as exc:   # last resort: a clear message, traceback only with --debug
        print(f"[error] unexpected failure: {exc!r}. Re-run with --debug.", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

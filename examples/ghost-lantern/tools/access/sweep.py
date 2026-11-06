#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# sweep.py
# Purpose : The accessibility sweep of the shell's screens (#91) and the Steam Deck pass (#85): runs the game's
#           `dev.py smoke --drive access` at 1920x1080 and at 1280x800 (gamepad only), at 100 % and 200 % text, and
#           checks what every screen reports: text size, text contrast, nothing clipped or off screen, every control
#           reachable with the arrow keys and the gamepad, focus that looks different from hover, both devices bound,
#           subtitles showing the dialogue line, and no keyboard glyphs while the gamepad is in use.
# Usage   : python tools/access/sweep.py                 # all four runs (a few minutes)
#           python tools/access/sweep.py --runs deck     # only the Steam Deck runs (pc, deck, or both: all)
#           python tools/access/sweep.py --report captures/access.md   # also write the results as Markdown
#           python tools/access/sweep.py --log smoke.log --resolution 1280x800   # check a saved drive log
# Notes   : Standard library only. Rules and sources (SOP-20): body text at least 18 px at 1080p, at least 9 px at
#           1280x800 with 12 recommended (F36, E75); text contrast 4.5:1, 3:1 for large text (E158: 18 pt, about
#           1.5 em; a game has no em, so here 1.5 times the screen's smallest text, since every pixel size grows
#           with the window and a 24 px cut-off would call all text large at 1080p);
#           text drawn over the game is checked against its panel or outline over both a black and a white game,
#           the worst case, since the game behind it changes. Engines report sizes in their design resolution and
#           how they scale it (whole numbers on Godot and LÖVE); the window size is the run's. What the drive cannot
#           see (how a screen looks, a real Deck's Proton, on-screen keyboard and suspend) stays a look and a
#           checklist: SOP-19's Steam Deck list. Exit 0 every run passes, 1 a check failed, 2 the game could not run
#           the drive (an engine without it, a crash) or a usage problem.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import glob
import json
import math
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import colour  # noqa: E402

PC_MIN_PX = 18           # F36: smallest body text at 1080p on PC
DECK_MIN_PX = 9          # F36, E75: smallest text at 1280x800
DECK_GOOD_PX = 12        # E75: recommended at 1280x800
CONTRAST = 4.5           # E158: text
CONTRAST_LARGE = 3.0     # E158: large text
LARGE_EM = 1.5           # E158: large text is 18 pt, about 1.5 em: here 1.5 times the screen's body (smallest) text
RUNS = {                 # name: (resolution, text scale, gamepad only, drive extras)
    "pc": ("1920x1080", 1.0, False, ""),
    "pc-200": ("1920x1080", 2.0, False, ""),
    "pc-read": ("1920x1080", 1.0, False, "read"),   # the readable font and double line spacing (#167)
    "deck": ("1280x800", 1.0, True, ""),
    "deck-200": ("1280x800", 2.0, True, ""),
}
RUN_SETS = {"pc": ("pc", "pc-200", "pc-read"), "deck": ("deck", "deck-200"), "all": tuple(RUNS)}
DIALOGUE_GLOB = "data/dialogue/*.built.json"
DRIVE_TIMEOUT_S = 600
MARKER = re.compile(r"\b(ACCESS_[A-Z]+) (.*)$")
OVERLAP_SLACK = 1        # px two glyph boxes may share (antialiasing, rounding) before it counts as overlap


class UsageError(Exception):
    pass


# -------------------------------------------------- reading a drive log
def parse(text):
    """{"input": {...}, "screens": [...], "subtitle": {...} or None, "prompts": {...} or None, "done": bool}."""
    out = {"input": None, "screens": [], "subtitle": None, "prompts": None, "done": False}
    for raw in text.splitlines():
        line = raw.strip()
        if "DRIVE_DONE access" in line:
            out["done"] = True
        m = MARKER.search(line)      # anywhere on the line: a browser's console adds its own prefix
        if not m:
            continue
        tag, body = m.group(1), m.group(2)
        try:
            data = json.loads(body)
        except ValueError:
            raise UsageError(f"the drive printed a broken {tag} line: {body[:80]}")
        if tag == "ACCESS_INPUT":
            out["input"] = data
        elif tag == "ACCESS_SCREEN":
            out["screens"].append(data)
        elif tag == "ACCESS_SUBTITLE":
            out["subtitle"] = data
        elif tag == "ACCESS_PROMPTS":
            out["prompts"] = data
    return out


def scale_for(resolution, design, scaling):
    """Window pixels per design pixel: whole numbers (Godot, LÖVE) or exact (a browser canvas or the DOM)."""
    w, h = (int(v) for v in resolution.split("x"))
    dw, dh = design
    s = min(w / dw, h / dh)
    return max(1, math.floor(s)) if scaling == "integer" else s


def dialogue_lines(root):
    """{line id: text} from the game's built dialogue files."""
    lines = {}
    for path in sorted(glob.glob(str(Path(root) / DIALOGUE_GLOB))):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for lid, row in (data.get("lines") or {}).items():
            if isinstance(row, dict):
                lines[lid] = str(row.get("text", ""))
    return lines


def _worst_backgrounds(layers):
    """The colours a text over the game can end up on: its layers (top first) over a black and over a white game."""
    out = []
    for world in ((0, 0, 0), (255, 255, 255)):
        c = world
        for hexa, alpha in reversed(layers):
            top = colour.parse(hexa)
            c = tuple(round(top[i] * alpha + c[i] * (1 - alpha)) for i in range(3))
        out.append(c)
    return out


# -------------------------------------------------- the checks
def check_run(log, resolution, pad, root):
    """(problems, warnings, stats) for one drive run."""
    problems, warnings = [], []
    if not log["done"]:
        problems.append("the drive did not finish (no DRIVE_DONE access line): see the smoke output")
    inp = log["input"] or {}
    for action, has in sorted((inp.get("actions") or {}).items()):
        for device in ("keyboard", "gamepad"):
            if not has.get(device):
                problems.append(f"input: {action} has no {device} binding")
    deck = resolution == "1280x800"
    smallest = None
    for scr in log["screens"]:
        name = scr.get("screen", "?")
        design = scr.get("design") or scr.get("base") or [640, 360]
        s = scale_for(resolution, design, scr.get("scaling", "integer"))
        shown = [t for t in scr.get("texts", []) if not t.get("covered")]   # under a dialog: not visible
        body = min([float(t.get("px", 0)) for t in shown] or [0])
        for t in shown:
            what = f"{name}: {t.get('text', '')[:40]!r}" + (f" ({t['state']})" if t.get("state") else "")
            px = float(t.get("px", 0)) * s
            smallest = px if smallest is None else min(smallest, px)
            if deck and px < DECK_MIN_PX:
                problems.append(f"{what}: {px:.0f} px at 1280x800 (under {DECK_MIN_PX}, E75)")
            elif deck and px < DECK_GOOD_PX:
                warnings.append(f"{what}: {px:.0f} px at 1280x800 ({DECK_GOOD_PX} recommended, E75)")
            elif not deck and px < PC_MIN_PX:
                problems.append(f"{what}: {px:.0f} px at {resolution} (under {PC_MIN_PX}, F36)")
            need = CONTRAST_LARGE if body and float(t.get("px", 0)) >= LARGE_EM * body else CONTRAST
            fg = colour.parse(t["fg"])
            if t.get("bg"):
                ratio = colour.contrast(fg, colour.parse(t["bg"]))
                where = t["bg"]
            elif t.get("outline"):
                ratio = colour.contrast(fg, colour.parse(t["outline"]))
                where = f"its outline {t['outline']}"
            elif t.get("over_game"):
                ratio = min(colour.contrast(fg, b) for b in _worst_backgrounds(t["over_game"]))
                where = "its panel over the game (worst case)"
            else:
                ratio, where = None, ""
                problems.append(f"{what}: drawn over the game with no panel or outline (its contrast depends on "
                                "whatever is behind it)")
            if ratio is not None and ratio < need:
                problems.append(f"{what}: contrast {ratio:.2f}:1 against {where} (needs {need:g}:1, E158)")
            if not t.get("fits", True):
                problems.append(f"{what}: clipped or off screen" + (f" ({t['why']})" if t.get("why") else ""))
        problems += overlaps(name, shown)
        focus = scr.get("focus") or {}
        for path in focus.get("unreached", []):
            problems.append(f"{name}: {path} cannot be reached with the arrow keys or the gamepad")
        for path in focus.get("focus_like_hover", []):
            problems.append(f"{name}: {path} looks the same focused as hovered")
        if focus.get("controls", 0) and not focus.get("start"):
            problems.append(f"{name}: nothing has focus, so the keyboard and the gamepad cannot start")
    sub = log["subtitle"]
    if sub is None:
        problems.append("no subtitle was reported (the drive shows the demo's line)")
    else:
        lines = dialogue_lines(root)
        if not sub.get("visible") or not sub.get("text"):
            problems.append("subtitles: the demo's line is not on screen with subtitles on")
        elif sub.get("id") in lines and lines[sub["id"]] != sub["text"]:
            problems.append(f"subtitles: shows {sub['text']!r}, the dialogue file says {lines[sub['id']]!r}")
    pr = log["prompts"]
    if pad and pr is not None:
        if not str(pr.get("device", "")).startswith("pad"):
            problems.append(f"prompts: the device is {pr.get('device')!r} after gamepad-only input")
        for action, row in sorted((pr.get("actions") or {}).items()):
            if row.get("shown") and row.get("shown") == row.get("keyboard"):
                problems.append(f"prompts: {action} shows the keyboard's {row['shown']!r} while the gamepad is in "
                                "use (E75)")
    stats = {"screens": len(log["screens"]), "texts": sum(len(s.get("texts", [])) for s in log["screens"]),
             "smallest_px": smallest}
    return problems, warnings, stats


def _hidden(a, b, ra, rb):
    """True when the two texts sit on different panels and the later panel covers the spot where they meet (a
    dialog over the HUD: the text underneath is hidden there, so nothing collides on screen)."""
    ca, cb = a.get("card") or {}, b.get("card") or {}
    if ca.get("order") == cb.get("order"):
        return False
    top = max((c for c in (ca, cb) if c.get("rect")), key=lambda c: c.get("order", -1), default=None)
    if top is None:
        return False
    cx = (max(ra[0], rb[0]) + min(ra[0] + ra[2], rb[0] + rb[2])) / 2
    cy = (max(ra[1], rb[1]) + min(ra[1] + ra[3], rb[1] + rb[3])) / 2
    x, y, w, h = top["rect"]
    return x <= cx <= x + w and y <= cy <= y + h


def overlaps(screen, texts):
    """Texts on one screen whose glyph boxes cross (more than OVERLAP_SLACK px each way): lines that run into each
    other, which a box check alone misses (a centred line can stick out of its box without hitting anything)."""
    boxes = [(t, t["ink"]) for t in texts if isinstance(t.get("ink"), list) and len(t["ink"]) == 4
             and t.get("state", "") in ("", "normal")]
    out = []
    for i, (a, ra) in enumerate(boxes):
        for b, rb in boxes[i + 1:]:
            if a.get("node") == b.get("node"):
                continue
            dx = min(ra[0] + ra[2], rb[0] + rb[2]) - max(ra[0], rb[0])
            dy = min(ra[1] + ra[3], rb[1] + rb[3]) - max(ra[1], rb[1])
            if dx > OVERLAP_SLACK and dy > OVERLAP_SLACK and not _hidden(a, b, ra, rb):
                out.append(f"{screen}: {a.get('text', '')[:30]!r} runs into {b.get('text', '')[:30]!r}")
    return out


# -------------------------------------------------- running the game
def run_drive(root, name, debug):
    resolution, scale, pad, extra = RUNS[name]
    opts = ",".join([f"res={resolution}"] + ([f"scale={scale:g}"] if scale != 1.0 else []) + (["pad"] if pad else [])
                    + ([extra] if extra else []))
    cmd = [sys.executable, "tools/dev.py", "smoke", "--drive", "access:" + opts]
    if debug:
        print(f"[debug] {' '.join(cmd)}", file=sys.stderr)
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, encoding="utf-8", errors="replace",
                           timeout=DRIVE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise UsageError(f"{name}: the drive ran over {DRIVE_TIMEOUT_S} s")
    out = r.stdout + r.stderr
    if r.returncode == 2 and "ACCESS_" not in out:
        raise UsageError(f"{name}: this game's dev.py cannot run the access drive (exit 2):\n  "
                         + "\n  ".join(out.strip().splitlines()[-4:]))
    return out, resolution, pad


def report_md(results):
    lines = ["# Accessibility sweep", ""]
    for name, (problems, warnings, stats) in results.items():
        lines += [f"## {name}: {'pass' if not problems else str(len(problems)) + ' problem(s)'}", "",
                  f"{stats['screens']} screens, {stats['texts']} texts, smallest "
                  f"{stats['smallest_px'] or 0:.0f} px", ""]
        lines += [f"- FAIL {p}" for p in problems] + [f"- warn {w}" for w in warnings] + [""]
    return "\n".join(lines)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(
        description="Run the shell's screens through the accessibility sweep (#91) and the Steam Deck pass (#85).",
        epilog="Exit codes: 0 pass, 1 a check failed, 2 the drive could not run or a usage problem. SOP-20 has the "
               "rules and their sources; SOP-19 the Steam Deck checklist a program cannot do.")
    p.add_argument("--runs", choices=sorted(RUN_SETS), default="all",
                   help="pc (1920x1080 at 100 and 200 %% text, and with the readable font and double line spacing), "
                        "deck (1280x800, gamepad only), or all (default)")
    p.add_argument("--report", default="", help="also write the results as Markdown to this file")
    p.add_argument("--log", default="", help="check a saved `smoke --drive access` log instead of running the game")
    p.add_argument("--resolution", default="1920x1080", help="with --log: the window size it ran at")
    p.add_argument("--pad", action="store_true", help="with --log: it was a gamepad-only run")
    p.add_argument("--root", default=".", help="the game folder (default: here)")
    p.add_argument("--debug", action="store_true", help="print the commands and tracebacks")
    args = p.parse_args(argv)
    root = Path(args.root)
    try:
        results = {}
        if args.log:
            text = Path(args.log).read_text(encoding="utf-8", errors="replace")
            results[Path(args.log).name] = check_run(parse(text), args.resolution, args.pad, root)
        else:
            if not (root / "tools" / "dev.py").is_file():
                raise UsageError(f"{root}: no tools/dev.py (run this in a game folder)")
            for name in RUN_SETS[args.runs]:
                print(f"[info] {name}: {RUNS[name][0]}, text {RUNS[name][1]:g}x"
                      f"{', gamepad only' if RUNS[name][2] else ''}"
                      f"{', readable font, double line spacing' if RUNS[name][3] == 'read' else ''} ...", flush=True)
                out, resolution, pad = run_drive(root, name, args.debug)
                log = parse(out)
                if log["input"] is None:
                    raise UsageError(f"{name}: the access drive never started: the game's main scene does not run the "
                                     "kit's front end (the shell's screens), so there is nothing for the sweep to "
                                     "walk; check your own screens by hand against SOP-20")
                results[name] = check_run(log, resolution, pad, root)
    except (UsageError, OSError) as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    failed = 0
    for name, (problems, warnings, stats) in results.items():
        mark = "[ OK ]" if not problems else "[FAIL]"
        print(f"{mark} {name}: {stats['screens']} screens, {stats['texts']} texts, smallest "
              f"{stats['smallest_px'] or 0:.0f} px, {len(problems)} problem(s), {len(warnings)} warning(s)")
        for msg in problems:
            print(f"  [FAIL] {msg}")
        for msg in warnings:
            print(f"  [warn] {msg}")
        failed += bool(problems)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(report_md(results), encoding="utf-8")
        print(f"[ OK ] report: {args.report}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

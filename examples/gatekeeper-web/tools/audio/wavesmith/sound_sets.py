#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# sound_sets.py
# Purpose : Whole families of sounds made and checked together, so a game never ships footsteps for four surfaces
#           out of five, a double step among single ones, or one take 6 dB louder than its siblings: footsteps per
#           surface and ambience beds (local_sfx.py, Stable Audio 3 on your own ComfyUI), and a UI set made from code
#           (sfx_synth.py, ship-safe: no model, no third-party rights). Writes the audio_events.json entries for them.
# Usage   : python tools/audio/wavesmith/wavesmith.py sets ui --out assets/audio/ui                  # the code-made UI set (12)
#           python tools/audio/wavesmith/wavesmith.py sets plan data/sound_sets.json                 # what make would render
#           python tools/audio/wavesmith/wavesmith.py sets make data/sound_sets.json --set footsteps # GPU: ComfyUI must be up
#           python tools/audio/wavesmith/wavesmith.py sets check data/sound_sets.json               # --ship: license must allow it
#           python tools/audio/wavesmith/wavesmith.py sets events data/sound_sets.json --root assets/audio --merge data/audio_events.json
# Needs   : Python 3.8+ only; `make` with local_sfx sets needs a running ComfyUI with Stable Audio 3 (see local_sfx.py)
# Exit    : 0 ok, 1 check problems (or make failures), 2 usage or unreadable files
# Notes   : A sets file: {"version": 1, "out_dir": "assets/audio", "target": "home", "sets": {<name>: {"generator":
#           "local_sfx" | "sfx_synth", "bus": "sfx", "kind": "oneshot" | "loop", "takes": 4, "seconds": 0.6,
#           "onsets": 1, "prompt": "... {} ...", "variants": {<variant>: "words for {}" | {sfx_synth params}},
#           "event": {extra audio_events fields}}}}. Files: <out_dir>/<set>/<set>_<variant>_<n>.wav (no _<n> when
#           takes is 1), each with its generator's sidecar (.gen.json or .sfx.json) that says where it came from.
#           make sets each file to its bus's house level (loudness.py conventions; max momentary loudness for one-shots,
#           integrated for loops, true peak capped at -1 dBTP) and keeps loop points.
#           check: every variant has all its takes and nothing extra; one-shots have exactly `onsets` attacks (a
#           "footstep" prompt often comes back as two or three steps); takes of a variant within 3 LU of each other and
#           every file within 2 LU of its bus level; loops have a loop point and a clean seam; the sidecar names a
#           license. Stable Audio output is under the Stability AI Community License (check it before you ship, see
#           local_sfx.py); sfx_synth output is yours: only that counts as ship-safe for `check --ship`.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   load + validate the sets file (names, generator, kind, takes, variants, prompt has {} for local_sfx)
#   plan:   every (set, variant) -> file names + the generator call
#   make:   local_sfx.main(make prompt --variants 2*takes --keep takes) | sfx_synth.make(params, seed)
#           -> level each file to its bus (gain only, true peak <= -1 dBTP, loop chunk kept)
#   check:  per variant: expected files present, no strays, sidecar + license; per file: onsets (5 ms envelope,
#           re-armed after 40 ms below -24 dB of the peak, attacks within attack_gap_s merged), level vs bus, loop
#           seam; spread between takes
#   events: one audio_events event per variant (files, random_no_repeat, set's "event" fields) -> print or --merge
#   ui:     the built-in UI recipes -> sfx_synth -> leveled WAVs + .sfx.json marked ship_safe
import argparse
import json
import math
import re
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audio_events  # noqa: E402
import loudness  # noqa: E402
import sfx_synth  # noqa: E402
from wavfile import read_wav_channels, stats, write_wav  # noqa: E402

VERSION = 1
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,31}$")
GENERATORS = ("local_sfx", "sfx_synth")
KINDS = ("oneshot", "loop")
TP_CEILING = -1.0
TAKE_SPREAD_LU = 3.0          # same limit as audio_events.py audit
BUS_TOLERANCE_LU = 2.0
ENV_S = 0.005                 # onset envelope frame
ONSET_DB = -18.0              # an attack: the envelope rises above this, relative to the file's peak frame
REARM_DB = -24.0              # ...after staying below this
REARM_S = 0.04                # ...for this long
ATTACK_GAP_S = 0.2            # attacks closer than this are one event (default; a set can set "attack_gap_s")
SHIP_SAFE_LICENSE = "code-made with sfx_synth.py: no model, no samples, no third-party rights"
# The code-made UI set: twelve sounds a menu needs, as sfx_synth parameters (tuned by ear 2026-11-01)
UI_SET = {
    "click":      {"wave": "square", "freq": 1800, "duty": 0.5, "sustain": 0.004, "decay": 0.025, "lowpass": 7000,
                   "volume": 0.4},
    "hover":      {"wave": "sine", "freq": 2400, "sustain": 0.0, "decay": 0.03, "volume": 0.25},
    "confirm":    {"wave": "square", "freq": 660, "arp_mult": 1.5, "arp_time": 0.05, "duty": 0.5, "sustain": 0.08,
                   "decay": 0.12, "lowpass": 6000, "volume": 0.35},
    "back":       {"wave": "square", "freq": 520, "slide": -1.5, "duty": 0.5, "sustain": 0.04, "decay": 0.08,
                   "lowpass": 5000, "volume": 0.35},
    "error":      {"wave": "square", "freq": 220, "arp_mult": 0.84, "arp_time": 0.07, "duty": 0.5, "sustain": 0.12,
                   "decay": 0.1, "lowpass": 2500, "volume": 0.4},
    "toggle_on":  {"wave": "triangle", "freq": 880, "slide": 3.0, "sustain": 0.03, "decay": 0.05, "volume": 0.45},
    "toggle_off": {"wave": "triangle", "freq": 1300, "slide": -3.0, "sustain": 0.03, "decay": 0.05, "volume": 0.45},
    "open":       {"wave": "triangle", "freq": 400, "slide": 2.5, "sustain": 0.08, "decay": 0.1, "volume": 0.45},
    "close":      {"wave": "triangle", "freq": 900, "slide": -2.5, "sustain": 0.08, "decay": 0.1, "volume": 0.45},
    "notify":     {"wave": "sine", "freq": 1046, "arp_mult": 1.26, "arp_time": 0.09, "sustain": 0.16, "decay": 0.25,
                   "volume": 0.4},
    "tick":       {"wave": "square", "freq": 3000, "duty": 0.5, "sustain": 0.002, "decay": 0.012, "volume": 0.25},
    "type":       {"wave": "square", "freq": 2200, "duty": 0.3, "sustain": 0.002, "decay": 0.015, "lowpass": 6000,
                   "volume": 0.3},
}
DEBUG = False


class ToolError(Exception):
    """Exit 2: usage or a file that cannot be read."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


# ---- the sets file ---------------------------------------------------------------------------------------------------
def load_sets(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"cannot read {path}: {exc}")
    errors = validate(data)
    if errors:
        raise ToolError(f"{path}:\n  " + "\n  ".join(errors))
    return data


def validate(data):
    """List of problems in a sets file (empty when it is good)."""
    errors = []
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return [f"version must be {VERSION}"]
    if data.get("target", "home") not in loudness.ASWG:
        errors.append(f"target must be one of {', '.join(loudness.ASWG)}")
    sets = data.get("sets")
    if not isinstance(sets, dict) or not sets:
        return errors + ["sets must be an object with at least one set"]
    for name, s in sets.items():
        where = f"set {name}"
        if not NAME_RE.match(name):
            errors.append(f"{where}: name must be lowercase letters, digits and _ (up to 32)")
        if not isinstance(s, dict):
            errors.append(f"{where}: must be an object")
            continue
        gen, kind = s.get("generator"), s.get("kind", "oneshot")
        if gen not in GENERATORS:
            errors.append(f"{where}: generator must be local_sfx or sfx_synth")
        if kind not in KINDS:
            errors.append(f"{where}: kind must be oneshot or loop")
        if gen == "sfx_synth" and kind == "loop":
            errors.append(f"{where}: sfx_synth makes one-shots; loops come from local_sfx")
        if s.get("bus") not in loudness.HOUSE:
            errors.append(f"{where}: bus must be one of {', '.join(loudness.HOUSE)}")
        takes = s.get("takes", 1)
        if not isinstance(takes, int) or isinstance(takes, bool) or not 1 <= takes <= 16:
            errors.append(f"{where}: takes must be a whole number 1..16")
        onsets = s.get("onsets")
        if onsets is not None and (kind == "loop" or not isinstance(onsets, int) or onsets < 1):
            errors.append(f"{where}: onsets is a whole number 1 or more, for one-shots")
        renders = s.get("renders", max(2 * takes, 4) if isinstance(takes, int) else 4)
        if isinstance(renders, bool) or not isinstance(renders, int) or not (isinstance(takes, int) and
                                                                               takes <= renders <= 64):
            errors.append(f"{where}: renders must be a whole number from takes up to 64 (local_sfx renders this many "
                          "and keeps the best)")
        gap = s.get("attack_gap_s", ATTACK_GAP_S)
        if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not 0 <= gap <= 2:
            errors.append(f"{where}: attack_gap_s must be 0..2 seconds")
        if gen == "local_sfx":
            if not isinstance(s.get("seconds"), (int, float)) or not 0.05 <= s["seconds"] <= 120:
                errors.append(f"{where}: seconds must be 0.05..120 (local_sfx renders to a length)")
            if not isinstance(s.get("prompt"), str) or s["prompt"].count("{}") != 1:
                errors.append(f"{where}: prompt must contain {{}} once (each variant's words go there)")
        variants = s.get("variants")
        if not isinstance(variants, dict) or not variants:
            errors.append(f"{where}: variants must be an object with at least one variant")
            continue
        for v, spec in variants.items():
            if not NAME_RE.match(v):
                errors.append(f"{where} variant {v}: name must be lowercase letters, digits and _")
            if gen == "local_sfx" and not (isinstance(spec, str) and spec.strip()):
                errors.append(f"{where} variant {v}: give the words that fill the prompt's {{}}")
            if gen == "sfx_synth":
                try:
                    sfx_synth.check_params(spec if isinstance(spec, dict) else {"bad": spec})
                except sfx_synth.SynthError as exc:
                    errors.append(f"{where} variant {v}: {exc}")
        if not isinstance(s.get("event", {}), dict):
            errors.append(f"{where}: event must be an object of audio_events.json fields")
    return errors


def take_names(set_name, variant, takes):
    stem = f"{set_name}_{variant}"
    return [f"{stem}.wav"] if takes == 1 else [f"{stem}_{n}.wav" for n in range(1, takes + 1)]


def plan(data, only_set=None, only_variant=None):
    """[(set name, set, variant, spec, [relative file paths])] in file order."""
    out = []
    for name, s in data["sets"].items():
        if only_set and name != only_set:
            continue
        for v, spec in s["variants"].items():
            if only_variant and v != only_variant:
                continue
            out.append((name, s, v, spec, [f"{name}/{f}" for f in take_names(name, v, s.get("takes", 1))]))
    return out


# ---- measuring -------------------------------------------------------------------------------------------------------
def read_channels(path):
    samples, rate, loop, channels = read_wav_channels(path)
    return [samples[c::channels] for c in range(channels)], rate, loop


def level(chans, rate, kind):
    """(loudness in LUFS, how it was measured). Loops: integrated (BS.1770). One-shots: the loudest 400 ms window
    (EBU Tech 3341 momentary), with clips shorter than 400 ms padded with silence, so short and long takes compare."""
    if kind == "loop":
        m = loudness.measure_channels(chans, rate, want_tp=False)
        if m["integrated_lufs"] is not None:
            return m["integrated_lufs"], "integrated"
    pad = max(int(0.4 * rate), -(-len(chans[0]) // int(0.1 * rate)) * int(0.1 * rate)) - len(chans[0])
    subs = [loudness.sub_block_energy(list(c) + [0.0] * pad, rate) for c in chans]
    windows = loudness.window_loudness(subs, 4)
    best = max((l for l, _ in windows), default=-math.inf)
    return (round(best, 2) if math.isfinite(best) else None), "momentary max"


def onsets(chans, rate, gap_s=None):
    """Times (s) where an attack starts: the 5 ms envelope rises above ONSET_DB (relative to the loudest frame)
    after at least REARM_S below REARM_DB. Attacks closer than gap_s to the previous one belong to the same event
    (the heel and toe of one step, the crunch that follows it): walking puts steps 0.25 s or more apart."""
    gap_s = ATTACK_GAP_S if gap_s is None else gap_s
    mono = [sum(f) / len(chans) for f in zip(*chans)]
    n = max(1, int(ENV_S * rate))
    env = [math.sqrt(sum(x * x for x in mono[i:i + n]) / n) for i in range(0, len(mono) - n + 1, n)]
    peak = max(env, default=0.0)
    if peak <= 0:
        return []
    on, rearm = peak * 10 ** (ONSET_DB / 20), peak * 10 ** (REARM_DB / 20)
    need = max(1, int(round(REARM_S / ENV_S)))
    out, armed, quiet = [], True, 0                 # the start of the file counts as quiet
    for k, e in enumerate(env):
        t = round(k * ENV_S, 3)
        if e >= on and armed:
            if not out or t - out[-1] >= gap_s:
                out.append(t)
            armed = False
        quiet = quiet + 1 if e < rearm else 0      # rising through the band between rearm and on keeps the arm
        if quiet >= need:
            armed = True
    return out


def set_level(path, bus, target, kind):
    """Gain the file to its bus house level, true peak capped; keeps the loop chunk. Returns (gain dB, note)."""
    samples, rate, loop, channels = read_wav_channels(path)
    chans = [samples[c::channels] for c in range(channels)]
    now, how = level(chans, rate, kind)
    if now is None:
        raise ToolError(f"{path}: silent")
    goal = loudness.ASWG[target] + loudness.HOUSE[bus]
    gain, note = goal - now, f"{how} {now:.1f} -> {goal:.0f} LUFS"
    tp = loudness.db(loudness.true_peak(chans, rate))
    if tp + gain > TP_CEILING:
        gain, note = TP_CEILING - tp, note + f" (capped by true peak at {TP_CEILING:.0f} dBTP)"
    g = 10 ** (gain / 20)
    write_wav(path, [s * g for s in samples], rate, loop=loop, channels=channels)
    return round(gain, 2), note


def sidecar(wav):
    for suffix in (".gen.json", ".sfx.json"):
        p = wav.with_suffix(suffix)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                return {"_unreadable": str(p.name)}
    return None


def pick_takes(folder, stem, renders, paths, s):
    """Keep the renders with the expected number of attacks first (in local_sfx's rank order), the rest after them
    only to fill the set (check will flag those); rename them to the set's names; remove the other renders."""
    names = [folder / f"{stem}.wav"] if renders == 1 else [folder / f"{stem}_{k}.wav" for k in range(1, renders + 1)]
    def attacks(path):
        chans, rate, _ = read_channels(path)
        return len(onsets(chans, rate, s.get("attack_gap_s")))
    found = [p for p in names if p.exists()]
    good = [p for p in found if attacks(p) == s["onsets"]]
    order = good + [p for p in found if p not in good]
    if len(order) < len(paths):
        raise ToolError(f"only {len(order)} usable render(s) for {len(paths)} take(s): raise renders")
    for src, dst in zip(order, paths):
        src.replace(dst)
        side = src.with_suffix(".gen.json")
        if side.exists():
            side.replace(dst.with_suffix(".gen.json"))
    for extra in order[len(paths):]:                       # renders this call made and did not keep
        extra.unlink()
        if extra.with_suffix(".gen.json").exists():
            extra.with_suffix(".gen.json").unlink()
    return (f"[pick] {len(good)} of {len(found)} render(s) have {s['onsets']} attack(s); kept "
            f"{min(len(good), len(paths))} of those" + ("" if len(good) >= len(paths) else
                                                         f" and {len(paths) - len(good)} that check will flag"))


# ---- commands --------------------------------------------------------------------------------------------------------
def make_synth(spec, path, meta, overwrite):
    params = sfx_synth.check_params(spec)
    rc, msg = sfx_synth.make(params, 0, path, path.with_suffix(".sfx.json"), meta, overwrite)
    if rc:
        raise ToolError(msg)


def cmd_ui(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, spec in UI_SET.items():
        path = out / f"ui_{name}.wav"
        make_synth(spec, path, {"set": "ui", "variant": name, "ship_safe": True, "license": SHIP_SAFE_LICENSE},
                   args.overwrite)
        gain, note = set_level(path, "ui", args.target, "oneshot")
        print(f"[ OK ] {path.as_posix()}: {note}")
    print(f"[ OK ] {len(UI_SET)} UI sounds, ship-safe ({SHIP_SAFE_LICENSE})")
    return 0


def cmd_plan(args):
    data = load_sets(args.sets)
    rows = plan(data, args.set, args.variant)
    for name, s, v, spec, files in rows:
        what = s["prompt"].replace("{}", spec) if s["generator"] == "local_sfx" else "sfx_synth recipe"
        print(f"{name}/{v}: {len(files)} file(s) via {s['generator']} ({what})")
    print(f"[plan] {sum(len(r[4]) for r in rows)} file(s) under {data.get('out_dir', '.')}")
    return 0


def cmd_make(args):
    data = load_sets(args.sets)
    out_dir = Path(args.root) / data.get("out_dir", ".")
    target, failed = data.get("target", "home"), 0
    for name, s, v, spec, files in plan(data, args.set, args.variant):
        paths = [out_dir / f for f in files]
        paths[0].parent.mkdir(parents=True, exist_ok=True)
        kind = s.get("kind", "oneshot")
        try:
            if s["generator"] == "sfx_synth":
                for n, path in enumerate(paths):
                    # takes of a code-made sound: the same recipe nudged by sfx_synth's seeded jitter
                    p = spec if len(paths) == 1 else sfx_synth.jitter(spec, n + 1, sfx_synth.VARY / 2)
                    make_synth(p, path, {"set": name, "variant": v, "ship_safe": True, "license": SHIP_SAFE_LICENSE},
                               args.overwrite)
            else:
                import local_sfx  # only here: it imports the ComfyUI client
                takes = len(paths)
                renders = s.get("renders", max(2 * takes, 4))
                # one-shots with an attack count: keep every render under a scratch name, then pick by attacks
                picky = kind == "oneshot" and bool(s.get("onsets"))
                if picky and not args.overwrite:
                    taken = [p for p in paths if p.exists()]
                    if taken:
                        raise ToolError(f"{taken[0].as_posix()} exists (use --overwrite); nothing was rendered")
                stem = f"{name}_{v}__take" if picky else f"{name}_{v}"
                argv = ["make", s["prompt"].replace("{}", spec), "--seconds", str(s["seconds"]),
                        "--out", str(out_dir / name / f"{stem}.wav"), "--variants", str(renders),
                        "--keep", str(renders if picky else takes), "--seed", str(args.seed)]
                argv += ["--loop"] if kind == "loop" else []
                argv += ["--mono"] if s.get("mono") else []
                argv += ["--overwrite"] if args.overwrite or picky else []
                argv += ["--url", args.url] if args.url else []
                rc = local_sfx.main(argv)
                if rc:
                    raise ToolError(f"local_sfx exited {rc}")
                if picky:
                    print(pick_takes(out_dir / name, stem, renders, paths, s))
            for path in paths:
                _, note = set_level(path, s["bus"], target, kind)
                print(f"[ OK ] {path.as_posix()}: {note}")
        except (ToolError, sfx_synth.SynthError) as exc:
            print(f"[FAIL] {name}/{v}: {exc}")
            failed += 1
    return 1 if failed else 0


def check_file(path, s, target):
    """(facts, problems) for one file of a set."""
    problems = []
    chans, rate, loop = read_channels(path)
    kind = s.get("kind", "oneshot")
    lufs, how = level(chans, rate, kind)
    goal = loudness.ASWG[target] + loudness.HOUSE[s["bus"]]
    facts = {"file": path.name, "lufs": lufs, "measure": how, "seconds": round(len(chans[0]) / rate, 3)}
    if lufs is None:
        return facts, ["silent"]
    tp = loudness.db(loudness.true_peak(chans, rate))
    facts["true_peak_dbtp"] = round(tp, 2)
    if tp > TP_CEILING + 0.05:
        problems.append(f"true peak {tp:.1f} dBTP is over {TP_CEILING:.0f}")
    capped = abs(tp - TP_CEILING) < 0.1 and lufs < goal     # set_level stopped at the ceiling: not a level problem
    if abs(lufs - goal) > BUS_TOLERANCE_LU and not capped:
        problems.append(f"{how} {lufs:.1f} LUFS is {lufs - goal:+.1f} LU from the {s['bus']} level {goal:.0f}")
    if kind == "oneshot" and s.get("onsets"):
        found = onsets(chans, rate, s.get("attack_gap_s"))
        facts["onsets"] = found
        if len(found) != s["onsets"]:
            problems.append(f"{len(found)} attacks (at {', '.join(f'{t:.2f}' for t in found)} s), expected "
                            f"{s['onsets']}")
    if kind == "loop":
        if not loop:
            problems.append("no loop point (make it with local_sfx --loop)")
        else:
            st = stats([sum(f) / len(chans) for f in zip(*chans)], rate, loop)
            facts["loop_seam_ok"] = st["loop_seam_ok"]
            if not st["loop_seam_ok"]:
                problems.append(f"loop seam jumps {st['loop_seam_step']} (a click)")
        if s.get("seconds") and facts["seconds"] < 0.8 * s["seconds"]:
            problems.append(f"{facts['seconds']} s, asked for {s['seconds']} s")
    meta = sidecar(path)
    if meta is None:
        problems.append("no .gen.json or .sfx.json next to it: where did it come from?")
    else:
        facts["license"] = meta.get("license", "")
        facts["ship_safe"] = bool(meta.get("ship_safe")) and meta.get("tool") == "sfx_synth"
        if not facts["license"]:
            problems.append("its sidecar names no license")
    return facts, problems


def cmd_check(args):
    data = load_sets(args.sets)
    out_dir = Path(args.root) / data.get("out_dir", ".")
    target = data.get("target", "home")
    report, n_problems, n_files = {}, 0, 0
    for name, s, v, spec, files in plan(data, args.set, args.variant):
        problems, facts = [], []
        for rel in files:
            path = out_dir / rel
            if not path.exists():
                problems.append(f"missing {rel}")
                continue
            try:
                f, p = check_file(path, s, target)
            except ValueError as exc:
                problems.append(f"{rel}: {exc}")
                continue
            n_files += 1
            facts.append(f)
            problems += [f"{rel}: {x}" for x in p]
            if args.ship and not f.get("ship_safe"):
                problems.append(f"{rel}: not ship-safe ({f.get('license') or 'no license'}): clear the license first")
        expected = {Path(rel).name for rel in files}
        stray = sorted(p.name for p in (out_dir / name).glob(f"{name}_{v}*.wav") if p.name not in expected
                       and re.fullmatch(rf"{re.escape(name)}_{re.escape(v)}(_\d+)?\.wav", p.name))
        problems += [f"extra take {x} (not in the set: remove it or raise takes)" for x in stray]
        levels = [f["lufs"] for f in facts if f.get("lufs") is not None]
        if len(levels) > 1 and max(levels) - min(levels) > TAKE_SPREAD_LU:
            problems.append(f"takes are {max(levels) - min(levels):.1f} LU apart (limit {TAKE_SPREAD_LU:.0f})")
        report[f"{name}/{v}"] = {"files": facts, "problems": problems}
        n_problems += len(problems)
        mark = "[ OK ]" if not problems else "[FAIL]"
        print(f"{mark} {name}/{v}: {len(facts)}/{len(files)} file(s)" +
              "".join(f"\n       - {p}" for p in problems))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[{'FAIL' if n_problems else ' OK '}] {n_files} file(s) in {len(report)} variant(s), {n_problems} problem(s)")
    return 1 if n_problems else 0


def events_for(data, root):
    """audio_events.json events for every variant: id <set>_<variant>, files relative to the audio root."""
    out_dir = Path(data.get("out_dir", "."))
    events = {}
    for name, s, v, spec, files in plan(data):
        rel = [(out_dir / f).as_posix() for f in files]
        if root:
            base = Path(root).as_posix().rstrip("/") + "/"
            rel = [r[len(base):] if r.startswith(base) else r for r in rel]
        ev = {"bus": s["bus"], "files": rel}
        if len(rel) > 1:
            ev["pick"] = "random_no_repeat"
        if s.get("kind") == "loop":
            ev["max_voices"] = 1
        for k, val in s.get("event", {}).items():
            ev[k] = val.replace("{variant}", v.replace("_", " ")) if isinstance(val, str) else val
        events[f"{name}_{v}"] = ev
    return events


def cmd_events(args):
    data = load_sets(args.sets)
    events = events_for(data, args.root)
    if not args.merge:
        print(json.dumps({"events": events}, indent=1, ensure_ascii=False))
        return 0
    path = Path(args.merge)
    try:
        target = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"cannot read {path}: {exc}")
    clash = sorted(set(events) & set(target.get("events", {})))
    if clash and not args.overwrite:
        raise ToolError(f"{path} already has {', '.join(clash)} (use --overwrite to replace them); nothing written")
    target.setdefault("events", {}).update(events)
    errors = audio_events.validate(target)
    if errors:
        raise ToolError("the merged file would not validate:\n  " + "\n  ".join(errors))
    path.write_text(json.dumps(target, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[ OK ] {path.as_posix()}: {len(events)} event(s) added or replaced; audio_events.py validate passes")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description="Make and check whole sets of sounds (footsteps per surface, ambience "
                                             "beds, a code-made UI set) and write their audio events.",
                                 epilog="Exit codes: 0 ok, 1 check problems or make failures, 2 usage.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="tracebacks")
    sub = ap.add_subparsers(dest="cmd")
    u = sub.add_parser("ui", parents=[common], help="render the built-in code-made UI set (ship-safe)")
    u.add_argument("--out", required=True, help="folder for ui_<name>.wav")
    u.add_argument("--target", choices=list(loudness.ASWG), default="home")
    u.add_argument("--overwrite", action="store_true")
    for cmd, text in (("plan", "list what make would render"), ("make", "render the sets (local_sfx needs ComfyUI)"),
                      ("check", "completeness, attacks, levels, loops, licenses"),
                      ("events", "audio_events.json entries for the sets")):
        p = sub.add_parser(cmd, parents=[common], help=text)
        p.add_argument("sets", help="the sets file (data/sound_sets.json)")
        if cmd != "events":
            p.add_argument("--set", help="only this set")
            p.add_argument("--variant", help="only this variant")
        if cmd in ("make", "check"):
            p.add_argument("--root", default=".", help="project root out_dir is relative to")
        if cmd == "make":
            p.add_argument("--seed", type=int, default=1, help="first local_sfx seed")
            p.add_argument("--url", help="ComfyUI address (local_sfx default otherwise)")
            p.add_argument("--overwrite", action="store_true")
        if cmd == "check":
            p.add_argument("--ship", action="store_true", help="also fail on files whose license is not cleared")
            p.add_argument("--json", help="write the full report here")
        if cmd == "events":
            p.add_argument("--root", help="the audio root the events' paths are relative to (e.g. assets/audio)")
            p.add_argument("--merge", help="add the events to this audio_events.json (validated before writing)")
            p.add_argument("--overwrite", action="store_true", help="with --merge: replace events with the same id")
    return ap


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2
    DEBUG = args.debug
    try:
        return {"ui": cmd_ui, "plan": cmd_plan, "make": cmd_make, "check": cmd_check, "events": cmd_events}[args.cmd](args)
    except (ToolError, sfx_synth.SynthError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

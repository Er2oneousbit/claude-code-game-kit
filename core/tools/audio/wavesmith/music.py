#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# music.py
# Purpose : Adaptive music as data (data/music.json: tracks on a BPM and bar grid, stems that play in sync, stingers,
#           and a transition map that says when a change may happen: now, next beat, next bar, next phrase, loop end)
#           plus the tools around it: cut a rendered or recorded piece into a bar-aligned loop, check a game's music
#           files against the grid, estimate a file's tempo, and the reference transition planner whose golden vectors
#           (data/golden/music.json) every engine's music player reproduces sample for sample.
# Usage   : python tools/audio/wavesmith/wavesmith.py music grid --bpm 96 --bars 8                       # bar start times and samples
#           python tools/audio/wavesmith/wavesmith.py music loop raw/explore.wav --bpm 96 --bars 8 --out assets/audio/music/explore.wav
#           python tools/audio/wavesmith/wavesmith.py music validate data/music.json --root assets/audio
#           python tools/audio/wavesmith/wavesmith.py music plan data/music.json --from explore --to combat --at 3.2   # when, where
#           python tools/audio/wavesmith/wavesmith.py music tempo raw/explore.wav                         # about 96 BPM?
#           python tools/audio/wavesmith/wavesmith.py music vectors --check                               # golden file current? (exit 1)
# Needs   : Python 3.8+ only (wavfile.py, same folder)
# Exit    : 0 ok, 1 validation problems or stale vectors, 2 usage or unreadable files
# Notes   : Everything is counted in samples at the file's rate, so every engine lands on the same sample: beat k of
#           a track starts at floor(k * 60 * rate / bpm + 0.5) (half rounds up in every language; Python's round()
#           and JavaScript's Math.round() disagree on halves, so neither is used). A track loops from loop_start_bar
#           (an intro plays once before it) to its last bar. `loop` cuts N bars and adds whatever rings past the loop
#           end (reverb, a decaying note) back onto the loop's start, so the loop has no click and keeps its tail; it
#           writes a 'smpl' loop chunk on the bar grid that Godot and Unity read, and the web player uses the same
#           points (Godot 4.7 loops from the sample after loop_begin, one sample short a pass: the kit's Godot music
#           player corrects it; a plain AudioStreamPlayer loop drifts by a sample each loop). Stems of a track must have the same rate, channels and length: they start together and stay
#           locked. A stinger plays at the switch point and the next track enters after the stinger's bars.
#           `tempo` is an estimate (onset autocorrelation) for checking generated music; it can be off by a factor of
#           two on sparse material.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-03 with Claude (Opus 5.5, claude-opus-5-5): validate checks default_transition like a
#           transitions entry (every rule inherits it)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   beat_sample(k) = floor(k * 60 * rate / bpm + 0.5); bar b starts at beat_sample(b * beats_per_bar)
#   position(track, playing since s0, now t): p = t - s0 + entry; past the loop end -> wrap into the loop
#   plan(from, to, t): rule (exact pair, from *, to *, default) -> next boundary of its quantize at or after p
#                      -> switch_at = t + (boundary - p); stinger? target enters after the stinger's bars
#                      -> target entry offset 0, or the same position in the bar when "sync" and the grids match
#   loop: read -> keep bars [0, N) -> add the tail past N onto the start -> smpl loop on the grid -> write
#   validate: tracks, stems (exist, same shape, long enough, loop chunk on the grid), stingers, transitions and
#             default_transition (the same rule checks)
#   tempo: 10 ms onset envelope -> autocorrelation over 60..200 BPM -> best lag
#   vectors: scripted plans through the reference -> data/golden/music.json (--write / --check)
import argparse
import json
import math
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audioio  # noqa: E402
from wavfile import read_wav_channels  # noqa: E402

VERSION = 1
QUANTIZE = ("immediate", "beat", "bar", "phrase", "loop_end")
DEFAULT_RULE = {"quantize": "bar", "fade_ms": 0, "sync": False}
MAX_STINGER_BARS = 8
TEMPO_RANGE = (60.0, 200.0)
BPM_RANGE = (20, 400)        # what validate accepts in music.json, and grid / loop on the command line
BEATS_PER_BAR_RANGE = (1, 16)
GOLDEN = HERE.parents[2] / "data" / "golden" / "music.json"
DEBUG = False


class ToolError(Exception):
    """Exit 2: usage or a file that cannot be read."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


# ---- The grid ----------------------------------------------------------------------------------------------------
def beat_sample(k, bpm, rate):
    """First sample of beat k (k may be any whole number)."""
    return math.floor(k * 60 * rate / bpm + 0.5)


def bar_sample(b, track, rate):
    return beat_sample(b * track.get("beats_per_bar", 4), track["bpm"], rate)


def bar_index_at(sample, track, rate):
    """The bar that contains `sample` (exact on the rounded grid, not a float estimate)."""
    b = math.floor(sample * track["bpm"] / (60 * rate * track.get("beats_per_bar", 4)))
    while bar_sample(b + 1, track, rate) <= sample:
        b += 1
    while b > 0 and bar_sample(b, track, rate) > sample:
        b -= 1
    return b


def loop_points(track, rate):
    """(loop start sample, loop end sample): the loop plays [start, end) forever after the intro."""
    return bar_sample(track.get("loop_start_bar", 0), track, rate), bar_sample(track["bars"], track, rate)


def position(track, rate, since, now, entry=0):
    """Where in the track (samples from its start) playback is at `now`, when it started at `since` from `entry`."""
    p = now - since + entry
    start, end = loop_points(track, rate)
    if p >= end:
        p = start + (p - start) % (end - start)
    return p


def next_boundary(track, rate, p, quantize, phrase_bars=4):
    """The first boundary of the given kind at or after track position p (a loop position: 0 <= p < loop end)."""
    if quantize == "immediate":
        return p
    bpb = track.get("beats_per_bar", 4)
    start, end = loop_points(track, rate)
    if quantize == "loop_end":
        return end
    step = {"beat": 1, "bar": bpb, "phrase": bpb * phrase_bars}[quantize]
    # the beat at or after p, then up to the next multiple of step (counted from the track's first beat)
    k = math.floor(p * track["bpm"] / (60 * rate))
    while beat_sample(k, track["bpm"], rate) < p:
        k += 1
    while k % step:
        k += 1
    return min(beat_sample(k, track["bpm"], rate), end)


def rule_for(data, frm, to):
    """The transition rule: exact pair, then from "*", then to "*", then the file's default, then DEFAULT_RULE."""
    rules = data.get("transitions", [])
    for want in ((frm, to), ("*", to), (frm, "*")):
        for r in rules:
            if (r.get("from"), r.get("to")) == want:
                return {**DEFAULT_RULE, **data.get("default_transition", {}), **r}
    return {**DEFAULT_RULE, **data.get("default_transition", {})}


def plan(data, frm, since, entry, to, now):
    """When and how to change from track `frm` (playing since sample `since` from offset `entry`) to `to`, asked at
    sample `now`. Returns {switch_at, from_stop_at, to_start_at, to_offset, fade, stinger, stinger_at}."""
    rate = data["sample_rate"]
    a, b = data["tracks"][frm], data["tracks"][to]
    rule = rule_for(data, frm, to)
    p = position(a, rate, since, now, entry)
    boundary = next_boundary(a, rate, p, rule["quantize"], rule.get("phrase_bars", 4))
    switch_at = now + (boundary - p)
    fade = math.floor(rule.get("fade_ms", 0) * rate / 1000 + 0.5)
    out = {"switch_at": switch_at, "from_stop_at": switch_at + fade, "fade": fade, "to_offset": 0,
           "to_start_at": switch_at, "stinger": rule.get("stinger"), "stinger_at": None}
    if rule.get("stinger"):
        st = data["stingers"][rule["stinger"]]
        out["stinger_at"] = switch_at
        out["to_start_at"] = switch_at + beat_sample(st["bars"] * b.get("beats_per_bar", 4), b["bpm"], rate)
    elif rule.get("sync") and a["bpm"] == b["bpm"] and a.get("beats_per_bar", 4) == b.get("beats_per_bar", 4):
        # keep the beat: enter the target at the same place in its bar (bar boundaries are where they line up)
        out["to_offset"] = boundary - bar_sample(bar_index_at(boundary, a, rate), a, rate)
    return out


# ---- Loop cutting ------------------------------------------------------------------------------------------------
def make_loop(samples, rate, channels, bpm, bars, beats_per_bar=4, tail_s=None):
    """(interleaved samples of exactly `bars` bars with the ring-out folded onto the start, loop (0, end - 1))."""
    frames = len(samples) // channels
    end = beat_sample(bars * beats_per_bar, bpm, rate)
    if frames < end:
        raise ToolError(f"the file is {frames / rate:.2f} s, shorter than {bars} bars at {bpm} BPM "
                        f"({end / rate:.2f} s): render longer or ask for fewer bars")
    tail = frames - end if tail_s is None else min(frames - end, int(tail_s * rate))
    tail = min(tail, end)                                  # never wrap more than the loop itself
    out = list(samples[:end * channels])
    for i in range(tail * channels):
        out[i] += samples[end * channels + i]
    return out, (0, end - 1)


# ---- Validate ----------------------------------------------------------------------------------------------------
def validate(data, root=None):
    """List of problems (empty = valid). Never raises: a value of the wrong type is one of the problems."""
    if not isinstance(data, dict):
        return [f"the file must hold one JSON object: {{\"version\": {VERSION}, \"tracks\": {{...}}, ...}}"]
    try:
        return _validate(data, root)
    except (TypeError, AttributeError, KeyError) as exc:   # a value of a type no check foresaw: named, not a crash
        return [f"a value has the wrong type ({type(exc).__name__}: {exc}); compare the file with the format in "
                f"docs/resources/audio.md"]


def _validate(data, root):
    p = []
    if data.get("version") != VERSION:
        return [f"version must be {VERSION}"]
    rate = data.get("sample_rate")
    if not isinstance(rate, int) or isinstance(rate, bool) or not 8000 <= rate <= 192000:
        p.append("sample_rate must be a whole number of Hz (44100 or 48000), the rate of every music file")
        rate = None
    tracks, stingers = data.get("tracks") or {}, data.get("stingers") or {}
    for key, value in (("tracks", tracks), ("stingers", stingers)):
        if not isinstance(value, dict):
            p.append(f"{key} must be an object of name -> {{...}}")
    tracks = tracks if isinstance(tracks, dict) else {}
    stingers = stingers if isinstance(stingers, dict) else {}
    if not tracks:
        p.append("tracks: at least one track")
    for name, t in tracks.items():
        where = f"track {name}"
        if not isinstance(t, dict):
            p.append(f"{where}: must be an object (bpm, bars, stems, ...)")
            continue
        bpm, bpb, bars = t.get("bpm"), t.get("beats_per_bar", 4), t.get("bars")
        if not isinstance(bpm, (int, float)) or isinstance(bpm, bool) or not BPM_RANGE[0] <= bpm <= BPM_RANGE[1]:
            p.append(f"{where}: bpm must be {BPM_RANGE[0]}..{BPM_RANGE[1]}")
            continue
        if not isinstance(bpb, int) or not BEATS_PER_BAR_RANGE[0] <= bpb <= BEATS_PER_BAR_RANGE[1]:
            p.append(f"{where}: beats_per_bar must be {BEATS_PER_BAR_RANGE[0]}..{BEATS_PER_BAR_RANGE[1]}")
            continue
        if not isinstance(bars, int) or bars < 1:
            p.append(f"{where}: bars must be a whole number, 1 or more")
            continue
        if not 0 <= t.get("loop_start_bar", 0) < bars:
            p.append(f"{where}: loop_start_bar must be 0..bars-1 (bars before it are an intro that plays once)")
            continue
        stems = t.get("stems")
        if not isinstance(stems, dict) or not stems:
            p.append(f"{where}: stems must name at least one file (one stem for a plain track)")
            continue
        if root and rate:
            p += check_stems(where, t, stems, root, rate)
    for name, s in stingers.items():
        where = f"stinger {name}"
        if not isinstance(s, dict):
            p.append(f"{where}: must be an object (file, bars)")
            continue
        if not isinstance(s.get("bars"), (int, float)) or not 0 < s["bars"] <= MAX_STINGER_BARS:
            p.append(f"{where}: bars must be above 0 and at most {MAX_STINGER_BARS} (the next track enters after it)")
        if not isinstance(s.get("file"), str):
            p.append(f"{where}: file is required")
        elif root and not (Path(root) / s["file"]).is_file():
            p.append(f"{where}: {s['file']} not found under the root")
    transitions = data.get("transitions") or []
    if not isinstance(transitions, list):
        p.append("transitions must be a list of rules")
        transitions = []
    for k, r in enumerate(transitions):
        if not isinstance(r, dict):
            p.append(f"transition {k}: must be an object (from, to, quantize, ...)")
            continue
        where = f"transition {k} ({r.get('from')} -> {r.get('to')})"
        for end in ("from", "to"):
            if r.get(end) != "*" and r.get(end) not in tracks:
                p.append(f"{where}: {end} must be a track name or *")
        p += rule_problems(where, r, stingers)
    # every rule inherits default_transition (rule_for), so it gets the same checks, minus from and to
    if "default_transition" in data:
        d = data["default_transition"]
        if not isinstance(d, dict):
            p.append("default_transition must be an object (quantize, fade_ms, ...), the rule every transition inherits")
        else:
            p += rule_problems("default_transition", d, stingers)
    if data.get("start") is not None and data["start"] not in tracks:
        p.append(f"start {data['start']!r} is not a track")
    return p


def rule_problems(where, r, stingers):
    """Problems in one transition rule's own values (a transitions entry or default_transition)."""
    p = []
    if r.get("quantize", "bar") not in QUANTIZE:
        p.append(f"{where}: quantize must be one of {', '.join(QUANTIZE)}")
    if not 0 <= r.get("fade_ms", 0) <= 10000:
        p.append(f"{where}: fade_ms must be 0..10000")
    if not isinstance(r.get("sync", False), bool):              # the engines read it as a JSON boolean
        p.append(f"{where}: sync must be true or false")
    bars = r.get("phrase_bars", 4)
    if not isinstance(bars, int) or isinstance(bars, bool) or bars < 1:
        p.append(f"{where}: phrase_bars must be a whole number, 1 or more")
    if r.get("stinger") is not None and r["stinger"] not in stingers:
        p.append(f"{where}: stinger {r['stinger']!r} is not in stingers")
    if r.get("stinger") and r.get("sync"):
        p.append(f"{where}: a stinger and sync do not combine (the stinger decides where the next track enters)")
    return p


def check_stems(where, t, stems, root, rate):
    p, shape = [], None
    start, end = loop_points(t, rate)
    for stem, f in stems.items():
        path = Path(root) / f
        if not path.is_file():
            p.append(f"{where} stem {stem}: {f} not found under the root")
            continue
        try:
            if audioio.sniff(path.read_bytes()[:64]) == "wav":
                samples, r, loop, ch = read_wav_channels(path)
                frames = len(samples) // ch
            else:                       # OGG / FLAC stems: no 'smpl' chunk; the engine's import sets the loop
                chans, r = audioio.read_audio(path)
                loop, ch, frames = (start, end - 1), len(chans), len(chans[0])
        except (ValueError, audioio.AudioIOError) as exc:
            p.append(f"{where} stem {stem}: {exc}")
            continue
        if r != rate:
            p.append(f"{where} stem {stem}: {r} Hz, the music runs at {rate} Hz (resample it)")
        if frames < end:
            p.append(f"{where} stem {stem}: {frames} samples, the loop needs {end} ({t['bars']} bars at {t['bpm']} BPM)")
        if loop is None:
            p.append(f"{where} stem {stem}: no loop point (make it with music.py loop)")
        elif loop != (start, end - 1):
            p.append(f"{where} stem {stem}: loop {loop[0]}..{loop[1]} is off the bar grid (expected {start}..{end - 1})")
        if shape is None:
            shape = (r, ch, frames, stem)
        elif (r, ch, frames) != shape[:3]:
            p.append(f"{where} stem {stem}: {r} Hz, {ch} channel(s), {frames} samples differs from stem {shape[3]} "
                     f"({shape[0]} Hz, {shape[1]}, {shape[2]}): stems must match to stay in sync")
    return p


# ---- Tempo estimate ----------------------------------------------------------------------------------------------
def tempo(samples, rate, channels, lo=TEMPO_RANGE[0], hi=TEMPO_RANGE[1]):
    """(BPM, confidence 0..1) from the autocorrelation of a 10 ms onset envelope (rises in energy only)."""
    hop = int(rate * 0.01)
    mono = [sum(samples[i * channels:(i + 1) * channels]) / channels for i in range(len(samples) // channels)]
    energy = [sum(x * x for x in mono[i:i + hop]) for i in range(0, len(mono) - hop + 1, hop)]
    env = [max(0.0, math.log10(energy[i] + 1e-9) - math.log10(energy[i - 1] + 1e-9)) for i in range(1, len(energy))]
    if len(env) < 400:
        raise ToolError("need at least 4 s of audio to estimate a tempo")
    mean = sum(env) / len(env)
    env = [e - mean for e in env]
    zero = sum(e * e for e in env) or 1.0
    best, best_r = None, -1.0
    for lag in range(int(6000 / hi), int(6000 / lo) + 1):     # lags in 10 ms hops
        r = sum(env[i] * env[i + lag] for i in range(len(env) - lag)) / zero
        if r > best_r:
            best, best_r = lag, r
    # refine to a fraction of a hop with a parabola through the peak and its neighbours
    def ac(lag):
        return sum(env[i] * env[i + lag] for i in range(len(env) - lag)) / zero
    y0, y1, y2 = ac(best - 1), best_r, ac(best + 1)
    shift = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2) if (y0 - 2 * y1 + y2) != 0 else 0.0
    return 6000 / (best + max(-0.5, min(0.5, shift))), max(0.0, min(1.0, best_r))


# ---- Golden vectors ----------------------------------------------------------------------------------------------
def vector_cases():
    """Scripted plans the engines must reproduce exactly (integers: no tolerance)."""
    base = {"version": 1, "sample_rate": 44100,
            "tracks": {"explore": {"bpm": 96, "beats_per_bar": 4, "bars": 8, "loop_start_bar": 1, "stems": {"a": "x"}},
                       "combat": {"bpm": 96, "beats_per_bar": 4, "bars": 4, "stems": {"a": "x"}},
                       "waltz": {"bpm": 137.5, "beats_per_bar": 3, "bars": 6, "stems": {"a": "x"}}},
            "stingers": {"alarm": {"file": "s.wav", "bars": 1}},
            "transitions": [{"from": "explore", "to": "combat", "quantize": "beat", "fade_ms": 120, "sync": True},
                            {"from": "combat", "to": "explore", "quantize": "bar", "fade_ms": 500},
                            {"from": "*", "to": "waltz", "quantize": "phrase", "phrase_bars": 2, "stinger": "alarm"},
                            {"from": "waltz", "to": "*", "quantize": "loop_end"}],
            "default_transition": {"quantize": "bar", "fade_ms": 250}}
    asks = [("explore", 0, 0, "combat", 0), ("explore", 0, 0, "combat", 1), ("explore", 0, 0, "combat", 27562),
            ("explore", 0, 0, "combat", 27563), ("explore", 1000, 0, "combat", 900000),
            ("explore", 0, 0, "combat", 999999), ("combat", 5000, 0, "explore", 50000),
            ("combat", 0, 12345, "explore", 0), ("explore", 0, 0, "waltz", 70000), ("combat", 0, 0, "waltz", 444444),
            ("waltz", 0, 0, "explore", 10), ("waltz", 300, 0, "combat", 600000)]
    grid = [{"bpm": bpm, "rate": rate, "k": k, "sample": beat_sample(k, bpm, rate)}
            for bpm, rate in ((96, 44100), (137.5, 44100), (120, 48000), (91.7, 48000)) for k in (0, 1, 3, 7, 64, 1001)]
    plans = [{"from": f, "since": s, "entry": e, "to": t, "now": n, "expect": plan(base, f, s, e, t, n)}
             for f, s, e, t, n in asks]
    return [{"type": "music_grid", "name": "beat samples", "steps": grid},
            {"type": "music_plan", "name": "transition plans", "params": base, "steps": plans}]


def render_vectors():
    return json.dumps({"version": 1, "tolerance": 0, "about": "tools/audio/wavesmith/music.py vectors --write",
                       "cases": vector_cases()}, indent=1) + "\n"


# ---- Commands ----------------------------------------------------------------------------------------------------
def load_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"cannot read {what} {path}: {exc}")


def check_grid_args(args):
    """The ranges validate applies to music.json, for --bpm, --bars and --beats-per-bar (ToolError, exit 2)."""
    if not BPM_RANGE[0] <= args.bpm <= BPM_RANGE[1]:
        raise ToolError(f"bpm must be {BPM_RANGE[0]}..{BPM_RANGE[1]} (got {args.bpm:g})")
    if args.bars < 1:
        raise ToolError(f"bars must be 1 or more (got {args.bars})")
    if not BEATS_PER_BAR_RANGE[0] <= args.beats_per_bar <= BEATS_PER_BAR_RANGE[1]:
        raise ToolError(f"beats-per-bar must be {BEATS_PER_BAR_RANGE[0]}..{BEATS_PER_BAR_RANGE[1]} "
                        f"(got {args.beats_per_bar})")
    if getattr(args, "rate", 1) < 1:
        raise ToolError(f"rate must be 1 Hz or more (got {args.rate})")


def cmd_grid(args):
    check_grid_args(args)
    track = {"bpm": args.bpm, "beats_per_bar": args.beats_per_bar}
    for b in range(args.bars + 1):
        s = bar_sample(b, track, args.rate)
        print(f"bar {b + 1 if b < args.bars else 'end':>3}: {s / args.rate:9.4f} s  sample {s}")
    return 0


def cmd_loop(args):
    out = Path(args.out)
    if out.exists() and not args.overwrite:
        raise ToolError(f"{out} exists (use --overwrite)")
    check_grid_args(args)
    samples, rate, channels = read_interleaved(args.file)
    body, loop = make_loop(samples, rate, channels, args.bpm, args.bars, args.beats_per_bar, args.tail)
    peak = max((abs(x) for x in body), default=0.0)
    if peak > 1.0:                                          # the folded tail can add up: keep it unclipped
        body = [x / peak * 0.98 for x in body]
    out.parent.mkdir(parents=True, exist_ok=True)
    try:                                    # .wav natively (smpl loop), .ogg via ffmpeg (LOOPSTART / LOOPLENGTH)
        audioio.write_audio(out, [body[c::channels] for c in range(channels)], rate, loop=loop)
    except audioio.AudioIOError as exc:
        raise ToolError(str(exc))
    print(f"[ OK ] {out.as_posix()}: {args.bars} bars at {args.bpm} BPM = {(loop[1] + 1) / rate:.3f} s, loop 0..{loop[1]}"
          + (f", scaled by {0.98 / peak:.3f} to stay unclipped" if peak > 1.0 else ""))
    return 0


def cmd_validate(args):
    data = load_json(args.music, "music")
    problems = validate(data, args.root)
    for x in problems:
        print(f"[FAIL] {x}")
    if not isinstance(data, dict):                  # validate named it; there is nothing to count
        print(f"[FAIL] {len(problems)} problem(s)")
        return 1

    def count(key, empty):          # a value of the wrong type was a problem above: counted as none here
        value = data.get(key) or empty
        return len(value) if isinstance(value, type(empty)) else 0
    print(f"[{'FAIL' if problems else ' OK '}] {count('tracks', {})} track(s), {count('stingers', {})} stinger(s), "
          f"{count('transitions', [])} transition(s), {len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_plan(args):
    data = load_json(args.music, "music")
    problems = validate(data)
    if problems:
        raise ToolError("the music file has problems (run validate): " + problems[0])
    for name in (args.frm, args.to):
        if name not in data["tracks"]:
            raise ToolError(f"no track {name!r}")
    rate = data["sample_rate"]
    r = plan(data, args.frm, 0, 0, args.to, math.floor(args.at * rate + 0.5))
    print(json.dumps(dict(r, seconds={k: round(v / rate, 4) for k, v in r.items() if isinstance(v, int)}), indent=1))
    return 0


def read_interleaved(path):
    """(interleaved samples, rate, channels) from any format audioio.py reads."""
    try:
        chans, rate = audioio.read_audio(path)
    except audioio.AudioIOError as exc:
        raise ToolError(str(exc))
    if len(chans) == 1:
        return list(chans[0]), rate, 1
    return [s for frame in zip(*chans) for s in frame], rate, len(chans)


def cmd_tempo(args):
    samples, rate, channels = read_interleaved(args.file)
    bpm, conf = tempo(samples, rate, channels)
    print(f"[ OK ] {Path(args.file).as_posix()}: about {bpm:.1f} BPM (confidence {conf:.2f}; half or double is possible)")
    return 0


def cmd_vectors(args):
    text = render_vectors()
    if args.write:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes(text.encode("utf-8"))
        print(f"[ OK ] wrote {GOLDEN}")
        return 0
    current = GOLDEN.read_bytes().decode("utf-8") if GOLDEN.exists() else None
    if current != text:
        print(f"[FAIL] {GOLDEN} is stale or missing: run music.py vectors --write")
        return 1
    print(f"[ OK ] {GOLDEN} is current")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description="Adaptive music on a bar grid: loops, validation, transition plans, "
                                             "tempo estimates and the golden vectors the engines follow.",
                                 epilog="Exit codes: 0 ok, 1 problems or stale vectors, 2 usage or unreadable files.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="tracebacks")
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("grid", parents=[common], help="bar start times and samples")
    g.add_argument("--bpm", type=float, required=True)
    g.add_argument("--bars", type=int, required=True)
    g.add_argument("--beats-per-bar", type=int, default=4)
    g.add_argument("--rate", type=int, default=44100)
    lo = sub.add_parser("loop", parents=[common], help="cut a WAV to N bars with its tail folded onto the start")
    lo.add_argument("file")
    lo.add_argument("--bpm", type=float, required=True)
    lo.add_argument("--bars", type=int, required=True)
    lo.add_argument("--beats-per-bar", type=int, default=4)
    lo.add_argument("--tail", type=float, help="seconds of ring-out to fold back (default: everything past the loop)")
    lo.add_argument("--out", required=True)
    lo.add_argument("--overwrite", action="store_true")
    v = sub.add_parser("validate", parents=[common], help="tracks, stems, loop points, stingers, transitions")
    v.add_argument("music", help="data/music.json")
    v.add_argument("--root", help="folder the stem and stinger paths are relative to (checks the files)")
    pl = sub.add_parser("plan", parents=[common], help="when a transition would happen, asked at a time")
    pl.add_argument("music")
    pl.add_argument("--from", dest="frm", required=True)
    pl.add_argument("--to", required=True)
    pl.add_argument("--at", type=float, required=True, help="seconds since the from-track started")
    t = sub.add_parser("tempo", parents=[common], help="estimate a WAV's tempo")
    t.add_argument("file")
    vc = sub.add_parser("vectors", parents=[common], help="data/golden/music.json: --check (default) or --write")
    vc.add_argument("--write", action="store_true")
    vc.add_argument("--check", action="store_true")
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
        return {"grid": cmd_grid, "loop": cmd_loop, "validate": cmd_validate, "plan": cmd_plan, "tempo": cmd_tempo,
                "vectors": cmd_vectors}[args.cmd](args)
    except ToolError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

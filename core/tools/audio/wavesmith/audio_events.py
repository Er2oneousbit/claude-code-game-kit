#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# audio_events.py
# Purpose : Game sound events as data (audio_events.json: variants, pitch and volume randomization, no-repeat picks,
#           voice limits, cooldowns, buses, ducking) and the reference audio director every engine port reproduces:
#           it validates and audits a game's events file and writes the golden vectors data/golden/audio.json.
# Usage   : python tools/audio/wavesmith/wavesmith.py events validate data/audio_events.json        # schema, files exist
#           python tools/audio/wavesmith/wavesmith.py events audit data/audio_events.json           # will it sound repetitive?
#           python tools/audio/wavesmith/wavesmith.py events vectors --check                        # golden file current? (exit 1)
#           python tools/audio/wavesmith/wavesmith.py events vectors --write                        # after changing the director
# Needs   : Python 3.8+ only (audit measures loudness with loudness.py, same folder)
# Exit    : 0 ok, 1 validation errors, audit warnings with --strict, or stale vectors, 2 usage or an unreadable file
# Notes   : The director is the spec: ports (TypeScript, GDScript, C#, Lua, ...) load data/golden/audio.json in their
#           tests and must reproduce every step within its tolerance (docs/sop/SOP-18 explains golden vectors).
#           Like tools/golden_vectors.py, every formula gives the same result in every language: the random source
#           is Park-Miller (products stay below 2^53, no bit operations), event ids are ASCII, and randomness is
#           drawn in a fixed order (variant, pitch, volume) and never by a rejected play (cooldown, voice cap).
#           Ducking is a straight line in dB: towards `depth_db` over `attack_ms` while any voice plays on the
#           trigger bus, back to 0 over `release_ms` when none does. Calls must come in time order.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   play(event, t): expire finished voices -> cooldown? reject -> voice cap? steal the oldest or reject
#                   -> variant (sequence | random | random_no_repeat | shuffle) -> pitch -> volume -> start a voice
#   duck(t):        advance each ducking envelope from its last time to t across the trigger bus's voice edges
#   validate: buses form a tree, ducking names real buses, every event is well formed, files exist (with --root)
#   audit: few variants without randomization, loud spread between variants, missing captions -> warnings
#   vectors: run the scripted cases through the director -> data/golden/audio.json (--write / --check)
import argparse
import json
import math
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = Path(__file__).resolve().parent
GOLDEN = HERE.parents[2] / "data" / "golden" / "audio.json"
TOLERANCE = 1e-6
VECTOR_VERSION = 1
PM_M = 2147483647                       # Park-Miller modulus (2^31 - 1)
PM_A = 16807
PICKS = ("sequence", "random", "random_no_repeat", "shuffle")
STEALS = ("oldest", "none")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
AUDIO_EXT = (".wav", ".flac", ".ogg", ".mp3")


# ----------------------------------------------------------------------------------------------- director
class Rng:
    """Park-Miller minimal standard generator: exact in 64-bit floats, so every language agrees."""

    def __init__(self, seed):
        self.s = seed % PM_M or 1

    def next(self):
        """A float in [0, 1)."""
        self.s = (self.s * PM_A) % PM_M
        return (self.s - 1) / (PM_M - 1)


def event_seed(event_id, global_seed):
    h = 0
    for ch in event_id:                  # ASCII only (validated), so byte, code unit and code point agree
        h = (h * 31 + ord(ch)) % PM_M
    return (h + (global_seed % PM_M) * 7919) % PM_M or 1


class Director:
    """The reference audio director: decisions only (which file, pitch, gain, which voice to stop, duck gains)."""

    def __init__(self, params):
        self.events = params["events"]
        self.ducking = params.get("ducking", [])
        self.seed = params.get("seed", 1)
        self.rng = {name: Rng(event_seed(name, self.seed)) for name in sorted(self.events)}
        self.voices = []                 # dicts: id, event, bus, start, end (end shortened when stolen)
        self.history = []                # trigger-bus voices the ducking envelopes may still need
        self.triggers = {rule["trigger"] for rule in self.ducking}
        self.next_id = 1
        self.last_play = {}
        self.last_variant = {}
        self.bags = {}
        self.duck_state = [{"gain": 0.0, "t": 0.0} for _ in self.ducking]
        self.now = 0.0

    def _clock(self, t):
        if t < self.now:
            raise ValueError(f"calls must come in time order ({t} ms after {self.now} ms)")
        self.now = t

    def _pick(self, name, ev, rng):
        n = len(ev["files"])
        last = self.last_variant.get(name, -1)
        pick = ev.get("pick", "random_no_repeat")
        if n == 1:
            return 0
        if pick == "sequence":
            return (last + 1) % n
        if pick == "random":
            return min(int(rng.next() * n), n - 1)
        if pick == "random_no_repeat":
            if last < 0:
                return min(int(rng.next() * n), n - 1)
            k = min(int(rng.next() * (n - 1)), n - 2)
            return k + 1 if k >= last else k
        bag = self.bags.get(name) or []
        if not bag:                      # shuffle: refill with Fisher-Yates, newest choice at the front
            bag = list(range(n))
            for i in range(n - 1, 0, -1):
                j = min(int(rng.next() * (i + 1)), i)
                bag[i], bag[j] = bag[j], bag[i]
            if bag[0] == last:           # never the same file twice across a refill
                bag[0], bag[1] = bag[1], bag[0]
        idx = bag.pop(0)
        self.bags[name] = bag
        return idx

    def play(self, name, t):
        self._clock(t)
        ev = self.events[name]
        self.voices = [v for v in self.voices if v["end"] > t]
        cooldown = ev.get("cooldown_ms", 0)
        if cooldown and name in self.last_play and t - self.last_play[name] < cooldown:
            return {"result": "cooldown"}
        mine = [v for v in self.voices if v["event"] == name]
        stolen = None
        if len(mine) >= ev.get("max_voices", 8):
            if ev.get("steal", "oldest") == "none":
                return {"result": "capped"}
            victim = min(mine, key=lambda v: (v["start"], v["id"]))
            victim["end"] = t                                    # it stops now (the ducking envelope sees that)
            self.voices.remove(victim)
            stolen = victim["id"]
        rng = self.rng[name]
        idx = self._pick(name, ev, rng)
        lo, hi = ev.get("pitch_semitones", [0.0, 0.0])
        semis = lo if lo == hi else lo + (hi - lo) * rng.next()
        vlo, vhi = ev.get("volume_db", [0.0, 0.0])
        gain = vlo if vlo == vhi else vlo + (vhi - vlo) * rng.next()
        ratio = 2.0 ** (semis / 12.0)
        voice = {"id": self.next_id, "event": name, "bus": ev["bus"], "start": t,
                 "end": t + ev["lengths_ms"][idx] / ratio}
        self.next_id += 1
        self.voices.append(voice)
        if voice["bus"] in self.triggers:
            self.history.append(voice)
        self.last_play[name] = t
        self.last_variant[name] = idx
        return {"result": "played", "variant": idx, "pitch_semitones": semis, "pitch_ratio": ratio, "gain_db": gain,
                "voice": voice["id"], "stolen": stolen, "ends_ms": voice["end"]}

    def duck(self, t):
        """{target bus: duck gain in dB} at time t, every rule advanced to t."""
        self._clock(t)
        out = {}
        for rule, st in zip(self.ducking, self.duck_state):
            edges = sorted({e for v in self.history if v["bus"] == rule["trigger"]
                            for e in (v["start"], v["end"]) if st["t"] < e < t})
            gain, at = st["gain"], st["t"]
            for edge in edges + [t]:
                active = any(v["start"] <= at < v["end"] for v in self.history if v["bus"] == rule["trigger"])
                gain = _ramp(gain, active, rule, edge - at)
                at = edge
            st["gain"], st["t"] = gain, t
            for bus in rule["targets"]:
                out[bus] = min(out.get(bus, 0.0), gain)
        # every rule now stands at t: a voice that ended at or before t adds no later edge and is never active
        # again, so it can go (keeps duck() cheap in a long session; results are unchanged)
        self.history = [v for v in self.history if v["end"] > t]
        return out


def _ramp(gain, active, rule, dt):
    depth = rule["depth_db"]
    if active:
        if rule.get("attack_ms", 0) <= 0:
            return depth
        return max(depth, gain + depth / rule["attack_ms"] * dt)
    if rule.get("release_ms", 0) <= 0:
        return 0.0
    return min(0.0, gain - depth / rule["release_ms"] * dt)


# ----------------------------------------------------------------------------------------------- validate / audit
class ToolError(Exception):
    """Exit 2: a file that cannot be read (a SystemExit with a message would exit 1, the code for problems found)."""


def load_events(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"cannot read {path}: {exc}")
    return data


def validate(data, root=None):
    """List of problems (empty = valid). Never raises: a value of the wrong type is one of the problems."""
    if not isinstance(data, dict):
        return ["the file must hold one JSON object: {\"version\": 1, \"buses\": {...}, \"events\": {...}}"]
    try:
        return _validate(data, root)
    except (TypeError, AttributeError, KeyError) as exc:   # a value of a type no check foresaw: named, not a crash
        return [f"a value has the wrong type ({type(exc).__name__}: {exc}); compare the file with the format in "
                f"docs/resources/audio.md"]


def _validate(data, root):
    p = []
    if data.get("version") != 1:
        p.append("version must be 1")
    seed = data.get("seed", 1)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        p.append("seed must be a whole number, 0 or more (ports compute with it exactly)")
    buses = data.get("buses", {})
    if not isinstance(buses, dict):
        p.append("buses must be an object: {\"master\": {}, \"sfx\": {\"parent\": \"master\"}}")
        buses = {}
    if "master" not in buses:
        p.append("buses: a 'master' bus is required")
    for name, b in buses.items():
        if not isinstance(b, dict):
            p.append(f"bus {name}: must be an object, e.g. {{\"parent\": \"master\"}}")
            continue
        parent = b.get("parent")
        if name != "master" and not (isinstance(parent, str) and parent in buses):
            p.append(f"bus {name}: parent {parent!r} is not a bus")
        seen, cur = set(), name
        while isinstance(cur, str) and cur in buses and cur != "master":
            if cur in seen:
                p.append(f"bus {name}: parent loop")
                break
            seen.add(cur)
            up = buses[cur]
            cur = up.get("parent") if isinstance(up, dict) else None
        if not isinstance(b.get("volume_db", 0), (int, float)) or b.get("volume_db", 0) > 12:
            p.append(f"bus {name}: volume_db must be a number at most +12")
    ducking = data.get("ducking", [])
    if not isinstance(ducking, list):
        p.append("ducking must be a list of rules")
        ducking = []
    for i, rule in enumerate(ducking):
        if not isinstance(rule, dict):
            p.append(f"ducking[{i}]: must be an object (trigger, targets, depth_db, attack_ms, release_ms)")
            continue
        if not (isinstance(rule.get("trigger"), str) and rule["trigger"] in buses):
            p.append(f"ducking[{i}]: trigger {rule.get('trigger')!r} is not a bus")
        targets = rule.get("targets", [])
        for t in targets if isinstance(targets, list) else [targets]:
            if not (isinstance(t, str) and t in buses):
                p.append(f"ducking[{i}]: target {t!r} is not a bus")
        if not rule.get("targets"):
            p.append(f"ducking[{i}]: no targets")
        if not -60 <= rule.get("depth_db", 1) <= 0:
            p.append(f"ducking[{i}]: depth_db must be -60..0")
        for k in ("attack_ms", "release_ms"):
            if not 0 <= rule.get(k, -1) <= 10000:
                p.append(f"ducking[{i}]: {k} must be 0..10000")
    events = data.get("events", {})
    if not isinstance(events, dict):
        p.append("events must be an object of event id -> {bus, files, ...}")
        events = {}
    if not events:
        p.append("events: none defined")
    for name, ev in events.items():
        where = f"event {name}"
        if not isinstance(ev, dict):
            p.append(f"{where}: must be an object, e.g. {{\"bus\": \"sfx\", \"files\": [\"hit.wav\"]}}")
            continue
        nulls = sorted(k for k, v in ev.items() if v is None)
        if nulls:
            p.append(f"{where}: {', '.join(nulls)} is null: leave the field out to get its default")
        if not ID_RE.match(name):
            p.append(f"{where}: id must be lowercase ASCII letters, digits, _ . - (it seeds the random source)")
        if not (isinstance(ev.get("bus"), str) and ev["bus"] in buses):
            p.append(f"{where}: bus {ev.get('bus')!r} is not a bus")
        files = ev.get("files")
        if not isinstance(files, list) or not files:
            p.append(f"{where}: files must be a non-empty list")
            files = []
        for f in files:
            if not isinstance(f, str) or not f.lower().endswith(AUDIO_EXT):
                p.append(f"{where}: {f!r} is not an audio file name ({', '.join(AUDIO_EXT)})")
            elif root and not (Path(root) / f).is_file():
                p.append(f"{where}: {f} not found under {root}")
        if ev.get("pick", "random_no_repeat") not in PICKS:
            p.append(f"{where}: pick must be one of {', '.join(PICKS)}")
        if ev.get("steal", "oldest") not in STEALS:
            p.append(f"{where}: steal must be one of {', '.join(STEALS)}")
        for key, lo_lim, hi_lim in (("pitch_semitones", -12, 12), ("volume_db", -60, 12)):
            rng_ = ev.get(key, [0, 0])
            if (not isinstance(rng_, list) or len(rng_) != 2 or not all(isinstance(x, (int, float)) for x in rng_)
                    or rng_[0] > rng_[1] or rng_[0] < lo_lim or rng_[1] > hi_lim):
                p.append(f"{where}: {key} must be [low, high] within {lo_lim}..{hi_lim}")
        if not isinstance(ev.get("max_voices", 8), int) or ev.get("max_voices", 8) < 1:
            p.append(f"{where}: max_voices must be a whole number, 1 or more")
        if not 0 <= ev.get("cooldown_ms", 0) <= 60000:
            p.append(f"{where}: cooldown_ms must be 0..60000")
        if "caption" in ev and not isinstance(ev["caption"], str):
            p.append(f"{where}: caption must be text, e.g. \"[door creaks]\"")
        if "directional" in ev and not isinstance(ev["directional"], bool):
            p.append(f"{where}: directional must be true or false (true: the caption gets an arrow off screen)")
    return p


def is_loop(path):
    """True when the file is a WAV with a loop point (smpl chunk): an ambience bed or music loop."""
    if not path.is_file() or path.suffix.lower() != ".wav":
        return False
    sys.path.insert(0, str(HERE))
    from wavfile import read_wav_channels
    try:
        return read_wav_channels(path)[2] is not None
    except ValueError:
        return False


def audit(data, root=None):
    """List of warnings: things that work but will sound cheap or shut players out."""
    w = []
    for name, ev in data.get("events", {}).items():
        n = len(ev.get("files", []))
        pitch = ev.get("pitch_semitones", [0, 0])
        vol = ev.get("volume_db", [0, 0])
        # UI sounds should sound the same every time (players learn them), so only game-world buses are checked
        repeats = ev.get("cooldown_ms", 0) < 500 and ev.get("bus") not in ("ui", "music")
        if repeats and root and n and all(is_loop(Path(root) / f) for f in ev["files"]):
            repeats = False         # a bed with a loop point plays on and on: there is no "next play" to vary
        if n < 3 and pitch[0] == pitch[1] and repeats:
            w.append(f"{name}: {n} file(s) and no pitch range: repeated plays will sound identical "
                     "(rotate 3 to 5 variants or add pitch_semitones like [-1, 1])")
        if n >= 2 and ev.get("pick") == "random":
            w.append(f"{name}: pick random can repeat a file back to back; random_no_repeat or shuffle avoid it")
        if pitch[1] - pitch[0] > 4:
            w.append(f"{name}: a pitch range over 4 semitones changes the sound's character, not just its take")
        if vol[1] - vol[0] > 6:
            w.append(f"{name}: a volume range over 6 dB makes some plays drop out of the mix")
        if ev.get("bus") not in ("ui", "music") and "caption" not in ev:
            w.append(f"{name}: no caption: deaf and hard-of-hearing players miss it (add e.g. \"[{name.replace('_', ' ')}]\")")
        if root and n >= 2:
            sys.path.insert(0, str(HERE))
            import loudness
            levels = []
            for f in ev["files"]:
                path = Path(root) / f
                if path.is_file():
                    m = loudness.measure_file(path, want_tp=False)
                    if m["integrated_lufs"] is not None:
                        levels.append(m["integrated_lufs"])
            if len(levels) >= 2 and max(levels) - min(levels) > 3:
                w.append(f"{name}: its files differ by {max(levels) - min(levels):.1f} LU: some takes will jump out "
                         "(loudness.py normalize them to one level)")
    return w


# ----------------------------------------------------------------------------------------------- golden vectors
def _case(name, params, script):
    d = Director(params)
    steps = []
    for call in script:
        step = dict(call)
        step["expect"] = d.play(call["event"], call["t_ms"]) if call["call"] == "play" else d.duck(call["t_ms"])
        steps.append(step)
    return {"type": "audio_director", "name": name, "params": params, "steps": steps}


def build_vectors():
    foot = {"bus": "sfx", "files": [f"step_{i}.wav" for i in range(4)], "lengths_ms": [180, 200, 170, 190],
            "pick": "random_no_repeat", "pitch_semitones": [-1.0, 1.0], "volume_db": [-3.0, 0.0],
            "max_voices": 4, "steal": "oldest", "cooldown_ms": 60}
    cases = [
        _case("footsteps: no repeats, pitch and volume ranges, cooldown",
              {"seed": 1, "events": {"step_stone": foot}},
              [{"call": "play", "event": "step_stone", "t_ms": t} for t in
               (0, 250, 500, 520, 750, 1000, 1250, 1500, 1750, 2000, 2250, 2300, 2500)]),
        _case("voice cap: steal the oldest",
              {"seed": 7, "events": {"impact": {"bus": "sfx", "files": ["hit_a.wav", "hit_b.wav", "hit_c.wav"],
                                                "lengths_ms": [600, 600, 600], "pick": "random", "max_voices": 2,
                                                "steal": "oldest"}}},
              [{"call": "play", "event": "impact", "t_ms": t} for t in (0, 100, 200, 300, 900, 1000)]),
        _case("voice cap: refuse when full",
              {"seed": 7, "events": {"coin": {"bus": "sfx", "files": ["coin.wav"], "lengths_ms": [400],
                                              "max_voices": 2, "steal": "none", "pitch_semitones": [0.0, 2.0]}}},
              [{"call": "play", "event": "coin", "t_ms": t} for t in (0, 50, 100, 150, 450, 500)]),
        _case("shuffle bag: every file once per round, no repeat across rounds",
              {"seed": 3, "events": {"swing": {"bus": "sfx", "files": ["s1.wav", "s2.wav", "s3.wav"],
                                               "lengths_ms": [100, 100, 100], "pick": "shuffle"}}},
              [{"call": "play", "event": "swing", "t_ms": t * 200} for t in range(10)]),
        _case("sequence: round robin",
              {"seed": 3, "events": {"chime": {"bus": "ui", "files": ["c1.wav", "c2.wav", "c3.wav"],
                                               "lengths_ms": [300, 300, 300], "pick": "sequence"}}},
              [{"call": "play", "event": "chime", "t_ms": t * 400} for t in range(5)]),
        _case("a seed above 2^32 stays exact in every port",
              {"seed": 1099511627783, "events": {"step_stone": foot}},
              [{"call": "play", "event": "step_stone", "t_ms": t} for t in (0, 250, 500, 750)]),
        _case("ducking: dialogue under music, attack and release",
              {"seed": 5,
               "ducking": [{"trigger": "dialogue", "targets": ["music", "ambience"], "depth_db": -8.0,
                            "attack_ms": 80.0, "release_ms": 400.0}],
               "events": {"line": {"bus": "dialogue", "files": ["line.wav"], "lengths_ms": [2000]}}},
              [{"call": "duck", "t_ms": 900}, {"call": "play", "event": "line", "t_ms": 1000},
               {"call": "duck", "t_ms": 1000}, {"call": "duck", "t_ms": 1040}, {"call": "duck", "t_ms": 1080},
               {"call": "duck", "t_ms": 2000}, {"call": "duck", "t_ms": 3000}, {"call": "duck", "t_ms": 3100},
               {"call": "duck", "t_ms": 3200}, {"call": "duck", "t_ms": 3400}, {"call": "duck", "t_ms": 3600}]),
        _case("ducking: a new line during the release dips again from where it was",
              {"seed": 5,
               "ducking": [{"trigger": "dialogue", "targets": ["music"], "depth_db": -10.0,
                            "attack_ms": 100.0, "release_ms": 500.0}],
               "events": {"line": {"bus": "dialogue", "files": ["a.wav", "b.wav"], "lengths_ms": [300, 300],
                                   "pick": "sequence", "max_voices": 1, "steal": "oldest"}}},
              [{"call": "play", "event": "line", "t_ms": 0}, {"call": "duck", "t_ms": 50},
               {"call": "duck", "t_ms": 300}, {"call": "duck", "t_ms": 400}, {"call": "play", "event": "line", "t_ms": 450},
               {"call": "duck", "t_ms": 460}, {"call": "play", "event": "line", "t_ms": 600},
               {"call": "duck", "t_ms": 700}, {"call": "duck", "t_ms": 1000}, {"call": "duck", "t_ms": 1400}]),
        # a long line stolen by a short one: the long voice's end moves to the steal, so the duck releases when the
        # short one ends (700 ms), not when the long one would have (3000 ms); found missing by the Bevy port's review
        _case("ducking: a stolen long line stops ducking when the short line that replaced it ends",
              {"seed": 5,
               "ducking": [{"trigger": "dialogue", "targets": ["music"], "depth_db": -12.0,
                            "attack_ms": 100.0, "release_ms": 600.0}],
               "events": {"line": {"bus": "dialogue", "files": ["long.wav", "short.wav"], "lengths_ms": [3000, 200],
                                   "pick": "sequence", "max_voices": 1, "steal": "oldest"}}},
              [{"call": "play", "event": "line", "t_ms": 0}, {"call": "duck", "t_ms": 400},
               {"call": "play", "event": "line", "t_ms": 500}, {"call": "duck", "t_ms": 1000},
               {"call": "duck", "t_ms": 1500}, {"call": "duck", "t_ms": 3500}]),
    ]
    return {"version": VECTOR_VERSION, "tolerance": TOLERANCE, "spec": "tools/audio/wavesmith/audio_events.py", "cases": cases}


def render(obj):
    return json.dumps(obj, indent=1, sort_keys=True) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sound events as data: validate, audit, and the golden vectors of the "
                                             "reference audio director.",
                                 epilog="Exit codes: 0 ok, 1 problems found or stale vectors, 2 usage or an unreadable file.")
    sub = ap.add_subparsers(dest="cmd")
    v = sub.add_parser("validate", help="schema checks (and files exist, with --root)")
    v.add_argument("file")
    v.add_argument("--root", help="folder the event file paths are relative to (checks they exist)")
    a = sub.add_parser("audit", help="warnings: repetition, loudness spread between takes, missing captions")
    a.add_argument("file")
    a.add_argument("--root", help="folder of the audio files (enables the loudness spread check)")
    a.add_argument("--strict", action="store_true", help="exit 1 when there are warnings")
    g = sub.add_parser("vectors", help="write or check data/golden/audio.json")
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--out", help="write here instead of data/golden/audio.json")
    args = ap.parse_args(argv)
    if args.cmd in ("validate", "audit"):
        try:
            data = load_events(args.file)
        except ToolError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 2
        problems = validate(data, getattr(args, "root", None))
        if problems:
            for x in problems:
                print(f"[FAIL] {x}")
            return 1
        if args.cmd == "validate":
            print(f"[ OK ] {args.file}: {len(data['events'])} events, {len(data['buses'])} buses, "
                  f"{len(data.get('ducking', []))} ducking rules")
            return 0
        warnings = audit(data, args.root)
        for x in warnings:
            print(f"[warn] {x}")
        print(f"[ OK ] {len(warnings)} warning(s)")
        return 1 if warnings and args.strict else 0
    if args.cmd == "vectors" and (args.write or args.check):
        text = render(build_vectors())
        target = Path(args.out) if args.out else GOLDEN
        if args.write:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
            print(f"[ OK ] wrote {target}")
            return 0
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != text:
            print(f"[FAIL] {target} is stale: run vectors --write")
            return 1
        print(f"[ OK ] {target} is current")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

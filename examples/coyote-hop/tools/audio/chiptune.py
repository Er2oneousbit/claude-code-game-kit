#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# chiptune.py
# Purpose : Render music written as a small JSON song file (notes in text patterns, like a tracker)
#           into a WAV with retro channels: pulse waves, a triangle bass and noise drums. Loops get a
#           'smpl' loop chunk, so Godot and Unity loop the track seamlessly with default settings.
# Usage   : python tools/audio/chiptune.py assets/audio/src/theme.song.json --out assets/audio/music/theme.wav
#           python tools/audio/chiptune.py song.json --out solo.wav --solo lead     # one channel, to check it
#           python tools/audio/chiptune.py song.json --check                        # validate, print the layout
# Needs   : Python 3.8+ only
# Exit    : 0 ok, 1 render problem (silent, or a click at a loop seam where nothing starts), 2 usage or song
#           error (with pattern and step)
# Notes   : Song file:
#             {"bpm": 150, "steps_per_beat": 4, "loop": true, "rate": 22050,
#              "channels": {"lead": {"wave": "square", "duty": 0.5, "volume": 0.3,
#                                    "attack": 0.005, "decay": 0.1, "sustain": 0.6, "release": 0.05,
#                                    "vibrato": [0.15, 6.0, 0.12]},
#                           "bass": {"wave": "triangle", "volume": 0.5}, "drums": {"wave": "drums"}},
#              "patterns": {"A": {"lead": "C5 - E5 . G5 - - .", "bass": "C3 . . . G2 . . .",
#                                 "drums": "k . h . s . h ."}},
#              "order": ["A", "A"]}
#           Steps are space separated ("|" is ignored, use it for bars): a note (C4, F#5, Bb3), "-" holds
#           the note before it, "." is silence. Drum steps: k kick, s snare, h hat, o open hat, c crash.
#           Every channel in a pattern needs the same number of steps; a channel left out is silent.
#           Waves: square (duty), saw, triangle (4-bit stepped, like the NES), sine, noise, drums.
#           vibrato = [depth in semitones, rate Hz, delay s]. The mix is normalized to -1 dBFS.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   load + validate the song -> per channel, walk the order's steps into note events (start, length, pitch)
#   -> render each event (oscillator x ADSR, release after the note) into the channel buffer
#   -> mix channels x volume -> loop: fold the tail past the end back onto the start (seamless wrap)
#   -> normalize -> WAV (+ smpl loop chunk) -> print stats (length, peak, loudness, loop seam)
import argparse
import json
import math
import random
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wavfile import stats, write_wav  # noqa: E402

DEFAULT_RATE = 22050      # plenty for chiptune and half the size of 44.1 kHz
PEAK = 0.89               # normalize to about -1 dBFS
NOTE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d)$")
SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
WAVES = ("square", "saw", "triangle", "sine", "noise", "drums")
DRUMS = ("k", "s", "h", "o", "c")
CHANNEL_DEFAULTS = {"wave": "square", "duty": 0.5, "volume": 0.3, "attack": 0.004, "decay": 0.08,
                    "sustain": 0.7, "release": 0.04, "vibrato": None, "octave": 0}
CHANNEL_RANGES = {"duty": (0.01, 0.99), "volume": (0, 1), "attack": (0, 10), "decay": (0, 10), "sustain": (0, 1),
                  "release": (0, 10), "octave": (-4, 4)}
SONG_RANGES = (("bpm", 20, 400), ("steps_per_beat", 1, 16), ("rate", 8000, 96000), ("seed", 0, 2 ** 31))
DRUM_TAIL_S = 1.0         # the longest drum (crash) rings this long
DEBUG = False


class SongError(Exception):
    """A mistake in the song file, with where it is."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def note_freq(token, octave_shift=0):
    m = NOTE.match(token)
    if not m:
        return None
    letter, acc, octave = m.group(1).upper(), m.group(2), int(m.group(3)) + octave_shift
    midi = 12 * (octave + 1) + SEMITONE[letter] + (1 if acc == "#" else -1 if acc == "b" else 0)
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def check_number(where, value, low, high, whole=False):
    """A song number must be a real number in range (a string or a huge release would crash the render)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (whole and value != int(value)):
        raise SongError(f"{where} must be a {'whole ' if whole else ''}number, not {value!r}")
    if not low <= value <= high:
        raise SongError(f"{where} must be between {low} and {high}, not {value}")


def load_song(path):
    try:
        song = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SongError(f"{path}: not valid JSON ({exc})")
    for key in ("bpm", "channels", "patterns", "order"):
        if key not in song:
            raise SongError(f"{path}: missing \"{key}\"")
    if not song["order"]:
        raise SongError("\"order\" is empty")
    for key, low, high in SONG_RANGES:
        if key in song:
            check_number(f"\"{key}\"", song[key], low, high, whole=key != "bpm")
    channels = {}
    for name, ch in song["channels"].items():
        unknown = sorted(set(ch) - set(CHANNEL_DEFAULTS))
        if unknown:
            raise SongError(f"channel {name!r}: unknown setting(s) {', '.join(unknown)}")
        full = dict(CHANNEL_DEFAULTS, **ch)
        if full["wave"] not in WAVES:
            raise SongError(f"channel {name!r}: wave must be one of {', '.join(WAVES)}")
        for key, (low, high) in CHANNEL_RANGES.items():
            check_number(f"channel {name!r} {key}", full[key], low, high, whole=key == "octave")
        vib = full["vibrato"]
        if vib is not None and (not isinstance(vib, list) or len(vib) != 3):
            raise SongError(f"channel {name!r} vibrato must be [depth semitones, rate Hz, delay s]")
        for part, value, high in zip(("depth", "rate", "delay"), vib or [], (12, 50, 60)):
            check_number(f"channel {name!r} vibrato {part}", value, 0, high)
        channels[name] = full
    for pname in song["order"]:
        if pname not in song["patterns"]:
            raise SongError(f"order names pattern {pname!r}, which is not in \"patterns\"")
    steps = {}
    for pname, pat in song["patterns"].items():
        lengths = set()
        for cname, text in pat.items():
            if cname not in channels:
                raise SongError(f"pattern {pname!r}: channel {cname!r} is not in \"channels\"")
            tokens = [t for t in text.split() if t != "|"]
            drums = channels[cname]["wave"] == "drums"
            for i, t in enumerate(tokens):
                ok = t in ("-", ".") or (t in DRUMS if drums else note_freq(t) is not None)
                if not ok:
                    kind = "drum (k s h o c)" if drums else "note like C4, F#5 or Bb3"
                    raise SongError(f"pattern {pname!r}, channel {cname!r}, step {i + 1}: {t!r} is not a {kind}, "
                                    f"'-' or '.'")
            lengths.add(len(tokens))
        if len(lengths) > 1:
            detail = ", ".join(f"{c}={len([t for t in x.split() if t != '|'])}" for c, x in pat.items())
            raise SongError(f"pattern {pname!r}: channels have different step counts ({detail})")
        steps[pname] = lengths.pop() if lengths else 0
    song["_channels"], song["_steps"] = channels, steps
    return song


def events_for(song, cname):
    """[(start_step, length_steps, token)] for one channel across the whole order. '-' extends a note,
    also across pattern boundaries."""
    tokens = []
    for pname in song["order"]:
        text = song["patterns"][pname].get(cname)
        n = song["_steps"][pname]
        tokens += [t for t in text.split() if t != "|"] if text else ["."] * n
    events = []
    for i, t in enumerate(tokens):
        if t == "-":
            if events and events[-1][0] + events[-1][1] == i:
                events[-1][1] += 1
        elif t != ".":
            events.append([i, 1, t])
    return [tuple(e) for e in events], len(tokens)


def poly_blep(t, dt):
    """Smooths the jump in a square or saw wave, which removes most of the harsh aliasing."""
    if t < dt:
        t /= dt
        return t + t - t * t - 1.0
    if t > 1.0 - dt:
        t = (t - 1.0) / dt
        return t * t + t + t + 1.0
    return 0.0


def render_note(ch, freq, gate, rate, rng):
    """Samples for one note: oscillator x ADSR, gate samples long plus the release."""
    a = max(int(ch["attack"] * rate), 1)
    d = max(int(ch["decay"] * rate), 1)
    r = max(int(ch["release"] * rate), int(0.004 * rate))
    s_level = ch["sustain"]
    vib = ch["vibrato"]
    out, phase, level, noise = [], 0.0, 0.0, 0.0
    for i in range(gate + r):
        if i < gate:
            level = i / a if i < a else max(s_level, 1.0 - (1.0 - s_level) * (i - a) / d)
            held = level
        else:
            level = held * (1.0 - (i - gate) / r)
        f = freq
        if vib and i / rate > vib[2]:
            f *= 2.0 ** (vib[0] / 12.0 * math.sin(2.0 * math.pi * vib[1] * (i / rate - vib[2])))
        dt = f / rate
        phase += dt
        if phase >= 1.0:
            phase -= 1.0
            noise = rng.uniform(-1.0, 1.0)
        w = ch["wave"]
        if w == "square":
            duty = ch["duty"]
            v = (1.0 if phase < duty else -1.0) + poly_blep(phase, dt) - poly_blep((phase - duty) % 1.0, dt)
        elif w == "saw":
            v = 2.0 * phase - 1.0 - poly_blep(phase, dt)
        elif w == "triangle":
            v = 4.0 * phase - 1.0 if phase < 0.5 else 3.0 - 4.0 * phase
            v = (min(15, int((v + 1.0) * 8.0)) - 7.5) / 7.5            # 16 steps in -1..1, the NES triangle
        elif w == "sine":
            v = math.sin(2.0 * math.pi * phase)
        else:
            v = noise
        out.append(v * level)
    return out


def render_drum(kind, rate, rng):
    """One drum hit, made from scratch: pitch-dropping sine kick, noise snare and hats."""
    if kind == "k":
        n, out, phase = int(0.16 * rate), [], 0.0
        for i in range(n):
            t = i / rate
            phase += (45.0 + 110.0 * math.exp(-t * 30.0)) / rate
            click = rng.uniform(-1, 1) * max(0.0, 1.0 - t / 0.004) * 0.4
            out.append((math.sin(2.0 * math.pi * phase) + click) * (1.0 - i / n) ** 1.5)
        return out
    if kind == "s":
        n, out, phase = int(0.14 * rate), [], 0.0
        for i in range(n):
            t = i / rate
            phase += 185.0 / rate
            tone = math.sin(2.0 * math.pi * phase) * max(0.0, 1.0 - t / 0.05) * 0.5
            out.append((rng.uniform(-1, 1) * 0.7 + tone) * (1.0 - i / n) ** 2)
        return out
    length = {"h": 0.035, "o": 0.18, "c": 1.0}[kind]
    n, out, prev = int(length * rate), [], 0.0
    for i in range(n):
        x = rng.uniform(-1, 1)
        out.append((x - prev) * 0.5 * (1.0 - i / n) ** 2)            # differencing = a cheap high-pass
        prev = x
    return out


def render_song(song, rate, solo=None):
    """(samples, loop_or_None, info)."""
    step_s = 60.0 / song["bpm"] / song.get("steps_per_beat", 4)
    rng = random.Random(song.get("seed", 1))
    mix, total_steps, onset_at_start = None, 0, False
    for cname, ch in song["_channels"].items():
        if solo and cname != solo:
            continue
        events, total_steps = events_for(song, cname)
        onset_at_start = onset_at_start or any(start == 0 for start, _, _ in events)
        if mix is None:
            # room after the last step for the longest release or drum tail (Kimi's audit: a 3 s release overflowed)
            tail_s = max([c["release"] for c in song["_channels"].values()] + [DRUM_TAIL_S]) + 0.5
            mix = [0.0] * (int(round(total_steps * step_s * rate)) + int(tail_s * rate))
        for start, length, token in events:
            at = int(round(start * step_s * rate))
            gate = int(round((start + length) * step_s * rate)) - at
            if ch["wave"] == "drums":
                samples = render_drum(token, rate, rng)
            else:
                samples = render_note(ch, note_freq(token, ch["octave"]), gate, rate, rng)
            vol = ch["volume"]
            for i, v in enumerate(samples):
                mix[at + i] += v * vol
        dbg(f"channel {cname}: {len(events)} notes")
    if mix is None:
        raise SongError(f"no channel named {solo!r}" if solo else "the song has no channels")
    end = int(round(total_steps * step_s * rate))
    loop = None
    if song.get("loop", True):
        for i in range(end, len(mix)):                    # wrap release tails onto the start: seamless loop
            mix[i - end] += mix[i]
        mix = mix[:end]
        loop = (0, end - 1)
    else:
        last = max((i for i, v in enumerate(mix) if abs(v) > 1e-4), default=end)
        mix = mix[:max(end, last + 1)]
    peak = max((abs(v) for v in mix), default=0.0)
    gain = PEAK / peak if peak > 0 else 1.0
    mix = [v * gain for v in mix]
    return mix, loop, {"steps": total_steps, "gain": round(gain, 3), "onset_at_start": onset_at_start}


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="Render a chiptune song file (JSON, notes in text patterns) to a WAV that loops seamlessly.",
        epilog="Exit codes: 0 ok, 1 silent output or a clicking loop seam, 2 usage or a song error.")
    ap.add_argument("song", help="song file (.json, format in this script's header)")
    ap.add_argument("--out", help="output WAV path")
    ap.add_argument("--rate", type=int, help=f"sample rate (default: the song's, else {DEFAULT_RATE})")
    ap.add_argument("--solo", help="render only this channel")
    ap.add_argument("--check", action="store_true", help="only validate the song and print its layout")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    ap.add_argument("--debug", action="store_true", help="print per-channel detail and tracebacks")
    args = ap.parse_args(argv)
    DEBUG = args.debug
    try:
        song = load_song(args.song)
        step_s = 60.0 / song["bpm"] / song.get("steps_per_beat", 4)
        total = sum(song["_steps"][p] for p in song["order"])
        layout = (f"{len(song['_channels'])} channels, {len(song['patterns'])} patterns, order of "
                  f"{len(song['order'])}, {total} steps = {total * step_s:.2f} s at {song['bpm']} bpm")
        if args.check:
            print(f"[ OK ] {args.song}: {layout}")
            return 0
        if not args.out:
            raise SongError("--out is required (or use --check)")
        out = Path(args.out)
        if out.exists() and not args.overwrite:
            raise SongError(f"{out} exists (use --overwrite)")
        rate = args.rate or song.get("rate", DEFAULT_RATE)
        samples, loop, info = render_song(song, rate, args.solo)
        if not samples or max(abs(v) for v in samples) < 0.01:
            print(f"[FAIL] {out}: silent (no notes?)")
            return 1
        write_wav(out, samples, rate, loop)
        st = stats(samples, rate, loop)
        msg = (f"{out}: {layout}; {st['seconds']} s, peak {st['peak_dbfs']} dBFS, loudness {st['rms_dbfs']} dBFS RMS"
               + (f", loop seam step {st['loop_seam_step']}" if loop else ", no loop"))
        # A note or drum on the first step is meant to start sharply. Without one, the wrap must be smooth,
        # so a jump there is a click (a bug in the song or in this tool).
        if loop and not st["loop_seam_ok"] and not info["onset_at_start"]:
            print(f"[FAIL] {msg}: the loop seam jumps (a click) although nothing starts on the first step")
            return 1
        print(f"[ OK ] {msg}")
        return 0
    except SongError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

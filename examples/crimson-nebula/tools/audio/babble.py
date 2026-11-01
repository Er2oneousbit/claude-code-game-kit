#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# babble.py
# Purpose : Gibberish character voices for speech bubbles ("babble"): a line of dialog becomes short voiced
#           blips plus a timing file, so the game reveals the bubble text in step with the voice. The same
#           line, voice and seed always sound the same. No model, no account, no license question.
# Usage   : python tools/audio/babble.py --list
#           python tools/audio/babble.py "Welcome, traveler!" --voice baker --out assets/audio/voice/welcome.wav
#           python tools/audio/babble.py "Halt. Who goes there?" --voice knight --variants 3 --out build/audition/halt.wav
#           python tools/audio/babble.py --lines docs/dialog/smith.txt --voice smith --out assets/audio/voice/smith.wav
#           python tools/audio/babble.py "..." --voice golem --set f0=50 --set metal=0.7 --out golem.wav
#           python tools/audio/babble.py "..." --voice baker --bank-dir assets_src/voice/baker_syllables --out x.wav
# Needs   : Python 3.8+ only
# Exit    : 0 ok, 1 render problem (nothing to say: the text has no letters), 2 usage or environment problem
# Notes   : 44.1 kHz mono 16-bit WAV, plus <name>.timeline.json: {"text", "voice", "seed", "params", "seconds",
#           "reveal": [{"i": char index, "t": seconds}, ...]} with one entry per character of the text, so a
#           typewriter reveal can show character i at time t. The same JSON re-renders the line exactly.
#           Voices are formant-synthesized (a pulse train through three vowel filters, plus a short noise or
#           nasal onset for consonants). --bank-dir swaps in recorded syllables (ba.wav, ko.wav, ...; mono
#           16-bit WAV, spoken at about --bank-f0 Hz), for example rendered once per character by a TTS tool.
#           Parameters (--set): f0 Hz (base pitch), size (formant scale: >1 smaller creature, <1 bigger),
#           cps (revealed characters per second), per (letters per blip), jitter (random semitones),
#           blip s (vowel length), metal 0..1 (ring modulation: robots, golems), burst 0..1 (consonant onset
#           level), volume 0..1 (output peak).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   params = voice preset -> --set overrides -> check
#   plan:  walk the text; every `per` letters is one blip at the current time; letters advance time by 1/cps,
#          punctuation adds a pause; each blip's syllable = first consonant + first vowel of its letters
#          (so babble loosely follows the words); pitch = f0 + seeded jitter + sentence contour
#          ("?" raises the last two blips, "!" raises and louds the whole sentence)
#   render: each blip from the bank (synth: sawtooth -> 3 band-pass formants (+ ring mod) + consonant onset;
#           recorded: resample the syllable for pitch) -> 8 ms fades -> mix at its time -> normalize to volume
#   write: 16-bit WAV + timeline JSON (reveal times + everything needed to re-render)
import argparse
import hashlib
import json
import math
import random
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wavfile import read_wav, stats, write_wav  # noqa: E402

RATE = 44100
FADE_S = 0.008            # per-blip fade in/out: removes clicks between blips
TAIL_S = 0.25             # silence after the last blip so the end never cuts off
VOWELS = "aeiou"
# Vowel formants (F1, F2, F3) in Hz for an adult voice; each voice scales them by `size`.
FORMANTS = {"a": (730, 1090, 2440), "e": (530, 1840, 2480), "i": (270, 2290, 3010),
            "o": (570, 840, 2410), "u": (300, 870, 2240)}
FORMANT_BW = (90, 110, 160)        # bandwidths in Hz
FORMANT_GAIN = (1.0, 0.6, 0.25)    # higher formants are quieter in real voices
# Letters fold onto the consonants the voice can make; h (and y, w as vowels) give a plain vowel onset.
CONSONANTS = {**{c: c for c in "bdklmnptw"}, "c": "k", "g": "k", "q": "k", "x": "k", "f": "p", "v": "b",
              "s": "t", "z": "t", "j": "t", "r": "l", "h": "", "y": ""}
PLOSIVE_CENTRE_HZ = {"b": 900, "p": 1100, "d": 3000, "t": 4000, "k": 2200}
PAUSES_S = {",": 0.12, ";": 0.15, ":": 0.15, ".": 0.28, "!": 0.28, "?": 0.30, "\n": 0.35}
SENTENCE_END = ".!?\n"
DEFAULTS = {"f0": 150.0, "size": 1.0, "cps": 26.0, "per": 2, "jitter": 1.0, "blip": 0.08, "metal": 0.0,
            "burst": 0.5, "volume": 0.7}
PRESETS = {
    "baker":  {"f0": 210, "size": 1.12, "cps": 28, "per": 2, "jitter": 1.5, "blip": 0.075},
    "knight": {"f0": 140, "size": 1.0, "cps": 26, "per": 2, "jitter": 1.0, "blip": 0.08},
    "smith":  {"f0": 92, "size": 0.92, "cps": 18, "per": 3, "jitter": 0.8, "blip": 0.11, "burst": 0.35},
    "sprite": {"f0": 560, "size": 1.45, "cps": 40, "per": 1, "jitter": 3.0, "blip": 0.045},
    "golem":  {"f0": 58, "size": 0.8, "cps": 14, "per": 3, "jitter": 0.5, "blip": 0.14, "metal": 0.55, "burst": 0.3},
}
DEBUG = False


class BabbleError(Exception):
    """A problem the user can fix (bad parameter, missing file, existing output)."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def check_params(p):
    """Full, validated parameter set (defaults filled in)."""
    unknown = sorted(set(p) - set(DEFAULTS))
    if unknown:
        raise BabbleError(f"unknown parameter(s): {', '.join(unknown)} (known: {', '.join(sorted(DEFAULTS))})")
    full = dict(DEFAULTS)
    full.update(p)
    for k, v in full.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise BabbleError(f"{k} must be a number, not {v!r}")
    if not 30 <= full["f0"] <= 1200:
        raise BabbleError("f0 must be 30..1200 Hz")
    if full["cps"] <= 0 or full["size"] <= 0 or full["blip"] <= 2 * FADE_S:
        raise BabbleError(f"cps and size must be above 0, blip above {2 * FADE_S} s")
    if int(full["per"]) != full["per"] or full["per"] < 1:
        raise BabbleError("per must be a whole number of letters, 1 or more")
    for k in ("metal", "burst"):
        if not 0.0 <= full[k] <= 1.0:
            raise BabbleError(f"{k} must be in 0..1")
    if not 0.0 < full["volume"] <= 1.0:
        raise BabbleError("volume must be in 0..1")
    full["per"] = int(full["per"])
    return full


# --- syllable sources ---------------------------------------------------------------------------------------
def bandpass(samples, centre, bandwidth):
    """RBJ biquad band-pass (0 dB peak): keeps a formant region of the pulse train."""
    centre = min(centre, RATE * 0.45)
    w0 = 2 * math.pi * centre / RATE
    alpha = math.sin(w0) / (2 * max(centre / bandwidth, 0.3))
    a0 = 1 + alpha
    b0, b2 = alpha / a0, -alpha / a0
    a1, a2 = -2 * math.cos(w0) / a0, (1 - alpha) / a0
    out, x1, x2, y1, y2 = [], 0.0, 0.0, 0.0, 0.0
    for x in samples:
        y = b0 * x + b2 * x2 - a1 * y1 - a2 * y2
        out.append(y)
        x2, x1, y2, y1 = x1, x, y1, y
    return out


def peak_normalize(samples):
    peak = max((abs(s) for s in samples), default=0.0)
    return [s / peak for s in samples] if peak > 0 else samples


class SynthBank:
    """Formant synthesizer: any consonant + vowel at any pitch, made on demand."""

    def __init__(self, params):
        self.p = params

    def syllable(self, cons, vowel, f0, rng):
        p = self.p
        n = int(p["blip"] * RATE)
        phase, saw = 0.0, []
        for i in range(n):
            # 5.5 Hz, 1 percent vibrato: without it the blips sound like a test tone
            phase += f0 * (1 + 0.01 * math.sin(2 * math.pi * 5.5 * i / RATE)) / RATE
            saw.append(2 * (phase % 1.0) - 1)
        voiced = [0.0] * n
        for f, bw, g in zip(FORMANTS[vowel], FORMANT_BW, FORMANT_GAIN):
            for i, s in enumerate(bandpass(saw, f * p["size"], bw)):
                voiced[i] += s * g
        if p["metal"]:
            ring = 2.7 * f0                      # inharmonic ring frequency: metallic, not just buzzy
            voiced = [s * (1 - p["metal"] + p["metal"] * math.sin(2 * math.pi * ring * i / RATE))
                      for i, s in enumerate(voiced)]
        voiced = peak_normalize(voiced)
        onset = []
        # `cons` may be "" (vowel-only blip). Test membership with a dict, never `cons in "bdkpt"`:
        # the empty string is a substring of every string.
        if cons in PLOSIVE_CENTRE_HZ:
            m = int(0.018 * RATE)
            noise = bandpass([rng.gauss(0, 1) for _ in range(m)], PLOSIVE_CENTRE_HZ[cons] * p["size"], 1500)
            noise = peak_normalize(noise)
            onset = [s * p["burst"] * (1 - i / m) for i, s in enumerate(noise)]
        elif cons in ("m", "n"):
            m = int(0.03 * RATE)
            onset = [s * 0.8 for s in peak_normalize(bandpass(saw[:m], 280 * p["size"], 120))]
        elif cons in ("l", "w"):
            ramp = int(0.02 * RATE)              # glide: a soft vowel attack instead of an onset
            voiced = [s * min(1.0, i / ramp) for i, s in enumerate(voiced)]
        return onset + voiced


class RecordedBank:
    """Recorded syllables (<consonant><vowel>.wav). Pitch moves by resampling, which suits babble."""

    def __init__(self, folder, bank_f0, params):
        folder = Path(folder)
        if not folder.is_dir():
            raise BabbleError(f"--bank-dir {folder} is not a folder")
        self.clips = {}
        for path in sorted(folder.glob("*.wav")):
            try:
                samples, rate, _ = read_wav(path)
            except ValueError as exc:
                raise BabbleError(f"{path}: {exc}")
            self.clips[path.stem.lower()] = (samples, rate)
        if not self.clips:
            raise BabbleError(f"no .wav syllables in {folder} (expected files like ba.wav, ko.wav)")
        self.bank_f0, self.p = bank_f0, params

    def pick(self, cons, vowel):
        """Exact syllable, else any syllable with that vowel, else the first one (stable order)."""
        if cons + vowel in self.clips:
            return cons + vowel
        same_vowel = [k for k in sorted(self.clips) if k.endswith(vowel)]
        return same_vowel[0] if same_vowel else sorted(self.clips)[0]

    def syllable(self, cons, vowel, f0, rng):
        samples, rate = self.clips[self.pick(cons, vowel)]
        step = (f0 / self.bank_f0) * (rate / RATE)          # source samples per output sample
        n = min(int((len(samples) - 1) / step), int(self.p["blip"] * RATE * 1.6))
        out = []
        for i in range(n):
            pos = i * step
            j = int(pos)
            frac = pos - j
            out.append(samples[j] * (1 - frac) + samples[j + 1] * frac)
        return peak_normalize(out)


# --- text -> blips -> samples ---------------------------------------------------------------------------------
def seeded_rng(text, voice, seed):
    digest = hashlib.sha1(f"{voice}|{seed}|{text}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:12], 16))


def plan(text, p, rng):
    """(blips, reveal, seconds). blip = dict(t, cons, vowel, semis, gain); reveal = [{"i", "t"}] per character."""
    char_s = 1.0 / p["cps"]
    raw, reveal, t, chunk = [], [], 0.0, ""
    for i, ch in enumerate(text):
        reveal.append({"i": i, "t": round(t, 4)})
        low = ch.lower()
        if low.isalpha():
            chunk += low
            if len(chunk) >= p["per"]:
                raw.append((t, chunk, i))
                chunk = ""
            t += char_s
        else:
            chunk = ""                           # a blip never spans two words
            t += PAUSES_S.get(ch, char_s)

    def sentence_end(i):
        return next((j for j in range(i, len(text)) if text[j] in SENTENCE_END), len(text))

    sentences = {}
    for k, (_, _, i) in enumerate(raw):
        sentences.setdefault(sentence_end(i), []).append(k)
    blips = []
    for k, (bt, letters, i) in enumerate(raw):
        cons = next((CONSONANTS.get(c, "") for c in letters if c not in VOWELS), "")
        vowel = next((c for c in letters if c in VOWELS), VOWELS[rng.randrange(5)])
        end = sentence_end(i)
        mark = text[end] if end < len(text) else "."
        members = sentences[end]
        to_end = len(members) - 1 - members.index(k)          # 0 = the sentence's last blip
        semis, gain = rng.gauss(0, p["jitter"]) if p["jitter"] else 0.0, 1.0
        if mark == "?" and to_end <= 1:
            semis += 3 + 2 * (1 - to_end)                    # questions rise at the end
        if mark == "!":
            semis, gain = semis + 2, 1.25                    # exclamations: higher and louder throughout
        blips.append({"t": bt, "cons": cons, "vowel": vowel, "semis": semis, "gain": gain})
    return blips, reveal, t


def render(text, voice, params, seed=0, bank=None):
    """(samples, timeline dict) for one line. Deterministic for (text, voice, params, seed, bank files)."""
    rng = seeded_rng(text, voice, seed)
    blips, reveal, seconds = plan(text, params, rng)
    bank = bank or SynthBank(params)
    pieces, end = [], 0
    for b in blips:
        f0 = params["f0"] * 2 ** (b["semis"] / 12)
        syl = bank.syllable(b["cons"], b["vowel"], f0, rng)
        fade = min(int(FADE_S * RATE), len(syl) // 2)
        for i in range(fade):
            syl[i] *= i / fade
            syl[-1 - i] *= i / fade
        start = int(b["t"] * RATE)
        pieces.append((start, [s * b["gain"] for s in syl]))
        end = max(end, start + len(syl))
    total = max(end, int(seconds * RATE)) + int(TAIL_S * RATE)
    mix = [0.0] * total
    for start, syl in pieces:
        for i, s in enumerate(syl):
            mix[start + i] += s
    peak = max((abs(s) for s in mix), default=0.0)
    if peak > 0:
        mix = [s / peak * params["volume"] for s in mix]
    timeline = {"tool": "babble", "text": text, "voice": voice, "seed": seed, "params": params,
                "rate": RATE, "seconds": round(total / RATE, 4), "blips": len(blips), "reveal": reveal}
    return mix, timeline


def make(text, voice, params, seed, out_path, bank, write_timeline, overwrite):
    """Render, check and write one line. Returns (exit_code, message)."""
    tl_path = out_path.with_suffix(".timeline.json")
    for path in (out_path, tl_path if write_timeline else None):
        if path and path.exists() and not overwrite:
            raise BabbleError(f"{path} exists (use --overwrite)")
    samples, timeline = render(text, voice, params, seed, bank)
    if timeline["blips"] == 0:
        return 1, f"{out_path}: nothing to say (the text has no letters)"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_wav(out_path, samples, RATE)
    if write_timeline:
        tl_path.write_bytes((json.dumps(timeline, indent=1) + "\n").encode("utf-8"))
    st = stats(samples, RATE)
    return 0, f"{out_path}: {st['seconds']} s, {timeline['blips']} blips, peak {st['peak_dbfs']} dBFS"


def parse_set(items):
    out = {}
    for item in items or []:
        if "=" not in item:
            raise BabbleError(f"--set needs KEY=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        try:
            out[k.strip()] = float(v)
        except ValueError:
            raise BabbleError(f"--set {k.strip()}: {v!r} is not a number")
    return out


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="Gibberish character voices for speech bubbles, with a reveal timeline for typewriter text.",
        epilog="Exit codes: 0 ok, 1 nothing to say, 2 usage. Voices: " + ", ".join(PRESETS))
    ap.add_argument("text", nargs="?", help="the line of dialog (or use --lines)")
    ap.add_argument("--lines", help="text file: one bubble per non-empty line, written as <out>_1.wav, <out>_2.wav ...")
    ap.add_argument("--voice", default="knight", help="voice preset (see --list; default knight)")
    ap.add_argument("--out", help="output WAV path")
    ap.add_argument("--seed", type=int, default=0, help="another take of the same line (same seed, same sound)")
    ap.add_argument("--variants", type=int, default=0, help="write N takes (seeds 1..N) as <out>_1.wav ...")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE", help="override one voice parameter (repeatable)")
    ap.add_argument("--bank-dir", help="folder of recorded syllables (ba.wav, ko.wav ...) instead of the synth")
    ap.add_argument("--bank-f0", type=float, default=150.0, help="pitch the recorded syllables were spoken at (Hz)")
    ap.add_argument("--no-timeline", action="store_true", help="do not write <name>.timeline.json")
    ap.add_argument("--overwrite", action="store_true", help="replace existing files")
    ap.add_argument("--list", action="store_true", help="list voice presets and their parameters")
    ap.add_argument("--debug", action="store_true", help="print the blip plan and tracebacks")
    args = ap.parse_args(argv)
    DEBUG = args.debug
    try:
        if args.list:
            for name, p in PRESETS.items():
                print(f"{name:7} " + " ".join(f"{k}={v}" for k, v in check_params(dict(p)).items()))
            return 0
        if args.voice not in PRESETS:
            raise BabbleError(f"unknown voice {args.voice!r}; choose one of: {', '.join(PRESETS)}")
        if not args.out:
            raise BabbleError("--out is required")
        if bool(args.text) == bool(args.lines):
            raise BabbleError("give the text or --lines FILE (one of them)")
        if args.lines and args.variants > 0:
            raise BabbleError("--lines writes one take per line: it does not combine with --variants")
        params = dict(PRESETS[args.voice])
        params.update(parse_set(args.set))
        params = check_params(params)
        bank = RecordedBank(args.bank_dir, args.bank_f0, params) if args.bank_dir else None
        out = Path(args.out)
        if args.lines:
            try:
                lines = [l.strip() for l in Path(args.lines).read_text(encoding="utf-8").splitlines() if l.strip()]
            except OSError as exc:
                raise BabbleError(f"cannot read --lines: {exc}")
            jobs = [(line, args.seed, out.with_name(f"{out.stem}_{n}{out.suffix}")) for n, line in enumerate(lines, 1)]
        elif args.variants > 0:
            jobs = [(args.text, s, out.with_name(f"{out.stem}_{s}{out.suffix}")) for s in range(1, args.variants + 1)]
        else:
            jobs = [(args.text, args.seed, out)]
        code = 0
        for text, seed, target in jobs:
            dbg(f"{target.name}: seed {seed}, {params}")
            rc, msg = make(text, args.voice, params, seed, target, bank, not args.no_timeline, args.overwrite)
            print(("[ OK ] " if rc == 0 else "[FAIL] ") + msg)
            code = max(code, rc)
        return code
    except BabbleError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

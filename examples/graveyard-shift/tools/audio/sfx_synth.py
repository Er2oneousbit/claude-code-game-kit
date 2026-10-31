#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# sfx_synth.py
# Purpose : Make retro sound effects from code (the sfxr idea): pick a preset, get a WAV.
#           Seeds make variations that repeat exactly, and every file gets a small JSON recipe
#           so it can be re-rendered or tweaked later. No account, no download, no license
#           question: the output is yours.
# Usage   : python tools/audio/sfx_synth.py --list
#           python tools/audio/sfx_synth.py jump --out assets/audio/sfx/jump.wav
#           python tools/audio/sfx_synth.py coin --variants 5 --out build/audition/coin.wav   # coin_1..coin_5
#           python tools/audio/sfx_synth.py jump --seed 3 --set slide=3.0 --set decay=0.25 --out jump.wav
#           python tools/audio/sfx_synth.py --from assets/audio/src/jump.sfx.json --out jump.wav
# Needs   : Python 3.8+ only
# Exit    : 0 ok, 1 render problem (clipped or silent output), 2 usage or environment problem
# Notes   : 44.1 kHz mono 16-bit WAV. Godot, Unity, Unreal and browsers all play WAV; convert to OGG
#           only if size matters. Listen to --variants side by side and keep the best seed.
#           Parameters (all optional in --set or a recipe): wave square|saw|triangle|sine|noise,
#           freq Hz, freq_min Hz (the sound stops below it), slide octaves/s, slide_accel octaves/s^2,
#           duty 0..1 (square only), duty_sweep per s, vibrato_depth semitones, vibrato_rate Hz,
#           arp_mult (frequency jump), arp_time s, repeat s (restart the pitch), attack, sustain,
#           decay s, punch 0..1 (louder start of sustain), lowpass Hz, highpass Hz, volume 0..1.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   params = preset (or --from recipe) -> seeded jitter (--seed, --vary) -> --set overrides
#   for each sample: pitch = freq * 2^(slide*t + accel*t^2/2) * vibrato * arpeggio (repeat restarts t)
#                    oscillator(wave, phase, duty) -> envelope(attack, sustain + punch, decay)
#                    -> one-pole low-pass / high-pass -> volume
#   short fades at both ends (no clicks) -> 16-bit WAV + recipe JSON
import argparse
import json
import math
import random
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wavfile import stats, write_wav  # noqa: E402

RATE = 44100
VARY = 0.12               # default jitter for --seed / --variants: each number moves up to +-12 percent
FADE_S = 0.004            # fade in and out, removes clicks at both ends
NOISE_STEPS = 32          # noise changes value 32 times per oscillator period (sfxr's trick for pitched noise)
MAX_SECONDS = 5.0
DEFAULTS = {
    "wave": "square", "freq": 440.0, "freq_min": 20.0, "slide": 0.0, "slide_accel": 0.0,
    "duty": 0.5, "duty_sweep": 0.0, "vibrato_depth": 0.0, "vibrato_rate": 0.0,
    "arp_mult": 1.0, "arp_time": 0.0, "repeat": 0.0,
    "attack": 0.0, "sustain": 0.1, "decay": 0.2, "punch": 0.0,
    "lowpass": 0.0, "highpass": 0.0, "volume": 0.5,
}
PRESETS = {
    "jump":      {"wave": "square", "freq": 300, "slide": 2.4, "duty": 0.42, "sustain": 0.05, "decay": 0.17,
                  "lowpass": 7000, "volume": 0.45},
    "coin":      {"wave": "square", "freq": 988, "arp_mult": 1.3348, "arp_time": 0.07, "duty": 0.5,
                  "sustain": 0.09, "decay": 0.26, "punch": 0.35, "lowpass": 9000, "volume": 0.4},
    "land":      {"wave": "noise", "freq": 70, "slide": -1.2, "sustain": 0.015, "decay": 0.09, "punch": 0.3,
                  "lowpass": 1600, "volume": 0.6},
    "fall":      {"wave": "square", "freq": 620, "slide": -1.6, "duty": 0.3, "vibrato_depth": 0.7,
                  "vibrato_rate": 11, "sustain": 0.3, "decay": 0.35, "lowpass": 5000, "volume": 0.4},
    "hit":       {"wave": "saw", "freq": 420, "slide": -2.8, "sustain": 0.03, "decay": 0.16, "punch": 0.4,
                  "lowpass": 4000, "volume": 0.45},
    "pickup":    {"wave": "square", "freq": 360, "slide": 1.4, "repeat": 0.075, "duty": 0.35,
                  "sustain": 0.22, "decay": 0.18, "lowpass": 8000, "volume": 0.38},
    "blip":      {"wave": "square", "freq": 1250, "duty": 0.25, "sustain": 0.035, "decay": 0.04, "volume": 0.35},
    "laser":     {"wave": "saw", "freq": 1500, "slide": -3.6, "sustain": 0.07, "decay": 0.12, "lowpass": 6000,
                  "volume": 0.38},
    "explosion": {"wave": "noise", "freq": 110, "slide": -0.7, "sustain": 0.12, "decay": 0.6, "punch": 0.5,
                  "lowpass": 3200, "volume": 0.6},
}
WAVES = ("square", "saw", "triangle", "sine", "noise")
DEBUG = False


class SynthError(Exception):
    """A problem the user can fix (bad parameter, bad recipe)."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def jitter(params, seed, vary):
    """Copy of params with every number nudged by up to +-vary, the same way every time for one seed."""
    rng = random.Random(seed)
    out = dict(params)
    for k in sorted(out):
        v = out[k]
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0 and k != "volume":
            out[k] = round(v * (1.0 + rng.uniform(-vary, vary)), 4)
    return out


def check_params(p):
    """Full, validated parameter set (defaults filled in)."""
    unknown = sorted(set(p) - set(DEFAULTS))
    if unknown:
        raise SynthError(f"unknown parameter(s): {', '.join(unknown)} (known: {', '.join(sorted(DEFAULTS))})")
    full = dict(DEFAULTS)
    full.update(p)
    if full["wave"] not in WAVES:
        raise SynthError(f"wave must be one of {', '.join(WAVES)}, not {full['wave']!r}")
    for k, v in full.items():
        if k != "wave" and not isinstance(v, (int, float)):
            raise SynthError(f"{k} must be a number, not {v!r}")
    if full["freq"] <= 0:
        raise SynthError("freq must be above 0")
    if not 0.0 < full["volume"] <= 1.0:
        raise SynthError("volume must be in 0..1")
    if full["attack"] + full["sustain"] + full["decay"] > MAX_SECONDS:
        raise SynthError(f"attack + sustain + decay is longer than {MAX_SECONDS} s")
    return full


def oscillator(wave, phase, duty, rng, state):
    if wave == "square":
        return 1.0 if phase < duty else -1.0
    if wave == "saw":
        return 2.0 * phase - 1.0
    if wave == "triangle":
        return 4.0 * phase - 1.0 if phase < 0.5 else 3.0 - 4.0 * phase
    if wave == "sine":
        return math.sin(2.0 * math.pi * phase)
    step = int(phase * NOISE_STEPS)              # noise: sample and hold, new value each step
    if step != state["noise_step"]:
        state["noise_step"] = step
        state["noise"] = rng.uniform(-1.0, 1.0)
    return state["noise"]


def envelope(t, p):
    a, s, d = p["attack"], p["sustain"], p["decay"]
    if t < a:
        return t / a
    t -= a
    if t < s:
        return 1.0 + p["punch"] * (1.0 - t / s) if s > 0 else 1.0
    t -= s
    if t < d:
        return 1.0 - t / d
    return 0.0


def render(p, seed=0):
    """List of float samples for a validated parameter set."""
    n = int((p["attack"] + p["sustain"] + p["decay"]) * RATE)
    rng = random.Random(seed)
    state = {"noise_step": -1, "noise": 0.0}
    phase, low, high_in, high_out = 0.0, 0.0, 0.0, 0.0
    lp = 1.0 - math.exp(-2.0 * math.pi * p["lowpass"] / RATE) if p["lowpass"] > 0 else 1.0
    hp = math.exp(-2.0 * math.pi * p["highpass"] / RATE) if p["highpass"] > 0 else 0.0
    out = []
    for i in range(n):
        t = i / RATE
        tp = t % p["repeat"] if p["repeat"] > 0 else t          # repeat restarts the pitch sweep
        freq = p["freq"] * 2.0 ** (p["slide"] * tp + 0.5 * p["slide_accel"] * tp * tp)
        if p["arp_time"] > 0 and tp >= p["arp_time"]:
            freq *= p["arp_mult"]
        if p["vibrato_depth"] > 0:
            freq *= 2.0 ** (p["vibrato_depth"] / 12.0 * math.sin(2.0 * math.pi * p["vibrato_rate"] * t))
        if freq < p["freq_min"]:
            break
        freq = min(freq, RATE / 2.5)
        phase = (phase + freq / RATE) % 1.0
        duty = min(0.95, max(0.05, p["duty"] + p["duty_sweep"] * t))
        v = oscillator(p["wave"], phase, duty, rng, state) * envelope(t, p)
        low += lp * (v - low)                                    # one-pole low-pass
        v = low
        if hp:
            high_out = hp * (high_out + v - high_in)             # one-pole high-pass
            high_in = v
            v = high_out
        out.append(v * p["volume"])
    fade = min(int(FADE_S * RATE), len(out) // 2)
    for i in range(fade):
        g = i / fade
        out[i] *= g
        out[-1 - i] *= g
    return out


def parse_set(items):
    """--set key=value pairs -> dict (numbers where they parse)."""
    out = {}
    for item in items or []:
        if "=" not in item:
            raise SynthError(f"--set needs key=value, got {item!r}")
        k, v = item.split("=", 1)
        try:
            out[k.strip()] = float(v)
        except ValueError:
            out[k.strip()] = v.strip()
    return out


def make(params, seed, out_path, recipe_path, meta, overwrite):
    """Render, check and write one sound. Returns (exit_code, message)."""
    for path in (out_path, recipe_path):
        if path and path.exists() and not overwrite:
            raise SynthError(f"{path} exists (use --overwrite)")
    samples = render(params, seed)
    if not samples or max(abs(s) for s in samples) < 0.01:
        return 1, f"{out_path}: the sound came out silent (freq below freq_min at once?)"
    clipped = write_wav(out_path, samples, RATE)
    if recipe_path:
        recipe_path.parent.mkdir(parents=True, exist_ok=True)
        recipe = dict(meta, tool="sfx_synth", rate=RATE, render_seed=seed, params=params)
        recipe_path.write_bytes((json.dumps(recipe, indent=2) + "\n").encode("utf-8"))
    st = stats(samples, RATE)
    msg = f"{out_path}: {st['seconds']} s, peak {st['peak_dbfs']} dBFS, loudness {st['rms_dbfs']} dBFS RMS"
    if clipped:
        return 1, msg + f", {clipped} samples clipped (lower volume)"
    return 0, msg


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="Make retro sound effects from presets. Seeds make repeatable variations; each WAV gets a "
                    "JSON recipe for exact re-rendering.",
        epilog="Exit codes: 0 ok, 1 clipped or silent output, 2 usage. Presets: " + ", ".join(PRESETS))
    ap.add_argument("preset", nargs="?", help="preset name (see --list); not needed with --from")
    ap.add_argument("--out", help="output WAV path")
    ap.add_argument("--seed", type=int, help="vary the preset with this seed (same seed, same sound)")
    ap.add_argument("--vary", type=float, default=VARY, help=f"how far a seed moves each number (default {VARY})")
    ap.add_argument("--variants", type=int, default=0, help="write N variations (seeds 1..N) as <out>_1.wav ...")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE", help="override one parameter (repeatable)")
    ap.add_argument("--from", dest="recipe_in", help="render the exact parameters from a recipe JSON")
    ap.add_argument("--recipe", help="where to write the recipe (default: next to the WAV as <name>.sfx.json)")
    ap.add_argument("--no-recipe", action="store_true", help="do not write a recipe")
    ap.add_argument("--overwrite", action="store_true", help="replace existing files")
    ap.add_argument("--list", action="store_true", help="list presets and their parameters")
    ap.add_argument("--debug", action="store_true", help="print parameters and tracebacks")
    args = ap.parse_args(argv)
    DEBUG = args.debug
    try:
        if args.list:
            for name, p in PRESETS.items():
                print(f"{name:10} " + " ".join(f"{k}={v}" for k, v in p.items()))
            return 0
        if not args.out:
            raise SynthError("--out is required")
        out = Path(args.out)
        if args.recipe_in:
            if args.variants > 0 or args.seed is not None:
                # a recipe is one exact sound; varying it is a new preset run (Kimi's audit: this silently wrote one file)
                raise SynthError("--from renders one exact sound: it does not combine with --variants or --seed")
            recipe = json.loads(Path(args.recipe_in).read_text(encoding="utf-8"))
            base, meta = recipe.get("params", {}), {"from": str(args.recipe_in)}
            seeds = [recipe.get("render_seed", 0)]
        else:
            if args.preset not in PRESETS:
                raise SynthError(f"unknown preset {args.preset!r}; choose one of: {', '.join(PRESETS)}")
            base, meta = PRESETS[args.preset], {"preset": args.preset, "vary": args.vary}
            seeds = list(range(1, args.variants + 1)) if args.variants > 0 else [args.seed]
        code = 0
        for seed in seeds:
            params = dict(base)
            if seed is not None and not args.recipe_in:
                params = jitter(params, seed, args.vary)
            params.update(parse_set(args.set))
            params = check_params(params)
            dbg(f"seed {seed}: {params}")
            target = out.with_name(f"{out.stem}_{seed}{out.suffix}") if args.variants > 0 else out
            recipe_path = None if args.no_recipe else (
                Path(args.recipe) if args.recipe and args.variants <= 0 else target.with_suffix(".sfx.json"))
            rc, msg = make(params, seed or 0, target, recipe_path, dict(meta, seed=seed), args.overwrite)
            print(("[ OK ] " if rc == 0 else "[FAIL] ") + msg)
            code = max(code, rc)
        return code
    except SynthError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

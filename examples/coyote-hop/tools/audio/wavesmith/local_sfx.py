#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# local_sfx.py
# Purpose : Sound effects and ambience loops from a text prompt on your own GPU: Stable Audio 3 through a local
#           ComfyUI. Renders several takes (seeds), cleans each one up (trims silence, normalizes, makes loops
#           seamless), ranks them on technical checks and keeps the best few for you to pick by ear.
# Usage   : python tools/audio/wavesmith/wavesmith.py sfx check                         # ComfyUI up? Stable Audio 3 files there?
#           python tools/audio/wavesmith/wavesmith.py sfx make "heavy wooden door creaking open, iron hinges" --seconds 2.5 \
#               --out build/audition/door.wav                              # 6 takes, keeps door_1 (best) .. door_3
#           python tools/audio/wavesmith/wavesmith.py sfx make "steady rain on a roof" --seconds 10 --loop \
#               --out assets/audio/amb/rain.wav --keep 1 --log
#           python tools/audio/wavesmith/wavesmith.py sfx make "short soft UI click" --seconds 0.4 --mono --model small-sfx \
#               --out build/audition/click.wav
#           python tools/audio/wavesmith/wavesmith.py sfx make "..." --seconds 2 --out x.wav --dry-run   # show the graph, send nothing
# Needs   : Python 3.8+ only, plus a running ComfyUI (0.43.0 or newer has Stable Audio 3 built in) with
#           checkpoints/stable_audio_3_medium.safetensors (or _small_sfx) and text_encoders/t5gemma_b_b_ul2.safetensors
#           from https://huggingface.co/Comfy-Org/stable-audio-3 . `check` names whatever is missing.
# Exit    : 0 ok, 1 ComfyUI failed or every take failed the checks, 2 usage, server not running, missing files
# Notes   : License: Stable Audio 3 is under the Stability AI Community License: free for individuals and
#           organizations under USD 1M annual revenue, an enterprise license above that (verify, and read
#           https://stability.ai/license before you ship). Each .gen.json records the model and license.
#           Ranking is technical only (clipping, silence, length against --seconds, crest factor, loop seam): it
#           cannot tell whether a take sounds like the prompt. Listen and choose; that is why it keeps several.
#           One-shots get 3 ms / 10 ms fades; --loop trims the silent tail Stable Audio leaves and crossfades the
#           end into the start (a 'smpl' loop chunk Godot and Unity read). Output: 44.1 kHz 16-bit WAV, stereo
#           unless --mono. Decoding is flacfile.py (ComfyUI saves FLAC with the prompt and workflow in its tags;
#           only the audio reaches the WAV). Settings per model come from the 2026-10-31 bake-off (K01).
#           Existing files are never replaced without --overwrite.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   check: server up (comfy_local) -> audio nodes exist -> checkpoint + text encoder in ComfyUI's lists?
#   make:  outputs free (or --overwrite), --log target valid  [before any GPU time]
#          for each seed: Stable Audio 3 graph -> queue -> wait -> GET the FLAC -> decode (tags dropped)
#            -> post: optional mono -> trim lead and tail silence -> loop crossfade or click fades -> normalize
#            -> technical score
#          rank (best first) -> keep the top --keep as <out>_1 .. <out>_N with <name>.gen.json -> --log row
import argparse
import datetime
import hashlib
import json
import math
import sys
import traceback
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[1] / "art"))
import comfy_local as cl  # noqa: E402  (server URL rule, queue, wait, job errors)
import fetch_asset  # noqa: E402  (shared ASSET_LOG helpers)
import flacfile  # noqa: E402
from wavfile import crossfade_loop, stats, write_wav  # noqa: E402

# Bake-off K01 (2026-10-31, 29 prompts x 3 seeds): medium won on every style (clean UI, realistic, stylized, retro)
# at the same speed as small-sfx once loaded; small-sfx is the second opinion (it won some creature and foley prompts).
MODELS = {
    "medium":    {"ckpt": "stable_audio_3_medium.safetensors"},
    "small-sfx": {"ckpt": "stable_audio_3_small_sfx.safetensors"},
}
TEXT_ENCODER = "t5gemma_b_b_ul2.safetensors"
SAMPLER = {"steps": 8, "cfg": 1.0, "sampler_name": "lcm", "scheduler": "simple"}   # the distilled models' settings
NEGATIVE = "music, melody, speech, voice, low quality, distorted, muffled"
AUDIO_NODES = ("EmptyLatentAudio", "VAEDecodeAudio", "SaveAudio", "CLIPLoader", "CheckpointLoaderSimple")
MODEL_SOURCE = "https://huggingface.co/Comfy-Org/stable-audio-3"
LICENSE = ("Stability AI Community License: free under USD 1M annual revenue, enterprise license above "
           "(verify at https://stability.ai/license)")
LOOP_MARGIN_S = 2.0           # loops: Stable Audio leaves up to about 1.7 s of silent tail (live check); trim eats it
MIN_GEN_S = 1.5               # ComfyUI's floor is 1 s; shorter requests come out as padded noise, trim does the rest
MAX_GEN_S = 120.0
MAX_VARIANTS = 64             # takes per run; a typo like 1000000000 built the seed list first (MemoryError, #261)
SILENCE_DB = -50.0            # below the take's own peak: what counts as silence when trimming
LEAD_KEEP_S = 0.005
TAIL_KEEP_S = 0.05
FADE_IN_S, FADE_OUT_S = 0.003, 0.010
RANKERS = ("technical",)      # hook: a meaning-based ranker (e.g. CLAP in an optional env) can register here
DEBUG = False


class ToolError(Exception):
    """Exit 2: something the user can fix."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


# ---- ComfyUI -------------------------------------------------------------------------
def node_options(info, node, field):
    """The choices ComfyUI offers for a combo input (old [[...]] and new {"options": [...]} shapes)."""
    spec = (((info.get(node) or {}).get("input") or {}).get("required") or {}).get(field) or []
    if spec and isinstance(spec[0], list):
        return spec[0]
    if len(spec) > 1 and isinstance(spec[1], dict):
        return spec[1].get("options") or []
    return []


def preflight(base, model):
    """System line, or ToolError naming the missing node or file and where it comes from."""
    stats_ = cl.get_json(base, "/system_stats")
    info = cl.get_json(base, "/object_info")
    missing = [n for n in AUDIO_NODES if n not in info]
    if missing:
        raise ToolError(f"this ComfyUI lacks {', '.join(missing)}: update it (Stable Audio 3 needs 0.43.0 or newer)")
    ckpt = MODELS[model]["ckpt"]
    if ckpt not in node_options(info, "CheckpointLoaderSimple", "ckpt_name"):
        raise ToolError(f"ComfyUI has no checkpoints/{ckpt}. Download it from {MODEL_SOURCE} (checkpoints/) "
                        "into ComfyUI's models/checkpoints, then restart ComfyUI")
    if TEXT_ENCODER not in node_options(info, "CLIPLoader", "clip_name"):
        raise ToolError(f"ComfyUI has no text_encoders/{TEXT_ENCODER}. Download it from {MODEL_SOURCE} "
                        "(text_encoders/) into ComfyUI's models/text_encoders, then restart ComfyUI")
    return cl.system_text(stats_)


def graph(model, prompt, seconds, seed):
    """Stable Audio 3 text-to-audio in ComfyUI's API format (the same graph as its official template)."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": MODELS[model]["ckpt"]}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "stable_audio",
                                                       "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["2", 0]}},
        "5": {"class_type": "EmptyLatentAudio", "inputs": {"seconds": seconds, "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": dict(SAMPLER, model=["1", 0], positive=["3", 0], negative=["4", 0],
                                                        latent_image=["5", 0], seed=seed, denoise=1.0)},
        "7": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveAudio", "inputs": {"audio": ["7", 0], "filename_prefix": "local_sfx/take"}},
    }


def render_take(base, wf, wait):
    """(samples interleaved, rate, channels, gpu_seconds) for one queued graph. Raises cl.JobError on failure."""
    prompt_id = cl.queue(base, wf)
    entry, seconds = cl.wait_history(base, prompt_id, wait)
    items = [i for i in cl.output_files(entry, False) if i["filename"].lower().endswith(".flac")]
    if not items:
        raise cl.JobError("the job finished but saved no FLAC (is the Save Audio node still in the graph?)")
    query = urllib.parse.urlencode({"filename": items[0]["filename"], "subfolder": items[0].get("subfolder", ""),
                                    "type": items[0].get("type", "output")})
    status, data = cl.http("GET", f"{base}/view?{query}")
    if status != 200:
        raise cl.JobError(f"could not fetch {items[0]['filename']} (HTTP {status})")
    try:
        info, chans, _ = flacfile.decode(data)
    except (flacfile.FlacError, flacfile.FlacCorrupt) as exc:
        raise cl.JobError(f"ComfyUI's FLAC did not decode: {exc}")
    scale = float(1 << (info["bits"] - 1))
    samples = [s / scale for frame in zip(*chans) for s in frame]
    return samples, info["rate"], info["channels"], seconds


# ---- Post-processing -----------------------------------------------------------------
def frame_levels(samples, channels):
    return [max(abs(samples[i + c]) for c in range(channels)) for i in range(0, len(samples), channels)]


def post(samples, rate, channels, args):
    """(clean samples, channels, loop or None, report). Report holds what scoring needs."""
    if args.mono and channels == 2:
        samples = [(samples[i] + samples[i + 1]) / 2 for i in range(0, len(samples), 2)]
        channels = 1
    levels = frame_levels(samples, channels)
    peak = max(levels, default=0.0)
    report = {"raw_peak_dbfs": round(20 * math.log10(peak), 1) if peak > 0 else -120.0,
              "raw_clipped": sum(1 for s in samples if abs(s) >= 0.999), "raw_seconds": round(len(levels) / rate, 3)}
    if peak <= 0:
        return samples, channels, None, dict(report, seconds=report["raw_seconds"], trimmed_s=0.0)
    floor = peak * 10 ** (SILENCE_DB / 20)
    loud = [i for i, v in enumerate(levels) if v > floor]
    first = max(0, loud[0] - int(LEAD_KEEP_S * rate))
    last = min(len(levels), loud[-1] + 1 + int(TAIL_KEEP_S * rate))
    body = samples[first * channels:last * channels]
    frames = len(body) // channels
    loop = None
    if args.loop:
        # cut to exactly length + crossfade so every loop is the requested length (the crossfade hides the cut)
        body = body[:int((args.seconds + args.crossfade) * rate) * channels]
        try:
            body = crossfade_loop(body, rate, args.crossfade, channels)
        except ValueError as exc:
            raise cl.JobError(f"cannot loop this take: {exc} (lower --crossfade or raise --seconds)")
        frames = len(body) // channels
        loop = (0, frames - 1)
    else:
        for i in range(min(int(FADE_IN_S * rate), frames)):
            for c in range(channels):
                body[i * channels + c] *= i / (FADE_IN_S * rate)
        n_out = min(int(FADE_OUT_S * rate), frames)
        for i in range(n_out):
            for c in range(channels):
                body[(frames - 1 - i) * channels + c] *= i / n_out
    # gain from the finished body: the loop crossfade folds the tail into the start and moves the peak
    body_peak = max((abs(s) for s in body), default=0.0)
    if body_peak > 0:
        gain = 10 ** (args.peak / 20) / body_peak
        body = [s * gain for s in body]
    report.update(seconds=round(frames / rate, 3), trimmed_s=round(report["raw_seconds"] - frames / rate, 3))
    return body, channels, loop, report


def score_technical(samples, rate, channels, loop, report, target, is_loop):
    """(score 0..100, reasons). Technical checks only: says nothing about whether it matches the prompt."""
    reasons, score = [], 100.0
    if report["raw_peak_dbfs"] < -45:
        return 0.0, [f"near-silent ({report['raw_peak_dbfs']} dBFS before normalizing)"]
    if report["raw_clipped"]:
        score -= min(40, 5 + report["raw_clipped"] / 20)
        reasons.append(f"{report['raw_clipped']} clipped samples in the raw take")
    mono = samples if channels == 1 else samples[0::channels]
    st = stats(mono, rate, loop)
    crest = st["peak_dbfs"] - st["rms_dbfs"]
    # Upper bound only: square waves (about 0 dB) and sines (3 dB) are legitimate retro sounds, and noise sits
    # near 12 dB, so a low crest says nothing. Above 30 dB the take is a lone spike in near-silence.
    if crest > 30:
        score -= 15
        reasons.append(f"crest factor {crest:.1f} dB (a lone spike in near-silence)")
    if is_loop:
        if not st.get("loop_seam_ok", True):
            score -= 30
            reasons.append(f"audible loop seam (step {st.get('loop_seam_step')})")
    else:
        off = abs(report["seconds"] - target) / max(target, 0.05)
        if off > 0.5:
            score -= min(30, 20 * off)
            reasons.append(f"{report['seconds']} s long against --seconds {target}")
    return round(max(score, 0.0), 1), reasons or ["clean"]


# ---- Commands ------------------------------------------------------------------------
def out_names(out, keep):
    return [out] if keep == 1 else [out.with_name(f"{out.stem}_{n}{out.suffix}") for n in range(1, keep + 1)]


def log_targets(args, files):
    """(root, log path, project-relative names). Called before any GPU time so a bad --root stops early."""
    root = Path(args.root).resolve()
    log_path = root / fetch_asset.ASSET_LOG
    if not log_path.is_file():
        raise ToolError(f"{fetch_asset.ASSET_LOG.as_posix()} not found under {root} (pass --root)")
    rels = []
    for f in files:
        try:
            rels.append((Path.cwd() / f).resolve().relative_to(root).as_posix())
        except ValueError:
            raise ToolError(f"{f} is outside the project {root}; --log is for files that ship in the project")
    return root, log_path, rels


def write_log(args, files, metas):
    root, log_path, rels = log_targets(args, files)
    log_text = log_path.read_text(encoding="utf-8")
    num, fill = fetch_asset.next_asset_id(log_text)
    asset_id = f"A-{num:04d}"
    m = metas[0]
    notes = "; ".join(x for x in [f"prompt: {m['prompt'][:160]}", f"seeds {', '.join(str(x['seed']) for x in metas)}",
                                  f"model {m['checkpoint']}", args.notes or ""] if x)
    row = (f"| {asset_id} | sfx | {', '.join(f'`{r}`' for r in rels)} | ComfyUI (local), Stable Audio 3 {m['model']} | "
           f"generated locally | {fetch_asset.md_cell(LICENSE)} |  | pre-generated | no | {m['date']} | "
           f"{fetch_asset.md_cell(notes)} |")
    evidence = (f"{asset_id}  sfx  generated {m['date']} with tools/audio/wavesmith/local_sfx.py\n"
                f"Model    : {m['checkpoint']} + {TEXT_ENCODER} ({MODEL_SOURCE})\n"
                f"Settings : {json.dumps(SAMPLER)}, seconds {m['request_seconds']}\n"
                f"Prompt   : {m['prompt']}\n"
                f"License  : {LICENSE}\n"
                + "".join(f"File     : {r}  seed {x['seed']}  SHA-256 {x['sha256']}\n" for r, x in zip(rels, metas)))
    log_path.write_bytes(fetch_asset.add_log_row(log_text, row, fill).encode("utf-8"))
    lic_dir = root / fetch_asset.LICENSE_DIR
    lic_dir.mkdir(parents=True, exist_ok=True)
    (lic_dir / f"{asset_id}.txt").write_bytes(evidence.encode("utf-8"))
    print(f"[ OK ] {asset_id} added to {fetch_asset.ASSET_LOG.as_posix()}, evidence in "
          f"{(fetch_asset.LICENSE_DIR / (asset_id + '.txt')).as_posix()}")


def cmd_check(args):
    base = cl.server_url(args)
    print(f"[ OK ] {preflight(base, args.model)}")
    print(f"[ OK ] Stable Audio 3 {args.model} ({MODELS[args.model]['ckpt']}) and {TEXT_ENCODER} are installed")
    return 0


def cmd_make(args):
    if not args.prompt.strip():
        raise ToolError("the prompt is empty: describe the sound")
    if not 0.05 <= args.seconds <= MAX_GEN_S:
        raise ToolError(f"--seconds must be 0.05..{MAX_GEN_S}")
    if args.keep < 1 or args.variants < args.keep:
        raise ToolError("--keep must be 1 or more and no more than --variants")
    if args.variants > MAX_VARIANTS:
        raise ToolError(f"--variants is at most {MAX_VARIANTS} (that many takes is already a long GPU session)")
    if args.loop and args.crossfade <= 0:
        raise ToolError("--loop needs a --crossfade above 0 s")
    if args.rank not in RANKERS:
        raise ToolError(f"--rank {args.rank} is not available (have: {', '.join(RANKERS)})")
    out = Path(args.out)
    if out.suffix.lower() != ".wav":
        raise ToolError("--out must be a .wav path")
    names = out_names(out, args.keep)
    for path in names + [p.with_suffix(".gen.json") for p in names]:
        if path.exists() and not args.overwrite:
            raise ToolError(f"{path} exists (use --overwrite); nothing was rendered")
    if args.log:
        log_targets(args, names)
    seconds = round(max(args.seconds + (args.crossfade + LOOP_MARGIN_S if args.loop else 0), MIN_GEN_S), 2)
    seeds = [args.seed + i for i in range(args.variants)]
    base = cl.server_url(args)
    if args.dry_run:
        print(json.dumps(graph(args.model, args.prompt, seconds, seeds[0]), indent=2, ensure_ascii=False))
        print(f"[dry-run] nothing sent. {args.variants} take(s), seeds {seeds[0]}..{seeds[-1]}, {seconds} s each, "
              f"keeping {args.keep}")
        return 0
    print(f"[....] {preflight(base, args.model)}")
    takes = []
    for seed in seeds:
        try:
            raw, rate, channels, gpu_s = render_take(base, graph(args.model, args.prompt, seconds, seed), args.wait)
            clean, ch, loop, report = post(raw, rate, channels, args)
            score, reasons = score_technical(clean, rate, ch, loop, report, args.seconds, args.loop)
        except cl.JobError as exc:
            if "interrupted" in str(exc) or "left ComfyUI's queue" in str(exc):
                raise
            print(f"[FAIL] seed {seed}: {exc}")
            continue
        takes.append({"seed": seed, "samples": clean, "rate": rate, "channels": ch, "loop": loop,
                      "report": report, "score": score, "reasons": reasons, "gpu_s": gpu_s})
        print(f"[take] seed {seed}: {report['seconds']} s, score {score} ({'; '.join(reasons)}), GPU {gpu_s:.1f} s")
    # clean takes all score 100, so ties go to the take closest to the requested length, then the lower seed
    usable = sorted((t for t in takes if t["score"] > 0),
                    key=lambda t: (-t["score"], abs(t["report"]["seconds"] - args.seconds), t["seed"]))
    if not usable:
        raise cl.JobError("no usable take (all failed or came out silent): try another prompt or more --variants")
    kept = usable[:args.keep]
    date = datetime.date.today().isoformat()
    metas, files = [], []
    for rank, (take, path) in enumerate(zip(kept, names), 1):
        clipped = write_wav(path, take["samples"], take["rate"], loop=take["loop"], channels=take["channels"])
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        meta = {"tool": "local_sfx", "date": date, "model": args.model, "checkpoint": MODELS[args.model]["ckpt"],
                "text_encoder": TEXT_ENCODER, "source": MODEL_SOURCE, "license": LICENSE, "prompt": args.prompt,
                "negative": NEGATIVE, "seed": take["seed"], "request_seconds": args.seconds, "generated_seconds": seconds,
                "sampler": SAMPLER, "loop": bool(take["loop"]), "mono": take["channels"] == 1, "peak_dbfs": args.peak,
                "rank": rank, "of_takes": len(takes), "ranker": args.rank, "score": take["score"],
                "checks": take["reasons"], "post": take["report"], "gpu_seconds": round(take["gpu_s"], 1), "sha256": sha}
        path.with_suffix(".gen.json").write_bytes((json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        metas.append(meta)
        files.append(path)
        print(f"[ OK ] {path.as_posix()}: #{rank}, seed {take['seed']}, {take['report']['seconds']} s, "
              f"score {take['score']}" + (f", {clipped} samples clipped" if clipped else ""))
    print(f"[ OK ] kept {len(kept)} of {len(takes)} take(s), ranked on technical checks only: listen and choose")
    if args.log:
        write_log(args, files, metas)
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        description="Sound effects and ambience loops from a prompt with Stable Audio 3 on your own ComfyUI.",
        epilog="Exit codes: 0 ok, 1 ComfyUI failed or no usable take, 2 usage, server or files missing. "
               "License: " + LICENSE)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", help=f"ComfyUI address (default {cl.DEFAULT_URL}, or {cl.URL_ENV})")
    common.add_argument("--allow-remote", action="store_true", help="allow a ComfyUI that is not on this machine")
    common.add_argument("--model", choices=list(MODELS), default="medium",
                        help="medium (default, best in the K01 bake-off) or small-sfx (second opinion)")
    common.add_argument("--debug", action="store_true", help="print requests and tracebacks")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check", parents=[common], help="is ComfyUI up, with the Stable Audio 3 files installed?")
    mk = sub.add_parser("make", parents=[common], help="render takes for a prompt and keep the best")
    mk.add_argument("prompt", help="what the sound is, in plain words (English works best)")
    mk.add_argument("--seconds", type=float, required=True, help="target length of the finished sound")
    mk.add_argument("--out", required=True, help="output .wav; with --keep N above 1: <name>_1.wav (best) .. _N")
    mk.add_argument("--variants", type=int, default=6, help="takes to render (seeds), default 6")
    mk.add_argument("--keep", type=int, default=3, help="best takes to keep, default 3")
    mk.add_argument("--seed", type=int, default=1, help="first seed (takes use seed, seed+1, ...)")
    mk.add_argument("--loop", action="store_true", help="ambience: trim the tail and crossfade into a seamless loop")
    mk.add_argument("--crossfade", type=float, default=1.0, help="loop crossfade in seconds (default 1)")
    mk.add_argument("--mono", action="store_true", help="mix to mono (positional one-shots)")
    mk.add_argument("--peak", type=float, default=-3.0, help="normalize each take's peak to this dBFS (default -3)")
    mk.add_argument("--rank", default="technical", help=f"how to order takes ({', '.join(RANKERS)})")
    mk.add_argument("--wait", type=int, default=cl.WAIT_S, help=f"seconds to wait per take (default {cl.WAIT_S})")
    mk.add_argument("--dry-run", action="store_true", help="print the graph and plan, send nothing")
    mk.add_argument("--overwrite", action="store_true", help="replace existing outputs")
    mk.add_argument("--log", action="store_true", help="add an ASSET_LOG row and evidence file for the kept files")
    mk.add_argument("--root", default=".", help="project root holding docs/ASSET_LOG.md (with --log)")
    mk.add_argument("--notes", help="extra text for the ASSET_LOG notes (with --log)")
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
    DEBUG = cl.DEBUG = getattr(args, "debug", False)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        return cmd_check(args) if args.cmd == "check" else cmd_make(args)
    except cl.JobError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 1
    except (ToolError, cl.ToolError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

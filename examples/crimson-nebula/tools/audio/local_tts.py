#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# local_tts.py
# Purpose : Spoken lines for your characters on your own GPU (Qwen3-TTS): design a character's voice from a text
#           description once, then voice speech bubbles and barks in that same voice. Free per line, no account.
# Usage   : python tools/audio/local_tts.py check                                 # is the TTS environment ready?
#           python tools/audio/local_tts.py design "warm, cheerful middle-aged baker, slightly husky" \
#               --out assets_src/voice/baker_ref.wav                                # the character's voice, once
#           python tools/audio/local_tts.py say --ref assets_src/voice/baker_ref.wav "Fresh bread, two coins!" \
#               --out assets/audio/voice/baker_bread.wav
#           python tools/audio/local_tts.py say --ref ... --lines docs/dialog/baker.txt --out assets/audio/voice/baker.wav
#           python tools/audio/local_tts.py say --ref golem_ref.wav "Who... disturbs... me" --pitch -5 --ring-hz 40 \
#               --out golem_1.wav                                                    # deeper / metallic than any human voice
# Needs   : Python 3.8+ for this file. The model runs in a separate environment (Python 3.10+, CUDA torch, qwen-tts)
#           named by --python or LOCAL_TTS_PYTHON; setup commands in docs/resources/audio.md. NVIDIA GPU.
# Exit    : 0 ok, 1 the model failed (worker crashed, timed out, bad reply), 2 usage, missing environment, no CUDA
# Notes   : Never clone a real person's voice without their written permission. The documented path designs voices
#           from a text description; a recorded reference needs --ref-origin (self or permission), and every
#           .gen.json records where the voice came from. Models: Qwen3-TTS-12Hz-1.7B-VoiceDesign (design) and
#           -1.7B-Base (say; --model 0.6b for the smaller Base), Apache-2.0, downloaded on first use into the
#           Hugging Face cache (about 4.3 GB each; 0.6B 2.4 GB). Output: mono 16-bit WAV at the model's rate
#           (24 kHz), trimmed, faded and normalized (-3 dBFS peak). About 3x slower than realtime on a 16 GB
#           RTX 5060 Ti: fine for pre-made lines, not for live speech. Bake-off K01 voice round: docs/resources/audio.md.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   env python (--python, LOCAL_TTS_PYTHON) -> start local_tts_worker.py with -I, one JSON request on stdin
#   -> read JSON lines from stdout (timeout per job, stderr kept for errors) -> "ok": false? name torch/qwen_tts/CUDA
#   check:  print versions
#   design: request op design (persona, reference text) -> post-process -> ref WAV + .gen.json (designed from text)
#   say:    reference provenance (its .gen.json, or --ref-text + --ref-origin) -> outputs free? -> request op say
#           (all lines in one job: the model loads once) -> per line: trim -> --pitch / --ring-hz -> fades
#           -> normalize -> WAV + .gen.json -> --log row
import argparse
import datetime
import hashlib
import json
import math
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import fetch_asset  # noqa: E402  (shared ASSET_LOG helpers)
from wavfile import read_wav, stats, write_wav  # noqa: E402

PYTHON_ENV = "LOCAL_TTS_PYTHON"
WORKER = HERE / "local_tts_worker.py"
DESIGN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
CLONE_MODELS = {"1.7b": "Qwen/Qwen3-TTS-12Hz-1.7B-Base", "0.6b": "Qwen/Qwen3-TTS-12Hz-0.6B-Base"}
LICENSE = "Apache-2.0 (Qwen3-TTS model cards, https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base)"
# Neutral and phonetically varied, about 10 s: what a designed voice says so it can be cloned later.
REF_TEXT = ("Good morning. The road north is clear today, and the market is busy. "
            "If you need bread, iron, or a warm place to rest, you will find it here.")
ORIGINS = {"self": "recorded: your own voice", "permission": "recorded: with the speaker's written permission"}
LOAD_TIMEOUT_S = 600          # first run downloads about 4.3 GB of weights
LINE_TIMEOUT_S = 180          # one line; measured about 3x realtime, so a 20 s line takes about a minute
SILENCE_DB = -45.0
LEAD_KEEP_S, TAIL_KEEP_S = 0.03, 0.08
FADE_IN_S, FADE_OUT_S = 0.005, 0.02
DEBUG = False


class ToolError(Exception):
    """Exit 2: something the user can fix (usage, missing environment, no CUDA)."""


class JobError(Exception):
    """Exit 1: the model run failed."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


# ---- The worker ---------------------------------------------------------------------
def env_python(args):
    py = args.python or os.environ.get(PYTHON_ENV, "")
    if not py:
        raise ToolError(f"no TTS environment: pass --python <env python> or set {PYTHON_ENV} "
                        "(setup: docs/resources/audio.md, 'Local voices')")
    if not Path(py).is_file():
        raise ToolError(f"the TTS environment's Python {py} does not exist (check --python / {PYTHON_ENV})")
    return py


def run_worker(args, request, timeout, on_reply=None):
    """Replies (dicts) from one worker job. Raises ToolError for a not-ready environment, JobError otherwise."""
    cmd = [env_python(args), "-I", str(args.worker or WORKER)]
    dbg(f"run {cmd} with {json.dumps(request)[:300]}")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace")
    lines, err_tail = queue.Queue(), []

    def pump_out():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    def pump_err():                                   # drained in a thread so a chatty worker never blocks
        for line in proc.stderr:
            err_tail.append(line.rstrip())
            del err_tail[:-12]
            if DEBUG:
                print(f"[worker] {line.rstrip()}", file=sys.stderr)

    threading.Thread(target=pump_out, daemon=True).start()
    threading.Thread(target=pump_err, daemon=True).start()
    try:
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.close()
    except OSError:
        pass                                          # it died at start; the exit code and stderr tell why
    try:
        return read_replies(proc, lines, err_tail, timeout, on_reply)
    finally:
        if proc.poll() is None:                       # never leave a GPU worker running behind an error
            proc.kill()
            proc.wait()


def read_replies(proc, lines, err_tail, timeout, on_reply):
    replies, deadline = [], time.monotonic() + timeout
    while True:
        try:
            line = lines.get(timeout=max(0.05, deadline - time.monotonic()))
        except queue.Empty:
            raise JobError(f"the TTS worker gave no answer within {timeout:.0f} s and was stopped "
                           "(first run downloads the weights: raise --timeout)")
        if line is None:
            break
        if not line.strip():
            continue
        try:
            reply = json.loads(line)
        except ValueError:
            raise JobError(f"the TTS worker sent something that is not JSON: {line.strip()[:200]!r}")
        if reply.get("ok") is False:
            raise ToolError(not_ready_text(reply))
        if "error" in reply:
            raise JobError(f"the TTS worker failed: {reply['error']}" + stderr_hint(err_tail))
        replies.append(reply)
        if on_reply:
            on_reply(reply)
    code = proc.wait()
    if code != 0:
        raise JobError(f"the TTS worker exited with code {code}" + stderr_hint(err_tail))
    return replies


def not_ready_text(reply):
    fix = {"torch": "install a CUDA build of torch into that environment (uv pip install torch --torch-backend cu130)",
           "qwen_tts": "install qwen-tts into that environment (uv pip install qwen-tts)",
           "cuda": "that torch is a CPU build or sees no NVIDIA GPU: reinstall with --torch-backend <your CUDA>"}
    missing = reply.get("missing", "?")
    return f"the TTS environment is not ready ({missing}): {reply.get('error', '')}. Fix: {fix.get(missing, 'see the docs')}"


def stderr_hint(tail):
    return ("\n  last worker output:\n    " + "\n    ".join(tail[-6:])) if tail else ""


# ---- Post-processing ----------------------------------------------------------------
def post(samples, rate, pitch=0.0, ring_hz=0.0, ring_mix=0.5, peak_db=-3.0):
    """(samples, report): trim silence -> pitch by resampling -> ring modulation -> fades -> normalize."""
    peak = max((abs(s) for s in samples), default=0.0)
    if peak <= 0:
        raise JobError("the model returned silence")
    floor = peak * 10 ** (SILENCE_DB / 20)
    loud = [i for i, s in enumerate(samples) if abs(s) > floor]
    body = samples[max(0, loud[0] - int(LEAD_KEEP_S * rate)):min(len(samples), loud[-1] + 1 + int(TAIL_KEEP_S * rate))]
    if pitch:
        # resampling shifts pitch and formants together and changes the length: a bigger, slower creature when
        # lowered, a smaller, quicker one when raised (what monster voices want; a plain voice keeps --pitch 0)
        step = 2 ** (pitch / 12)
        n = int((len(body) - 1) / step)
        body = [body[int(i * step)] * (1 - (i * step) % 1) + body[min(int(i * step) + 1, len(body) - 1)] * ((i * step) % 1)
                for i in range(n)]
    if ring_hz:
        body = [s * ((1 - ring_mix) + ring_mix * math.sin(2 * math.pi * ring_hz * i / rate)) for i, s in enumerate(body)]
    n_in, n_out = min(int(FADE_IN_S * rate), len(body)), min(int(FADE_OUT_S * rate), len(body))
    for i in range(n_in):
        body[i] *= i / n_in
    for i in range(n_out):
        body[-1 - i] *= i / n_out
    top = max((abs(s) for s in body), default=0.0)
    body = [s / top * 10 ** (peak_db / 20) for s in body] if top else body
    return body, {"seconds": round(len(body) / rate, 3), "raw_seconds": round(len(samples) / rate, 3),
                  "pitch_semitones": pitch, "ring_hz": ring_hz, "ring_mix": ring_mix if ring_hz else 0}


def finish(tmp_wav, out, args, meta):
    """Post-process one worker WAV into `out` with its .gen.json. Returns the meta written."""
    samples, rate, _ = read_wav(tmp_wav)
    body, report = post(samples, rate, getattr(args, "pitch", 0.0), getattr(args, "ring_hz", 0.0),
                        getattr(args, "ring_mix", 0.5))
    out.parent.mkdir(parents=True, exist_ok=True)
    write_wav(out, body, rate)
    meta = dict(meta, rate=rate, post=report, sha256=hashlib.sha256(out.read_bytes()).hexdigest())
    out.with_suffix(".gen.json").write_bytes((json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    st = stats(body, rate)
    print(f"[ OK ] {out.as_posix()}: {st['seconds']} s, peak {st['peak_dbfs']} dBFS")
    return meta


def refuse_existing(paths, overwrite):
    for p in paths:
        for f in (p, p.with_suffix(".gen.json")):
            if f.exists() and not overwrite:
                raise ToolError(f"{f} exists (use --overwrite); nothing was generated")


# ---- Reference provenance -----------------------------------------------------------
def ref_provenance(args):
    """(ref_text, provenance dict) for --ref: from its .gen.json when local_tts designed it, else from the flags."""
    ref = Path(args.ref)
    if not ref.is_file():
        raise ToolError(f"--ref {ref} not found (make one with: local_tts.py design \"<voice description>\" --out ...)")
    side = ref.with_suffix(".gen.json")
    if side.is_file():
        try:
            meta = json.loads(side.read_text(encoding="utf-8"))
        except ValueError:
            raise ToolError(f"{side} is not valid JSON")
        if meta.get("tool") == "local_tts" and meta.get("op") == "design":
            return meta["ref_text"], {"origin": "designed from text", "persona": meta.get("persona"),
                                      "reference": shown_path(ref), "reference_sha256": sha256_file(ref)}
    if not args.ref_text or not args.ref_origin:
        raise ToolError(f"{ref} was not designed by local_tts.py, so say what it is: --ref-text \"<exact words "
                        "spoken in it>\" and --ref-origin self (your own voice) or permission (the speaker gave "
                        "written permission). Never clone a real person's voice without it.")
    return args.ref_text, {"origin": ORIGINS[args.ref_origin], "reference": shown_path(ref),
                           "reference_sha256": sha256_file(ref)}


def shown_path(path):
    """The reference as it may be written into a .gen.json that ships with the game: relative to the project
    (the current folder) when inside it, else the file name only. Never an absolute path (folder names leak);
    the SHA-256 next to it still identifies the file exactly."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.name


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---- ASSET_LOG ----------------------------------------------------------------------
def log_targets(args, files):
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
    voice = m["voice"]
    notes = "; ".join(x for x in [f"voice: {voice['origin']}" + (f" ({voice['persona'][:80]})" if voice.get("persona") else ""),
                                  f"model {m['model']}", args.notes or ""] if x)
    row = (f"| {asset_id} | voice | {', '.join(f'`{r}`' for r in rels)} | Qwen3-TTS (local) | generated locally | "
           f"{fetch_asset.md_cell(LICENSE)} |  | pre-generated | no | {m['date']} | {fetch_asset.md_cell(notes)} |")
    evidence = (f"{asset_id}  voice  generated {m['date']} with tools/audio/local_tts.py\n"
                f"Model    : {m['model']}\nLicense  : {LICENSE}\n"
                f"Voice    : {json.dumps(voice, ensure_ascii=False)}\n"
                + "".join(f"File     : {r}  SHA-256 {x['sha256']}  text: {x['text']}\n" for r, x in zip(rels, metas)))
    log_path.write_bytes(fetch_asset.add_log_row(log_text, row, fill).encode("utf-8"))
    lic_dir = root / fetch_asset.LICENSE_DIR
    lic_dir.mkdir(parents=True, exist_ok=True)
    (lic_dir / f"{asset_id}.txt").write_bytes(evidence.encode("utf-8"))
    print(f"[ OK ] {asset_id} added to {fetch_asset.ASSET_LOG.as_posix()}, evidence in "
          f"{(fetch_asset.LICENSE_DIR / (asset_id + '.txt')).as_posix()}")


# ---- Commands -----------------------------------------------------------------------
def cmd_check(args):
    r = run_worker(args, {"op": "check"}, args.timeout or 120)[0]
    print(f"[ OK ] TTS environment ready: Python {r.get('python')}, torch {r['torch']} (CUDA {r['cuda']}), "
          f"qwen-tts {r['qwen_tts']}, GPU {r['gpu']}")
    return 0


def cmd_design(args):
    if not args.persona.strip():
        raise ToolError("describe the voice, e.g. \"gruff older blacksmith, deep gravelly voice, slow speech\"")
    out = Path(args.out)
    refuse_existing([out], args.overwrite)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_wav = str(Path(tmp) / "ref.wav")
        req = {"op": "design", "model": DESIGN_MODEL, "persona": args.persona, "text": REF_TEXT,
               "language": args.language, "seed": args.seed, "out": tmp_wav}
        rep = run_worker(args, req, args.timeout or LOAD_TIMEOUT_S + LINE_TIMEOUT_S)
        if not rep:
            raise JobError("the TTS worker finished without an answer")
        meta = {"tool": "local_tts", "op": "design", "date": datetime.date.today().isoformat(), "model": DESIGN_MODEL,
                "license": LICENSE, "persona": args.persona, "ref_text": REF_TEXT, "seed": args.seed,
                "language": args.language, "voice": {"origin": "designed from text", "persona": args.persona}}
        finish(tmp_wav, out, args, meta)
    print("[note] listen to it; if the voice is wrong, run design again with another --seed or a clearer description")
    return 0


def cmd_say(args):
    if bool(args.text) == bool(args.lines):
        raise ToolError("give the text or --lines FILE (one of them)")
    if args.lines:
        try:
            texts = [l.strip() for l in Path(args.lines).read_text(encoding="utf-8").splitlines() if l.strip()]
        except OSError as exc:
            raise ToolError(f"cannot read --lines: {exc}")
        if not texts:
            raise ToolError(f"{args.lines} has no lines")
    else:
        texts = [args.text]
    out = Path(args.out)
    outs = [out] if len(texts) == 1 and not args.lines else [out.with_name(f"{out.stem}_{n}{out.suffix}")
                                                             for n in range(1, len(texts) + 1)]
    ref_text, voice = ref_provenance(args)
    refuse_existing(outs, args.overwrite)
    if args.log:
        log_targets(args, outs)
    model = CLONE_MODELS[args.model]
    timeout = args.timeout or LOAD_TIMEOUT_S + LINE_TIMEOUT_S * len(texts)
    date = datetime.date.today().isoformat()
    metas = []
    with tempfile.TemporaryDirectory() as tmp:
        req = {"op": "say", "model": model, "ref": str(Path(args.ref).resolve()), "ref_text": ref_text,
               "language": args.language, "seed": args.seed, "outdir": tmp,
               "lines": [{"id": f"line{n}", "text": t} for n, t in enumerate(texts, 1)]}
        index = {f"line{n}": (t, o) for n, (t, o) in enumerate(zip(texts, outs), 1)}

        def done(reply):
            if "id" not in reply:
                return
            if reply["id"] not in index:
                raise JobError(f"the TTS worker answered for an unknown line {reply['id']!r}")
            text, target = index[reply["id"]]
            meta = {"tool": "local_tts", "op": "say", "date": date, "model": model, "license": LICENSE, "text": text,
                    "seed": args.seed + int(reply["id"][4:]) - 1, "language": args.language, "voice": voice,
                    "gpu_seconds": reply.get("wall")}
            metas.append(finish(reply["file"], target, args, meta))

        replies = run_worker(args, req, timeout, done)
    if not any(r.get("done") for r in replies) or len(metas) != len(texts):
        raise JobError(f"the TTS worker stopped early: {len(metas)} of {len(texts)} line(s) came back")
    print(f"[ OK ] {len(metas)} line(s) in the voice from {Path(args.ref).name} ({voice['origin']})")
    if args.log:
        write_log(args, outs, metas)
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        description="Character voices on your own GPU with Qwen3-TTS: design a voice from a description, then voice "
                    "lines in it. Never clone a real person's voice without their written permission.",
        epilog="Exit codes: 0 ok, 1 the model run failed, 2 usage or environment not ready. License: " + LICENSE)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--python", help=f"the TTS environment's python (default: ${PYTHON_ENV})")
    common.add_argument("--worker", help=argparse.SUPPRESS)          # tests point this at a stand-in worker
    common.add_argument("--timeout", type=float, help="seconds before a job is stopped (default: generous per line)")
    common.add_argument("--debug", action="store_true", help="show the worker's log and tracebacks")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check", parents=[common], help="is the TTS environment ready (torch, CUDA, qwen-tts)?")
    out_opts = argparse.ArgumentParser(add_help=False)
    out_opts.add_argument("--out", required=True, help="output .wav")
    out_opts.add_argument("--seed", type=int, default=1, help="sampling seed (another seed, another take)")
    out_opts.add_argument("--language", default="English", help="spoken language (default English)")
    out_opts.add_argument("--overwrite", action="store_true", help="replace existing outputs")
    ds = sub.add_parser("design", parents=[common, out_opts], help="make a character's reference voice from a description")
    ds.add_argument("persona", help="the voice in plain words: age, character, pitch, pace, accent")
    sy = sub.add_parser("say", parents=[common, out_opts], help="voice lines in a reference's voice")
    sy.add_argument("text", nargs="?", help="the line to speak (or --lines)")
    sy.add_argument("--lines", help="text file, one line per row: <out>_1.wav, <out>_2.wav ...")
    sy.add_argument("--ref", required=True, help="the voice reference WAV (from design, or a recording, see --ref-origin)")
    sy.add_argument("--ref-text", help="exact words spoken in a recorded --ref (designed references carry their own)")
    sy.add_argument("--ref-origin", choices=list(ORIGINS), help="a recorded --ref: self (your voice) or permission "
                                                                "(the speaker's written permission)")
    sy.add_argument("--model", choices=list(CLONE_MODELS), default="1.7b", help="Base model size (default 1.7b)")
    sy.add_argument("--pitch", type=float, default=0.0, help="semitones, by resampling (also changes length); "
                                                             "-5 for a giant, +5 for a small creature")
    sy.add_argument("--ring-hz", type=float, default=0.0, help="ring modulation frequency: 30-60 for metal, robots")
    sy.add_argument("--ring-mix", type=float, default=0.5, help="ring modulation amount 0..1 (default 0.5)")
    sy.add_argument("--log", action="store_true", help="add an ASSET_LOG row and evidence file")
    sy.add_argument("--root", default=".", help="project root holding docs/ASSET_LOG.md (with --log)")
    sy.add_argument("--notes", help="extra text for the ASSET_LOG notes (with --log)")
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
    DEBUG = getattr(args, "debug", False)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        if args.cmd == "say" and not 0 <= args.ring_mix <= 1:
            raise ToolError("--ring-mix must be 0..1")
        if args.cmd == "say" and not -12 <= args.pitch <= 12:
            raise ToolError("--pitch must be -12..12 semitones")
        return {"check": cmd_check, "design": cmd_design, "say": cmd_say}[args.cmd](args)
    except JobError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 1
    except ToolError as exc:
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

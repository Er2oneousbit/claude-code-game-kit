#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# local_tts_worker.py
# Purpose : The GPU half of local_tts.py. It runs inside a separate Python environment that has torch and qwen-tts,
#           so the kit's own tools stay standard-library only. local_tts.py starts it, sends one JSON request on
#           stdin, and reads JSON lines back from stdout.
# Usage   : not called by hand. local_tts.py runs: <env python> -I local_tts_worker.py  (request on stdin)
#           Requests: {"op": "check"}
#                     {"op": "design", "model", "persona", "text", "language", "seed", "out"}
#                     {"op": "say", "model", "ref", "ref_text", "language", "seed", "outdir", "lines": [{"id", "text"}]}
#           Replies (one JSON object per line): check -> {"ok", "torch", "cuda", "gpu", "qwen_tts"} or
#           {"ok": false, "missing", "error"}; design -> {"file", "seconds", "wall"}; say -> one {"id", "file",
#           "seconds", "wall"} per line, then {"done": true}; any failure -> {"error"} and exit 1.
# Needs   : The TTS environment: Python 3.10+, a CUDA build of torch, qwen-tts (setup in docs/resources/audio.md).
#           This file itself sticks to Python 3.8 syntax so the kit's syntax check passes everywhere.
# Notes   : stdout carries the protocol only; every log line, and anything a library prints, goes to stderr. Weights download on first use into the
#           Hugging Face cache (HF_HOME, default ~/.cache/huggingface): VoiceDesign 1.7B and Base 1.7B, about
#           4.3 GB each, Apache-2.0. WAVs are written with the stdlib wave module (16-bit mono).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   move stray stdout writes to stderr (fd level) -> read one JSON request
#   check (design and say run it first): import torch / qwen_tts, CUDA? -> versions, or which part is missing
#   design: load VoiceDesign -> seed -> generate the reference text in the described voice -> WAV
#   say:    load Base -> clone prompt from the reference once -> per line: seed -> generate -> WAV -> reply line
import json
import os
import sys
import time
import wave

PROTO = None   # the real stdout, kept for JSON replies only (see protocol_stream)


def protocol_stream():
    """The real stdout for the replies. Everything else that writes to stdout goes to stderr instead, at the
    file-descriptor level so native code is covered too: qwen-tts prints a flash-attn banner to stdout when it is
    imported, which would otherwise break the JSON-lines protocol (found in the live check, 2026-10-31)."""
    sys.stdout.flush()
    fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return os.fdopen(fd, "w", encoding="utf-8", newline="\n")


def reply(obj):
    PROTO.write(json.dumps(obj) + "\n")
    PROTO.flush()


def log(msg):
    sys.stderr.write("[worker] " + msg + "\n")
    sys.stderr.flush()


def write_wav(path, samples, rate):
    """Float samples (-1..1, any iterable) to a 16-bit mono WAV, clipped."""
    frames = bytearray()
    for s in samples:
        v = int(round(max(-1.0, min(1.0, float(s))) * 32767))
        frames += v.to_bytes(2, "little", signed=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(bytes(frames))
    return len(frames) // 2 / float(rate)


def op_check():
    try:
        import torch
    except Exception as exc:                       # broad on purpose: a broken torch install raises many kinds
        return {"ok": False, "missing": "torch", "error": "cannot import torch: {}".format(exc)}
    try:
        import qwen_tts
    except Exception as exc:
        return {"ok": False, "missing": "qwen_tts", "error": "cannot import qwen_tts: {}".format(exc),
                "torch": torch.__version__}
    try:
        from importlib.metadata import version
        qv = version("qwen-tts")
    except Exception:                              # an editable or vendored install has no dist-info
        qv = getattr(qwen_tts, "__version__", "unknown")
    if not torch.cuda.is_available():
        return {"ok": False, "missing": "cuda", "torch": torch.__version__, "qwen_tts": qv,
                "error": "torch {} sees no CUDA GPU (a CPU build, or the driver is missing)".format(torch.__version__)}
    return {"ok": True, "torch": torch.__version__, "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0),
            "qwen_tts": qv, "python": sys.version.split()[0]}


def load(model_id):
    import torch
    from qwen_tts import Qwen3TTSModel
    t = time.time()
    m = Qwen3TTSModel.from_pretrained(model_id, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")
    log("loaded {} in {:.1f}s".format(model_id, time.time() - t))
    return m


def seed_all(seed):
    import torch
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def op_design(req):
    m = load(req["model"])
    seed_all(req["seed"])
    t = time.time()
    wavs, rate = m.generate_voice_design(text=req["text"], instruct=req["persona"], language=req["language"])
    seconds = write_wav(req["out"], wavs[0], rate)
    reply({"file": req["out"], "seconds": round(seconds, 3), "wall": round(time.time() - t, 2)})


def op_say(req):
    m = load(req["model"])
    prompt = m.create_voice_clone_prompt(ref_audio=req["ref"], ref_text=req["ref_text"])   # embed the voice once
    for i, line in enumerate(req["lines"]):
        seed_all(req["seed"] + i)
        t = time.time()
        cap = {"max_new_tokens": line["max_tokens"]} if line.get("max_tokens") else {}   # stop a take that never ends
        wavs, rate = m.generate_voice_clone(text=line["text"], language=req["language"], voice_clone_prompt=prompt, **cap)
        path = "{}/{}.wav".format(req["outdir"], line["id"])
        seconds = write_wav(path, wavs[0], rate)
        reply({"id": line["id"], "file": path, "seconds": round(seconds, 3), "wall": round(time.time() - t, 2)})
    reply({"done": True})


def main():
    global PROTO
    PROTO = protocol_stream()
    try:
        req = json.loads(sys.stdin.read())
        op = req.get("op")
        if op == "check":
            reply(op_check())
        elif op in ("design", "say"):
            ready = op_check()                     # a missing torch / qwen_tts / CUDA is named, not a crash
            if not ready["ok"]:
                reply(ready)
                return 2
            (op_design if op == "design" else op_say)(req)
        else:
            reply({"error": "unknown op {!r}".format(op)})
            return 1
        return 0
    except Exception as exc:
        log("failed: {}: {}".format(type(exc).__name__, exc))
        reply({"error": "{}: {}".format(type(exc).__name__, exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())

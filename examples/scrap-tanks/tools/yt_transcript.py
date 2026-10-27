#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# yt_transcript.py
# Purpose : Get a text transcript of a YouTube video so Claude can read it
#           (research videos, tutorials, dev logs) and record it in docs/EVIDENCE.md (+ docs/evidence/video-notes.md).
# Usage   : python tools/yt_transcript.py <url-or-id> [--out FILE] [--lang en] [--whisper] [--device cpu|cuda]
#                                         [--model small] [--debug]
#           A bare id that starts with "-" needs "--" first:  python tools/yt_transcript.py -- -AbCdEfGhIj
# Method  : tries in order (stops at first success)
#             1. youtube-transcript-api   (pip install youtube-transcript-api)
#             2. yt-dlp subtitles         (pip install yt-dlp)  [manual or auto captions]
#             3. --whisper: yt-dlp audio + faster-whisper speech-to-text, for videos with no captions
#                (pip install yt-dlp faster-whisper "av<19"; PyAV 19 breaks faster-whisper 1.2.x audio decoding).
#                No system ffmpeg needed: the audio is downloaded as-is and decoded by PyAV.
# Exit    : 0 ok, 1 no transcript for this video, 2 usage/environment problem (missing library, bad input)
# Notes   : The first --whisper run downloads the model (~0.5 GB for "small") into the Hugging Face cache
#           (%USERPROFILE%\.cache\huggingface or $HF_HOME). It runs on the CPU by default: --device cuda needs
#           the CUDA 12 cuBLAS and cuDNN 9 libraries, which a normal NVIDIA driver install does not include,
#           so a failed CUDA run falls back to the CPU. Only use on videos you may view, and respect the
#           creator's terms: transcripts here are for personal research notes. Run it on a PC or a server.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-21 with Claude (Opus 5.5, claude-opus-5-5): UTF-8 output; --out creates its folder.
#           Audit pass 7: CPU by default (CUDA crashed on NVIDIA PCs without cuBLAS), no ffmpeg, av<19,
#           exit 2 when no method is installed, real failure reasons, entities and whitespace cleaned,
#           regional --lang codes, stricter URL parsing, --model
# ---------------------------------------------------------------------------
import argparse
import html
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

WHISPER_MODELS = ("tiny", "base", "small", "medium")    # bigger = slower and more accurate
YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")

DEBUG = False


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def flat(text):
    """One line of plain text: entities decoded, line breaks and runs of spaces collapsed."""
    return " ".join(html.unescape(text).split())


def video_id(s):
    """Accept a YouTube URL (watch?v=, youtu.be, shorts, embed, live) or a bare 11-char id; else None."""
    if "://" in s or s.startswith(("www.", "youtu")):
        host = re.sub(r"^[a-z]+://", "", s.lower()).split("/")[0]
        if not any(host == h or host.endswith("." + h) for h in YOUTUBE_HOSTS):
            return None
        m = re.search(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", s)
        return m.group(1) if m else None
    return s if re.fullmatch(r"[A-Za-z0-9_-]{11}", s) else None


def have(module):
    return importlib.util.find_spec(module) is not None


def via_transcript_api(vid, lang):
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        # Newer versions use an instance + fetch(); older ones use get_transcript(). Try both.
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            parts = YouTubeTranscriptApi.get_transcript(vid, languages=[lang])
            return flat(" ".join(p["text"] for p in parts)), None
        parts = YouTubeTranscriptApi().fetch(vid, languages=[lang])
        return flat(" ".join(getattr(p, "text", None) or p["text"] for p in parts)), None
    except Exception as exc:  # captions disabled, blocked IP, no such language...
        return None, f"youtube-transcript-api: {str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__}"


def last_error(stderr):
    """yt-dlp's last ERROR line (the real reason: video unavailable, sign-in needed, ...)."""
    errs = [l.strip() for l in (stderr or "").splitlines() if "ERROR" in l]
    return errs[-1] if errs else (stderr or "").strip()[-200:]


def via_ytdlp_subs(vid, lang, tmp):
    cmd = [sys.executable, "-m", "yt_dlp", "--skip-download", "--write-subs", "--write-auto-subs",
           "--sub-langs", lang, "--sub-format", "vtt", "-o", str(tmp / "%(id)s.%(ext)s"),
           f"https://www.youtube.com/watch?v={vid}"]
    dbg(" ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    files = list(tmp.glob("*.vtt"))
    if not files:
        return None, f"yt-dlp subtitles: {last_error(r.stderr) or f'no {lang} captions'}"
    lines, last = [], ""
    for ln in files[0].read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = re.sub(r"<[^>]+>", "", ln).strip()          # drop inline timing tags
        if not ln or "-->" in ln or ln.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        ln = html.unescape(ln)                            # VTT escapes & and <; auto captions write ">>" speaker marks
        ln = re.sub(r"^>>\s*", "", ln)
        if ln and ln != last:                             # auto-captions repeat lines
            lines.append(ln)
            last = ln
    return flat(" ".join(lines)), None


def whisper_lang(lang):
    """faster-whisper wants base codes: en-US -> en, pt-BR -> pt, zh-Hans -> zh."""
    return lang.split("-")[0].split("_")[0].lower()


def via_whisper(vid, lang, tmp, device, model_name):
    # bestaudio as-is (webm/m4a): PyAV inside faster-whisper decodes it, so no system ffmpeg is needed
    cmd = [sys.executable, "-m", "yt_dlp", "-f", "bestaudio", "-o", str(tmp / "audio.%(ext)s"),
           f"https://www.youtube.com/watch?v={vid}"]
    dbg(" ".join(cmd))
    # Progress goes to stderr under --debug, never to stdout (stdout is the transcript)
    r = subprocess.run(cmd, stdout=sys.stderr if DEBUG else subprocess.PIPE, stderr=None if DEBUG else subprocess.PIPE,
                       text=True, encoding="utf-8", errors="replace")
    audio = next(iter(tmp.glob("audio.*")), None)
    if r.returncode != 0 or not audio:
        return None, f"yt-dlp audio download: {last_error(r.stderr) if not DEBUG else 'see the log above'}"
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")   # Windows without Developer Mode
    from faster_whisper import WhisperModel
    for dev in ([device, "cpu"] if device != "cpu" else ["cpu"]):
        try:
            print(f"[info] transcribing with faster-whisper {model_name} on {dev} (first run downloads the model)",
                  file=sys.stderr)
            model = WhisperModel(model_name, device=dev, compute_type="int8")
            segs, _ = model.transcribe(str(audio), language=whisper_lang(lang))
            return flat(" ".join(s.text for s in segs)), None
        except Exception as exc:
            msg = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            if "metadata_errors" in msg:
                return None, 'faster-whisper cannot decode with PyAV 19: pip install "av<19"'
            if dev != "cpu":
                print(f"[warn] {dev} failed ({msg}); retrying on the CPU", file=sys.stderr)
                continue
            return None, f"faster-whisper: {msg}"
    return None, "faster-whisper: no device worked"


def main(argv=None):
    global DEBUG
    ap = argparse.ArgumentParser(
        description="Fetch a YouTube transcript as plain text (captions first, optional local speech-to-text).",
        epilog='A video id starting with "-" needs "--" before it. Exit: 0 ok, 1 no transcript, 2 environment/usage.')
    ap.add_argument("video", help="YouTube URL (watch, youtu.be, shorts, embed, live) or 11-character video id")
    ap.add_argument("--out", help="write to this file (default: print to stdout)")
    ap.add_argument("--lang", default="en", help="caption language code, e.g. en or en-US (default en)")
    ap.add_argument("--whisper", action="store_true", help="if no captions exist, download audio and transcribe locally")
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda", "auto"],
                    help="where --whisper runs (default cpu; cuda needs CUDA 12 cuBLAS + cuDNN 9, falls back to cpu)")
    ap.add_argument("--model", default="small", choices=WHISPER_MODELS, help="--whisper model size (default small, ~0.5 GB)")
    ap.add_argument("--debug", action="store_true", help="show why each method failed")
    args = ap.parse_args(argv)
    DEBUG = args.debug
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # captions hold ♪, emoji, any script
        except (AttributeError, ValueError):
            pass

    vid = video_id(args.video)
    if not vid:
        print("[error] not a YouTube URL or 11-character video id (an id starting with '-' needs '--' before it)",
              file=sys.stderr)
        return 2

    methods = []
    if have("youtube_transcript_api"):
        methods.append(("captions api", lambda tmp: via_transcript_api(vid, args.lang)))
    if have("yt_dlp"):
        methods.append(("yt-dlp subtitles", lambda tmp: via_ytdlp_subs(vid, args.lang, tmp)))
    if args.whisper:
        if not (have("faster_whisper") and have("yt_dlp")):
            print('[error] --whisper needs: pip install yt-dlp faster-whisper "av<19"', file=sys.stderr)
            return 2
        methods.append(("whisper", lambda tmp: via_whisper(vid, args.lang, tmp, args.device, args.model)))
    if not methods:
        print("[error] no transcript method installed: pip install youtube-transcript-api yt-dlp", file=sys.stderr)
        return 2

    text, reasons = None, []
    with tempfile.TemporaryDirectory() as d:
        for name, method in methods:
            dbg(f"trying {name}")
            text, why = method(Path(d))
            if text:
                break
            reasons.append(why)
            dbg(why)
    if not text:
        for why in reasons:
            print(f"[FAIL] {why}", file=sys.stderr)
        gone = any(w in (why or "").lower() for why in reasons for w in ("unavailable", "private", "removed", "sign in"))
        if not args.whisper and not gone:
            print("[info] no captions found; --whisper transcribes the audio locally instead", file=sys.stderr)
        return 1
    if args.out:
        try:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"[error] cannot write {args.out}: {exc.strerror or exc}", file=sys.stderr)
            return 2
        print(f"[ OK ] {len(text.split())} words -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

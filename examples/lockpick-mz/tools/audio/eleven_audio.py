#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# eleven_audio.py
# Purpose : Generate sound effects and music with the ElevenLabs API, save them in the project, and
#           (with --log) add the ASSET_LOG row and evidence file: prompt, model, date, your plan and
#           what that plan lets you do with the result. Opt-in: needs your own account and API key.
# Usage   : python tools/audio/eleven_audio.py check                       # key works? which plan?
#           python tools/audio/eleven_audio.py sfx --text "wooden door creaks open" --seconds 2 \
#               --out assets/audio/sfx/door.mp3 --log
#           python tools/audio/eleven_audio.py sfx --text "..." --variants 3 --out build/audition/door.mp3
#           python tools/audio/eleven_audio.py music --prompt "slow eerie graveyard music box, instrumental" \
#               --seconds 60 --instrumental --out assets/audio/music/night.wav --loop-crossfade 2 --log
#           python tools/audio/eleven_audio.py music --prompt "..." --out x.mp3 --dry-run   # show, send nothing
# Needs   : Python 3.8+ only. An ElevenLabs account and an API key in the ELEVENLABS_API_KEY environment
#           variable (on Windows a user variable set in Settings works without restarting the terminal).
# Exit    : 0 ok, 1 the service failed (try again later), 2 usage, key, plan or quota problem
# Notes   : Every request spends credits from your plan. --dry-run prints the request and sends nothing.
#           Use a dedicated API key restricted to "Sound Effects" and "Music" (plus "User" read for
#           `check`) with a credit limit, so a leaked key cannot do much. The key is never printed or saved.
#           Licensing depends on YOUR plan (as of 2026-10, verify on elevenlabs.io): paid plans include a
#           commercial license; free plans are non-commercial and need attribution, so --log marks those
#           files PLACEHOLDER (replace them before release, SOP-04). The music API needs a paid plan
#           (a free key gets HTTP 402, seen 2026-10-22).
#           .mp3 output works everywhere. .wav output asks for raw PCM and wraps it; only WAV can take
#           --loop-crossfade, which blends the end into the start and writes loop points (seamless loops
#           in Godot and Unity). 44.1 kHz PCM needs a Pro plan or above: --format pcm_24000 otherwise.
#           Results are not repeatable: keep the file, the .gen.json next to it records how it was made.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   parse command -> dry run? print request, stop
#   key from the environment (Windows: also the saved user variable) -> plan from /v1/user/subscription
#   -> POST /v1/sound-generation or /v1/music -> save (mp3 as is; pcm -> WAV, optional crossfade loop)
#   -> <out>.gen.json (prompt, model, date, plan, license, SHA-256) -> --log: ASSET_LOG row + evidence file
import argparse
import datetime
import hashlib
import json
import os
import re
import struct
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from wavfile import crossfade_loop, write_wav  # noqa: E402
import fetch_asset  # noqa: E402  (shared ASSET_LOG helpers)

API = "https://api.elevenlabs.io"
KEY_ENV = "ELEVENLABS_API_KEY"
TIMEOUT_S = 300                       # long music takes a while
SFX_MODEL = "eleven_text_to_sound_v2"
MUSIC_MODEL = "music_v1"
FORMAT_BY_SUFFIX = {".mp3": "mp3_44100_128", ".wav": "pcm_44100"}
FORMAT_SHAPE = {".mp3": re.compile(r"^mp3_\d{4,5}_\d{2,3}$"), ".wav": re.compile(r"^pcm_\d{4,5}$")}
PCM_CHANNELS = 2                      # measured 2026-10-22: the API's pcm_* is 16-bit little-endian stereo, interleaved
# Free plan: published content must carry "elevenlabs.io" or "11.ai" in its title; Eleven Music is credited by name.
# This one line satisfies both (TERMS_URL, read 2026-10-25).
FREE_ATTRIBUTION = "Created in collaboration with ElevenLabs (elevenlabs.io)"
TERMS_URL = "https://elevenlabs.io/docs/help-center/legal/can-i-publish-the-content-i-generate-on-the-platform"
USER_AGENT = "claude-code-game-kit eleven_audio.py"
DEBUG = False


class ToolError(Exception):
    """Exit 2: something the user can fix (usage, key, plan, quota)."""


class ServiceError(Exception):
    """Exit 1: the service failed; trying again later may work."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def get_key():
    """The API key, or None. On Windows a user variable saved after this terminal opened is read too."""
    key = os.environ.get(KEY_ENV, "").strip()
    if key or os.name != "nt":
        return key or None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, KEY_ENV)[0]).strip() or None
    except OSError:
        return None


def http(method, url, key, body=None):
    """(status, headers, bytes). Network errors raise ToolError. Kept small so the exam can replace it."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"xi-api-key": key, "Content-Type": "application/json",
                                          "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read() or b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ToolError(f"could not reach {API} ({getattr(exc, 'reason', exc)})")


def error_detail(raw):
    """The service's own error message from a JSON error body, without anything sensitive."""
    try:
        detail = json.loads(raw.decode("utf-8", "replace")).get("detail", raw[:300].decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        return raw[:300].decode("utf-8", "replace")
    if isinstance(detail, list):
        return "; ".join(f"{'.'.join(str(x) for x in d.get('loc', []))}: {d.get('msg', '')}" for d in detail)
    if isinstance(detail, dict):
        return detail.get("message") or detail.get("status") or json.dumps(detail)[:300]
    return str(detail)


def call(method, path, key, body=None, query=None):
    url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
    dbg(f"{method} {url}")
    status, headers, raw = http(method, url, key, body)
    if status == 200:
        return headers, raw
    detail = error_detail(raw)
    if status == 401:
        raise ToolError(f"the API key was rejected ({detail}). Check {KEY_ENV}, and that the key has the permission "
                        "for this request")
    if status == 402:   # seen 2026-10-22: "Music API is not available for free users"
        raise ToolError(f"your ElevenLabs plan does not include this, or its credits are used up: {detail}")
    if status == 429:
        raise ToolError(f"ElevenLabs refused for rate limit or quota ({detail}); wait, or check your plan's credits")
    if status in (400, 403, 404, 422):
        raise ToolError(f"ElevenLabs rejected the request ({status}): {detail}")
    raise ServiceError(f"ElevenLabs failed ({status}): {detail}; try again later")


def plan_info(key):
    """dict with tier, status, used, limit, reset; or None when the key may not read the account."""
    try:
        _, raw = call("GET", "/v1/user/subscription", key)
    except ToolError as exc:
        dbg(f"subscription: {exc}")
        return None
    s = json.loads(raw.decode("utf-8", "replace"))
    reset = s.get("next_character_count_reset_unix")
    return {"tier": s.get("tier"), "status": s.get("status"), "used": s.get("character_count"),
            "limit": s.get("character_limit"),
            "reset": datetime.datetime.fromtimestamp(reset).strftime("%Y-%m-%d %H:%M") if reset else None}


def license_for(plan_arg, info):
    """(paid?, license text, attribution, placeholder?) or raise when nothing tells us the plan."""
    if plan_arg == "auto":
        if not info:
            raise ToolError("could not read your plan (the key may lack the User read permission). "
                            "Pass --plan paid or --plan free")
        free = str(info.get("tier", "")).lower() == "free" or str(info.get("status", "")).lower().startswith("free")
        plan_arg = "free" if free else "paid"
    if plan_arg == "paid":
        return True, "ElevenLabs paid plan: commercial use allowed (per plan terms)", "", False
    return False, "ElevenLabs free plan: non-commercial only", FREE_ATTRIBUTION, True


def build_request(kind, args):
    """(path, body, query) for a sfx or music request."""
    suffix = Path(args.out).suffix.lower()
    if suffix not in FORMAT_BY_SUFFIX:
        raise ToolError(f"--out must end in {' or '.join(FORMAT_BY_SUFFIX)}")
    fmt = args.format or FORMAT_BY_SUFFIX[suffix]
    # the format must match the file type, and be well formed, before anything is sent (Kimi's audit: a typo spent
    # credits and then failed, and pcm into .mp3 wrote a WAV under an .mp3 name)
    if not FORMAT_SHAPE[suffix].match(fmt):
        raise ToolError(f"--format {fmt!r} does not fit a {suffix} file: use "
                        + ("mp3_<rate>_<kbps>, e.g. mp3_44100_128" if suffix == ".mp3" else "pcm_<rate>, e.g. pcm_24000"))
    # checked before sending, so a usage mistake never costs credits
    if not fmt.startswith("pcm_") and (args.mono or getattr(args, "loop_crossfade", None)):
        raise ToolError("--mono and --loop-crossfade need a .wav --out (MP3 is saved as the service sends it, "
                        "and its padding at the ends stops a clean loop)")
    if kind == "sfx":
        if not args.text:
            raise ToolError("sfx needs --text, a description of the sound")
        body = {"text": args.text, "model_id": args.model or SFX_MODEL, "prompt_influence": args.influence}
        if args.seconds is not None:
            if not 0.5 <= args.seconds <= 30:
                raise ToolError("--seconds must be 0.5..30 for sound effects")
            body["duration_seconds"] = args.seconds
        if args.loop:
            body["loop"] = True
        return "/v1/sound-generation", body, {"output_format": fmt}
    if not args.prompt:
        raise ToolError("music needs --prompt, a description of the music")
    body = {"prompt": args.prompt, "model_id": args.model or MUSIC_MODEL}
    if args.seconds is not None:
        if not 3 <= args.seconds <= 600:
            raise ToolError("--seconds must be 3..600 for music")
        body["music_length_ms"] = int(args.seconds * 1000)
    if args.instrumental:
        body["force_instrumental"] = True
    return "/v1/music", body, {"output_format": fmt}


def pcm_to_samples(raw):
    n = len(raw) // 2
    return [v / 32768.0 for v in struct.unpack(f"<{n}h", raw[:n * 2])]


def to_mono(samples, channels):
    if channels == 1:
        return samples
    return [sum(samples[i:i + channels]) / channels for i in range(0, len(samples) - channels + 1, channels)]


def save(raw, out, fmt, crossfade, mono=False):
    """Write the audio; returns a short description."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt.startswith("pcm_"):
        rate = int(fmt.split("_")[1])
        samples, channels = pcm_to_samples(raw), PCM_CHANNELS
        if mono:
            samples, channels = to_mono(samples, channels), 1
        loop = None
        if crossfade:
            try:
                samples = crossfade_loop(samples, rate, crossfade, channels)
            except ValueError as exc:
                raise ToolError(f"--loop-crossfade: {exc}")
            loop = (0, len(samples) // channels - 1)
        write_wav(out, samples, rate, loop, channels)
        return (f"{len(samples) / channels / rate:.2f} s {'mono' if channels == 1 else 'stereo'} WAV at {rate} Hz"
                + (", loops" if loop else ""))
    if mono:
        raise ToolError("--mono needs a .wav --out (MP3 is saved as the service sends it)")
    out.write_bytes(raw)
    return f"{len(raw) // 1024} KB {fmt.split('_')[0].upper()}"


def outputs(args):
    out = Path(args.out)
    if getattr(args, "variants", 0) and args.variants > 1:
        return [out.with_name(f"{out.stem}_{i}{out.suffix}") for i in range(1, args.variants + 1)]
    return [out]


def write_log(args, kind, files, meta, lic):
    """ASSET_LOG row + docs/licenses/A-NNNN.txt evidence, using fetch_asset's helpers."""
    root = Path(args.root).resolve()
    log_path = root / fetch_asset.ASSET_LOG
    if not log_path.is_file():
        raise ToolError(f"{fetch_asset.ASSET_LOG.as_posix()} not found under {root} (pass --root)")
    log_text = log_path.read_text(encoding="utf-8")
    num, fill = fetch_asset.next_asset_id(log_text)
    asset_id = f"A-{num:04d}"
    paid, license_text, attribution, placeholder = lic
    rels = []
    for f in files:
        try:
            rels.append(f"`{f.resolve().relative_to(root).as_posix()}`")
        except ValueError:
            raise ToolError(f"{f} is outside the project {root}; --log is for files that ship in the project")
    what = meta["text"] if kind == "sfx" else meta["prompt"]
    notes = "; ".join(x for x in ["PLACEHOLDER" if placeholder else "",
                                  f"prompt: {what}", f"model {meta['model_id']}", args.notes or ""] if x)
    row = (f"| {asset_id} | {kind if kind == 'sfx' else 'music'} | {', '.join(rels)} | "
           f"ElevenLabs API ({meta['endpoint']}) | ElevenLabs (generated) | {fetch_asset.md_cell(license_text)} | "
           f"{attribution} | pre-generated | no | {meta['date']} | {fetch_asset.md_cell(notes)} |")
    evidence = (f"{asset_id}  {kind}  generated {meta['date']} with tools/audio/eleven_audio.py\n"
                f"Service  : ElevenLabs {meta['endpoint']}, model {meta['model_id']}\n"
                f"Plan     : {meta.get('plan') or 'given with --plan'}\n"
                f"License  : {license_text}\n"
                + (f"Credit   : {attribution}\n" if attribution else "")
                + f"Terms    : {TERMS_URL} (read and save a screenshot when you ship)\n"
                f"Request  : {json.dumps(meta['request'], ensure_ascii=False)}\n"
                + "".join(f"File     : {r.strip('`')}  SHA-256 {h}\n" for r, h in zip(rels, meta["sha256"])))
    log_path.write_text(fetch_asset.add_log_row(log_text, row, fill), encoding="utf-8", newline="\n")
    lic_dir = root / fetch_asset.LICENSE_DIR
    lic_dir.mkdir(parents=True, exist_ok=True)
    (lic_dir / f"{asset_id}.txt").write_text(evidence, encoding="utf-8", newline="\n")
    print(f"[ OK ] {asset_id} added to {fetch_asset.ASSET_LOG.as_posix()}, evidence in "
          f"{(fetch_asset.LICENSE_DIR / (asset_id + '.txt')).as_posix()}")
    if placeholder:
        print("[warn] free plan: logged as PLACEHOLDER (non-commercial, needs credit). Replace before release, "
              "or regenerate on a paid plan")


def cmd_check(args):
    key = get_key()
    if not key:
        raise ToolError(missing_key_help())
    info = plan_info(key)
    if not info:
        print("[ OK ] the key is set; it may not read the account (no User read permission), so the plan is unknown. "
              "Generation still works if the key allows it; pass --plan with --log")
        return 0
    paid = license_for("auto", info)[0]
    print(f"[ OK ] key works: plan {info['tier']} ({info['status']}), {info['used']} of {info['limit']} credits used"
          + (f", resets {info['reset']}" if info["reset"] else ""))
    print("       license: " + ("paid plan, commercial use allowed" if paid else
                                "free plan, non-commercial only and needs credit: --log marks files PLACEHOLDER"))
    return 0


def missing_key_help():
    return (f"{KEY_ENV} is not set. Create a key at elevenlabs.io (Developers, API Keys; restrict it to Sound "
            "Effects, Music and User read, with a credit limit), then add it as a user environment variable "
            f"named {KEY_ENV} (Windows: Settings, search 'environment variables'). Never put it in the project.")


def cmd_generate(args, kind):
    path, body, query = build_request(kind, args)
    files = outputs(args)
    for f in files:
        if f.exists() and not args.overwrite:
            raise ToolError(f"{f} exists (use --overwrite)")
    if args.dry_run:
        print(f"[dry-run] POST {API}{path}?{urllib.parse.urlencode(query)}")
        print(f"[dry-run] body {json.dumps(body, ensure_ascii=False)}")
        print(f"[dry-run] would write {', '.join(str(f) for f in files)} ({len(files)} request(s), each spends credits)")
        return 0
    key = get_key()
    if not key:
        raise ToolError(missing_key_help())
    info = plan_info(key)
    lic = license_for(args.plan, info) if (args.log or args.plan != "auto" or info) else None
    meta = {"tool": "eleven_audio", "service": "ElevenLabs", "endpoint": path, "model_id": body["model_id"],
            "request": dict(body, output_format=query["output_format"]), "date": datetime.date.today().isoformat(),
            "plan": f"{info['tier']} ({info['status']})" if info else None, "sha256": [],
            "license": lic[1] if lic else "unknown: check your plan", "text": body.get("text"),
            "prompt": body.get("prompt")}
    for f in files:
        headers, raw = call("POST", path, key, body, query)
        dbg("response headers: " + ", ".join(sorted(headers)))
        what = save(raw, f, query["output_format"], getattr(args, "loop_crossfade", None), args.mono)
        sha = hashlib.sha256(f.read_bytes()).hexdigest()
        meta["sha256"].append(sha)
        h = {k.lower(): v for k, v in headers.items()}
        cost = h.get("character-cost")                 # credits this request spent (seen 2026-10-22)
        side = dict(meta, sha256=sha, request_id=h.get("x-trace-id") or h.get("request-id"), credits=cost)
        side.pop("text"), side.pop("prompt")
        f.with_suffix(".gen.json").write_text(json.dumps(side, indent=2, ensure_ascii=False) + "\n",
                                              encoding="utf-8", newline="\n")
        print(f"[ OK ] {f}: {what}" + (f", cost {cost} credits" if cost else ""))
    if args.log:
        write_log(args, kind, files, meta, lic)
    elif lic and lic[3]:
        print("[warn] free plan: these files are non-commercial and need credit (log them with --log)")
    return 0


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".", help="project root for --log (default: current folder)")
    common.add_argument("--debug", action="store_true", help="print requests (never the key) and tracebacks")
    gen = argparse.ArgumentParser(add_help=False)
    gen.add_argument("--out", required=True, help="output file, .mp3 or .wav (relative to the current folder)")
    gen.add_argument("--seconds", type=float, help="length (sfx 0.5..30, music 3..600; default: the model decides)")
    gen.add_argument("--model", help=f"model id (default {SFX_MODEL} for sfx, {MUSIC_MODEL} for music)")
    gen.add_argument("--format", help="output_format, e.g. mp3_44100_128 or pcm_24000 (default from the file type)")
    gen.add_argument("--mono", action="store_true", help="mix the stereo result down to mono (.wav only; 3D sounds)")
    gen.add_argument("--plan", choices=("auto", "paid", "free"), default="auto",
                     help="your plan, for the license note (default: ask the API)")
    gen.add_argument("--log", action="store_true", help="add the ASSET_LOG row and evidence file (files that ship)")
    gen.add_argument("--notes", help="extra text for the ASSET_LOG Notes column")
    gen.add_argument("--overwrite", action="store_true", help="replace existing files")
    gen.add_argument("--dry-run", action="store_true", help="print the request, send nothing, spend nothing")
    ap = argparse.ArgumentParser(
        description="Generate sound effects and music with the ElevenLabs API (your key, your credits) and log them.",
        epilog=f"Key: environment variable {KEY_ENV}. Exit codes: 0 ok, 1 service failure, 2 usage, key, plan or quota.",
        parents=[common])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("check", parents=[common], help="test the key and show the plan and its license")
    s = sub.add_parser("sfx", parents=[common, gen], help="text to sound effect")
    s.add_argument("--text", help="what the sound is, e.g. 'heavy stone door grinding open'")
    s.add_argument("--influence", type=float, default=0.3, help="0..1, how literally to follow the text (default 0.3)")
    s.add_argument("--loop", action="store_true", help="ask for a sound that loops smoothly (ambience)")
    s.add_argument("--variants", type=int, default=1, help="make N takes as <out>_1 ... (N requests)")
    m = sub.add_parser("music", parents=[common, gen], help="text to music")
    m.add_argument("--prompt", help="style, mood, instruments, tempo")
    m.add_argument("--instrumental", action="store_true", help="no vocals")
    m.add_argument("--loop-crossfade", type=float, metavar="SECONDS",
                   help="blend the end into the start and add loop points (.wav only)")
    return ap


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    DEBUG = args.debug
    try:
        if args.command == "check":
            return cmd_check(args)
        return cmd_generate(args, args.command)
    except (ToolError, fetch_asset.FetchError) as exc:   # FetchError: a broken ASSET_LOG table, from --log
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except ServiceError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[error] interrupted", file=sys.stderr)
        return 1
    except Exception as exc:   # last resort: clear message, traceback only with --debug
        print(f"[error] unexpected failure: {exc!r}. Re-run with --debug.", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# fish_tts.py
# Purpose : Fish Audio text to speech from the command line: check the key and API balance, search the
#           voice library for a voice ID, and render a line to a file (pre-generated voice). Games that
#           speak live lines call the same API at runtime instead (examples/gatekeeper-godot).
# Usage   : python tools/audio/fish_tts.py check
#           python tools/audio/fish_tts.py voices --search "old knight" --language en
#           python tools/audio/fish_tts.py say --voice <id> --text "Halt. Who goes there?" --out build/voice/halt.mp3
#           python tools/audio/fish_tts.py say --voice <id> --text "..." --out x.mp3 --dry-run   # send nothing
#           python tools/audio/fish_tts.py say --voice <id> --text "Who's there?" --text "Gotcha." \
#               --out assets/audio/voice/ghost.wav --log      # ghost_1.wav, ghost_2.wav, one ASSET_LOG row
# Needs   : Python 3.8+ only. A Fish Audio API key in FISH_API_KEY (on Windows a saved user variable works
#           without restarting the terminal).
# Exit    : 0 ok, 1 the service failed (try again later), 2 usage, key, balance or quota problem
# Notes   : The API is pay-as-you-go and billed apart from any Fish Audio subscription (2026-10: $15 per
#           million UTF-8 bytes of text on s2.1-pro, so a 60-character line costs about $0.001; s2.1-pro-free
#           costs nothing). Commercial-use terms for API output are not in the API docs: read Fish Audio's
#           terms before shipping (verify). Some library voices imitate real people: pick an original or
#           "licensed" voice, never one that sounds like a real person. Output is mono (wav, mp3 or opus).
#           The key is never printed or saved, and a redirect carries it only to the same https host and
#           port (anywhere else it is dropped; a redirect from https to http is refused). say --log checks
#           ASSET_LOG and --root before any request.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   key from the environment -> check: GET /wallet/self/api-credit | voices: GET /model?title=&language=
#   | say: --log? ASSET_LOG exists, outputs inside --root -> POST /v1/tts {text, reference_id, format} with the model header -> save + <out>.gen.json
import argparse
import datetime
import hashlib
import json
import os
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # tools/: fetch_asset.py for --log

API = "https://api.fish.audio"
KEY_ENV = "FISH_API_KEY"
KEY_HEADER = "authorization"          # the request header that carries the key (lower case: how it is matched)
MODEL = "s2.1-pro"
FORMATS = {".mp3": "mp3", ".wav": "wav", ".opus": "opus"}
TIMEOUT_S = 120
USER_AGENT = "claude-code-game-kit fish_tts.py"
DEBUG = False


class ToolError(Exception):
    """Exit 2: something the user can fix (usage, key, balance)."""


class ServiceError(Exception):
    """Exit 1: the service failed; trying again later may work."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def get_key():
    key = os.environ.get(KEY_ENV, "").strip()
    if key or os.name != "nt":
        return key or None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, KEY_ENV)[0]).strip() or None
    except OSError:
        return None


def redirect_rule(old_url, new_url):
    """'keep', 'strip' or 'refuse' for a redirect. The key may follow only to the same https origin (scheme, host
    and port); anywhere else it is dropped, and a step down from https to plain http is refused outright."""
    old, new = urllib.parse.urlsplit(old_url), urllib.parse.urlsplit(new_url)
    if old.scheme == "https" and new.scheme != "https":
        return "refuse"
    try:
        same = (new.scheme == "https" == old.scheme and old.hostname == new.hostname
                and (old.port or 443) == (new.port or 443))
    except ValueError:                    # a port that is not a number
        return "refuse"
    return "keep" if same else "strip"


class KeepKeyOnHost(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but never carry the key off its origin: urllib copies every header (Authorization too)
    onto the redirected request, so a redirect to another host, port or scheme would otherwise send it there."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        rule = redirect_rule(req.full_url, newurl)
        if rule == "refuse":
            fp.close()
            target = urllib.parse.urlsplit(newurl)
            raise ServiceError(f"Fish Audio redirected to a non-https address ({target.scheme}://{target.hostname}); "
                               "refusing it")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and rule == "strip":
            for store in (new.headers, new.unredirected_hdrs):
                for name in [h for h in store if h.lower() == KEY_HEADER]:
                    del store[name]
        return new


OPENER = urllib.request.build_opener(KeepKeyOnHost)


def http(method, url, key, body=None, extra_headers=None):
    """(status, headers, bytes). Kept small so the exam can replace it."""
    headers = {"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}
    if body is not None:
        headers["Content-Type"] = "application/json"
    headers.update(extra_headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8") if body is not None else None,
                                 method=method, headers=headers)
    try:
        with OPENER.open(req, timeout=TIMEOUT_S) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read() or b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ToolError(f"could not reach {API} ({getattr(exc, 'reason', exc)})")


def call(method, path, key, body=None, query=None, extra_headers=None):
    url = API + path + ("?" + urllib.parse.urlencode(query, doseq=True) if query else "")
    dbg(f"{method} {url}")
    status, headers, raw = http(method, url, key, body, extra_headers)
    if status == 200:
        return headers, raw
    try:
        err = json.loads(raw.decode("utf-8", "replace"))
        detail = err.get("message") or err.get("detail") or str(err)[:300]
    except (ValueError, AttributeError):
        detail = raw[:300].decode("utf-8", "replace")
    if status == 401:
        raise ToolError(f"the API key was rejected ({detail}); check {KEY_ENV}")
    if status == 402:
        raise ToolError(f"no API balance for this ({detail}); top up the developer API wallet, or use --model s2.1-pro-free")
    if status == 429:
        raise ToolError(f"rate limited ({detail}); wait and try again")
    if status in (400, 404, 422):
        raise ToolError(f"Fish Audio rejected the request ({status}): {detail}")
    raise ServiceError(f"Fish Audio failed ({status}): {detail}; try again later")


def need_key():
    key = get_key()
    if not key:
        raise ToolError(f"{KEY_ENV} is not set. Create an API key at fish.audio (Developers), then save it as a user "
                        f"environment variable named {KEY_ENV}. Never put it in the project.")
    return key


def cmd_check(args):
    _, raw = call("GET", "/wallet/self/api-credit", need_key(), query={"check_free_credit": "true"})
    w = json.loads(raw.decode("utf-8", "replace"))
    print(f"[ OK ] key works: API credit {w.get('credit')} (topped up {w.get('cumulative_top_up')} in all)"
          + (", free credit available" if w.get("has_free_credit") else ""))
    print("       the API is billed apart from any subscription; --model s2.1-pro-free costs nothing")
    return 0


def cmd_voices(args):
    query = {"page_size": args.limit, "sort_by": "score"}
    if args.search:
        query["title"] = args.search
    if args.language:
        query["language"] = args.language
    if args.licensed:
        query["licensed"] = "true"
    _, raw = call("GET", "/model", need_key(), query=query)
    items = json.loads(raw.decode("utf-8", "replace")).get("items", [])
    if not items:
        print("no voices matched; try a broader --search")
        return 0
    for m in items:
        langs = ",".join(m.get("languages") or [])
        flag = " licensed" if m.get("licensed") else ""
        print(f"{m['_id']}  {m.get('title', '')[:40]:40}  [{langs}]  {m.get('like_count', 0)} likes{flag}")
    print("Listen on fish.audio before choosing. Avoid voices that imitate real people.")
    return 0


def cmd_say(args):
    out = Path(args.out)
    fmt = FORMATS.get(out.suffix.lower())
    if not fmt:
        raise ToolError(f"--out must end in {', '.join(FORMATS)}")
    texts = [t.strip() for t in args.text]
    if not all(texts):
        raise ToolError("--text is empty")
    # several --text lines: one file each, <out>_1, <out>_2 ... (and one ASSET_LOG row for the set)
    files = [out] if len(texts) == 1 else [out.with_name(f"{out.stem}_{i}{out.suffix}") for i in range(1, len(texts) + 1)]
    for f in files:
        if f.exists() and not args.overwrite:
            raise ToolError(f"{f} exists (use --overwrite)")
    headers = {"model": args.model}
    if args.dry_run:
        print(f"[dry-run] POST {API}/v1/tts  model: {args.model}, voice {args.voice}")
        for f, text in zip(files, texts):
            print(f"[dry-run] {f}: {json.dumps(text, ensure_ascii=False)} ({len(text.encode('utf-8'))} bytes of text)")
        return 0
    if args.log:
        log_targets(args, files)          # a missing ASSET_LOG or a file outside --root stops here, before spending
    key = need_key()
    done = []
    for f, text in zip(files, texts):
        body = {"text": text, "reference_id": args.voice, "format": fmt, "latency": "balanced"}
        resp_headers, raw = call("POST", "/v1/tts", key, body, extra_headers=headers)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(raw)
        side = {"tool": "fish_tts", "service": "Fish Audio", "endpoint": "/v1/tts", "model": args.model,
                "request": body, "date": datetime.date.today().isoformat(),
                "sha256": hashlib.sha256(raw).hexdigest(), "text_bytes": len(text.encode("utf-8")),
                "license": "Fish Audio API terms (verify before shipping)"}
        f.with_suffix(".gen.json").write_text(json.dumps(side, indent=2, ensure_ascii=False) + "\n",
                                              encoding="utf-8", newline="\n")
        print(f"[ OK ] {f}: {len(raw) // 1024} KB {fmt}, {side['text_bytes']} bytes of text on {args.model}")
        done.append((f, text, side["sha256"]))
    if args.log:
        write_log(args, key, done)
    return 0


def voice_title(key, voice_id):
    """The voice's library title, for the evidence file; empty if it cannot be read."""
    try:
        _, raw = call("GET", f"/model/{voice_id}", key)
        return json.loads(raw.decode("utf-8", "replace")).get("title", "")
    except (ToolError, ServiceError, ValueError):
        return ""


def log_targets(args, files):
    """(root, ASSET_LOG path, `project/relative` names) for --log. Called before the first request too, so a
    missing log or a file outside --root stops the run before any balance is spent."""
    import fetch_asset   # tools/fetch_asset.py, one folder up (path added at the top)
    root = Path(args.root).resolve()
    log_path = root / fetch_asset.ASSET_LOG
    if not log_path.is_file():
        raise ToolError(f"{fetch_asset.ASSET_LOG.as_posix()} not found under {root} (pass --root)")
    try:   # a log without a table would reject the row only after the paid call
        fetch_asset.add_log_row(log_path.read_text(encoding="utf-8", errors="replace"), "", False)
    except fetch_asset.UsageError as exc:
        raise ToolError(str(exc))
    try:
        rels = [f"`{f.resolve().relative_to(root).as_posix()}`" for f in files]
    except ValueError:
        raise ToolError("--log is for files inside the project (--root)")
    return root, log_path, rels


def write_log(args, key, done):
    """ASSET_LOG row + docs/licenses/A-NNNN.txt for a set of lines, using fetch_asset's helpers."""
    import fetch_asset   # tools/fetch_asset.py, one folder up (path added at the top)
    root, log_path, rels = log_targets(args, [f for f, _, _ in done])
    log_text = log_path.read_text(encoding="utf-8")
    num, fill = fetch_asset.next_asset_id(log_text)
    asset_id = f"A-{num:04d}"
    title = voice_title(key, args.voice)
    today = datetime.date.today().isoformat()
    lines = "; ".join(f'"{t}"' for _, t, _ in done)
    notes = "; ".join(x for x in [f"lines: {lines}", args.notes or ""] if x)
    row = (f"| {asset_id} | voice | {', '.join(rels)} | Fish Audio API (/v1/tts), model {args.model}, voice "
           f"{args.voice}{f' ({title})' if title else ''} | Fish Audio (generated) | Fish Audio API terms (verify) |  | "
           f"pre-generated | no | {today} | {fetch_asset.md_cell(notes)} |")
    evidence = (f"{asset_id}  voice  generated {today} with tools/audio/fish_tts.py\n"
                f"Service  : Fish Audio text to speech (/v1/tts), model {args.model}\n"
                f"Voice    : {args.voice}{f' ({title})' if title else ''}; check it is not an imitation of a real person\n"
                f"License  : Fish Audio API terms, read before release (verify)\n"
                + "".join(f"File     : {r.strip('`')}  \"{t}\"  SHA-256 {h}\n" for r, (_, t, h) in zip(rels, done)))
    try:
        new_log = fetch_asset.add_log_row(log_text, row, fill)
    except fetch_asset.FetchError as exc:   # a log without its table
        raise ToolError(str(exc))
    log_path.write_text(new_log, encoding="utf-8", newline="\n")
    (root / fetch_asset.LICENSE_DIR).mkdir(parents=True, exist_ok=True)
    (root / fetch_asset.LICENSE_DIR / f"{asset_id}.txt").write_text(evidence, encoding="utf-8", newline="\n")
    print(f"[ OK ] {asset_id} added to {fetch_asset.ASSET_LOG.as_posix()}, evidence in "
          f"{(fetch_asset.LICENSE_DIR / (asset_id + '.txt')).as_posix()}")


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="print requests (never the key) and tracebacks")
    ap = argparse.ArgumentParser(description="Fish Audio text to speech: check the key, find a voice, render a line.",
                                 epilog=f"Key: {KEY_ENV}. Exit codes: 0 ok, 1 service failure, 2 usage, key or balance.",
                                 parents=[common])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("check", parents=[common], help="test the key, show the API balance")
    v = sub.add_parser("voices", parents=[common], help="search the voice library for a voice ID")
    v.add_argument("--search", help="words in the voice title, e.g. 'old knight'")
    v.add_argument("--language", help="language code, e.g. en")
    v.add_argument("--licensed", action="store_true", help="only Fish Audio-licensed voices")
    v.add_argument("--limit", type=int, default=15, help="how many to list (default 15, max 100)")
    s = sub.add_parser("say", parents=[common], help="render one line to a file")
    s.add_argument("--voice", required=True, help="voice ID (reference_id) from `voices`")
    s.add_argument("--text", required=True, action="append",
                   help="what to say; repeat for a set of lines, saved as <out>_1, <out>_2 ...")
    s.add_argument("--out", required=True, help="output file: .mp3, .wav or .opus")
    s.add_argument("--model", default=MODEL, help=f"TTS model (default {MODEL}; s2.1-pro-free costs nothing)")
    s.add_argument("--overwrite", action="store_true", help="replace an existing file")
    s.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    s.add_argument("--log", action="store_true", help="add one ASSET_LOG row and evidence file for the lines")
    s.add_argument("--root", default=".", help="project root for --log (default: current folder)")
    s.add_argument("--notes", help="extra text for the ASSET_LOG Notes column")
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
        return {"check": cmd_check, "voices": cmd_voices, "say": cmd_say}[args.command](args)
    except ToolError as exc:
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

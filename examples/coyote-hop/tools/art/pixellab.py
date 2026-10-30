#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# pixellab.py
# Purpose : Generate pixel art with the PixelLab API (images, characters, animations, tilesets, effects, UI, fonts,
#           props, image fixes; the full list: -h),
#           save it in the project, and (with --log) add the ASSET_LOG row and evidence file: prompt, endpoint,
#           date, your plan and the cost. Opt-in: needs your own PixelLab account and API token.
# Usage   : python tools/art/pixellab.py check                                  # token works? plan, generations left
#           python tools/art/pixellab.py image --text "rusty iron key, top-down" --size 32 \
#               --no-background --out assets/art/items/key.png --log
#           python tools/art/pixellab.py character --text "old gravekeeper with a lantern" --size 64 \
#               --directions 8 --out assets/art/keeper --log
#           python tools/art/pixellab.py character --text "tiny wizard" --size 16 --directions 4 --legacy --out ...
#           python tools/art/pixellab.py animate --frame assets/art/keeper/Idle/rotations/south.png \
#               --action "walking" --frames 8 --out assets/art/keeper/walk_south --log
#           python tools/art/pixellab.py tileset --lower "dark grass" --upper "cobblestone path" \
#               --tile-size 16 --out assets/art/tiles/path --log
#           python tools/art/pixellab.py animate-character --from assets/art/keeper --mode skeleton-v3 \
#               --template cross-punch --directions south,east --out assets/art/keeper_punch
#           python tools/art/pixellab.py vfx --text "brass punch impact sparks" --out assets/fx/punch
#           python tools/art/pixellab.py prop --text "a loaf of bread on a plate" --out assets/art/bread.png
#           python tools/art/pixellab.py edit --image hero.png --text "make ONLY the right hand a fist" --out hero2.png
#           python tools/art/pixellab.py tiles-pro --text "dirt road" --feature roads --out assets/art/roads   [paid plan]
#           Also: tileset --kind sidescroller, iso-tile, object (1 or 8 directions), ui, font, pixelate, fix
#           (reduce-colors, correct, unzoom, remove-background, normal-map), outfit [paid plan].
#           python tools/art/pixellab.py image --text "..." --out x.png --dry-run      # show, send nothing
# Needs   : Python 3.8+ only. A PixelLab account (pixellab.ai; a paid plan or the free trial's few generations)
#           and its API token in the PIXELLAB_API_KEY environment variable (on Windows a user variable set in
#           Settings works without restarting the terminal). The token is never printed or saved.
# Exit    : 0 ok, 1 the service failed (try again later), 2 usage, token, plan or credits problem
# Notes   : Every request but `check` spends generations or credits; each command prints what it cost.
#           --dry-run prints the request and sends nothing. Character, animation and tileset jobs run on
#           PixelLab's servers for 30 s to a few minutes; this tool polls them (--wait to change the limit).
#           Licensing (PixelLab's FAQ, 2026-10, verify the terms when you ship): commercial use is allowed; do not
#           train AI models on the output. Stores ask whether a game uses AI assets (SOP-04).
#           A PNG output is checked to really be a PNG; zip downloads are extracted only inside --out.
#           Interactive use through Claude Code: PixelLab's MCP server (docs/sop/SOP-16-2d-art-pipeline.md).
#           Run live 2026-10-24: `check`, and one `character --size 16 --legacy` (1 generation): 24x24 frames (the
#           canvas is about 40% bigger than the size asked), files under <out>/Idle/rotations/<direction>.png.
#           Run live 2026-10-26: prop (1), vfx lite (1: a GIF, spritesheet and JSON from
#           storage links), iso-tile (1), tileset --kind sidescroller (2, 16 tiles), edit (1), fix reduce-colors (0.1).
#           Learned live: GET /map-objects/{id} answers 423 while it is generating (handled as "still working").
#           Not yet live: ui, font, object, tiles-pro, outfit, pixelate, animate-character (verify).
#           [paid plan only] in -h (tiles-pro, outfit) is PixelLab's rule; a trial account gets a 402, explained.
#           Download links on PixelLab's storage get no token: it is sent only to the API host, and a redirect
#           keeps it only on the same https host and port (anywhere else it is dropped; https to http is refused).
#           Names from a response (object directions) must be plain names, so nothing is written outside --out.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   parse command -> dry run? print the request (images replaced by their size), stop
#   token from the environment (Windows: also the saved user variable) -> plan from GET /balance
#   image:     POST /create-image-pixflux -> PNG at once
#   character: POST /create-character-v3 -> poll the job -> GET /characters/{id}/zip -> extract into --out
#   animate:   POST /animate-with-text-v3 (the frame as base64) -> poll -> last_response.images -> frame PNGs
#   tileset:   POST /create-tileset(-sidescroller) -> poll -> GET /tilesets/{id} -> tile PNGs + tileset.json
#   ui, prop, object: POST -> poll the resource (GET /ui-assets|/map-objects|/objects/{id}) -> download its links
#   vfx, font, edit, outfit, normal-map: POST -> poll the job -> save last_response (images, files, ttf_base64)
#   animate-character: POST /characters/animations -> poll every direction's job -> the character's zip
#   -> pixellab.gen.json (request, date, plan, cost, SHA-256 of each file) -> --log: ASSET_LOG row + evidence file
import argparse
import base64
import datetime
import binascii
import hashlib
import http.client as http_client
import io
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fetch_asset  # noqa: E402  (shared ASSET_LOG helpers)

API = "https://api.pixellab.ai/v2"
KEY_ENV = "PIXELLAB_API_KEY"
KEY_HEADER = "authorization"          # the request header that carries the token (lower case: how it is matched)
TIMEOUT_S = 120                       # one HTTP request
POLL_EVERY_S = 3                      # the API docs ask for 2 to 5 s between job polls
WAIT_S = 600                          # how long to wait for a job (--wait)
MAX_VARIANTS = 4                      # each variant is a paid generation
MAX_DOWNLOAD = 200_000_000            # bytes: one response or one zip member (a character with many animations is far less)
MAX_ZIP_TOTAL = 500_000_000           # bytes: everything one zip may unpack to
SAFE_EXTENSIONS = {".png", ".gif", ".json", ".zip", ".ttf", ".txt", ".webp"}   # what a result may write to disk
MAX_NAME = 100                        # characters in a downloaded file name
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
LICENSE = "PixelLab: commercial use allowed; do not train AI models on the output (FAQ 2026-10, verify the terms)"
TERMS_URL = "https://www.pixellab.ai"
USER_AGENT = "claude-code-game-kit pixellab.py"
DEBUG = False
SLEEP = time.sleep                    # the exam replaces it


class ToolError(Exception):
    """Exit 2: something the user can fix (usage, token, plan, credits)."""


class ServiceError(Exception):
    """Exit 1: the service failed; trying again later may work."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def get_key():
    """The API token, or None. On Windows a user variable saved after this terminal opened is read too."""
    key = os.environ.get(KEY_ENV, "").strip()
    if key or os.name != "nt":
        return key or None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, KEY_ENV)[0]).strip() or None
    except OSError:
        return None


def missing_key_help():
    return (f"no PixelLab token: set the {KEY_ENV} environment variable (pixellab.ai > account > API token). "
            "Use --dry-run to see a request without one.")


def redirect_rule(old_url, new_url):
    """'keep', 'strip' or 'refuse' for a redirect. The token may follow only to the same https origin (scheme,
    host and port); anywhere else it is dropped, and a step down from https to plain http is refused outright
    (comparing the host alone kept the token on an https -> http redirect to the same host)."""
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
    """Follow redirects, but never carry the token off its origin: urllib copies every header (Authorization
    too) onto the redirected request, so a redirect to storage would otherwise send it there."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        rule = redirect_rule(req.full_url, newurl)
        if rule == "refuse":
            fp.close()
            target = urllib.parse.urlsplit(newurl)
            raise ServiceError(f"PixelLab redirected to a non-https address ({target.scheme}://{target.hostname}); "
                               "refusing it")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and rule == "strip":
            for store in (new.headers, new.unredirected_hdrs):
                for name in [h for h in store if h.lower() == KEY_HEADER]:
                    del store[name]
        return new


OPENER = urllib.request.build_opener(KeepKeyOnHost)


def http(method, url, key, body=None):
    """(status, headers, bytes). Network errors raise ToolError, a body cut off or too big ServiceError. Kept small
    so the exam can replace it. key None sends no Authorization header (storage links need none)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with OPENER.open(req, timeout=TIMEOUT_S) as resp:
            payload = resp.read(MAX_DOWNLOAD + 1)
            if len(payload) > MAX_DOWNLOAD:
                raise ServiceError(f"a response from PixelLab is over {MAX_DOWNLOAD // 1_000_000} MB; refusing it")
            return resp.status, dict(resp.headers), payload
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read(64_000) or b""
    except http_client.HTTPException as exc:
        raise ServiceError(f"the connection to PixelLab broke mid-answer ({exc.__class__.__name__}); try again")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ToolError(f"could not reach {API} ({getattr(exc, 'reason', exc)})")


def error_detail(raw):
    """The service's own error message from a JSON error body (FastAPI style), short."""
    try:
        detail = json.loads(raw.decode("utf-8", "replace")).get("detail", "")
    except (ValueError, AttributeError):
        return raw[:300].decode("utf-8", "replace")
    if isinstance(detail, list):
        return "; ".join(f"{'.'.join(str(x) for x in d.get('loc', [])[1:])}: {d.get('msg', '')}" for d in detail)[:500]
    return str(detail)[:500]


def call(method, path, key, body=None, raw=False, pending_ok=False):
    """One API request. Returns parsed JSON (or bytes with raw=True); maps failures to the exit codes.
    pending_ok: a 423 ("still being generated", seen live on GET /map-objects/{id}) returns {"status": "processing"}."""
    dbg(f"{method} {API}{path}")
    status, headers, data = http(method, API + path, key, body)
    if status == 423 and pending_ok:
        return {"status": "processing", "detail": error_detail(data)}
    if status in (200, 201, 202):
        if raw:
            return data
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError:
            raise ServiceError(f"PixelLab answered {path} with something that is not JSON")
    detail = error_detail(data)
    if status in (401, 403):
        raise ToolError(f"PixelLab rejected the token ({status}: {detail}). Check {KEY_ENV}.")
    if status == 402:
        raise ToolError(f"PixelLab says the plan cannot pay for this ({detail}): out of generations or credits, "
                        "or the tool needs a higher tier. `check` shows what is left.")
    if status == 422:
        raise ToolError(f"PixelLab rejected the request: {detail}")
    if status == 429:
        raise ToolError(f"PixelLab is limiting requests ({detail}): too many at once or too fast. Wait, then retry.")
    raise ServiceError(f"PixelLab failed ({status}: {detail})")


def cost_text(usage):
    """'1 generation' / '$0.02' / '' from a response's usage."""
    if not isinstance(usage, dict):
        return ""
    if usage.get("type") == "generations" and usage.get("generations") is not None:
        g = usage["generations"]
        return f"{g:g} generation{'s' if g != 1 else ''}"
    if usage.get("usd") is not None:
        return f"${usage['usd']:.2f}"
    return ""


def balance(key):
    """(plan text, raw) from GET /balance; the plan text is short and safe to log."""
    info = call("GET", "/balance", key)
    sub = info.get("subscription") or {}
    credits = (info.get("credits") or {}).get("usd")
    plan = f"{sub.get('plan') or 'no plan'} ({sub.get('status', 'unknown')})"
    left = f"{sub.get('generations', 0):g} of {sub.get('total', 0):g} generations left"
    usd = f", ${credits:.2f} credits" if credits is not None else ""
    return plan, f"{plan}: {left}{usd}"


def wait_job(key, job_id, limit):
    """Poll a background job until it completes. Returns its last_response."""
    start = time.monotonic()
    said = 0.0
    while True:
        job = call("GET", f"/background-jobs/{job_id}", key)
        status = job.get("status")
        last = job.get("last_response") or {}
        if status == "completed":
            return last, job.get("usage")
        if status == "failed":
            raise ServiceError(f"PixelLab job {job_id} failed: {last.get('detail') or last.get('error') or 'no reason given'}")
        waited = time.monotonic() - start
        if waited >= limit:
            raise ServiceError(f"job {job_id} still {status} after {limit} s (it keeps running on PixelLab's side; "
                               "it may still be charged). Rerun with a longer --wait.")
        if waited - said >= 15:
            where = f", queue position {last['queue_position']}" if isinstance(last, dict) and "queue_position" in last else ""
            print(f"[info] job {status}{where}, {int(waited)} s so far ...")
            said = waited
        SLEEP(POLL_EVERY_S)


def b64decode(text, what):
    """Base64 from PixelLab (a bare string or a data: URL) -> bytes; garbage is a service failure, not a crash."""
    if isinstance(text, str) and text.startswith("data:"):
        text = text.split(",", 1)[-1]
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise ServiceError(f"PixelLab sent broken base64 data for {what}")


def png_from_b64(img, path):
    """Write one Base64Image (or a bare base64 string) to path as PNG. Returns the SHA-256."""
    data = b64decode(img["base64"] if isinstance(img, dict) else img, path.name)
    if not data.startswith(PNG_MAGIC):
        raise ServiceError(f"PixelLab sent something that is not a PNG for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def b64_image(path):
    """A local PNG as the API's Base64Image."""
    p = Path(path)
    if not p.is_file():
        raise ToolError(f"{p} not found")
    data = p.read_bytes()
    if not data.startswith(PNG_MAGIC):
        raise ToolError(f"{p} is not a PNG")
    return {"type": "base64", "base64": base64.b64encode(data).decode("ascii"), "format": "png"}


def extract_zip(data, out_dir):
    """Unpack a zip from PixelLab into out_dir, refusing any member that would land outside it. Returns the files."""
    out_dir = out_dir.resolve()
    files = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ServiceError("PixelLab sent a broken zip")
    with zf:
        members = [i for i in zf.infolist() if not i.is_dir()]
        if sum(i.file_size for i in members) > MAX_ZIP_TOTAL or any(i.file_size > MAX_DOWNLOAD for i in members):
            raise ServiceError("PixelLab's zip would unpack to more than the size limit; refusing it")
        for info in members:
            target = (out_dir / info.filename).resolve()
            if out_dir not in target.parents:
                raise ServiceError(f"refusing zip member outside {out_dir}: {info.filename}")
            if not allowed_name(target.name):
                raise ServiceError(f"refusing zip member with an unexpected name or type: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
            files.append(target)
    return files


def allowed_name(name):
    """A result file name the tool will write: an expected type, no stream (':'), not hidden, not too long."""
    return (Path(name).suffix.lower() in SAFE_EXTENSIONS and ":" not in name and not name.startswith(".")
            and len(name) <= MAX_NAME)


def plain_name(text):
    """True for a short name of ASCII letters, digits, '-' and '_' (a direction like 'south' or 'north-east'):
    nothing that could be a folder, a parent ('..'), a drive or a stream."""
    return (isinstance(text, str) and 0 < len(text) <= 40
            and all(c.isascii() and (c.isalnum() or c in "-_") for c in text))


def printable(body):
    """The request with images (also inside lists and nested objects) replaced by a short note, for --dry-run,
    the .gen.json and the evidence file."""
    if isinstance(body, dict):
        if "base64" in body and isinstance(body["base64"], str):
            return f"<{body.get('format', 'png')} image, {len(body['base64']) * 3 // 4} bytes>"
        return {k: printable(v) for k, v in body.items()}
    if isinstance(body, list):
        return [printable(v) for v in body]
    return body


def png_size(path):
    """(width, height) of a local PNG, read from its header."""
    data = Path(path).read_bytes()[:24]
    if not data.startswith(PNG_MAGIC):
        raise ToolError(f"{path} is not a PNG")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


MAGIC = {".png": (PNG_MAGIC,), ".gif": (b"GIF87a", b"GIF89a"), ".zip": (b"PK\x03\x04",),
         ".ttf": (b"\x00\x01\x00\x00", b"OTTO", b"true")}


def check_bytes(data, name):
    """Refuse a download whose content does not match its file type."""
    ext = Path(name).suffix.lower()
    if ext in MAGIC and not data.startswith(MAGIC[ext]):
        raise ServiceError(f"PixelLab sent something that is not a {ext} file for {name}")
    if ext == ".json":
        try:
            json.loads(data.decode("utf-8"))
        except ValueError:
            raise ServiceError(f"PixelLab sent a broken JSON file for {name}")


def safe_name(url, fallback):
    """A plain file name from a download URL (no folders, no query string)."""
    name = urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1])
    name = "".join(c for c in name if c.isalnum() or c in "._-")
    return name if name and allowed_name(name) else fallback


def fetch_url(url, key, path):
    """Download one result file. The token goes only to PixelLab's own API host, never to storage links."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ServiceError(f"refusing a non-https download link: {url[:80]}")
    if not allowed_name(path.name):
        raise ServiceError(f"refusing to write {path.name!r}: not one of the expected result types or names")
    send_key = key if parsed.netloc == urllib.parse.urlparse(API).netloc else None
    status, _, data = http("GET", url, send_key)
    if status != 200:
        raise ServiceError(f"download failed ({status}) for {path.name}")
    check_bytes(data, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def poll_resource(key, path, limit, done=("completed",), failed=("failed", "error")):
    """Poll GET path until its status is done. Returns the resource."""
    start = time.monotonic()
    said = 0.0
    while True:
        res = call("GET", path, key, pending_ok=True)
        status = res.get("status")
        if status in done:
            return res
        if status in failed:
            raise ServiceError(f"PixelLab says {path} {status}: {res.get('detail') or res.get('error') or 'no reason given'}")
        waited = time.monotonic() - start
        if waited >= limit:
            raise ServiceError(f"{path} still {status} after {limit} s (it may still finish and be charged). "
                               "Rerun with a longer --wait.")
        if waited - said >= 15:
            print(f"[info] {status or 'working'}, {int(waited)} s so far ...")
            said = waited
        if status == "review":
            return res
        SLEEP(POLL_EVERY_S)


def url_values(obj):
    """Every https link in a value (a string, a list, or a dict of them, nested)."""
    if isinstance(obj, str):
        return [obj] if obj.startswith("https://") else []
    if isinstance(obj, dict):
        return [u for v in obj.values() for u in url_values(v)]
    if isinstance(obj, list):
        return [u for v in obj for u in url_values(v)]
    return []


def save_last(last, out, key, stem="image"):
    """Save whatever a finished job returned: one image, several images, download links or a font. Returns files."""
    files = []
    if isinstance(last.get("image"), (dict, str)):
        files.append(_save(last["image"], out / f"{stem}.png"))
    images = last.get("images") or []
    for i, img in enumerate(images):
        files.append(_save(img, out / (f"{stem}.png" if len(images) == 1 and not files else f"{stem}_{i:02d}.png")))
    for i, url in enumerate(url_values(last.get("files"))):
        files.append(fetch_url(url, key, out / safe_name(url, f"file_{i:02d}.bin")))
    if last.get("ttf_base64"):
        data = b64decode(last["ttf_base64"], "the font")
        check_bytes(data, "font.ttf")
        (out / f"{stem}.ttf").write_bytes(data)
        files.append(out / f"{stem}.ttf")
    if not files:
        raise ServiceError(f"the job finished, but its result has none of the expected parts (got: {sorted(last)})")
    return files


# ---- Requests ----------------------------------------------------------------------
def size_arg(text):
    """'64' or '64x48' -> {'width': 64, 'height': 48}."""
    try:
        w, _, h = text.lower().partition("x")
        w, h = int(w), int(h or w)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a size like 64 or 64x48")
    return {"width": w, "height": h}


def check_size(size, low, high, what):
    for side in ("width", "height"):
        if not low <= size[side] <= high:
            raise ToolError(f"{what} {side} {size[side]} is outside {low} to {high} pixels")


def style(args, body):
    for name in ("outline", "shading", "detail", "view"):
        value = getattr(args, name, None)
        if value:
            body[name] = value
    if getattr(args, "seed", None) is not None:
        body["seed"] = args.seed
    return body


def build(kind, args):
    """(endpoint, body) for a command."""
    if kind == "image":
        check_size(args.size, 16, 400, "image")
        body = {"description": args.text, "image_size": args.size, "no_background": args.no_background}
        if args.negative:
            body["negative_description"] = args.negative
        return "/create-image-pixflux", style(args, body)
    if kind == "character" and args.legacy:
        # The older 4-direction endpoint goes down to 16 px (v3 starts at 32); its canvas is about 40% bigger than
        # the character, room for animation
        if args.directions != 4:
            raise ToolError("--legacy makes 4 directions only (--directions 4)")
        check_size(args.size, 16, 128, "character")
        return "/create-character-with-4-directions", style(args, {"description": args.text, "image_size": args.size})
    if kind == "character":
        check_size(args.size, 32, 256, "character frame")
        body = {"description": args.text, "n_directions": args.directions, "image_size": args.size,
                "no_background": True}
        if args.name:
            body["name"] = args.name
        return "/create-character-v3", style(args, body)
    if kind == "animate":
        if not 4 <= args.frames <= 16:
            raise ToolError("--frames must be 4 to 16")
        body = {"first_frame": b64_image(args.frame), "action": args.action, "frame_count": args.frames}
        if args.seed is not None:
            body["seed"] = args.seed
        return "/animate-with-text-v3", body
    if kind == "tileset" and args.kind == "sidescroller":
        body = {"lower_description": args.lower, "transition_description": args.transition or "",
                "tile_size": {"width": args.tile_size, "height": args.tile_size}}
        return "/create-tileset-sidescroller", style(args, body)
    if kind == "tileset":
        if not args.upper:
            raise ToolError("a top-down tileset needs --upper (the terrain on top), e.g. --upper \"cobblestone path\"")
        body = {"lower_description": args.lower, "upper_description": args.upper,
                "transition_description": args.transition or "",
                "tile_size": {"width": args.tile_size, "height": args.tile_size}}
        return "/create-tileset", style(args, body)
    if kind == "iso-tile":
        check_size(args.size, 16, 64, "isometric tile")
        body = {"description": args.text, "image_size": args.size, "isometric_tile_shape": args.shape}
        return "/create-isometric-tile", style(args, body)
    if kind == "tiles-pro":
        body = {"description": args.text, "tile_type": args.type, "tile_size": args.tile_size, "tile_view": args.view_angle}
        if args.feature:
            body["tile_feature"] = args.feature
        return "/create-tiles-pro", style(args, body)
    if kind == "vfx":
        if not 1 <= args.sprite_frames <= 32:
            raise ToolError("--sprite-frames must be 1 to 32")
        body = {"description": args.text, "artist": "pro" if args.pro else "lite", "game_pack": args.game_pack}
        if args.sprite:
            body["sprite"] = b64_image(args.sprite)
            body["sprite_frames"] = args.sprite_frames
        if args.name:
            body["name"] = args.name
        return "/vfx", body
    if kind == "ui":
        check_size(args.size, 192, 688, "UI panel")
        body = {"description": args.text, "image_size": args.size, "no_background": True}
        if args.name:
            body["name"] = args.name
        return "/create-ui-asset", style(args, body)
    if kind == "font":
        body = {"description": args.text, "weight": args.weight, "glyph_px": args.glyph}
        if args.name:
            body["font_name"] = args.name
        return "/generate-font-pro", style(args, body)
    if kind == "object" and args.directions == 8:
        if not 24 <= args.size <= 168:
            raise ToolError("an 8-direction object's --size must be 24 to 168")
        view = args.view or "low top-down"
        if view not in ("low top-down", "high top-down", "side"):
            raise ToolError("an 8-direction object's --view is 'low top-down', 'high top-down' or 'side'")
        return "/create-8-direction-object", {"description": args.text, "size": args.size, "view": view}
    if kind == "object":
        if not 16 <= args.size <= 256:
            raise ToolError("a 1-direction object's --size must be 16 to 256")
        view = args.view or "top-down"
        if view not in ("top-down", "sidescroller"):
            raise ToolError("a 1-direction object's --view is 'top-down' or 'sidescroller'")
        return "/create-1-direction-object", {"description": args.text, "size": args.size, "view": view}
    if kind == "prop":
        check_size(args.size, 32, 400, "prop")
        body = {"description": args.text, "image_size": args.size, "view": args.view or "high top-down"}
        return "/map-objects", style(args, {k: v for k, v in body.items()})
    if kind == "edit":
        w, h = png_size(args.image)
        if w % 4 or h % 4 or w > 256 or h > 256:
            raise ToolError(f"{args.image} is {w}x{h}: `edit` needs every side a multiple of 4 and at most 256 "
                            "(pad with transparent pixels; never rescale pixel art)")
        body = {"image": b64_image(args.image), "description": args.text, "no_background": True}
        if args.seed is not None:
            body["seed"] = args.seed
        return "/edit-image-pixen", body
    if kind == "pixelate":
        w, h = png_size(args.image)
        check_size(args.size, 16, 512, "pixel art output")
        body = {"image": b64_image(args.image), "image_size": {"width": w, "height": h}, "output_size": args.size}
        if args.seed is not None:
            body["seed"] = args.seed
        return "/image-to-pixelart", body
    if kind == "fix":
        img = b64_image(args.image)
        if args.op == "reduce-colors":
            return "/reduce-colors", {"images": [img], "num_colors": args.colors}
        if args.op == "correct":
            return "/correct-pixelart", {"images": [img], "strength": args.strength}
        if args.op == "unzoom":
            return "/unzoom", {"image": img}
        if args.op == "remove-background":
            w, h = png_size(args.image)
            return "/remove-background", {"image": img, "image_size": {"width": w, "height": h}}
        return "/normal-map", {"image": img, "mode": "pro" if args.pro else "lite"}
    if kind == "outfit":
        frames = sorted(Path(args.frames).glob("*.png"))
        if not 2 <= len(frames) <= 16:
            raise ToolError(f"--frames needs a folder with 2 to 16 PNG frames ({len(frames)} found in {args.frames})")
        w, h = png_size(frames[0])
        rw, rh = png_size(args.reference)
        body = {"reference_image": {"image": b64_image(args.reference), "size": {"width": rw, "height": rh}},
                "frames": [{"image": b64_image(f), "size": {"width": w, "height": h}} for f in frames],
                "image_size": {"width": w, "height": h}, "no_background": True}
        if args.text:
            body["additional_instructions"] = args.text
        return "/transfer-outfit-v2", body
    if kind == "animate-character":
        char_id = args.character_id or character_id_from(args.source)
        body = {"character_id": char_id, "mode": args.mode}
        if args.mode in ("template", "skeleton-v3"):
            if not args.template:
                raise ToolError(f"--mode {args.mode} needs --template (e.g. walk, cross-punch, breathing-idle)")
            body["template_animation_id"] = args.template
        else:
            if not args.action:
                raise ToolError(f"--mode {args.mode} needs --action (e.g. 'swinging a huge gauntlet')")
            body["action_description"] = args.action
            body["frame_count"] = args.frames
        if args.directions:
            body["directions"] = [d.strip() for d in args.directions.split(",") if d.strip()]
        if args.name:
            body["animation_name"] = args.name
        return "/characters/animations", body
    raise ToolError(f"unknown kind {kind}")


def character_id_from(folder):
    """The character_id saved in a `character` output folder's pixellab.gen.json."""
    if not folder:
        raise ToolError("give --character-id or --from <the folder a `character` command wrote>")
    meta = Path(folder) / "pixellab.gen.json"
    try:
        cid = json.loads(meta.read_text(encoding="utf-8")).get("character_id")
    except (OSError, ValueError):
        cid = None
    if not cid:
        raise ToolError(f"no character_id in {meta} (made before this tool saved it?): pass --character-id")
    return cid


# ---- Logging -----------------------------------------------------------------------
LOG_TYPE = {"image": "art", "character": "sprite", "animate": "sprite", "tileset": "tileset", "animate-character": "sprite",
            "iso-tile": "tileset", "tiles-pro": "tileset", "vfx": "vfx", "ui": "ui", "font": "font", "object": "sprite",
            "prop": "sprite", "edit": "art", "pixelate": "art", "fix": "art", "outfit": "sprite"}


def write_log(args, kind, files, meta):
    """ASSET_LOG row + docs/licenses/A-NNNN.txt evidence, using fetch_asset's helpers."""
    root = Path(args.root).resolve()
    log_path = root / fetch_asset.ASSET_LOG
    if not log_path.is_file():
        raise ToolError(f"{fetch_asset.ASSET_LOG.as_posix()} not found under {root} (pass --root)")
    rels = []
    for f in files:
        try:
            rels.append(f.resolve().relative_to(root).as_posix())
        except ValueError:
            raise ToolError(f"{f} is outside the project {root}; --log is for files that ship in the project")
    log_text = log_path.read_text(encoding="utf-8")
    num, fill = fetch_asset.next_asset_id(log_text)
    asset_id = f"A-{num:04d}"
    folder = os.path.commonpath(rels) if len(rels) > 1 else ""
    shown = f"`{folder}/` ({len(rels)} files)" if folder and len(rels) > 3 else ", ".join(f"`{r}`" for r in rels)
    req = meta["request"]
    what = req.get("description") or req.get("action") or req.get("action_description") or \
        req.get("template_animation_id") or req.get("additional_instructions") or \
        (f"{req.get('lower_description')} / {req.get('upper_description')}" if req.get("lower_description") else "") or \
        f"{meta['endpoint'].strip('/')} of a local image"
    notes = "; ".join(x for x in [f"prompt: {what}", f"plan {meta['plan']}", f"cost {meta['cost']}" if meta["cost"] else "",
                                  args.notes or ""] if x)
    row = (f"| {asset_id} | {LOG_TYPE[kind]} | {shown} | PixelLab API ({meta['endpoint']}) | PixelLab (generated) | "
           f"{fetch_asset.md_cell(LICENSE)} |  | pre-generated | no | {meta['date']} | {fetch_asset.md_cell(notes)} |")
    evidence = (f"{asset_id}  {kind}  generated {meta['date']} with tools/art/pixellab.py\n"
                f"Service  : PixelLab {API}{meta['endpoint']}\n"
                f"Plan     : {meta['plan']}\n"
                f"Cost     : {meta['cost'] or 'not reported'}\n"
                f"License  : {LICENSE}\n"
                f"Terms    : {TERMS_URL} (read the terms of service and save a screenshot when you ship)\n"
                f"Request  : {json.dumps(meta['request'], ensure_ascii=False)}\n"
                + "".join(f"File     : {r}  SHA-256 {h}\n" for r, h in zip(rels, meta["sha256"])))
    log_path.write_text(fetch_asset.add_log_row(log_text, row, fill), encoding="utf-8", newline="\n")
    lic_dir = root / fetch_asset.LICENSE_DIR
    lic_dir.mkdir(parents=True, exist_ok=True)
    (lic_dir / f"{asset_id}.txt").write_text(evidence, encoding="utf-8", newline="\n")
    print(f"[ OK ] {asset_id} added to {fetch_asset.ASSET_LOG.as_posix()}, evidence in "
          f"{(fetch_asset.LICENSE_DIR / (asset_id + '.txt')).as_posix()}")


# ---- Commands ----------------------------------------------------------------------
def cmd_check(args):
    key = get_key()
    if not key:
        raise ToolError(missing_key_help())
    _, text = balance(key)
    print(f"[ OK ] token works: {text}")
    return 0


SYNC_IMAGE = {"image", "pixelate"}                       # the POST answers with the image itself
FILE_KINDS = {"image", "prop", "ui", "edit", "pixelate", "fix"}   # --out is one .png file; the rest write folders


def run_job(kind, key, endpoint, body, out, args):
    """Submit, wait, save. Returns (files, cost text, extra metadata)."""
    first = call("POST", endpoint, key, body)
    cost = cost_text(first.get("usage"))
    if first.get("quoted_generations") is not None and not cost:
        cost = f"{cost_text({'type': 'generations', 'generations': first['quoted_generations']})} (quoted)"
    if kind in SYNC_IMAGE or (kind == "fix" and args.op != "normal-map"):
        img = first.get("image") or (first.get("images") or [None])[0]
        if img is None:
            raise ServiceError(f"PixelLab answered {endpoint} without an image")
        return [_save(img, out)], cost, {}
    if kind == "iso-tile" and first.get("image"):
        out.mkdir(parents=True, exist_ok=True)
        return [_save(first["image"], out / "tile.png")], cost, {}
    if kind == "ui":
        asset_id = first.get("ui_asset_id")
        if not asset_id:
            raise ServiceError("PixelLab did not return a ui_asset_id")
        print(f"[info] UI asset {asset_id} queued ...")
        res = poll_resource(key, f"/ui-assets/{asset_id}", args.wait)
        if not res.get("image_url"):
            raise ServiceError("the UI asset finished without an image_url")
        return [fetch_url(res["image_url"], key, out)], cost, {"ui_asset_id": asset_id}
    if kind == "prop":
        obj = first.get("object_id")
        print(f"[info] map object {obj} queued (about 15 to 30 s) ...")
        res = poll_resource(key, f"/map-objects/{obj}", args.wait)
        cost = cost or cost_text(res.get("usage"))
        if not res.get("download_url"):
            raise ServiceError("the map object finished without a download_url")
        return [fetch_url(res["download_url"], key, out)], cost, {"object_id": obj}
    if kind == "object":
        obj = first.get("object_id")
        print(f"[info] object {obj} queued; PixelLab takes 30 s to a few minutes ...")
        res = poll_resource(key, f"/objects/{obj}", args.wait)
        if res.get("status") == "review":
            raise ToolError(f"PixelLab made several candidates for object {obj}: keep the ones you want on pixellab.ai "
                            "(or the MCP's select_object_frames), then download them; a different --size gives one")
        out.mkdir(parents=True, exist_ok=True)
        rot = {d: u for d, u in (res.get("rotation_urls") or {}).items() if u}
        for d in rot:                     # the API's keys become file names: a plain name only, never a path
            if not plain_name(d):
                raise ServiceError(f"refusing direction {str(d)[:40]!r} from PixelLab: not a plain name")
        links = [(f"{d}.png", u) for d, u in rot.items()] or \
                [(f"frame_{i:02d}.png", u) for i, u in enumerate(res.get("frame_urls") or [])] or \
                [(f"image_{i:02d}.png", u) for i, u in enumerate(url_values(res.get("storage_urls")))]
        if not links:
            raise ServiceError(f"object {obj} finished without image links")
        return [fetch_url(u, key, out / name) for name, u in links], cost, {"object_id": obj}
    jobs = first.get("background_job_ids") or ([first["background_job_id"]] if first.get("background_job_id") else [])
    if not jobs:
        raise ServiceError(f"PixelLab did not return a job for {endpoint}")
    print(f"[info] {len(jobs)} job(s) queued; PixelLab takes 30 s to a few minutes"
          + (" (skeleton animation: 3 to 5 minutes per direction)" if kind == "animate-character" else "") + " ...")
    results = [wait_job(key, j, args.wait) for j in jobs]
    last = results[-1][0]
    cost = cost or summed_cost([u for _, u in results])
    if kind not in FILE_KINDS:
        out.mkdir(parents=True, exist_ok=True)
    if kind == "character":
        data = character_zip(key, first["character_id"], args.wait)
        return extract_zip(data, out), cost, {"character_id": first["character_id"]}
    if kind == "animate-character":
        data = character_zip(key, body["character_id"], args.wait)
        return extract_zip(data, out), cost, {"character_id": body["character_id"],
                                               "animation_group_id": first.get("animation_group_id")}
    if kind == "animate":
        images = last.get("images") or []
        if not images:
            raise ServiceError("the animation job finished without frames")
        return [_save(img, out / f"frame_{i:02d}.png") for i, img in enumerate(images)], cost, {}
    if kind == "tileset":
        return save_tileset(key, first["tileset_id"], out, args.kind), cost, {"tileset_id": first["tileset_id"]}
    if kind == "iso-tile":
        tile_id = first.get("tile_id") or first.get("isometric_tile_id") or first.get("id")
        if not tile_id:
            raise ServiceError("the isometric tile job finished, but PixelLab gave no tile id to fetch it by")
        res = call("GET", f"/isometric-tiles/{tile_id}", key)
        return [_save(res["image"], out / "tile.png")], cost, {"tile_id": tile_id}
    if kind == "tiles-pro":
        tile_id = first.get("tile_id")
        res = call("GET", f"/tiles-pro/{tile_id}", key)
        links = url_values(res.get("storage_urls"))
        if not links:
            raise ServiceError("the tiles finished without download links")
        used, files = set(), []
        for i, u in enumerate(links):
            name = safe_name(u, f"tile_{i:02d}.png")
            if name.lower() in used:                     # two links with one basename must not overwrite each other
                name = f"{Path(name).stem}_{i:02d}{Path(name).suffix}"
            used.add(name.lower())
            files.append(fetch_url(u, key, out / name))
        rules = out / "tiles_pro.json"
        rules.write_text(json.dumps({"kind": res.get("kind"), "tile_rules": res.get("tile_rules"),
                                     "files": [f.name for f in files]}, indent=2) + "\n", encoding="utf-8")
        return files + [rules], cost, {"tile_id": tile_id}
    if kind == "vfx":
        files = save_last(last, out, key, stem="effect")
        info = {k: v for k, v in last.items() if k in ("effect_id", "name", "edit_url", "message", "canvas", "frames",
                                                       "fps", "loop", "anchor")}
        (out / "vfx.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        return files + [out / "vfx.json"], cost, {"effect_id": last.get("effect_id")}
    if kind == "font":
        return save_last(last, out, key, stem=args.name or "font"), cost, {}
    if kind in ("edit", "outfit", "fix"):
        if kind == "outfit":
            return save_last(last, out, key, stem="frame"), cost, {}
        img = last.get("image") or (last.get("images") or [None])[0]
        if img is not None:
            return [_save(img, out)], cost, {}
        links = [u for u in url_values(last.get("files")) if urllib.parse.urlparse(u).path.lower().endswith(".png")]
        if not links:
            raise ServiceError(f"{endpoint} finished without an image (got: {sorted(last)})")
        return [fetch_url(links[0], key, out)], cost, {}
    raise ToolError(f"unknown kind {kind}")


def summed_cost(usages):
    """Cost of several jobs (one per direction): the sum when they share a unit, else the last one's."""
    gens = [u.get("generations") for u in usages if isinstance(u, dict) and u.get("type") == "generations"]
    if gens and len(gens) == len(usages) and all(g is not None for g in gens):
        text = cost_text({"type": "generations", "generations": sum(gens)})
        return f"{text} ({len(gens)} jobs)" if len(gens) > 1 else text
    return cost_text(usages[-1]) if usages else ""


def character_zip(key, character_id, limit):
    """The character's zip; PixelLab answers 423 while its animations are still being written, so wait for it."""
    start = time.monotonic()
    while True:
        data = call("GET", f"/characters/{character_id}/zip", key, raw=True, pending_ok=True)
        if not isinstance(data, dict):
            return data
        if time.monotonic() - start >= limit:
            raise ServiceError(f"character {character_id} is paid for but still not downloadable after {limit} s: "
                               f"get it later, free, with `pixellab.py fetch --character-id {character_id} --out <folder>`")
        SLEEP(POLL_EVERY_S)


def save_tileset(key, tileset_id, out, kind):
    """Tiles of a finished top-down or sidescroller tileset (both are read from GET /tilesets/{id})."""
    data = call("GET", f"/tilesets/{tileset_id}", key)
    tiles = (data.get("tileset") or {}).get("tiles") or []
    if not tiles:
        raise ServiceError("the tileset job finished without tiles")
    files, index = [], []
    for i, t in enumerate(tiles):
        name = f"tile_{i:02d}.png"
        files.append(_save(t["image"], out / name))
        index.append({"file": name, "name": t.get("name"), "corners": t.get("corners"), "pattern_4x4": t.get("pattern_4x4")})
    how = ("Wang corner autotiling: match each map cell's corners to a tile's pattern_4x4 (0 lower, 1 upper, "
           "2 transition, 255 any)") if kind != "sidescroller" else \
        "Sidescroller platform tiles: pick by name (top, middle, edge pieces); the transition layer sits on the top edge"
    layout = out / "tileset.json"
    layout.write_text(json.dumps({"tile_size": (data.get("tileset") or {}).get("tile_size"), "tiles": index, "how": how},
                                 indent=2) + "\n", encoding="utf-8")
    return files + [layout]


def _save(img, path):
    png_from_b64(img, path)
    return path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_fetch(args):
    """Download a character you already paid for (with all its animations) by id: free, no generation."""
    key = get_key()
    if not key:
        raise ToolError(missing_key_help())
    out = Path(args.out)
    if out.exists() and not out.is_dir():
        raise ToolError(f"{out} is a file; `fetch` writes a folder there")
    if out.is_dir() and any(out.iterdir()) and not args.overwrite:
        raise ToolError(f"{out} already exists (--overwrite to replace it)")
    files = extract_zip(character_zip(key, args.character_id, args.wait), out)
    meta = {"tool": "pixellab", "endpoint": f"/characters/{args.character_id}/zip", "character_id": args.character_id,
            "date": datetime.date.today().isoformat(), "cost": "free (download)",
            "files": [f.resolve().relative_to(out.resolve()).as_posix() for f in files], "sha256": [sha256(f) for f in files]}
    (out / "pixellab.gen.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"[ OK ] {out}: {len([f for f in files if f.suffix == '.png'])} PNG(s) of character {args.character_id}")
    return 0


def outputs(args, kind, variants):
    base = Path(args.out)
    return [base if variants == 1 else base.with_name(f"{base.stem}_{n}{base.suffix}") for n in range(1, variants + 1)]


def check_outputs(args, kind, variants):
    """Refuse before spending: an existing output without --overwrite, a file where a folder goes, a --log
    destination outside the project or without an asset log."""
    for out in outputs(args, kind, variants):
        if kind not in FILE_KINDS and out.exists() and not out.is_dir():
            raise ToolError(f"{out} is a file; `{kind}` writes a folder there")
        if kind in FILE_KINDS and out.is_dir():   # --overwrite cannot turn a folder into a PNG
            raise ToolError(f"{out} is a folder; `{kind}` writes one file there")
        if out.exists() and not args.overwrite and (kind in FILE_KINDS or any(out.iterdir())):
            raise ToolError(f"{out} already exists (--overwrite to replace it)")
        if args.log:
            root = Path(args.root).resolve()
            if not (root / fetch_asset.ASSET_LOG).is_file():
                raise ToolError(f"{fetch_asset.ASSET_LOG.as_posix()} not found under {root} (pass --root)")
            try:   # a log without a table would reject the row only after the paid call
                fetch_asset.add_log_row((root / fetch_asset.ASSET_LOG).read_text(encoding="utf-8", errors="replace"),
                                        "", False)
            except fetch_asset.UsageError as exc:
                raise ToolError(str(exc))
            try:
                out.resolve().relative_to(root)
            except ValueError:
                raise ToolError(f"{out} is outside the project {root}; --log is for files that ship in the project")


def clear_previous(out):
    """--overwrite on a folder: remove the files the previous run listed, so stale frames do not linger."""
    side = out / "pixellab.gen.json"
    try:
        old = json.loads(side.read_text(encoding="utf-8")).get("files", [])
    except (OSError, ValueError):
        return
    root = out.resolve()
    for rel in old + ["pixellab.gen.json"]:
        target = (out / rel).resolve()
        if root in target.parents and target.is_file():
            target.unlink()


def cmd_generate(args, kind):
    endpoint, body = build(kind, args)
    if kind in FILE_KINDS and not args.out.lower().endswith(".png"):
        raise ToolError(f"--out must be a .png file for `{kind}`")
    variants = args.variants if kind == "image" else 1
    if not 1 <= variants <= MAX_VARIANTS:
        raise ToolError(f"--variants must be 1 to {MAX_VARIANTS} (each one is a paid generation)")
    shown = printable(body)
    if kind == "animate":
        shown["first_frame"] = f"<{Path(args.frame).as_posix()}, {Path(args.frame).stat().st_size} bytes>"
    if args.dry_run:
        print(f"[dry-run] POST {API}{endpoint}  x{variants}\n{json.dumps(shown, indent=2, ensure_ascii=False)}")
        return 0
    check_outputs(args, kind, variants)                   # everything a run could refuse, before anything is spent
    key = get_key()
    if not key:
        raise ToolError(missing_key_help())
    try:
        plan, _ = balance(key)
    except ToolError:
        raise
    except ServiceError:
        plan = "unknown"
    base = Path(args.out)
    for n in range(1, variants + 1):
        out = base if variants == 1 else base.with_name(f"{base.stem}_{n}{base.suffix}")
        if out.is_dir() and args.overwrite:
            clear_previous(out)
        files, cost, extra = run_job(kind, key, endpoint, body, out, args)
        pngs = [f for f in files if f.suffix.lower() == ".png"]
        meta = {"tool": "pixellab", "endpoint": endpoint, "request": shown, "date": datetime.date.today().isoformat(),
                "plan": plan, "cost": cost,
                "files": [f.name if kind in FILE_KINDS else f.resolve().relative_to(out.resolve()).as_posix() for f in files],
                "sha256": [sha256(f) for f in files]}
        meta.update({k: v for k, v in extra.items() if v})
        side = out.with_suffix(".gen.json") if kind in FILE_KINDS else out / "pixellab.gen.json"
        side.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[ OK ] {out}: {len(pngs)} PNG(s)" + (f", cost {cost}" if cost else ""))
        if kind == "animate":
            print(f"[info] preview: python tools/art/frames_to_gif.py {out} {out}.gif   (needs Pillow)")
        if args.log:
            write_log(args, kind, files, meta)
    return 0


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".", help="project root for --log (default: current folder)")
    common.add_argument("--debug", action="store_true", help="print requests (never the token) and tracebacks")
    gen = argparse.ArgumentParser(add_help=False)
    gen.add_argument("--out", required=True, help="image, prop, ui, edit, pixelate, fix: a .png file; the others: a folder")
    gen.add_argument("--seed", type=int, help="seed for a repeatable request (results may still differ)")
    gen.add_argument("--log", action="store_true", help="add the ASSET_LOG row and evidence file (files that ship)")
    gen.add_argument("--notes", default="", help="extra text for the ASSET_LOG Notes column")
    gen.add_argument("--overwrite", action="store_true", help="replace an existing output")
    gen.add_argument("--dry-run", action="store_true", help="print the request, send nothing, spend nothing")
    gen.add_argument("--wait", type=int, default=WAIT_S, help=f"seconds to wait for a job (default {WAIT_S})")
    look = argparse.ArgumentParser(add_help=False)
    look.add_argument("--outline", help="e.g. 'single color black outline', 'lineless'")
    look.add_argument("--shading", help="e.g. 'basic shading', 'flat shading'")
    look.add_argument("--detail", help="e.g. 'low detail', 'medium detail', 'highly detailed'")
    look.add_argument("--view", help="e.g. 'side', 'low top-down', 'high top-down'")

    ap = argparse.ArgumentParser(
        prog="pixellab.py",
        description="Generate pixel art with the PixelLab API (your token, your generations) and log it.",
        epilog=f"Token: environment variable {KEY_ENV}. Exit codes: 0 ok, 1 service failure, 2 usage, token, plan or credits.",
        parents=[common])
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    sub.required = True
    sub.add_parser("check", parents=[common], help="test the token and show the plan and what is left").set_defaults(
        fn=cmd_check)
    p = sub.add_parser("fetch", parents=[common], help="download a character you already made, with its animations (free)")
    p.add_argument("--character-id", required=True, help="the id (in a `character` folder's pixellab.gen.json)")
    p.add_argument("--out", required=True, help="a folder")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--wait", type=int, default=WAIT_S, help=f"seconds to wait while PixelLab finishes it (default {WAIT_S})")
    p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("image", parents=[common, gen, look], help="one image (sprite, item, portrait) as a PNG")
    p.add_argument("--text", required=True, help="what to draw, e.g. 'rusty iron key, top-down'")
    p.add_argument("--size", type=size_arg, default=size_arg("64"), help="64 or 64x48 pixels (16 to 400; default 64)")
    p.add_argument("--negative", default="", help="what to avoid")
    p.add_argument("--no-background", action="store_true", help="transparent background")
    p.add_argument("--variants", type=int, default=1, help=f"make N takes as <out>_1.png ... (N requests, at most {MAX_VARIANTS})")
    p.set_defaults(fn=lambda a: cmd_generate(a, "image"))
    p = sub.add_parser("character", parents=[common, gen, look], help="a character facing 4 or 8 directions (a folder of PNGs)")
    p.add_argument("--text", required=True, help="who it is, e.g. 'old gravekeeper with a lantern'")
    p.add_argument("--size", type=size_arg, default=size_arg("64"), help="frame size, 32 to 256 (default 64)")
    p.add_argument("--directions", type=int, choices=(4, 8), default=8, help="4 or 8 directions (default 8)")
    p.add_argument("--name", default="", help="a name for the character in your PixelLab library")
    p.add_argument("--legacy", action="store_true",
                   help="the older 4-direction endpoint: sizes 16 to 128 (v3 starts at 32); the canvas is about 40%% larger")
    p.set_defaults(fn=lambda a: cmd_generate(a, "character"))
    p = sub.add_parser("animate", parents=[common, gen], help="animate one frame from a text action (frame PNGs)")
    p.add_argument("--frame", required=True, help="the first frame, a PNG (e.g. a rotation from `character`)")
    p.add_argument("--action", required=True, help="what happens, e.g. 'walking', 'swinging a sword'")
    p.add_argument("--frames", type=int, default=8, help="4 to 16 frames (default 8: a walk cycle)")
    p.set_defaults(fn=lambda a: cmd_generate(a, "animate"))
    p = sub.add_parser("tileset", parents=[common, gen, look],
                       help="a top-down Wang tileset or a sidescroller platform set: tile PNGs + tileset.json (about 1)")
    p.add_argument("--kind", choices=("topdown", "sidescroller"), default="topdown", help="default topdown")
    p.add_argument("--lower", required=True, help="top-down: the lower terrain ('deep water'); sidescroller: the platform ('stone bricks')")
    p.add_argument("--upper", default="", help="top-down only: the upper terrain, e.g. 'sandy beach'")
    p.add_argument("--transition", default="", help="top-down: what lies between ('wet sand'); sidescroller: the top layer ('moss')")
    p.add_argument("--tile-size", type=int, choices=(16, 32), default=16, help="16 or 32 pixels (default 16)")
    p.set_defaults(fn=lambda a: cmd_generate(a, "tileset"))

    look2 = argparse.ArgumentParser(add_help=False)
    for flag, eg in (("--outline", "'single color outline', 'lineless'"), ("--shading", "'basic shading'"),
                     ("--detail", "'medium detail'")):
        look2.add_argument(flag, help=f"e.g. {eg}")
    p = sub.add_parser("animate-character", parents=[common, gen],
                       help="animate a character made by `character` (keeps its look; best for attacks and props)")
    p.add_argument("--from", dest="source", help="the folder `character` wrote (its pixellab.gen.json has the id)")
    p.add_argument("--character-id", help="or the PixelLab character id")
    p.add_argument("--mode", choices=("template", "skeleton-v3", "v3", "pixminimax"), default="template",
                   help="template: a stock motion, 1 per direction (big props can vanish); skeleton-v3: the same motion "
                        "posed on your character, keeps props, 2 to 4 per direction; v3 / pixminimax: from --action text")
    p.add_argument("--template", help="template or skeleton-v3: e.g. walk, breathing-idle, cross-punch, attack, backflip")
    p.add_argument("--action", help="v3 or pixminimax: what happens, e.g. 'swinging a huge gauntlet'")
    p.add_argument("--frames", type=int, default=8, help="v3: 4 to 16, even; pixminimax: a multiple of 4 up to 40 (default 8)")
    p.add_argument("--directions", default="", help="comma list, e.g. south,east (default: all for template, south for custom)")
    p.add_argument("--name", default="", help="the animation's name in your PixelLab library")
    p.set_defaults(fn=lambda a: cmd_generate(a, "animate-character"))
    p = sub.add_parser("iso-tile", parents=[common, gen, look2], help="one isometric tile or block (about 1)")
    p.add_argument("--text", required=True, help="e.g. 'mossy stone block'")
    p.add_argument("--size", type=size_arg, default=size_arg("32"), help="16 to 64 (default 32)")
    p.add_argument("--shape", choices=("thick tile", "thin tile", "block"), default="block", help="default block")
    p.set_defaults(fn=lambda a: cmd_generate(a, "iso-tile"))
    p = sub.add_parser("tiles-pro", parents=[common, gen],
                       help="[paid plan only] pro tiles: variations, a connectable terrain set, road autotiles or a "
                            "building kit, many shapes (10 to 25)")
    p.add_argument("--text", required=True, help="number the variations: '1). grass 2). dirt 3). stone'; a set: 'grass to water'")
    p.add_argument("--type", choices=("square_topdown", "isometric", "oblique", "hex", "hex_pointy", "octagon"),
                   default="square_topdown", help="tile shape (default square_topdown)")
    p.add_argument("--tile-size", type=int, default=32, help="16 to 128 (default 32)")
    p.add_argument("--view-angle", choices=("top-down", "high top-down", "low top-down", "side"), default="low top-down",
                   help="how much depth the tiles show (default low top-down)")
    p.add_argument("--feature", choices=("roads", "tileset", "building"),
                   help="a connectable set: roads (18 path pieces), tileset (terrain transitions), building (a kit)")
    p.set_defaults(fn=lambda a: cmd_generate(a, "tiles-pro"))
    p = sub.add_parser("vfx", parents=[common, gen],
                       help="an animated effect (hit, slash, explosion, aura): GIF + spritesheet + JSON (lite 1, pro 6)")
    p.add_argument("--text", required=True, help="e.g. 'brass piston punch impact, yellow sparks, 6 frames'")
    p.add_argument("--sprite", help="optional: a PNG of your sprite, so the effect fits around it")
    p.add_argument("--sprite-frames", type=int, default=1, help="frames in --sprite if it is a strip (1 to 32)")
    p.add_argument("--pro", action="store_true", help="the pro artist (6, 8 with a sprite; lite is 1)")
    p.add_argument("--game-pack", action="store_true", help="also a game-ready zip")
    p.add_argument("--name", default="", help="a name for the effect in your PixelLab library")
    p.set_defaults(fn=lambda a: cmd_generate(a, "vfx"))
    p = sub.add_parser("ui", parents=[common, gen, look2], help="a pixel-art UI panel, bar or frame as a PNG (10 to 25)")
    p.add_argument("--text", required=True, help="e.g. 'wooden dialog box with brass corners'")
    p.add_argument("--size", type=size_arg, default=size_arg("256x192"), help="192 to 688 per side (default 256x192)")
    p.add_argument("--name", default="", help="a name in your PixelLab library")
    p.set_defaults(fn=lambda a: cmd_generate(a, "ui"))
    p = sub.add_parser("font", parents=[common, gen], help="a pixel font: .ttf + glyph atlas PNG (15)")
    p.add_argument("--text", required=True, help="the look, e.g. 'chunky wooden sign letters'")
    p.add_argument("--weight", choices=("Regular", "Bold"), default="Regular")
    p.add_argument("--glyph", type=int, choices=(8, 16, 32, 64), default=16, help="glyph size in pixels (default 16)")
    p.add_argument("--name", default="", help="the font's name (also the file name)")
    p.set_defaults(fn=lambda a: cmd_generate(a, "font"))
    p = sub.add_parser("object", parents=[common, gen], help="a prop seen from 1 or 8 directions (10 to 25)")
    p.add_argument("--text", required=True, help="e.g. 'iron cannon on wheels'")
    p.add_argument("--directions", type=int, choices=(1, 8), default=1)
    p.add_argument("--size", type=int, default=64, help="1 direction: 16 to 256; 8 directions: 24 to 168 (default 64)")
    p.add_argument("--view", help="1 direction: top-down or sidescroller; 8: low top-down, high top-down or side")
    p.set_defaults(fn=lambda a: cmd_generate(a, "object"))
    p = sub.add_parser("prop", parents=[common, gen, look2], help="a single map prop with a transparent background (about 1)")
    p.add_argument("--text", required=True, help="e.g. 'a loaf of bread on a plate'")
    p.add_argument("--size", type=size_arg, default=size_arg("64"), help="32 to 400, e.g. 64 or 96x64 (default 64)")
    p.add_argument("--view", choices=("low top-down", "high top-down", "side"), default="high top-down")
    p.set_defaults(fn=lambda a: cmd_generate(a, "prop"))
    p = sub.add_parser("edit", parents=[common, gen], help="change one thing in a pixel-art PNG, keep the rest (1)")
    p.add_argument("--image", required=True, help="the PNG; sides a multiple of 4, at most 256 (pad, never rescale)")
    p.add_argument("--text", required=True, help="what to change, e.g. 'change ONLY the right hand into a clenched fist'")
    p.set_defaults(fn=lambda a: cmd_generate(a, "edit"))
    p = sub.add_parser("pixelate", parents=[common, gen], help="turn a picture (e.g. a concept image) into real pixel art (1)")
    p.add_argument("--image", required=True, help="the source PNG, 16 to 2048 per side")
    p.add_argument("--size", type=size_arg, default=size_arg("64"), help="output size, 16 to 512 (default 64)")
    p.set_defaults(fn=lambda a: cmd_generate(a, "pixelate"))
    p = sub.add_parser("fix", parents=[common, gen],
                       help="clean up a PNG: reduce-colors, correct (stray pixels), unzoom (upscaled art back to 1x), "
                            "remove-background, normal-map (about 0.1 each; normal-map pro 0.5)")
    p.add_argument("--op", required=True, choices=("reduce-colors", "correct", "unzoom", "remove-background", "normal-map"))
    p.add_argument("--image", required=True, help="the PNG to fix")
    p.add_argument("--colors", type=int, default=16, help="reduce-colors: how many (2 to 256, default 16)")
    p.add_argument("--strength", type=float, default=0.1, help="correct: 0 to 1 (default 0.1)")
    p.add_argument("--pro", action="store_true", help="normal-map: pro mode (0.5 instead of 0.1)")
    p.set_defaults(fn=lambda a: cmd_generate(a, "fix"))
    p = sub.add_parser("outfit", parents=[common, gen],
                       help="[paid plan only] put a reference outfit onto every frame of an animation (10 to 25)")
    p.add_argument("--reference", required=True, help="a PNG of the character wearing the outfit")
    p.add_argument("--frames", required=True, help="a folder of 2 to 16 animation frame PNGs, all one size")
    p.add_argument("--text", default="", help="extra instructions, e.g. 'keep the red nose'")
    p.set_defaults(fn=lambda a: cmd_generate(a, "outfit"))
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
        return args.fn(args)
    except ToolError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except ServiceError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[abort] interrupted (a job already sent keeps running on PixelLab's side)", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[error] unexpected failure: {exc!r}. Re-run with --debug.", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

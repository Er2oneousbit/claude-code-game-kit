#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# comfy_local.py
# Purpose : Run a saved ComfyUI workflow on your own GPU (a local ComfyUI server), save the images it makes into the
#           project without ComfyUI's embedded prompt and workflow, and (with --log) add the ASSET_LOG row and
#           evidence file: workflow, settings, models used, date, SHA-256 of each file. Opt-in: needs ComfyUI
#           installed and running (docs/sop/SOP-16-2d-art-pipeline.md "Generating pixel art locally").
# Usage   : python tools/art/comfy_local.py check                      # server up? version, GPU, free VRAM
#           python tools/art/comfy_local.py check --workflow art_src/comfy/npc.api.json   # every node installed?
#           python tools/art/comfy_local.py run --workflow art_src/comfy/npc.api.json \
#               --set "6.text=old lamplighter, top-down, pixel art" --seed 3001 --out assets/art/npcs --log
#           python tools/art/comfy_local.py run --workflow art_src/comfy/edit.api.json \
#               --image 12=assets/art/hero.png --set "Prompt.text=add a red scarf" --out assets/art/hero_scarf
#           python tools/art/comfy_local.py run --workflow ... --out ... --dry-run   # show the edited graph, send nothing
#           python tools/art/comfy_local.py strip media/*.png --out media/clean       # drop embedded workflow text
# Needs   : Python 3.8+ only. ComfyUI running (default http://127.0.0.1:8188, or COMFYUI_URL / --url), with the
#           node packs and models the workflow names. A workflow saved in API format (ComfyUI's "Export (API)";
#           the normal save format is refused with that hint).
# Exit    : 0 ok, 1 ComfyUI ran the job and it failed (out of memory, a node error), 2 usage, server not running,
#           missing nodes, or a workflow ComfyUI rejected
# Notes   : ComfyUI has no login, so this tool talks only to a server on this machine (127.0.0.1, localhost, ::1)
#           unless --allow-remote. Free per image; the cost is GPU time (each run prints it).
#           ComfyUI writes the full prompt and workflow (local paths included) into every PNG it saves; this tool
#           removes those text chunks before writing, and `strip` does the same for images saved by hand.
#           Other formats (GIF, WebP, video) are saved as they come, with a warning: check them before sharing.
#           Licensing: each model and LoRA has its own license; --log lists the models the workflow names so you
#           can check every model card before shipping (some are non-commercial).
#           Existing files are never replaced without --overwrite.
#           Tested offline against a stand-in server (test_comfy_local.py); live against ComfyUI 0.43.0 (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   server URL (--url, COMFYUI_URL, default) -> refuse a non-local host unless --allow-remote
#   check: GET /system_stats -> version, device, VRAM; --workflow: every class_type in GET /object_info?
#   run:   load the API-format workflow -> apply --image (POST /upload/image), --set NODE.INPUT=VALUE, --seed
#          -> missing nodes? stop -> dry run? print the graph, stop
#          -> POST /prompt -> poll GET /history/<id> until it has a status -> error? print ComfyUI's message
#          -> each output image: GET /view -> PNG: drop tEXt/iTXt/zTXt chunks -> write under --out (no overwrite)
#          -> comfy_local.gen.json (workflow SHA-256, settings, models, files) -> --log: ASSET_LOG row + evidence
#   strip: each PNG -> same chunk filter -> in place (--overwrite) or into --out
import argparse
import datetime
import hashlib
import ipaddress
import json
import os
import re
import struct
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fetch_asset  # noqa: E402  (shared ASSET_LOG helpers)

DEFAULT_URL = "http://127.0.0.1:8188"   # ComfyUI's default; it listens on this machine only unless started with --listen
URL_ENV = "COMFYUI_URL"
TIMEOUT_S = 60                          # one HTTP request
POLL_EVERY_S = 2
WAIT_S = 1800                           # how long to wait for a job (--wait); a Wan animation took about 2 min
MAX_DOWNLOAD = 500_000_000              # bytes: one output file
LOCAL_HOSTS = {"localhost"}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
TEXT_CHUNKS = {b"tEXt", b"iTXt", b"zTXt"}   # where ComfyUI stores "prompt" and "workflow"
SAVE_EXTENSIONS = {".png", ".gif", ".webp", ".jpg", ".jpeg", ".mp4", ".webm"}
MODEL_EXTENSIONS = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin", ".sft")
PROMPT_INPUTS = ("text", "prompt", "positive", "text_g", "text_l")   # inputs that usually hold the prompt
SEED_INPUTS = ("seed", "noise_seed")
LOG_TYPES = ("art", "sprite", "tileset", "ui", "vfx", "other")
LICENSE = "Per model: check each model and LoRA card before shipping (some are non-commercial)"
USER_AGENT = "claude-code-game-kit comfy_local.py"
GEN_FILE = "comfy_local.gen.json"
DEBUG = False
SLEEP = time.sleep                      # the exam replaces it
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never send local traffic through a proxy


class ToolError(Exception):
    """Exit 2: something the user can fix (usage, server not running, missing nodes, a rejected workflow)."""


class JobError(Exception):
    """Exit 1: ComfyUI ran the job and it failed."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


# ---- Server ------------------------------------------------------------------------
def server_url(args):
    """The base URL, refused when it points off this machine (ComfyUI has no login) unless --allow-remote."""
    url = (args.url or os.environ.get(URL_ENV, "") or DEFAULT_URL).strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError(f"--url must look like {DEFAULT_URL}, got {url!r}")
    host = parts.hostname
    local = host.lower() in LOCAL_HOSTS
    if not local:
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
    if not local and not args.allow_remote:
        raise ToolError(f"{host} is not this machine. ComfyUI has no login, so anyone who can reach it can run code on "
                        "it; this tool talks to a local server only. Pass --allow-remote if you really mean it.")
    return url


def http(method, url, body=None, headers=None):
    """(status, body bytes). Connection refused becomes a ToolError with the fix."""
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"User-Agent": USER_AGENT, **(headers or {})})
    dbg(f"{method} {url}")
    try:
        with OPENER.open(req, timeout=TIMEOUT_S) as resp:
            data = resp.read(MAX_DOWNLOAD + 1)
            if len(data) > MAX_DOWNLOAD:
                raise ToolError(f"response from {url} is over {MAX_DOWNLOAD:,} bytes")
            return resp.status, data
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(1_000_000)
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
        base = url.split("/", 3)
        raise ToolError(f"no ComfyUI answering at {'/'.join(base[:3])} ({getattr(exc, 'reason', exc)}). Start it (its "
                        "launcher, or `python main.py` in the ComfyUI folder), wait for 'To see the GUI go to', "
                        f"then retry. Another address: --url or {URL_ENV}.")


def get_json(base, path):
    status, data = http("GET", base + path)
    if status != 200:
        raise ToolError(f"GET {path} answered HTTP {status}: {data[:300].decode('utf-8', 'replace')}")
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:
        raise ToolError(f"GET {path} did not return JSON; is {base} really ComfyUI?")


def system_text(stats):
    sysinfo = stats.get("system", {})
    devs = stats.get("devices") or [{}]
    dev = devs[0]
    gb = lambda b: f"{(b or 0) / 1024 ** 3:.1f} GB"  # noqa: E731
    return (f"ComfyUI {sysinfo.get('comfyui_version', '?')}, Python {str(sysinfo.get('python_version', '?')).split()[0]}, "
            f"{str(dev.get('name', 'no GPU reported')).split(' : ')[0]}: {gb(dev.get('vram_free'))} of {gb(dev.get('vram_total'))} VRAM free")


# ---- Workflow ----------------------------------------------------------------------
def load_workflow(path):
    p = Path(path)
    if not p.is_file():
        raise ToolError(f"workflow {p} not found")
    try:
        wf = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ToolError(f"workflow {p} is not valid JSON: {exc}")
    if isinstance(wf, dict) and "nodes" in wf and "links" in wf:
        raise ToolError(f"{p} is in ComfyUI's normal save format. Open it in ComfyUI and save it in API format "
                        "(the Workflow menu's 'Export (API)'), then pass that file.")
    if not isinstance(wf, dict) or not wf or not all(
            isinstance(n, dict) and "class_type" in n and isinstance(n.get("inputs"), dict) for n in wf.values()):
        raise ToolError(f"{p} is not an API-format workflow (a map of node id -> class_type and inputs)")
    return wf


def find_node(wf, ref):
    """A node id, or a node title (_meta.title) that names exactly one node."""
    if ref in wf:
        return ref
    hits = [nid for nid, n in wf.items() if (n.get("_meta") or {}).get("title") == ref]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise ToolError(f"title {ref!r} names {len(hits)} nodes ({', '.join(hits)}); use the node id")
    titles = sorted({(n.get('_meta') or {}).get('title', '') for n in wf.values()} - {""})
    raise ToolError(f"no node {ref!r} in the workflow. Ids: {', '.join(sorted(wf, key=str))}"
                    + (f"; titles: {', '.join(titles)}" if titles else ""))


def parse_value(text):
    """JSON when it parses (numbers, true, lists), else the plain string."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def apply_sets(wf, sets):
    applied = []
    for item in sets or []:
        target, sep, value = item.partition("=")
        node_ref, dot, name = target.rpartition(".")
        if not sep or not dot or not node_ref or not name:
            raise ToolError(f"--set {item!r}: use NODE.INPUT=VALUE, e.g. 6.text=\"a lamp post\" or KSampler.steps=8")
        nid = find_node(wf, node_ref)
        inputs = wf[nid]["inputs"]
        if name not in inputs:
            raise ToolError(f"node {nid} ({wf[nid]['class_type']}) has no input {name!r}; it has: "
                            f"{', '.join(sorted(inputs))}")
        if isinstance(inputs[name], list):
            raise ToolError(f"{nid}.{name} is wired to another node; change that node instead")
        inputs[name] = parse_value(value)
        applied.append(f"{nid}.{name}")
    return applied


def apply_seed(wf, seed):
    hits = []
    for nid, node in wf.items():
        for name in SEED_INPUTS:
            if name in node["inputs"] and not isinstance(node["inputs"][name], list):
                node["inputs"][name] = seed
                hits.append(f"{nid}.{name}")
    if not hits:
        raise ToolError("--seed: no node in this workflow has a plain seed or noise_seed input")
    return hits


def multipart(field, filename, data, extra):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in extra.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    safe = filename.replace('"', "_")
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{safe}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def apply_images(base, wf, images, dry_run):
    """--image NODE=path: upload the file to ComfyUI's input folder and point the node's `image` input at it."""
    done = []
    for item in images or []:
        node_ref, sep, path = item.partition("=")
        if not sep:
            raise ToolError(f"--image {item!r}: use NODE=path, e.g. 12=assets/art/hero.png")
        nid = find_node(wf, node_ref)
        if "image" not in wf[nid]["inputs"]:
            raise ToolError(f"node {nid} ({wf[nid]['class_type']}) has no image input (use a LoadImage node)")
        src = Path(path)
        if not src.is_file():
            raise ToolError(f"--image file {src} not found")
        name = src.name
        if not dry_run:
            body, ctype = multipart("image", src.name, src.read_bytes(), {"overwrite": "true", "type": "input"})
            status, data = http("POST", base + "/upload/image", body, {"Content-Type": ctype})
            if status != 200:
                raise ToolError(f"upload of {src} failed: HTTP {status} {data[:200].decode('utf-8', 'replace')}")
            info = json.loads(data.decode("utf-8"))
            name = f"{info['subfolder']}/{info['name']}" if info.get("subfolder") else info["name"]
        wf[nid]["inputs"]["image"] = name
        done.append(f"{nid}.image={name}")
    return done


def missing_nodes(wf, object_info):
    return sorted({n["class_type"] for n in wf.values()} - set(object_info))


def models_in(wf):
    found = set()
    for node in wf.values():
        for value in node["inputs"].values():
            if isinstance(value, str) and value.lower().endswith(MODEL_EXTENSIONS):
                found.add(value.replace("\\", "/"))
    return sorted(found)


def prompt_in(wf):
    for node in wf.values():
        for name in PROMPT_INPUTS:
            value = node["inputs"].get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


# ---- Job ---------------------------------------------------------------------------
def node_errors_text(body):
    try:
        err = json.loads(body.decode("utf-8"))
    except ValueError:
        return body[:500].decode("utf-8", "replace")
    lines = [str((err.get("error") or {}).get("message", "ComfyUI rejected the workflow"))]
    for nid, info in (err.get("node_errors") or {}).items():
        for e in info.get("errors", []):
            lines.append(f"  node {nid} ({info.get('class_type', '?')}): {e.get('message', '')} {e.get('details', '')}".rstrip())
    return "\n".join(lines)


def queue(base, wf):
    body = json.dumps({"prompt": wf, "client_id": uuid.uuid4().hex}).encode("utf-8")
    status, data = http("POST", base + "/prompt", body, {"Content-Type": "application/json"})
    if status != 200:
        raise ToolError("ComfyUI refused the workflow:\n" + node_errors_text(data))
    return json.loads(data.decode("utf-8"))["prompt_id"]


def wait_history(base, prompt_id, limit):
    start = time.monotonic()
    while True:
        hist = get_json(base, f"/history/{prompt_id}")
        entry = hist.get(prompt_id)
        status = (entry or {}).get("status") or {}
        if entry and (status.get("completed") or status.get("status_str") in ("success", "error")):
            if status.get("status_str") == "error":
                msgs = [m[1] for m in status.get("messages", []) if m and m[0] == "execution_error"]
                detail = "; ".join(f"node {m.get('node_id')} ({m.get('node_type')}): {m.get('exception_message', '').strip()}"
                                   for m in msgs) or "no message"
                raise JobError(f"ComfyUI ran the job and it failed: {detail}"
                               + (" (out of memory: close other GPU apps, lower the size, or start ComfyUI with "
                                  "--lowvram)" if "out of memory" in detail.lower() else ""))
            return entry, time.monotonic() - start
        if time.monotonic() - start > limit:
            raise JobError(f"no result after {limit} s (job {prompt_id} may still be running in ComfyUI; raise --wait)")
        SLEEP(POLL_EVERY_S)


def output_files(entry, include_temp):
    files = []
    for nid, out in (entry.get("outputs") or {}).items():
        for key in ("images", "gifs", "videos", "animated"):
            for item in out.get(key) or []:
                if isinstance(item, dict) and item.get("filename") and \
                        (item.get("type") == "output" or (include_temp and item.get("type") == "temp")):
                    files.append(item)
    return files


# ---- Files -------------------------------------------------------------------------
def strip_png(data):
    """The PNG without its text chunks (ComfyUI's prompt and workflow). Raises ToolError when it is not a PNG."""
    if not data.startswith(PNG_MAGIC):
        raise ToolError("not a PNG file")
    out, pos = [PNG_MAGIC], len(PNG_MAGIC)
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        end = pos + 12 + length
        if end > len(data):
            raise ToolError("PNG is truncated")
        if kind not in TEXT_CHUNKS:
            out.append(data[pos:end])
        pos = end
        if kind == b"IEND":
            break
    return b"".join(out)


def safe_name(name):
    base = re.sub(r"[^\w.\-]+", "_", Path(name.replace("\\", "/")).name).strip("._") or "image"
    return base[:100]


def write_new(path, data, overwrite):
    if path.exists() and not overwrite:
        raise ToolError(f"{path} exists; pass --overwrite to replace it on purpose")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ---- Log ---------------------------------------------------------------------------
def write_log(args, files, meta):
    """ASSET_LOG row + docs/licenses/A-NNNN.txt evidence, using fetch_asset's helpers."""
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
    log_text = log_path.read_text(encoding="utf-8")
    num, fill = fetch_asset.next_asset_id(log_text)
    asset_id = f"A-{num:04d}"
    folder = os.path.commonpath(rels) if len(rels) > 1 else ""
    shown = f"`{folder}/` ({len(rels)} files)" if folder and len(rels) > 3 else ", ".join(f"`{r}`" for r in rels)
    notes = "; ".join(x for x in [f"prompt: {meta['prompt'][:160]}" if meta["prompt"] else "",
                                  f"seed {meta['seed']}" if meta["seed"] is not None else "",
                                  f"models: {', '.join(meta['models'])}" if meta["models"] else "",
                                  f"GPU {meta['gpu_seconds']:.0f} s", args.notes or ""] if x)
    row = (f"| {asset_id} | {args.type} | {shown} | ComfyUI (local), workflow `{fetch_asset.md_cell(meta['workflow'])}` | "
           f"generated locally | {fetch_asset.md_cell(LICENSE)} |  | pre-generated | no | {meta['date']} | "
           f"{fetch_asset.md_cell(notes)} |")
    evidence = (f"{asset_id}  {args.type}  generated {meta['date']} with tools/art/comfy_local.py\n"
                f"Server   : {meta['server']}\n"
                f"Workflow : {meta['workflow']}  SHA-256 {meta['workflow_sha256']} (before the settings below)\n"
                f"Settings : {json.dumps(meta['settings'], ensure_ascii=False)}\n"
                f"Seed     : {meta['seed'] if meta['seed'] is not None else 'as saved in the workflow'}\n"
                f"Prompt   : {meta['prompt'] or 'none found'}\n"
                f"Models   : {', '.join(meta['models']) or 'none named'}\n"
                f"License  : {LICENSE}\n"
                + "".join(f"File     : {r}  SHA-256 {h}\n" for r, h in zip(rels, meta["sha256"])))
    log_path.write_bytes((fetch_asset.add_log_row(log_text, row, fill)).encode("utf-8"))
    lic_dir = root / fetch_asset.LICENSE_DIR
    lic_dir.mkdir(parents=True, exist_ok=True)
    (lic_dir / f"{asset_id}.txt").write_bytes((evidence).encode("utf-8"))
    print(f"[ OK ] {asset_id} added to {fetch_asset.ASSET_LOG.as_posix()}, evidence in "
          f"{(fetch_asset.LICENSE_DIR / (asset_id + '.txt')).as_posix()}")
    print("[note] check the license of every model listed above before shipping these files")


# ---- Commands ----------------------------------------------------------------------
def cmd_check(args):
    base = server_url(args)
    print(f"[ OK ] {system_text(get_json(base, '/system_stats'))}")
    if args.workflow:
        wf = load_workflow(args.workflow)
        missing = missing_nodes(wf, get_json(base, "/object_info"))
        if missing:
            raise ToolError(f"{args.workflow} needs node types this ComfyUI does not have: {', '.join(missing)}. "
                            "Install the node pack (review it first, SOP-16), restart ComfyUI, retry.")
        print(f"[ OK ] all {len(wf)} nodes of {args.workflow} are installed")
        models = models_in(wf)
        if models:
            print(f"[info] models it names (check each license): {', '.join(models)}")
    return 0


def cmd_run(args):
    base = server_url(args)
    wf = load_workflow(args.workflow)
    wf_sha = sha256(Path(args.workflow).read_bytes())
    out_dir = Path(args.out)
    if args.log and not (Path(args.root) / fetch_asset.ASSET_LOG).is_file():
        raise ToolError(f"{fetch_asset.ASSET_LOG.as_posix()} not found under {Path(args.root).resolve()} (pass --root)")
    settings = apply_sets(wf, args.set)
    if args.seed is not None:
        settings += apply_seed(wf, args.seed)
    settings += apply_images(base, wf, args.image, args.dry_run)
    if args.dry_run:
        print(json.dumps(wf, indent=2, ensure_ascii=False))
        print(f"[dry-run] nothing sent. Changed: {', '.join(settings) or 'nothing'}; models: "
              f"{', '.join(models_in(wf)) or 'none named'}")
        return 0
    stats = get_json(base, "/system_stats")
    missing = missing_nodes(wf, get_json(base, "/object_info"))
    if missing:
        raise ToolError(f"this ComfyUI lacks node types the workflow needs: {', '.join(missing)}")
    prompt_id = queue(base, wf)
    print(f"[....] queued job {prompt_id}; waiting (up to {args.wait} s)")
    entry, seconds = wait_history(base, prompt_id, args.wait)
    items = output_files(entry, args.include_temp)
    if not items:
        raise JobError("the job finished but saved no images (does the workflow end in a Save node?)")
    written, hashes = [], []
    for item in items:
        query = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                        "type": item.get("type", "output")})
        status, data = http("GET", f"{base}/view?{query}")
        if status != 200:
            raise JobError(f"could not fetch {item['filename']} (HTTP {status})")
        name = safe_name((args.prefix + "_" if args.prefix else "") + item["filename"])
        ext = Path(name).suffix.lower()
        if ext not in SAVE_EXTENSIONS:
            print(f"[skip] {item['filename']}: {ext or 'no extension'} is not an image or video type this tool saves")
            continue
        if ext == ".png":
            data = strip_png(data)
        else:
            print(f"[warn] {name}: {ext} files can carry the workflow too; this tool strips PNGs only")
        path = out_dir / name
        write_new(path, data, args.overwrite)
        written.append(path)
        hashes.append(sha256(data))
        print(f"[ OK ] {path.as_posix()} ({len(data):,} bytes)")
    if not written:
        raise JobError("nothing was saved")
    meta = {"date": datetime.date.today().isoformat(), "server": base, "workflow": Path(args.workflow).as_posix(),
            "workflow_sha256": wf_sha, "settings": args.set or [], "seed": args.seed, "prompt": prompt_in(wf),
            "models": models_in(wf), "gpu_seconds": seconds, "prompt_id": prompt_id,
            "comfyui": (stats.get("system") or {}).get("comfyui_version"),
            "files": [p.as_posix() for p in written], "sha256": hashes}
    write_new(out_dir / GEN_FILE, json.dumps(meta, indent=2, ensure_ascii=False).encode("utf-8"), True)
    print(f"[ OK ] {len(written)} file(s) in {seconds:.0f} s on the GPU; record in {(out_dir / GEN_FILE).as_posix()}")
    if args.log:
        write_log(args, written, meta)
    return 0


def cmd_strip(args):
    if not args.out and not args.overwrite:
        raise ToolError("pass --out <folder> for clean copies, or --overwrite to clean the files in place")
    count = 0
    for name in args.files:
        src = Path(name)
        if not src.is_file():
            raise ToolError(f"{src} not found")
        data = src.read_bytes()
        try:
            clean = strip_png(data)
        except ToolError as exc:
            raise ToolError(f"{src}: {exc}")
        dst = Path(args.out) / src.name if args.out else src
        write_new(dst, clean, args.overwrite)   # in place needs --overwrite (checked above)
        dropped = len(data) - len(clean)
        print(f"[ OK ] {dst.as_posix()}: {dropped:,} bytes of embedded text removed")
        count += 1
    print(f"[ OK ] {count} file(s) cleaned")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        description="Run saved ComfyUI workflows on this machine's GPU, save clean images, log them (SOP-16).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit: 0 ok, 1 the job failed in ComfyUI, 2 usage, server, missing nodes or a rejected workflow.\n"
               f"Env: {URL_ENV} (default {DEFAULT_URL}).")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", help=f"ComfyUI address (default {URL_ENV} or {DEFAULT_URL})")
    common.add_argument("--allow-remote", action="store_true",
                        help="allow a server that is not on this machine (ComfyUI has no login: think twice)")
    common.add_argument("--debug", action="store_true", help="print each request and full tracebacks")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", parents=[common], help="is ComfyUI up; with --workflow, are all its nodes installed")
    p.add_argument("--workflow", help="an API-format workflow JSON to check")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("run", parents=[common], help="run a workflow and save its images under --out",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="NODE is a node id from the workflow file or its title (ComfyUI's node title).\n"
                              "VALUE is parsed as JSON when it can be (8, 0.45, true), else used as text.")
    p.add_argument("--workflow", required=True, help="API-format workflow JSON (ComfyUI's 'Export (API)')")
    p.add_argument("--out", required=True, help="folder for the images and comfy_local.gen.json")
    p.add_argument("--set", action="append", metavar="NODE.INPUT=VALUE", help="change one input; repeat as needed")
    p.add_argument("--image", action="append", metavar="NODE=PATH", help="upload a picture into a LoadImage node")
    p.add_argument("--seed", type=int, help="set every seed / noise_seed input to this value")
    p.add_argument("--prefix", default="", help="put this in front of each saved file name")
    p.add_argument("--wait", type=int, default=WAIT_S, help=f"seconds to wait for the job (default {WAIT_S})")
    p.add_argument("--include-temp", action="store_true", help="also save preview (temp) images")
    p.add_argument("--overwrite", action="store_true", help="replace files that already exist")
    p.add_argument("--dry-run", action="store_true", help="print the edited workflow, send nothing")
    p.add_argument("--log", action="store_true", help="add the ASSET_LOG row and evidence file")
    p.add_argument("--root", default=".", help="project root for --log (default: current folder)")
    p.add_argument("--type", default="art", choices=LOG_TYPES, help="ASSET_LOG type for --log (default art)")
    p.add_argument("--notes", default="", help="extra text for the ASSET_LOG Notes column")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("strip", parents=[common], help="remove embedded prompt and workflow text from PNG files")
    p.add_argument("files", nargs="+", help="PNG files")
    p.add_argument("--out", help="write clean copies into this folder")
    p.add_argument("--overwrite", action="store_true", help="clean in place, or replace existing copies in --out")
    p.set_defaults(fn=cmd_strip)
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
    except JobError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[abort] interrupted (a queued job keeps running in ComfyUI; cancel it there)", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[error] unexpected failure: {exc!r}. Re-run with --debug.", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

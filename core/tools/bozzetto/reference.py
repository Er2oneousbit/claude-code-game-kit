#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# reference.py
# Purpose : `bozzetto.py reference`: a concept picture or an idea to model-ready reference views of a character:
#           the same design in a relaxed A-pose (arms about 35 degrees out, hands open, legs a little apart),
#           orthographic and straight-on, flat even light, plain light grey background, nothing else in frame, loose
#           cloth hanging. One picture per view (front, left, back, right), a turnaround sheet, a record and an asset
#           log row. The views feed `make --image` (front) or a multiview make.
# Usage   : python tools/bozzetto/bozzetto.py reference chr_hero --prompt "a lanky lighthouse keeper in a yellow coat"
#           python tools/bozzetto/bozzetto.py reference chr_hero --from art_src/hero_concept.png --seed 4
#           python tools/bozzetto/bozzetto.py reference chr_hero --from concept.png --with nanobanana --quote-only
#           python tools/bozzetto/bozzetto.py reference chr_hero --prompt "..." --with tripo --max-cost 40
#           python tools/bozzetto/bozzetto.py reference chr_hero --swap-sides     # left and right came back swapped
#           Options: --with local|nanobanana|tripo, --views front,left,back,right, --seed N, --model ID,
#           --max-cost N (dollars for nanobanana, credits for tripo), --quote-only, --no-reuse, --project DIR,
#           --overwrite, --no-log, --wait S, --url/--allow-remote (local), --swap-sides, --debug
# Needs   : Python 3.8+ (standard library; Pillow only speeds up the sheet and reads JPEG/WebP). local: a running
#           ComfyUI with Dotwork's Qwen-Image-Edit-2511 files (route qwen_rotate in its models.lock.json, plus the
#           ComfyUI-GGUF node pack) and, for --prompt, its FLUX.2 klein 4B files. nanobanana: GEMINI_API_KEY from a
#           project with billing on (a free-tier key gets HTTP 429 with an image quota of 0, measured 2026-11-11: the
#           run says so and stops). tripo: TRIPO_API_KEY with API credits.
# Exit    : 0 ok (or the quote printed), 1 a generation call or job failed, 2 usage, environment, a missing key,
#           the cost cap, or files in the way
# Notes   : Routes. local (default, free): FLUX.2 klein draws the front from a prompt, or Qwen-Image-Edit re-poses a
#           concept to the A-pose front; Qwen-Image-Edit with the Multiple-Angles LoRA turns the front to each other
#           view (as Dotwork's rotations do). nanobanana: Google's Gemini image model, one generateContent call per
#           view in one conversation (the front first, then "the same character from its left side" ...). tripo:
#           Tripo's text-to-image or image-to-image for the front, then its image-to-multiview for the rest.
#           Paid routes: a quote first, --max-cost checked before every call against what this run has spent, a
#           journal (reference/journal.json, outputs in reference/steps/) so a rerun reuses what was paid for, the
#           actual cost recorded, keys only ever in request headers, metadata stripped from every picture sent out.
#           Prices and terms were read on 2026-11-11 and are marked (verify) in the README.
#           Tripo goes through tripo.py's shared Client and Budget (the image endpoints, models and quote are there);
#           the per-picture journal here also serves the Gemini route, so it stays this tool's own.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   plan:    name, --from xor --prompt, views (front always), route, model, cap, files in the way, asset log, key
#   quote:   per route: which steps the journal already holds -> what is left -> a price -> print [-> --quote-only stop]
#            paid: the quote over --max-cost stops here, before any call
#   run:     local: ComfyUI preflight (nodes, model files) -> front (klein job | upload concept + Qwen re-pose)
#                   -> free VRAM -> one Qwen + Angle LoRA job per other view
#            nanobanana: history = [user: concept + re-pose | user: prompt]; per view: journal hit -> reuse, else
#                   cap check -> generateContent(history) -> picture + model parts (thought signatures kept) +
#                   usage -> cost -> journal; history += model turn, next user turn
#            tripo: front: journal hit | a task left running -> wait for it | cap + balance -> (upload concept)
#                   -> text-to-image or image-to-image -> journal as running -> wait -> download -> journal done
#                   others: the same around upload(front) -> image-to-multiview -> download each view
#   write:   views as PNG (metadata stripped) -> concept copy -> sheet -> look check -> record -> asset log row ->
#            print the next command (make --image front.png; multiview make with all four)
#   swap:    --swap-sides: record -> swap left.png and right.png -> swap their record entries (each keeps the prompt
#            that made it, under its new file name and hash) -> sheet -> look -> record -> the same log row updated
import base64
import datetime
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import refsheet
import tripo as tp   # the one Tripo client in Bozzetto (Client, Budget; image tasks), shared with make and rig

bz = None   # bozzetto.py binds itself here (bind)

HERE = Path(__file__).resolve().parent
WORKFLOW_EDIT = HERE / "workflows" / "qwen_edit_reference.api.json"
EDIT_NODES = {"image": "INPUT image", "prompt": "Edit prompt", "seed": "SEED", "angle": "Angle LoRA",
              "output": "OUTPUT view"}
VIEWS = ("front", "left", "back", "right")
ROUTES = ("local", "nanobanana", "tripo")
REF_DIR = "reference"
RECORD = "reference.json"
JOURNAL = "journal.json"
STEPS = "steps"                     # pictures the routes made, kept for reuse and for the record
SHEET = "sheet.png"
WAIT_S = 1800
MAX_DOWNLOAD = 64 * 1024 * 1024
CONCEPT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}

# ---- what every route is asked for ------------------------------------------------------------------------------
POSE = ("a relaxed A-pose, standing straight, both arms held about 35 degrees out from the body with a clear gap "
        "between each arm and the torso, hands open with the fingers relaxed, legs a little apart, feet flat on "
        "the ground")
CLOTH = "loose cloth such as scarves, capes, coat tails and long hair hangs straight down under gravity, not blowing"
LOOK = ("orthographic straight-on camera at chest height with no perspective distortion, flat even lighting with no "
        "cast shadows, plain light grey background, nothing else in frame: no ground, no props, no text, no frame")
FRONT_FROM_PROMPT = ("{prompt}. Full-body character model reference, front view facing the viewer, the whole figure "
                     "from head to feet centered with space around it, " + POSE + ". " + CLOTH + ". " + LOOK + ".")
REPOSE = ("Redraw this exact character as a full-body front view model reference. Keep every design detail "
          "identical: face, hair, body proportions, outfit, colours, materials, markings and accessories. Change "
          "only the pose, the camera, the light and the background: " + POSE + "; " + CLOTH + "; " + LOOK
          + ". Show the whole figure from head to feet, centered.")
TURN = ("Now show this exact same character, in the same A-pose, {how}. Keep every design detail, proportion and "
        "colour identical; the same scale and framing with the feet on the same line; the same flat light and plain "
        "light grey background; orthographic, nothing else in frame.")
TURN_HOW = {"left": "from its left side: a side profile of its left side, facing the left edge of the picture",
            "back": "from directly behind: the back of the head and body toward the viewer",
            "right": "from its right side: a side profile of its right side, facing the right edge of the picture"}
# Qwen-Image-Edit-2511 Multiple-Angles LoRA (fal): "<sks> <azimuth> <elevation> <distance>", as Dotwork's
# rotations send it; its azimuth names the side the camera sees (left side view: the figure faces picture-left)
ANGLE_PROMPT = "<sks> {azimuth} eye-level shot medium shot"
AZIMUTH = {"left": "left side view", "back": "back view", "right": "right side view"}
ANGLE_STRENGTH = 0.9
# the first two live runs (2026-11-11) got "left side view" back facing picture-right; Dotwork saw the LoRA read the
# sides either way from one character to the next, so every run asks for a look instead of trusting the label
SIDES_NOTE = ("left.png should show the character's left side, facing the picture's left edge, and right.png the "
              "other way; generators mix the two up, so if they are swapped, `reference <name> --swap-sides` swaps "
              "them with the sheet, the record and the asset log (no GPU, no cost)")

# ---- Google Gemini (Nano Banana) --------------------------------------------------------------------------------
GEMINI_ENV = "GEMINI_API_KEY"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"   # the exam points this at a stand-in
GEMINI_MODEL = "gemini-nano-banana-2.1"
# USD per 1M tokens: input, text and thinking output, image output; output tokens per 1K image (read 2026-11-11 on
# aistudio.google.com/docs/pricing, Standard tier; verify)
GEMINI_PRICES = {
    "gemini-nano-banana-2.1": {"in": 1.50, "text_out": 7.50, "image_out": 30.00, "image_tokens": 1120},
    "gemini-3.1-flash-image": {"in": 0.50, "text_out": 3.00, "image_out": 60.00, "image_tokens": 1120},
    "gemini-3.1-flash-lite-image": {"in": 0.25, "text_out": 1.50, "image_out": 30.00, "image_tokens": 1120},
    "gemini-3-pro-image": {"in": 2.00, "text_out": 12.00, "image_out": 120.00, "image_tokens": 1120},
    "gemini-2.5-flash-image": {"in": 0.30, "text_out": 2.50, "image_out": 30.00, "image_tokens": 1290},
}
GEMINI_IN_IMAGE_TOKENS = 1120       # quote estimate per picture in the conversation (verify)
GEMINI_TURN_TOKENS = 400            # quote estimate per text turn
GEMINI_THINK_TOKENS = 2000          # quote allowance for thinking tokens per call
GEMINI_TIMEOUT_S = 360
GEMINI_MAX_COST = 1.00              # dollars, default --max-cost

# ---- Tripo: the client, endpoints, image models and quote live in tripo.py (shared with make and rig) -------------
TRIPO_ENV = tp.TRIPO_ENV
TRIPO_MAX_COST = 40                 # credits (1 credit = $0.01), default --max-cost

# ---- terms (record and asset log) ------------------------------------------------------------------------------
TERMS = {
    "local": {"owner": "you: generated on your own GPU, no service terms",
              "licence": "models Apache-2.0 (FLUX.2 klein 4B, Qwen-Image-Edit-2511 and its LoRAs: Dotwork's "
                         "models.lock.json)",
              "notes": "whether AI output can be owned depends on your country (verify)"},
    "nanobanana": {"owner": "you: the Gemini API Additional Terms (effective 2026-03-23, 'Use of Generated Content') "
                            "say Google won't claim ownership of generated content, and may generate the same or "
                            "similar content for others (verify)",
                   "licence": "Gemini API Additional Terms",
                   "notes": "paid tier: prompts and outputs are not used to improve Google's products, logged for a "
                            "limited time for abuse checks; every image carries a SynthID watermark (verify)"},
    "tripo": {"owner": "you, on paid API credits (Tripo terms 5.2.2); outputs from free credits are not yours (verify)",
              "licence": "Tripo terms (paid output)",
              "notes": "Tripo's banana models carry Google's invisible watermark (Tripo docs) (verify)"},
}

OPENER = tp.opener()                # Gemini calls: the key in a header, so no redirect is followed; the exam replaces it


class Spent:
    """What this run spends, against --max-cost (journal reuse costs nothing)."""

    def __init__(self, cap, unit):
        self.cap, self.unit, self.new = cap, unit, 0.0

    def allow(self, more, what):
        if self.new + more > self.cap + 1e-9:
            raise bz.ToolError(f"{what} would take this run to {fmt(self.new + more, self.unit)}, over --max-cost "
                               f"{fmt(self.cap, self.unit)}; what was paid for so far is kept in "
                               f"{REF_DIR}/{JOURNAL} and a rerun reuses it")

    def add(self, cost):
        self.new += cost


def fmt(amount, unit):
    return f"${amount:.4f}" if unit == "usd" else f"{amount:g} credits"


def bind(module):
    global bz
    bz = module


def sha(data):
    return hashlib.sha256(data).hexdigest()


def key_of(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()[:16]


scrub = tp.scrub   # the key out of anything shown, even when a server echoes it


def clean(data):
    """A picture without its metadata (text chunks, EXIF, XMP); a format strip_picture does not know is refused."""
    try:
        return bz.cl.strip_picture(data)
    except bz.cl.ToolError:
        raise bz.JobError("the service sent something that is not a PNG, JPEG or WebP picture")


# ---- journal (paid routes) --------------------------------------------------------------------------------------
class Journal:
    """reference/journal.json: every paid step by key, written when a task is created and when it ends. A finished
    step's picture lives in reference/steps/<key>.<ext>; a rerun with the same inputs reuses it."""

    def __init__(self, folder, route, reuse):
        self.folder, self.path = folder, folder / JOURNAL
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        self.doc = doc if isinstance(doc, dict) else {}
        self.doc.setdefault("steps", {})
        self.doc["route"] = route
        self.reuse = reuse

    @property
    def steps(self):
        return self.doc["steps"]

    def done(self, key):
        """The finished entry and its picture bytes, or (None, None). A multiview entry holds several files (a dict
        `files`, view -> path): (entry, None) when every one is still there."""
        e = self.steps.get(key) or {}
        if not self.reuse or e.get("status") != "success":
            return None, None
        if isinstance(e.get("files"), dict):
            ok = e["files"] and all((self.folder / f).is_file() for f in e["files"].values())
            return (e, None) if ok else (None, None)
        p = self.folder / e.get("file", "")
        if not e.get("file") or not p.is_file() or sha(p.read_bytes()) != e.get("sha256"):
            return None, None
        return e, p.read_bytes()

    def running(self, key):
        e = self.steps.get(key) or {}
        return e if self.reuse and e.get("status") == "running" and e.get("task_id") else None

    def put(self, key, entry):
        self.steps[key] = entry
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.doc, indent=2) + "\n", encoding="utf-8")

    def keep(self, key, data, entry):
        """Store a paid picture (metadata stripped) and mark its step finished. Returns the stored bytes."""
        data = clean(data)
        ext = ".png" if data.startswith(refsheet.PNG_MAGIC) else ".jpg" if data[:2] == b"\xff\xd8" else ".webp"
        (self.folder / STEPS).mkdir(parents=True, exist_ok=True)
        rel_file = f"{STEPS}/{key}{ext}"
        (self.folder / rel_file).write_bytes(data)
        self.put(key, dict(entry, status="success", file=rel_file, sha256=sha(data)))
        return data


# ---- HTTP ---------------------------------------------------------------------------------------------------------
def http_json(method, url, headers, body=None, raw=None, timeout=180, secret=""):
    """(status, parsed JSON or None, text). Network trouble is a ToolError; the key never reaches a message: the
    text is scrubbed before it is parsed, so a message taken from the parsed answer is clean too."""
    data = json.dumps(body).encode("utf-8") if body is not None else raw
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    bz.dbg(f"{method} {url.split('?')[0]}")
    try:
        with OPENER(req, timeout=timeout) as r:
            text = r.read(MAX_DOWNLOAD).decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read(100_000).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        raise bz.ToolError(scrub(f"cannot reach {url.split('/')[2]}: {getattr(e, 'reason', e)}", secret))
    text = scrub(text, secret)
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    return status, doc if isinstance(doc, dict) else None, text


# ---- plan -----------------------------------------------------------------------------------------------------------
def parse_views(text):
    want = [v.strip().lower() for v in (text or "").split(",") if v.strip()]
    bad = [v for v in want if v not in VIEWS]
    if bad:
        raise bz.ToolError(f"--views has no view {bad[0]!r}: choose from {','.join(VIEWS)}")
    if not want:
        raise bz.ToolError("--views needs at least one view")
    if "front" not in want:
        print("[info] --views: the front is always made (every other view is turned from it)")
    return [v for v in VIEWS if v in want or v == "front"]


class Plan:
    """Everything reference decides before any GPU time or paid call."""

    def __init__(self, args):
        self.root = Path(args.project).resolve()
        if not self.root.is_dir():
            raise bz.ToolError(f"--project {args.project} is not a folder")
        if not bz.NAME_RULE.match(args.name):
            raise bz.ToolError(f"name {args.name!r}: lowercase letters, digits and underscores, starting with a "
                               "letter (chr_<name>, npc_<name>)")
        if bool(args.concept) == bool(args.prompt):
            raise bz.ToolError("give exactly one of --from <concept picture> or --prompt \"...\"")
        if args.prompt is not None and not args.prompt.strip():
            raise bz.ToolError("--prompt is empty")
        self.name, self.route = args.name, args.backend
        self.views = parse_views(args.views)
        self.dir = self.root / bz.SRC_ROOT / self.name / REF_DIR
        self.prompt = args.prompt.strip().rstrip(".") if args.prompt else None
        self.concept = self.concept_bytes = self.concept_type = None
        if args.concept:
            p = Path(args.concept)
            if not p.is_absolute() and not p.is_file():
                p = self.root / args.concept
            if not p.is_file():
                raise bz.ToolError(f"--from {args.concept} not found")
            if p.suffix.lower() not in CONCEPT_TYPES:
                raise bz.ToolError("--from must be a .png, .jpg or .webp picture")
            try:   # what goes out (to ComfyUI or a paid service) and what is kept: EXIF, XMP and text removed
                self.concept_bytes = bz.comfy(bz.cl.strip_picture, p.read_bytes())
            except bz.ToolError as exc:
                raise bz.ToolError(f"--from {p.name}: {exc}")
            b = self.concept_bytes   # the type the bytes really are, whatever the file is called
            ctype = "image/png" if b.startswith(refsheet.PNG_MAGIC) else "image/jpeg" if b[:2] == b"\xff\xd8" \
                else "image/webp"
            if self.route == "tripo" and ctype == "image/webp":
                raise bz.ToolError("Tripo's image-to-image refuses WebP on some routes: save the concept as PNG first")
            self.concept, self.concept_type = p, ctype
        if args.wait <= 0:
            raise bz.ToolError("--wait must be a positive number of seconds")
        # route model and cost unit
        if self.route == "local":
            if args.model:
                raise bz.ToolError("--model is for the paid routes; the local route uses Dotwork's locked models")
            self.model, self.unit, self.cap = "local", "free", 0
        elif self.route == "nanobanana":
            self.model = args.model or GEMINI_MODEL
            if self.model not in GEMINI_PRICES:
                raise bz.ToolError(f"no price on record for --model {self.model}, so no honest quote; known: "
                                   f"{', '.join(GEMINI_PRICES)} (add its price to GEMINI_PRICES in reference.py)")
            self.unit, self.cap = "usd", GEMINI_MAX_COST if args.max_cost is None else args.max_cost
        else:
            self.model = args.model or tp.IMAGE_MODEL
            if self.model not in tp.IMAGE_MODELS:
                raise bz.ToolError(f"--model {self.model}: Tripo image models wired in here: {', '.join(tp.IMAGE_MODELS)}")
            self.unit, self.cap = "credits", TRIPO_MAX_COST if args.max_cost is None else args.max_cost
        if self.route != "local" and self.cap <= 0:
            raise bz.ToolError("--max-cost must be a positive number")
        self.log = not args.no_log
        self.log_path = self.root / bz.fetch_asset.ASSET_LOG
        self.files = {v: self.dir / f"{v}.png" for v in self.views}

    def in_the_way(self):
        return [p for p in list(self.files.values()) + [self.dir / SHEET, self.dir / RECORD] if p.exists()]


def preflight(args, plan):
    if not args.overwrite:
        busy = plan.in_the_way()
        if busy:
            raise bz.ToolError(f"{', '.join(bz.rel(plan.root, p) for p in busy)} already exist(s); pass --overwrite "
                               "to make these views again (a paid route reuses what its journal holds; --no-reuse "
                               "pays again)")
    if plan.log and not plan.log_path.is_file():
        raise bz.ToolError(f"{bz.fetch_asset.ASSET_LOG.as_posix()} not found under {plan.root}: run from the game's "
                           "root folder (or --project), or pass --no-log")
    if not args.quote_only:
        env = {"nanobanana": GEMINI_ENV, "tripo": TRIPO_ENV}.get(plan.route)
        if env and not os.environ.get(env):
            raise bz.ToolError(f"--with {plan.route} needs {env} (a paid key; it is read from the environment and "
                               "never written anywhere). --quote-only prints the price without it")


# ---- local route: ComfyUI ----------------------------------------------------------------------------------------
def qwen_models():
    """The Qwen-Image-Edit files Dotwork's rotations load (route qwen_rotate in its register)."""
    try:
        lock = json.loads(bz.DOTWORK_LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [m for m in lock.get("models", []) if "qwen_rotate" in m.get("routes", [])]


class Local:
    unit = "free"

    def __init__(self, args, plan):
        self.args, self.plan = args, plan

    def quote(self):
        return 0.0, (f"local: free on your GPU, {len(self.plan.views)} ComfyUI job(s) ("
                     + ("FLUX.2 klein 4B for the front, " if self.plan.prompt else "")
                     + "Qwen-Image-Edit-2511)")

    def preflight(self):
        args, plan = self.args, self.plan
        base = bz.comfy_base(args)
        self.stats = bz.comfy(bz.cl.get_json, base, "/system_stats")
        info = bz.comfy(bz.cl.get_json, base, "/object_info")
        need_edit = plan.concept is not None or len(plan.views) > 1
        wfs = ([bz.load_workflow(WORKFLOW_EDIT)] if need_edit else []) + \
              ([bz.load_workflow(bz.WORKFLOW_REF)] if plan.prompt else [])
        self.wf_edit = wfs[0] if need_edit else None
        self.wf_ref = wfs[-1] if plan.prompt else None
        for wf in wfs:
            missing = bz.cl.missing_nodes(wf, info)
            if missing:
                raise bz.ToolError(f"this ComfyUI lacks node types: {', '.join(missing)}"
                                   + (" (UnetLoaderGGUF comes with the ComfyUI-GGUF node pack, as Dotwork's setup "
                                      "installs it)" if "UnetLoaderGGUF" in missing else ""))
        need = (qwen_models() if need_edit else []) + (bz.klein_models() if plan.prompt else [])
        if (need_edit and not qwen_models()) or (plan.prompt and not bz.klein_models()):
            raise bz.ToolError(f"the local route reads Dotwork's model register "
                               f"({bz.rel(bz.TOOLS.parent, bz.DOTWORK_LOCK)}), which is missing or has no "
                               "qwen_rotate / klein entries")
        gone = bz.missing_models(info, need)
        if gone:
            raise bz.ToolError("model files missing in ComfyUI (download each into the folder shown, then restart "
                               "ComfyUI):\n" + "\n".join(bz.model_lines(m) for m in gone))
        self.base = base

    def upload(self, wf, path):
        bz.comfy(bz.cl.apply_images, self.base, wf, [f"{EDIT_NODES['image']}={path}"], False)
        return wf[bz.node_id(wf, EDIT_NODES["image"])]["inputs"]["image"]

    def edit(self, image_name, prompt, seed, angle, what):
        wf = json.loads(json.dumps(self.wf_edit))
        wf[bz.node_id(wf, EDIT_NODES["image"])]["inputs"]["image"] = image_name
        wf[bz.node_id(wf, EDIT_NODES["prompt"])]["inputs"]["prompt"] = prompt
        wf[bz.node_id(wf, EDIT_NODES["seed"])]["inputs"]["seed"] = seed
        wf[bz.node_id(wf, EDIT_NODES["angle"])]["inputs"]["strength_model"] = angle
        entry, seconds, _ = bz.run_job(self.base, wf, what, self.args.wait)
        items = [i for i in bz.outputs_of(entry, bz.node_id(wf, EDIT_NODES["output"]))
                 if i["filename"].lower().endswith(".png")]
        if not items:
            raise bz.JobError(f"{what}: the job saved no picture")
        return bz.comfy(bz.cl.strip_png, bz.fetch(self.base, items[0])), seconds

    def run(self, spent):
        plan, args = self.plan, self.args
        out, work = {}, plan.dir / STEPS
        work.mkdir(parents=True, exist_ok=True)
        if plan.prompt:
            text = FRONT_FROM_PROMPT.format(prompt=plan.prompt)
            wf = json.loads(json.dumps(self.wf_ref))
            wf[bz.node_id(wf, bz.NODES["prompt"])]["inputs"]["text"] = text
            wf[bz.node_id(wf, bz.NODES["ref_seed"])]["inputs"]["noise_seed"] = args.seed
            entry, seconds, _ = bz.run_job(self.base, wf, "front (FLUX.2 klein 4B)", args.wait)
            items = [i for i in bz.cl.output_files(entry, False) if i["filename"].lower().endswith(".png")]
            if not items:
                raise bz.JobError("the front job saved no picture")
            data = bz.comfy(bz.cl.strip_png, bz.fetch(self.base, items[0]))
            out["front"] = (data, {"prompt": text, "seed": args.seed, "model": "FLUX.2 klein 4B",
                                   "gpu_seconds": round(seconds, 1)})
        else:
            src = work / f"local_concept{plan.concept.suffix.lower()}"
            src.write_bytes(plan.concept_bytes)
            name = self.upload(json.loads(json.dumps(self.wf_edit)), src)
            data, seconds = self.edit(name, REPOSE, args.seed, 0.0, "front: re-pose the concept (Qwen-Image-Edit)")
            out["front"] = (data, {"prompt": REPOSE, "seed": args.seed, "model": "Qwen-Image-Edit-2511 (Q4_K_M) + "
                                   "Lightning 4-step LoRA", "gpu_seconds": round(seconds, 1)})
        print(f"[ OK ] front: {out['front'][1]['gpu_seconds']:.0f} s on the GPU", flush=True)
        others = [v for v in plan.views if v != "front"]
        if others:
            if plan.prompt:
                bz.free_vram(self.base)          # klein out, Qwen-Image-Edit in (both do not fit in 16 GB)
            front = work / "local_front.png"
            front.write_bytes(out["front"][0])
            name = self.upload(json.loads(json.dumps(self.wf_edit)), front)
            for i, view in enumerate(others, 1):
                prompt = ANGLE_PROMPT.format(azimuth=AZIMUTH[view])
                data, seconds = self.edit(name, prompt, args.seed + i, ANGLE_STRENGTH,
                                          f"{view} (Qwen-Image-Edit + Multiple-Angles LoRA)")
                out[view] = (data, {"prompt": prompt, "seed": args.seed + i, "gpu_seconds": round(seconds, 1),
                                    "model": "Qwen-Image-Edit-2511 (Q4_K_M) + Multiple-Angles LoRA + Lightning"})
                print(f"[ OK ] {view}: {seconds:.0f} s on the GPU", flush=True)
        return out

    def models(self):
        used = (qwen_models() if (self.plan.concept or len(self.plan.views) > 1) else []) + \
               (bz.klein_models() if self.plan.prompt else [])
        return [{k: m.get(k) for k in ("file", "repo", "commit", "license")} for m in used]


# ---- nanobanana route: Gemini ------------------------------------------------------------------------------------
def free_tier_quota(text):
    """True for Google's 429 on a free-tier key: a QuotaFailure whose quotaValue is 0 (the image models have no free
    quota; one such answer was read on 2026-11-11, so the match is generous: a zero quota value or limit, or a
    free-tier quota name). A 429 without it is a plain rate limit."""
    flat = " ".join(text.split()).lower()
    return bool(re.search(r'"quota_?value"\s*:\s*"?0"?(?:[,}\s]|$)', flat)
                or re.search(r'"limit"\s*:\s*"?0"?(?:[,}\s]|$)', flat)
                or "free_tier" in flat or "freetier" in flat or "free tier" in flat)


class Gemini:
    unit = "usd"

    def __init__(self, args, plan):
        self.args, self.plan = args, plan
        self.price = GEMINI_PRICES[plan.model]
        self.key = os.environ.get(GEMINI_ENV, "")

    def user_turn(self, view):
        if view != "front":
            return [{"text": TURN.format(how=TURN_HOW[view])}]
        if self.plan.concept:
            return [{"inline_data": {"mime_type": self.plan.concept_type,
                                     "data": base64.b64encode(self.plan.concept_bytes).decode("ascii")}},
                    {"text": REPOSE}]
        return [{"text": FRONT_FROM_PROMPT.format(prompt=self.plan.prompt)}]

    def estimate(self, index):
        """Quote for the call that makes view number `index` (0 = front): its picture, the conversation so far as
        input, and an allowance for thinking."""
        p = self.price
        images_in = index + (1 if self.plan.concept else 0)
        tokens_in = GEMINI_TURN_TOKENS * (index + 1) + GEMINI_IN_IMAGE_TOKENS * images_in
        return (tokens_in * p["in"] + p["image_tokens"] * p["image_out"] + GEMINI_THINK_TOKENS * p["text_out"]) / 1e6

    def cost(self, usage):
        """Dollars from usageMetadata: prompt tokens at the input price, image tokens at the image price, the rest
        of the output (text, thinking) at the text price. (None, reason) when the response carried no usage."""
        if not usage:
            return None
        p = self.price
        prompt = usage.get("promptTokenCount") or 0
        out = usage.get("candidatesTokenCount") or 0
        thoughts = usage.get("thoughtsTokenCount") or 0
        image = sum(d.get("tokenCount") or 0 for d in usage.get("candidatesTokensDetails") or []
                    if str(d.get("modality", "")).upper() == "IMAGE")
        if not image and out:
            image = min(out, p["image_tokens"])
        return (prompt * p["in"] + image * p["image_out"] + (out - image + thoughts) * p["text_out"]) / 1e6

    def keys(self):
        """The journal key of each view: its route, model, the inputs so far (a changed front changes the rest)."""
        src = sha(self.plan.concept_bytes) if self.plan.concept else self.plan.prompt
        out, chain = {}, []
        for view in self.plan.views:
            chain.append(view)
            out[view] = key_of("nanobanana", self.plan.model, src, self.args.seed, chain)
        return out

    def quote(self, journal):
        keys = self.keys()
        todo = [i for i, v in enumerate(self.plan.views) if journal.done(keys[v])[0] is None]
        total = sum(self.estimate(i) for i in todo)
        p = self.price
        return total, (f"nanobanana ({self.plan.model}): {len(todo)} of {len(self.plan.views)} view(s) to make, "
                       f"about ${total:.2f} (each about ${p['image_tokens'] * p['image_out'] / 1e6:.4f} for the "
                       f"picture, plus input and thinking tokens; prices read 2026-11-11, verify)"
                       + (f"; {len(self.plan.views) - len(todo)} reused from the journal" if len(todo) < len(
                           self.plan.views) else ""))

    def call(self, contents):
        url = f"{GEMINI_BASE}/models/{self.plan.model}:generateContent"
        cfg = {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "1:1"}}
        if not self.plan.model.startswith("gemini-2.5"):
            cfg["imageConfig"]["imageSize"] = "1K"
        status, doc, text = http_json("POST", url, {"x-goog-api-key": self.key, "Content-Type": "application/json"},
                                      body={"contents": contents, "generationConfig": cfg},
                                      timeout=GEMINI_TIMEOUT_S, secret=self.key)
        if status != 200:
            msg = ((doc or {}).get("error") or {}).get("message") or text[:300]
            if status in (401, 403) or "API_KEY_INVALID" in text or "API key not valid" in text:
                raise bz.ToolError(f"Gemini refused the key (HTTP {status}): check {GEMINI_ENV} and that its project "
                                   "has billing on (image output has no free tier)")
            if status == 429 and free_tier_quota(text):
                raise bz.ToolError(f"Gemini's free tier makes no images: this key's image quota is 0 (HTTP 429, "
                                   f"measured 2026-11-11). Image models need {GEMINI_ENV} from a Google Cloud project "
                                   "with billing on (the local route is free)")
            if status == 429:
                raise bz.JobError(f"Gemini HTTP 429: too many requests ({msg}); wait a minute and run again")
            if 300 <= status < 400:
                raise bz.JobError(f"Gemini answered with a redirect (HTTP {status}) to another address; not followed, "
                                  "the key stays with the API")
            raise bz.JobError(f"Gemini HTTP {status}: {msg}")
        return doc or {}

    @staticmethod
    def parts_to_keep(parts):
        """The model turn for the journal: every part as received (thought signatures included) but the picture's
        bytes, which live in steps/ (a "_picture" marker holds its MIME type). Thought pictures (draft images some
        models show while thinking) are left out of the history; their text and signatures stay (verify)."""
        out = []
        for p in parts:
            q = dict(p)
            inline = q.pop("inlineData", None) or q.pop("inline_data", None)
            if inline is not None:
                if q.get("thought"):
                    continue
                q["_picture"] = inline.get("mimeType") or inline.get("mime_type") or "image/png"
            out.append(q)
        return out

    @staticmethod
    def parts_to_send(kept, data):
        out = []
        for p in kept:
            q = dict(p)
            if "_picture" in q:
                q["inlineData"] = {"mimeType": q.pop("_picture"), "data": base64.b64encode(data).decode("ascii")}
            out.append(q)
        return out

    def picture(self, doc, view):
        """(picture bytes, the model's parts as received, usage)."""
        usage = doc.get("usageMetadata") or {}
        cands = doc.get("candidates") or []
        if not cands:
            block = (doc.get("promptFeedback") or {}).get("blockReason")
            raise bz.JobError(f"Gemini returned no picture for the {view} view"
                              + (f" (blocked: {block})" if block else ""))
        parts = (cands[0].get("content") or {}).get("parts") or []
        data = None
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data") and not part.get("thought"):
                data = base64.b64decode(inline["data"])
        if data is None:
            reason = cands[0].get("finishReason") or "no image part"
            words = " ".join(p.get("text", "") for p in parts if p.get("text"))[:200]
            raise bz.JobError(f"Gemini made no picture for the {view} view ({reason})" + (f": {words}" if words else ""))
        return data, parts, usage

    def run(self, spent, journal):
        out, history = {}, []
        keys = self.keys()
        for index, view in enumerate(self.plan.views):
            history.append({"role": "user", "parts": self.user_turn(view)})
            entry, data = journal.done(keys[view])
            if entry:
                print(f"[ OK ] {view}: reused from the journal (paid {fmt(entry.get('cost') or 0, 'usd')} before, "
                      "nothing now)")
                facts = {"reused": True, "cost": 0.0, "paid_before": entry.get("cost")}
            else:
                spent.allow(self.estimate(index), f"the {view} view (about ${self.estimate(index):.4f})")
                t0 = time.monotonic()
                doc = self.call(history)
                try:
                    data, parts, usage = self.picture(doc, view)
                except bz.JobError:
                    lost = self.cost(doc.get("usageMetadata"))
                    if lost:
                        spent.add(lost)
                        print(f"[info] that call still cost about ${lost:.4f} (input tokens)")
                    raise
                cost = self.cost(usage)
                estimated = cost is None
                cost = self.estimate(index) if estimated else cost
                spent.add(cost)
                data = journal.keep(keys[view], data, {"step": view, "model": self.plan.model, "cost": round(cost, 6),
                                                "cost_estimated": estimated, "usage": usage,
                                                "parts": self.parts_to_keep(parts)})
                entry = journal.steps[keys[view]]
                print(f"[ OK ] {view}: {time.monotonic() - t0:.0f} s, {fmt(cost, 'usd')}"
                      + (" (estimated: no usage in the reply)" if estimated else ""), flush=True)
                facts = {"reused": False, "cost": round(cost, 6), "usage": usage}
            # the model turn goes back as received (thought signatures included), with its picture
            history.append({"role": "model", "parts": self.parts_to_send(entry["parts"], data)})
            text = history[-2]["parts"][-1].get("text", "")
            out[view] = (data, dict(facts, prompt=text, model=self.plan.model, journal_key=keys[view]))
        return out

    def models(self):
        return [{"service": "Google Gemini API", "model": self.plan.model}]


# ---- tripo route ---------------------------------------------------------------------------------------------------
class Tripo:
    """Tripo's image tasks through the shared client (tripo.py: Client, Budget), with this tool's per-picture journal:
    a front from text-to-image or image-to-image, the other views from one image-to-multiview task."""
    unit = "credits"

    def __init__(self, args, plan):
        self.args, self.plan = args, plan
        self.client = tp.Client(journal=f"{REF_DIR}/{JOURNAL}")
        self.budget = None            # tp.Budget, made at the first paid step (it needs the balance)

    def keys(self):
        src = sha(self.plan.concept_bytes) if self.plan.concept else self.plan.prompt
        return {"front": key_of("tripo", self.plan.model, src, self.args.seed, "front")}

    def mv_key(self, front_bytes):
        return key_of("tripo", "image_to_multiview", sha(front_bytes))

    def front_kind(self):
        return "image_to_image" if self.plan.concept else "text_to_image"

    def quote(self, journal):
        k = self.keys()["front"]
        e, data = journal.done(k)
        todo = [] if e else [self.front_kind()]
        others = [v for v in self.plan.views if v != "front"]
        if others and not (data is not None and journal.done(self.mv_key(data))[0]):
            todo.append("image_to_multiview")
        q = tp.IMAGE_QUOTE
        total = sum(q[t] for t in todo)
        return float(total), (f"tripo ({self.plan.model}): {', '.join(todo) or 'nothing'} to pay for, up to "
                              f"{total} credits (${total / 100:.2f}; "
                              + (', '.join(f'{t} {q[t]}' for t in todo) or 'all reused')
                              + "; upper bounds read 2026-11-11, verify)")

    def task(self, journal, key, kind, extra, spent, entry_extra):
        """One paid task with the journal around it: a task the last run left running is asked for first (never
        paid twice; a failed one cost nothing and is made again), else cap and balance (tp.Budget) -> create ->
        journal as running -> wait. Returns (task data, credits, whether the last run paid for it)."""
        old = journal.running(key)
        if old:
            print(f"[info] the last run's {kind} task {old['task_id']} is in the journal: asking Tripo for it first")
            st = self.client.call("GET", f"/tasks/{old['task_id']}").get("status")
            if st in tp.FAILED:
                print(f"[info] it ended {st} (not charged); a new task will be made")
            else:
                d = self.client.wait_for(old["task_id"], f"{kind} (from the last run)", self.args.wait)
                d.setdefault("task_id", old["task_id"])
                return d, float(d.get("credits_consumed") or 0), True
        if self.budget is None:
            self.budget = tp.Budget(self.plan.cap, self.client.balance(), spent.new, flag="--max-cost",
                                    journal=f"{REF_DIR}/{JOURNAL}")
        self.budget.afford(tp.IMAGE_QUOTE[kind])
        tid = self.client.image_task(kind, self.plan.model, extra)
        journal.put(key, dict(entry_extra, step=kind, status="running", task_id=tid))
        print(f"[info] Tripo {kind} task {tid} (journal: {REF_DIR}/{JOURNAL})", flush=True)
        d = self.client.wait_for(tid, kind, self.args.wait)
        cost = float(d.get("credits_consumed") or 0)
        self.budget.charge(cost)
        spent.add(cost)
        d.setdefault("task_id", tid)
        return d, cost, False

    def fetch(self, journal, url, what):
        """A result picture through the shared client (no key goes to the CDN), metadata stripped."""
        tmp = journal.folder / STEPS / f"download_{uuid.uuid4().hex}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = self.client.download(url, tmp)
        finally:
            if tmp.exists():
                tmp.unlink()
        if len(data) > MAX_DOWNLOAD:
            raise bz.JobError(f"{what} is over {MAX_DOWNLOAD // 2 ** 20} MB")
        return clean(data)

    @staticmethod
    def facts(cost, earlier, extra):
        """Per-view record facts: what this run paid, or what an earlier run paid for a reused result."""
        return dict(extra, reused=earlier, cost=0.0 if earlier else cost, paid_before=cost if earlier else None)

    def make_front(self, spent, journal, k):
        if self.plan.concept:
            prompt = REPOSE
            tok = self.client.upload(self.plan.concept_bytes, f"concept{self.plan.concept.suffix}",
                                     self.plan.concept_type)
            extra = {"input": tok, "prompt": prompt}
        else:
            prompt = FRONT_FROM_PROMPT.format(prompt=self.plan.prompt)
            extra = {"prompt": prompt}
        d, cost, earlier = self.task(journal, k, self.front_kind(), extra, spent, {"prompt": prompt})
        url = (d.get("output") or {}).get("generated_image_url")
        if not url:
            raise bz.JobError(f"Tripo returned no generated_image_url for task {d['task_id']}; it is kept in "
                              f"{JOURNAL}, a rerun asks for it again without paying")
        front = journal.keep(k, self.fetch(journal, url, "Tripo's front picture"),
                             {"step": "front", "model": self.plan.model, "prompt": prompt, "task_id": d["task_id"],
                              "cost": cost})
        return front, self.facts(cost, earlier, {"prompt": prompt, "model": self.plan.model, "task_id": d["task_id"]})

    def make_multiview(self, spent, journal, mk, front):
        """All of Tripo's multiview pictures into steps/; returns ({view: bytes}, facts)."""
        is_png = front.startswith(refsheet.PNG_MAGIC)
        tok = self.client.upload(clean(front), "front.png" if is_png else "front.jpg",
                                 "image/png" if is_png else "image/jpeg")
        d, cost, earlier = self.task(journal, mk, "image_to_multiview", {"input": tok}, spent, {})
        urls = (d.get("output") or {}).get("generate_multiview_image") or {}
        files, views = {}, {}
        for v in VIEWS:
            url = urls.get(f"{v}_view_url")
            if not url:
                continue
            data = self.fetch(journal, url, f"Tripo's {v} view")
            rel_file = f"{STEPS}/{mk}_{v}" + (".png" if data.startswith(refsheet.PNG_MAGIC) else ".jpg")
            (journal.folder / rel_file).write_bytes(data)
            files[v], views[v] = rel_file, data
        journal.put(mk, {"step": "image_to_multiview", "status": "success", "task_id": d["task_id"], "cost": cost,
                         "files": files})
        return views, self.facts(cost, earlier, {"task_id": d["task_id"]})

    def run(self, spent, journal):
        out = {}
        k = self.keys()["front"]
        entry, front = journal.done(k)
        if entry:
            print(f"[ OK ] front: reused from the journal (paid {entry.get('cost') or 0:g} credits before, nothing now)")
            out["front"] = (front, self.facts(entry.get("cost") or 0, True, {
                "prompt": entry.get("prompt"), "model": self.plan.model, "task_id": entry.get("task_id")}))
        else:
            front, facts = self.make_front(spent, journal, k)
            out["front"] = (front, facts)
        others = [v for v in self.plan.views if v != "front"]
        if not others:
            return out
        mk = self.mv_key(front)
        mv, _ = journal.done(mk)
        if mv:
            print(f"[ OK ] {', '.join(others)}: reused from the journal (multiview task {mv.get('task_id')})")
            views = {v: (journal.folder / f).read_bytes() for v, f in mv["files"].items()}
            facts = self.facts(mv.get("cost") or 0, True, {"task_id": mv.get("task_id")})
        else:
            views, facts = self.make_multiview(spent, journal, mk, front)
        lacking = [v for v in others if v not in views]
        if lacking:
            raise bz.JobError(f"Tripo's multiview has no {', '.join(lacking)} view (it gave: "
                              f"{', '.join(views) or 'none'}); the task is kept in {JOURNAL}")
        for i, v in enumerate(others):   # one task made them all: its cost is counted once, on the first
            f = dict(facts, model="Tripo image-to-multiview", journal_key=mk,
                     prompt="(image-to-multiview takes no prompt)")
            if i:
                f.update(cost=0.0, paid_before=None)
            out[v] = (views[v], f)
        return out

    def models(self):
        return [{"service": "Tripo API", "model": self.plan.model}, {"service": "Tripo API", "model": "image-to-multiview"}]


# ---- write the results -------------------------------------------------------------------------------------------
def write_views(plan, results, overwrite):
    """Each view as <view>.png in the reference folder (metadata stripped). Returns {view: path}."""
    files = {}
    for view in plan.views:
        data = results[view][0]
        png = refsheet.to_png(data)
        dest = plan.files[view]
        if png is None:   # a JPEG or WebP and no Pillow to convert it: kept as it came
            ext = ".jpg" if data[:2] == b"\xff\xd8" else ".webp"
            dest = dest.with_suffix(ext)
            print(f"[warn] {view}: the service sent {ext[1:].upper()}; kept as {dest.name} (install Pillow to get PNG)")
            png = data
        bz.write_new(dest, bz.comfy(bz.cl.strip_picture, png), overwrite)
        files[view] = dest
    return files


def write_log(plan, record):
    """ASSET_LOG row for the views (updated in place on a rerun) + docs/licenses/A-NNNN.txt."""
    fa = bz.fetch_asset
    text = plan.log_path.read_text(encoding="utf-8")
    front_rel = record["views"]["front"]["file"]
    existing = [l for l in text.splitlines() if l.startswith("| A-") and f"`{front_rel}`" in l]
    if existing:
        aid, fill = existing[0].split("|")[1].strip(), None
    else:
        num, fill = fa.next_asset_id(text)
        aid = f"A-{num:04d}"
    terms = TERMS[plan.route]
    source = {"local": f"{bz.TOOL} reference (local ComfyUI: "
                       + ("FLUX.2 klein 4B, " if plan.prompt else "") + "Qwen-Image-Edit-2511)",
              "nanobanana": f"Google Gemini API ({plan.model}) via `bozzetto.py reference`",
              "tripo": f"Tripo API ({plan.model}, image-to-multiview) via `bozzetto.py reference`"}[plan.route]
    how = "generated locally" if plan.route == "local" else "paid service"
    files = [v["file"] for v in record["views"].values()] + ([record["sheet"]] if record.get("sheet") else [])
    cost = record["cost"]
    notes = "; ".join(x for x in [
        f"reference views for {plan.name} ({', '.join(record['views'])}); source art for `make`, not shipped",
        f"prompt: {plan.prompt[:160]}" if plan.prompt else "from a concept picture (see the record)",
        f"seed {record['seed']}" if record.get("seed") is not None else "",
        "free" if plan.route == "local" else f"cost {fmt(cost['total_paid'], plan.unit)}",
        f"owner: {terms['owner']}",
        f"record `{bz.rel(plan.root, plan.dir / RECORD)}`"] if x)
    shown = ", ".join(f"`{f}`" for f in files)
    attribution = "SynthID watermark in every image" if plan.route == "nanobanana" else ""
    row = (f"| {aid} | art | {shown} | {fa.md_cell(source)} | {how} | {fa.md_cell(terms['licence'])} | "
           f"{fa.md_cell(attribution)} | pre-generated | no | {record['date']} | {fa.md_cell(notes)} |")
    new = text.replace(existing[0], row, 1) if existing else fa.add_log_row(text, row, fill)
    plan.log_path.write_bytes(new.encode("utf-8"))
    ev = [f"{aid}  art  reference views generated {record['date']} with tools/{bz.TOOL.lower()}/"
          f"{bz.TOOL.lower()}.py reference {bz.VERSION}",
          f"Route    : {plan.route} ({plan.model})"
          + (f", seed {record['seed']}" if record.get("seed") is not None else ", no seed (the journal names the take)"),
          f"Source   : " + (f"prompt: {plan.prompt}" if plan.prompt else
                            f"concept picture, SHA-256 {record['source']['sha256']}"),
          f"Owner    : {terms['owner']}", f"Licence  : {terms['licence']}", f"Notes    : {terms['notes']}",
          f"Cost     : " + ("free" if plan.route == "local" else
                           f"{fmt(cost['total_paid'], plan.unit)} in all ({fmt(cost['this_run'], plan.unit)} this run)")]
    ev += [f"File     : {v['file']}  SHA-256 {v['sha256']}  prompt: {v.get('prompt', '')[:200]}"
           for v in record["views"].values()]
    lic = plan.root / fa.LICENSE_DIR
    lic.mkdir(parents=True, exist_ok=True)
    (lic / f"{aid}.txt").write_bytes(("\n".join(ev) + "\n").encode("utf-8"))
    print(f"[ OK ] {aid} {'updated in' if existing else 'added to'} {fa.ASSET_LOG.as_posix()}")
    return aid


def next_steps(plan, files):
    r = lambda v: bz.rel(plan.root, files[v])  # noqa: E731
    print(f"[next] look at {bz.rel(plan.root, plan.dir / SHEET)}: the same character in every view, arms clear of the "
          "body, nothing cut off. When it is right:")
    print(f"       python tools/{bz.TOOL.lower()}/{bz.TOOL.lower()}.py make {plan.name} --image {r('front')} "
          "--class npc --seed 1      # --class hero for the main character")
    if all(v in files for v in VIEWS):
        print(f"       or the paid multiview make (Tripo; quote first, ask): python tools/{bz.TOOL.lower()}/"
              f"{bz.TOOL.lower()}.py make {plan.name} --with tripo --class npc --front {r('front')} "
              f"--left {r('left')} --back {r('back')} --right {r('right')}")


def swap_sides(args):
    """--swap-sides: the generator turned the figure the wrong way for left and right (SIDES_NOTE). Swap the two
    pictures, rebuild the sheet, swap the two views in the record (each picture keeps the prompt and model that made
    it, under its new name, so the record still says how each file was made) and update the asset log row and its
    evidence file, whose hashes would otherwise describe the wrong files. No GPU, no service, no cost."""
    root = Path(args.project).resolve()
    if not bz.NAME_RULE.match(args.name):
        raise bz.ToolError(f"name {args.name!r}: lowercase letters, digits and underscores, starting with a letter")
    extra = [flag for flag, on in (("--from", args.concept), ("--prompt", args.prompt), ("--model", args.model),
                                   ("--max-cost", args.max_cost is not None), ("--quote-only", args.quote_only),
                                   ("--no-reuse", args.no_reuse), ("--overwrite", args.overwrite)) if on]
    if extra:
        raise bz.ToolError(f"--swap-sides works on the views already made and takes no {', '.join(extra)}")
    folder = root / bz.SRC_ROOT / args.name / REF_DIR
    rec_path = folder / RECORD
    if not rec_path.is_file():
        raise bz.ToolError(f"{bz.rel(root, rec_path)} not found: make the views first (reference {args.name} --prompt "
                           "or --from)")
    record = json.loads(rec_path.read_text(encoding="utf-8"))
    views = record.get("views") or {}
    if "left" not in views or "right" not in views:
        raise bz.ToolError(f"{bz.rel(root, rec_path)} has no left and right views to swap")
    left, right = root / views["left"]["file"], root / views["right"]["file"]
    for p in (left, right):
        if not p.is_file():
            raise bz.ToolError(f"{bz.rel(root, p)} is missing: make the views again (--overwrite)")
    if left.suffix.lower() != right.suffix.lower():
        raise bz.ToolError(f"{left.name} and {right.name} are different picture types: swap them by hand")
    a, b = left.read_bytes(), right.read_bytes()
    bz.write_new(left, b, True)
    bz.write_new(right, a, True)
    views["left"], views["right"] = (dict(views["right"], file=views["left"]["file"], sha256=sha(b)),
                                     dict(views["left"], file=views["right"]["file"], sha256=sha(a)))
    record["sides_swapped"] = not record.get("sides_swapped", False)   # a second swap undoes the first
    print(f"[ OK ] swapped {left.name} and {right.name}")
    images = {v: refsheet.decode((root / views[v]["file"]).read_bytes()) for v in views}
    if all(images.values()):
        sheet = folder / SHEET
        bz.write_new(sheet, refsheet.sheet([images[v] for v in views]), True)
        record["sheet"] = bz.rel(root, sheet)
        print(f"[ OK ] turnaround sheet: {record['sheet']} ({', '.join(views)}, left to right)")
    else:
        print("[warn] no sheet: a view could not be read here (install Pillow); the views themselves are swapped")
    look = refsheet.look(images)
    look["by_eye"] = SIDES_NOTE
    record["look"] = look
    bz.write_new(rec_path, json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8"), True)
    print(f"[ OK ] record: {bz.rel(root, rec_path)}")
    log_path = root / bz.fetch_asset.ASSET_LOG
    front_rel = views.get("front", {}).get("file", "")
    if args.no_log or not log_path.is_file() or f"`{front_rel}`" not in log_path.read_text(encoding="utf-8"):
        print("[info] no asset log row for these views to update")
    else:
        source = record.get("source") or {}
        plan = type("SwapPlan", (), dict(root=root, name=args.name, dir=folder, log_path=log_path,
                                         route=record["route"], model=record.get("model"),
                                         prompt=source.get("prompt"), unit=record["cost"]["unit"]))
        write_log(plan, record)
    print(f"[look] look at {record.get('sheet') or bz.rel(root, folder)} again: left faces the picture's left edge")
    return 0


# ---- command ---------------------------------------------------------------------------------------------------------
def cmd_reference(args):
    if args.swap_sides:
        return swap_sides(args)
    t0 = time.monotonic()
    plan = Plan(args)
    if args.seed is None and plan.route == "local":
        args.seed = int(time.time()) % 100000
        print(f"[info] no --seed given: using {args.seed} (pass it to name this take again)")
    elif args.seed is None:
        # the paid services take no seed: it only names the take in the journal. A clock seed here would make the
        # same command, run again after a 500, a cap stop or Ctrl-C, pay for the front a second time.
        print("[info] no --seed given: a re-run of this command reuses this take from the journal (pass --seed N or "
              "--no-reuse for a new take)")
    preflight(args, plan)
    route = {"local": Local, "nanobanana": Gemini, "tripo": Tripo}[plan.route](args, plan)
    journal = Journal(plan.dir, plan.route, not args.no_reuse) if plan.route != "local" else None
    amount, text = route.quote(journal) if journal is not None else route.quote()
    print(f"[quote] {text}" + ("" if plan.route == "local" else f"; cap --max-cost {fmt(plan.cap, plan.unit)}"))
    if args.quote_only:
        print("[ OK ] --quote-only: nothing was made or spent")
        return 0
    if plan.route != "local" and amount > plan.cap + 1e-9:
        raise bz.ToolError(f"the quote ({fmt(amount, plan.unit)}) is over --max-cost {fmt(plan.cap, plan.unit)}: "
                           "raise the cap or make fewer views")
    stats = None
    if plan.route == "local":
        route.preflight()             # ComfyUI, nodes, model files: before any folder is made
        stats = route.stats
    plan.dir.mkdir(parents=True, exist_ok=True)
    spent = Spent(plan.cap, plan.unit)
    if plan.route == "local":
        results = route.run(spent)
    else:
        results = route.run(spent, journal)
    files = write_views(plan, results, args.overwrite)
    concept_rel = None
    if plan.concept:
        dest = plan.dir / f"concept{plan.concept.suffix.lower()}"
        bz.write_new(dest, plan.concept_bytes, True)
        concept_rel = bz.rel(plan.root, dest)
    images = {v: refsheet.decode(files[v].read_bytes()) for v in plan.views}
    sheet_rel = None
    if all(images.values()):
        sheet = plan.dir / SHEET
        bz.write_new(sheet, refsheet.sheet([images[v] for v in plan.views]), True)
        sheet_rel = bz.rel(plan.root, sheet)
        print(f"[ OK ] turnaround sheet: {sheet_rel} ({', '.join(plan.views)}, left to right)")
    else:
        print("[warn] no sheet: a view could not be read here (install Pillow); the views themselves are fine")
    look = refsheet.look(images)
    if "left" in plan.views or "right" in plan.views:   # no pixel count tells which way a profile faces
        look["by_eye"] = SIDES_NOTE
        print(f"[look] by eye: {SIDES_NOTE}")
    for w in look["warnings"]:
        print(f"[look] {w}")
    if not look["warnings"]:
        print("[ OK ] look check: flat light background, the views agree in height and feet line")
    paid_before = sum(float(r[1].get("paid_before") or 0) for r in results.values())
    record = {"tool": f"{bz.TOOL} {bz.VERSION} reference", "date": datetime.date.today().isoformat(),
              "name": plan.name, "route": plan.route, "model": plan.model, "seed": args.seed,
              "source": ({"kind": "prompt", "prompt": plan.prompt} if plan.prompt else
                         {"kind": "concept", "file": concept_rel, "sha256": sha(plan.concept_bytes)}),
              "views": {v: dict({k: x for k, x in results[v][1].items() if k != "usage"},
                                file=bz.rel(plan.root, files[v]), sha256=sha(files[v].read_bytes()))
                        for v in plan.views},
              "sheet": sheet_rel,
              "cost": {"unit": plan.unit, "quoted": round(amount, 6), "this_run": round(spent.new, 6),
                       "total_paid": round(spent.new + paid_before, 6), "cap": plan.cap},
              "terms": TERMS[plan.route], "models": route.models(), "look": look,
              "comfyui": ((stats or {}).get("system") or {}).get("comfyui_version"),
              "seconds": round(time.monotonic() - t0, 1)}
    bz.write_new(plan.dir / RECORD, json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8"), True)
    print(f"[ OK ] record: {bz.rel(plan.root, plan.dir / RECORD)}"
          + ("" if plan.route == "local" else f"; spent {fmt(spent.new, plan.unit)} this run"))
    if plan.log:
        write_log(plan, record)
    next_steps(plan, files)
    return 0


def add_parser(sub, common):
    p = sub.add_parser("reference", parents=[common],
                       help="model-ready reference views (A-pose front, left, back, right) from a concept or a prompt")
    p.add_argument("name", help="the character's name (chr_hero, npc_guard): views go to assets_src/bozzetto/<name>/"
                                "reference/")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--from", dest="concept", help="a concept picture (.png .jpg .webp), any pose")
    src.add_argument("--prompt", help="describe the character; the front is drawn from it")
    p.add_argument("--with", dest="backend", choices=ROUTES, default="local",
                   help="local: free, your GPU (default); nanobanana: Google Gemini, GEMINI_API_KEY, paid per image; "
                        "tripo: Tripo image tasks, TRIPO_API_KEY, paid credits")
    p.add_argument("--views", default=",".join(VIEWS), help=f"which views (default {','.join(VIEWS)}; front always)")
    p.add_argument("--seed", type=int, help="seed (local: every sampler, from the clock when not given; paid routes: "
                                            "names the take in the journal, so a re-run without one reuses its paid work)")
    p.add_argument("--model", help=f"nanobanana: a Gemini image model (default {GEMINI_MODEL}); tripo: "
                                   f"{', '.join(tp.IMAGE_MODELS)} (default {tp.IMAGE_MODEL})")
    p.add_argument("--max-cost", type=float, help=f"never spend more than this in one run: dollars for nanobanana "
                                                  f"(default {GEMINI_MAX_COST:.2f}), credits for tripo (default "
                                                  f"{TRIPO_MAX_COST})")
    p.add_argument("--quote-only", action="store_true", help="print the price and stop (no key needed)")
    p.add_argument("--no-reuse", action="store_true", help="paid routes: ignore the journal and pay again")
    p.add_argument("--project", default=".", help="the game's root folder (default: the current folder)")
    p.add_argument("--overwrite", action="store_true", help="replace views, sheet and record from an earlier run")
    p.add_argument("--no-log", action="store_true", help="do not touch docs/ASSET_LOG.md (scratch runs)")
    p.add_argument("--wait", type=int, default=WAIT_S, help=f"seconds to wait for each job or task (default {WAIT_S})")
    p.add_argument("--swap-sides", action="store_true",
                   help="the views already made have left and right the wrong way round: swap left.png and right.png "
                        "and update the sheet, the record and the asset log (no GPU, no cost; give only the name)")
    p.set_defaults(fn=cmd_reference)

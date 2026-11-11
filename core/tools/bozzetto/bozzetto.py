#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# bozzetto.py
# Purpose : Bozzetto, the kit's local 3D asset lane: a reference image (yours, or made from a prompt) to a
#           game-ready, budgeted .glb in the game, on your own GPU. TRELLIS.2 makes the mesh through a local
#           ComfyUI; Blender cleans it, scales it, sets the pivot, writes LODs and checks the budget; the asset log
#           gets its row. One front door, like Wavesmith (audio) and Dotwork (pixel art).
# Usage   : python tools/bozzetto/bozzetto.py list                 # the steps and subcommands
#           python tools/bozzetto/bozzetto.py check                # ComfyUI, nodes, model files, Blender
#           python tools/bozzetto/bozzetto.py test [--live]        # the exams (--live: one real GPU run too)
#           python tools/bozzetto/bozzetto.py make prop_crate --image art_src/crate.png --class prop
#           python tools/bozzetto/bozzetto.py make prop_chest --prompt "a wooden chest with iron bands" --seed 11
#           python tools/bozzetto/bozzetto.py make prop_chest --prompt "..." --reference-only --seed 12  # image only
#           python tools/bozzetto/bozzetto.py make npc_guard --image ref.png --class npc --lods 0.5 --sprites assets/art/guard.png
#           python tools/bozzetto/bozzetto.py rig check            # the rig routes: UniRig (local) and Tripo (paid)
#           python tools/bozzetto/bozzetto.py rig make npc_guard   # skeleton, skin weights, Mixamo names, clips
#           Options for make: --class prop|kit|hero|npc, --seed N, --out <models folder>, --lods 0.5,0.25|none,
#           --height M, --turn DEG, --quality normal|high, --material texture|vertex, --no-log, --overwrite, --debug
# Needs   : Python 3.8+ (standard library). For make: a running ComfyUI 0.43.0+ (TRELLIS.2 nodes are built in) with
#           the model files in models.lock.json (check lists what is missing and where it goes; --prompt also needs
#           Dotwork's FLUX.2 klein files), and Blender 4.2+ (BLENDER_BIN, PATH, the default install) or the bpy module.
# Exit    : 0 ok, 1 the job or the budget check failed, 2 usage, environment, missing models or files in the way
# Notes   : Steps of make: reference (copy --image, or FLUX.2 klein from --prompt) -> TRELLIS.2 over ComfyUI's HTTP
#           API (BiRefNet removes the background inside the workflow; ComfyUI's prompt is stripped from the .glb)
#           -> cleanup.py in Blender -> tools/blender/prep_export.py (the one glTF preset, LODs) ->
#           tools/blender/validate_asset.py --class -> files into --out -> ASSET_LOG row + evidence + the model
#           licence texts in docs/licenses/ (first time) -> turntable.py preview; with --sprites, render_sprites.py
#           runs before the log, so the sheet gets its row and hash. rig (rig.py, rig_finish.py) gives a model
#           a skeleton: UniRig on your GPU or the Tripo3D API, then a weight check, Mixamo bone names and clips.
#           Sources and records stay in assets_src/bozzetto/<name>/ (reference, raw mesh, reports, preview).
#           Nothing reaches --out unless the budget check passes. Files are never replaced without --overwrite.
#           Licences: TRELLIS.2 and BiRefNet are MIT, DINOv3 (TRELLIS.2's image encoder) has its own licence with a
#           use restriction list (LICENSES.md). Paid 3D services are not wired in: docs/resources/ai-tools.md.
#           Timing on a 16 GB RTX 5060 Ti: about 5 min per model at normal quality once warm, about 19 at high (K01).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   list:  the steps table
#   check: Python -> ComfyUI up (comfy_local) -> node types of both workflows -> each locked model in the loader's
#          list -> non-commercial pieces named in the workflow? -> Blender or bpy -> exit 0 ready / 2 not
#   test:  test_bozzetto.py (offline) [+ test_bozzetto_live.py]
#   make:  check name, paths, budget, Blender, ComfyUI, nodes, models, outputs free, ASSET_LOG  [before any GPU time]
#          reference: --image copied (EXIF/XMP/text gone) | --prompt -> klein job -> free VRAM [-> --reference-only stop]
#          TRELLIS.2 job (only the --material branch; image, seed, resolution, face target, texture size)
#          -> fetch the .glb (extras stripped)
#          cleanup.py -> prep_export.py --no-validate -> validate_asset.py --json -> fail: stop, exit 1
#          copy the .glb and LODs into --out -> --sprites sheet -> record JSON -> ASSET_LOG row (updated on a
#          re-run; the sheet is in it) -> turntable
import argparse
import datetime
import functools
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for _p in (TOOLS, TOOLS / "art", TOOLS / "blender"):
    sys.path.insert(0, str(_p))
import comfy_local as cl  # noqa: E402  (server rule, upload, queue, wait, GLB / PNG stripping)
import fetch_asset  # noqa: E402  (ASSET_LOG helpers)
import validate_asset as va  # noqa: E402  (class budgets; its bpy import is lazy)

TOOL = "Bozzetto"                 # the one place the name is spelled for people: a rename starts here
VERSION = "0.12.0"
SRC_ROOT = Path("assets_src") / TOOL.lower()   # per model: reference, raw mesh, reports, preview
DEFAULT_OUT = "assets/models"
# where models go when --out is not given, by the engine in the game's .game-kit.json (its assets folder + models;
# Unreal imports a .glb through its own importer, so the file waits outside Content/)
ENGINE_OUT = {"web": "public/assets/models", "web-3d": "public/assets/models", "unity": "Assets/Models",
              "unreal": "SourceArt/Models"}
WORKFLOW_3D = HERE / "workflows" / "trellis2_image_to_3d.api.json"
WORKFLOW_REF = HERE / "workflows" / "klein_reference.api.json"
LOCK = HERE / "models.lock.json"
DOTWORK_LOCK = TOOLS / "art" / "dotwork" / "models.lock.json"   # FLUX.2 klein for --prompt, as Dotwork loads it
LICENSE_TEXTS = HERE / "licenses"
RECORD = "bozzetto.json"
WAIT_S = 3600                       # one TRELLIS.2 job: about 5 min at normal, 19 at high on a 16 GB card
QUALITY = {"normal": 1024, "high": 1536}
FACE_SHARE = 0.9                    # TRELLIS.2 decimates to this share of the class budget (Blender has headroom)
# per class: target height in metres, baked texture size, default LODs (SOP-11: hero LODs required)
CLASS_SETTINGS = {
    "prop": {"height": 1.0, "texture": 1024, "lods": []},
    "kit":  {"height": 3.0, "texture": 2048, "lods": [0.5]},
    "hero": {"height": 1.8, "texture": 2048, "lods": [0.5, 0.25]},
    "npc":  {"height": 1.8, "texture": 1024, "lods": [0.5]},
}
REF_SIZE = 1024
REF_TEMPLATES = {   # what TRELLIS.2 reads best: one object, whole, centred, plain background, no cast shadow
    "object": "{prompt}, one single object, whole object in view, centered, three-quarter view from slightly above, "
              "plain white background, soft even studio lighting, no shadow, no text, 3D game asset render",
    "character": "{prompt}, one single character, full body from head to feet, standing straight in an A-pose with "
                 "the arms slightly away from the body, front view, centered, plain white background, soft even "
                 "studio lighting, no shadow, no text, 3D game character render",
}
NODES = {"image": "INPUT image", "resolution": "Upsample", "faces": "Decimate", "unwrap": "UV unwrap",
         "bake": "Bake base/metal/rough", "normal": "Bake normal map", "textured": "OUTPUT textured GLB",
         "vertex": "OUTPUT vertex-colour GLB", "prompt": "Prompt", "ref_seed": "SEED"}
NON_COMMERCIAL = ("rmbg", "nvdiffrast")   # upstream TRELLIS.2 pieces (CC BY-NC, NVIDIA non-commercial): never load
NAME_RULE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
BLENDER_ENV = "BLENDER_BIN"
ATTRIBUTION = "Built with DINOv3. 3D model generated with TRELLIS.2 (Microsoft)."
DEBUG = False
SLEEP = time.sleep                  # the exam replaces it


class ToolError(Exception):
    """Exit 2: usage, environment, missing models, files in the way."""


class JobError(Exception):
    """Exit 1: generation, cleanup or the budget check failed."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


# ---- model register -------------------------------------------------------------------
def load_lock():
    try:
        return json.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"{LOCK.name} unreadable: {exc}")


def klein_models():
    """The FLUX.2 klein files --prompt loads, from Dotwork's register (its pixel-art LoRA left out)."""
    try:
        lock = json.loads(DOTWORK_LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [m for m in lock.get("models", []) if "klein" in m.get("routes", []) and m.get("loader") != "LoraLoaderModelOnly"]


loader_options = cl.loader_options      # both /object_info styles; shared with Dotwork (#197)


def missing_models(info, models):
    return [m for m in models if m["file"] not in loader_options(info, m["loader"], m["input"])]


def model_lines(m):
    return (f"         {m['file']}  ({m['size'] / 1024 ** 3:.2f} GB, {m['license']})\n"
            f"           -> ComfyUI/models/{m['folder']}/   {m['url']}")


def non_commercial_in(wf):
    """Names of non-commercial upstream pieces (RMBG-2.0, nvdiffrast) anywhere in a workflow's nodes or inputs."""
    hits = set()
    for node in wf.values():
        texts = [node.get("class_type", "")] + [v for v in node.get("inputs", {}).values() if isinstance(v, str)]
        for t in texts:
            for bad in NON_COMMERCIAL:
                if bad in t.lower():
                    hits.add(t)
    return sorted(hits)


# ---- Blender ----------------------------------------------------------------------------
def bpy_importable():
    return importlib.util.find_spec("bpy") is not None


def default_blenders():
    """Blender executables in the usual install places, newest version first."""
    found = []
    if os.name == "nt":
        for base in {os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramW6432", "")}:
            root = Path(base) / "Blender Foundation" if base else None
            if root and root.is_dir():
                for d in root.glob("Blender*"):
                    exe = d / "blender.exe"
                    if exe.is_file():
                        nums = tuple(int(x) for x in re.findall(r"\d+", d.name)) or (0,)
                        found.append((nums, exe))
    else:
        for p in ("/Applications/Blender.app/Contents/MacOS/Blender", "/snap/bin/blender", "/usr/bin/blender"):
            if Path(p).is_file():
                found.append(((0,), Path(p)))
    return [str(p) for _, p in sorted(found, key=lambda x: x[0], reverse=True)]


def find_blender(choice=None):
    """("blender", path) or ("bpy", python) or None. --blender PATH|bpy wins; then BLENDER_BIN, PATH, the default
    install, and last the bpy module in this Python."""
    if choice == "bpy":
        return ("bpy", sys.executable) if bpy_importable() else None
    if choice:
        return ("blender", choice) if Path(choice).is_file() else None
    for c in [os.environ.get(BLENDER_ENV), shutil.which("blender")] + default_blenders():
        if c and Path(c).is_file():
            return ("blender", c)
    return ("bpy", sys.executable) if bpy_importable() else None


@functools.lru_cache(maxsize=None)
def blender_version(blender):
    """'Blender 5.2.2' or None (cached: starting Blender takes seconds)."""
    kind, path = blender
    cmd = [path, "--version"] if kind == "blender" else [path, "-c", "import bpy; print('Blender', bpy.app.version_string)"]
    try:
        out = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = next((l.strip() for l in out.splitlines() if l.strip().startswith("Blender")), "")
    return line or None


def run_bpy(blender, script, argv, what):
    """Run a Blender-side script; its [ OK ] / [FAIL] / [WARN] lines are shown, everything with --debug.
    Returns (exit code, output)."""
    kind, path = blender
    cmd = ([path, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(script), "--"] if kind == "blender"
           else [path, str(script)]) + [str(a) for a in argv]
    dbg("run: " + " ".join(cmd))
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=WAIT_S)
    except OSError as exc:
        raise ToolError(f"could not start Blender ({path}): {exc}")
    except subprocess.TimeoutExpired:
        raise JobError(f"{what} did not finish in {WAIT_S} s")
    out = (proc.stdout or "") + (proc.stderr or "")
    for line in out.splitlines():
        if DEBUG or re.match(r"^\[(?: OK |FAIL|WARN|ENV |info)\]", line) or line.startswith(("Tris", "  - {")):
            print(f"       {line}")
    if proc.returncode not in (0, 1) and not DEBUG:   # a crash: show the tail so the cause is visible
        print("\n".join("       " + l for l in out.splitlines()[-25:]))
    dbg(f"{what}: exit {proc.returncode} in {time.monotonic() - t0:.1f} s")
    return proc.returncode, out


# ---- GPU memory (optional, for the record) -------------------------------------------------
class VramPeak(threading.Thread):
    """Samples nvidia-smi every 2 s while a job runs; peak stays None when there is no nvidia-smi."""

    def __init__(self):
        super().__init__(daemon=True)
        self.peak, self.stop = None, threading.Event()
        self.exe = shutil.which("nvidia-smi")

    def run(self):
        while self.exe and not self.stop.is_set():
            try:
                out = subprocess.run([self.exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                     capture_output=True, encoding="utf-8", errors="replace", timeout=10).stdout
                v = int(out.split()[0])
                self.peak = max(self.peak or 0, v)
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                pass
            self.stop.wait(2)


# ---- ComfyUI jobs ----------------------------------------------------------------------------
class _Url:
    def __init__(self, url, allow_remote):
        self.url, self.allow_remote = url, allow_remote


def comfy_base(args):
    try:
        return cl.server_url(_Url(args.url, args.allow_remote))
    except cl.ToolError as exc:
        raise ToolError(str(exc))


def comfy(fn, *a):
    """Call a comfy_local helper, mapping its errors onto this tool's exit codes."""
    try:
        return fn(*a)
    except cl.JobError as exc:
        raise JobError(str(exc))
    except cl.ToolError as exc:
        raise ToolError(str(exc))


def run_job(base, wf, what, wait):
    """Queue a graph, wait, return (history entry, GPU seconds, VRAM peak MiB or None)."""
    sampler = VramPeak()
    sampler.start()
    try:
        pid = comfy(cl.queue, base, wf)
        print(f"[....] {what}: job {pid} queued, waiting (up to {wait} s)", flush=True)
        entry, seconds = comfy(cl.wait_history, base, pid, wait)
    finally:
        sampler.stop.set()
        sampler.join(15)   # a sample still running would hold the current folder open (Windows)
    return entry, seconds, sampler.peak


def fetch(base, item):
    import urllib.parse
    q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                "type": item.get("type", "output")})
    status, data = comfy(cl.http, "GET", f"{base}/view?{q}")
    if status != 200:
        raise JobError(f"could not fetch {item['filename']} from ComfyUI (HTTP {status})")
    return data


def outputs_of(entry, node_id):
    out = (entry.get("outputs") or {}).get(node_id) or {}
    return [i for key in cl.OUTPUT_KEYS for i in (out.get(key) or []) if isinstance(i, dict) and i.get("filename")]


def free_vram(base):
    """Ask ComfyUI to unload models between the klein and TRELLIS.2 jobs (both together do not fit in 16 GB)."""
    try:
        cl.http("POST", base + "/free", json.dumps({"unload_models": True, "free_memory": True}).encode(),
                {"Content-Type": "application/json"})
        SLEEP(2)
    except cl.ToolError as exc:
        dbg(f"/free failed: {exc}")


def load_workflow(path):
    return comfy(cl.load_workflow, str(path))


def node_id(wf, title):
    return comfy(cl.find_node, wf, title)


# ---- make: preflight ----------------------------------------------------------------------
def rel(root, p):
    """A project-relative POSIX path for messages, records and the log (never an absolute local path)."""
    try:
        return Path(p).resolve().relative_to(root).as_posix()
    except ValueError:
        return Path(p).name


def default_out(root):
    """The models folder for this game's engine (.game-kit.json), else assets/models."""
    try:
        engine = json.loads((root / ".game-kit.json").read_text(encoding="utf-8")).get("engine", "")
    except (OSError, ValueError):
        engine = ""
    return ENGINE_OUT.get(engine, DEFAULT_OUT)


def parse_lods(text, asset_class):
    if text is None:
        return list(CLASS_SETTINGS[asset_class]["lods"])
    if text.strip().lower() in ("", "none", "0"):
        return []
    try:
        ratios = [float(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise ToolError(f"--lods must look like 0.5,0.25 or none, got {text!r}")
    if any(not 0 < r < 1 for r in ratios):
        raise ToolError("every --lods ratio must be between 0 and 1 (exclusive)")
    return ratios


class Plan:
    """Everything make decides before any GPU time is spent."""

    def __init__(self, args):
        self.root = Path(args.project).resolve()
        if not self.root.is_dir():
            raise ToolError(f"--project {args.project} is not a folder")
        if not NAME_RULE.match(args.name):
            raise ToolError(f"name {args.name!r}: lowercase letters, digits and underscores, starting with a letter "
                            "(SOP-11 names: prop_<thing>, kit_<set>_<piece>, chr_<name>, npc_<name>)")
        if bool(args.image) == bool(args.prompt):
            raise ToolError("give exactly one of --image <reference.png> or --prompt \"...\"")
        self.name, self.cls = args.name, args.asset_class
        settings = CLASS_SETTINGS[self.cls]
        self.budget = dict(va.CLASS_BUDGETS[self.cls])
        self.height = args.height if args.height is not None else settings["height"]
        if self.height <= 0:
            raise ToolError("--height must be a positive number of metres")
        self.texture = args.texture or settings["texture"]
        self.faces = int(self.budget["max_tris"] * FACE_SHARE)
        self.lods = parse_lods(args.lods, self.cls)
        self.src = self.root / SRC_ROOT / self.name
        out = args.out or default_out(self.root)
        self.out_dir = (self.root / out) if not Path(out).is_absolute() else Path(out)
        self.main = self.out_dir / f"{self.name}.glb"
        self.lod_files = [self.out_dir / f"{self.name}_LOD{i}.glb" for i in range(1, len(self.lods) + 1)]
        self.log = not args.no_log and not args.reference_only
        self.log_path = self.root / fetch_asset.ASSET_LOG
        self.sprites = Path(args.sprites) if args.sprites else None
        if self.sprites and not self.sprites.is_absolute():
            self.sprites = self.root / self.sprites
        if args.image:
            self.image = Path(args.image)
            if not self.image.is_absolute() and not self.image.is_file():
                self.image = self.root / args.image
            if not self.image.is_file():
                raise ToolError(f"--image {args.image} not found")
            if self.image.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                raise ToolError("--image must be a .png, .jpg or .webp picture")

    def in_the_way(self, args):
        """Files this run would replace (refused without --overwrite)."""
        if args.reference_only:
            return [p for p in [self.src / f"reference_seed{args.seed}.png"] if p.exists()]
        paths = [self.main] + self.lod_files + [self.src / RECORD] + (
            [self.sprites, self.sprites.with_suffix(".json")] if self.sprites else [])
        return [p for p in paths if p.exists()]


def preflight(args, plan):
    """Every check that can fail before a GPU minute is spent. Returns (base URL, blender, workflows, stats)."""
    if not args.overwrite:
        busy = plan.in_the_way(args)
        if busy:
            raise ToolError(f"{', '.join(rel(plan.root, p) for p in busy)} already exist(s); pass --overwrite to "
                            "make this model again on purpose")
    if plan.log:
        if not plan.log_path.is_file():
            raise ToolError(f"{fetch_asset.ASSET_LOG.as_posix()} not found under {plan.root}: run from the game's "
                            "root folder (or --project), or pass --no-log")
        try:
            plan.main.resolve().relative_to(plan.root)
        except ValueError:
            raise ToolError(f"--out {plan.out_dir} is outside the project; the asset log is for files that ship in it "
                            "(pass --no-log for a scratch run)")
    blender = None
    if not args.reference_only:
        blender = find_blender(args.blender)
        if blender is None:
            raise ToolError(f"Blender not found: set {BLENDER_ENV} to blender(.exe), put blender on PATH, install it "
                            "in the default place, or run with a Python that has the bpy module "
                            "(uv run --python 3.13 --with bpy python tools/bozzetto/bozzetto.py ...)")
    base = comfy_base(args)
    stats = comfy(cl.get_json, base, "/system_stats")
    info = comfy(cl.get_json, base, "/object_info")
    wf3d = None if args.reference_only else load_workflow(args.workflow or WORKFLOW_3D)
    wfref = load_workflow(WORKFLOW_REF) if args.prompt else None
    for wf in [w for w in (wf3d, wfref) if w]:
        bad = non_commercial_in(wf)
        if bad:
            raise ToolError(f"the workflow names non-commercial pieces ({', '.join(bad)}); {TOOL} never loads them "
                            "(LICENSES.md). Use the shipped workflow, or remove them.")
        missing = cl.missing_nodes(wf, info)
        if missing:
            raise ToolError(f"this ComfyUI lacks node types: {', '.join(missing)}. TRELLIS.2 nodes are built into "
                            "ComfyUI 0.43.0 and newer: update ComfyUI (python main.py --version shows yours)")
    need = ([] if args.reference_only else load_lock()["models"]) + (klein_models() if args.prompt else [])
    if args.prompt and not klein_models():
        raise ToolError(f"--prompt needs Dotwork's model register ({rel(TOOLS.parent, DOTWORK_LOCK)}); use --image")
    gone = missing_models(info, need)
    if gone:
        raise ToolError("model files missing in ComfyUI (download each into the folder shown, then restart "
                        "ComfyUI; `check` lists them too):\n" + "\n".join(model_lines(m) for m in gone))
    return base, blender, (wf3d, wfref), stats


# ---- make: steps ----------------------------------------------------------------------------
def write_new(path, data, overwrite):
    if path.exists() and not overwrite:
        raise ToolError(f"{path.name} exists; pass --overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def make_reference(args, plan, base, wfref):
    """reference.png in the source folder: the --image copied (EXIF, XMP, text and comments removed; a .jpg or .webp
    keeps its format), or a FLUX.2 klein render."""
    # an audition (--reference-only) is named by its seed, so several sit side by side to choose from
    dest = plan.src / (f"reference_seed{args.seed}.png" if args.reference_only else "reference.png")
    if args.image:
        # the copy is committed with the game: EXIF (GPS, camera), XMP, text and comments go, the pixels stay
        try:
            data = comfy(cl.strip_picture, plan.image.read_bytes())
        except ToolError as exc:
            raise ToolError(f"--image {plan.image.name}: {exc}")
        if plan.image.suffix.lower() != ".png":
            dest = plan.src / f"reference{plan.image.suffix.lower()}"
        write_new(dest, data, True)
        print(f"[ OK ] reference: {rel(plan.root, dest)} (from --image, metadata removed)")
        return dest, {"kind": "image", "sha256": sha256_bytes(data)}
    cls_kind = "character" if plan.cls in ("hero", "npc") else "object"
    text = args.prompt if args.raw_prompt else REF_TEMPLATES[cls_kind].format(prompt=args.prompt.strip().rstrip("."))
    wf = json.loads(json.dumps(wfref))
    wf[node_id(wf, NODES["prompt"])]["inputs"]["text"] = text
    wf[node_id(wf, NODES["ref_seed"])]["inputs"]["noise_seed"] = args.seed
    entry, seconds, _ = run_job(base, wf, "reference image (FLUX.2 klein 4B)", args.wait)
    items = [i for i in cl.output_files(entry, False) if i["filename"].lower().endswith(".png")]
    if not items:
        raise JobError("the reference job saved no image")
    data = comfy(cl.strip_png, fetch(base, items[0]))
    write_new(dest, data, True)
    print(f"[ OK ] reference: {rel(plan.root, dest)} ({seconds:.0f} s on the GPU, seed {args.seed})")
    return dest, {"kind": "prompt", "prompt": args.prompt, "full_prompt": text, "seed": args.seed,
                  "model": "FLUX.2 klein 4B", "gpu_seconds": round(seconds, 1), "sha256": sha256_bytes(data)}


def prune_to(wf, title):
    """Only the node with this title and the nodes it reads from. ComfyUI runs every Save node in a graph, so the
    branch a job does not use (the unwrap and the bakes for --material vertex) would cost GPU minutes."""
    need, stack = set(), [node_id(wf, title)]
    while stack:
        nid = stack.pop()
        if nid in need:
            continue
        need.add(nid)
        stack += [v[0] for v in wf[nid].get("inputs", {}).values()
                  if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] in wf]
    return {k: v for k, v in wf.items() if k in need}


def make_mesh(args, plan, base, wf3d, reference):
    """TRELLIS.2 over ComfyUI: returns (raw .glb path, job facts)."""
    sets = {NODES["resolution"]: ("target_resolution", QUALITY[args.quality]),
            NODES["faces"]: ("target_face_count", plan.faces),
            NODES["unwrap"]: ("resolution", plan.texture), NODES["bake"]: ("texture_size", plan.texture),
            NODES["normal"]: ("resolution", plan.texture)}
    ids = {title: node_id(wf3d, title) for title in sets}   # every title must be in the workflow, used or not
    want = NODES["textured"] if args.material == "texture" else NODES["vertex"]
    wf = prune_to(json.loads(json.dumps(wf3d)), want)
    settings = comfy(cl.apply_images, base, wf, [f"{NODES['image']}={reference}"], False)
    settings += comfy(cl.apply_seed, wf, args.seed)
    for title, (field, value) in sets.items():
        nid = ids[title]
        if nid in wf:                    # the bake settings only on a texture job
            wf[nid]["inputs"][field] = value
            settings.append(f"{nid}.{field}={value}")
    entry, seconds, vram = run_job(base, wf, f"3D model (TRELLIS.2, {args.quality} quality)", args.wait)
    items = [i for i in outputs_of(entry, node_id(wf, want)) if i["filename"].lower().endswith(".glb")]
    if not items:
        raise JobError("the 3D job finished but saved no .glb (does the workflow still end in Save 3D Model?)")
    data = comfy(cl.strip_glb, fetch(base, items[0]))
    raw = plan.src / "raw.glb"
    write_new(raw, data, True)
    doc, _ = cl.read_glb(data)
    print(f"[ OK ] raw mesh: {rel(plan.root, raw)} ({glb_triangles(doc):,} triangles, {seconds:.0f} s on the GPU"
          + (f", VRAM peak {vram / 1024:.1f} GB" if vram else "") + ")")
    return raw, {"gpu_seconds": round(seconds, 1), "vram_peak_mib": vram, "settings": settings,
                 "tris_raw": glb_triangles(doc), "sha256": sha256_bytes(data)}


def glb_triangles(doc):
    tris = 0
    for mesh in doc.get("meshes", []):
        for p in mesh.get("primitives", []):
            if p.get("mode", 4) != 4:
                continue
            acc = doc["accessors"][p["indices"]] if "indices" in p else doc["accessors"][p["attributes"]["POSITION"]]
            tris += acc["count"] // 3
    return tris


def blender_steps(args, plan, blender, raw):
    """cleanup.py -> prep_export.py -> validate_asset.py. Returns (exported main, LODs, cleanup report, validation)."""
    clean = plan.src / "clean.glb"
    rc, _ = run_bpy(blender, HERE / "cleanup.py",
                    [raw, "--out", clean, "--name", plan.name, "--max-tris", plan.faces, "--height", plan.height,
                     "--turn", args.turn, "--json", plan.src / "cleanup.json", "--overwrite"]
                    + (["--debug"] if DEBUG else []), "cleanup")
    if rc != 0:
        raise (JobError if rc == 1 else ToolError)(f"cleanup.py failed (exit {rc}); --debug shows Blender's output")
    export = plan.src / "export" / f"{plan.name}.glb"
    rc, _ = run_bpy(blender, TOOLS / "blender" / "prep_export.py",
                    [clean, "--out", export, "--class", plan.cls, "--no-validate", "--overwrite"]
                    + (["--lods", ",".join(str(r) for r in plan.lods)] if plan.lods else []), "prep_export")
    if rc != 0:
        raise (JobError if rc == 1 else ToolError)(f"prep_export.py failed (exit {rc})")
    report = plan.src / "validate.json"
    if report.exists():                  # a report from an earlier run must never stand in for this one
        report.unlink()
    rc, _ = run_bpy(blender, TOOLS / "blender" / "validate_asset.py",
                    [export, "--class", plan.cls, "--json", report], "validate_asset")
    if rc == 2:
        raise ToolError("validate_asset.py could not run (exit 2)")
    if rc not in (0, 1) or not report.is_file():   # a crash (any other code) or no report: nothing is checked
        raise JobError(f"validate_asset.py did not finish (exit {rc}{', no report' if rc in (0, 1) else ''}); "
                       f"nothing was copied into {rel(plan.root, plan.out_dir)}. --debug shows Blender's output")
    validation = json.loads(report.read_text(encoding="utf-8"))
    validation["asset"] = rel(plan.root, export)   # the validator writes the path it was given (absolute)
    report.write_text(json.dumps(validation, indent=2), encoding="utf-8")
    cleanup = json.loads((plan.src / "cleanup.json").read_text(encoding="utf-8"))
    lods = [export.with_name(f"{export.stem}_LOD{i}.glb") for i in range(1, len(plan.lods) + 1)]
    if rc == 1:
        fails = "; ".join(validation.get("failures", [])) or "see validate.json"
        raise JobError(f"{plan.name} fails the {plan.cls} budget: {fails}. Nothing was copied into "
                       f"{rel(plan.root, plan.out_dir)}; the files are in {rel(plan.root, plan.src)}/")
    return export, lods, cleanup, validation


def install(plan, export, lods, overwrite):
    placed = []
    for src, dst in zip([export] + lods, [plan.main] + plan.lod_files):
        write_new(dst, src.read_bytes(), overwrite)
        placed.append(dst)
        print(f"[ OK ] {rel(plan.root, dst)}")
    return placed


def models_used(prompt_route):
    lock = load_lock()["models"]
    used = [{k: m[k] for k in ("file", "repo", "commit", "license", "role")} for m in lock]
    if prompt_route:
        used += [{"file": m["file"], "repo": m["repo"], "commit": m["commit"], "license": m["license"],
                  "role": "reference image (FLUX.2 klein 4B)"} for m in klein_models()]
    return used


def copy_licence_texts(plan):
    """The model licence texts into the game's docs/licenses/ (first time only; credits.py ships them)."""
    dest = plan.root / fetch_asset.LICENSE_DIR
    added = []
    for src in sorted(LICENSE_TEXTS.glob("*")):
        target = dest / f"{TOOL.lower()}-{src.name}"
        if not target.exists():
            dest.mkdir(parents=True, exist_ok=True)
            target.write_bytes(src.read_bytes())
            added.append(target)
    if added:
        print(f"[ OK ] model licence texts added to {fetch_asset.LICENSE_DIR.as_posix()}/: "
              f"{', '.join(p.name for p in added)}")


def write_log(plan, record):
    """ASSET_LOG row (updated in place when this model was logged before) + docs/licenses/A-NNNN.txt."""
    text = plan.log_path.read_text(encoding="utf-8")
    files = record["files"]
    main_rel = rel(plan.root, plan.main)
    existing = [l for l in text.splitlines() if l.startswith("| A-") and f"`{main_rel}`" in l]
    if existing:
        aid, fill = existing[0].split("|")[1].strip(), None
    else:
        num, fill = fetch_asset.next_asset_id(text)
        aid = f"A-{num:04d}"
    licences = sorted({m["license"] for m in record["models"]})
    ref = record["reference"]
    notes = "; ".join(x for x in [
        f"{TOOL} {plan.cls}",
        f"prompt: {ref['prompt'][:160]}" if ref.get("prompt") else "reference image supplied (see the record)",
        f"seed {record['seed']}", f"{record['tris']} triangles", f"GPU {record['job']['gpu_seconds']:.0f} s",
        f"record `{rel(plan.root, plan.src / RECORD)}`"] if x)
    shown = ", ".join(f"`{f['file']}`" for f in files)
    source = f"{TOOL} (local ComfyUI: TRELLIS.2 4B" + (", FLUX.2 klein 4B reference" if ref["kind"] == "prompt" else "") + ")"
    row = (f"| {aid} | model | {shown} | {fetch_asset.md_cell(source)} | generated locally | "
           f"{fetch_asset.md_cell(', '.join(licences))} | {fetch_asset.md_cell(ATTRIBUTION)} | pre-generated | no | "
           f"{record['date']} | {fetch_asset.md_cell(notes)} |")
    ev = [f"{aid}  model  generated {record['date']} with tools/{TOOL.lower()}/{TOOL.lower()}.py {VERSION}",
          f"Class    : {plan.cls} (budget {plan.budget['max_tris']} triangles, {plan.budget['max_dim']} m), "
          f"height {plan.height} m, seed {record['seed']}, quality {record['quality']}",
          f"Reference: {ref['kind']}" + (f", prompt: {ref['prompt']}" if ref.get("prompt") else "")
          + f", SHA-256 {ref['sha256']}",
          f"ComfyUI  : {record['comfyui']}, workflow SHA-256 {record['workflow_sha256']}",
          "Models   : " + "; ".join(f"{m['file']} ({m['repo']} @ {m['commit'][:12]}, {m['license']})"
                                    for m in record["models"]),
          f"Credit   : {ATTRIBUTION}",
          f"Licences : texts in {fetch_asset.LICENSE_DIR.as_posix()}/{TOOL.lower()}-*; the DINOv3 License restricts "
          "some uses (its section 1.b.v): read it before you ship"]
    ev += [f"File     : {f['file']}  SHA-256 {f['sha256']}  "
           + (f"{f['triangles']} triangles" if "triangles" in f else f.get("kind", "")) for f in files]
    new = text.replace(existing[0], row, 1) if existing else fetch_asset.add_log_row(text, row, fill)
    plan.log_path.write_bytes(new.encode("utf-8"))
    lic = plan.root / fetch_asset.LICENSE_DIR
    lic.mkdir(parents=True, exist_ok=True)
    (lic / f"{aid}.txt").write_bytes(("\n".join(ev) + "\n").encode("utf-8"))
    print(f"[ OK ] {aid} {'updated in' if existing else 'added to'} {fetch_asset.ASSET_LOG.as_posix()}, evidence "
          f"{(fetch_asset.LICENSE_DIR / (aid + '.txt')).as_posix()}")
    copy_licence_texts(plan)
    return aid


def sprites(args, plan, blender):
    """The --sprites sheet (and its layout .json), rendered from the installed model before the log is written, so
    the sheet gets its row and hash. Returns an error message for the end of the run, or None."""
    if not plan.sprites:
        return None
    rc, _ = run_bpy(blender, TOOLS / "blender" / "render_sprites.py",
                    [plan.main, "--out", plan.sprites, "--directions", "8", "--size", "128"]
                    + (["--overwrite"] if args.overwrite else []), "render_sprites")
    if rc != 0 or not plan.sprites.is_file():
        return (f"render_sprites.py failed (exit {rc}); the model is in place and logged, run it again by hand "
                "(SOP-11 'sprite sheets')")
    print(f"[ OK ] {rel(plan.root, plan.sprites)} (sprite sheet, layout in {plan.sprites.with_suffix('.json').name})")
    return None


def turntable(args, plan, blender):
    """Turntable sheet in the source folder. A failure here is a warning."""
    if not args.no_preview:
        rc, _ = run_bpy(blender, HERE / "turntable.py",
                        [plan.main, "--out", plan.src / "turntable.png", "--overwrite"], "turntable")
        if rc != 0:
            print(f"[warn] turntable preview failed (exit {rc}); the model itself is fine")


def cmd_make(args):
    t0 = time.monotonic()
    plan = Plan(args)
    if args.seed is None:
        args.seed = int(time.time()) % 100000
        print(f"[info] no --seed given: using {args.seed} (pass it to make the same model again)")
    base, blender, (wf3d, wfref), stats = preflight(args, plan)
    if blender:
        print(f"[info] Blender: {blender_version(blender) or blender[1]} ({'module' if blender[0] == 'bpy' else 'app'})")
    plan.src.mkdir(parents=True, exist_ok=True)
    reference, ref_facts = make_reference(args, plan, base, wfref)
    if args.reference_only:
        print(f"[ OK ] --reference-only: look at {rel(plan.root, reference)}; when it is right, run make again with "
              f"--image {rel(plan.root, reference)}")
        return 0
    if args.prompt:
        free_vram(base)
    raw, job = make_mesh(args, plan, base, wf3d, reference)
    export, lods, cleanup, validation = blender_steps(args, plan, blender, raw)
    placed = install(plan, export, lods, args.overwrite)
    sprite_error = sprites(args, plan, blender)
    files = []
    for p in placed:
        data = p.read_bytes()
        files.append({"file": rel(plan.root, p), "sha256": sha256_bytes(data),
                      "triangles": glb_triangles(cl.read_glb(data)[0])})
    if plan.sprites and not sprite_error:   # the sheet ships in the game too: it gets its hash and the log row
        files.append({"file": rel(plan.root, plan.sprites), "sha256": sha256_bytes(plan.sprites.read_bytes()),
                      "kind": "sprite sheet"})
    record = {"tool": f"{TOOL} {VERSION}", "date": datetime.date.today().isoformat(), "name": plan.name,
              "class": plan.cls, "budget": plan.budget, "height_m": plan.height, "seed": args.seed,
              "quality": args.quality, "material": args.material, "texture_px": plan.texture, "lods": plan.lods,
              "reference": dict(ref_facts, file=rel(plan.root, reference)),
              "workflow": rel(TOOLS.parent, args.workflow or WORKFLOW_3D),
              "workflow_sha256": sha256_bytes(Path(args.workflow or WORKFLOW_3D).read_bytes()),
              "comfyui": (stats.get("system") or {}).get("comfyui_version"), "job": job,
              "cleanup": cleanup, "validation": {k: validation.get(k) for k in ("failures", "warnings", "notes",
                                                                                "objects", "total_tris")},
              "tris": files[0]["triangles"], "files": files, "models": models_used(bool(args.prompt)),
              "blender": blender_version(blender)}
    write_new(plan.src / RECORD, json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8"), True)
    if plan.log:
        write_log(plan, record)
    turntable(args, plan, blender)
    if sprite_error:
        raise JobError(sprite_error)
    warns = len(validation.get("warnings") or [])
    print(f"[ OK ] {plan.name}: {files[0]['triangles']:,} triangles, {plan.height} m tall, "
          f"{len(placed)} file(s) in {rel(plan.root, plan.out_dir)}, {time.monotonic() - t0:.0f} s in all"
          + (f"; {warns} validator warning(s) in {rel(plan.root, plan.src / 'validate.json')}" if warns else ""))
    godot = (plan.root / "project.godot").is_file()
    print(f"[next] look at {rel(plan.root, plan.src / 'turntable.png')}, then import it in the engine "
          + ("(`python tools/dev.py import`, or let check, test or smoke import it: they import new assets)"
             if godot else "(docs/ENGINE.md)") + "; a generated mesh is a draft (SOP-11)")
    return 0


# ---- check / list / test --------------------------------------------------------------------
def cmd_check(args):
    results = []

    def say(level, msg):
        print({"ok": "[ OK ]", "warn": "[warn]", "error": "[FAIL]", "info": "[info]"}[level] + " " + msg)
        results.append(level)

    say("ok" if sys.version_info >= (3, 8) else "error", f"Python {sys.version.split()[0]}")
    lock = load_lock()
    blender = find_blender(args.blender)
    if blender:
        say("ok", f"{blender_version(blender) or 'Blender (version unknown)'} "
                  f"({'bpy module in this Python' if blender[0] == 'bpy' else 'app: ' + Path(blender[1]).name})")
    else:
        say("error", f"Blender not found ({BLENDER_ENV}, PATH, default install, or the bpy module): cleanup, export "
                     "and the budget check need it")
    try:
        base = comfy_base(args)
        say("ok", cl.system_text(comfy(cl.get_json, base, "/system_stats")))
        info = comfy(cl.get_json, base, "/object_info")
    except ToolError as exc:
        say("error", str(exc))
        info = None
    wf3d = load_workflow(args.workflow or WORKFLOW_3D)
    wfref = load_workflow(WORKFLOW_REF)
    for wf, label in ((wf3d, "3D workflow"), (wfref, "reference workflow")):
        bad = non_commercial_in(wf)
        if bad:
            say("warn", f"{label} names non-commercial pieces: {', '.join(bad)} ({TOOL} refuses to run it)")
    if info is None:
        say("info", "model files (NOT checked: start ComfyUI and run check again):")
        for m in lock["models"]:
            print(model_lines(m))
    else:
        for wf, label, required in ((wf3d, "3D workflow", True), (wfref, "--prompt reference workflow", False)):
            missing = cl.missing_nodes(wf, info)
            if missing:
                say("error" if required else "warn", f"{label}: node types missing in ComfyUI: {', '.join(missing)} "
                                                      "(ComfyUI 0.43.0+ has them built in)")
            else:
                say("ok", f"{label}: all {len(wf)} nodes installed")
        gone = missing_models(info, lock["models"])
        size = sum(m["size"] for m in lock["models"]) / 1024 ** 3
        if gone:
            say("error", f"{len(gone)} of {len(lock['models'])} model files missing ({size:.1f} GB in all):")
            for m in gone:
                print(model_lines(m))
        else:
            say("ok", f"all {len(lock['models'])} model files present ({size:.1f} GB: "
                      + ", ".join(sorted({m['license'] for m in lock['models']})) + ")")
        kl = klein_models()
        kgone = missing_models(info, kl) if kl else []
        if not kl:
            say("warn", "Dotwork's model register not found: --prompt cannot run (--image works)")
        elif kgone:
            say("warn", f"--prompt needs FLUX.2 klein files that are missing (--image still works):")
            for m in kgone:
                print(model_lines(m))
        else:
            say("ok", f"--prompt: FLUX.2 klein 4B files present ({len(kl)} files, Apache-2.0)")
    if args.hash:
        root = os.environ.get("COMFYUI_ROOT")
        if not root:
            say("warn", "--hash needs COMFYUI_ROOT (the model files are read from disk)")
        else:
            for m in lock["models"]:
                p = Path(root) / "models" / m["folder"] / m["file"]
                if p.is_file():
                    h = hashlib.sha256()
                    with open(p, "rb") as f:
                        for chunk in iter(lambda: f.read(1 << 24), b""):
                            h.update(chunk)
                    ok = h.hexdigest() == m["sha256"]
                    say("ok" if ok else "error", f"{m['file']} SHA-256 {'matches' if ok else 'DIFFERS from'} the lock")
                else:
                    say("info", f"{m['file']}: not on disk, nothing to hash")
    say("info", "licences: TRELLIS.2 and BiRefNet MIT; DINOv3 License (use restrictions in its section 1.b.v): "
                "LICENSES.md")
    bad = "error" in results
    print(f"\n{'[FAIL] not ready: fix the [FAIL] lines above (README: Setup)' if bad else '[ OK ] ready'}")
    return 2 if bad else 0


STEPS = [
    ("reference", "--image as given, or --prompt -> FLUX.2 klein 4B (Apache-2.0) on a plain background"),
    ("generate", "TRELLIS.2 4B through ComfyUI: BiRefNet background removal, shape, texture bake (MIT; DINOv3 License)"),
    ("cleanup", "cleanup.py in Blender: merge, drop fragments, normals, decimate to budget, height, pivot"),
    ("export", "tools/blender/prep_export.py: the kit's one glTF preset, LODs"),
    ("validate", "tools/blender/validate_asset.py --class: budget, size, UVs; nothing ships when it fails"),
    ("log", "docs/ASSET_LOG.md row (pre-generated AI), evidence file, model licence texts"),
    ("preview", "turntable.py contact sheet; render_sprites.py sheet with --sprites"),
]


def cmd_list(args):
    print(f"{TOOL}: the kit's local 3D asset lane. python tools/{TOOL.lower()}/{TOOL.lower()}.py <subcommand>\n")
    print("  check     what is ready here        test      the exams (--live adds one GPU run)")
    print("  make      a model from --image or --prompt (make --help for every option)\n\nSteps of make:")
    for name, what in STEPS:
        print(f"  {name:9} {what}")
    print("\nClasses (budgets from tools/blender/validate_asset.py, SOP-11):")
    for c, s in CLASS_SETTINGS.items():
        b = va.CLASS_BUDGETS[c]
        print(f"  {c:5} up to {b['max_tris']:>6,} triangles, {s['height']} m tall by default, {s['texture']} px "
              f"textures, LODs {','.join(str(x) for x in s['lods']) or 'none'}")
    return 0


def cmd_test(args):
    exams = [HERE / "test_bozzetto.py", HERE / "test_rig.py", HERE / "test_chain.py"] + \
        ([HERE / "test_bozzetto_live.py"] if args.live else [])
    failed = 0
    for exam in exams:
        t0 = time.monotonic()
        proc = subprocess.run([sys.executable, "-B", str(exam)], capture_output=True, encoding="utf-8",
                              errors="replace")
        tail = [l for l in (proc.stdout + proc.stderr).splitlines() if l.strip()][-3:]
        print(f"[{' OK ' if proc.returncode == 0 else 'FAIL'}] {exam.name} ({time.monotonic() - t0:.0f} s): "
              + " | ".join(tail))
        failed += proc.returncode != 0
    return 1 if failed else 0


# ---- arguments ----------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(
        prog=f"{TOOL.lower()}.py", formatter_class=argparse.RawDescriptionHelpFormatter,
        description=f"{TOOL}: a reference image or a prompt to a budgeted, game-ready .glb on your own GPU "
                    "(TRELLIS.2 in a local ComfyUI, cleanup and checks in Blender).",
        epilog="Exit: 0 ok, 1 the job or the budget check failed, 2 usage, environment, missing models or files in "
               f"the way.\nEnv: {cl.URL_ENV} (default {cl.DEFAULT_URL}), {BLENDER_ENV} (blender executable), "
               "COMFYUI_ROOT (check --hash); rig: UNIRIG_DIR, UNIRIG_PY, TRIPO_API_KEY.\nREADME.md in this folder "
               "walks through setup and every option.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", help=f"ComfyUI address (default {cl.URL_ENV} or {cl.DEFAULT_URL})")
    common.add_argument("--allow-remote", action="store_true", help="allow a ComfyUI that is not on this machine")
    common.add_argument("--blender", help=f"Blender executable, or 'bpy' for the module in this Python "
                                          f"(default: {BLENDER_ENV}, PATH, the default install, then bpy)")
    common.add_argument("--workflow", help="a different API-format TRELLIS.2 workflow (same node titles)")
    common.add_argument("--debug", action="store_true", help="show Blender's full output and tracebacks")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", parents=[common], help="the steps of make and the asset classes")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("check", parents=[common], help="ComfyUI, nodes, model files, Blender: what is ready")
    p.add_argument("--hash", action="store_true", help="also check each model file's SHA-256 (needs COMFYUI_ROOT)")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("test", parents=[common], help="run the exams")
    p.add_argument("--live", action="store_true", help="also the live exam (one real GPU run, about 6 minutes)")
    p.set_defaults(fn=cmd_test)
    p = sub.add_parser("make", parents=[common], help="make one model", formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="Classes and budgets: `list`. Sources and reports land in assets_src/bozzetto/<name>/.")
    p.add_argument("name", help="asset name: lowercase, digits, underscores (prop_crate, npc_guard)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--image", help="reference picture: one object, whole, plain background (.png .jpg .webp)")
    src.add_argument("--prompt", help="describe the object; FLUX.2 klein draws the reference first")
    p.add_argument("--raw-prompt", action="store_true", help="send --prompt as written (no 'plain background...' suffix)")
    p.add_argument("--reference-only", action="store_true", help="with --prompt: stop after the reference image")
    p.add_argument("--class", dest="asset_class", choices=sorted(CLASS_SETTINGS), default="prop",
                   help="budget class from SOP-11 (default prop)")
    p.add_argument("--seed", type=int, help="seed for every sampler (default: from the clock, printed)")
    p.add_argument("--out", help=f"models folder in the game (default {DEFAULT_OUT}; web and web-3d "
                                 "public/assets/models, Unity Assets/Models, Unreal SourceArt/Models)")
    p.add_argument("--project", default=".", help="the game's root folder (default: the current folder)")
    p.add_argument("--lods", help="LOD ratios, e.g. 0.5,0.25, or none (default per class: `list`)")
    p.add_argument("--height", type=float, help="height in metres (default per class: prop 1.0, kit 3.0, hero/npc 1.8)")
    p.add_argument("--turn", type=float, default=0.0, help="degrees to turn around the up axis if the front is wrong")
    p.add_argument("--texture", type=int, choices=(512, 1024, 2048), help="baked texture size (default per class)")
    p.add_argument("--quality", choices=sorted(QUALITY), default="normal",
                   help="TRELLIS.2 resolution: normal 1024 (about 5 min), high 1536 (about 19 min)")
    p.add_argument("--material", choices=("texture", "vertex"), default="texture",
                   help="baked PBR textures (default), or vertex colours: no textures, smaller, and the unwrap and "
                        "bakes do not run (cleanup.py adds a UV map for lightmaps)")
    p.add_argument("--sprites", help="also render an 8-direction sprite sheet PNG here (2D games, SOP-11)")
    p.add_argument("--no-preview", action="store_true", help="skip the turntable contact sheet")
    p.add_argument("--no-log", action="store_true", help="do not touch docs/ASSET_LOG.md (scratch runs)")
    p.add_argument("--overwrite", action="store_true", help="replace this model's files from an earlier run")
    p.add_argument("--wait", type=int, default=WAIT_S, help=f"seconds to wait for each ComfyUI job (default {WAIT_S})")
    p.set_defaults(fn=cmd_make)
    import rig as rig_mod   # noqa: E402  (rig.py: the rig subcommand)
    rig_mod.bind(sys.modules[__name__])
    rig_mod.add_parser(sub, common)
    return ap


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    DEBUG = args.debug
    if getattr(args, "reference_only", False) and not args.prompt:
        print("[error] --reference-only goes with --prompt (an --image is already the reference)", file=sys.stderr)
        return 2
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

#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# rig.py
# Purpose : `bozzetto.py rig`: give a character in the game a skeleton, skin weights and (optionally) clips, then
#           prove the rig deforms and log it. Two routes: UniRig on your own GPU (free; needs a patched UniRig
#           checkout and its Python env), or the Tripo3D API (paid credits, any machine, Mixamo bones and mocap-like
#           clips). Either way rig_finish.py checks the weights, gives the bones Mixamo names and writes the .glb.
# Usage   : python tools/bozzetto/bozzetto.py rig check                       # what is ready for each route
#           python tools/bozzetto/bozzetto.py rig make npc_guard               # UniRig, clips idle,wave,walk
#           python tools/bozzetto/bozzetto.py rig make npc_guard --animate none --names keep
#           python tools/bozzetto/bozzetto.py rig make npc_guard --with tripo --clips idle,walk,run
#           Input: <models folder>/<name>.glb (a Bozzetto model), or --input any .glb. Output:
#           <models folder>/<name>_rigged.glb; sources and reports in assets_src/bozzetto/<name>/rig/<route>/.
# Needs   : Python 3.8+ (standard library), Blender 4.2+ or bpy. UniRig: UNIRIG_DIR (a checkout patched by
#           rig/patch_unirig.py) and its env (UNIRIG_PY, default <UNIRIG_DIR>/.venv); an NVIDIA GPU, about 16 GB.
#           Tripo: TRIPO_API_KEY (paid API credits; a Tripo Studio plan does not add API credits).
# Exit    : 0 ok, 1 the rig failed its checks or a job failed, 2 usage, environment, credits or files in the way
# Notes   : UniRig steps are UniRig's own four (extract, skeleton, extract, skin, merge), run with its Python in its
#           folder; ComfyUI is asked to unload its models first (UniRig needs nearly all 16 GB). Tripo: upload ->
#           rig-check (free) -> rig (Mixamo spec, 25 credits) -> retarget (10 credits a clip) -> download; the
#           quote is printed first and the run refuses past --max-credits or the balance. Tripo returns every model
#           1.0 m tall: rig_finish.py scales it back by 1/normalize_scale. Paid outputs are yours under Tripo's
#           terms (5.2.2); outputs from free credits are not.
#           Licences: UniRig MIT; its checkpoint was trained on Articulation-XL2.0 (CC-BY-4.0: the credit goes in
#           the asset log and docs/licenses/).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   check: Blender | UNIRIG_DIR -> patched? -> its python imports torch, spconv, bpy | TRIPO_API_KEY -> balance
#   make:  name, input, output free, asset log, Blender, route ready [before any GPU time or credit]
#          unirig: free ComfyUI VRAM -> 5 steps (each logged, timed) -> rigged.glb
#          tripo:  quote <= max credits and balance -> upload -> rig-check (biped?) -> rig -> retarget -> download
#          rig_finish.py (scale, weights, Mixamo names, clips) -> fail: stop, exit 1, nothing placed
#          copy into the models folder -> record rig.json -> ASSET_LOG row (rig of A-NNNN) -> licence texts
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

bz = None   # bozzetto.py binds itself here (bind): importing it again would load a second copy

HERE = Path(__file__).resolve().parent
RIG_DIR = HERE / "rig"
FINISH = HERE / "rig_finish.py"
PATCHER = RIG_DIR / "patch_unirig.py"
RIG_LICENSES = RIG_DIR / "licenses"
UNIRIG_ENV, UNIRIG_PY_ENV, TRIPO_ENV = "UNIRIG_DIR", "UNIRIG_PY", "TRIPO_API_KEY"
TRIPO_BASE = "https://openapi.tripo3d.ai/v3"
TRIPO_RIG_MODEL = "v3.0-20260909"
TRIPO_COST = {"rig": 25, "clip": 10}          # credits (1 credit = $0.01), read 2026-11-05
TRIPO_CLIPS = ("idle", "walk", "run", "dive", "climb", "jump", "slash", "shoot", "hurt", "fall", "turn")
CLIPS_DEFAULT = "idle,wave,walk"
SUFFIXES = "obj,fbx,FBX,dae,glb,gltf,vrm"
STEP_WAIT_S = 1800
POLL_S = 3
RECORD = "rig.json"
CREDIT_UNIRIG = ("Rig by UniRig (VAST-AI-Research, MIT); its checkpoint was trained on Articulation-XL2.0 "
                 "(Seed3D, CC-BY-4.0).")
CREDIT_TRIPO = "Rig and clips by the Tripo3D API (paid credits; outputs owned by the paying user, Tripo terms 5.2.2)."
OPENER = urllib.request.urlopen              # the exam replaces it
PROBE = True                                 # import torch/spconv/bpy in UniRig's env (the exam turns it off)


def bind(module):
    """Use the running bozzetto module (its DEBUG flag, Blender helpers, error types)."""
    global bz
    bz = module


# ---- UniRig ---------------------------------------------------------------------------------------------------
def unirig_dir():
    d = os.environ.get(UNIRIG_ENV)
    return Path(d) if d else None


def unirig_python(d):
    env = os.environ.get(UNIRIG_PY_ENV)
    if env:
        return Path(env)
    for p in (d / ".venv" / "Scripts" / "python.exe", d / ".venv" / "bin" / "python"):
        if p.is_file():
            return p
    return None


def unirig_problems(probe=None):
    """[] when UniRig is ready, else what is missing (plain words)."""
    probe = PROBE if probe is None else probe
    d = unirig_dir()
    if d is None:
        return [f"{UNIRIG_ENV} is not set: clone https://github.com/VAST-AI-Research/UniRig, run "
                f"`python tools/bozzetto/rig/patch_unirig.py <checkout>`, make its env (README 'Rig a character'), "
                f"then set {UNIRIG_ENV}"]
    if not (d / "run.py").is_file():
        return [f"{UNIRIG_ENV}={d} is not a UniRig checkout (no run.py)"]
    out = []
    proc = subprocess.run([sys.executable, str(PATCHER), str(d), "--check"], capture_output=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        out.append("the UniRig checkout is not patched: run `python tools/bozzetto/rig/patch_unirig.py "
                   f"{d}` (it is safe to run twice)")
    py = unirig_python(d)
    if py is None or not py.is_file():
        out.append(f"no Python env for UniRig: make {d / '.venv'} (README 'Rig a character') or set {UNIRIG_PY_ENV}")
    elif probe:
        code = "import torch, spconv, bpy; print(torch.__version__, torch.cuda.is_available())"
        p = subprocess.run([str(py), "-c", code], capture_output=True, encoding="utf-8", errors="replace",
                           cwd=str(d), timeout=600)
        if p.returncode != 0:
            last = (p.stderr or p.stdout).strip().splitlines()[-1:] or ["no output"]
            out.append(f"UniRig's env cannot import torch, spconv and bpy: {last[0]}")
        elif p.stdout.split()[-1:] != ["True"]:
            out.append("UniRig's PyTorch sees no CUDA GPU (UniRig needs an NVIDIA card)")
    return out


def run_unirig(inp, work, log):
    """UniRig's own steps, called directly (its bash launchers do not run on Windows). Returns (rigged.glb, timings,
    VRAM peak MiB or None)."""
    d = unirig_dir()
    py = str(unirig_python(d))
    stamp = time.strftime("%Y_%m_%d_%H_%M_%S")
    npz = work / "npz"
    skel, skin, merged = work / "skeleton.fbx", work / "skin.fbx", work / "rigged.glb"
    extract = ["-m", "src.data.extract", "--config=configs/data/quick_inference.yaml", f"--require_suffix={SUFFIXES}",
               "--force_override=true", "--num_runs=1", "--id=0", f"--time={stamp}", "--faces_target_count=50000",
               f"--output_dir={npz}"]
    steps = [
        ("extract mesh", extract + [f"--input={inp}"]),
        ("skeleton", ["run.py", "--task=configs/task/quick_inference_skeleton_articulationxl_ar_256.yaml",
                      "--seed=12345", f"--input={inp}", f"--output={skel}", f"--npz_dir={npz}"]),
        ("extract skeleton", extract + [f"--input={skel}"]),
        ("skin", ["run.py", "--task=configs/task/quick_inference_unirig_skin.yaml", "--seed=12345",
                  f"--input={skel}", f"--output={skin}", f"--npz_dir={npz}", "--data_name=raw_data.npz"]),
        ("merge", ["-m", "src.inference.merge", f"--require_suffix={SUFFIXES}", "--num_runs=1", "--id=0",
                   f"--source={skin}", f"--target={inp}", f"--output={merged}"]),
    ]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    sampler = bz.VramPeak()
    sampler.start()
    times = {}
    try:
        with open(log, "w", encoding="utf-8") as fh:
            for what, argv in steps:
                t0 = time.monotonic()
                fh.write(f"### {what}: {' '.join(argv)}\n")
                fh.flush()
                try:
                    proc = subprocess.run([py] + argv, cwd=str(d), env=env, stdout=fh, stderr=subprocess.STDOUT,
                                          timeout=STEP_WAIT_S)
                except subprocess.TimeoutExpired:
                    raise bz.JobError(f"UniRig {what} did not finish in {STEP_WAIT_S} s (log: {log.name})")
                times[what] = round(time.monotonic() - t0, 1)
                print(f"[ OK ] UniRig {what}: {times[what]:.0f} s" if proc.returncode == 0 else
                      f"[FAIL] UniRig {what}: exit {proc.returncode}", flush=True)
                if proc.returncode != 0:
                    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
                    print("\n".join("       " + l for l in tail))
                    raise bz.JobError(f"UniRig {what} failed (exit {proc.returncode}); the whole log is "
                                      f"{log.as_posix()}")
    finally:
        sampler.stop.set()
        sampler.join(15)
    if not merged.is_file():
        raise bz.JobError("UniRig's merge wrote no rigged.glb")
    return merged, times, sampler.peak


# ---- Tripo ----------------------------------------------------------------------------------------------------
class Tripo:
    def __init__(self, key, base=TRIPO_BASE):
        self.key, self.base = key, base.rstrip("/")

    def call(self, method, path, body=None, raw=None, ctype=None):
        h = {"Authorization": f"Bearer {self.key}"}
        data = None
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        if raw is not None:
            data, h["Content-Type"] = raw, ctype
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with OPENER(req, timeout=180) as r:
                doc = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            if e.code in (401, 403):
                raise bz.ToolError(f"Tripo refused the key (HTTP {e.code}): check {TRIPO_ENV}")
            raise bz.JobError(f"Tripo {path}: HTTP {e.code}: {msg}")
        except (urllib.error.URLError, OSError) as e:
            raise bz.ToolError(f"cannot reach Tripo ({self.base}): {e}")
        if doc.get("code", 0) != 0:
            raise bz.JobError(f"Tripo {path}: {doc.get('message') or doc}")
        return doc.get("data") or {}

    def balance(self):
        return float(self.call("GET", "/account/balance").get("balance", 0))

    def upload(self, path):
        b = "----bozzetto" + uuid.uuid4().hex
        raw = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
               f"Content-Type: model/gltf-binary\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{b}--\r\n".encode()
        tok = self.call("POST", "/files", raw=raw, ctype=f"multipart/form-data; boundary={b}").get("file_token")
        if not tok:
            raise bz.JobError("Tripo's upload returned no file_token")
        return tok

    def task(self, path, body, what, wait):
        tid = self.call("POST", path, body=body).get("task_id")
        if not tid:
            raise bz.JobError(f"Tripo {what}: no task id")
        t0 = time.monotonic()
        while True:
            d = self.call("GET", f"/tasks/{tid}")
            st = d.get("status")
            if st == "success":
                print(f"[ OK ] Tripo {what}: {time.monotonic() - t0:.0f} s, {d.get('credits_consumed', 0):g} credits",
                      flush=True)
                return tid, d
            if st in ("failed", "cancelled", "banned", "expired"):
                raise bz.JobError(f"Tripo {what}: {st}")
            if time.monotonic() - t0 > wait:
                raise bz.JobError(f"Tripo {what} did not finish in {wait} s (task {tid})")
            bz.SLEEP(POLL_S)

    def download(self, url, dst):
        try:
            with OPENER(urllib.request.Request(url), timeout=300) as r:
                dst.write_bytes(r.read())
        except (urllib.error.URLError, OSError) as e:
            raise bz.JobError(f"could not download Tripo's model (links expire after 5 minutes): {e}")


def tripo_clips(text):
    if text.strip().lower() in ("", "none"):
        return []
    clips = [c.strip().lower() for c in text.split(",") if c.strip()]
    bad = [c for c in clips if c not in TRIPO_CLIPS]
    if bad:
        raise bz.ToolError(f"Tripo has no clip {bad[0]!r} on its v3 rig; choose from {', '.join(TRIPO_CLIPS)}")
    if len(clips) > 5:
        raise bz.ToolError("Tripo retargets at most 5 clips per run")
    return clips


def run_tripo(args, inp, work, clips):
    """Quote, then upload -> rig-check -> rig -> retarget. Returns (rigged .glb, scale to apply, credits, tasks)."""
    t = Tripo(os.environ[TRIPO_ENV], getattr(args, "tripo_url", None) or TRIPO_BASE)
    quote = TRIPO_COST["rig"] + TRIPO_COST["clip"] * len(clips)
    bal = t.balance()
    print(f"[info] Tripo quote: {quote} credits (rig {TRIPO_COST['rig']} + {len(clips)} clip(s) x "
          f"{TRIPO_COST['clip']}); balance {bal:g}; limit --max-credits {args.max_credits}")
    if quote > args.max_credits:
        raise bz.ToolError(f"the quote ({quote} credits) is over --max-credits {args.max_credits}")
    if quote > bal:
        raise bz.ToolError(f"the Tripo balance ({bal:g} credits) is under the quote ({quote}); API credits are bought "
                           "separately from a Tripo Studio plan")
    tok = t.upload(inp)
    _, chk = t.task("/animations/rig-check", {"input": tok}, "rig check (free)", args.wait)
    out = chk.get("output") or {}
    if not out.get("riggable") or out.get("rig_type") != "biped":
        raise bz.JobError(f"Tripo says this model is not a riggable biped (riggable={out.get('riggable')}, "
                          f"type={out.get('rig_type')})")
    rig_id, rig = t.task("/animations/rig", {"input": tok, "model": TRIPO_RIG_MODEL, "rig_type": "biped",
                                             "spec": "mixamo"}, "rig (Mixamo bones)", args.wait)
    spent = float(rig.get("credits_consumed") or 0)
    tasks = {"rig_check": "free", "rig": rig_id}
    final = rig
    if clips:
        anim_id, final = t.task("/animations/retarget", {"input": rig_id, "animations": [f"preset:{c}" for c in clips],
                                                         "animate_in_place": True}, "clips", args.wait)
        spent += float(final.get("credits_consumed") or 0)
        tasks["retarget"] = anim_id
    url = (final.get("output") or {}).get("model_url")
    if not url:
        raise bz.JobError("Tripo returned no model URL")
    dst = work / "tripo.glb"
    t.download(url, dst)
    norm = (rig.get("output") or {}).get("normalize_scale") or (chk.get("output") or {}).get("normalize_scale") or 1.0
    return dst, 1.0 / float(norm), spent, tasks


# ---- commands -------------------------------------------------------------------------------------------------
def cmd_rig_check(args):
    ok = True
    blender = bz.find_blender(args.blender)
    print(f"[{' OK ' if blender else 'FAIL'}] Blender: " + (bz.blender_version(blender) or blender[1] if blender else
                                                             f"not found (set {bz.BLENDER_ENV})"))
    ok &= blender is not None
    probs = unirig_problems()
    print(f"[{' OK ' if not probs else 'MISS'}] UniRig route (free, local GPU)" + ("" if probs else f": {unirig_dir()}"))
    for p in probs:
        print(f"       {p}")
    if os.environ.get(TRIPO_ENV):
        try:
            print(f"[ OK ] Tripo route (paid): balance {Tripo(os.environ[TRIPO_ENV]).balance():g} credits")
        except (bz.ToolError, bz.JobError) as e:
            print(f"[FAIL] Tripo route: {e}")
    else:
        print(f"[MISS] Tripo route (paid): {TRIPO_ENV} is not set (optional)")
    ready = blender is not None and (not probs or bool(os.environ.get(TRIPO_ENV)))
    print("[ OK ] ready" if ready else "[FAIL] not ready: a route needs Blender plus UniRig or a Tripo key")
    return 0 if ready else 2


def resolve(args):
    root = Path(args.project).resolve()
    if not root.is_dir():
        raise bz.ToolError(f"--project {args.project} is not a folder")
    if not bz.NAME_RULE.match(args.name):
        raise bz.ToolError(f"name {args.name!r}: lowercase letters, digits and underscores")
    out = args.out or bz.default_out(root)
    out_dir = (root / out) if not Path(out).is_absolute() else Path(out)
    inp = Path(args.input) if args.input else out_dir / f"{args.name}.glb"
    if args.input and not inp.is_absolute() and not inp.is_file():
        inp = root / args.input
    if not inp.is_file():
        raise bz.ToolError(f"{bz.rel(root, inp)} not found: make the model first (bozzetto.py make {args.name} ...) "
                           "or pass --input")
    return root, out_dir, inp.resolve(), out_dir / f"{args.name}_rigged.glb", root / bz.SRC_ROOT / args.name / "rig" / args.backend


def cmd_rig_make(args):
    root, out_dir, inp, dst, work = resolve(args)
    route = args.backend
    clips_unirig = [] if args.animate.strip().lower() == "none" else [c.strip() for c in args.animate.split(",")]
    clips_tripo = tripo_clips(args.clips) if route == "tripo" else []
    if dst.exists() and not args.overwrite:
        raise bz.ToolError(f"{bz.rel(root, dst)} exists; pass --overwrite to rig it again")
    log_path = root / bz.fetch_asset.ASSET_LOG
    if not args.no_log and not log_path.is_file():
        raise bz.ToolError(f"{bz.fetch_asset.ASSET_LOG.as_posix()} not found under {root}: run from the game's root "
                           "folder (or --project), or pass --no-log")
    blender = bz.find_blender(args.blender)
    if blender is None:
        raise bz.ToolError(f"Blender not found (set {bz.BLENDER_ENV}); rig_finish.py runs in it")
    if route == "unirig":
        probs = unirig_problems()
        if probs:
            raise bz.ToolError("UniRig is not ready:\n" + "\n".join("  " + p for p in probs))
    elif not os.environ.get(TRIPO_ENV):
        raise bz.ToolError(f"--with tripo needs {TRIPO_ENV} (paid API credits)")
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    record = {"tool": f"tools/{bz.TOOL.lower()}/{bz.TOOL.lower()}.py rig {bz.VERSION}", "route": route,
              "input": bz.rel(root, inp), "input_sha256": bz.sha256_bytes(inp.read_bytes()),
              "date": time.strftime("%Y-%m-%d")}
    if route == "unirig":
        try:
            bz.free_vram(bz.comfy_base(args))      # UniRig needs nearly all of a 16 GB card
        except bz.ToolError:
            pass                                   # no ComfyUI running: nothing to free
        rigged, times, peak = run_unirig(inp, work, work / "unirig.log")
        scale, finish_clips = 1.0, ",".join(clips_unirig) or "none"
        record.update({"unirig_steps_s": times, "vram_peak_mib": peak, "clips": clips_unirig})
    else:
        rigged, scale, spent, tasks = run_tripo(args, inp, work, clips_tripo)
        finish_clips = "none"
        record.update({"tripo_credits": spent, "tripo_tasks": tasks, "clips": clips_tripo,
                       "tripo_rig_model": TRIPO_RIG_MODEL})
    report, finished = work / "rig_finish.json", work / "finished.glb"
    sheet = work / "clips.png"
    rc, _ = bz.run_bpy(blender, FINISH, [rigged, "--out", finished, "--scale", f"{scale:.6f}", "--names", args.names,
                                         "--animate", finish_clips, "--report", report]
                       + ([] if args.no_preview else ["--sheet", sheet]), "rig_finish")
    rep = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    record["checks"] = rep
    (work / RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if rc != 0 or not finished.is_file():
        raise bz.JobError(f"the rig failed its checks ({'; '.join(rep.get('failures', [])) or f'exit {rc}'}); "
                          f"nothing was copied into {bz.rel(root, out_dir)}; reports in {bz.rel(root, work)}/")
    bz.write_new(dst, finished.read_bytes(), args.overwrite)
    print(f"[ OK ] {bz.rel(root, dst)}")
    record["output"] = {"file": bz.rel(root, dst), "sha256": bz.sha256_bytes(dst.read_bytes()),
                        "clips": rep.get("clips", []), "bones": rep.get("bones")}
    (work / RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if not args.no_log:
        write_rig_log(root, log_path, dst, work, record, route)
    print(f"[ OK ] {args.name}: {rep.get('bones')} bones, clips {', '.join(rep.get('clips', [])) or 'none'}, "
          f"{time.monotonic() - t0:.0f} s in all" + (f", {record['tripo_credits']:g} Tripo credits"
                                                     if route == "tripo" else ""))
    print("[next] look at " + (bz.rel(root, sheet) if sheet.is_file() else "the model in the engine")
          + "; Unity: set the rig to Humanoid (Mixamo names map by themselves) (verify)")
    return 0


def write_rig_log(root, log_path, dst, work, record, route):
    """ASSET_LOG row for the rigged file (updated on a re-run) + evidence + licence texts (first time)."""
    fa = bz.fetch_asset
    text = log_path.read_text(encoding="utf-8")
    main_rel = bz.rel(root, dst)
    base_row = next((l for l in text.splitlines() if l.startswith("| A-") and f"`{record['input']}`" in l), None)
    base_id = base_row.split("|")[1].strip() if base_row else None
    existing = [l for l in text.splitlines() if l.startswith("| A-") and f"`{main_rel}`" in l]
    if existing:
        aid, fill = existing[0].split("|")[1].strip(), None
    else:
        num, fill = fa.next_asset_id(text)
        aid = f"A-{num:04d}"
    if route == "unirig":
        source, how, lic, credit = "UniRig (local, `bozzetto.py rig`)", "generated locally", \
            "UniRig MIT; Articulation-XL2.0 CC-BY-4.0", CREDIT_UNIRIG
    else:
        source, how, lic, credit = "Tripo3D API (`bozzetto.py rig --with tripo`)", "paid service", \
            "Tripo3D terms (paid output)", CREDIT_TRIPO
    clips = record["output"]["clips"]
    notes = "; ".join(x for x in [f"rig of {base_id}" if base_id else f"rig of `{record['input']}`",
                                  f"{record['output']['bones']} bones, Mixamo names",
                                  f"clips: {', '.join(clips)}" if clips else "no clips",
                                  f"{record['tripo_credits']:g} credits" if route == "tripo" else "",
                                  f"record `{bz.rel(root, work / RECORD)}`"] if x)
    row = (f"| {aid} | model | `{main_rel}` | {fa.md_cell(source)} | {how} | {fa.md_cell(lic)} | {fa.md_cell(credit)} | "
           f"pre-generated | no | {record['date']} | {fa.md_cell(notes)} |")
    new = text.replace(existing[0], row, 1) if existing else fa.add_log_row(text, row, fill)
    log_path.write_bytes(new.encode("utf-8"))
    ev = [f"{aid}  model  rigged {record['date']} with {record['tool']} ({route})",
          f"Input    : {record['input']}  SHA-256 {record['input_sha256']}" + (f" (asset {base_id})" if base_id else ""),
          f"Output   : {main_rel}  SHA-256 {record['output']['sha256']}",
          f"Checks   : {json.dumps({k: record['checks'].get(k) for k in ('vertices', 'unweighted', 'nan', 'bones_used', 'top_bone_share')})}",
          f"Clips    : {', '.join(clips) or 'none'}", f"Credit   : {credit}"]
    if route == "tripo":
        ev.append(f"Tripo    : {record['tripo_credits']:g} credits, tasks {record['tripo_tasks']}")
    lic_dir = root / fa.LICENSE_DIR
    lic_dir.mkdir(parents=True, exist_ok=True)
    (lic_dir / f"{aid}.txt").write_bytes(("\n".join(ev) + "\n").encode("utf-8"))
    if route == "unirig":
        for src in sorted(RIG_LICENSES.glob("*")):
            target = lic_dir / f"{bz.TOOL.lower()}-rig-{src.name}"
            if not target.exists():
                target.write_bytes(src.read_bytes())
    print(f"[ OK ] {aid} {'updated in' if existing else 'added to'} {fa.ASSET_LOG.as_posix()}"
          + (f" (rig of {base_id})" if base_id else ""))


def add_parser(sub, common):
    p = sub.add_parser("rig", help="give a character a skeleton, skin weights and clips (UniRig or Tripo)")
    rs = p.add_subparsers(dest="rig_cmd", required=True)
    c = rs.add_parser("check", parents=[common], help="what is ready for the UniRig and Tripo routes")
    c.set_defaults(fn=cmd_rig_check)
    m = rs.add_parser("make", parents=[common], help="rig one model already in the game")
    m.add_argument("name", help="the model's name (its <models>/<name>.glb is the input)")
    m.add_argument("--with", dest="backend", choices=("unirig", "tripo"), default="unirig",
                   help="unirig: free, your GPU (default); tripo: paid credits, Mixamo bones, mocap-like clips")
    m.add_argument("--input", help="rig this .glb instead of <models>/<name>.glb")
    m.add_argument("--animate", default=CLIPS_DEFAULT,
                   help=f"UniRig: script-made clips to add, from idle,wave,walk, or none (default {CLIPS_DEFAULT})")
    m.add_argument("--clips", default="idle,walk",
                   help=f"Tripo: preset clips, up to 5 ({','.join(TRIPO_CLIPS)}) or none; 10 credits each "
                        "(default idle,walk)")
    m.add_argument("--max-credits", type=int, default=100, help="Tripo: refuse a run quoted above this (default 100)")
    m.add_argument("--names", choices=("mixamo", "keep"), default="mixamo",
                   help="bone names: mixamo (default; engines' humanoid setups and animation packs map them) or keep")
    m.add_argument("--out", help="models folder (default: the engine's, as for make)")
    m.add_argument("--project", default=".", help="the game's root folder (default: the current folder)")
    m.add_argument("--no-preview", action="store_true", help="skip the clip contact sheet")
    m.add_argument("--no-log", action="store_true", help="do not touch docs/ASSET_LOG.md (scratch runs)")
    m.add_argument("--overwrite", action="store_true", help="replace <name>_rigged.glb from an earlier run")
    m.add_argument("--wait", type=int, default=STEP_WAIT_S, help=f"seconds to wait for each step (default {STEP_WAIT_S})")
    m.set_defaults(fn=cmd_rig_make)

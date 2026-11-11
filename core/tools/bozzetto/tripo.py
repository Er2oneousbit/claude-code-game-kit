#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# tripo.py
# Purpose : Everything Bozzetto says to the Tripo3D API, in one place, for both of its paid routes: `make --with tripo`
#           (a model from a picture, several views or a sentence), `rig make --with tripo` (rig.py) and `reference
#           --with tripo` (reference.py: text-to-image, image-to-image, image-to-multiview pictures). The client,
#           the price quote, the --max-credits cap with the balance check, and the tasks.json journal that lets a
#           re-run reuse paid work live here; rig.py keeps only its own steps.
# Usage   : A module, not a command. bozzetto.py binds itself (bind) and calls run_make(); rig.py uses Client, Journal
#           and Budget; reference.py uses Client (image_task) and Budget with its own per-picture journal. The commands:
#             python tools/bozzetto/bozzetto.py make prop_crate --with tripo --image art_src/crate.png
#             python tools/bozzetto/bozzetto.py make npc_guard --with tripo --class npc --front f.png --back b.png
#             python tools/bozzetto/bozzetto.py make prop_lamp --with tripo --prompt "a brass ship's lantern"
# Needs   : Python 3.8+ (standard library), TRIPO_API_KEY with paid API credits (a Tripo Studio plan adds none).
# Notes   : API facts, read from https://developers.tripo3d.ai/en/docs on 2026-11-11 (the API itself not called since
#           the 2026-11-05 test, E153): base https://openapi.tripo3d.ai/v3, Bearer key; POST /files (multipart "file",
#           PNG or JPEG up to 20 MB) -> file_token; POST /generation/image-to-model {input, model}, /multiview-to-model
#           {inputs: [{"front": tok}, ...], front required, 2 views at least}, /text-to-model {prompt <= 1024 chars};
#           models P1-20260311 and P2-20260801; GET /tasks/{id} (poll every 1-2 s; credits_consumed, error_code,
#           error_message; banned and expired come back as failed); GET /account/balance {balance, frozen}. Credits are
#           frozen when a task is created and charged only when it succeeds (failed and cancelled tasks cost nothing).
#           There is no price or estimate endpoint, so the quote is MAKE_QUOTE below: conservative, and only the P2
#           image-to-model figure is measured (110 credits, E153; the public table says 30). Each task's actual
#           cost is read back from credits_consumed and checked against --max-credits before the next paid call.
#           Result links expire after about 5 minutes (E153, verify): the finished task is asked again for a fresh
#           link each run. The key is sent only to the API, never to the download host, and never written down.
#           Outputs bought with paid credits are the user's and not used for training (Tripo terms 5.2.2); outputs
#           from free credits stay Tripo's (5.2.1).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   Client:  call (JSON in, {code, data} out; 401/403 -> ToolError) | upload | create task -> journal it running ->
#            wait (poll; failed/cancelled -> JobError with Tripo's reason) | download (no key sent)
#   Journal: tasks.json in the work folder; reused only when every input fact matches (and not --no-reuse); a task
#            left running is asked how it ended before anything new is paid for
#   Budget:  actual spend so far + the next step <= --max-credits, and <= the balance; else stop before paying
#   run_make: pictures stripped of metadata and kept -> journal -> quote, balance, cap -> upload -> one task ->
#            actual cost -> the finished task asked again for a fresh link -> download -> raw.glb (extras stripped)
import json
import os
import time
import urllib.error
import urllib.request
import uuid

bz = None   # bozzetto.py binds itself here (bind): its errors, DEBUG flag, SLEEP and helpers

TRIPO_ENV = "TRIPO_API_KEY"
SECRET_PREFIX, CLIENT_ID_PREFIX = "tsk_", "tcli_"    # Tripo's secret API keys and its client IDs (refused as keys)
BASE = "https://openapi.tripo3d.ai/v3"       # the exam points this at its stand-in server
OPENER = urllib.request.urlopen              # the exam may replace it too
POLL_S = 2                                   # the docs ask for one query every 1 to 2 seconds
FAILED = ("failed", "cancelled", "banned", "expired")   # banned/expired: legacy names Tripo now reports as failed
JOURNAL = "tasks.json"
NO_STUDIO = "API credits are bought separately: a Tripo Studio plan adds none"
TERMS = ("outputs made with paid API credits are the user's and are not used for training (Tripo terms 5.2.2); "
         "outputs from free credits stay Tripo's (5.2.1); a Tripo Studio plan adds no API credits")
LICENSE = "Tripo3D terms (paid output, 5.2.2)"
CREDIT_MAKE = "3D model generated with the Tripo3D API (paid credits; outputs owned by the paying user, Tripo terms 5.2.2)."

# ---- make: the model route -------------------------------------------------------------------------------------
MAKE_MODELS = ("P2-20260801", "P1-20260311")  # the P series ("game assets"); P2 is the one tested (E153)
MAKE_MODEL = "P2-20260801"
# credits per task before any add-on. No endpoint quotes a price: P2 image-to-model is measured (110, E153), every
# other figure is set to that ceiling until a run measures it (verify). The actual cost is read after each task.
MAKE_QUOTE = {model: {"image": 110, "multiview": 110, "text": 110} for model in MAKE_MODELS}
QUALITY = {"normal": ("standard", 0), "high": ("detailed", 30)}   # --quality -> texture_quality, extra credits (verify)
FACE_LIMIT = {"P2-20260801": (48, 50000), "P1-20260311": (50, 20000)}   # triangle limits from the docs
ENDPOINT = {"image": "/generation/image-to-model", "multiview": "/generation/multiview-to-model",
            "text": "/generation/text-to-model"}
VIEWS = ("front", "left", "back", "right")
UPLOAD_MAX = 20 * 1024 * 1024                # /files: images up to 20 MB, PNG or JPEG
PROMPT_MAX = 1024
# Tripo writes models facing +X (its export_orientation default "+x", and the 2026-11-05 rig test); glTF's front is
# +Z. cleanup.py turns counter-clockwise seen from above, so -90 brings +X round to +Z (verify on a live run).
FACING = "+X"
FACING_TURN = -90.0
CHARACTER_HINT = ", full body, standing in an A-pose with the arms slightly away from the body"

# ---- reference pictures: reference.py's tripo route (#288) --------------------------------------------------------
# POST /generation/text-to-image {prompt, model, size, aspect_ratio (banana models), output_format},
# /generation/image-to-image {input: file_token | URL | task_id, prompt, ...} -> output.generated_image_url;
# /generation/image-to-multiview {input} -> output.generate_multiview_image {front,left,back,right}_view_url
# (developers.tripo3d.ai, read 2026-11-11)
IMAGE_ENDPOINT = {"text_to_image": "/generation/text-to-image", "image_to_image": "/generation/image-to-image",
                  "image_to_multiview": "/generation/image-to-multiview"}
# credits per task: upper bounds from the pricing summary (text to image 5, generate image 5 to 10, image to multiview
# 10; verify). No endpoint quotes a price: the actual cost is read from each finished task.
IMAGE_QUOTE = {"text_to_image": 10, "image_to_image": 10, "image_to_multiview": 10}
IMAGE_MODELS = {"banana2": "1K", "banana_pro": "1K", "banana": "1024x1024", "seedream_v5": "2K"}   # model: size
IMAGE_MODEL = "banana2"
IMAGE_TERMS = TERMS + "; its banana models are Google's and carry Google's invisible watermark (Tripo docs)"


def bind(module):
    global bz
    bz = module


def key():
    return os.environ.get(TRIPO_ENV, "")


def refusal_hint(body):
    """Tripo's own words on a refused key ("API key must start with 'tsk_' ..."), so the user sees the fix."""
    try:
        doc = json.loads(body)
    except ValueError:
        return ""
    if not isinstance(doc, dict):
        return ""
    words = " ".join(str(doc[k]) for k in ("message", "suggestion") if doc.get(k))
    return f". Tripo says: {words[:240]}" if words else ""


# ---- the client --------------------------------------------------------------------------------------------------
class Client:
    def __init__(self, api_key=None, base=None):
        self.key, self.base = api_key or key(), (base or BASE).rstrip("/")

    def call(self, method, path, body=None, raw=None, ctype=None):
        if self.key.startswith(CLIENT_ID_PREFIX):       # a common mix-up; Tripo refuses it, so say so before a call
            raise bz.ToolError(f"{TRIPO_ENV} holds a Tripo client ID ({CLIENT_ID_PREFIX}...), not the secret key: "
                               f"use the secret key, which starts with {SECRET_PREFIX} (Tripo's API keys page)")
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
                raise bz.ToolError(f"Tripo refused the key (HTTP {e.code}): check {TRIPO_ENV}{refusal_hint(msg)}")
            if e.code == 429:
                raise bz.JobError(f"Tripo {path}: too many requests or tasks at once (HTTP 429): wait and run again")
            raise bz.JobError(f"Tripo {path}: HTTP {e.code}: {msg}")
        except (urllib.error.URLError, OSError) as e:
            raise bz.ToolError(f"cannot reach Tripo ({self.base}): {e}")
        except ValueError:
            raise bz.JobError(f"Tripo {path}: the answer is not JSON")
        if doc.get("code", 0) != 0:
            raise bz.JobError(f"Tripo {path}: {doc.get('message') or doc}")
        return doc.get("data") or {}

    def balance(self):
        return float(self.call("GET", "/account/balance").get("balance", 0))

    def upload(self, data, filename, ctype):
        b = "----bozzetto" + uuid.uuid4().hex
        raw = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
               f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
        tok = self.call("POST", "/files", raw=raw, ctype=f"multipart/form-data; boundary={b}").get("file_token")
        if not tok:
            raise bz.JobError("Tripo's upload returned no file_token")
        return tok

    def task(self, path, body, what, wait, on_created=None):
        """Create a task, journal it (on_created) before anything else can fail (#210), wait for it."""
        tid = self.call("POST", path, body=body).get("task_id")
        if not tid:
            raise bz.JobError(f"Tripo {what}: no task id")
        if on_created:
            on_created(tid)
        return tid, self.wait_for(tid, what, wait)

    def wait_for(self, tid, what, wait):
        t0 = time.monotonic()
        while True:
            d = self.call("GET", f"/tasks/{tid}")
            st = d.get("status")
            if st == "success":
                print(f"[ OK ] Tripo {what}: task {tid}, {time.monotonic() - t0:.0f} s, "
                      f"{float(d.get('credits_consumed') or 0):g} credits", flush=True)
                return d
            if st in FAILED:
                why = d.get("error_message") or ""
                code = d.get("error_code")
                raise bz.JobError(f"Tripo {what}: {st} (task {tid}" + (f", error {code}" if code is not None else "")
                                  + (f": {why}" if why else "") + "); a failed task costs no credits")
            if time.monotonic() - t0 > wait:
                raise bz.JobError(f"Tripo {what} did not finish in {wait} s (task {tid}; a re-run picks it up from "
                                  f"{JOURNAL} without paying again)")
            bz.SLEEP(POLL_S)

    def image_task(self, kind, model, extra):
        """Create a reference-picture task (IMAGE_ENDPOINT kind) and return its id. The body: a square PNG at the
        model's size (Banana models take an aspect ratio, the others refuse one) plus `extra` (prompt, input)."""
        body = {"model": model, "size": IMAGE_MODELS[model], "output_format": "png"} if kind != "image_to_multiview" \
            else {}
        if kind != "image_to_multiview" and model.startswith("banana"):
            body["aspect_ratio"] = "1:1"
        body.update(extra)
        tid = self.call("POST", IMAGE_ENDPOINT[kind], body=body).get("task_id")
        if not tid:
            raise bz.JobError(f"Tripo {kind}: no task id")
        return tid

    def download(self, url, dst):
        """The result file. The link is Tripo's CDN: no key goes with it."""
        try:
            with OPENER(urllib.request.Request(url), timeout=300) as r:
                data = r.read()
        except (urllib.error.URLError, OSError) as e:
            raise bz.JobError(f"could not download Tripo's model ({e}); its links expire after about 5 minutes: run "
                              f"again, the paid task is kept in {JOURNAL} and a fresh link is fetched without paying")
        dst.write_bytes(data)
        return data


# ---- the journal and the cap -------------------------------------------------------------------------------------
class Journal:
    """tasks.json: every paid task, written as it is created and as it finishes (#210). Reused only when each input
    fact in `want` matches the file (and reuse is on); otherwise it starts empty."""

    def __init__(self, path, want, reuse=True):
        self.path = path
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
        self.data = old if (reuse and all(old.get(k) == v for k, v in want.items())) else dict(want, tasks={})
        self.tasks = self.data.setdefault("tasks", {})

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")

    def done(self, step):
        return (self.tasks.get(step) or {}).get("status") == "success"

    def running(self, step, tid):
        self.tasks[step] = {"id": tid, "status": "running"}
        self.save()

    def finished(self, step, tid, credits, **extra):
        self.tasks[step] = dict({"id": tid, "status": "success", "credits": credits}, **extra)
        self.save()

    def spent(self):
        return sum(float(v.get("credits") or 0) for v in self.tasks.values())

    def settle(self, client, steps, wait, extra=None):
        """A task journalled as running (the last run timed out or was stopped after paying): ask Tripo how it ended
        before paying for another one (#221). extra(step, result) adds facts to a finished entry."""
        for step in steps:
            entry = self.tasks.get(step) or {}
            if entry.get("status") != "running" or not entry.get("id"):
                continue
            st = client.call("GET", f"/tasks/{entry['id']}").get("status")
            if st in FAILED:
                print(f"[info] the last run's {step} task {entry['id']} ended {st}; a new one will be made")
                del self.tasks[step]
                self.save()
                continue
            try:
                d = client.wait_for(entry["id"], f"{step} (from the last run)", wait)
            except bz.JobError:
                # still running after --wait: never pay for a second one while the first may still finish
                raise bz.ToolError(f"the last run's {step} task {entry['id']} is still running at Tripo; run again "
                                   f"later (it is kept in {JOURNAL}), or pass --no-reuse to pay for a new one")
            more = extra(step, d) if extra else {}
            self.finished(step, entry["id"], float(d.get("credits_consumed") or 0), **more)

    def reused(self):
        return ", ".join(f"{k} task {v['id']}" for k, v in self.tasks.items() if v.get("status") == "success")


class Budget:
    """--max-credits counts actual charges; the balance is checked too. afford() refuses before a paid call."""

    def __init__(self, cap, balance, spent=0.0, flag="--max-credits", journal=JOURNAL):
        self.cap, self.balance, self.spent = cap, balance, spent
        self.flag, self.journal = flag, journal      # how the caller names its cap and journal (reference.py differs)

    def afford(self, more):
        if self.spent + more > self.cap:
            raise bz.ToolError(f"spending {more:g} more credits would make {self.spent + more:g} in all, over "
                               f"{self.flag} {self.cap:g}; finished tasks are kept in {self.journal} for a re-run")
        if more > self.balance:
            raise bz.ToolError(f"the Tripo balance ({self.balance:g} credits) is under the next step ({more:g}); "
                               f"{NO_STUDIO}")

    def charge(self, cost):
        self.spent += cost
        self.balance -= cost


# ---- make --with tripo -------------------------------------------------------------------------------------------
def make_kind(args):
    """'image', 'multiview' or 'text' from make's options."""
    if any(getattr(args, v, None) for v in VIEWS):
        return "multiview"
    return "text" if args.prompt else "image"


def quote(model, kind, quality):
    return MAKE_QUOTE[model][kind] + QUALITY[quality][1]


def face_limit(model, faces):
    lo, hi = FACE_LIMIT[model]
    return max(lo, min(hi, faces))


def prompt_text(args, cls):
    """The sentence Tripo gets: as written for props and with --raw-prompt; characters get the A-pose hint (a rig
    needs gaps between the arms and the body)."""
    text = args.prompt.strip()
    if cls in ("hero", "npc") and not args.raw_prompt:
        text = text.rstrip(".") + CHARACTER_HINT
    return text


def check_make(args, plan):
    """make --with tripo's own checks, before any credit (bozzetto's preflight calls this)."""
    if not key():
        raise bz.ToolError(f"--with tripo needs {TRIPO_ENV} (paid API credits; {NO_STUDIO})")
    if args.max_credits <= 0:
        raise bz.ToolError("--max-credits must be a positive number")
    if args.wait <= 0:
        raise bz.ToolError("--wait must be a positive number of seconds")
    if args.material != "texture":
        raise bz.ToolError("--with tripo makes textured models only (--material texture)")
    if args.prompt and len(prompt_text(args, plan.cls)) > PROMPT_MAX:
        raise bz.ToolError(f"--prompt is longer than Tripo takes ({PROMPT_MAX} characters)")
    for role, path in plan.pictures:
        if path.stat().st_size > UPLOAD_MAX:
            raise bz.ToolError(f"{path.name} is over Tripo's 20 MB upload limit")


def keep_pictures(plan):
    """Each picture, metadata removed (as the local route does), kept in the source folder and returned with its
    upload facts: [(role, kept path, bytes, content type, sha256)]. Tripo's upload takes PNG and JPEG only."""
    out = []
    for role, path in plan.pictures:
        try:
            data = bz.comfy(bz.cl.strip_picture, path.read_bytes())
        except bz.ToolError as exc:
            raise bz.ToolError(f"{path.name}: {exc}")
        if data.startswith(b"\x89PNG"):
            ext, ctype = ".png", "image/png"
        elif data.startswith(b"\xff\xd8"):
            ext, ctype = ".jpg", "image/jpeg"
        else:
            raise bz.ToolError(f"{path.name}: Tripo's upload takes PNG or JPEG pictures; save it as one of those")
        name = ("reference" if role == "image" else f"view_{role}") + ext
        dest = plan.src / name
        bz.write_new(dest, data, True)
        out.append((role, dest, data, ctype, bz.sha256_bytes(data)))
    if out:
        print(f"[ OK ] reference: " + ", ".join(bz.rel(plan.root, p[1]) for p in out) + " (metadata removed)")
    return out


def run_make(args, plan):
    """One Tripo model task with the journal, quote and cap. Returns (raw .glb path, job facts, reference facts)."""
    client = Client()
    work = plan.src / "tripo"
    kind, model = make_kind(args), args.tripo_model
    pictures = keep_pictures(plan)
    tq = QUALITY[args.quality][0]
    settings = {"model": model, "face_limit": face_limit(model, plan.faces), "texture": True, "pbr": True,
                "texture_quality": tq}
    if args.seed is not None:
        settings.update(model_seed=args.seed, texture_seed=args.seed)
        if kind == "text":
            settings["image_seed"] = args.seed
    text = prompt_text(args, plan.cls) if kind == "text" else None
    want = {"kind": kind, "inputs_sha256": {role: sha for role, _, _, _, sha in pictures}, "prompt": text,
            "settings": settings}
    j = Journal(work / JOURNAL, want, reuse=not args.no_reuse)
    j.settle(client, ["model"], args.wait)
    price = 0 if j.done("model") else quote(model, kind, args.quality)
    budget = Budget(args.max_credits, client.balance(), j.spent())
    if j.done("model"):
        print(f"[ OK ] reusing paid Tripo work from {JOURNAL}: {j.reused()} (no new credits)")
    print(f"[info] Tripo quote: {price} credits still to spend ({model} {kind}-to-model, texture {tq}; the quote is "
          f"the kit's table, Tripo has no price endpoint); balance {budget.balance:g}; limit --max-credits "
          f"{args.max_credits}")
    budget.afford(price)
    if not j.done("model"):
        body = dict(settings)
        if kind == "image":
            _, p, data, ctype, _ = pictures[0]
            body["input"] = client.upload(data, p.name, ctype)
        elif kind == "multiview":
            body["inputs"] = [{role: client.upload(data, p.name, ctype)} for role, p, data, ctype, _ in pictures]
        else:
            body["prompt"] = text

        def created(tid):
            j.running("model", tid)
            print(f"[info] Tripo {kind}-to-model task {tid} (journal: {bz.rel(plan.root, j.path)})", flush=True)
        tid, d = client.task(ENDPOINT[kind], body, f"{kind}-to-model ({model})", args.wait, created)
        cost = float(d.get("credits_consumed") or 0)
        j.finished("model", tid, cost)
        budget.charge(cost)
        if cost > price:
            print(f"[warn] Tripo charged {cost:g} credits, more than the quote ({price}): raise MAKE_QUOTE in "
                  f"tools/bozzetto/tripo.py for {model} {kind}")
    tid = j.tasks["model"]["id"]
    # the finished task is asked again for its link: links expire after about 5 minutes, a reused task needs a new one
    fin = client.wait_for(tid, "model result", args.wait)
    url = (fin.get("output") or {}).get("model_url")
    if not url:
        raise bz.JobError(f"Tripo returned no model link for task {tid}; it is kept in {JOURNAL}, a re-run fetches "
                          "it again without paying")
    work.mkdir(parents=True, exist_ok=True)
    got = work / "tripo.glb"
    if got.exists():
        got.unlink()
    data = client.download(url, got)
    try:
        data = bz.cl.strip_glb(data)
    except bz.cl.ToolError as exc:
        raise bz.JobError(f"Tripo's file for task {tid} is not a usable .glb ({exc}); it is kept as "
                          f"{bz.rel(plan.root, got)}")
    raw = plan.src / "raw.glb"
    bz.write_new(raw, data, True)
    doc, _ = bz.cl.read_glb(data)
    tris = bz.glb_triangles(doc)
    print(f"[ OK ] raw mesh: {bz.rel(plan.root, raw)} ({tris:,} triangles from Tripo)")
    job = {"service": "Tripo3D API", "endpoint": ENDPOINT[kind], "model": model, "task_id": tid,
           "tasks": {k: v["id"] for k, v in j.tasks.items()}, "credits": j.spent(), "quote": quote(model, kind, args.quality),
           "settings": settings, "facing": FACING, "tris_raw": tris, "sha256": bz.sha256_bytes(data), "terms": TERMS}
    if kind == "text":
        ref = {"kind": "prompt", "prompt": args.prompt, "full_prompt": text}
    elif kind == "image":
        ref = {"kind": "image", "file": bz.rel(plan.root, pictures[0][1]), "sha256": pictures[0][4]}
    else:
        ref = {"kind": "views", "views": {role: {"file": bz.rel(plan.root, p), "sha256": sha}
                                          for role, p, _, _, sha in pictures}}
    return raw, job, ref

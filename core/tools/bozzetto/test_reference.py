#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_reference.py
# Purpose : The exam for `bozzetto.py reference` (reference.py, refsheet.py), offline. One stand-in server on
#           127.0.0.1 plays three services: a ComfyUI (the local route: /object_info, uploads, jobs, /view), Google's
#           Gemini generateContent (the nanobanana route) and Tripo's v3 image tasks plus a CDN (the tripo route).
#           Cases: the front door and every check made before any call; each route from a prompt and from a
#           concept; the A-pose prompts and the Multiple-Angles prompts reaching the jobs; metadata stripped from
#           every picture sent out; the conversation (thought signatures and pictures) going back to Gemini; cost
#           from the reply's usage; the quote over the cap, a cap stop mid-run, a failed call, a blocked picture, a
#           refused key, a missing key; the journal reused by a rerun (no second payment), a Tripo task the last
#           run left running; the sheet, the look check, the record, the asset log row and its terms; no key and no
#           local path in any written file; the PNG reader on every filter and colour type.
# Usage   : python tools/bozzetto/test_reference.py          (standard library, any Python 3.8+, about 5 s)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import base64
import contextlib
import http.server
import io
import json
import os
import struct
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bozzetto as bz  # noqa: E402
import reference as ref  # noqa: E402
import tripo as tp  # noqa: E402  (the shared Tripo client the tripo route uses)
import refsheet  # noqa: E402
cl = bz.cl
ref.bind(bz)   # as bozzetto.py's parser does, for the cases that call reference.py's helpers directly
tp.bind(bz)

KEY_G = "AIzaTEST-gemini-key-never-written-7f3a"
KEY_T = "tsk_TEST-tripo-key-never-written-91c2"
EMBEDDED = "X:/someone/private/concept_source.psd"     # a local path a picture carries in its text chunk
LOG = """# Asset Log

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | | | | | | | no | no | 2026-01-01 | |

## Rules
"""


# ---- fixtures ---------------------------------------------------------------------------------------------------
def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def figure_png(colour=(60, 40, 120), w=48, h=48, top=6, bottom=42, text=True):
    """A light grey picture with a dark upright block (the 'figure'); a tEXt chunk with a local path."""
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            inside = top <= y < bottom and w // 3 <= x < 2 * w // 3
            row += bytes(colour if inside else (208, 208, 208))
        rows.append(b"\x00" + bytes(row))
    return (refsheet.PNG_MAGIC + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + (chunk(b"tEXt", b"prompt\x00" + EMBEDDED.encode()) if text else b"")
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def colour_of(name):
    """A colour per output name, so the exam can tell which picture landed where."""
    h = zlib.crc32(name.encode()) & 0xFFFFFF
    return (h & 0x7F, (h >> 8) & 0x7F, (h >> 16) & 0x7F)


def filtered_png(pixels, w, h, ctype, filt, plte=None, trns=None):
    """A PNG of raw pixel rows (bytes per row) written with one filter type, to exam the reader's unfiltering."""
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    stride = w * ch
    out, prev = b"", bytes(stride)
    for y in range(h):
        line = pixels[y * stride:(y + 1) * stride]
        enc = bytearray()
        for i in range(stride):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if filt == 0:
                pred = 0
            elif filt == 1:
                pred = a
            elif filt == 2:
                pred = b
            elif filt == 3:
                pred = (a + b) >> 1
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
            enc.append((line[i] - pred) & 255)
        out += bytes([filt]) + bytes(enc)
        prev = line
    return (refsheet.PNG_MAGIC + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + (chunk(b"PLTE", plte) if plte else b"") + (chunk(b"tRNS", trns) if trns else b"")
            + chunk(b"IDAT", zlib.compress(out)) + chunk(b"IEND", b""))


# ---- the stand-in server ---------------------------------------------------------------------------------------
class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.requests = []               # (method, path, headers, body)
        self.prompts, self.uploads, self.frees = [], [], 0
        self.missing, self.drop_nodes, self.comfy_fail = set(), set(), None
        self.gemini = []                 # per call: "ok" (default), "500", "safety", "badkey", "nousage"
        self.gemini_thoughts = 100       # thinking tokens each reply reports
        self.balance = 500.0
        self.tasks = {}                  # id -> {"type", "body"}
        self.next_task = 0               # task ids never repeat, even after a case clears `tasks`
        self.task_status = {}            # id -> status the next /tasks query answers
        self.fail_type = None            # a Tripo task type that fails
        self.credits = {"text_to_image": 5.0, "image_to_image": 7.0, "image_to_multiview": 10.0}
        self.multiview_views = ("front", "left", "back", "right")

    def calls(self, prefix):
        return [r for r in self.requests if r[1].startswith(prefix)]


STATE = State()
WF_EDIT = json.loads(ref.WORKFLOW_EDIT.read_text(encoding="utf-8"))
WF_REF = json.loads(bz.WORKFLOW_REF.read_text(encoding="utf-8"))


def object_info():
    info = {n["class_type"]: {"input": {"required": {}}} for wf in (WF_EDIT, WF_REF) for n in wf.values()}
    models = ref.qwen_models() + bz.klein_models()
    for m in models:
        names = [x["file"] for x in models if x["loader"] == m["loader"] and x["file"] not in STATE.missing]
        info.setdefault(m["loader"], {"input": {"required": {}}})["input"]["required"][m["input"]] = [names]
    for n in STATE.drop_nodes:
        info.pop(n, None)
    return info


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def base(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    # -- GET
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        STATE.requests.append(("GET", url.path, {k.lower(): v for k, v in self.headers.items()}, b""))
        if url.path.startswith("/v3/"):
            return self.tripo_get(url.path[3:])
        if url.path.startswith("/cdn/"):
            return self.send(200, figure_png(colour_of(url.path), text=True), "image/png")
        if url.path == "/system_stats":
            return self.send(200, {"system": {"comfyui_version": "0.43.0", "python_version": "3.12.12"},
                                   "devices": [{"name": "cuda:0 Test GPU", "vram_total": 16 * 1024 ** 3,
                                                "vram_free": 15 * 1024 ** 3}]})
        if url.path == "/object_info":
            return self.send(200, object_info())
        if url.path.startswith("/history/"):
            pid = url.path.rsplit("/", 1)[-1]
            graph = STATE.prompts[int(pid.split("-")[1]) - 1]
            if STATE.comfy_fail:
                return self.send(200, {pid: {"outputs": {}, "status": {"status_str": "error", "completed": False,
                                       "messages": [["execution_error", {"node_id": "15", "node_type": "KSampler",
                                                                         "exception_message": STATE.comfy_fail}]]}}})
            outs = {nid: {"images": [{"filename": f"{pid}_00001_.png", "subfolder": "bozzetto", "type": "output"}]}
                    for nid, n in graph.items() if n["class_type"] == "SaveImage"}
            return self.send(200, {pid: {"outputs": outs, "status": {"status_str": "success", "completed": True,
                                                                     "messages": []}}})
        if url.path == "/queue":
            return self.send(200, {"queue_running": [], "queue_pending": []})
        if url.path == "/view":
            name = urllib.parse.parse_qs(url.query)["filename"][0]
            return self.send(200, figure_png(colour_of(name)), "image/png")
        self.send(404, {"error": "no such path in the exam"})

    def tripo_auth(self):
        if self.headers.get("authorization") != f"Bearer {KEY_T}":
            self.send(401, {"code": 1002, "message": "bad key"})
            return False
        return True

    def tripo_get(self, path):
        if not self.tripo_auth():
            return
        if path == "/account/balance":
            return self.send(200, {"code": 0, "data": {"balance": STATE.balance, "frozen": 0}})
        if path.startswith("/tasks/"):
            tid = path.rsplit("/", 1)[-1]
            t = STATE.tasks.get(tid)
            if not t:
                return self.send(404, {"code": 2001, "message": "no such task"})
            status = STATE.task_status.get(tid, "success")
            out = {}
            if status == "success":
                if t["type"] == "image_to_multiview":
                    out = {"generate_multiview_image": {f"{v}_view_url": f"{self.base()}/cdn/{tid}_{v}.png"
                                                        for v in STATE.multiview_views}}
                else:
                    out = {"generated_image_url": f"{self.base()}/cdn/{tid}.png"}
            return self.send(200, {"code": 0, "data": {"task_id": tid, "type": t["type"], "status": status,
                                                       "progress": 100, "output": out,
                                                       "credits_consumed": STATE.credits[t["type"]]
                                                       if status == "success" else 0}})
        self.send(404, {"code": 404, "message": "no such path"})

    # -- POST
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        STATE.requests.append(("POST", self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        if self.path.startswith("/v1beta/models/"):
            return self.gemini(body)
        if self.path.startswith("/v3/"):
            return self.tripo_post(self.path[3:], body)
        if self.path == "/prompt":
            STATE.prompts.append(json.loads(body.decode("utf-8"))["prompt"])
            return self.send(200, {"prompt_id": f"p-{len(STATE.prompts)}", "number": 1, "node_errors": {}})
        if self.path == "/upload/image":
            STATE.uploads.append(body)
            return self.send(200, {"name": f"upload_{len(STATE.uploads)}.png", "subfolder": "", "type": "input"})
        if self.path == "/free":
            STATE.frees += 1
            return self.send(200, {})
        self.send(404, {"error": "no such path"})

    def gemini(self, body):
        n = len(STATE.calls("/v1beta/"))
        mode = STATE.gemini[n - 1] if n - 1 < len(STATE.gemini) else "ok"
        if self.headers.get("x-goog-api-key") != KEY_G or mode == "badkey":
            return self.send(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                             "status": "INVALID_ARGUMENT"}})
        if mode == "500":
            return self.send(500, {"error": {"code": 500, "message": "Internal error encountered."}})
        usage = {"promptTokenCount": 1000 * n, "candidatesTokenCount": 1130, "thoughtsTokenCount": STATE.gemini_thoughts,
                 "candidatesTokensDetails": [{"modality": "IMAGE", "tokenCount": 1120},
                                             {"modality": "TEXT", "tokenCount": 10}]}
        if mode == "safety":
            return self.send(200, {"candidates": [{"content": {"role": "model", "parts": []},
                                                   "finishReason": "IMAGE_SAFETY"}], "usageMetadata": usage})
        img = base64.b64encode(figure_png(colour_of(f"gemini-{n}"))).decode()
        reply = {"candidates": [{"content": {"role": "model", "parts": [
            {"text": "**Planning the pose**", "thought": True, "thoughtSignature": f"thought-sig-{n}"},
            {"inlineData": {"mimeType": "image/png", "data": img}, "thoughtSignature": f"sig-{n}"}]},
            "finishReason": "STOP"}]}
        if mode != "nousage":
            reply["usageMetadata"] = usage
        return self.send(200, reply)

    def tripo_post(self, path, body):
        if not self.tripo_auth():
            return
        if path == "/files":
            STATE.uploads.append(body)
            return self.send(200, {"code": 0, "data": {"file_token": f"file_{len(STATE.uploads)}"}})
        kinds = {"/generation/text-to-image": "text_to_image", "/generation/image-to-image": "image_to_image",
                 "/generation/image-to-multiview": "image_to_multiview"}
        if path in kinds:
            STATE.next_task += 1
            tid = f"task-{STATE.next_task}"
            STATE.tasks[tid] = {"type": kinds[path], "body": json.loads(body.decode("utf-8"))}
            if kinds[path] == STATE.fail_type:
                STATE.task_status[tid] = "failed"
            return self.send(200, {"code": 0, "data": {"task_id": tid}})
        self.send(404, {"code": 404, "message": "no such path"})


# ---- base -------------------------------------------------------------------------------------------------------
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        STATE.reset()
        self.tmp = tempfile.TemporaryDirectory(prefix="bz_ref_exam_")
        self.root = Path(self.tmp.name).resolve()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        (self.root / "art_src").mkdir()
        (self.root / "art_src" / "concept.png").write_bytes(figure_png((150, 30, 30), w=40, h=56))
        self.saved = (cl.SLEEP, bz.SLEEP, ref.GEMINI_BASE, tp.BASE, ref.OPENER, tp.OPENER, os.getcwd(),
                      {k: os.environ.get(k) for k in (ref.GEMINI_ENV, ref.TRIPO_ENV)})
        cl.SLEEP = bz.SLEEP = lambda s: None
        ref.GEMINI_BASE, tp.BASE = self.url + "/v1beta", self.url + "/v3"
        no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({})).open   # never a system proxy
        ref.OPENER = tp.OPENER = no_proxy
        os.environ[ref.GEMINI_ENV], os.environ[ref.TRIPO_ENV] = KEY_G, KEY_T
        os.chdir(self.root)

    def tearDown(self):
        cl.SLEEP, bz.SLEEP, ref.GEMINI_BASE, tp.BASE, ref.OPENER, tp.OPENER, cwd, env = self.saved
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        os.chdir(cwd)
        self.tmp.cleanup()

    def run_tool(self, *argv):
        args = ["reference"] + list(argv) + ["--url", self.url]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = bz.main(args)
        return rc, out.getvalue() + err.getvalue()

    @property
    def dir(self):
        return self.root / "assets_src" / "bozzetto" / "chr_hero" / "reference"

    def record(self):
        return json.loads((self.dir / ref.RECORD).read_text(encoding="utf-8"))

    def journal(self):
        return json.loads((self.dir / ref.JOURNAL).read_text(encoding="utf-8"))

    def log_rows(self):
        return [l for l in (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8").splitlines()
                if l.startswith("| A-0001 |") or l.startswith("| A-0002 |")]

    def clean_files(self):
        """No key, no local path, no picture text chunk in anything written under the project (the exam's own
        concept excepted)."""
        needles = [KEY_G.encode(), KEY_T.encode(), str(self.root).encode(), self.root.as_posix().encode(),
                   str(Path.home()).encode(), Path.home().as_posix().encode(), EMBEDDED.encode()]
        for p in self.root.rglob("*"):
            if p.is_file() and p.parts[len(self.root.parts)] != "art_src":
                data = p.read_bytes()
                for n in needles:
                    self.assertNotIn(n, data, f"{p.relative_to(self.root)} holds {n[:20]!r}")

    def sent_out(self):
        """Every picture the services received holds no local path."""
        for method, path, _, body in STATE.requests:
            self.assertNotIn(EMBEDDED.encode(), body, f"{path} received a picture with its metadata")
            if path.startswith("/v1beta/"):
                self.assertNotIn(EMBEDDED, base64.b64decode(json.loads(body)["contents"][0]["parts"][0]
                                                            .get("inline_data", {}).get("data", "")).decode("latin-1"))


# ---- front door and plan ---------------------------------------------------------------------------------------
class FrontDoor(Base):
    def test_help_and_list(self):
        rc, out = self.run_tool("-h")
        self.assertEqual(rc, 0)
        for word in ("--from", "--prompt", "--with", "nanobanana", "tripo", "--views", "--max-cost", "--quote-only"):
            self.assertIn(word, out)
        out_list = io.StringIO()
        with contextlib.redirect_stdout(out_list):
            self.assertEqual(bz.main(["list"]), 0)
        self.assertIn("reference", out_list.getvalue())

    def test_usage_errors_exit_2_before_any_call(self):
        for argv, words in [
            (["chr_hero"], "exactly one of"),
            (["Chr Hero", "--prompt", "x"], "lowercase"),
            (["chr_hero", "--prompt", "x", "--views", "front,top"], "no view 'top'"),
            (["chr_hero", "--prompt", "x", "--model", "anything"], "--model is for the paid routes"),
            (["chr_hero", "--prompt", "x", "--with", "nanobanana", "--model", "gemini-9-image"], "no price on record"),
            (["chr_hero", "--prompt", "x", "--with", "tripo", "--model", "dalle"], "Tripo image models"),
            (["chr_hero", "--prompt", "x", "--with", "tripo", "--max-cost", "0"], "--max-cost must be"),
            (["chr_hero", "--from", "art_src/nope.png"], "not found"),
            (["chr_hero", "--prompt", "  "], "--prompt is empty"),
            (["chr_hero", "--prompt", "x", "--wait", "0"], "--wait"),
        ]:
            STATE.reset()
            rc, out = self.run_tool(*argv)
            self.assertEqual(rc, 2, f"{argv}: {out}")
            self.assertIn(words, out, argv)
            self.assertEqual(STATE.requests, [], argv)
        payload = b"\x2f" + bytes(9)                       # a VP8L chunk: the exam only needs the container
        body = b"WEBP" + b"VP8L" + struct.pack("<I", len(payload)) + payload
        (self.root / "art_src" / "c.webp").write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
        rc, out = self.run_tool("chr_hero", "--from", "art_src/c.webp", "--with", "tripo")
        self.assertEqual(rc, 2)
        self.assertIn("save the concept as PNG", out)

    def test_edit_workflow_loads_exactly_dotworks_rotation_files(self):
        loads = {v for n in WF_EDIT.values() for v in n["inputs"].values()
                 if isinstance(v, str) and v.endswith((".safetensors", ".gguf"))}
        self.assertEqual(loads, {m["file"] for m in ref.qwen_models()})
        self.assertEqual(bz.non_commercial_in(WF_EDIT), [])
        for title in ref.EDIT_NODES.values():
            bz.cl.find_node(WF_EDIT, title)          # every title the tool sets is in the workflow, once

    def test_paste_template_in_briefs_matches_the_tool(self):
        briefs = HERE.parents[1] / "docs" / "BRIEFS.md"     # core/docs in the kit, docs/ in a game
        if not briefs.is_file():
            self.skipTest("no docs/BRIEFS.md beside tools/")
        text = " ".join(briefs.read_text(encoding="utf-8").split())
        self.assertIn(ref.REPOSE, text)
        self.assertIn(ref.TURN.format(how=ref.TURN_HOW["left"]), text)

    def test_one_tripo_client_in_bozzetto(self):
        """The tripo route talks to Tripo only through tripo.py (shared with make and rig): no URL, upload or
        endpoint of its own."""
        src = (HERE / "reference.py").read_text(encoding="utf-8")
        for own in ("openapi.tripo3d.ai", '"/files"', "/generation/", "Bearer"):
            self.assertNotIn(own, src)
        self.assertIsInstance(ref.Tripo(None, None).client, tp.Client)

    def test_missing_key_exits_2_and_quote_only_needs_none(self):
        for route, env in (("nanobanana", ref.GEMINI_ENV), ("tripo", ref.TRIPO_ENV)):
            os.environ.pop(env)
            rc, out = self.run_tool("chr_hero", "--prompt", "a knight", "--with", route, "--seed", "1")
            self.assertEqual(rc, 2, out)
            self.assertIn(env, out)
            self.assertEqual(STATE.requests, [])
            rc, out = self.run_tool("chr_hero", "--prompt", "a knight", "--with", route, "--seed", "1", "--quote-only")
            self.assertEqual(rc, 0, out)
            self.assertIn("[quote]", out)
            self.assertIn("nothing was made or spent", out)
            self.assertEqual(STATE.requests, [])
            self.assertFalse(self.dir.exists())

    def test_files_in_the_way_and_the_asset_log(self):
        self.dir.mkdir(parents=True)
        (self.dir / "front.png").write_bytes(b"old")
        rc, out = self.run_tool("chr_hero", "--prompt", "a knight", "--seed", "1")
        self.assertEqual(rc, 2)
        self.assertIn("--overwrite", out)
        self.assertEqual(STATE.requests, [])
        (self.dir / "front.png").unlink()
        (self.root / "docs" / "ASSET_LOG.md").unlink()
        rc, out = self.run_tool("chr_hero", "--prompt", "a knight", "--seed", "1")
        self.assertEqual(rc, 2)
        self.assertIn("--no-log", out)


# ---- local route --------------------------------------------------------------------------------------------------
class LocalRoute(Base):
    def test_prompt_end_to_end(self):
        rc, out = self.run_tool("chr_hero", "--prompt", "a lanky lighthouse keeper in a yellow coat.", "--seed", "40")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(STATE.prompts), 4)
        klein = STATE.prompts[0]
        text = klein[bz.cl.find_node(klein, "Prompt")]["inputs"]["text"]
        self.assertTrue(text.startswith("a lanky lighthouse keeper in a yellow coat. Full-body"))
        for words in ("A-pose", "35 degrees", "hands open", "legs a little apart", "orthographic",
                      "flat even lighting", "plain light grey background", "nothing else in frame", "hangs straight down"):
            self.assertIn(words, text)
        self.assertEqual(klein[bz.cl.find_node(klein, "SEED")]["inputs"]["noise_seed"], 40)
        self.assertEqual(STATE.frees, 1, "klein must be unloaded before Qwen-Image-Edit")
        for i, (view, job) in enumerate(zip(("left", "back", "right"), STATE.prompts[1:]), 1):
            self.assertEqual(job[bz.cl.find_node(job, "Edit prompt")]["inputs"]["prompt"],
                             f"<sks> {ref.AZIMUTH[view]} eye-level shot medium shot")
            self.assertEqual(job[bz.cl.find_node(job, "Angle LoRA")]["inputs"]["strength_model"], 0.9)
            self.assertEqual(job[bz.cl.find_node(job, "SEED")]["inputs"]["seed"], 40 + i)
        self.assertEqual(len(STATE.uploads), 1, "the front is uploaded once for every turn")
        for v in ref.VIEWS:
            self.assertTrue((self.dir / f"{v}.png").is_file(), v)
        # each view is the job's own picture: p-1 front, p-2 left, ...
        for i, v in enumerate(ref.VIEWS, 1):
            img = refsheet.decode((self.dir / f"{v}.png").read_bytes())
            self.assertEqual(img.px(24, 24), colour_of(f"p-{i}_00001_.png"), v)
        sheet = refsheet.decode((self.dir / "sheet.png").read_bytes())
        self.assertEqual(sheet.h, refsheet.CELL_H + 2 * refsheet.GAP)
        self.assertGreater(sheet.w, 4 * refsheet.CELL_H)
        rec = self.record()
        self.assertEqual(rec["route"], "local")
        self.assertEqual(rec["source"], {"kind": "prompt", "prompt": "a lanky lighthouse keeper in a yellow coat"})
        self.assertEqual(rec["views"]["front"]["model"], "FLUX.2 klein 4B")
        self.assertIn("you", rec["terms"]["owner"])
        self.assertEqual(rec["look"]["warnings"], [])
        self.assertIn("--swap-sides", rec["look"]["by_eye"])
        self.assertIn("[look] by eye: left.png should show", out)
        self.assertTrue(rec["models"] and all(m["license"].lower() == "apache-2.0" for m in rec["models"]))
        row = self.log_rows()[0]
        self.assertIn("| A-0001 | art |", row)
        self.assertIn("`assets_src/bozzetto/chr_hero/reference/front.png`", row)
        self.assertIn("Apache-2.0", row)
        self.assertIn("generated locally", row)
        self.assertTrue((self.root / "docs" / "licenses" / "A-0001.txt").is_file())
        self.assertIn("make chr_hero --image assets_src/bozzetto/chr_hero/reference/front.png", out)
        self.assertIn("multiview make", out)
        self.assertIn("make chr_hero --with tripo --class npc --front assets_src/bozzetto/chr_hero/reference/front.png",
                      out)
        self.clean_files()

    def test_concept_is_reposed_then_turned(self):
        rc, out = self.run_tool("chr_hero", "--from", "art_src/concept.png", "--seed", "3", "--views", "back")
        self.assertEqual(rc, 0, out)
        self.assertIn("front is always made", out)
        self.assertEqual(len(STATE.prompts), 2)
        self.assertFalse(any(n["class_type"] == "UNETLoader" for p in STATE.prompts for n in p.values()), "no klein")
        repose = STATE.prompts[0]
        self.assertEqual(repose[bz.cl.find_node(repose, "Edit prompt")]["inputs"]["prompt"], ref.REPOSE)
        self.assertEqual(repose[bz.cl.find_node(repose, "Angle LoRA")]["inputs"]["strength_model"], 0.0)
        self.assertIn("Keep every design detail identical", ref.REPOSE)
        self.assertEqual(STATE.frees, 0)
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.png")), ["back.png", "concept.png", "front.png",
                                                                          "sheet.png"])
        self.assertNotIn(EMBEDDED.encode(), STATE.uploads[0], "the concept went to ComfyUI with its metadata")
        self.assertEqual(self.record()["source"]["kind"], "concept")
        self.clean_files()

    def test_missing_models_or_nodes_stop_before_any_job(self):
        STATE.missing = {"qwen-image-edit-2511-multiple-angles-lora.safetensors"}
        rc, out = self.run_tool("chr_hero", "--prompt", "a knight", "--seed", "1")
        self.assertEqual(rc, 2)
        self.assertIn("multiple-angles-lora", out)
        self.assertEqual(STATE.prompts, [])
        STATE.reset()
        STATE.drop_nodes = {"UnetLoaderGGUF"}
        rc, out = self.run_tool("chr_hero", "--prompt", "a knight", "--seed", "1")
        self.assertEqual(rc, 2)
        self.assertIn("ComfyUI-GGUF", out)
        self.assertEqual(STATE.prompts, [])

    def test_failed_job_exit_1_and_nothing_logged(self):
        STATE.comfy_fail = "CUDA out of memory"
        rc, out = self.run_tool("chr_hero", "--prompt", "a knight", "--seed", "1")
        self.assertEqual(rc, 1, out)
        self.assertIn("out of memory", out)
        self.assertEqual(len(self.log_rows()), 1)
        self.assertNotIn("art", self.log_rows()[0])

    def test_swap_sides_keeps_sheet_record_and_log_in_step(self):
        # #291 live run: left and right came back swapped (the second run in two); "swap the two files" by hand
        # left the sheet, the record's hashes and the asset log's evidence file describing the wrong pictures
        self.assertEqual(self.run_tool("chr_hero", "--prompt", "a knight", "--seed", "5")[0], 0)
        left, right = (self.dir / "left.png").read_bytes(), (self.dir / "right.png").read_bytes()
        before = self.record()
        sheet_before = (self.dir / "sheet.png").read_bytes()
        STATE.reset()
        rc, out = self.run_tool("chr_hero", "--swap-sides")
        self.assertEqual(rc, 0, out)
        self.assertEqual(STATE.requests, [], "no GPU job and no service call")
        self.assertEqual((self.dir / "left.png").read_bytes(), right)
        self.assertEqual((self.dir / "right.png").read_bytes(), left)
        self.assertNotEqual((self.dir / "sheet.png").read_bytes(), sheet_before)
        sheet = refsheet.decode((self.dir / "sheet.png").read_bytes())
        cell = refsheet.CELL_H + refsheet.GAP           # the cells are square here: the views are square
        self.assertEqual(sheet.px(refsheet.GAP + cell + 12, refsheet.GAP + 12),
                         refsheet.decode(right).px(2, 2), "the sheet's second cell is the new left view")
        rec = self.record()
        self.assertTrue(rec["sides_swapped"])
        for view, data in (("left", right), ("right", left)):
            self.assertEqual(rec["views"][view]["file"], f"assets_src/bozzetto/chr_hero/reference/{view}.png")
            self.assertEqual(rec["views"][view]["sha256"], ref.sha(data), view)
        # each picture keeps the prompt that made it, under its new name
        self.assertEqual(rec["views"]["left"]["prompt"], before["views"]["right"]["prompt"])
        self.assertEqual(rec["views"]["right"]["prompt"], before["views"]["left"]["prompt"])
        self.assertEqual(list(rec["views"]), list(ref.VIEWS))
        evidence = (self.root / "docs" / "licenses" / "A-0001.txt").read_text(encoding="utf-8")
        self.assertIn(f"left.png  SHA-256 {ref.sha(right)}", evidence)
        self.assertIn(f"right.png  SHA-256 {ref.sha(left)}", evidence)
        self.assertEqual(len([l for l in self.log_rows() if "chr_hero/reference" in l]), 1, "the same row, updated")
        # a second swap puts everything back
        self.assertEqual(self.run_tool("chr_hero", "--swap-sides")[0], 0)
        self.assertEqual((self.dir / "left.png").read_bytes(), left)
        self.assertFalse(self.record()["sides_swapped"])
        rc, out = self.run_tool("chr_hero", "--swap-sides", "--prompt", "x")
        self.assertEqual(rc, 2)
        self.assertIn("takes no --prompt", out)
        rc, out = self.run_tool("chr_nobody", "--swap-sides")
        self.assertEqual(rc, 2)
        self.assertIn("make the views first", out)
        self.clean_files()

    def test_rerun_needs_overwrite_and_updates_the_same_row(self):
        self.assertEqual(self.run_tool("chr_hero", "--prompt", "a knight", "--seed", "1", "--views", "front")[0], 0)
        rc, out = self.run_tool("chr_hero", "--prompt", "a knight", "--seed", "2", "--views", "front")
        self.assertEqual(rc, 2)
        rc, out = self.run_tool("chr_hero", "--prompt", "a knight", "--seed", "2", "--views", "front", "--overwrite")
        self.assertEqual(rc, 0, out)
        self.assertIn("updated in", out)
        rows = [l for l in (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8").splitlines()
                if "chr_hero/reference/front.png" in l]
        self.assertEqual(len(rows), 1)
        self.assertIn("seed 2", rows[0])


# ---- nanobanana route ------------------------------------------------------------------------------------------
class GeminiRoute(Base):
    def gemini_bodies(self):
        return [json.loads(r[3]) for r in STATE.calls("/v1beta/")]

    def test_prompt_conversation_cost_and_terms(self):
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "nanobanana", "--seed", "5")
        self.assertEqual(rc, 0, out)
        calls = STATE.calls("/v1beta/")
        self.assertEqual(len(calls), 4)
        for _, path, headers, _ in calls:
            self.assertEqual(path, "/v1beta/models/gemini-nano-banana-2.1:generateContent")
            self.assertNotIn(KEY_G, path)
            self.assertEqual(headers.get("x-goog-api-key"), KEY_G)
        bodies = self.gemini_bodies()
        self.assertEqual(bodies[0]["generationConfig"]["responseModalities"], ["IMAGE"])
        self.assertEqual(bodies[0]["generationConfig"]["imageConfig"], {"aspectRatio": "1:1", "imageSize": "1K"})
        first = bodies[0]["contents"]
        self.assertEqual(len(first), 1)
        self.assertIn("a frog knight. Full-body", first[0]["parts"][0]["text"])
        last = bodies[3]["contents"]
        self.assertEqual([c["role"] for c in last], ["user", "model", "user", "model", "user", "model", "user"])
        model1 = last[1]["parts"]
        self.assertEqual(model1[0]["thoughtSignature"], "thought-sig-1")
        self.assertEqual(model1[1]["thoughtSignature"], "sig-1")
        self.assertEqual(base64.b64decode(model1[1]["inlineData"]["data"]),   # the same picture, metadata stripped
                         figure_png(colour_of("gemini-1"), text=False))
        self.assertIn("from its left side", last[2]["parts"][0]["text"])
        self.assertIn("from its right side", last[6]["parts"][0]["text"])
        rec = self.record()
        p = ref.GEMINI_PRICES["gemini-nano-banana-2.1"]
        want = (1000 * p["in"] + 1120 * p["image_out"] + (10 + 100) * p["text_out"]) / 1e6
        self.assertAlmostEqual(rec["views"]["front"]["cost"], want, places=6)
        self.assertAlmostEqual(rec["cost"]["this_run"], sum(v["cost"] for v in rec["views"].values()), places=5)
        self.assertEqual(rec["cost"]["unit"], "usd")
        self.assertIn("Google won't claim ownership", rec["terms"]["owner"])
        row = self.log_rows()[0]
        self.assertIn("Google Gemini API (gemini-nano-banana-2.1)", row)
        self.assertIn("paid service", row)
        self.assertIn("SynthID", row)
        self.assertIn("[quote] nanobanana", out)
        self.assertEqual(len(self.journal()["steps"]), 4)
        self.clean_files()

    def test_concept_goes_out_stripped(self):
        rc, out = self.run_tool("chr_hero", "--from", "art_src/concept.png", "--with", "nanobanana", "--seed", "5",
                                "--views", "front,back")
        self.assertEqual(rc, 0, out)
        first = self.gemini_bodies()[0]["contents"][0]["parts"]
        self.assertEqual(first[0]["inline_data"]["mime_type"], "image/png")
        self.assertEqual(first[1]["text"], ref.REPOSE)
        self.sent_out()
        self.clean_files()

    def test_quote_over_cap_stops_before_any_call(self):
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "nanobanana", "--seed", "5",
                                "--max-cost", "0.05")
        self.assertEqual(rc, 2)
        self.assertIn("over --max-cost", out)
        self.assertEqual(STATE.calls("/v1beta/"), [])

    def test_cap_stop_mid_run_then_rerun_reuses_what_was_paid(self):
        STATE.gemini_thoughts = 30000          # replies cost far more than the quote's thinking allowance
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "nanobanana", "--seed", "5",
                                "--max-cost", "0.30")
        self.assertEqual(rc, 2, out)
        self.assertIn("over --max-cost", out)
        self.assertEqual(len(STATE.calls("/v1beta/")), 1)
        self.assertFalse((self.dir / "front.png").exists(), "views are written only at the end")
        self.assertEqual(len(self.journal()["steps"]), 1)
        STATE.reset()
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "nanobanana", "--seed", "5",
                                "--max-cost", "1")
        self.assertEqual(rc, 0, out)
        self.assertIn("reused from the journal", out)
        self.assertEqual(len(STATE.calls("/v1beta/")), 3, "the front was not paid for again")
        rec = self.record()
        self.assertTrue(rec["views"]["front"]["reused"])
        self.assertEqual(rec["views"]["front"]["cost"], 0.0)
        self.assertGreater(rec["cost"]["total_paid"], rec["cost"]["this_run"])
        # the rerun's second call still carried the reused front with its signature
        second = json.loads(STATE.calls("/v1beta/")[0][3])["contents"]
        self.assertEqual(second[1]["parts"][1]["thoughtSignature"], "sig-1")

    def test_failed_call_exit_1_keeps_paid_views(self):
        STATE.gemini = ["ok", "500"]
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "nanobanana", "--seed", "5")
        self.assertEqual(rc, 1, out)
        self.assertIn("HTTP 500", out)
        self.assertEqual(len(self.journal()["steps"]), 1)
        STATE.reset()
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "nanobanana", "--seed", "5")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(STATE.calls("/v1beta/")), 3)
        STATE.reset()
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "nanobanana", "--seed", "5",
                                "--overwrite", "--no-reuse")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(STATE.calls("/v1beta/")), 4, "--no-reuse pays again")

    def test_blocked_picture_and_refused_key(self):
        STATE.gemini = ["safety"]
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "nanobanana", "--seed", "5")
        self.assertEqual(rc, 1)
        self.assertIn("IMAGE_SAFETY", out)
        self.assertIn("still cost", out)
        STATE.reset()
        STATE.gemini = ["badkey"]
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "nanobanana", "--seed", "5")
        self.assertEqual(rc, 2)
        self.assertIn("refused the key", out)
        self.assertNotIn(KEY_G, out)

    def test_reply_without_usage_is_estimated(self):
        STATE.gemini = ["nousage"]
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "nanobanana", "--seed", "5",
                                "--views", "front")
        self.assertEqual(rc, 0, out)
        self.assertIn("estimated", out)
        self.assertTrue(self.journal()["steps"][next(iter(self.journal()["steps"]))]["cost_estimated"])


# ---- tripo route ----------------------------------------------------------------------------------------------------
class TripoRoute(Base):
    def test_prompt_text_to_image_then_multiview(self):
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "tripo", "--seed", "8")
        self.assertEqual(rc, 0, out)
        kinds = [t["type"] for t in STATE.tasks.values()]
        self.assertEqual(kinds, ["text_to_image", "image_to_multiview"])
        t2i = STATE.tasks["task-1"]["body"]
        self.assertEqual(t2i["model"], "banana2")
        self.assertEqual(t2i["aspect_ratio"], "1:1")
        self.assertEqual(t2i["output_format"], "png")
        self.assertIn("A-pose", t2i["prompt"])
        self.assertEqual(STATE.tasks["task-2"]["body"], {"input": "file_1"})
        for _, path, headers, _ in STATE.calls("/v3/"):
            self.assertEqual(headers.get("authorization"), f"Bearer {KEY_T}")
        for i, v in enumerate(("left", "back", "right")):
            img = refsheet.decode((self.dir / f"{v}.png").read_bytes())
            self.assertEqual(img.px(24, 24), colour_of(f"/cdn/task-2_{v}.png"), v)
        front = refsheet.decode((self.dir / "front.png").read_bytes())
        self.assertEqual(front.px(24, 24), colour_of("/cdn/task-1.png"), "front.png is the A-pose front itself")
        rec = self.record()
        self.assertEqual(rec["cost"], {"unit": "credits", "quoted": 20.0, "this_run": 15.0, "total_paid": 15.0,
                                       "cap": 40.0})
        self.assertIn("5.2.2", rec["terms"]["owner"])
        row = self.log_rows()[0]
        self.assertIn("Tripo API (banana2, image-to-multiview)", row)
        self.assertIn("15 credits", row)
        self.sent_out()
        self.clean_files()

    def test_concept_image_to_image(self):
        rc, out = self.run_tool("chr_hero", "--from", "art_src/concept.png", "--with", "tripo", "--seed", "8",
                                "--views", "front")
        self.assertEqual(rc, 0, out)
        self.assertEqual([t["type"] for t in STATE.tasks.values()], ["image_to_image"])
        body = STATE.tasks["task-1"]["body"]
        self.assertEqual(body["input"], "file_1")
        self.assertEqual(body["prompt"], ref.REPOSE)
        self.assertNotIn(EMBEDDED.encode(), STATE.uploads[0])
        self.assertEqual(self.record()["cost"]["this_run"], 7.0)

    def test_failed_task_exit_1_and_not_counted(self):
        STATE.fail_type = "image_to_multiview"
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "tripo", "--seed", "8")
        self.assertEqual(rc, 1, out)
        self.assertIn("failed", out)
        steps = self.journal()["steps"]
        self.assertEqual(sorted(e["status"] for e in steps.values()), ["running", "success"])
        self.assertEqual(self.record_missing(), True)
        # the rerun asks about the failed task (not charged), makes a new one, and reuses the paid front
        STATE.fail_type = None
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "tripo", "--seed", "8")
        self.assertEqual(rc, 0, out)
        self.assertIn("not charged", out)
        self.assertEqual([t["type"] for t in STATE.tasks.values()],
                         ["text_to_image", "image_to_multiview", "image_to_multiview"])
        self.assertEqual(self.record()["cost"]["this_run"], 10.0)
        STATE.tasks.clear()
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "tripo", "--seed", "8",
                                "--no-reuse", "--overwrite")
        self.assertEqual(rc, 0, out)
        self.assertEqual([t["type"] for t in STATE.tasks.values()], ["text_to_image", "image_to_multiview"],
                         "--no-reuse pays for everything again")

    def record_missing(self):
        return not (self.dir / ref.RECORD).exists()

    def test_task_left_running_is_waited_for_not_paid_twice(self):
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "tripo", "--seed", "8",
                                "--views", "front")
        self.assertEqual(rc, 0, out)
        j = self.journal()
        key = next(iter(j["steps"]))
        j["steps"][key]["status"] = "running"     # as if the last run was cut off while Tripo worked
        (self.dir / ref.JOURNAL).write_text(json.dumps(j), encoding="utf-8")
        before = len(STATE.tasks)
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "tripo", "--seed", "8",
                                "--views", "front", "--overwrite")
        self.assertEqual(rc, 0, out)
        self.assertIn("asking Tripo for it first", out)
        self.assertEqual(len(STATE.tasks), before, "no second task was created")
        self.assertEqual(self.record()["cost"]["this_run"], 0.0)

    def test_cap_stop_mid_run_and_reuse(self):
        STATE.credits["text_to_image"] = 35.0          # costlier than quoted
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "tripo", "--seed", "8")
        self.assertEqual(rc, 2, out)
        self.assertIn("over --max-cost", out)
        self.assertEqual([t["type"] for t in STATE.tasks.values()], ["text_to_image"])
        STATE.tasks.clear()
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "tripo", "--seed", "8")
        self.assertEqual(rc, 0, out)
        self.assertEqual([t["type"] for t in STATE.tasks.values()], ["image_to_multiview"])
        rec = self.record()
        self.assertEqual(rec["cost"]["this_run"], 10.0)
        self.assertEqual(rec["cost"]["total_paid"], 45.0)

    def test_quote_over_cap_and_low_balance(self):
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "tripo", "--seed", "8",
                                "--max-cost", "15")
        self.assertEqual(rc, 2)
        self.assertEqual(STATE.calls("/v3/"), [])
        STATE.balance = 4
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "tripo", "--seed", "8")
        self.assertEqual(rc, 2)
        self.assertIn("balance", out)
        self.assertEqual(STATE.tasks, {})

    def test_refused_key(self):
        os.environ[ref.TRIPO_ENV] = "wrong"
        rc, out = self.run_tool("chr_hero", "--prompt", "a frog knight", "--with", "tripo", "--seed", "8")
        self.assertEqual(rc, 2)
        self.assertIn("refused the key", out)


# ---- refsheet ---------------------------------------------------------------------------------------------------------
class Sheet(unittest.TestCase):
    def test_reader_every_filter_and_colour_type(self):
        w, h = 5, 4
        rgb = bytes((x * 40 + y * 7) % 256 for y in range(h) for x in range(w * 3))
        want = refsheet.Image(w, h, rgb)
        for filt in range(5):
            img = refsheet._decode_png(filtered_png(rgb, w, h, 2, filt))
            self.assertEqual(img.rgb, want.rgb, f"filter {filt}")
        rgba = b"".join(rgb[i:i + 3] + b"\xff" for i in range(0, len(rgb), 3))
        self.assertEqual(refsheet._decode_png(filtered_png(rgba, w, h, 6, 4)).rgb, rgb)
        gray = bytes(range(0, 200, 10))
        self.assertEqual(refsheet._decode_png(filtered_png(gray, w, h, 0, 3)).px(1, 0), (10, 10, 10))
        pal = refsheet._decode_png(filtered_png(bytes([0, 1] * 10), w, h, 3, 1, plte=b"\x10\x20\x30\xf0\xe0\xd0",
                                                trns=b"\xff\x00"))
        self.assertEqual(pal.px(0, 0), (16, 32, 48))
        self.assertEqual(pal.px(1, 0), refsheet.BACKGROUND, "a transparent pixel is flattened onto the grey")
        self.assertIsNone(refsheet.decode(b"not a picture"))

    def test_encode_roundtrip_and_sheet_size(self):
        img = refsheet._decode_png(figure_png())
        self.assertEqual(refsheet._decode_png(refsheet.encode(img)).rgb, img.rgb)
        s = refsheet._decode_png(refsheet.sheet([img, img, img], cell_h=96))
        self.assertEqual((s.w, s.h), (refsheet.GAP + 3 * (96 + refsheet.GAP), 96 + 2 * refsheet.GAP))

    def test_look_check(self):
        ok = refsheet._decode_png(figure_png())
        self.assertEqual(refsheet.look({"front": ok, "left": ok})["warnings"], [])
        short = refsheet._decode_png(figure_png(top=20))
        warns = refsheet.look({"front": ok, "back": short})["warnings"]
        self.assertTrue(any("height" in w for w in warns), warns)
        cut = refsheet._decode_png(figure_png(top=0, bottom=48))
        self.assertTrue(any("touches the edge" in w for w in refsheet.look({"front": cut})["warnings"]))
        floor = refsheet._decode_png(figure_png(top=6, bottom=48))     # feet or a floor shadow on the bottom edge
        self.assertTrue(any("bottom edge" in w for w in refsheet.look({"front": floor})["warnings"]))
        dark = refsheet.Image(8, 8, bytes((20, 20, 20)) * 64)
        warns = refsheet.look({"front": dark})["warnings"]
        self.assertTrue(any("not light grey" in w for w in warns), warns)
        noisy = refsheet.Image(16, 16, bytes((i * 97) % 256 for i in range(16 * 16 * 3)))
        self.assertTrue(any("not flat" in w for w in refsheet.look({"front": noisy})["warnings"]))
        self.assertTrue(any("not readable" in w for w in refsheet.look({"front": None})["warnings"]))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)

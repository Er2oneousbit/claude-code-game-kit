#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_meshwright.py
# Purpose : The exam for meshwright.py, offline: a stand-in ComfyUI on 127.0.0.1 (a random port) answers what the
#           tool asks (/system_stats, /object_info with the loaders' file lists, /upload/image, /prompt, /history,
#           /view, /free) and returns a canned mesh built here in pure Python: a textured barrel-like cylinder with
#           ComfyUI's prompt (a local path) in its glTF extras, every triangle on its own vertices, a stray fragment
#           and more triangles than a prop may have.
#           Part 1 (standard library, any Python 3.8+): front door help and exit codes, check, the non-commercial
#           refusal, everything make decides before GPU time, the job settings per class and quality, the prompt
#           route, the asset log row and evidence, a budget failure, a re-run, no local paths in written files.
#           The Blender steps are replaced by a stand-in here.
#           Part 2 (when Blender or the bpy module is found): the same make with the real cleanup.py,
#           prep_export.py, validate_asset.py and turntable.py: triangles under budget, height, pivot, fragment
#           gone, LODs smaller, a size budget failure that ships nothing.
# Usage   : python tools/meshwright/test_meshwright.py                       # part 1, part 2 if Blender is found
#           uv run --python 3.13 --with bpy python tools/meshwright/test_meshwright.py   # part 2 on the bpy module
#           MESHWRIGHT_TEST_BLENDER=skip|bpy|<path to blender>  picks part 2's Blender (skip: part 1 only)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import http.server
import io
import json
import math
import os
import shutil
import struct
import sys
import tempfile
import threading
import unittest
import urllib.parse
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import meshwright as mw  # noqa: E402
cl = mw.cl

EMBEDDED_PATH = "X:/someone/ComfyUI/input/private_reference.png"   # stands in for what SaveGLB embeds
LOG = """# Asset Log

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | | | | | | | no | no | 2026-01-01 | |

## Rules
"""
PNG_SIG = b"\x89PNG\r\n\x1a\n"


# ---- fixtures -------------------------------------------------------------------------------
def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def png(w=4, h=4, rgb=(150, 90, 40), text=True):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + (chunk(b"tEXt", b"prompt\x00" + json.dumps({"path": EMBEDDED_PATH}).encode()) if text else b"")
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def canned_glb(segments=64, rings=30, radius=0.4, height=0.9):
    """A textured cylinder about 0.9 units across, Y-up and centred like TRELLIS.2's output, as triangle soup
    (every triangle on its own three vertices, so merging has work to do), plus a tiny loose triangle above it.
    Side: 2 * segments * rings triangles, caps: 2 * segments, fragment: 1."""
    pos, uv = [], []

    def tri(a, b, c):
        for p, t in (a, b, c):
            pos.append(p)
            uv.append(t)

    y0, y1 = -height / 2, height / 2
    ring = [(math.cos(2 * math.pi * i / segments), math.sin(2 * math.pi * i / segments)) for i in range(segments + 1)]
    for j in range(rings):
        ya, yb = y0 + height * j / rings, y0 + height * (j + 1) / rings
        va, vb = 0.7 * j / rings, 0.7 * (j + 1) / rings
        for i in range(segments):
            (ca, sa), (cb, sb) = ring[i], ring[i + 1]
            ua, ub = i / segments, (i + 1) / segments
            p00, p10 = (radius * ca, ya, radius * sa), (radius * cb, ya, radius * sb)
            p01, p11 = (radius * ca, yb, radius * sa), (radius * cb, yb, radius * sb)
            tri((p00, (ua, va)), (p01, (ua, vb)), (p10, (ub, va)))
            tri((p10, (ub, va)), (p01, (ua, vb)), (p11, (ub, vb)))
    for y, flip, u0 in ((y1, False, 0.0), (y0, True, 0.5)):
        centre = ((0.0, y, 0.0), (u0 + 0.25, 0.85))
        for i in range(segments):
            (ca, sa), (cb, sb) = ring[i], ring[i + 1]
            a = ((radius * ca, y, radius * sa), (u0 + 0.25 + 0.14 * ca, 0.85 + 0.14 * sa))
            b = ((radius * cb, y, radius * sb), (u0 + 0.25 + 0.14 * cb, 0.85 + 0.14 * sb))
            tri(centre, b, a) if not flip else tri(centre, a, b)
    f = ((0.3, 0.6, 0.0), (0.0, 0.0))   # the stray fragment: one tiny triangle floating above the lid
    tri(f, ((0.31, 0.6, 0.0), (0.01, 0.0)), ((0.3, 0.61, 0.0), (0.0, 0.01)))
    n = len(pos)
    pbin = b"".join(struct.pack("<3f", *p) for p in pos)
    tbin = b"".join(struct.pack("<2f", u, 1 - v) for u, v in uv)
    img = png(8, 8, text=False)
    pad = lambda b: b + b"\x00" * (-len(b) % 4)  # noqa: E731
    binary = pad(pbin) + pad(tbin) + pad(img)
    o1, o2 = len(pad(pbin)), len(pad(pbin)) + len(pad(tbin))
    mins = [min(p[i] for p in pos) for i in range(3)]
    maxs = [max(p[i] for p in pos) for i in range(3)]
    doc = {"asset": {"version": "2.0", "generator": "ComfyUI",
                     "extras": {"prompt": json.dumps({"1": {"inputs": {"image": EMBEDDED_PATH}}})}},
           "buffers": [{"byteLength": len(binary)}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pbin), "target": 34962},
                           {"buffer": 0, "byteOffset": o1, "byteLength": len(tbin), "target": 34962},
                           {"buffer": 0, "byteOffset": o2, "byteLength": len(img)}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": n, "type": "VEC3", "min": mins, "max": maxs},
                         {"bufferView": 1, "componentType": 5126, "count": n, "type": "VEC2"}],
           "images": [{"bufferView": 2, "mimeType": "image/png"}], "samplers": [{}],
           "textures": [{"source": 0, "sampler": 0}],
           "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0,
                                                   "roughnessFactor": 0.8}, "doubleSided": True}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "material": 0}]}],
           "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0}
    return cl.write_glb(doc, binary)


def vertex_glb(segments=32, rings=8, radius=0.4, height=0.9):
    """What ComfyUI's SaveGLB writes for PaintMesh's output: an indexed cylinder with linear COLOR_0 (VEC3 float),
    no TEXCOORD_0 (PaintMesh runs before UnwrapMesh), and a plain material whose base colour factor is white."""
    pos, col, idx = [], [], []
    for j in range(rings + 1):
        y = -height / 2 + height * j / rings
        for i in range(segments):
            a = 2 * math.pi * i / segments
            pos.append((radius * math.cos(a), y, radius * math.sin(a)))
            col.append((0.6 * j / rings, 0.3, 0.1 + 0.5 * i / segments))
    for j in range(rings):
        for i in range(segments):
            a, b = j * segments + i, j * segments + (i + 1) % segments
            idx += [a, a + segments, b, b, a + segments, b + segments]
    for y, flip in ((height / 2, False), (-height / 2, True)):   # caps: a centre vertex and a fan
        c = len(pos)
        pos.append((0.0, y, 0.0))
        col.append((0.8, 0.8, 0.2))
        ring0 = (rings if not flip else 0) * segments
        for i in range(segments):
            a, b = ring0 + i, ring0 + (i + 1) % segments
            idx += [c, b, a] if not flip else [c, a, b]
    pad = lambda b: b + b"\x00" * (-len(b) % 4)  # noqa: E731
    pbin = b"".join(struct.pack("<3f", *p) for p in pos)
    cbin = b"".join(struct.pack("<3f", *c) for c in col)
    ibin = b"".join(struct.pack("<I", i) for i in idx)
    binary = pad(pbin) + pad(cbin) + pad(ibin)
    o1, o2 = len(pad(pbin)), len(pad(pbin)) + len(pad(cbin))
    doc = {"asset": {"version": "2.0", "generator": "ComfyUI",
                     "extras": {"prompt": json.dumps({"1": {"inputs": {"image": EMBEDDED_PATH}}})}},
           "buffers": [{"byteLength": len(binary)}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pbin), "target": 34962},
                           {"buffer": 0, "byteOffset": o1, "byteLength": len(cbin), "target": 34962},
                           {"buffer": 0, "byteOffset": o2, "byteLength": len(ibin), "target": 34963}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3",
                          "min": [min(p[i] for p in pos) for i in range(3)],
                          "max": [max(p[i] for p in pos) for i in range(3)]},
                         {"bufferView": 1, "componentType": 5126, "count": len(col), "type": "VEC3"},
                         {"bufferView": 2, "componentType": 5125, "count": len(idx), "type": "SCALAR"}],
           "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1.0, 1.0, 1.0, 1.0], "metallicFactor": 0.0,
                                                   "roughnessFactor": 1.0}, "doubleSided": True}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}, "indices": 2, "material": 0}]}],
           "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0}
    return cl.write_glb(doc, binary)


def glb_doc(path):
    return cl.read_glb(Path(path).read_bytes())[0]


# ---- stand-in ComfyUI ------------------------------------------------------------------------
class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.prompts, self.uploads, self.frees = [], [], 0
        self.missing = set()          # model files the loaders do not list
        self.drop_nodes = set()       # node types /object_info leaves out
        self.fail = None
        self.mesh = canned_glb()


STATE = State()
WF3D = json.loads(mw.WORKFLOW_3D.read_text(encoding="utf-8"))
WFREF = json.loads(mw.WORKFLOW_REF.read_text(encoding="utf-8"))


def object_info():
    info = {n["class_type"]: {"input": {"required": {}}} for wf in (WF3D, WFREF) for n in wf.values()}
    models = mw.load_lock()["models"] + mw.klein_models()
    for m in models:
        names = [x["file"] for x in models if x["loader"] == m["loader"] and x["file"] not in STATE.missing]
        names.append("someone_elses_model.safetensors")
        req = info.setdefault(m["loader"], {"input": {"required": {}}})["input"]["required"]
        req[m["input"]] = ["COMBO", {"options": names}] if m["loader"] == "LoadBackgroundRemovalModel" else [names]
    for n in STATE.drop_nodes:
        info.pop(n, None)
    return info


class FakeComfy(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/system_stats":
            return self.send(200, {"system": {"comfyui_version": "0.43.0", "python_version": "3.12.12"},
                                   "devices": [{"name": "cuda:0 Test GPU", "vram_total": 16 * 1024 ** 3,
                                                "vram_free": 15 * 1024 ** 3}]})
        if url.path == "/object_info":
            return self.send(200, object_info())
        if url.path.startswith("/history/"):
            pid = url.path.rsplit("/", 1)[-1]
            graph = STATE.prompts[int(pid.split("-")[1]) - 1]["prompt"]
            if STATE.fail:
                return self.send(200, {pid: {"outputs": {}, "status": {"status_str": "error", "completed": False,
                                       "messages": [["execution_error", {"node_id": "24", "node_type": "KSampler",
                                                                         "exception_message": STATE.fail}]]}}})
            if any(n["class_type"] == "SaveGLB" for n in graph.values()):   # only the Save nodes in the graph ran
                outs = {nid: {"3d": [{"filename": f"{n['inputs']['filename_prefix'].split('/')[-1]}_00001_.glb",
                                      "subfolder": "meshwright", "type": "output"}]}
                        for nid, n in graph.items() if n["class_type"] == "SaveGLB"}
            else:
                outs = {"13": {"images": [{"filename": "reference_00001_.png", "subfolder": "meshwright",
                                           "type": "output"}]}}
            return self.send(200, {pid: {"outputs": outs, "status": {"status_str": "success", "completed": True,
                                                                     "messages": []}}})
        if url.path == "/queue":
            return self.send(200, {"queue_running": [], "queue_pending": []})
        if url.path == "/view":
            name = urllib.parse.parse_qs(url.query)["filename"][0]
            if name.endswith(".glb"):
                return self.send(200, STATE.mesh, "model/gltf-binary")
            return self.send(200, png(16, 16), "image/png")
        self.send(404, {"error": "no such path in the exam"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/prompt":
            graph = json.loads(body.decode("utf-8"))["prompt"]
            dangling = {nid: v[0] for nid, n in graph.items() for v in n["inputs"].values()
                        if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in graph}
            if dangling:   # ComfyUI refuses a graph whose links point at nodes that are not in it
                return self.send(400, {"error": {"type": "prompt_outputs_failed_validation", "message": "bad link"},
                                       "node_errors": {k: {"errors": [{"message": f"input from missing node {v}"}]}
                                                       for k, v in dangling.items()}})
            STATE.prompts.append(json.loads(body.decode("utf-8")))
            return self.send(200, {"prompt_id": f"p-{len(STATE.prompts)}", "number": 1, "node_errors": {}})
        if self.path == "/upload/image":
            STATE.uploads.append(body)
            return self.send(200, {"name": "reference.png", "subfolder": "", "type": "input"})
        if self.path == "/free":
            STATE.frees += 1
            return self.send(200, {})
        self.send(404, {"error": "no such path"})


# ---- a stand-in for the Blender steps (part 1) --------------------------------------------------
class FakeBlender:
    """Replaces run_bpy: copies the mesh through each step and writes the reports the real scripts write.
    validate_rc 1 plays a budget failure."""

    def __init__(self):
        self.calls, self.validate_rc = [], 0

    def __call__(self, blender, script, argv, what):
        argv = [str(a) for a in argv]
        self.calls.append((Path(script).name, argv))
        name = Path(script).name
        if name == "cleanup.py":
            Path(argv[2]).write_bytes(Path(argv[0]).read_bytes())
            Path(argv[argv.index("--json") + 1]).write_text(json.dumps({"tris_in": 3969, "tris_out": 2600,
                                                                         "parts_dropped": 1}), encoding="utf-8")
        elif name == "prep_export.py":
            out = Path(argv[2])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(Path(argv[0]).read_bytes())
            if "--lods" in argv:
                for i, _ in enumerate(argv[argv.index("--lods") + 1].split(","), 1):
                    out.with_name(f"{out.stem}_LOD{i}.glb").write_bytes(out.read_bytes())
        elif name == "validate_asset.py":
            if self.validate_rc not in (0, 1):   # a crash: Blender dies before the report is written
                return self.validate_rc, "Segmentation fault"
            report = {"asset": str(Path(argv[0]).resolve()), "total_tris": 2600, "objects": [],
                      "failures": ["prop_x: largest side 5.00 m is over 3.0 m"] if self.validate_rc else [],
                      "warnings": ["texel density varies 3.0x"], "notes": []}
            Path(argv[argv.index("--json") + 1]).write_text(json.dumps(report), encoding="utf-8")
            return self.validate_rc, ""
        elif name == "turntable.py":
            Path(argv[2]).write_bytes(png(text=False))
        elif name == "render_sprites.py":
            out = Path(argv[2])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png(16, 8, (20, 200, 60), text=False))
            out.with_suffix(".json").write_text(json.dumps({"cell": 128}), encoding="utf-8")
        return 0, ""


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeComfy)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        STATE.reset()
        self.tmp = tempfile.TemporaryDirectory(prefix="mw_exam_")
        self.root = Path(self.tmp.name).resolve()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        (self.root / "art_src").mkdir()
        (self.root / "art_src" / "crate.png").write_bytes(png(32, 32))
        self.saved = (cl.SLEEP, mw.SLEEP, mw.run_bpy, mw.find_blender, os.getcwd())
        cl.SLEEP = mw.SLEEP = lambda s: None
        self.fake = FakeBlender()
        mw.run_bpy = self.fake
        mw.find_blender = lambda choice=None: ("blender", "fake-blender")
        mw.blender_version.cache_clear()
        self.real_version = mw.blender_version
        mw.blender_version = lambda b: "Blender 9.9 (stand-in)"
        os.chdir(self.root)

    def tearDown(self):
        cl.SLEEP, mw.SLEEP, mw.run_bpy, mw.find_blender, cwd = self.saved
        mw.blender_version = self.real_version
        os.chdir(cwd)
        self.tmp.cleanup()

    def run_tool(self, *argv, url=True):
        args = list(argv) + (["--url", self.url] if url else [])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mw.main(args)
        return rc, out.getvalue() + err.getvalue()

    def make(self, *extra, name="prop_crate"):
        return self.run_tool("make", name, *(extra or ("--image", "art_src/crate.png", "--seed", "7")))

    def mesh_jobs(self):
        return [p["prompt"] for p in STATE.prompts if any(n["class_type"] == "SaveGLB" for n in p["prompt"].values())]

    def no_local_paths(self):
        """No written file names the temp folder, the user's home or the path ComfyUI embedded."""
        needles = [str(self.root).encode(), self.root.as_posix().encode(), EMBEDDED_PATH.encode(),
                   str(Path.home()).encode(), Path.home().as_posix().encode()]
        for p in self.root.rglob("*"):
            if p.is_file() and p.parts[len(self.root.parts)] != "art_src":   # the exam's own input carries one
                data = p.read_bytes()
                for n in needles:
                    self.assertNotIn(n, data, f"{p.relative_to(self.root)} holds a local path")


# ---- part 1: standard library ------------------------------------------------------------------
class FrontDoor(Base):
    def test_help_and_usage_exit_codes(self):
        rc, out = self.run_tool("--help", url=False)
        self.assertEqual(rc, 0)
        self.assertIn("Exit: 0 ok, 1", out)
        self.assertIn("BLENDER_BIN", out)
        self.assertEqual(self.run_tool(url=False)[0], 2, "no subcommand is a usage error")
        rc, out = self.run_tool("make", "-h", url=False)
        self.assertEqual(rc, 0)
        for opt in ("--image", "--prompt", "--class", "--seed", "--out", "--lods", "--debug", "--quality"):
            self.assertIn(opt, out)

    def test_list_shows_steps_and_class_budgets(self):
        rc, out = self.run_tool("list", url=False)
        self.assertEqual(rc, 0)
        for word in ("cleanup", "prep_export", "validate_asset", "3,000", "60,000", "turntable"):
            self.assertIn(word, out)

    def test_make_usage_errors_exit_2_before_any_job(self):
        cases = [((), "exactly one of"),
                 (("--image", "art_src/crate.png", "--prompt", "x"), "not allowed with"),
                 (("--image", "nope.png"), "not found"),
                 (("--image", "art_src/crate.png", "--reference-only"), "goes with --prompt"),
                 (("--image", "art_src/crate.png", "--lods", "0.5,2"), "between 0 and 1"),
                 (("--image", "art_src/crate.png", "--height", "-1"), "positive")]
        for argv, why in cases:
            rc, out = self.run_tool("make", "prop_crate", *argv)
            self.assertEqual(rc, 2, f"{argv}: {out}")
            self.assertIn(why, out, argv)
        rc, out = self.run_tool("make", "Prop Crate", "--image", "art_src/crate.png")
        self.assertEqual(rc, 2)
        self.assertIn("lowercase", out)
        self.assertEqual(STATE.prompts, [], "usage errors must not reach ComfyUI")


class Check(Base):
    def test_check_ready(self):
        rc, out = self.run_tool("check")
        self.assertEqual(rc, 0, out)
        self.assertIn("all 5 model files present", out)
        self.assertIn("FLUX.2 klein 4B files present", out)
        self.assertIn("DINOv3", out)

    def test_check_names_a_missing_model_with_its_folder_and_url(self):
        STATE.missing = {"birefnet.safetensors"}
        rc, out = self.run_tool("check")
        self.assertEqual(rc, 2, out)
        self.assertIn("ComfyUI/models/background_removal/", out)
        self.assertIn("huggingface.co/Comfy-Org/BiRefNet/resolve/", out)

    def test_check_without_blender_or_server(self):
        mw.find_blender = lambda choice=None: None
        rc, out = self.run_tool("check", "--url", "http://127.0.0.1:9", url=False)
        self.assertEqual(rc, 2)
        self.assertIn("Blender not found", out)
        self.assertIn("no ComfyUI answering", out)
        self.assertIn("NOT checked", out)

    def test_loader_options_reads_both_object_info_styles(self):
        info = {"A": {"input": {"required": {"f": [["x.safetensors", "sub/y.safetensors"]]}}},
                "B": {"input": {"required": {"f": ["COMBO", {"options": ["z.safetensors"]}]}}}}
        self.assertEqual(mw.loader_options(info, "A", "f"), {"x.safetensors", "y.safetensors"})
        self.assertEqual(mw.loader_options(info, "B", "f"), {"z.safetensors"})
        self.assertEqual(mw.loader_options(info, "C", "f"), set())

    def test_non_commercial_pieces_refused(self):
        wf = json.loads(json.dumps(WF3D))
        wf["2"]["inputs"]["bg_removal_name"] = "RMBG-2.0.safetensors"
        (self.root / "bad.api.json").write_text(json.dumps(wf), encoding="utf-8")
        self.assertEqual(mw.non_commercial_in(WF3D), [])
        rc, out = self.run_tool("check", "--workflow", "bad.api.json")
        self.assertIn("non-commercial", out)
        rc, out = self.make("--image", "art_src/crate.png", "--workflow", "bad.api.json")
        self.assertEqual(rc, 2, out)
        self.assertIn("RMBG-2.0", out)
        self.assertEqual(STATE.prompts, [])

    def test_lock_and_licence_files_agree(self):
        lock = mw.load_lock()
        files = {m["file"] for m in lock["models"]}
        self.assertEqual(files, {n["inputs"][k] for n in WF3D.values() for k in n["inputs"]
                                 if isinstance(n["inputs"][k], str) and n["inputs"][k].endswith(".safetensors")},
                         "the lock must list exactly the files the workflow loads")
        text = (HERE / "LICENSES.md").read_text(encoding="utf-8")
        for m in lock["models"]:
            self.assertIn(m["file"], text)
            self.assertIn(m["commit"][:8], text)
            self.assertEqual(len(m["sha256"]), 64)
        self.assertTrue(any(p.name.startswith("DINOv3") for p in mw.LICENSE_TEXTS.iterdir()))


class MakePreflight(Base):
    def test_files_in_the_way_stop_before_the_gpu(self):
        (self.root / "assets" / "models").mkdir(parents=True)
        (self.root / "assets" / "models" / "prop_crate.glb").write_bytes(b"mine")
        rc, out = self.make()
        self.assertEqual(rc, 2, out)
        self.assertIn("--overwrite", out)
        self.assertEqual(STATE.prompts, [])
        self.assertEqual((self.root / "assets" / "models" / "prop_crate.glb").read_bytes(), b"mine")

    def test_needs_asset_log_or_no_log(self):
        (self.root / "docs" / "ASSET_LOG.md").unlink()
        rc, out = self.make()
        self.assertEqual(rc, 2, out)
        self.assertIn("ASSET_LOG.md not found", out)
        self.assertEqual(STATE.prompts, [])
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "1", "--no-log")
        self.assertEqual(rc, 0, out)

    def test_out_outside_the_project_needs_no_log(self):
        rc, out = self.make("--image", "art_src/crate.png", "--out", str(self.root.parent / "elsewhere"))
        self.assertEqual(rc, 2, out)
        self.assertIn("outside the project", out)

    def test_no_blender_stops_before_the_gpu(self):
        mw.find_blender = lambda choice=None: None
        rc, out = self.make()
        self.assertEqual(rc, 2, out)
        self.assertIn("Blender not found", out)
        self.assertEqual(STATE.prompts, [])

    def test_missing_model_or_node_stops_before_the_gpu(self):
        STATE.missing = {"trellis_2_int8_convrot.safetensors"}
        rc, out = self.make()
        self.assertEqual(rc, 2, out)
        self.assertIn("ComfyUI/models/diffusion_models/", out)
        STATE.missing, STATE.drop_nodes = set(), {"Trellis2Conditioning"}
        rc, out = self.make()
        self.assertEqual(rc, 2, out)
        self.assertIn("Trellis2Conditioning", out)
        self.assertEqual(STATE.prompts, [])


class MakeRun(Base):
    def test_image_route_end_to_end(self):
        rc, out = self.make()
        self.assertEqual(rc, 0, out)
        jobs = self.mesh_jobs()
        self.assertEqual(len(jobs), 1)
        wf = jobs[0]
        seeds = [n["inputs"]["seed"] for n in wf.values() if n["class_type"] == "KSampler"]
        self.assertEqual(seeds, [7, 7, 7, 7], "--seed sets every sampler")
        self.assertEqual(wf["20"]["inputs"]["target_resolution"], 1024)
        self.assertEqual(wf["27"]["inputs"]["target_face_count"], 2700, "prop: 90% of 3000")
        self.assertEqual(wf["30"]["inputs"]["texture_size"], 1024)
        self.assertEqual(wf["1"]["inputs"]["image"], "reference.png")
        self.assertEqual(len(STATE.uploads), 1)
        src = self.root / "assets_src" / "meshwright" / "prop_crate"
        raw = (src / "raw.glb").read_bytes()
        self.assertNotIn(b"extras", raw, "ComfyUI's prompt must be stripped from the raw mesh")
        self.assertNotIn(b"tEXt", (src / "reference.png").read_bytes())
        self.assertTrue((self.root / "assets" / "models" / "prop_crate.glb").is_file())
        self.assertEqual([c[0] for c in self.fake.calls],
                         ["cleanup.py", "prep_export.py", "validate_asset.py", "turntable.py"])
        cleanup = self.fake.calls[0][1]
        self.assertEqual(cleanup[cleanup.index("--max-tris") + 1], "2700")
        self.assertEqual(cleanup[cleanup.index("--height") + 1], "1.0")
        rec = json.loads((src / "meshwright.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["seed"], 7)
        self.assertEqual(rec["files"][0]["file"], "assets/models/prop_crate.glb")
        self.assertEqual(rec["reference"]["kind"], "image")
        self.assertIn("DINOv3 License", {m["license"] for m in rec["models"]})
        self.assertEqual(json.loads((src / "validate.json").read_text(encoding="utf-8"))["asset"],
                         "assets_src/meshwright/prop_crate/export/prop_crate.glb")
        log = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        row = [l for l in log.splitlines() if l.startswith("| A-0001")][0]
        for cell in ("| model |", "`assets/models/prop_crate.glb`", "TRELLIS.2", "pre-generated", "DINOv3 License",
                     "mit", "Built with DINOv3", "seed 7"):
            self.assertIn(cell, row)
        ev = (self.root / "docs" / "licenses" / "A-0001.txt").read_text(encoding="utf-8")
        self.assertIn("Comfy-Org/TRELLIS.2 @ 430a9d09b241", ev)
        self.assertIn("SHA-256", ev)
        lic = sorted(p.name for p in (self.root / "docs" / "licenses").glob("meshwright-*"))
        self.assertEqual(lic, ["meshwright-BiRefNet-LICENSE.txt", "meshwright-DINOv3-LICENSE.md",
                               "meshwright-TRELLIS.2-LICENSE.txt"])
        self.no_local_paths()

    def test_models_folder_follows_the_engine(self):
        (self.root / ".game-kit.json").write_text(json.dumps({"engine": "web-3d"}), encoding="utf-8")
        rc, out = self.make()
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "public" / "assets" / "models" / "prop_crate.glb").is_file())
        self.assertIn("`public/assets/models/prop_crate.glb`", (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8"))

    def test_godot_game_is_told_to_import(self):
        (self.root / "project.godot").write_text("", encoding="utf-8")
        rc, out = self.make()
        self.assertEqual(rc, 0, out)
        self.assertIn("python tools/dev.py import", out)

    def test_class_and_quality_settings_reach_the_job(self):
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "3", "--class", "hero", "--quality", "high",
                            "--no-preview", name="chr_test")
        self.assertEqual(rc, 0, out)
        wf = self.mesh_jobs()[0]
        self.assertEqual(wf["20"]["inputs"]["target_resolution"], 1536)
        self.assertEqual(wf["27"]["inputs"]["target_face_count"], 54000)
        self.assertEqual(wf["29"]["inputs"]["resolution"], 2048)
        models = self.root / "assets" / "models"
        self.assertEqual(sorted(p.name for p in models.iterdir()),
                         ["chr_test.glb", "chr_test_LOD1.glb", "chr_test_LOD2.glb"], "hero: LODs 0.5,0.25 by default")
        self.assertNotIn("turntable.py", [c[0] for c in self.fake.calls])

    def test_prompt_route_reference_then_mesh(self):
        rc, out = self.make("--prompt", "a wooden crate with rope handles", "--seed", "11")
        self.assertEqual(rc, 0, out)
        ref = STATE.prompts[0]["prompt"]
        self.assertEqual(ref["8"]["inputs"]["noise_seed"], 11)
        text = ref["4"]["inputs"]["text"]
        self.assertTrue(text.startswith("a wooden crate with rope handles, one single object"))
        self.assertIn("plain white background", text)
        self.assertEqual(STATE.frees, 1, "the klein models are unloaded before TRELLIS.2")
        self.assertEqual(len(self.mesh_jobs()), 1)
        rec = json.loads((self.root / "assets_src/meshwright/prop_crate/meshwright.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["reference"]["prompt"], "a wooden crate with rope handles")
        self.assertIn("apache-2.0", {m["license"] for m in rec["models"]})
        row = [l for l in (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8").splitlines()
               if l.startswith("| A-0001")][0]
        self.assertIn("prompt: a wooden crate with rope handles", row)
        self.assertIn("FLUX.2 klein", row)
        self.no_local_paths()

    def test_character_prompt_and_reference_only(self):
        rc, out = self.run_tool("make", "npc_test", "--prompt", "a small robot", "--class", "npc", "--seed", "2",
                                "--reference-only")
        self.assertEqual(rc, 0, out)
        self.assertIn("A-pose", STATE.prompts[0]["prompt"]["4"]["inputs"]["text"])
        self.assertEqual(len(STATE.prompts), 1, "--reference-only stops before the 3D job")
        self.assertTrue((self.root / "assets_src/meshwright/npc_test/reference_seed2.png").is_file(),
                        "audition references are named by seed, so several can sit side by side")
        self.assertFalse((self.root / "assets").exists())
        self.assertNotIn("A-0001 | model", (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8"))

    def test_budget_failure_ships_nothing_and_logs_nothing(self):
        self.fake.validate_rc = 1
        rc, out = self.make()
        self.assertEqual(rc, 1, out)
        self.assertIn("fails the prop budget", out)
        self.assertIn("over 3.0 m", out)
        self.assertFalse((self.root / "assets" / "models" / "prop_crate.glb").exists())
        self.assertNotIn("| model |", (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8"))
        self.assertTrue((self.root / "assets_src/meshwright/prop_crate/export/prop_crate.glb").is_file(),
                        "the failed files stay in the source folder to look at")

    def test_validator_crash_ships_nothing_even_with_an_old_report(self):
        # an earlier passing run left validate.json behind; this run's validator crashes (a Windows access
        # violation): nothing may reach the models folder or the log on the strength of the old report
        src = self.root / "assets_src" / "meshwright" / "prop_crate"
        src.mkdir(parents=True)
        (src / "validate.json").write_text(json.dumps({"failures": [], "warnings": [], "notes": []}), encoding="utf-8")
        self.fake.validate_rc = 3221225477
        rc, out = self.make()
        self.assertEqual(rc, 1, out)
        self.assertIn("validate_asset.py did not finish (exit 3221225477)", out)
        self.assertFalse((self.root / "assets" / "models" / "prop_crate.glb").exists(), "an unchecked model shipped")
        self.assertNotIn("| model |", (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8"))
        self.assertFalse((src / "validate.json").exists(), "the stale report must go")

    def test_rerun_needs_overwrite_and_updates_the_same_row(self):
        self.assertEqual(self.make()[0], 0)
        rc, out = self.make()
        self.assertEqual(rc, 2, out)
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "8", "--overwrite")
        self.assertEqual(rc, 0, out)
        log = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertEqual(log.count("`assets/models/prop_crate.glb`"), 1, "a re-run updates its row")
        self.assertIn("seed 8", log)
        self.assertFalse((self.root / "docs" / "licenses" / "A-0002.txt").exists())

    def test_failed_job_exit_1(self):
        STATE.fail = "CUDA out of memory"
        rc, out = self.make()
        self.assertEqual(rc, 1, out)
        self.assertIn("out of memory", out)
        self.assertFalse((self.root / "assets" / "models" / "prop_crate.glb").exists())

    def test_reference_photo_metadata_is_removed(self):
        # the reference copy is committed with the game: a phone photo's EXIF GPS must not ride along
        gps = b"GPSLatitude 51.4779 N"
        seg = lambda m, body: bytes((0xFF, m)) + len(body + b"..").to_bytes(2, "big") + body  # noqa: E731
        scan = seg(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x12\xff\x00\x34\xff\xd9"
        jpg = (b"\xff\xd8" + seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
               + seg(0xE1, b"Exif\x00\x00MM\x00\x2a" + gps) + seg(0xFE, b"a comment") + seg(0xDB, bytes(65)) + scan)
        (self.root / "art_src" / "photo.jpg").write_bytes(jpg)
        whole = png(8, 8)
        (self.root / "art_src" / "shot.png").write_bytes(whole[:33] + chunk(b"eXIf", b"MM\x00\x2a" + gps) + whole[33:])
        for image, name, ref in (("art_src/photo.jpg", "prop_photo", "reference.jpg"),
                                 ("art_src/shot.png", "prop_shot", "reference.png")):
            rc, out = self.make("--image", image, "--seed", "4", "--no-preview", name=name)
            self.assertEqual(rc, 0, out)
            kept = (self.root / "assets_src" / "meshwright" / name / ref).read_bytes()
            self.assertNotIn(gps, kept, f"{ref} kept the GPS position")
            self.assertNotIn(gps, STATE.uploads[-1], "ComfyUI got the GPS position too")
            rec = json.loads((self.root / "assets_src/meshwright" / name / "meshwright.json").read_text(encoding="utf-8"))
            self.assertEqual(rec["reference"]["sha256"], mw.sha256_bytes(kept))
        self.assertTrue(kept.startswith(PNG_SIG))
        (self.root / "art_src" / "fake.webp").write_bytes(b"not a picture")
        rc, out = self.make("--image", "art_src/fake.webp", "--seed", "4", name="prop_fake")
        self.assertEqual(rc, 2, out)
        self.assertIn("not a PNG, JPEG or WebP", out)
        self.assertEqual(len(self.mesh_jobs()), 2, "a file that is not a picture stops before the GPU")

    def test_sprite_sheet_is_logged_with_its_hash(self):
        # a 2D game ships the sheet, not the .glb: it is AI-derived art and needs its row, record entry and hash
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "7", "--sprites", "assets/art/crate_sheet.png")
        self.assertEqual(rc, 0, out)
        sheet = self.root / "assets" / "art" / "crate_sheet.png"
        self.assertTrue(sheet.is_file())
        digest = mw.sha256_bytes(sheet.read_bytes())
        rec = json.loads((self.root / "assets_src/meshwright/prop_crate/meshwright.json").read_text(encoding="utf-8"))
        self.assertIn({"file": "assets/art/crate_sheet.png", "sha256": digest, "kind": "sprite sheet"}, rec["files"])
        self.assertEqual(rec["tris"], rec["files"][0]["triangles"])
        row = [l for l in (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8").splitlines()
               if l.startswith("| A-0001")][0]
        self.assertIn("`assets/art/crate_sheet.png`", row)
        self.assertIn(digest, (self.root / "docs" / "licenses" / "A-0001.txt").read_text(encoding="utf-8"))
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "7", "--sprites", "assets/art/crate_sheet.png")
        self.assertEqual(rc, 2, "a second run without --overwrite stops before the GPU")
        self.no_local_paths()

    def test_vertex_material_takes_the_other_output(self):
        STATE.mesh = vertex_glb()
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "1", "--material", "vertex")
        self.assertEqual(rc, 0, out)
        self.assertIn("raw mesh", out)

    def test_each_material_queues_only_its_own_branch(self):
        # ComfyUI runs every Save node in a graph: a vertex job must not spend GPU minutes on the unwrap and the
        # bakes, and a texture job must not paint vertex colours it throws away
        types = lambda wf: {n["class_type"] for n in wf.values()}  # noqa: E731
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "1", "--material", "vertex", "--no-preview")
        self.assertEqual(rc, 0, out)
        wf = self.mesh_jobs()[-1]
        self.assertEqual([n["_meta"]["title"] for n in wf.values() if n["class_type"] == "SaveGLB"],
                         [mw.NODES["vertex"]])
        for gone in ("UnwrapMesh", "BakeTextureFromVoxel", "BakeNormalMapFromMesh", "BakeAmbientOcclusion",
                     "ApplyTextureToMesh"):
            self.assertNotIn(gone, types(wf))
        self.assertIn("PaintMesh", types(wf))
        rec = json.loads((self.root / "assets_src/meshwright/prop_crate/meshwright.json").read_text(encoding="utf-8"))
        self.assertFalse([s for s in rec["job"]["settings"] if "texture_size" in s], "no bake settings on a vertex job")
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "2", "--overwrite", "--no-preview")
        self.assertEqual(rc, 0, out)
        wf = self.mesh_jobs()[-1]
        self.assertEqual([n["_meta"]["title"] for n in wf.values() if n["class_type"] == "SaveGLB"],
                         [mw.NODES["textured"]])
        self.assertNotIn("PaintMesh", types(wf))
        self.assertIn("BakeTextureFromVoxel", types(wf))


# ---- part 2: the real Blender steps ---------------------------------------------------------------
def part2_blender():
    """Blender for part 2: MESHWRIGHT_TEST_BLENDER (skip, bpy or a path), else what meshwright itself finds; under
    a Python that has the bpy module, the module (that is what `uv run --with bpy` asks for)."""
    choice = os.environ.get("MESHWRIGHT_TEST_BLENDER", "")
    if choice == "skip":
        return None
    if not choice and mw.bpy_importable():
        choice = "bpy"
    return mw.find_blender(choice or None)


REAL_RUN, REAL_VERSION = mw.run_bpy, mw.blender_version
BLENDER = part2_blender()


@unittest.skipIf(BLENDER is None, "no Blender or bpy module found (part 2 skipped)")
class RealBlender(Base):
    def setUp(self):
        super().setUp()
        mw.run_bpy, mw.blender_version = REAL_RUN, REAL_VERSION
        mw.find_blender = lambda choice=None: BLENDER

    def bounds(self, path):
        doc = glb_doc(path)
        acc = [doc["accessors"][p["attributes"]["POSITION"]] for m in doc["meshes"] for p in m["primitives"]]
        lo = [min(a["min"][i] for a in acc) for i in range(3)]
        hi = [max(a["max"][i] for a in acc) for i in range(3)]
        return lo, hi, mw.glb_triangles(doc)

    def test_real_cleanup_export_validate_turntable(self):
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "5", "--height", "0.8", "--lods", "0.5")
        self.assertEqual(rc, 0, out)
        main = self.root / "assets" / "models" / "prop_crate.glb"
        lo, hi, tris = self.bounds(main)
        self.assertLessEqual(tris, 2700, "decimated to the face target")
        self.assertGreater(tris, 1500, "not decimated to nothing")
        self.assertAlmostEqual(hi[1] - lo[1], 0.8, places=3, msg="glTF +Y is up: height 0.8 m")
        self.assertAlmostEqual(lo[1], 0.0, places=4, msg="pivot at the bottom")
        self.assertAlmostEqual((lo[0] + hi[0]) / 2, 0.0, places=3)
        self.assertAlmostEqual((lo[2] + hi[2]) / 2, 0.0, places=3)
        self.assertNotIn(b"extras", main.read_bytes())
        doc = glb_doc(main)
        self.assertEqual(doc["nodes"][0]["name"], "prop_crate")
        self.assertTrue(doc.get("images"), "the texture survives cleanup and export")
        lod = self.root / "assets" / "models" / "prop_crate_LOD1.glb"
        self.assertLess(self.bounds(lod)[2], tris)
        src = self.root / "assets_src" / "meshwright" / "prop_crate"
        rep = json.loads((src / "cleanup.json").read_text(encoding="utf-8"))
        self.assertEqual(rep["tris_in"], 2 * 64 * 30 + 2 * 64 + 1)
        self.assertEqual(rep["merged_vertices"], 3 * rep["tris_in"] - (64 * 31 + 2 + 3), "triangle soup welded to its 1989 corners")
        self.assertEqual(rep["parts_dropped"], 1, "the stray fragment is gone")
        self.assertTrue(rep["decimated"])
        val = json.loads((src / "validate.json").read_text(encoding="utf-8"))
        self.assertEqual(val["failures"], [])
        self.assertTrue((src / "turntable.png").read_bytes().startswith(PNG_SIG))
        self.assertIn("| model |", (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8"))
        self.no_local_paths()

    def test_real_vertex_colour_mesh_without_uvs(self):
        # --material vertex: PaintMesh's mesh has no UV map; cleanup.py gives it one (lightmaps need it, and the
        # validator fails a mesh without), the colours survive cleanup and export, and the model ships
        STATE.mesh = vertex_glb()
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "5", "--material", "vertex", "--no-preview")
        self.assertEqual(rc, 0, out)
        main = self.root / "assets" / "models" / "prop_crate.glb"
        doc = glb_doc(main)
        attrs = doc["meshes"][0]["primitives"][0]["attributes"]
        self.assertIn("COLOR_0", attrs, "the vertex colours are the model's only colour: they must survive")
        self.assertIn("TEXCOORD_0", attrs)
        self.assertFalse(doc.get("images"), "a vertex-colour model has no textures")
        src = self.root / "assets_src" / "meshwright" / "prop_crate"
        self.assertTrue(json.loads((src / "cleanup.json").read_text(encoding="utf-8"))["uv_added"])
        val = json.loads((src / "validate.json").read_text(encoding="utf-8"))
        self.assertEqual(val["failures"], [])
        self.assertTrue(any("no image texture" in n for n in val["notes"]), val["notes"])

    def test_real_size_budget_failure(self):
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "5", "--height", "5", "--no-preview")
        self.assertEqual(rc, 1, out)
        self.assertIn("over 3.0 m", out)
        self.assertFalse((self.root / "assets" / "models").exists())

    def test_cleanup_on_its_own_and_its_usage_errors(self):
        (self.root / "raw.glb").write_bytes(canned_glb(16, 4))
        code, out = REAL_RUN(BLENDER, HERE / "cleanup.py", [self.root / "raw.glb", "--out", self.root / "c.glb",
                                                            "--turn", "90", "--min-part", "0"], "cleanup")
        self.assertEqual(code, 0, out)
        lo, hi, tris = self.bounds(self.root / "c.glb")
        self.assertEqual(tris, 2 * 16 * 4 + 2 * 16 + 1, "--min-part 0 keeps the fragment, no budget: no decimation")
        self.assertAlmostEqual(lo[1], 0.0, places=4)
        code, out = REAL_RUN(BLENDER, HERE / "cleanup.py", [self.root / "raw.glb", "--out", self.root / "c.glb"],
                             "cleanup")
        self.assertEqual(code, 2, "an existing --out needs --overwrite")
        code, out = REAL_RUN(BLENDER, HERE / "cleanup.py", [self.root / "missing.glb", "--out", self.root / "d.glb"],
                             "cleanup")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    print(f"[info] part 2 Blender: {BLENDER[0] + ' ' + Path(BLENDER[1]).name if BLENDER else 'none (skipped)'}")
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)

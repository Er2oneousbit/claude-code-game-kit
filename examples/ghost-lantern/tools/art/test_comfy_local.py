#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_comfy_local.py
# Purpose : Exam for comfy_local.py, offline: a stand-in ComfyUI server on 127.0.0.1 (a random port) answers the
#           endpoints the tool uses (/system_stats, /object_info, /upload/image, /prompt, /history, /queue,
#           /view), so no GPU, models or ComfyUI install are needed. Checks the local-only rule, workflow formats,
#           --set / --seed / --image, missing nodes, rejected, failed, interrupted and cancelled jobs, PNG
#           text-chunk and FLAC tag stripping (audio jobs), EXIF/XMP removal from PNG, JPEG and WebP pictures,
#           no overwrite, ASSET_LOG rows, and a non-ASCII prompt end to end.
# Usage   : python tools/art/test_comfy_local.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
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
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "audio" / "wavesmith"))
import comfy_local as cl  # noqa: E402
import flacfile  # noqa: E402  (decodes the audio to prove stripping kept it intact)
from test_flacfile import FIXTURES as FLAC_FIXTURES  # noqa: E402  (a real encoder's FLAC, padding removed)

PNG_SIG = b"\x89PNG\r\n\x1a\n"
EMBEDDED_PATH = "C:/Users/you/ComfyUI/models/private.safetensors"   # stands in for what ComfyUI embeds
LOG = """# Asset Log

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | | | | | | | no | no | 2026-01-01 | |

## Rules
"""
WORKFLOW = {
    "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 4, "denoise": 1.0, "model": ["4", 0]}},
    "4": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux-2-klein-4b.safetensors"}},
    "5": {"class_type": "LoraLoader", "inputs": {"lora_name": "pixel\\pixel_lora.safetensors", "model": ["4", 0]}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a lamp post"}, "_meta": {"title": "Prompt"}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "kit", "images": ["3", 0]}},
    "12": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
}


def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def png_with_text():
    raw = b"\x00" + b"\x00\x00\x00\xff"                       # one opaque black pixel
    return (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"tEXt", b"prompt\x00" + json.dumps({"path": EMBEDDED_PATH}).encode())
            + chunk(b"iTXt", b"workflow\x00\x00\x00\x00\x00{}")
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def flac_with_tags():
    """A real FLAC (ffmpeg's encoder) with a VORBIS_COMMENT block holding ComfyUI-style prompt text."""
    import base64
    data = base64.b64decode(FLAC_FIXTURES["mono16"])
    comment = ("prompt=" + json.dumps({"path": EMBEDDED_PATH})).encode()
    vendor = b"Lavf63.1.102"
    body = (struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 1)
            + struct.pack("<I", len(comment)) + comment)
    info_len = int.from_bytes(data[5:8], "big")
    streaminfo = bytes([data[4] & 0x7F]) + data[5:8 + info_len]
    # the new tag block goes right after STREAMINFO and takes over its "last block" flag (ffmpeg's own
    # encoder tag block may follow, and then keeps its flag)
    tags = bytes([0x04 | (data[4] & 0x80)]) + len(body).to_bytes(3, "big") + body
    return data[:4] + streaminfo + tags + data[8 + info_len:]


def glb_with_extras():
    """A one-triangle GLB with ComfyUI-style asset.extras.prompt (SaveGLB writes the whole prompt there)."""
    binary = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    doc = {"asset": {"version": "2.0", "generator": "ComfyUI", "extras": {"prompt": json.dumps({"path": EMBEDDED_PATH})}},
           "buffers": [{"byteLength": len(binary)}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary)}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
                          "min": [0, 0, 0], "max": [1, 1, 0]}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}], "extras": {"workflow": "{}"}}],
           "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0}
    return cl.write_glb(doc, binary)


class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.prompts, self.uploads = [], []
        self.upload_name = "hero.png"  # the name /upload/image answers with (ComfyUI renames when one is taken)
        self.reject = False          # /prompt answers 400 with node errors
        self.fail = None             # history status error with this exception message
        self.interrupted = False     # history status error with only an execution_interrupted message
        self.polls_pending = 1       # history polls that return {} before the result
        self.dropped = False         # the job left the queue without a result (cancelled before it ran)
        self.queue_polls = 0
        self.nodes = {n["class_type"] for n in WORKFLOW.values()}
        self.files = [{"filename": "kit_00001_.png", "subfolder": "", "type": "output"},
                      {"filename": "kit_preview.png", "subfolder": "", "type": "temp"}]
        self.audio = []              # Save Audio node outputs (history key "audio")
        self.models = []             # Save 3D Model node outputs (history key "3d")
        self.redirect = None         # /system_stats answers 302 to this address (#248)


STATE = State()


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
        if url.path == "/system_stats" and STATE.redirect:
            self.send_response(302)
            self.send_header("Location", STATE.redirect)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if url.path == "/system_stats":
            return self.send(200, {"system": {"comfyui_version": "0.43.0", "python_version": "3.12.12 (main)"},
                                   "devices": [{"name": "cuda:0 Test GPU", "vram_total": 16 * 1024 ** 3,
                                                "vram_free": 12 * 1024 ** 3}]})
        if url.path == "/object_info":
            return self.send(200, {n: {} for n in STATE.nodes})
        if url.path.startswith("/history/"):
            pid = url.path.rsplit("/", 1)[-1]
            if STATE.polls_pending > 0 or STATE.dropped:
                STATE.polls_pending -= 1
                return self.send(200, {})
            if STATE.interrupted:
                return self.send(200, {pid: {"outputs": {}, "status": {"status_str": "error", "completed": False,
                                       "messages": [["execution_start", {"prompt_id": pid}],
                                                    ["execution_interrupted", {"node_id": "3",
                                                                               "node_type": "KSampler"}]]}}})
            if STATE.fail:
                return self.send(200, {pid: {"outputs": {}, "status": {"status_str": "error", "completed": False,
                                       "messages": [["execution_error", {"node_id": "3", "node_type": "KSampler",
                                                                         "exception_message": STATE.fail}]]}}})
            return self.send(200, {pid: {"outputs": {"9": {"images": STATE.files}, "10": {"audio": STATE.audio},
                                                     "11": {"3d": STATE.models}},
                                         "status": {"status_str": "success", "completed": True, "messages": []}}})
        if url.path == "/queue":
            STATE.queue_polls += 1
            running = [] if STATE.dropped else [[1, "p-1", {}, {}, []]]
            return self.send(200, {"queue_running": running, "queue_pending": []})
        if url.path == "/view":
            q = urllib.parse.parse_qs(url.query)
            name = q["filename"][0]
            if name.endswith(".png"):
                return self.send(200, png_with_text(), "image/png")
            if name.endswith(".flac"):
                return self.send(200, flac_with_tags(), "audio/flac")
            if name.endswith(".glb"):
                return self.send(200, glb_with_extras(), "model/gltf-binary")
            if name.endswith(".webp"):
                return self.send(200, webp_with_exif()[0], "image/webp")
            if name.endswith(".mp3"):
                return self.send(200, b"ID3 fake mp3", "audio/mpeg")
            return self.send(200, b"GIF89a fake", "image/gif")
        self.send(404, {"error": "no such path in the exam"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/prompt":
            if STATE.reject:
                return self.send(400, {"error": {"message": "Prompt outputs failed validation"},
                                       "node_errors": {"4": {"class_type": "UNETLoader", "errors": [
                                           {"message": "Value not in list", "details": "unet_name: 'x' not in []"}]}}})
            STATE.prompts.append(json.loads(body.decode("utf-8")))
            return self.send(200, {"prompt_id": "p-1", "number": 1, "node_errors": {}})
        if self.path == "/upload/image":
            STATE.uploads.append(body)
            return self.send(200, {"name": STATE.upload_name, "subfolder": "", "type": "input"})
        self.send(404, {"error": "no such path"})


class ComfyLocalExam(unittest.TestCase):
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
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        (self.root / "wf.api.json").write_text(json.dumps(WORKFLOW), encoding="utf-8")
        (self.root / "hero.png").write_bytes(png_with_text())
        self.real_sleep = cl.SLEEP
        cl.SLEEP = lambda s: None
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)
        cl.SLEEP = self.real_sleep
        self.tmp.cleanup()

    def run_tool(self, *argv, url=True):
        args = list(argv) + (["--url", self.url] if url else [])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cl.main(args)
        return rc, out.getvalue() + err.getvalue()

    # ---- server and checks
    def test_check_reports_version_and_gpu(self):
        rc, out = self.run_tool("check")
        self.assertEqual(rc, 0, out)
        self.assertIn("ComfyUI 0.43.0", out)
        self.assertIn("12.0 GB of 16.0 GB VRAM free", out)

    def test_check_workflow_lists_models(self):
        rc, out = self.run_tool("check", "--workflow", "wf.api.json")
        self.assertEqual(rc, 0, out)
        self.assertIn("all 6 nodes", out)
        self.assertIn("pixel/pixel_lora.safetensors", out)

    def test_missing_node_pack_named(self):
        STATE.nodes.discard("LoraLoader")
        rc, out = self.run_tool("check", "--workflow", "wf.api.json")
        self.assertEqual(rc, 2)
        self.assertIn("LoraLoader", out)

    def test_remote_server_refused(self):
        rc, out = self.run_tool("check", "--url", "http://192.168.1.50:8188", url=False)
        self.assertEqual(rc, 2)
        self.assertIn("not this machine", out)

    def test_remote_allowed_on_request(self):
        args = cl.build_parser().parse_args(["check", "--url", "http://10.0.0.2:8188", "--allow-remote"])
        self.assertEqual(cl.server_url(args), "http://10.0.0.2:8188")

    def test_localhost_names_accepted(self):
        for url in ("http://localhost:8188", "http://[::1]:8188", "http://127.0.0.5:8188"):
            args = cl.build_parser().parse_args(["check", "--url", url])
            self.assertEqual(cl.server_url(args), url)

    def test_server_down_gives_the_fix(self):
        rc, out = self.run_tool("check", "--url", "http://127.0.0.1:9", url=False)
        self.assertEqual(rc, 2)
        self.assertIn("no ComfyUI answering", out)
        self.assertNotIn("Traceback", out)

    # ---- workflow handling
    def test_ui_format_refused_with_hint(self):
        (self.root / "ui.json").write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
        rc, out = self.run_tool("run", "--workflow", "ui.json", "--out", "o")
        self.assertEqual(rc, 2)
        self.assertIn("Export (API)", out)

    def test_dry_run_sends_nothing_and_applies_sets(self):
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o", "--dry-run",
                                "--set", "Prompt.text=a brass gear", "--set", "3.steps=8", "--seed", "42")
        self.assertEqual(rc, 0, out)
        self.assertEqual(STATE.prompts, [])
        self.assertIn('"text": "a brass gear"', out)
        self.assertIn('"steps": 8', out)
        self.assertIn('"seed": 42', out)
        self.assertFalse((self.root / "o").exists())

    def test_set_unknown_input_lists_real_ones(self):
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o", "--set", "3.stepz=8")
        self.assertEqual(rc, 2)
        self.assertIn("denoise, model, seed, steps", out)

    def test_set_wired_input_refused(self):
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o", "--set", "3.model=x")
        self.assertEqual(rc, 2)
        self.assertIn("wired to another node", out)

    def test_unknown_node_lists_ids_and_titles(self):
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o", "--set", "Nope.text=x")
        self.assertEqual(rc, 2)
        self.assertIn("titles: Prompt", out)

    # ---- running
    def test_run_saves_clean_png_and_record(self):
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "assets/art", "--seed", "7")
        self.assertEqual(rc, 0, out)
        saved = self.root / "assets" / "art" / "kit_00001_.png"
        data = saved.read_bytes()
        self.assertTrue(data.startswith(PNG_SIG))
        self.assertNotIn(b"tEXt", data)
        self.assertNotIn(b"iTXt", data)
        self.assertNotIn(EMBEDDED_PATH.encode(), data)
        self.assertIn(b"IDAT", data)
        self.assertFalse((self.root / "assets" / "art" / "kit_preview.png").exists(), "temp previews are skipped")
        self.assertEqual(STATE.prompts[0]["prompt"]["3"]["inputs"]["seed"], 7)
        rec = json.loads((self.root / "assets" / "art" / cl.GEN_FILE).read_text(encoding="utf-8"))
        self.assertEqual(rec["seed"], 7)
        self.assertIn("flux-2-klein-4b.safetensors", rec["models"])
        self.assertEqual(len(rec["sha256"][0]), 64)

    def test_include_temp_saves_previews(self):
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o", "--include-temp")
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "o" / "kit_preview.png").exists())

    def test_no_overwrite_without_flag(self):
        self.assertEqual(self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")[0], 0)
        STATE.polls_pending = 0
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 2)
        self.assertIn("--overwrite", out)
        self.assertEqual(self.run_tool("run", "--workflow", "wf.api.json", "--out", "o", "--overwrite")[0], 0)

    def test_existing_record_or_any_output_stops_before_writing(self):
        # #30: comfy_local.gen.json was always replaced, and a job wrote its first files before refusing a later one
        (self.root / "o").mkdir()
        (self.root / "o" / cl.GEN_FILE).write_bytes(b"keep")
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 2, out)
        self.assertIn(cl.GEN_FILE, out)
        self.assertEqual((self.root / "o" / cl.GEN_FILE).read_bytes(), b"keep")
        self.assertEqual(STATE.prompts, [], "refused before the GPU was spent")
        (self.root / "o" / cl.GEN_FILE).unlink()
        (self.root / "o" / "kit_preview.png").write_bytes(b"keep")
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o", "--include-temp")
        self.assertEqual(rc, 2, out)
        self.assertFalse((self.root / "o" / "kit_00001_.png").exists(), "nothing written when one file is refused")
        self.assertEqual((self.root / "o" / "kit_preview.png").read_bytes(), b"keep")

    def test_image_upload_points_node_at_it(self):
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o", "--image", "12=hero.png")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(STATE.uploads), 1)
        self.assertEqual(STATE.prompts[0]["prompt"]["12"]["inputs"]["image"], "hero.png")

    def test_upload_never_replaces_comfyuis_own_file(self):
        # #32: uploads sent overwrite=true, replacing an input file of the same name already in ComfyUI
        STATE.upload_name = "hero (1).png"
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o", "--image", "12=hero.png")
        self.assertEqual(rc, 0, out)
        self.assertIn(b'name="overwrite"' + bytes([13, 10, 13, 10]) + b"false", STATE.uploads[0])
        self.assertEqual(STATE.prompts[0]["prompt"]["12"]["inputs"]["image"], "hero (1).png", "the name ComfyUI chose")

    def test_rejected_workflow_shows_node_errors(self):
        STATE.reject = True
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 2)
        self.assertIn("node 4 (UNETLoader): Value not in list", out)

    def test_failed_job_exit_1_with_oom_hint(self):
        STATE.fail = "CUDA out of memory. Tried to allocate 2.00 GiB"
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 1)
        self.assertIn("node 3 (KSampler)", out)
        self.assertIn("--lowvram", out)

    def test_interrupted_job_says_so(self):
        STATE.interrupted = True
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 1)
        self.assertIn("interrupted at node 3 (KSampler)", out)
        self.assertNotIn("no message", out)

    def test_job_cancelled_before_it_ran_stops_the_wait(self):
        STATE.polls_pending = 12     # still running for 12 polls: two /queue checks see it and keep waiting
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 0, out)
        self.assertEqual(STATE.queue_polls, 2)
        STATE.reset()
        STATE.dropped = True
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o2", "--wait", "60")
        self.assertEqual(rc, 1)
        self.assertIn("left ComfyUI's queue without a result", out)
        self.assertEqual(STATE.queue_polls, 1)        # stopped at the first check, not after --wait

    def test_non_png_output_saved_with_warning(self):
        STATE.files = [{"filename": "walk.gif", "subfolder": "", "type": "output"}]
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 0, out)
        self.assertIn("[warn] walk.gif", out)

    def test_webp_output_loses_its_exif_and_xmp(self):
        """#198: a WebP that ComfyUI returned was saved with its EXIF and XMP (the workflow), only warned about."""
        STATE.files = [{"filename": "kit_00001_.webp", "subfolder": "", "type": "output"}]
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("[warn] kit_00001_.webp", out)
        saved = (self.root / "o" / "kit_00001_.webp").read_bytes()
        for gone in (GPS, b"EXIF", b"xmpmeta"):
            self.assertNotIn(gone, saved)
        self.assertIn(webp_with_exif()[1], saved, "the image itself is kept")

    def test_hostile_file_name_stays_in_out(self):
        STATE.files = [{"filename": "../../evil.png", "subfolder": "", "type": "output"}]
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "o" / "evil.png").exists())
        self.assertFalse((self.root.parent / "evil.png").exists())

    # ---- logging
    def test_log_row_and_evidence_non_ascii_prompt(self):
        prompt = "Í baker \u201cold\u201d | brass"
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "assets/art", "--log",
                                "--set", f"Prompt.text={prompt}", "--type", "sprite", "--seed", "3")
        self.assertEqual(rc, 0, out)
        log = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertIn("| A-0001 | sprite | `assets/art/kit_00001_.png` | ComfyUI (local)", log)
        self.assertIn("pre-generated", log)
        self.assertIn("Í baker", log)
        self.assertIn("\\| brass", log, "a pipe in the prompt must not break the table")
        self.assertIn("seed 3", log)
        ev = (self.root / "docs" / "licenses" / "A-0001.txt").read_text(encoding="utf-8")
        self.assertIn("flux-2-klein-4b.safetensors", ev)
        self.assertIn("SHA-256", ev)

    def test_log_needs_asset_log_before_running(self):
        (self.root / "docs" / "ASSET_LOG.md").unlink()
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o", "--log")
        self.assertEqual(rc, 2)
        self.assertEqual(STATE.prompts, [], "nothing should be queued when the log is missing")

    # ---- strip
    def test_strip_into_folder(self):
        rc, out = self.run_tool("strip", "hero.png", "--out", "clean", url=False)
        self.assertEqual(rc, 0, out)
        self.assertNotIn(b"tEXt", (self.root / "clean" / "hero.png").read_bytes())
        self.assertIn(b"tEXt", (self.root / "hero.png").read_bytes(), "the original is untouched")

    def test_strip_needs_out_or_overwrite(self):
        rc, out = self.run_tool("strip", "hero.png", url=False)
        self.assertEqual(rc, 2)
        rc, out = self.run_tool("strip", "hero.png", "--overwrite", url=False)
        self.assertEqual(rc, 0, out)
        self.assertNotIn(b"tEXt", (self.root / "hero.png").read_bytes())

    # ---- audio jobs (Save Audio writes FLAC with the prompt and workflow in its tags)
    def test_audio_job_saves_flac_without_tags_and_same_audio(self):
        STATE.files = []
        STATE.audio = [{"filename": "sfx_00001_.flac", "subfolder": "audio", "type": "output"}]
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 0, out)
        saved = (self.root / "o" / "sfx_00001_.flac").read_bytes()
        self.assertNotIn(EMBEDDED_PATH.encode(), saved)
        self.assertIn(EMBEDDED_PATH.encode(), flac_with_tags(), "the stand-in must carry the path to begin with")
        before, after = flacfile.decode(flac_with_tags()), flacfile.decode(saved)
        self.assertEqual((after[2], after[1]), ("ok", before[1]), "stripping changed the audio or broke its MD5")
        self.assertNotIn("[warn]", out)

    def test_audio_formats_without_strip_are_saved_with_warning(self):
        STATE.files = []
        STATE.audio = [{"filename": "sfx_00001_.mp3", "subfolder": "audio", "type": "output"}]
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 0, out)
        self.assertIn("[warn] sfx_00001_.mp3", out)

    # ---- 3D jobs (Save 3D Model writes the prompt into the glTF asset extras)
    def test_3d_job_saves_glb_without_extras_and_same_mesh(self):
        STATE.files = []
        STATE.models = [{"filename": "textured_00001_.glb", "subfolder": "bozzetto", "type": "output"}]
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 0, out)
        saved = (self.root / "o" / "textured_00001_.glb").read_bytes()
        self.assertIn(EMBEDDED_PATH.encode(), glb_with_extras(), "the stand-in must carry the path to begin with")
        self.assertNotIn(EMBEDDED_PATH.encode(), saved)
        self.assertNotIn(b"extras", saved)
        doc, binary = cl.read_glb(saved)
        before = cl.read_glb(glb_with_extras())
        self.assertEqual(binary, before[1], "stripping changed the mesh data")
        self.assertEqual(doc["accessors"], before[0]["accessors"])
        self.assertEqual(len(saved) % 4, 0, "GLB length must stay a multiple of 4")
        self.assertNotIn("[warn]", out)

    def test_strip_glb_by_hand_and_refuse_a_cut_one(self):
        (self.root / "m.glb").write_bytes(glb_with_extras())
        rc, out = self.run_tool("strip", "m.glb", "--out", "clean", url=False)
        self.assertEqual(rc, 0, out)
        self.assertNotIn(EMBEDDED_PATH.encode(), (self.root / "clean" / "m.glb").read_bytes())
        (self.root / "cut.glb").write_bytes(glb_with_extras()[:30])
        rc, out = self.run_tool("strip", "cut.glb", "--out", "c2", url=False)
        self.assertEqual(rc, 2, out)
        self.assertFalse((self.root / "c2" / "cut.glb").exists())

    def test_strip_flac_by_hand(self):
        (self.root / "take.flac").write_bytes(flac_with_tags())
        rc, out = self.run_tool("strip", "take.flac", "--out", "clean", url=False)
        self.assertEqual(rc, 0, out)
        clean = (self.root / "clean" / "take.flac").read_bytes()
        self.assertNotIn(EMBEDDED_PATH.encode(), clean)
        self.assertEqual(flacfile.decode(clean)[2], "ok")
        self.assertEqual(clean[4] & 0x80, 0x80, "STREAMINFO must now carry the last-block flag")

    def test_strip_refuses_truncated_flac(self):
        (self.root / "bad.flac").write_bytes(flac_with_tags()[:20])
        rc, out = self.run_tool("strip", "bad.flac", "--out", "c", url=False)
        self.assertEqual(rc, 2, out)
        self.assertIn("truncated", out)

    def test_strip_refuses_non_png(self):
        (self.root / "x.png").write_bytes(b"GIF89a")
        rc, out = self.run_tool("strip", "x.png", "--out", "c", url=False)
        self.assertEqual(rc, 2)
        self.assertIn("not a PNG", out)

    def test_strip_refuses_a_bare_signature_or_cut_png(self):
        # #31: a file that was only the 8-byte PNG signature was "cleaned" and written
        whole = png_with_text()
        for name, data, why in (("sig.png", PNG_SIG, "IHDR"), ("cut.png", whole[:-12], "no IEND"),
                                ("headless.png", PNG_SIG + whole[33:], "IHDR")):
            (self.root / name).write_bytes(data)
            rc, out = self.run_tool("strip", name, "--out", "c", url=False)
            self.assertEqual(rc, 2, out)
            self.assertIn(why, out)
            self.assertFalse((self.root / "c" / name).exists())


# ---- reference pictures a user supplies: metadata that can carry personal data -------------------
GPS = b"GPSLatitude 51.4779 N, GPSLongitude 0.0015 W"   # stands in for a phone photo's EXIF GPS block
EXIF = b"Exif\x00\x00MM\x00\x2a\x00\x00\x00\x08" + GPS
XMP = b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta><rdf:Description photoshop:City='Somewhere'/></x:xmpmeta>"


def seg(marker, body):
    return bytes((0xFF, marker)) + struct.pack(">H", len(body) + 2) + body


def jpeg_with_exif():
    """A JPEG's segment layout (the scan bytes are not a real image: strip_jpeg copies them as they are):
    JFIF, EXIF with GPS, XMP, an ICC profile, IPTC, a comment, the tables and the scan with stuffed 0xFF bytes."""
    head = (seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00") + seg(0xE1, EXIF) + seg(0xE1, XMP)
            + seg(0xE2, b"ICC_PROFILE\x00\x01\x01" + b"icc-bytes") + seg(0xED, b"Photoshop 3.0\x00" + GPS)
            + seg(0xFE, b"taken at home") + seg(0xDB, b"\x00" + bytes(range(64)))
            + seg(0xC0, b"\x08\x00\x10\x00\x10\x01\x01\x11\x00") + seg(0xC4, b"\x00" + bytes(16) + b"\x00"))
    scan = seg(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x12\xff\x00\x34\xff\xd0\x56" + b"\xff\xd9"
    return b"\xff\xd8" + head + scan, scan


def riff(kind, body):
    return kind + struct.pack("<I", len(body)) + body + b"\x00" * (len(body) & 1)


def webp_with_exif():
    """An extended WebP: VP8X (ICC, EXIF and XMP flags), ICC profile, a VP8L image, EXIF with GPS, XMP."""
    vp8x = bytes((0x20 | 0x08 | 0x04, 0, 0, 0)) + b"\x00\x00\x00" + b"\x00\x00\x00"
    image = riff(b"VP8L", b"\x2f\x00\x00\x00\x00\x07")       # odd lengths: the padding byte must survive
    body = (b"WEBP" + riff(b"VP8X", vp8x) + riff(b"ICCP", b"icc-bytes") + image + riff(b"EXIF", EXIF[6:])
            + riff(b"XMP ", XMP))
    return b"RIFF" + struct.pack("<I", len(body)) + body, image


class PictureMetadata(unittest.TestCase):
    def test_png_loses_exif_and_time_keeps_colour_and_pixels(self):
        whole = png_with_text()
        idat = whole[whole.index(b"IDAT") - 4:whole.index(b"IEND") - 4]
        data = (whole[:33] + chunk(b"iCCP", b"icc\x00\x00" + zlib.compress(b"p")) + chunk(b"eXIf", EXIF[6:])
                + chunk(b"tIME", b"\x07\xea\x0b\x05\x0c\x00\x00") + whole[33:])
        out = cl.strip_png(data)
        for gone in (GPS, b"eXIf", b"tIME", b"tEXt", b"iTXt"):
            self.assertNotIn(gone, out)
        self.assertIn(b"iCCP", out)
        self.assertIn(idat, out)

    def test_jpeg_loses_exif_xmp_iptc_and_comments(self):
        data, scan = jpeg_with_exif()
        out = cl.strip_jpeg(data)
        for gone in (GPS, b"Exif", b"xmpmeta", b"Photoshop", b"taken at home"):
            self.assertNotIn(gone, out)
        self.assertIn(b"JFIF", out)
        self.assertIn(b"ICC_PROFILE", out)
        self.assertTrue(out.endswith(scan), "the scan and everything after it is copied byte for byte")
        self.assertEqual(cl.strip_picture(data), out)
        self.assertEqual(cl.strip_jpeg(out), out, "a clean JPEG comes back unchanged")
        for bad in (data[:40], b"\xff\xd8\x00\x00"):
            with self.assertRaises(cl.ToolError):
                cl.strip_jpeg(bad)

    def test_loader_options_reads_both_object_info_styles(self):
        """#197: Dotwork's setup_check read only [[names]]; ComfyUI's V3 nodes answer ["COMBO", {"options": ...}]."""
        info = {"Old": {"input": {"required": {"f": [["a/x.safetensors", "y.safetensors"], {}]}}},
                "V3": {"input": {"required": {"f": ["COMBO", {"options": ["sub\\z.safetensors"]}]}}},
                "Odd": {"input": {"required": {"f": "INT"}}}}
        self.assertEqual(cl.loader_options(info, "Old", "f"), {"x.safetensors", "y.safetensors"})
        self.assertEqual(cl.loader_options(info, "V3", "f"), {"z.safetensors"})
        self.assertEqual(cl.loader_options(info, "Odd", "f"), set())
        self.assertEqual(cl.loader_options(info, "Gone", "f"), set())
        setup = (Path(__file__).resolve().parent / "dotwork" / "setup_check.py").read_text(encoding="utf-8")
        self.assertIn("cl.loader_options(", setup, "Dotwork's setup check reads models through the shared reader")

    def test_webp_loses_exif_and_xmp_and_their_flags(self):
        data, image = webp_with_exif()
        out = cl.strip_webp(data)
        for gone in (GPS, b"EXIF", b"XMP ", b"xmpmeta"):
            self.assertNotIn(gone, out)
        self.assertEqual(out[:4] + out[8:12], b"RIFFWEBP")
        self.assertEqual(struct.unpack("<I", out[4:8])[0], len(out) - 8, "the RIFF size matches the new file")
        self.assertEqual(out[20], 0x20, "VP8X keeps the ICC flag, loses the EXIF and XMP flags")
        self.assertIn(b"ICCP", out)
        self.assertIn(image, out)
        self.assertEqual(cl.strip_picture(data), out)
        with self.assertRaises(cl.ToolError):
            cl.strip_webp(data[:-20])
        with self.assertRaises(cl.ToolError):
            cl.strip_picture(b"GIF89a" + bytes(20))


class ComfyReviewFixes(ComfyLocalExam):
    """#248: same-name outputs collided, long names lost their extension, redirects left localhost, JPEG trailers
    survived, and the log row used backslashes on Windows."""

    def test_same_name_outputs_in_two_subfolders_are_both_kept(self):
        STATE.files = [{"filename": "kit_00001_.png", "subfolder": "front", "type": "output"},
                       {"filename": "kit_00001_.png", "subfolder": "side", "type": "output"}]
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len([p for p in (self.root / "o").glob("*.png")]), 2, out)

    def test_a_long_name_keeps_its_extension(self):
        self.assertTrue(cl.safe_name("x" * 90 + "_ComfyUI_00001_.png").endswith(".png"))
        self.assertLessEqual(len(cl.safe_name("x" * 300 + ".png")), 100)

    def test_a_redirect_is_not_followed(self):
        STATE.redirect = "http://192.0.2.1:9/system_stats"     # TEST-NET: never reached
        rc, out = self.run_tool("check")
        self.assertNotEqual(rc, 0, out)
        self.assertIn("302", out)

    def test_a_jpeg_trailer_is_cut(self):
        data, scan = jpeg_with_exif()
        out = cl.strip_jpeg(data + b"MOTION-PHOTO-TRAILER with GPS")
        self.assertNotIn(b"MOTION-PHOTO", out)
        self.assertTrue(out.endswith(b"\xff\xd9"))

    def test_the_log_row_uses_forward_slashes(self):
        STATE.files = [{"filename": f"kit_0000{i}_.png", "subfolder": "", "type": "output"} for i in range(1, 5)]
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "assets/art", "--log", "--type", "sprite")
        self.assertEqual(rc, 0, out)
        log = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertIn("`assets/art/` (4 files)", log)


class ComfyKimiFixes(unittest.TestCase):
    """#258: a progressive JPEG kept APP and COM segments between its scans."""

    def test_metadata_between_scans_is_dropped(self):
        def seg(marker, body):
            return bytes((0xFF, marker)) + (len(body) + 2).to_bytes(2, "big") + body
        sos = seg(0xDA, b"\x01\x01\x00\x00\x3f\x00")
        data = (b"\xff\xd8" + seg(0xE0, b"JFIF\x00\x01\x01") + sos + b"\x12\xff\x00\x34"
                + seg(0xE1, b"http://ns.adobe.com/xap/1.0/\x00GPS-SECRET") + seg(0xFE, b"comment")
                + sos + b"\x56\xff\xd0\x78" + b"\xff\xd9" + b"TRAILER")
        out = cl.strip_jpeg(data)
        self.assertNotIn(b"GPS-SECRET", out)
        self.assertNotIn(b"comment", out)
        self.assertNotIn(b"TRAILER", out)
        self.assertIn(b"\x12\xff\x00\x34", out)
        self.assertIn(b"\x56\xff\xd0\x78", out)
        self.assertTrue(out.endswith(b"\xff\xd9"))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)

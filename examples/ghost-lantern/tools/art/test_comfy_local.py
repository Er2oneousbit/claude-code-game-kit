#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_comfy_local.py
# Purpose : Exam for comfy_local.py, offline: a stand-in ComfyUI server on 127.0.0.1 (a random port) answers the
#           endpoints the tool uses (/system_stats, /object_info, /upload/image, /prompt, /history, /view), so no
#           GPU, models or ComfyUI install are needed. Checks the local-only rule, workflow formats, --set / --seed /
#           --image, missing nodes, rejected and failed jobs, PNG text-chunk stripping, no overwrite, ASSET_LOG rows,
#           and a non-ASCII prompt end to end.
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
import comfy_local as cl  # noqa: E402

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


class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.prompts, self.uploads = [], []
        self.reject = False          # /prompt answers 400 with node errors
        self.fail = None             # history status error with this exception message
        self.polls_pending = 1       # history polls that return {} before the result
        self.nodes = {n["class_type"] for n in WORKFLOW.values()}
        self.files = [{"filename": "kit_00001_.png", "subfolder": "", "type": "output"},
                      {"filename": "kit_preview.png", "subfolder": "", "type": "temp"}]


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
        if url.path == "/system_stats":
            return self.send(200, {"system": {"comfyui_version": "0.43.0", "python_version": "3.12.12 (main)"},
                                   "devices": [{"name": "cuda:0 Test GPU", "vram_total": 16 * 1024 ** 3,
                                                "vram_free": 12 * 1024 ** 3}]})
        if url.path == "/object_info":
            return self.send(200, {n: {} for n in STATE.nodes})
        if url.path.startswith("/history/"):
            pid = url.path.rsplit("/", 1)[-1]
            if STATE.polls_pending > 0:
                STATE.polls_pending -= 1
                return self.send(200, {})
            if STATE.fail:
                return self.send(200, {pid: {"outputs": {}, "status": {"status_str": "error", "completed": False,
                                       "messages": [["execution_error", {"node_id": "3", "node_type": "KSampler",
                                                                         "exception_message": STATE.fail}]]}}})
            return self.send(200, {pid: {"outputs": {"9": {"images": STATE.files}},
                                         "status": {"status_str": "success", "completed": True, "messages": []}}})
        if url.path == "/view":
            q = urllib.parse.parse_qs(url.query)
            name = q["filename"][0]
            if name.endswith(".png"):
                return self.send(200, png_with_text(), "image/png")
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
            return self.send(200, {"name": "hero.png", "subfolder": "", "type": "input"})
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

    def test_image_upload_points_node_at_it(self):
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o", "--image", "12=hero.png")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(STATE.uploads), 1)
        self.assertEqual(STATE.prompts[0]["prompt"]["12"]["inputs"]["image"], "hero.png")

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

    def test_non_png_output_saved_with_warning(self):
        STATE.files = [{"filename": "walk.gif", "subfolder": "", "type": "output"}]
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 0, out)
        self.assertIn("[warn] walk.gif", out)

    def test_hostile_file_name_stays_in_out(self):
        STATE.files = [{"filename": "../../evil.png", "subfolder": "", "type": "output"}]
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "o")
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "o" / "evil.png").exists())
        self.assertFalse((self.root.parent / "evil.png").exists())

    # ---- logging
    def test_log_row_and_evidence_non_ascii_prompt(self):
        prompt = "Í lamplighter \u201cold\u201d | brass"
        rc, out = self.run_tool("run", "--workflow", "wf.api.json", "--out", "assets/art", "--log",
                                "--set", f"Prompt.text={prompt}", "--type", "sprite", "--seed", "3")
        self.assertEqual(rc, 0, out)
        log = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertIn("| A-0001 | sprite | `assets/art/kit_00001_.png` | ComfyUI (local)", log)
        self.assertIn("pre-generated", log)
        self.assertIn("Í lamplighter", log)
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

    def test_strip_refuses_non_png(self):
        (self.root / "x.png").write_bytes(b"GIF89a")
        rc, out = self.run_tool("strip", "x.png", "--out", "c", url=False)
        self.assertEqual(rc, 2)
        self.assertIn("not a PNG", out)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)

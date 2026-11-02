#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_local_sfx.py
# Purpose : Exam for local_sfx.py, offline: a stand-in ComfyUI on 127.0.0.1 (random port) answers the endpoints
#           the tool uses and serves real FLAC files (written here, with a tag block that carries a local path,
#           as ComfyUI's Save Audio does). Checks the preflight messages, the Stable Audio 3 graph, ranking
#           (clean beats clipped, silent is dropped), trimming and normalizing, loops, mono, failed jobs, no
#           rendering when outputs exist, the .gen.json record, ASSET_LOG rows, and that no tag text reaches a WAV.
# Usage   : python tools/audio/wavesmith/test_local_sfx.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import hashlib
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flacfile  # noqa: E402
import local_sfx  # noqa: E402
from test_flacfile import BitWriter  # noqa: E402
from wavfile import read_wav_channels, stats  # noqa: E402

RATE = 44100
EMBEDDED_PATH = "C:/Users/you/ComfyUI/models/checkpoints/stable_audio_3_medium.safetensors"
LOG = """# Asset Log
| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | | | | | | | no | no | 2026-01-01 | |
## Rules
"""


# ---- a minimal FLAC writer (VERBATIM subframes) -------------------------------------------------------------
def utf8_number(n):
    if n < 0x80:
        return bytes([n])
    if n < 0x800:
        return bytes([0xC0 | (n >> 6), 0x80 | (n & 0x3F)])
    return bytes([0xE0 | (n >> 12), 0x80 | ((n >> 6) & 0x3F), 0x80 | (n & 0x3F)])


def make_flac(chans, tags=True):
    """16-bit FLAC of int channel lists, one VERBATIM frame per 4096 samples, MD5 set, plus a ComfyUI-like tag."""
    total = len(chans[0])
    md5 = hashlib.md5()
    for frame in zip(*chans):
        md5.update(struct.pack("<" + "h" * len(chans), *frame))
    packed = (RATE << 44) | ((len(chans) - 1) << 41) | (15 << 36) | total
    info = struct.pack(">HH", 4096, 4096) + b"\0" * 6 + packed.to_bytes(8, "big") + md5.digest()
    comment = ("prompt=" + json.dumps({"ckpt_name": EMBEDDED_PATH})).encode()
    body = struct.pack("<I", 4) + b"Lavf" + struct.pack("<I", 1) + struct.pack("<I", len(comment)) + comment
    out = b"fLaC" + bytes([0x00 if tags else 0x80, 0, 0, len(info)]) + info
    if tags:
        out += bytes([0x84]) + len(body).to_bytes(3, "big") + body
    for number, start in enumerate(range(0, total, 4096)):
        block = chans[0][start:start + 4096]
        head = BitWriter()
        head.put(14, 0x3FFE); head.put(1, 0); head.put(1, 0)
        head.put(4, 7); head.put(4, 9)                       # 16-bit block size at the end, 44.1 kHz
        head.put(4, len(chans) - 1); head.put(3, 4); head.put(1, 0)
        hb = head.bytes() + utf8_number(number) + struct.pack(">H", len(block) - 1)
        fr = BitWriter()
        fr.value, fr.n = int.from_bytes(hb + bytes([flacfile.crc8(hb)]), "big"), (len(hb) + 1) * 8
        for ch in chans:
            fr.put(1, 0); fr.put(6, 1); fr.put(1, 0)          # VERBATIM
            for s in ch[start:start + 4096]:
                fr.put(16, s)
        fr.pad()
        fb = fr.bytes()
        out += fb + flacfile.crc16(fb).to_bytes(2, "big")
    return out


def lcg_noise(seed, n, amp):
    x, out = seed, []
    for _ in range(n):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        out.append(((x >> 8) % (2 * amp + 1)) - amp)
    return out


def burst(seed):
    """0.1 s silence, 0.4 s decaying noise at about -6 dBFS, 1.0 s silence: a typical one-shot take."""
    n = int(0.4 * RATE)
    noise = [v * (n - i) // n for i, v in enumerate(lcg_noise(seed, n, 16000))]
    ch = [0] * int(0.1 * RATE) + noise + [0] * RATE
    return [ch, [v // 2 for v in ch]]


def clipped(seed):
    sq = [32767 if (i // 50) % 2 else -32768 for i in range(int(0.4 * RATE))]
    ch = [0] * int(0.1 * RATE) + sq + [0] * RATE
    return [ch, list(ch)]


def silent(seed):
    return [[0] * int(1.5 * RATE)] * 2


def bed(seed):
    """3 s steady noise bed then 0.5 s of silence (the tail Stable Audio leaves): loop material."""
    ch = lcg_noise(seed, 3 * RATE, 6000) + [0] * (RATE // 2)
    return [ch, lcg_noise(seed + 1, 3 * RATE, 6000) + [0] * (RATE // 2)]


class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.prompts = []
        self.by_seed = {}            # seed -> signal function, or "error"
        self.default = burst
        self.nodes = set(local_sfx.AUDIO_NODES) | {"KSampler", "CLIPTextEncode"}
        self.ckpts = list(m["ckpt"] for m in local_sfx.MODELS.values())
        self.encoders = [local_sfx.TEXT_ENCODER]


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

    def seed_of(self, pid):
        return STATE.prompts[int(pid.split("-")[1])]["prompt"]["6"]["inputs"]["seed"]

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/system_stats":
            return self.send(200, {"system": {"comfyui_version": "0.43.0", "python_version": "3.12.12"},
                                   "devices": [{"name": "cuda:0 Test GPU", "vram_total": 16 << 30, "vram_free": 12 << 30}]})
        if url.path == "/object_info":
            info = {n: {} for n in STATE.nodes}
            if "CheckpointLoaderSimple" in info:      # the old combo shape
                info["CheckpointLoaderSimple"] = {"input": {"required": {"ckpt_name": [STATE.ckpts, {}]}}}
            if "CLIPLoader" in info:                  # the new combo shape
                info["CLIPLoader"] = {"input": {"required": {"clip_name": ["COMBO", {"options": STATE.encoders}]}}}
            return self.send(200, info)
        if url.path.startswith("/history/"):
            pid = url.path.rsplit("/", 1)[-1]
            if STATE.by_seed.get(self.seed_of(pid)) == "error":
                return self.send(200, {pid: {"outputs": {}, "status": {"status_str": "error", "completed": False,
                                       "messages": [["execution_error", {"node_id": "6", "node_type": "KSampler",
                                                                         "exception_message": "CUDA error"}]]}}})
            return self.send(200, {pid: {"outputs": {"8": {"audio": [{"filename": f"{pid}.flac", "subfolder": "local_sfx",
                                                                      "type": "output"}]}},
                                         "status": {"status_str": "success", "completed": True, "messages": []}}})
        if url.path == "/queue":
            return self.send(200, {"queue_running": [], "queue_pending": []})
        if url.path == "/view":
            pid = urllib.parse.parse_qs(url.query)["filename"][0][:-5]
            seed = self.seed_of(pid)
            return self.send(200, make_flac(STATE.by_seed.get(seed, STATE.default)(seed)), "audio/flac")
        self.send(404, {"error": "no such path in the exam"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/prompt":
            STATE.prompts.append(json.loads(body.decode("utf-8")))
            return self.send(200, {"prompt_id": f"p-{len(STATE.prompts) - 1}", "number": 1, "node_errors": {}})
        self.send(404, {"error": "no such path"})


class LocalSfxExam(unittest.TestCase):
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
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def run_tool(self, *argv):
        args = [str(a) for a in argv] + ["--url", self.url]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = local_sfx.main(args)
        return rc, out.getvalue() + err.getvalue()

    def make(self, *extra):
        return self.run_tool("make", "a wooden door creaking", "--seconds", 0.4, "--out", "door.wav", *extra)

    # ---- preflight
    def test_check_ok(self):
        rc, out = self.run_tool("check")
        self.assertEqual(rc, 0, out)
        self.assertIn("ComfyUI 0.43.0", out)

    def test_check_names_missing_checkpoint_and_source(self):
        STATE.ckpts = []
        rc, out = self.run_tool("check")
        self.assertEqual(rc, 2, out)
        self.assertIn("stable_audio_3_medium.safetensors", out)
        self.assertIn(local_sfx.MODEL_SOURCE, out)

    def test_check_names_missing_text_encoder(self):
        STATE.encoders = []
        rc, out = self.run_tool("check", "--model", "small-sfx")
        self.assertEqual(rc, 2, out)
        self.assertIn(local_sfx.TEXT_ENCODER, out)

    def test_old_comfyui_without_audio_nodes(self):
        STATE.nodes.discard("VAEDecodeAudio")
        rc, out = self.run_tool("check")
        self.assertEqual(rc, 2, out)
        self.assertIn("VAEDecodeAudio", out)

    # ---- make
    def test_ranks_clean_over_clipped_and_drops_silent(self):
        STATE.by_seed = {1: clipped, 2: burst, 3: silent}
        rc, out = self.make("--variants", 3, "--keep", 2)
        self.assertEqual(rc, 0, out)
        best = json.loads((self.root / "door_1.gen.json").read_text(encoding="utf-8"))
        second = json.loads((self.root / "door_2.gen.json").read_text(encoding="utf-8"))
        self.assertEqual((best["seed"], second["seed"]), (2, 1), out)
        self.assertGreater(best["score"], second["score"])
        self.assertTrue(any("clipped" in r for r in second["checks"]))
        self.assertIn("near-silent", out)
        self.assertEqual((best["rank"], best["of_takes"], best["model"]), (1, 3, "medium"))
        self.assertIn("Stability AI Community License", best["license"])
        self.assertEqual(best["prompt"], "a wooden door creaking")

    def test_trimmed_normalized_and_no_tag_text(self):
        rc, out = self.make("--variants", 1, "--keep", 1)
        self.assertEqual(rc, 0, out)
        wav = self.root / "door.wav"
        samples, rate, loop, channels = read_wav_channels(wav)
        st = stats(samples[0::2], rate)
        self.assertEqual((rate, channels, loop), (RATE, 2, None))
        self.assertAlmostEqual(st["seconds"], 0.4 + local_sfx.LEAD_KEEP_S + local_sfx.TAIL_KEEP_S, delta=0.03)
        self.assertAlmostEqual(st["peak_dbfs"], -3.0, delta=0.2)
        self.assertLess(abs(samples[0]) + abs(samples[-1]), 0.01, "fades missing")
        for f in (wav, wav.with_suffix(".gen.json")):
            self.assertNotIn(b"C:/Users", f.read_bytes(), f"{f.name} carries the embedded path")

    def test_graph_model_seeds_and_minimum_length(self):
        rc, out = self.make("--variants", 2, "--keep", 1, "--seed", 40, "--model", "small-sfx")
        self.assertEqual(rc, 0, out)
        graphs = [p["prompt"] for p in STATE.prompts]
        self.assertEqual([g["6"]["inputs"]["seed"] for g in graphs], [40, 41])
        self.assertEqual(graphs[0]["1"]["inputs"]["ckpt_name"], "stable_audio_3_small_sfx.safetensors")
        self.assertEqual(graphs[0]["5"]["inputs"]["seconds"], local_sfx.MIN_GEN_S)
        self.assertEqual(graphs[0]["3"]["inputs"]["text"], "a wooden door creaking")
        self.assertEqual(graphs[0]["6"]["inputs"]["steps"], 8)

    def test_loop_has_seamless_loop_points(self):
        STATE.default = bed
        rc, out = self.run_tool("make", "steady rain on a roof", "--seconds", 2.5, "--loop", "--crossfade", 0.5,
                                "--variants", 1, "--keep", 1, "--out", "rain.wav")
        self.assertEqual(rc, 0, out)
        samples, rate, loop, channels = read_wav_channels(self.root / "rain.wav")
        st = stats(samples[0::2], rate, loop)
        self.assertIsNotNone(loop)
        self.assertTrue(st["loop_seam_ok"], st)
        self.assertAlmostEqual(st["seconds"], 2.5, delta=0.001, msg="a loop is exactly --seconds long")
        self.assertAlmostEqual(st["peak_dbfs"], -3.0, delta=0.2, msg="normalize after the crossfade, not before")
        self.assertEqual(STATE.prompts[0]["prompt"]["5"]["inputs"]["seconds"], 2.5 + 0.5 + local_sfx.LOOP_MARGIN_S,
                         "a loop renders its length + crossfade + margin for the silent tail")

    def test_clean_ties_go_to_the_requested_length(self):
        def short(seed):                      # 0.15 s of sound: further from --seconds 0.4 than burst's 0.4 s
            n = int(0.15 * RATE)
            ch = [0] * int(0.1 * RATE) + [v * (n - i) // n for i, v in enumerate(lcg_noise(seed, n, 16000))] + [0] * RATE
            return [ch, list(ch)]
        STATE.by_seed = {1: short, 2: burst}
        rc, out = self.make("--variants", 2, "--keep", 2)
        self.assertEqual(rc, 0, out)
        best = json.loads((self.root / "door_1.gen.json").read_text(encoding="utf-8"))
        self.assertEqual((best["seed"], best["score"]), (2, 100.0), "both clean: the 0.4 s take should win")

    def test_mono(self):
        rc, out = self.make("--variants", 1, "--keep", 1, "--mono")
        self.assertEqual(rc, 0, out)
        self.assertEqual(read_wav_channels(self.root / "door.wav")[3], 1)

    def test_failed_take_skipped_and_all_failed_is_exit_1(self):
        STATE.by_seed = {1: "error"}
        rc, out = self.make("--variants", 2, "--keep", 1)
        self.assertEqual(rc, 0, out)
        self.assertIn("[FAIL] seed 1", out)
        self.assertEqual(json.loads((self.root / "door.gen.json").read_text(encoding="utf-8"))["seed"], 2)
        STATE.by_seed = {1: silent, 2: "error"}
        rc, out = self.run_tool("make", "x", "--seconds", 1, "--variants", 2, "--keep", 1, "--out", "x.wav")
        self.assertEqual(rc, 1, out)
        self.assertIn("no usable take", out)
        self.assertFalse((self.root / "x.wav").exists())

    def test_existing_output_stops_before_any_render(self):
        (self.root / "door_2.wav").write_bytes(b"keep me")
        rc, out = self.make("--variants", 3, "--keep", 3)
        self.assertEqual(rc, 2, out)
        self.assertIn("nothing was rendered", out)
        self.assertEqual(STATE.prompts, [])
        rc, out = self.make("--variants", 3, "--keep", 3, "--overwrite")
        self.assertEqual(rc, 0, out)

    def test_dry_run_sends_nothing(self):
        rc, out = self.make("--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn('"KSampler"', out)
        self.assertEqual(STATE.prompts, [])

    def test_log_row_and_evidence(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        rc, out = self.make("--variants", 2, "--keep", 2, "--log")
        self.assertEqual(rc, 0, out)
        log = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertIn("| A-0001 | sfx | `door_1.wav`, `door_2.wav` |", log)   # fills the template's empty row
        self.assertIn("Stability AI Community License", log)
        evidence = (self.root / "docs" / "licenses" / "A-0001.txt").read_text(encoding="utf-8")
        self.assertIn("seed 1", evidence)
        self.assertIn("a wooden door creaking", evidence)

    def test_log_without_asset_log_stops_before_render(self):
        rc, out = self.make("--log")
        self.assertEqual(rc, 2, out)
        self.assertEqual(STATE.prompts, [])

    def test_usage_errors(self):
        for args in (("make", "x", "--seconds", 1, "--out", "x.wav", "--keep", 4, "--variants", 3),
                     ("make", "x", "--seconds", 1, "--out", "x.mp3"),
                     ("make", "  ", "--seconds", 1, "--out", "x.wav"),
                     ("make", "x", "--seconds", 500, "--out", "x.wav"),
                     ("make", "x", "--seconds", 1, "--out", "x.wav", "--rank", "clap")):
            rc, out = self.run_tool(*args)
            self.assertEqual(rc, 2, f"{args}: {out}")
            self.assertNotIn("Traceback", out)
        self.assertEqual(STATE.prompts, [])

    def test_server_down(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = local_sfx.main(["check", "--url", "http://127.0.0.1:9"])
        self.assertEqual(rc, 2)
        self.assertIn("no ComfyUI answering", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=1)

#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_local_tts.py
# Purpose : Exam for local_tts.py, offline: a stand-in worker (a small standard-library script written by this
#           test) answers the JSON-lines protocol instead of the real GPU worker, so no torch, models or GPU are
#           needed. Checks the environment checks (missing env, no torch, no CUDA), design and say with voice
#           provenance, the real-voice rule, post-processing (trim, pitch, ring, normalize), a bad JSON reply, a
#           worker crash, a timeout (and that the worker is stopped), an early stop, no work when outputs exist,
#           ASSET_LOG rows, and that the real worker parses as Python 3.8.
# Usage   : python tools/audio/wavesmith/test_local_tts.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import ast
import contextlib
import io
import json
import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_tts  # noqa: E402
from wavfile import read_wav, stats  # noqa: E402

FAKE_WORKER = r'''
import json, math, os, sys, time, wave
mode = os.environ.get("FAKE_TTS_MODE", "ok")
req = json.loads(sys.stdin.read())
with open(os.environ["FAKE_TTS_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(req) + "\n")
def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()
def tone(path, hz, seconds=0.6, rate=24000):
    # 0.2 s silence, a tone at about -6 dBFS, 0.5 s silence: what a TTS take looks like to post-processing
    n = int(seconds * rate)
    data = [0] * int(0.2 * rate) + [int(16000 * math.sin(2 * math.pi * hz * i / rate)) for i in range(n)] + [0] * int(0.5 * rate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(v.to_bytes(2, "little", signed=True) for v in data))
    return len(data) / rate
sys.stderr.write("[worker] fake worker log line\n")
if mode == "notorch":
    out({"ok": False, "missing": "torch", "error": "cannot import torch: No module named 'torch'"}); sys.exit(2)
if mode == "nocuda":
    out({"ok": False, "missing": "cuda", "torch": "2.9.0+cpu", "error": "torch 2.9.0+cpu sees no CUDA GPU"}); sys.exit(2)
if mode == "badjson":
    sys.stdout.write("Loading weights 100%\n"); sys.stdout.flush(); sys.exit(0)
if mode == "crash":
    sys.stderr.write("Traceback: CUDA out of memory\n"); sys.exit(3)
if mode == "hang":
    time.sleep(4)                       # still alive after 4 s? then local_tts failed to stop it: leave a marker
    open(os.environ["FAKE_TTS_LOG"] + ".survived", "w").close(); sys.exit(0)
if mode == "error":
    out({"error": "RuntimeError: CUDA error: device-side assert"}); sys.exit(1)
if req["op"] == "check":
    out({"ok": True, "torch": "2.14.1+cu130", "cuda": "13.0", "gpu": "Test GPU", "qwen_tts": "0.1.1", "python": "3.12.12"})
elif req["op"] == "design":
    out({"file": req["out"], "seconds": tone(req["out"], 220), "wall": 0.1})
elif req["op"] == "say":
    for i, line in enumerate(req["lines"]):
        if mode == "short" and i == 1:
            sys.exit(0)
        path = req["outdir"] + "/" + line["id"] + ".wav"
        long = mode == "runaway" and i == 1          # this take runs to its cap: max_tokens / 12 Hz seconds
        secs = tone(path, 300 + 50 * i, seconds=line["max_tokens"] / 12 - 0.7 if long else 0.6)
        out({"id": line["id"], "file": path, "seconds": secs, "wall": 0.1})
    out({"done": True})
'''


class LocalTtsExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.worker = self.root / "fake_worker.py"
        self.worker.write_text(FAKE_WORKER, encoding="utf-8")
        self.log = self.root / "requests.jsonl"
        self.env_before = dict(os.environ)
        os.environ.update(FAKE_TTS_LOG=str(self.log), FAKE_TTS_MODE="ok")
        os.environ.pop(local_tts.PYTHON_ENV, None)
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)
        os.environ.clear()
        os.environ.update(self.env_before)
        self.tmp.cleanup()

    def run_tool(self, *argv, env_python=True):
        args = [str(a) for a in argv] + ["--worker", str(self.worker)]
        if env_python:
            args += ["--python", sys.executable]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = local_tts.main(args)
        return rc, out.getvalue() + err.getvalue()

    def requests(self):
        return [json.loads(l) for l in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []

    def design(self, name="baker_ref.wav"):
        rc, out = self.run_tool("design", "warm cheerful baker, slightly husky", "--out", name)
        self.assertEqual(rc, 0, out)
        return self.root / name

    # ---- environment
    def test_check_prints_versions(self):
        rc, out = self.run_tool("check")
        self.assertEqual(rc, 0, out)
        for part in ("torch 2.14.1+cu130", "CUDA 13.0", "qwen-tts 0.1.1", "Test GPU"):
            self.assertIn(part, out)

    def test_missing_environment_names_the_fix(self):
        rc, out = self.run_tool("check", env_python=False)
        self.assertEqual(rc, 2, out)
        self.assertIn(local_tts.PYTHON_ENV, out)
        rc, out = self.run_tool("check", "--python", self.root / "no" / "python.exe", env_python=False)
        self.assertEqual(rc, 2, out)
        self.assertIn("does not exist", out)

    def test_env_variable_is_used(self):
        os.environ[local_tts.PYTHON_ENV] = sys.executable
        rc, out = self.run_tool("check", env_python=False)
        self.assertEqual(rc, 0, out)

    def test_no_torch_and_no_cuda_are_named(self):
        for mode, word in (("notorch", "(torch)"), ("nocuda", "(cuda)")):
            os.environ["FAKE_TTS_MODE"] = mode
            rc, out = self.run_tool("check")
            self.assertEqual(rc, 2, out)
            self.assertIn(word, out)
            self.assertIn("Fix:", out)
            rc, out = self.run_tool("design", "a voice", "--out", "x.wav")
            self.assertEqual(rc, 2, f"design must name it too: {out}")

    # ---- design and say
    def test_design_writes_reference_with_provenance(self):
        ref = self.design()
        meta = json.loads(ref.with_suffix(".gen.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["op"], meta["voice"]["origin"]), ("design", "designed from text"))
        self.assertEqual(meta["ref_text"], local_tts.REF_TEXT)
        self.assertIn("Apache-2.0", meta["license"])
        req = self.requests()[-1]
        self.assertEqual((req["op"], req["model"], req["text"]), ("design", local_tts.DESIGN_MODEL, local_tts.REF_TEXT))
        self.assertEqual(req["persona"], "warm cheerful baker, slightly husky")

    def test_say_lines_in_designed_voice(self):
        ref = self.design()
        (self.root / "dialog.txt").write_text("Fresh bread!\n\nTwo coins, please.\nCome back soon.\n", encoding="utf-8")
        rc, out = self.run_tool("say", "--ref", ref, "--lines", "dialog.txt", "--out", "baker.wav", "--seed", 7)
        self.assertEqual(rc, 0, out)
        req = self.requests()[-1]
        self.assertEqual(req["ref_text"], local_tts.REF_TEXT, "a designed reference carries its own words")
        self.assertEqual([l["text"] for l in req["lines"]], ["Fresh bread!", "Two coins, please.", "Come back soon."])
        self.assertEqual(req["model"], local_tts.CLONE_MODELS["1.7b"])
        metas = [json.loads((self.root / f"baker_{n}.gen.json").read_text(encoding="utf-8")) for n in (1, 2, 3)]
        self.assertEqual([m["seed"] for m in metas], [7, 8, 9])
        self.assertEqual(metas[1]["text"], "Two coins, please.")
        self.assertEqual(metas[0]["voice"]["origin"], "designed from text")
        self.assertIn("baker", metas[0]["voice"]["persona"])

    def test_post_trims_and_normalizes(self):
        ref = self.design()
        rc, out = self.run_tool("say", "--ref", ref, "Hello.", "--out", "hi.wav")
        self.assertEqual(rc, 0, out)
        samples, rate, _ = read_wav(self.root / "hi.wav")
        st = stats(samples, rate)
        self.assertAlmostEqual(st["seconds"], 0.6 + local_tts.LEAD_KEEP_S + local_tts.TAIL_KEEP_S, delta=0.01)
        self.assertAlmostEqual(st["peak_dbfs"], -3.0, delta=0.1)
        self.assertLess(abs(samples[0]) + abs(samples[-1]), 0.01)

    def test_pitch_down_is_longer_and_ring_changes_sound(self):
        ref = self.design()
        self.run_tool("say", "--ref", ref, "Who disturbs me", "--out", "plain.wav")
        self.run_tool("say", "--ref", ref, "Who disturbs me", "--out", "low.wav", "--pitch", -5)
        self.run_tool("say", "--ref", ref, "Who disturbs me", "--out", "ring.wav", "--ring-hz", 40)
        plain, low = (stats(read_wav(self.root / f)[0], 24000)["seconds"] for f in ("plain.wav", "low.wav"))
        self.assertAlmostEqual(low / plain, 2 ** (5 / 12), delta=0.03)
        self.assertNotEqual((self.root / "plain.wav").read_bytes(), (self.root / "ring.wav").read_bytes())
        meta = json.loads((self.root / "low.gen.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["post"]["pitch_semitones"], -5.0)

    def test_gen_json_never_holds_an_absolute_path(self):
        # .gen.json files ship next to the game's assets: a full path would leak the user's folder names
        ref = self.design("voices/baker_ref.wav")
        rc, out = self.run_tool("say", "--ref", ref.resolve(), "Hi.", "--out", "inside.wav")    # absolute, in project
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads((self.root / "inside.gen.json").read_text(encoding="utf-8"))["voice"]["reference"],
                         "voices/baker_ref.wav")
        with tempfile.TemporaryDirectory() as other:                                        # outside the project
            far = Path(other) / "far_ref.wav"
            far.write_bytes(ref.read_bytes())
            far.with_suffix(".gen.json").write_bytes(ref.with_suffix(".gen.json").read_bytes())
            rc, out = self.run_tool("say", "--ref", far, "Hi.", "--out", "outside.wav")
            self.assertEqual(rc, 0, out)
        for f in self.root.glob("*.gen.json"):
            text = f.read_text(encoding="utf-8")
            self.assertNotIn(str(self.root.resolve()).replace("\\", "/"), text, f.name)
            self.assertNotIn(str(Path(other).resolve()).replace("\\", "/"), text, f.name)
        self.assertEqual(json.loads((self.root / "outside.gen.json").read_text(encoding="utf-8"))["voice"]["reference"],
                         "far_ref.wav")

    def test_recorded_reference_needs_origin_and_words(self):
        rec = self.root / "my_voice.wav"
        rec.write_bytes(self.design().read_bytes())          # a WAV without local_tts provenance
        before = len(self.requests())
        rc, out = self.run_tool("say", "--ref", rec, "Hi.", "--out", "a.wav")
        self.assertEqual(rc, 2, out)
        self.assertIn("written permission", out)
        self.assertEqual(len(self.requests()), before, "nothing reaches the worker")
        rc, out = self.run_tool("say", "--ref", rec, "Hi.", "--out", "a.wav", "--ref-text", "Testing one two",
                                "--ref-origin", "self")
        self.assertEqual(rc, 0, out)
        meta = json.loads((self.root / "a.gen.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["voice"]["origin"], local_tts.ORIGINS["self"])
        self.assertEqual(self.requests()[-1]["ref_text"], "Testing one two")

    # ---- failures
    def test_bad_json_reply_is_exit_1(self):
        ref = self.design()
        os.environ["FAKE_TTS_MODE"] = "badjson"
        rc, out = self.run_tool("say", "--ref", ref, "Hi.", "--out", "a.wav")
        self.assertEqual(rc, 1, out)
        self.assertIn("not JSON", out)

    def test_worker_crash_shows_its_last_words(self):
        ref = self.design()
        os.environ["FAKE_TTS_MODE"] = "crash"
        rc, out = self.run_tool("say", "--ref", ref, "Hi.", "--out", "a.wav")
        self.assertEqual(rc, 1, out)
        self.assertIn("exited with code 3", out)
        self.assertIn("CUDA out of memory", out)
        self.assertFalse((self.root / "a.wav").exists())

    def test_error_reply_is_exit_1(self):
        ref = self.design()
        os.environ["FAKE_TTS_MODE"] = "error"
        rc, out = self.run_tool("say", "--ref", ref, "Hi.", "--out", "a.wav")
        self.assertEqual(rc, 1, out)
        self.assertIn("device-side assert", out)

    def test_timeout_stops_the_worker(self):
        ref = self.design()
        os.environ["FAKE_TTS_MODE"] = "hang"
        start = time.monotonic()
        rc, out = self.run_tool("say", "--ref", ref, "Hi.", "--out", "a.wav", "--timeout", 1.5)
        self.assertEqual(rc, 1, out)
        self.assertIn("no answer within 2 s", out)
        self.assertLess(time.monotonic() - start, 4, "local_tts must not wait the hung worker out")
        time.sleep(max(0.0, start + 6 - time.monotonic()))          # past the worker's 4 s nap
        self.assertFalse(Path(str(self.log) + ".survived").exists(), "the hung worker was left running")

    def test_early_stop_is_reported(self):
        ref = self.design()
        os.environ["FAKE_TTS_MODE"] = "short"
        (self.root / "d.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
        rc, out = self.run_tool("say", "--ref", ref, "--lines", "d.txt", "--out", "x.wav")
        self.assertEqual(rc, 1, out)
        self.assertIn("1 of 3", out)

    def test_existing_output_stops_before_the_worker(self):
        ref = self.design()
        (self.root / "b_2.wav").write_bytes(b"keep")
        (self.root / "d.txt").write_text("one\ntwo\n", encoding="utf-8")
        before = len(self.requests())
        rc, out = self.run_tool("say", "--ref", ref, "--lines", "d.txt", "--out", "b.wav")
        self.assertEqual(rc, 2, out)
        self.assertEqual(len(self.requests()), before)
        self.assertEqual((self.root / "b_2.wav").read_bytes(), b"keep")

    def test_log_row_records_voice_origin(self):
        ref = self.design()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "ASSET_LOG.md").write_text(
            "# Asset Log\n| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) "
            "| AI-assisted? | Modified? | Date added | Notes |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
            "| A-0001 | | | | | | | no | no | 2026-01-01 | |\n## Rules\n", encoding="utf-8")
        rc, out = self.run_tool("say", "--ref", ref, "Hello.", "--out", "hi.wav", "--log")
        self.assertEqual(rc, 0, out)
        log = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertIn("| A-0001 | voice | `hi.wav` | Qwen3-TTS (local)", log)
        self.assertIn("voice: designed from text", log)
        self.assertIn("Apache-2.0", log)

    def test_usage_errors(self):
        ref = self.design()
        for args in (("say", "--ref", ref, "--out", "a.wav"),
                     ("say", "--ref", ref, "hi", "--lines", "x.txt", "--out", "a.wav"),
                     ("say", "--ref", "missing.wav", "hi", "--out", "a.wav"),
                     ("say", "--ref", ref, "hi", "--out", "a.wav", "--pitch", 30),
                     ("say", "--ref", ref, "hi", "--out", "a.wav", "--ring-mix", 2),
                     ("design", "  ", "--out", "b.wav"),
                     ("say", "--ref", ref, "hi", "--out", "a.wav", "--language", "Klingon"),
                     ("design", "a calm voice", "--out", "b.wav", "--language", "Dutch")):
            rc, out = self.run_tool(*args)
            self.assertEqual(rc, 2, f"{args}: {out}")
            self.assertNotIn("Traceback", out)
        rc, out = self.run_tool("say", "--ref", ref, "hi", "--out", "a.wav", "--language", "Klingon")
        self.assertIn("is not one the model speaks: Chinese, English, Japanese", out)

    def test_a_take_that_never_ends_is_capped_and_not_kept(self):
        ref = self.design()
        lines = self.root / "lines.txt"
        lines.write_text("Fresh bread!\nTwo coins a loaf.\nCome back soon.\n", encoding="utf-8")
        os.environ["FAKE_TTS_MODE"] = "runaway"
        rc, out = self.run_tool("say", "--ref", ref, "--lines", lines, "--out", "vo.wav")
        self.assertEqual(rc, 1, out)
        say = [r for r in self.requests() if r["op"] == "say"][-1]
        caps = [line["max_tokens"] for line in say["lines"]]
        self.assertEqual(caps, [math.ceil(local_tts.line_cap_s(t) * 12) for t in
                                ("Fresh bread!", "Two coins a loaf.", "Come back soon.")])
        self.assertTrue((self.root / "vo_1.wav").exists() and (self.root / "vo_3.wav").exists())
        self.assertFalse((self.root / "vo_2.wav").exists())
        self.assertIn("vo_2.wav not written: the take ran to the 6 s cap without ending", out)
        self.assertIn("2 of 3 line(s) written", out)
        self.assertGreater(local_tts.line_cap_s("x" * 20, "Japanese"), local_tts.line_cap_s("x" * 20, "German"))

    def test_language_names_are_the_models_spelling(self):
        self.assertEqual(local_tts.language_name(" german "), "German")
        self.assertEqual(local_tts.language_name("JAPANESE"), "Japanese")
        self.assertEqual(len(local_tts.LANGUAGES), 10)
        with self.assertRaises(local_tts.ToolError):
            local_tts.language_name("Esperanto")

    def test_real_worker_keeps_the_protocol_clean_of_library_output(self):
        # The real local_tts_worker.py in a real separate environment (a throwaway venv, no pip) whose stub torch and
        # qwen_tts print to stdout at import, from Python and natively (qwen-tts really prints a flash-attn banner
        # there; the live check found it). -I keeps the worker's own folder off sys.path, so stubs go in site-packages.
        import subprocess
        import venv
        venv.create(self.root / "stubvenv", with_pip=False)
        py = next(p for p in (self.root / "stubvenv" / "Scripts" / "python.exe", self.root / "stubvenv" / "bin" / "python")
                  if p.exists())
        site = Path(subprocess.run([str(py), "-I", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                                   capture_output=True, encoding="utf-8", errors="replace", check=True).stdout.strip())
        env = site
        (env / "qwen_tts").mkdir(parents=True)
        (env / "torch.py").write_text(
            "import os\nprint('********')\nos.write(1, b'native banner on fd 1\\n')\n__version__ = '9.9.9+stub'\n"
            "class version:\n    cuda = '13.0'\nbfloat16 = 'bf16'\n"
            "class cuda:\n    is_available = staticmethod(lambda: True)\n"
            "    get_device_name = staticmethod(lambda i: 'Stub GPU')\n    manual_seed_all = staticmethod(lambda s: None)\n"
            "def manual_seed(s):\n    pass\n", encoding="utf-8")
        (env / "qwen_tts" / "__init__.py").write_text(
            "import math\nprint('********')\nprint('Warning: flash-attn is not installed.')\n__version__ = '0.0.stub'\n"
            "class Qwen3TTSModel:\n"
            "    @classmethod\n    def from_pretrained(cls, *a, **k):\n        print('loading weights...')\n        return cls()\n"
            "    def generate_voice_design(self, text, instruct, language):\n"
            "        return [[0.0] * 2400 + [0.5 * math.sin(i / 5) for i in range(12000)] + [0.0] * 2400], 24000\n"
            "    def create_voice_clone_prompt(self, ref_audio, ref_text):\n        return {'ref': ref_audio}\n"
            "    def generate_voice_clone(self, text, language, voice_clone_prompt, **kwargs):\n"
            "        print('generating', text)\n"
            "        return [[0.0] * 1200 + [0.4 * math.sin(i / 7) for i in range(9600)] + [0.0] * 1200], 24000\n",
            encoding="utf-8")
        self.worker = Path(local_tts.__file__).parent / "local_tts_worker.py"
        rc, out = self.run_tool("check", "--python", py, env_python=False)
        self.assertEqual(rc, 0, out)
        self.assertIn("torch 9.9.9+stub", out)
        self.assertIn("qwen-tts 0.0.stub", out)
        rc, out = self.run_tool("design", "a gruff smith", "--out", "ref.wav", "--python", py, env_python=False)
        self.assertEqual(rc, 0, out)
        rc, out = self.run_tool("say", "--ref", "ref.wav", "Bring me iron.", "--out", "line.wav", "--python", py,
                                env_python=False)
        self.assertEqual(rc, 0, out)
        self.assertAlmostEqual(stats(read_wav(self.root / "line.wav")[0], 24000)["peak_dbfs"], -3.0, delta=0.1)

    def test_real_worker_is_python_38_syntax_and_stdout_clean(self):
        src = (Path(local_tts.__file__).parent / "local_tts_worker.py").read_text(encoding="utf-8")
        tree = ast.parse(src, feature_version=(3, 8))
        top_imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any(a.name == "torch" for n in top_imports for a in getattr(n, "names", [])),
                         "torch must be imported inside the worker's functions only")
        self.assertNotIn("print(", src, "stdout is the protocol: logs go through log() to stderr")


if __name__ == "__main__":
    unittest.main(verbosity=1)

#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_wavesmith.py
# Purpose : Exam for wavesmith.py, Wavesmith's front door: `list` names every subcommand, every subcommand's --help
#           runs through the front door, every tool module in this folder has a subcommand (a new tool cannot be
#           forgotten), unknown subcommands are usage errors, `test` runs a named exam, and `check` reports the GPU
#           tools without failing a machine that has none.
# Usage   : python tools/audio/wavesmith/test_wavesmith.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import wavesmith as W  # noqa: E402

NOT_TOOLS = {"wavesmith", "local_tts_worker", "flacfile"}   # the front door, the TTS worker, a codec library


class WavesmithExam(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = W.main([str(a) for a in argv])
            except SystemExit as exc:                    # argparse --help exits inside the subcommand
                rc = exc.code if isinstance(exc.code, int) else 0
        return rc, out.getvalue() + err.getvalue()

    def test_list_names_every_subcommand(self):
        rc, out = self.run_main("list")
        self.assertEqual(rc, 0)
        for name in list(W.SUBCOMMANDS) + ["check", "test"]:
            self.assertIn(f"  {name}", out)

    def test_every_tool_module_has_a_subcommand(self):
        modules = {p.stem for p in HERE.glob("*.py") if not p.stem.startswith("test_")} - NOT_TOOLS
        self.assertEqual(modules, {m for m, _ in W.SUBCOMMANDS.values()})
        for name, (module, _) in W.SUBCOMMANDS.items():
            self.assertTrue((HERE / f"test_{module}.py").exists(), f"{name}: no exam for {module}.py")

    def test_every_subcommand_help_runs_through_the_front_door(self):
        for name, (module, _) in W.SUBCOMMANDS.items():
            rc, out = self.run_main(name, "--help")
            self.assertEqual(rc, 0, f"{name}: {out}")
            self.assertIn("usage:", out, name)

    def test_usage_errors(self):
        rc, out = self.run_main()
        self.assertEqual(rc, 2)
        self.assertIn("Wavesmith", out)
        rc, out = self.run_main("mixdown")
        self.assertEqual(rc, 2)
        self.assertIn("unknown subcommand 'mixdown'", out)
        rc, out = self.run_main("test", "no_such_exam")
        self.assertEqual(rc, 2)

    def test_a_named_exam_runs_in_its_own_process(self):
        r = subprocess.run([sys.executable, "-B", str(HERE / "wavesmith.py"), "test", "wavfile"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("test_wavfile.py", r.stdout)
        self.assertIn("1 of 1 exam(s) passed", r.stdout)

    def test_check_never_fails_a_machine_without_the_gpu_tools(self):
        env = {k: v for k, v in os.environ.items() if k not in ("LOCAL_TTS_PYTHON", "COMFYUI_URL")}
        env["PYTHONIOENCODING"] = "utf-8"
        env["COMFYUI_URL"] = "http://127.0.0.1:9"                       # nothing listens on the discard port
        r = subprocess.run([sys.executable, "-B", str(HERE / "wavesmith.py"), "check"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("standard-library tools ready", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)

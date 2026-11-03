#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_make_sprites.py
# Purpose : Exam for tools/make_sprites.py without Blender: a missing launcher (uv or BPY_PYTHON) or kit tool
#           is an [error] with exit 2 and no traceback, a render that dies before printing a [..] line
#           shows its last output, a working render passes its [..] lines through, BPY_PYTHON keeps
#           Windows backslashes.
# Usage   : python tools/test_make_sprites.py
# Notes   : Stand-in renderers are tiny Python scripts run through BPY_PYTHON; nothing is rendered or
#           written (the stand-ins ignore the arguments make_sprites passes).
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "make_sprites.py"
sys.path.insert(0, str(HERE))
import make_sprites  # noqa: E402

# Bytes cp1252 cannot decode, so a pipe that is not UTF-8 shows up
ODD = "Í\u201d"
FAILS_EARLY = ("import sys\nsys.stderr.reconfigure(encoding='utf-8')\n"
               "print('Traceback (most recent call last):', file=sys.stderr)\n"
               f"print(\"ModuleNotFoundError: No module named 'bpy' {ODD}\", file=sys.stderr)\nsys.exit(1)\n")
WORKS = "import sys\nsys.stdout.reconfigure(encoding='utf-8')\nprint('noise')\nprint('[ OK ] rendered " + ODD + "')\n"


def quoted(path):
    return f'"{path}"'


class MakeSprites(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="make_sprites_" + ODD))

    def stub(self, body):
        p = self.tmp / f"stub_{ODD}.py"
        p.write_text(body, encoding="utf-8")
        return f"{quoted(sys.executable)} {quoted(p)}"

    def run_cli(self, *args, bpy=None, path=None):
        env = dict(os.environ)
        env.pop("BPY_PYTHON", None)
        if bpy is not None:
            env["BPY_PYTHON"] = bpy
        if path is not None:
            env["PATH"] = path
        proc = subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True, env=env,
                              encoding="utf-8", errors="replace")
        return proc.returncode, proc.stdout + proc.stderr

    def test_missing_bpy_python_is_a_setup_error(self):
        code, out = self.run_cli("crate", bpy=quoted(self.tmp / "no-such-python.exe"))
        self.assertEqual(code, 2, out)
        self.assertIn("[error] cannot find '", out)
        self.assertIn("(from BPY_PYTHON)", out)
        self.assertNotIn("Traceback", out)

    def test_missing_uv_is_a_setup_error(self):
        empty = self.tmp / "empty-path"
        empty.mkdir()
        code, out = self.run_cli("crate", path=str(empty))
        self.assertEqual(code, 2, out)
        self.assertIn("'uv'", out)
        self.assertNotIn("Traceback", out)

    def test_missing_kit_tool_is_a_setup_error(self):
        err = io.StringIO()
        with mock.patch.object(make_sprites, "TOOL", make_sprites.ROOT / "tools" / "blender" / "gone.py"), \
                mock.patch.dict(os.environ, {"BPY_PYTHON": quoted(sys.executable)}), \
                mock.patch.object(sys, "argv", ["make_sprites.py", "crate"]), \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = make_sprites.main()
        self.assertEqual(code, 2)
        self.assertIn("[error] the kit's render tool is missing: tools/blender/gone.py", err.getvalue())

    def test_early_child_failure_shows_its_cause(self):
        code, out = self.run_cli("crate", bpy=self.stub(FAILS_EARLY))
        self.assertEqual(code, 1, out)
        self.assertIn("No module named 'bpy' " + ODD, out)
        self.assertIn("[error] 1 render(s) failed", out)

    def test_working_render_passes_bracket_lines(self):
        code, out = self.run_cli("crate", bpy=self.stub(WORKS))
        self.assertEqual(code, 0, out)
        self.assertIn("crate: [ OK ] rendered " + ODD, out)
        self.assertNotIn("noise", out)
        code, out = self.run_cli("--debug", "crate", bpy=self.stub(WORKS))
        self.assertEqual(code, 0, out)
        self.assertIn("crate: noise", out)          # --debug shows everything
        self.assertIn("crate: [debug] ", out)       # ... and the command

    def test_bpy_python_keeps_windows_paths(self):
        with mock.patch.dict(os.environ, {"BPY_PYTHON": '"C:\\Program Files\\Py\\python.exe" -X utf8'}):
            self.assertEqual(make_sprites.bpy_python(), ["C:\\Program Files\\Py\\python.exe", "-X", "utf8"])
        if os.name == "nt":  # unquoted backslashes are escapes on POSIX, as in a shell
            with mock.patch.dict(os.environ, {"BPY_PYTHON": "C:\\Py\\python.exe"}):
                self.assertEqual(make_sprites.bpy_python(), ["C:\\Py\\python.exe"])


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    unittest.main(verbosity=1)

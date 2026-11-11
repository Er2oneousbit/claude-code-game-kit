#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_frames_to_gif.py
# Purpose : Exam for tools/art/frames_to_gif.py (#14): frames in file-name order, PNG and BMP, --every, --width
#           (nearest, never up), the frame delay a browser really plays (whole centiseconds, never under 20 ms),
#           a strip too thin to scale, the overwrite guard, the usage errors (exit 2), no frames or an unreadable
#           frame (exit 1, no traceback), Pillow missing (exit 2), and a non-ASCII output name printed as UTF-8.
# Usage   : python tools/art/test_frames_to_gif.py [-v]
# Needs   : Pillow (the tool needs it too)
# Exit    : 0 all pass, 1 a case failed, 2 Pillow is missing
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "frames_to_gif.py"
sys.path.insert(0, str(HERE))
try:
    from PIL import Image
except ImportError:
    print("[ENV ] Pillow is not installed (pip install pillow)")
    sys.exit(2)
import frames_to_gif as ftg  # noqa: E402

# distinct, palette-safe colours: frame i is COLOURS[i], so the GIF's frame order can be read back
COLOURS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255)]


def gif_frames(path):
    """[(rgb of pixel 0,0, duration ms)] per frame, plus the size and the loop count."""
    out = []
    with Image.open(path) as im:
        size, loop = im.size, im.info.get("loop")
        for k in range(im.n_frames):
            im.seek(k)
            out.append((im.convert("RGB").getpixel((0, 0)), im.info.get("duration")))
    return out, size, loop


class FramesToGif(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = self.tmp / "frames"
        self.src.mkdir()

    def frames(self, n, size=(16, 12), ext="png", names=None):
        for i in range(n):
            name = names[i] if names else "f%05d.%s" % (i, ext)
            Image.new("RGB", size, COLOURS[i % len(COLOURS)]).save(self.src / name)

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ftg.main([str(a) for a in args])
        return code, out.getvalue(), err.getvalue()

    # ---- the happy path --------------------------------------------------------------------------------------
    def test_frames_in_name_order_loop_forever(self):
        self.frames(4, names=["f00003.png", "f00001.png", "f00000.png", "f00002.png"])
        # the names above were written in that order with colours 0..3; sorted by name: colours 2, 1, 3, 0
        code, out, err = self.run_tool(self.src, self.tmp / "a.gif")
        self.assertEqual(code, 0, err)
        got, size, loop = gif_frames(self.tmp / "a.gif")
        self.assertEqual([c for c, _ in got], [COLOURS[2], COLOURS[1], COLOURS[3], COLOURS[0]])
        self.assertEqual(size, (16, 12))
        self.assertEqual(loop, 0)
        self.assertIn("[ OK ]", out)
        self.assertIn("4 frames", out)

    def test_bmp_frames_from_the_cpp_recorder(self):
        self.frames(3, ext="bmp")
        code, _, err = self.run_tool(self.src, self.tmp / "b.gif")
        self.assertEqual(code, 0, err)
        self.assertEqual([c for c, _ in gif_frames(self.tmp / "b.gif")[0]], COLOURS[:3])

    def test_other_files_in_the_folder_are_ignored(self):
        self.frames(2)
        (self.src / "notes.txt").write_text("not a frame", encoding="utf-8")
        (self.src / "sub").mkdir()
        code, out, err = self.run_tool(self.src, self.tmp / "c.gif")
        self.assertEqual(code, 0, err)
        self.assertIn("2 frames", out)

    def test_every_keeps_every_nth_frame_from_the_first(self):
        self.frames(6)
        code, out, err = self.run_tool(self.src, self.tmp / "e.gif", "--every", "2")
        self.assertEqual(code, 0, err)
        self.assertEqual([c for c, _ in gif_frames(self.tmp / "e.gif")[0]], [COLOURS[0], COLOURS[2], COLOURS[4]])
        self.assertIn("3 frames", out)

    def test_width_scales_down_with_nearest_and_never_up(self):
        im = Image.new("RGB", (40, 20), (255, 0, 0))
        for x in range(20, 40):
            for y in range(20):
                im.putpixel((x, y), (0, 0, 255))
        im.save(self.src / "f0.png")
        code, _, err = self.run_tool(self.src, self.tmp / "w.gif", "--width", "20")
        self.assertEqual(code, 0, err)
        with Image.open(self.tmp / "w.gif") as g:
            self.assertEqual(g.size, (20, 10))
            rgb = g.convert("RGB")
            # nearest neighbour: the two halves stay pure, no blended column at the seam
            self.assertEqual({rgb.getpixel((x, 5)) for x in range(20)}, {(255, 0, 0), (0, 0, 255)})
        code, _, err = self.run_tool(self.src, self.tmp / "big.gif", "--width", "400")
        self.assertEqual(code, 0, err)
        self.assertEqual(gif_frames(self.tmp / "big.gif")[1], (40, 20))     # smaller than --width: kept
        code, _, err = self.run_tool(self.src, self.tmp / "keep.gif", "--width", "0")
        self.assertEqual(code, 0, err)
        self.assertEqual(gif_frames(self.tmp / "keep.gif")[1], (40, 20))

    def test_a_strip_too_thin_to_scale_keeps_one_row(self):
        # 2000 x 1 scaled to 480 wide would be 0.24 px tall: the old code asked Pillow for a 0-px image and failed
        Image.new("RGB", (2000, 1), (255, 0, 0)).save(self.src / "f0.png")
        code, _, err = self.run_tool(self.src, self.tmp / "s.gif")
        self.assertEqual(code, 0, err)
        self.assertEqual(gif_frames(self.tmp / "s.gif")[1], (480, 1))

    def test_rgba_frames_are_flattened(self):
        Image.new("RGBA", (8, 8), (255, 0, 0, 0)).save(self.src / "f0.png")
        code, _, err = self.run_tool(self.src, self.tmp / "r.gif")
        self.assertEqual(code, 0, err)

    # ---- frame delay -----------------------------------------------------------------------------------------
    def test_delay_is_the_nearest_whole_centisecond(self):
        # GIF stores delays in hundredths of a second: 15 fps is 66.7 ms, so 70 ms (the old code wrote 60:
        # Pillow cut its 67 ms down to 6 cs, a GIF 11 % fast)
        self.frames(3)
        code, out, err = self.run_tool(self.src, self.tmp / "d.gif", "--fps", "15")
        self.assertEqual(code, 0, err)
        self.assertEqual({d for _, d in gif_frames(self.tmp / "d.gif")[0]}, {70})
        self.assertIn("0.2 s", out)                                     # 3 x 70 ms, the length it really plays
        code, _, err = self.run_tool(self.src, self.tmp / "d30.gif", "--fps", "30")
        self.assertEqual({d for _, d in gif_frames(self.tmp / "d30.gif")[0]}, {30})

    def test_fast_fps_is_capped_where_browsers_still_play_it(self):
        # browsers play a 0 or 1 cs delay at 100 ms: --fps 60 used to give 10 ms frames, a GIF 6x too slow
        self.frames(3)
        code, out, err = self.run_tool(self.src, self.tmp / "f.gif", "--fps", "60")
        self.assertEqual(code, 0, err)
        self.assertEqual({d for _, d in gif_frames(self.tmp / "f.gif")[0]}, {20})
        self.assertIn("[warn]", err)
        self.assertIn("--every", err)

    # ---- guards and errors -----------------------------------------------------------------------------------
    def test_existing_output_needs_overwrite(self):
        self.frames(2)
        out = self.tmp / "o.gif"
        out.write_bytes(b"keep me")
        code, _, err = self.run_tool(self.src, out)
        self.assertEqual(code, 2)
        self.assertIn("--overwrite", err)
        self.assertEqual(out.read_bytes(), b"keep me")
        code, _, err = self.run_tool(self.src, out, "--overwrite")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.read_bytes().startswith(b"GIF8"))

    def test_output_folder_is_created(self):
        self.frames(1)
        code, _, err = self.run_tool(self.src, self.tmp / "deep" / "er" / "x.gif")
        self.assertEqual(code, 0, err)
        self.assertTrue((self.tmp / "deep" / "er" / "x.gif").is_file())

    def test_usage_errors_exit_2(self):
        self.frames(1)
        cases = [
            ((self.tmp / "nope", self.tmp / "x.gif"), "not a folder"),
            ((self.src, self.tmp / "x.png"), "must end in .gif"),
            ((self.src, self.tmp / "x.gif", "--fps", "0"), "--fps > 0"),
            ((self.src, self.tmp / "x.gif", "--every", "0"), "--every >= 1"),
            ((self.src, self.tmp / "x.gif", "--colors", "1"), "--colors 2..256"),
            ((self.src, self.tmp / "x.gif", "--colors", "257"), "--colors 2..256"),
            ((self.src, self.tmp / "x.gif", "--width", "-1"), "--width >= 0"),
        ]
        for args, want in cases:
            with self.subTest(args=args[2:] or args[:2]):
                code, _, err = self.run_tool(*args)
                self.assertEqual(code, 2)
                self.assertIn(want, err)
        self.assertFalse((self.tmp / "x.gif").exists())

    def test_no_frames_exits_1(self):
        code, _, err = self.run_tool(self.src, self.tmp / "n.gif")
        self.assertEqual(code, 1)
        self.assertIn("no .png or .bmp frames", err)

    def test_unreadable_frame_exits_1_without_a_traceback(self):
        self.frames(1)
        (self.src / "f00001.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really")
        code, _, err = self.run_tool(self.src, self.tmp / "u.gif")
        self.assertEqual(code, 1)
        self.assertIn("[error]", err)
        self.assertIn("f00001.png", err)
        self.assertNotIn("Traceback", err)
        self.assertFalse((self.tmp / "u.gif").exists())

    def test_pillow_missing_exits_2(self):
        self.frames(1)
        saved = {k: v for k, v in sys.modules.items() if k == "PIL" or k.startswith("PIL.")}
        try:
            for k in saved:
                del sys.modules[k]
            sys.modules["PIL"] = None                     # makes `from PIL import Image` raise ImportError
            code, _, err = self.run_tool(self.src, self.tmp / "p.gif")
        finally:
            sys.modules.pop("PIL", None)
            sys.modules.update(saved)
        self.assertEqual(code, 2)
        self.assertIn("Pillow is required", err)

    def test_help_names_every_option(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            ftg.main(["-h"])
        self.assertEqual(stop.exception.code, 0)
        for opt in ("--fps", "--every", "--width", "--colors", "--overwrite", "--debug"):
            self.assertIn(opt, out.getvalue())

    def test_a_non_ascii_output_name_prints_as_utf8(self):
        # bytes cp1252 cannot decode (0x8D in "Í", 0x9D in a right double quote): the tool must write UTF-8
        self.frames(2)
        name = "Í”clip.gif"
        env = dict(os.environ)
        env.pop("PYTHONIOENCODING", None)
        env.pop("PYTHONUTF8", None)
        r = subprocess.run([sys.executable, str(TOOL), str(self.src), str(self.tmp / name), "--debug"],
                           capture_output=True, encoding="utf-8", errors="strict", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(name, r.stdout)
        self.assertIn("[debug] frame f00000.png", r.stderr)


if __name__ == "__main__":
    unittest.main()

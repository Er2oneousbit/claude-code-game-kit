#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_wavfile.py
# Purpose : Exam for wavfile.py's commands: stats, normalize (keeps loop points and stereo) and loop (a
#           seamless crossfade loop from any recording, with intro and outro trimming).
# Usage   : python tools/audio/wavesmith/test_wavfile.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wavfile  # noqa: E402

RATE = 8000


def stereo_tone(seconds, freq=220.0, level=0.01):
    """Interleaved L R, right channel at half level, so channel mix-ups show."""
    out = []
    for i in range(int(seconds * RATE)):
        v = level * math.sin(2 * math.pi * freq * i / RATE)
        out += [v, v * 0.5]
    return out


class WavfileExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = wavfile.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    def test_normalize_raises_a_quiet_file_and_keeps_stereo_and_loop(self):
        path = self.dir / "quiet.wav"
        wavfile.write_wav(path, stereo_tone(1.0), RATE, loop=(0, RATE - 1), channels=2)
        rc, out = self.cli("normalize", path, "--peak", "-3")
        self.assertEqual(rc, 0, out)
        s, rate, loop, ch = wavfile.read_wav_channels(path)
        self.assertEqual((rate, loop, ch), (RATE, (0, RATE - 1), 2))
        self.assertAlmostEqual(20 * math.log10(max(abs(v) for v in s)), -3.0, delta=0.05)
        self.assertAlmostEqual(max(s[1::2]) / max(s[0::2]), 0.5, delta=0.01, msg="channel balance kept")

    def test_never_writes_wav_bytes_under_another_name(self):
        with self.assertRaises(ValueError):
            wavfile.write_wav(self.dir / "x.ogg", [0.1] * 100, RATE)
        self.assertFalse((self.dir / "x.ogg").exists())
        wavfile.write_wav(self.dir / "UPPER.WAV", [0.1] * 100, RATE)          # any case of .wav is fine
        path = self.dir / "in.wav"
        wavfile.write_wav(path, [0.1] * 1000, RATE)
        for cmd in ("normalize", "loop"):
            rc, out = self.cli(cmd, path, "--out", self.dir / f"{cmd}.ogg")
            self.assertEqual(rc, 2, out)
            self.assertIn("must end in .wav", out)
            self.assertFalse((self.dir / f"{cmd}.ogg").exists())

    def test_out_never_replaces_a_file_without_overwrite(self):
        # #30: normalize and loop --out replaced an existing file silently
        path = self.dir / "in.wav"
        wavfile.write_wav(path, stereo_tone(6.0, level=0.5), RATE, channels=2)
        for cmd in ("normalize", "loop"):
            keep = self.dir / f"{cmd}_kept.wav"
            keep.write_bytes(b"not yours")
            rc, out = self.cli(cmd, path, "--out", keep)
            self.assertEqual(rc, 2, out)
            self.assertIn("--overwrite", out)
            self.assertEqual(keep.read_bytes(), b"not yours")
            rc, out = self.cli(cmd, path, "--out", keep, "--overwrite")
            self.assertEqual(rc, 0, out)
            self.assertEqual(wavfile.read_wav_channels(keep)[1], RATE)

    def test_normalize_silent_file_fails(self):
        path = self.dir / "silent.wav"
        wavfile.write_wav(path, [0.0] * 100, RATE)
        rc, out = self.cli("normalize", path)
        self.assertEqual(rc, 1)

    def test_loop_trims_crossfades_and_writes_loop_points(self):
        path, out_path = self.dir / "song.wav", self.dir / "loop.wav"
        wavfile.write_wav(path, stereo_tone(6.0, level=0.5), RATE, channels=2)
        rc, out = self.cli("loop", path, "--start", "1", "--end", "5", "--crossfade", "1", "--out", out_path)
        self.assertEqual(rc, 0, out)
        s, rate, loop, ch = wavfile.read_wav_channels(out_path)
        frames = len(s) // 2
        self.assertAlmostEqual(frames / rate, 3.0, places=2, msg="4 s kept minus the 1 s crossfade")
        self.assertEqual(loop, (0, frames - 1))
        # the step from the last frame back to the first is no bigger than an ordinary step
        steps = [abs(s[i + 2] - s[i]) for i in range(0, len(s) - 2, 2)]
        self.assertLessEqual(abs(s[0] - s[-2]), max(steps) + 1e-6)

    def test_loop_too_long_crossfade_is_usage_error(self):
        path = self.dir / "short.wav"
        wavfile.write_wav(path, stereo_tone(1.0), RATE, channels=2)
        rc, out = self.cli("loop", path, "--crossfade", "0.8")
        self.assertEqual(rc, 2)
        self.assertIn("too long", out)

    def test_reads_32_bit_recordings(self):
        # Godot's movie writer records 32-bit PCM; read as 16-bit it looks like noise
        import struct
        n = RATE
        frames = [int(0.25 * 2147483647 * math.sin(2 * math.pi * 300 * i / RATE)) for i in range(n)]
        data = struct.pack(f"<{2 * n}i", *(v for f in frames for v in (f, f)))
        fmt = struct.pack("<HHIIHH", 1, 2, RATE, RATE * 8, 8, 32)
        body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(data)) + data
        path = self.dir / "movie.wav"
        path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
        s, rate, loop, ch = wavfile.read_wav_channels(path)
        self.assertEqual((rate, ch, len(s)), (RATE, 2, 2 * n))
        self.assertAlmostEqual(max(s), 0.25, places=3)
        crossings = sum(1 for i in range(2, len(s), 2) if (s[i - 2] < 0) != (s[i] < 0))
        self.assertAlmostEqual(crossings, 600, delta=4, msg="a 300 Hz tone, not noise")

    def test_loop_end_past_the_data_is_clamped(self):
        # another writer's off-by-one (loop end = frame count) must not make stats index past the end
        path = self.dir / "offbyone.wav"
        samples = [0.1 * math.sin(i / 5) for i in range(2000)]
        wavfile.write_wav(path, samples, RATE, loop=(0, len(samples)))
        s, rate, loop = wavfile.read_wav(path)
        self.assertEqual(loop, (0, len(samples) - 1))
        self.assertIn("loop_seam_step", wavfile.stats(s, rate, loop))
        wavfile.write_wav(path, samples, RATE, loop=(5000, 6000))
        self.assertIsNone(wavfile.read_wav(path)[2], "a loop wholly outside the data is dropped")

    def test_stats_and_unreadable_file(self):
        path = self.dir / "a.wav"
        wavfile.write_wav(path, stereo_tone(0.5, level=0.5), RATE, channels=2)
        rc, out = self.cli("stats", path)
        self.assertEqual(rc, 0, out)
        self.assertIn("2 ch", out)
        rc, out = self.cli("stats", self.dir / "nope.wav")
        self.assertEqual(rc, 2)

    def test_broken_headers_are_clean_errors(self):
        good = self.dir / "good.wav"
        wavfile.write_wav(good, [0.1] * 100, RATE)
        raw = good.read_bytes()
        fmt_at = raw.index(b"fmt ")
        short = raw[:fmt_at + 4] + struct.pack("<I", 8) + raw[fmt_at + 8:fmt_at + 16] + raw[fmt_at + 24:]
        zero = bytearray(raw)
        zero[fmt_at + 12:fmt_at + 16] = struct.pack("<I", 0)            # the sample rate field
        for name, data, word in (("short.wav", short, "cut short"), ("zero.wav", bytes(zero), "0 Hz")):
            path = self.dir / name
            path.write_bytes(data)
            with self.assertRaises(ValueError) as ctx:
                wavfile.read_wav_channels(path)
            self.assertIn(word, str(ctx.exception))
            with self.assertRaises(ValueError):
                wavfile.wav_stream(path)
            rc, out = self.cli("stats", path)
            self.assertEqual(rc, 2, out)
            self.assertNotIn("Traceback", out)

    def test_stream_reads_the_same_samples(self):
        path = self.dir / "s.wav"
        wavfile.write_wav(path, stereo_tone(0.3), RATE, loop=(0, 99), channels=2)
        samples, rate, _, ch = wavfile.read_wav_channels(path)
        r, c, frames, chunks = wavfile.wav_stream(path, chunk_frames=777)
        got = [[], []]
        for part in chunks():
            self.assertLessEqual(len(part[0]), 777)
            got[0] += part[0]
            got[1] += part[1]
        self.assertEqual((r, c, frames), (rate, 2, len(samples) // 2))
        self.assertEqual(got, [samples[0::2], samples[1::2]])


if __name__ == "__main__":
    unittest.main(verbosity=1)

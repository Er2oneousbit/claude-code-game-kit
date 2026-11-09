#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_wavfile.py
# Purpose : Exam for wavfile.py's commands: stats, normalize (keeps loop points and stereo) and loop (a
#           seamless crossfade loop from any recording, with intro and outro trimming); 8 / 16 / 24 / 32-bit PCM and
#           float WAVs read with plain and extensible headers, and other sample formats are refused naming ffmpeg.
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


def raw_wav(fmt, data):
    """A RIFF/WAVE file from a fmt chunk body and sample bytes, built by hand (write_wav only writes 16-bit)."""
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    body += b"\0" * (len(data) % 2)
    return b"RIFF" + struct.pack("<I", len(body)) + body


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

    def test_reads_24_bit_8_bit_float_and_extensible_headers(self):
        # #102: only 16 and 32-bit integer PCM with a plain header were read; DAW exports (24-bit) and anything
        # ffmpeg writes as WAVE_FORMAT_EXTENSIBLE (24 / 32-bit, 16-bit above 48 kHz) stopped every tool
        n = 2000
        src = [0.5 * math.sin(2 * math.pi * 300 * i / RATE) for i in range(n)]
        stereo = [v for s in src for v in (s, -s)]
        guid = lambda tag: struct.pack("<I", tag) + wavfile.GUID_TAIL
        cases = {
            "pcm24": (1, 24, b"".join(struct.pack("<i", int(round(v * 8388607)))[:3] for v in stereo), b"", 1e-6),
            "pcm8": (1, 8, bytes(int(round(v * 127)) + 128 for v in stereo), b"", 1 / 127),
            "f32": (3, 32, struct.pack(f"<{2 * n}f", *stereo), b"", 1e-7),
            "f64": (3, 64, struct.pack(f"<{2 * n}d", *stereo), b"", 0.0),
            "ext16": (0xFFFE, 16, struct.pack(f"<{2 * n}h", *(int(round(v * 32767)) for v in stereo)),
                      struct.pack("<HHI", 22, 16, 3) + guid(1), 1e-4),
            "ext24": (0xFFFE, 24, b"".join(struct.pack("<i", int(round(v * 8388607)))[:3] for v in stereo),
                      struct.pack("<HHI", 22, 24, 3) + guid(1), 1e-6),
            "extf32": (0xFFFE, 32, struct.pack(f"<{2 * n}f", *stereo), struct.pack("<HHI", 22, 32, 3) + guid(3), 1e-7),
        }
        for name, (tag, bits, data, ext, tol) in cases.items():
            with self.subTest(name):
                path = self.dir / f"{name}.wav"
                fmt = struct.pack("<HHIIHH", tag, 2, RATE, RATE * bits // 4, bits // 4, bits) + ext
                path.write_bytes(raw_wav(fmt, data))
                s, rate, loop, ch = wavfile.read_wav_channels(path)
                self.assertEqual((rate, ch, len(s)), (RATE, 2, 2 * n))
                self.assertLessEqual(max(abs(a - b) for a, b in zip(s, stereo)), tol + 1e-9)
                r, c, frames, chunks = wavfile.wav_stream(path, chunk_frames=777)
                self.assertEqual((r, c, frames), (RATE, 2, n))
                self.assertEqual([v for part in chunks() for v in part[0]], s[0::2], "the stream reads the same")
                rc, out = self.cli("stats", path)
                self.assertEqual(rc, 0, out)

    def test_an_unread_sample_format_says_how_to_convert(self):
        # ADPCM (tag 2), an unknown extensible GUID: WavFormatError, which audioio hands to ffmpeg
        path = self.dir / "adpcm.wav"
        path.write_bytes(raw_wav(struct.pack("<HHIIHH", 2, 1, RATE, RATE, 256, 4), b"\0" * 512))
        odd = self.dir / "odd.wav"
        odd.write_bytes(raw_wav(struct.pack("<HHIIHH", 0xFFFE, 1, RATE, RATE * 2, 2, 16)
                                + struct.pack("<HHI", 22, 16, 4) + b"\x01" * 16, b"\0" * 200))
        for p in (path, odd):
            with self.assertRaises(wavfile.WavFormatError) as ctx:
                wavfile.read_wav_channels(p)
            self.assertIn("ffmpeg", str(ctx.exception))
            with self.assertRaises(wavfile.WavFormatError):
                wavfile.wav_stream(p)
            rc, out = self.cli("stats", p)
            self.assertEqual(rc, 2, out)
            self.assertNotIn("Traceback", out)
        six = self.dir / "six.wav"                         # 5.1: refused, but not as a format ffmpeg would fix
        six.write_bytes(raw_wav(struct.pack("<HHIIHH", 1, 6, RATE, RATE * 12, 12, 16), b"\0" * 1200))
        with self.assertRaises(ValueError) as ctx:
            wavfile.read_wav_channels(six)
        self.assertNotIsInstance(ctx.exception, wavfile.WavFormatError)
        self.assertIn("6 channels", str(ctx.exception))

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

    def test_a_sample_rate_the_header_cannot_hold_is_an_error_not_a_traceback(self):
        # the rate field is 32 bits and reads fine near its top, but rate x block align no longer fits the
        # byte-rate field: write_wav raised struct.error from normalize and loop, a raw traceback
        fmt = struct.pack("<HHIIHH", 1, 1, 0xFFFFFFFF, 0xFFFFFFFF, 2, 16)
        path = self.dir / "hz.wav"
        path.write_bytes(raw_wav(fmt, struct.pack("<16h", *([100] * 16))))
        rc, out = self.cli("stats", path)
        self.assertEqual(rc, 0, out)
        for name, args in (("n.wav", ("normalize",)), ("l.wav", ("loop", "--crossfade", "1e-9"))):
            rc, out = self.cli(*args, path, "--out", self.dir / name)
            self.assertEqual(rc, 2, out)
            self.assertIn("[error]", out)
            self.assertIn("cannot be written", out)
            self.assertNotIn("Traceback", out)
            self.assertFalse((self.dir / name).exists())
        for rate in (0xFFFFFFFF, 0x40000000, 0):
            with self.assertRaises(ValueError):
                wavfile.write_wav(self.dir / "x.wav", [0.0] * 4, rate, channels=2)
        wavfile.write_wav(self.dir / "ok.wav", [0.0] * 4, 384000, channels=2)     # the highest real rate is fine

    def test_fix_stream_sizes_sets_placeholder_sizes_to_the_real_ones(self):
        # #178: a streamed WAV says 0xFFFFFFxx for the RIFF and data sizes; only those two fields change
        fmt = struct.pack("<HHIIHH", 1, 1, RATE, RATE * 2, 2, 16)
        good = raw_wav(fmt, struct.pack("<4h", 1, -1, 300, -300))
        streamed = good[:4] + struct.pack("<I", 0xFFFFFF24) + good[8:40] + struct.pack("<I", 0xFFFFFF00) + good[44:]
        fixed, changed = wavfile.fix_stream_sizes(streamed)
        self.assertEqual((fixed, changed), (good, True))
        self.assertEqual(wavfile.fix_stream_sizes(good), (good, False))
        # a chunk after data keeps every size; bytes that are not a WAV come back untouched
        tail = good + b"LIST" + struct.pack("<I", 4) + b"INFO"
        tail = tail[:4] + struct.pack("<I", len(tail) - 8) + tail[8:]
        self.assertEqual(wavfile.fix_stream_sizes(tail), (tail, False))
        self.assertEqual(wavfile.fix_stream_sizes(b"\xff\xfbmp3"), (b"\xff\xfbmp3", False))

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

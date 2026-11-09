#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_flacfile.py
# Purpose : Exam for flacfile.py: real encoder output (ffmpeg's FLAC encoder, the one ComfyUI uses) decodes to
#           the exact source samples with a matching MD5, every subframe type and stereo layout is exercised,
#           and corrupt or out-of-scope files are refused instead of decoded wrong.
# Usage   : python tools/audio/wavesmith/test_flacfile.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : The fixtures are small FLAC files (base64, padding removed) encoded from the integer-only signals
#           below, so the expected samples are regenerated exactly on any platform. Measured coverage of the
#           fixtures: CONSTANT, VERBATIM, FIXED, LPC orders 2-8, wasted bits, independent / left-side /
#           side-right / mid-side stereo, 16- and 24-bit, extra metadata blocks. The escape-coded residual
#           path is covered by a frame built bit by bit in this file (real encoders rarely emit it).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import base64
import contextlib
import hashlib
import io
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flacfile  # noqa: E402
from wavfile import read_wav_channels  # noqa: E402


# ---- the fixtures' source signals (integer math only) ----
def lcg(seed):
    x = seed
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x


def tri(i, period, amp):
    p = i % period
    half = period // 2
    return (amp * (2 * p - half) // half) if p < half else (amp * (2 * (period - p) - half) // half)


def signal(name, n=1500):
    """Channel lists of ints for one fixture."""
    r1, r2 = lcg(7), lcg(11)
    if name == "mono16":
        return [[tri(i, 97, 12000) + next(r1) % 201 - 100 for i in range(n)]]
    if name == "stereo16":
        left = [tri(i, 113, 9000) + next(r1) % 201 - 100 for i in range(n)]
        return [left, [(v * 13) // 16 + (next(r2) % 101 - 50) for v in left]]
    if name == "stereo16_const":
        left = [tri(i, 64, 8000) if i < n // 2 else 0 for i in range(n)]
        return [left, list(left)]
    if name == "mono24":
        return [[tri(i, 89, 3000000) + (next(r1) % 201 - 100) * 300 for i in range(n)]]
    if name == "wasted16":
        return [[(tri(i, 101, 3000) + next(r1) % 41 - 20) * 8 for i in range(n)]]
    if name == "fixed16":
        return [[tri(i, 200, 6000) for i in range(n)]]
    if name == "noise16":
        return [[((next(r1) >> 8) & 0xFFFF) - 32768 for _ in range(n)]]
    raise KeyError(name)


# ---- a tiny FLAC writer for hand-built frames (escape residuals, out-of-scope headers) ----
class BitWriter:
    def __init__(self):
        self.value, self.n = 0, 0

    def put(self, bits, v):
        self.value = (self.value << bits) | (v & ((1 << bits) - 1))
        self.n += bits

    def pad(self):
        self.put((8 - self.n % 8) % 8, 0)

    def bytes(self):
        return self.value.to_bytes(self.n // 8, "big")


def streaminfo(rate, channels, bits, total, md5=bytes(16)):
    packed = (rate << 44) | ((channels - 1) << 41) | ((bits - 1) << 36) | total
    body = struct.pack(">HH", 4096, 4096) + b"\0" * 6 + packed.to_bytes(8, "big") + md5
    return b"fLaC" + bytes([0x80, 0, 0, len(body)]) + body


def hand_frame(block, subframes, channels_code=0):
    """One 16-bit frame (44.1 kHz, frame number 0, block size in 8 bits) from subframe writers, each a function
    that writes one channel's subframe into a BitWriter; channels_code is the header's channel layout code
    (0 mono, 1 independent stereo). Both CRCs are right, so only what the subframes say can be wrong."""
    head = BitWriter()
    head.put(14, 0x3FFE); head.put(1, 0); head.put(1, 0)     # sync, reserved, fixed block size
    head.put(4, 6); head.put(4, 9)                          # block size in 8 bits at the end, 44.1 kHz
    head.put(4, channels_code); head.put(3, 4); head.put(1, 0)   # channels, 16-bit, reserved
    head.put(8, 0)                                          # frame number 0
    head.put(8, block - 1)
    hb = head.bytes()
    frame = BitWriter()
    frame.value, frame.n = int.from_bytes(hb + bytes([flacfile.crc8(hb)]), "big"), (len(hb) + 1) * 8
    for write in subframes:
        write(frame)
    frame.pad()
    fb = frame.bytes()
    return fb + flacfile.crc16(fb).to_bytes(2, "big")


def fixed0(samples, raw_bits=16, parts=0):
    """A FIXED order 0 subframe whose 2 ** parts residual partitions are all escape-coded (raw_bits raw bits
    each): the samples go in verbatim, so a frame can say anything, in range or not."""
    def write(frame):
        frame.put(1, 0); frame.put(6, 8); frame.put(1, 0)   # FIXED order 0, no wasted bits
        frame.put(2, 0); frame.put(4, parts)                # rice, partition order
        n = len(samples) >> parts
        for p in range(1 << parts):
            frame.put(4, 15); frame.put(5, raw_bits)        # escape: raw_bits per residual
            for s in samples[p * n:(p + 1) * n]:
                frame.put(raw_bits, s)
    return write


def constant(value, wasted=0):
    """A CONSTANT subframe, optionally with wasted bits (a unary count, then the value in the bits left)."""
    def write(frame):
        frame.put(1, 0); frame.put(6, 0)
        if wasted:
            frame.put(1, 1); frame.put(wasted, 1)           # wasted - 1 zeros, then the 1: the count
            frame.put(max(16 - wasted, 0), value)
        else:
            frame.put(1, 0); frame.put(16, value)
    return write


def escape_frame(samples):
    """One mono 16-bit frame: FIXED order 0 subframe whose single residual partition is escape-coded (raw)."""
    return hand_frame(len(samples), [fixed0(samples)])


def md5_16(chans):
    m = hashlib.md5()
    for frame in zip(*chans):
        m.update(struct.pack("<" + "h" * len(frame), *frame))
    return m.digest()


# Encoded by ffmpeg 9.0 (flac, padding removed) from signal(); tagged16 is mono16 with two tags.
FIXTURES = {
    "mono16": (
        "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"),
    "stereo16": (
        "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"),
    "stereo16_const": (
        "ZkxhQwAAACIBAAEAAAAOAADpCsRC8AAABdyWjPTlvhizAD2sws4Ri/z4hAAALAwAAABMYXZmNjMuMS4xMDIBAAAAFAAAAGVuY29kZXI9TGF2ZjYzLjEuMTAy//iJiAClQ3gw4rea9kMQYKjbKqf+kV/chDJ5BRhp4gUVMqWMGTZw8b8BxvXLFalQIQzJKrpvqKq7bpFUadStXs2rlvYHS3Zq0580iv7kIZPIKMNPECiplSxgybOHjfgON65YrUqBCGZJVdN9RVXbdIqjTqVq9m1ct7A6W7NWnPmkV/chDJ5BRhp4gUVMqWMGTZw8b8BxvXLFalQIQzJKrpvqKq7bpFUadStXs2rlvYHS3Zq0580iv7kIZPIKMNPECiplSxgybOHjfgON65YrUqBCGZJVdN9RVXbdIqjTqVq9m1cgAAAA3mz/+ImIAaJDeDDit5r2QxBgqNsqp/6RX9yEMnkFGGniBRUypYwZNnDxvwHG9csVqVAhDMkqum+oqrtukVRp1K1ezauW9gdLdmrTnzSK/uQhk8gow08QKKmVLGDJs4eN+A43rlitSoEIZklV031FVdt0iqNOpWr2bVy3sDpbs1ac+aRX9yEMnkFGGniBRUypYwZNnDxvwHG9csVqVAhDMkqum+oqrtukVRp1K1ezauW9gdLdmrTnzSK/uQhk8gow08QKKmVLGDJs4eN+A43rlitSoEIZklV031FVdt0iqNOpWr2bVyAAAAB9zP/4iYgCq0N4MOK3mvZDEGCo2yqn/pFf3IQyeQUYaeIFFTKljBk2cPG/Acb1yxWpUCEMySq6b6iqu26RVGnUrV7Nq5b2B0t2atOfNIr+5CGTyCjDTxAoqZUsYMmzh434DjeuWK1KgQhmSVXTfUVV23SKo06lavZtXLewOluzVpz5pFf3IQyeQUYaeIFFTKljBk2cPG/Acb1yxWpUCEMySq6b6iqu26RVGnUrV7Nq5b2B0t2atOfNIr+5CGTyCjDTxAoqZUsYMmzh434DjeuWK1Kg8ZFQ0JAQI+QYAf4f4AAAAMUZ//iJGANNAAAAAAAACkT/+IkYBFgAAAAAAADuBf/4aRgF2/EAAAAAAAAUAw=="),
    "mono24": (
        "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"),
    "wasted16": (
        "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"),
    "fixed16": (
        "ZkxhQwAAACICAAIAAABrAAB1CsRA8AAABdyp8M277su5kBqfqP+rZ4wyhAAALAwAAABMYXZmNjMuMS4xMDIBAAAAFAAAAGVuY29kZXI9TGF2ZjYzLjEuMTAy//iZCACxFT0S6QhB////////////////wAAAAAAAAAf///8P///////////4AAAAAAAAAH////////8P//////+AAAAAAAAAD/////////////4f//AAAAAAAAAA////////////////8AAAAAAAAAH/wHa4//iZCAG2FSI6EVhB//////////////wAAAAAAAAAP/////+H/////////8AAAAAAAAAH//////////8P////+AAAAAAAAAB///////////////8PgAAAAAAAAA////////////////8AAAAAAAAAD///4Kqt//h5CAIB260VPnr0SEH////////////AAAAAAAAAB//////+H/////////gAAAAAAAAAf/////////w//////4AAAAAAAAAP////////////8P//8AAAAAAAAAD////////////////gS3Y="),
    "noise16": (
        "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"),
    "tagged16": (
        "ZkxhQwAAACIF3AXcAAcaAAcaCsRA8AAABdzDaTKzn4tolN/W49pOREa9hAAAZwwAAABMYXZmNjMuMS4xMDIDAAAAHwAAAHByb21wdD17IjEiOiAiYSBDb21meVVJIGdyYXBoIn0UAAAAREVTQ1JJUFRJT049dGFnIHRlc3QUAAAAZW5jb2Rlcj1MYXZmNjMuMS4xMDL/+HkIAAXbL0bRZ9Nt1SPXGeavFva55kfd2FFJkXTTmB4BRWYQXS8+hJNG0xg9GxXChqoulcadCYiQydKj7F8wLMWT4Um1JMuF5RovUMkAJUAf0WVXeG8lTXBeUwulQrU1tytaFKUUymXhnt61xR9EOHdFLkEbw6N6xY7vxvG5frqU5e/lxisuXvdGBrHmXbeJHc1jS5EaP5Us6NI6+W0eOwm5mqKf1LJBKaRYIDAE031qvuIUSuIAl0ezb+K5xSuTvrA2wBYw0bH36ZYz/YaHX/TSBOKXLIR94g2UV8/Dvl4iN7uf/9XBvcYx6o4X7Njanxp2bRNM5TU0/UFZcIC+B2It3XHQqiqzNIx0ETTWJcyW8vKWy75S+0tJO2t2wraI+pUFA3dwmS4RpTOWQ7BZUn2OzkHcANMAwIN/UUU3OeQaXJGTKf1uJsNDo2u7zMK5zbrZXWTyllqFjlMkqrmxOWQZc0fg8V5e5SGTVUlND/tzbMDQBFLjTLHh0Jg228dNoNZRx36FALomzrxJEInFtljbVGK4uG7RzZcH5OJMMFa2Iiq+Yx2EFJN7g9gAm4Z1ryxZmRLFhEnaiHJOykl5nXlFUq0Q0NTmaae+xxVT2GVWtOHTJFvXs2S0ydlr8SKLbKtFHaxZwgAGkdgQS9y1zitEhj7oo+qPlFekE4+biJpI7rjVA+m3mtj0KpJoAhn8/zgVRyW5kNBSi8cmUUwARAAAmQA8WPhV5/JpDrDDFMheYrWp1OSv49DdeMQIAkboUPojkCJ18FK+/IuaP4HHYvU3Z2PRojUiaomQAG4ALaQKflQ9NW7syuWJpqvft4LivEw191sNx9yowvOwvMQY1lT/lOdEcSA/EmWy5BMU0sH0AMQAAAgwEC6ec7CFbApk0evUeHS1I59sDTquZa1PE2FLtk3ZTRk3v4TcvPDPJ481GI2AiBKo0sbN/k/jAByAZBAQrfOlDcaCKnSJFTMVGRPPGrEiFoWrKWBZuDUNZn8TgpaAplkopK8FRPl4mCgNSVP5dgA6AAASoBSmO6JrC7GATpuJpQsy9GQe95qI03uft29fpxOgjc5S4ZkvQcKGItE0bNsWzynLGipMljApcUAAVgWgpha7GDp8YmYNCOYcJHHnpOgtVBf7USLQqdzZNA5wgKueiCezBYYqQdGGYWEVj4bTI8zmADuAABEgPEwVwuyAjOIqMquxauzEI5VA/PvP3YuI9z8hZPvDkr3vW78mRePyv+x1YbbRU/qaR541c29bUgPQwxKlzjiB8ZPZlAm3WZw70o2TUeLYjfVGI7qX2PRUjfe96JZNbdYyVdSAZl5qGxFAKVDfFI1qBOgBfxl0tQy76KVJx5VauqCUdCtbP+dTYRV+1fapw1J+Vw6sOru19MPoP90HropI7JS0DTWkqKkOEWVrwHiJJ5OGmCz3WEzdHc8sPo0cIhfaV+AbjLdXERmHeaARSqbhKLszryJUnaHMFFdU2WUyFneTwMsKMAsoOTqfc3nHgOUSTepcnL5f2ZWyWqBpc7HsBcbPbEBwec0trhuybH4xyyMna8bpYanqWxHdvvN0l4YCLC0VuUXB2YPWtnje9jVbRRC5CtCS5V1FXsEI9lSoOVWjzU21qxgW0x6YVBVPdu2kiqGebaEkhgJEAL2E/RdhPaiWOQiGob8EaSW3L8h+aodnbxH7/0EF8qPcG2L/xOnEIDzVvrNH+swxvLTtTbvvP6QXctiA4A3Etjv3raRFFW7Z4Vp3ApfvlnPsiqVGpwCszBkOjjksVdEL5hkg7eixjkXdtMuVyJTZQqpqr4DtAP+Dkw2XqNFpfRo84oLAkyI6RhDT5FAjFj3iMFfhpBG6GqQbEPGuuRBoRDuFjo906q7QAec18jbqhBgAOwCs2DFTTHXbgcMPA+IrSUdg1TU3d4/xvFyiCwY8RKC+I9MGEhzqSKAMbOHw5yC1vw4BNYSgPYBIAAHCAP0QboMxVvK+XWmnNcsnfXXiOdgo6gzlzQOfMdOxSuWC00g+zPUmyNdJvJphE996QZ89wu7AaoABOAJCr0b8h6dcFf7F3rVxB2zSt+tA6KkOhN7hWlck24N7zhGuIp5RphISJIxQGETIZysaxMSAAKYAABfgLUwRKXP5vSXeb1uIY8+JuZpXGPL6XonhD0WsU7SM+kSbGM3l7BFrWf8Was6ZHkGaouyKChi2SACEAEQg12rNm/8Rmqats4RmfZD/0xpqxPsAk7pOJLwVU1Mk4hS6gWt3icdCaUEY3BOXi89B0AO4AAChAdPnBtaiJiZm0UsMtRJxEwt+VhunEjdxt+aGZM58oqtJOELFSrQRKuGHCP+kMl7rE79YSJwvgAfgCiPI9baaHjFKpYydK28BfN9c4xGGyNLnWLkKMhmURjFQpVE0/C/URoCKS+ELqrEhqk4AfQ4="),
}


class FlacExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def data(self, name):
        return base64.b64decode(FIXTURES[name])

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = flacfile.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    def test_every_fixture_decodes_to_the_exact_source(self):
        for name in FIXTURES:
            info, chans, status = flacfile.decode(self.data(name))
            expect = signal("mono16" if name == "tagged16" else name)
            self.assertEqual(status, "ok", name)
            self.assertEqual(chans, expect, f"{name}: samples differ from the source signal")
            self.assertEqual(info["channels"], len(expect))

    def test_24_bit_is_read_as_24_bit(self):
        info, chans, _ = flacfile.decode(self.data("mono24"))
        self.assertEqual(info["bits"], 24)
        self.assertGreater(max(abs(v) for v in chans[0]), 1 << 20)

    def test_read_flac_gives_interleaved_floats(self):
        path = self.dir / "s.flac"
        path.write_bytes(self.data("stereo16"))
        samples, rate, channels = flacfile.read_flac(path)
        left, right = signal("stereo16")
        self.assertEqual((rate, channels, len(samples)), (44100, 2, 2 * len(left)))
        self.assertAlmostEqual(samples[0], left[0] / 32768.0)
        self.assertAlmostEqual(samples[1], right[0] / 32768.0)

    def test_escape_coded_residual(self):
        samples = [0, 1, -1, 32767, -32768, 1234, -4321, 7]
        data = streaminfo(44100, 1, 16, len(samples), md5_16([samples])) + escape_frame(samples)
        _, chans, status = flacfile.decode(data)
        self.assertEqual((chans[0], status), (samples, "ok"))

    def test_unset_md5_is_accepted_and_reported(self):
        samples = [5, -5, 9, -9]
        _, chans, status = flacfile.decode(streaminfo(44100, 1, 16, 4, bytes(16)) + escape_frame(samples))
        self.assertEqual((chans[0], status), (samples, "unset"))
        path = self.dir / "unset.flac"
        path.write_bytes(streaminfo(44100, 1, 16, 4, bytes(16)) + escape_frame(samples))
        rc, out = self.run_tool("info", path)
        self.assertEqual(rc, 0, out)
        self.assertIn("MD5 unset", out)

    def test_wrong_md5_is_a_failure_not_audio(self):
        data = bytearray(self.data("mono16"))
        md5_at = 4 + 4 + 18                         # fLaC, block header, STREAMINFO fields before the MD5
        data[md5_at] ^= 0xFF
        with self.assertRaises(flacfile.FlacCorrupt):
            flacfile.decode(bytes(data))

    def test_flipped_audio_byte_fails_a_crc(self):
        data = bytearray(self.data("stereo16"))
        data[len(data) // 2] ^= 0x10
        with self.assertRaises(flacfile.FlacCorrupt):
            flacfile.decode(bytes(data))

    def test_truncated_file_fails(self):
        data = self.data("mono24")
        with self.assertRaises(flacfile.FlacCorrupt):
            flacfile.decode(data[: len(data) - 200])

    def test_out_of_scope_streams_are_refused_by_name(self):
        for bits, channels, word in ((8, 1, "8-bit"), (20, 1, "20-bit"), (16, 3, "3-channel")):
            with self.assertRaises(flacfile.FlacError) as ctx:
                flacfile.decode(streaminfo(44100, channels, bits, 4, bytes(16)))
            self.assertIn(word, str(ctx.exception))
        with self.assertRaises(flacfile.FlacError):
            flacfile.decode(b"RIFF....WAVE")

    def test_extra_metadata_blocks_are_skipped(self):
        data = self.data("tagged16")
        self.assertIn(b"a ComfyUI graph", data, "fixture should carry a tag")
        _, chans, status = flacfile.decode(data)
        self.assertEqual((chans, status), (signal("mono16"), "ok"))

    def test_towav_writes_the_samples_and_no_tags(self):
        src, wav = self.dir / "t.flac", self.dir / "t.wav"
        src.write_bytes(self.data("tagged16"))
        rc, out = self.run_tool("towav", src, "--out", wav)
        self.assertEqual(rc, 0, out)
        samples, rate, _, channels = read_wav_channels(wav)
        self.assertEqual([round(s * 32767) for s in samples][:50],
                         [round(v / 32768.0 * 32767) for v in signal("mono16")[0][:50]])
        self.assertNotIn(b"ComfyUI", wav.read_bytes())
        rc, out = self.run_tool("towav", src, "--out", wav)
        self.assertEqual(rc, 2, "an existing WAV needs --overwrite")
        rc, out = self.run_tool("towav", src, "--out", self.dir / "t.ogg")
        self.assertEqual(rc, 2, out)
        self.assertIn("must end in .wav", out)
        self.assertNotIn("Traceback", out)

    def test_a_short_or_zeroed_metadata_region_is_corrupt_not_a_crash(self):
        # #111: a STREAMINFO of length 0, or a real file zeroed after its STREAMINFO (a cut, padded download),
        # raised struct.error and printed a traceback
        import audioio
        real = self.data("tagged16")                         # STREAMINFO is not the last block here
        cases = {"empty.flac": (b"fLaC" + bytes([0x80, 0, 0, 0]), "0 bytes, not 34"),
                 "zeroed.flac": (real[:42] + bytes(len(real) - 42), "0 bytes, not 34"),
                 "twice.flac": (real[:4] + bytes([0]) + real[5:42] + real[4:42] + real[42:], "second STREAMINFO"),
                 "cut.flac": (real[:4] + bytes([0x80, 0, 0, 34]) + real[8:30], "runs past the end")}
        for name, (data, word) in cases.items():
            with self.subTest(name):
                with self.assertRaises(flacfile.FlacCorrupt) as ctx:
                    flacfile.decode(data)
                self.assertIn(word, str(ctx.exception))
                path = self.dir / name
                path.write_bytes(data)
                rc, out = self.run_tool("info", path)
                self.assertEqual(rc, 1, out)
                self.assertIn("[FAIL]", out)
                self.assertNotIn("Traceback", out)
                with self.assertRaises(audioio.AudioIOError):
                    audioio.read_audio(path)
                with self.assertRaises(audioio.AudioIOError):
                    audioio.stream_audio(path)

    def hostile(self, name, data, word, audioio_too=True):
        """A crafted file is FlacCorrupt everywhere it can be read: decode(), the CLI (exit 1, no traceback), and
        audioio's read and stream paths (AudioIOError, never a raw exception)."""
        with self.assertRaises(flacfile.FlacCorrupt) as ctx:
            flacfile.decode(data)
        self.assertIn(word, str(ctx.exception))
        path = self.dir / name
        path.write_bytes(data)
        rc, out = self.run_tool("info", path)
        self.assertEqual(rc, 1, out)
        self.assertNotIn("Traceback", out)
        if audioio_too:
            import audioio
            with self.assertRaises(audioio.AudioIOError):
                audioio.read_audio(path)
            with self.assertRaises(audioio.AudioIOError):      # from the header, or from inside chunks()
                list(audioio.stream_audio(path)[2]())

    def test_a_zero_sample_rate_is_corrupt_not_a_crash(self):
        # the STREAMINFO rate is 20 untrusted bits: 0 reached `samples / rate` in the CLI and in audioio's convert
        data = streaminfo(0, 1, 16, 8) + escape_frame([1] * 8)
        self.hostile("rate0.flac", data, "0 Hz")

    def test_wasted_bits_past_the_sample_depth_are_corrupt_not_a_crash(self):
        # a subframe's wasted-bits count is unary, so it can exceed the depth: 17 of 16 bits left a negative width
        # that read(n) widened the cache with and signed(n) shifted by (ValueError: negative shift count)
        self.hostile("wasted17.flac", streaminfo(44100, 1, 16, 8) + hand_frame(8, [constant(1, wasted=17)]), "wastes 17")
        self.hostile("wasted16.flac", streaminfo(44100, 1, 16, 8) + hand_frame(8, [constant(0, wasted=16)]), "wastes 16")
        _, chans, _ = flacfile.decode(streaminfo(44100, 1, 16, 8) + hand_frame(8, [constant(5, wasted=3)]))
        self.assertEqual(chans[0], [40] * 8, "a legal count still shifts the samples back up")

    def test_cli_exit_codes(self):
        bad, corrupt = self.dir / "bad.flac", self.dir / "corrupt.flac"
        bad.write_bytes(b"not flac at all")
        data = bytearray(self.data("mono16"))
        data[-10] ^= 0xFF
        corrupt.write_bytes(bytes(data))
        rc, out = self.run_tool("info", bad)
        self.assertEqual(rc, 2, out)
        self.assertIn("[error]", out)
        rc, out = self.run_tool("info", corrupt)
        self.assertEqual(rc, 1, out)
        self.assertNotIn("Traceback", out)
        rc, out = self.run_tool("info", self.dir / "missing.flac")
        self.assertEqual(rc, 2, out)


if __name__ == "__main__":
    unittest.main(verbosity=1)

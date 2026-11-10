#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_audioio.py
# Purpose : Exam for audioio.py: formats are recognised by their bytes; WAV reads with nothing installed; without
#           ffmpeg, OGG Vorbis still reads (oggvorbis.py), also behind a Skeleton or Theora page (#262), while MP3 /
#           Opus input (and an Ogg with no Vorbis stream) and OGG output stop with the fix
#           named; a source above full scale warns and exits 1; with a stand-in ffmpeg the decode and
#           encode command lines are right (the OGG loop as LOOPSTART / LOOPLENGTH); the tools that read audio
#           (loudness, dialogue, music) go through it; and, when a real ffmpeg is installed, a WAV -> OGG -> read
#           round trip stays close to the source.
# Usage   : python tools/audio/wavesmith/test_audioio.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import base64
import contextlib
import io
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audioio  # noqa: E402
import loudness  # noqa: E402
from wavfile import read_wav_channels, write_wav  # noqa: E402

RATE = 44100

# A stand-in ffmpeg: logs its arguments, "decodes" by copying a prepared WAV, "encodes" by writing an Ogg header
STUB = r'''
import json, os, shutil, sys
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")
out = args[-1]
if "pcm_s16le" in args:
    shutil.copy(os.environ["STUB_DECODED"], out)
elif out.endswith(".ogg"):
    with open(out, "wb") as fh:
        fh.write(b"OggS" + b"\0" * 24 + b"\x01vorbis" + b"\0" * 20)
    if os.environ.get("STUB_FAIL_AFTER_WRITE"):      # what ffmpeg does on a full disk or a kill: a part-file stays
        sys.stderr.write("stub: no space left on device\n")
        sys.exit(1)
else:
    sys.stderr.write("stub: cannot write " + out + "\n")
    sys.exit(1)
'''


def tone(seconds=0.5, hz=440.0, amp=0.5):
    return [amp * math.sin(2 * math.pi * hz * i / RATE) for i in range(int(seconds * RATE))]


class AudioIOExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def run_tool(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = audioio.main([str(a) for a in argv])
        return rc, out.getvalue() + err.getvalue()

    def no_ffmpeg(self):
        os.environ[audioio.FFMPEG_ENV] = str(self.dir / "no-such-ffmpeg.exe")

    def stub_ffmpeg(self, decoded):
        """Points WAVESMITH_FFMPEG at the stand-in (a .cmd on Windows, a shell script elsewhere)."""
        stub = self.dir / "stub_ffmpeg.py"
        stub.write_text(STUB, encoding="utf-8")
        if os.name == "nt":
            exe = self.dir / "ffmpeg.cmd"
            exe.write_text(f'@"{sys.executable}" -I "{stub}" %*\n', encoding="utf-8")
        else:
            exe = self.dir / "ffmpeg"
            exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{stub}" "$@"\n', encoding="utf-8")
            exe.chmod(0o755)
        os.environ.update({audioio.FFMPEG_ENV: str(exe), "STUB_LOG": str(self.dir / "stub.log"),
                           "STUB_DECODED": str(decoded)})

    def stub_calls(self):
        log = self.dir / "stub.log"
        return [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    # ---- recognising files
    def test_sniff_by_bytes_not_names(self):
        self.assertEqual(audioio.sniff(b"RIFF\0\0\0\0WAVEfmt "), "wav")
        self.assertEqual(audioio.sniff(b"fLaC\0\0\0\x22"), "flac")
        ogg = b"OggS" + b"\0" * 24
        self.assertEqual(audioio.sniff(ogg + b"\x01vorbis\0"), "ogg-vorbis")
        self.assertEqual(audioio.sniff(ogg + b"OpusHead"), "ogg-opus")
        self.assertEqual(audioio.sniff(ogg + b"\x80theora"), "ogg")
        self.assertEqual(audioio.sniff(b"ID3\x04\0\0\0\0\0\0"), "other")

    def test_wav_reads_with_nothing_installed(self):
        self.no_ffmpeg()
        f = self.dir / "a.mp3"                          # the name lies: the bytes are a WAV, and that is what counts
        write_wav(self.dir / "a.wav", tone(), RATE)
        (self.dir / "a.wav").rename(f)
        chans, rate = audioio.read_audio(f)
        self.assertEqual((len(chans), rate, len(chans[0])), (1, RATE, int(0.5 * RATE)))

    @unittest.skipUnless((HERE / "oggvorbis.py").is_file(), "oggvorbis.py is not installed next to audioio.py")
    def test_ogg_vorbis_reads_with_nothing_installed(self):
        from test_oggvorbis import FIXTURES                # a real libvorbis file the decoder's own exam carries
        self.no_ffmpeg()
        f = self.dir / "tone.ogg"
        f.write_bytes(base64.b64decode(FIXTURES["mono22k"]))
        chans, rate = audioio.read_audio(f)
        self.assertEqual((len(chans), rate, len(chans[0])), (1, 22050, 11025))
        rc, out = self.run_tool("info", f)
        self.assertEqual(rc, 0, out)
        self.assertIn("read by oggvorbis.py", out)

    def hide_ffmpeg(self):
        """No ffmpeg anywhere: WAVESMITH_FFMPEG names a missing file and PATH holds only the empty temp folder."""
        self.no_ffmpeg()
        os.environ["PATH"] = str(self.dir)

    def muxed_ogg(self, first_bos, vorbis=True):
        """A hand-built Ogg whose first BOS page carries first_bos (a Skeleton or Theora header) on its own serial.
        vorbis=True: the libvorbis fixture follows, its BOS page second, the other stream's EOS page after it.
        vorbis=False: an Opus BOS page follows instead (a video with Opus sound: no Vorbis anywhere)."""
        from test_oggvorbis import FIXTURES, ogg_page
        other = ogg_page(0x5EED, 0, 0, 2, [first_bos])
        if not vorbis:
            opus = ogg_page(0x0805, 0, 0, 2, [b"OpusHead\x01\x01\x38\x01\x80\xbb\0\0\0\0\0"])
            return other + opus + ogg_page(0x5EED, 1, 0, 4, [b""]) + ogg_page(0x0805, 1, 0, 4, [b""])
        src = base64.b64decode(FIXTURES["mono22k"])
        nseg = src[26]
        cut = 27 + nseg + sum(src[27:27 + nseg])          # the end of the Vorbis BOS page
        return other + src[:cut] + ogg_page(0x5EED, 1, 0, 4, [b""]) + src[cut:]

    @unittest.skipUnless((HERE / "oggvorbis.py").is_file(), "oggvorbis.py is not installed next to audioio.py")
    def test_vorbis_behind_a_skeleton_or_theora_page_reads_with_nothing_installed(self):
        # #262: sniff saw only the first BOS page, so a Vorbis stream behind a Skeleton or Theora header went to
        # ffmpeg, and without ffmpeg the file was refused although oggvorbis.py reads it
        self.hide_ffmpeg()
        heads = {"skeleton": b"fishead\0" + struct.pack("<HH", 3, 0) + b"\0" * 52,
                 "theora": b"\x80theora\x03\x02\x01" + b"\0" * 33}
        for name, head in heads.items():
            f = self.dir / f"{name}.ogg"
            f.write_bytes(self.muxed_ogg(head))
            with self.subTest(name):
                chans, rate = audioio.read_audio(f)
                self.assertEqual((len(chans), rate, len(chans[0])), (1, 22050, 11025))
                srate, nch, chunks = audioio.stream_audio(f)
                self.assertEqual((srate, nch), (22050, 1))
                self.assertEqual([s for p in chunks() for s in p[0]], chans[0])
                rc, out = self.run_tool("info", f)
                self.assertEqual(rc, 0, out)
                self.assertIn("ogg-vorbis", out)
                self.assertIn("read by oggvorbis.py", out)
                # the fixture peaks a hair above full scale, so convert warns and exits 1 (its own exam): what
                # matters here is that it decoded natively and wrote the WAV
                rc, out = self.run_tool("convert", f, "--out", self.dir / f"{name}.wav")
                self.assertNotIn("needs ffmpeg", out)
                self.assertTrue((self.dir / f"{name}.wav").is_file(), out)

    def test_an_ogg_without_vorbis_still_goes_to_ffmpeg(self):
        # #262's other side: an Ogg with no Vorbis stream (Opus first, or Opus behind a Theora page) is ffmpeg's
        from test_oggvorbis import ogg_page
        muxed = self.dir / "video-with-opus.ogg"
        muxed.write_bytes(self.muxed_ogg(b"\x80theora\x03\x02\x01" + b"\0" * 33, vorbis=False))
        opus = self.dir / "voice.opus"
        opus.write_bytes(ogg_page(7, 0, 0, 2, [b"OpusHead\x01\x01\x38\x01\x80\xbb\0\0\0\0\0"])
                         + ogg_page(7, 1, 0, 4, [b"OpusTags\0\0\0\0\0\0\0\0"]))
        self.hide_ffmpeg()
        for f in (muxed, opus):
            with self.subTest(f.name):
                for read in (audioio.read_audio, audioio.stream_audio):
                    with self.assertRaises(audioio.AudioIOError) as ctx:
                        read(f)
                    self.assertIn("needs ffmpeg", str(ctx.exception), read.__name__)
        decoded = self.dir / "decoded_by_stub.wav"
        write_wav(decoded, tone(), RATE)
        self.stub_ffmpeg(decoded)
        for f in (muxed, opus):
            with self.subTest(f.name):
                before = len(self.stub_calls())
                self.assertEqual(audioio.read_audio(f)[1], RATE)
                rate, _, chunks = audioio.stream_audio(f)
                list(chunks())
                self.assertEqual(len(self.stub_calls()) - before, 2, "both reads went through ffmpeg")

    def test_a_source_above_full_scale_warns_and_exits_1(self):
        self.no_ffmpeg()
        loud = [0.5] * 100 + [1.2] * 3                      # lossy decoders can overshoot full scale a little
        fake = type("FakeVorbis", (), {"decode": staticmethod(lambda data: ({"rate": RATE}, [loud], []))})
        real = audioio.oggvorbis_module
        audioio.oggvorbis_module = lambda: fake
        try:
            src = self.dir / "loud.ogg"
            src.write_bytes(b"OggS" + b"\0" * 24 + b"\x01vorbis" + b"\0" * 20)
            rc, out = self.run_tool("convert", src, "--out", self.dir / "loud.wav")
        finally:
            audioio.oggvorbis_module = real
        self.assertEqual(rc, 1, out)
        self.assertIn("[warn]", out)
        self.assertIn("3 samples clipped", out)
        self.assertNotIn("[ OK ]", out)

    # ---- without ffmpeg
    def test_without_ffmpeg_other_formats_name_the_fix(self):
        self.no_ffmpeg()
        mp3 = self.dir / "door.mp3"
        mp3.write_bytes(b"ID3\x04" + b"\0" * 200)
        with self.assertRaises(audioio.AudioIOError) as ctx:
            audioio.read_audio(mp3)
        self.assertIn("needs ffmpeg", str(ctx.exception))
        self.assertIn("convert it to WAV, FLAC or OGG Vorbis", str(ctx.exception))
        with self.assertRaises(audioio.AudioIOError) as ctx:
            audioio.write_audio(self.dir / "out.ogg", [tone()], RATE)
        self.assertIn("write a .wav", str(ctx.exception))
        rc, out = self.run_tool("check")
        self.assertEqual(rc, 0)
        self.assertIn("no ffmpeg", out)
        rc, out = self.run_tool("info", mp3)
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", out)

    def test_a_sample_rate_the_wav_cannot_hold_is_an_error_not_a_traceback(self):
        # a WAV (or Vorbis) header can say 0xFFFFFFFF Hz; convert read it and write_wav's byte-rate field
        # overflowed as struct.error, a raw traceback instead of [error]
        self.no_ffmpeg()
        fmt = struct.pack("<HHIIHH", 1, 1, 0xFFFFFFFF, 0xFFFFFFFF, 2, 16)
        data = struct.pack("<8h", *([100] * 8))
        body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(data)) + data
        src = self.dir / "hz.wav"
        src.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
        rc, out = self.run_tool("info", src)
        self.assertEqual(rc, 0, out)
        rc, out = self.run_tool("convert", src, "--out", self.dir / "hz16.wav")
        self.assertEqual(rc, 2, out)
        self.assertIn("[error]", out)
        self.assertNotIn("Traceback", out)
        with self.assertRaises(audioio.AudioIOError):
            audioio.write_audio(self.dir / "w.wav", [[0.0] * 4], 0xFFFFFFFF)

    def adpcm_wav(self):
        """A WAV in a sample format wavfile.py does not read (IMA ADPCM, tag 0x11)."""
        fmt = struct.pack("<HHIIHH", 0x11, 1, RATE, RATE // 2, 256, 4)
        body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", 512) + b"\0" * 512
        path = self.dir / "adpcm.wav"
        path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
        return path

    def test_a_wav_format_wavfile_does_not_read_names_ffmpeg(self):
        # #102: the error named no way out, and ffmpeg was never tried for a RIFF/WAVE file
        self.no_ffmpeg()
        wav = self.adpcm_wav()
        for read in (audioio.read_audio, audioio.stream_audio, loudness.measure_file):
            with self.assertRaises((audioio.AudioIOError, loudness.ToolError)) as ctx:
                read(wav)
            self.assertIn("ffmpeg", str(ctx.exception), read.__name__)
        rc, out = self.run_tool("info", wav)
        self.assertEqual(rc, 2, out)
        self.assertNotIn("Traceback", out)

    # ---- with a stand-in ffmpeg
    def test_a_wav_format_wavfile_does_not_read_goes_through_ffmpeg(self):
        decoded = self.dir / "decoded_by_stub.wav"
        write_wav(decoded, tone(seconds=1.0, amp=0.25), RATE)
        self.stub_ffmpeg(decoded)
        wav = self.adpcm_wav()
        chans, rate = audioio.read_audio(wav)
        self.assertEqual((len(chans), rate, len(chans[0])), (1, RATE, RATE))
        rate, nch, chunks = audioio.stream_audio(wav)
        self.assertEqual(sum(len(p[0]) for p in chunks()), RATE)
        self.assertIsNotNone(loudness.measure_file(wav, want_tp=False)["integrated_lufs"])
        self.assertEqual(len(self.stub_calls()), 3)
        rc, out = self.run_tool("info", wav)
        self.assertEqual(rc, 0, out)
        self.assertIn("read by ffmpeg", out)

    def test_decode_and_encode_command_lines(self):
        decoded = self.dir / "decoded_by_stub.wav"
        write_wav(decoded, [s for frame in zip(tone(hz=220), tone(hz=330)) for s in frame], RATE, channels=2)
        self.stub_ffmpeg(decoded)
        mp3 = self.dir / "theme.mp3"
        mp3.write_bytes(b"ID3\x04" + b"\0" * 200)
        chans, rate = audioio.read_audio(mp3)
        self.assertEqual((len(chans), rate), (2, RATE))
        call = self.stub_calls()[-1]
        self.assertEqual(call[:8], ["-nostdin", "-v", "error", "-protocol_whitelist", "file", "-i", str(mp3.resolve()),
                                    "-c:a"])                # local files only: no URL from a playlist-style input
        self.assertIn("pcm_s16le", call)
        src = self.dir / "loop.wav"
        body = tone(seconds=1.0)
        write_wav(src, body, RATE, loop=(0, len(body) - 1))
        rc, out = self.run_tool("convert", src, "--out", self.dir / "loop.ogg", "--loop", "--quality", 5)
        self.assertEqual(rc, 0, out)
        call = self.stub_calls()[-1]
        self.assertIn("libvorbis", call)
        self.assertEqual(call[call.index("-protocol_whitelist") + 1], "file")
        self.assertEqual(call[call.index("-q:a") + 1], "5")
        self.assertIn(f"LOOPSTART=0", call)
        self.assertIn(f"LOOPLENGTH={len(body)}", call)
        self.assertIn("kept as LOOPSTART / LOOPLENGTH", out)
        rc, out = self.run_tool("convert", src, "--out", self.dir / "loop.ogg")
        self.assertEqual(rc, 2)                              # exists: refused, not replaced
        self.assertIn("use --overwrite", out)

    def test_the_tools_that_read_audio_go_through_it(self):
        decoded = self.dir / "decoded_by_stub.wav"
        write_wav(decoded, tone(seconds=2.0, amp=0.25), RATE)
        self.stub_ffmpeg(decoded)
        mp3 = self.dir / "line.mp3"
        mp3.write_bytes(b"ID3\x04" + b"\0" * 200)
        m = loudness.measure_file(mp3, want_tp=False)        # loudness, and so the events audit, reads MP3 now
        self.assertIsNotNone(m["integrated_lufs"])
        import dialogue
        levels, rate = dialogue.read_mono(mp3)
        self.assertEqual((rate, len(levels)), (RATE, 2 * RATE))
        import music
        samples, rate, ch = music.read_interleaved(mp3)
        self.assertEqual((ch, len(samples)), (1, 2 * RATE))

    def test_stream_audio_hands_out_chunks_and_deletes_ffmpegs_wav(self):
        decoded = self.dir / "decoded_by_stub.wav"
        write_wav(decoded, tone(seconds=2.5, amp=0.25), RATE)
        self.stub_ffmpeg(decoded)
        mp3 = self.dir / "long.mp3"
        mp3.write_bytes(b"ID3\x04" + b"\0" * 200)
        made, real = [], tempfile.mkdtemp
        try:
            tempfile.mkdtemp = lambda *a, **k: made.append(real(*a, **k)) or made[-1]
            rate, nch, chunks = audioio.stream_audio(mp3)
            parts = list(chunks())
        finally:
            tempfile.mkdtemp = real
        self.assertEqual((rate, nch), (RATE, 1))
        self.assertTrue(all(len(p[0]) <= audioio.CHUNK_FRAMES for p in parts) and len(parts) > 1)
        self.assertEqual([s for p in parts for s in p[0]], audioio.read_audio(mp3)[0][0])
        self.assertEqual(len(made), 1)
        self.assertFalse(Path(made[0]).exists(), "ffmpeg's temporary WAV is deleted once read")

    def test_ffmpegs_wav_is_deleted_even_when_the_chunks_are_never_read(self):
        # a caller that stops between stream_audio() and iterating chunks() (an error in between) never ran the
        # generator's finally, so ffmpeg's decoded WAV stayed in the temp folder for good; only the process
        # ending can prove the backstop, so this runs in one
        decoded = self.dir / "decoded_by_stub.wav"
        write_wav(decoded, tone(seconds=0.5, amp=0.25), RATE)
        self.stub_ffmpeg(decoded)
        mp3 = self.dir / "drop.mp3"
        mp3.write_bytes(b"ID3\x04" + b"\0" * 200)
        script = (f"import sys, tempfile; sys.path.insert(0, {str(HERE)!r})\n"
                  "import audioio\n"
                  "made, real = [], tempfile.mkdtemp\n"
                  "tempfile.mkdtemp = lambda *a, **k: made.append(real(*a, **k)) or made[-1]\n"
                  f"rate, nch, chunks = audioio.stream_audio({str(mp3)!r})\n"
                  "print(made[0])\n")
        r = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        tmp = Path(r.stdout.strip().splitlines()[-1])
        try:
            self.assertFalse(tmp.exists(), f"{tmp}: ffmpeg's temporary WAV must go when the process ends")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_failed_encode_leaves_no_file_and_keeps_the_old_one(self):
        # ffmpeg wrote straight onto the destination: a run that died part-way (a timeout, a full disk) left a
        # broken file there, and with --overwrite replaced a good file with it
        decoded = self.dir / "decoded_by_stub.wav"
        write_wav(decoded, tone(), RATE)
        self.stub_ffmpeg(decoded)
        os.environ["STUB_FAIL_AFTER_WRITE"] = "1"
        src = self.dir / "s.wav"
        write_wav(src, tone(), RATE)
        out = self.dir / "theme.ogg"
        rc, text = self.run_tool("convert", src, "--out", out)
        self.assertEqual(rc, 2, text)
        self.assertIn("could not write", text)
        self.assertFalse(out.exists(), "a failed encode leaves nothing behind")
        out.write_bytes(b"the good file")
        rc, text = self.run_tool("convert", src, "--out", out, "--overwrite")
        self.assertEqual(rc, 2, text)
        self.assertEqual(out.read_bytes(), b"the good file", "a failed encode never replaces the file that was there")
        self.assertEqual([p.name for p in self.dir.glob("*.ogg*")], ["theme.ogg"], "no staged file next to it")
        del os.environ["STUB_FAIL_AFTER_WRITE"]
        rc, text = self.run_tool("convert", src, "--out", out, "--overwrite")
        self.assertEqual(rc, 0, text)
        self.assertTrue(out.read_bytes().startswith(b"OggS"), "a good encode lands on the destination")

    # ---- a real ffmpeg, when there is one
    @unittest.skipUnless(shutil.which("ffmpeg"), "no ffmpeg on PATH: the real round trip is skipped")
    def test_real_round_trip_wav_to_ogg_and_back(self):
        os.environ.pop(audioio.FFMPEG_ENV, None)
        src = tone(seconds=1.0, hz=440.0, amp=0.5)
        out = self.dir / "round.ogg"
        audioio.write_audio(out, [src], RATE, quality=8)
        chans, rate = audioio.read_audio(out)
        self.assertEqual(rate, RATE)
        n = min(len(src), len(chans[0]))
        self.assertGreater(n, int(0.95 * RATE))
        err = max(abs(a - b) for a, b in zip(src[2000:n - 2000], chans[0][2000:n - 2000]))
        self.assertLess(err, 0.05, "a 440 Hz tone at quality 8 comes back close to the source")


if __name__ == "__main__":
    unittest.main(verbosity=1)

#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_loudness.py
# Purpose : Exam for loudness.py against the published compliance signals: the K-weighting equals ITU-R BS.1770-5
#           Tables 1 and 2, EBU Tech 3341 (2023) cases 1-5 (integrated loudness) and 15-23 (true peak), EBU Tech
#           3342 (2023) cases 1-4 (loudness range), plus check-mix against ASWG-R001 v1.10, normalize, FLAC input
#           and the command line.
# Usage   : python tools/audio/test_loudness.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Signals are synthesized here at 48 kHz exactly as the EBU documents describe them (cases 7-8 and 3342
#           cases 5-6 use EBU's authentic programme files, which are not redistributed with the kit). Cases 20-23
#           are rebuilt from their description: synthesized at 4 x fs, low-pass filtered, downsampled at offsets 0-3.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loudness as L  # noqa: E402
from wavfile import read_wav_channels, write_wav  # noqa: E402

FS = 48000


def tone(dbfs, seconds, freq=1000.0, rate=FS):
    """Sine with the given per-channel PEAK level (EBU's convention), as one channel list."""
    a = 10 ** (dbfs / 20)
    return [a * math.sin(2 * math.pi * freq * i / rate) for i in range(int(round(seconds * rate)))]


def bursts(dbfs, seconds, rate=FS):
    """1 kHz bursts (50 ms on, 150 ms off): measurable loudness with a game-like crest, so the true-peak search
    stays cheap where true peak is not what a test is about."""
    a, on, period = 10 ** (dbfs / 20), int(0.05 * rate), int(0.2 * rate)
    return [a * math.sin(2 * math.pi * 1000 * i / rate) if i % period < on else 0.0 for i in range(int(seconds * rate))]


def stereo(ch):
    return [ch, list(ch)]


def tapered(ch, rate=FS, fade_s=0.01):
    n = int(fade_s * rate)
    out = list(ch)
    for i in range(n):
        out[i] *= i / n
        out[-1 - i] *= i / n
    return out


def lowpass_decimate(x, factor, offset, taps=127, cutoff=0.45):
    """Windowed-sinc low-pass at `cutoff` of the output Nyquist, then keep every `factor`-th sample from `offset`."""
    h = []
    for i in range(taps):
        t = i - (taps - 1) / 2
        w = 0.42 - 0.5 * math.cos(2 * math.pi * i / (taps - 1)) + 0.08 * math.cos(4 * math.pi * i / (taps - 1))
        fc = cutoff / factor
        h.append((2 * fc * (math.sin(2 * math.pi * fc * t) / (2 * math.pi * fc * t) if t else 1.0)) * w)
    s = sum(h)
    h = [c / s for c in h]
    out = []
    for n in range(offset, len(x) - taps, factor):
        out.append(sum(c * x[n + k] for k, c in enumerate(h)))
    return out


class LoudnessExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = L.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    def wav(self, name, channels, rate=FS):
        path = self.dir / name
        write_wav(path, [s for frame in zip(*channels) for s in frame], rate, channels=len(channels))
        return path

    def measure(self, channels, rate=FS, tp=False):
        return L.measure_channels(channels, rate, want_tp=tp)

    # ---- BS.1770-5
    def test_k_weighting_equals_bs1770_tables_at_48k(self):
        shelf, highpass = L.k_weighting(48000)
        table1 = (1.53512485958697, -2.69169618940638, 1.19839281085285, -1.69065929318241, 0.73248077421585)
        table2 = (1.0, -2.0, 1.0, -1.99004745483398, 0.99007225036621)
        for got, want in zip(shelf + highpass, table1 + table2):
            self.assertAlmostEqual(got, want, places=12)

    # ---- EBU Tech 3341 Table 1, integrated loudness (tolerance +/-0.1 LU)
    def test_3341_case_1_and_2_steady_tones(self):
        self.assertAlmostEqual(self.measure(stereo(tone(-23, 20)))["integrated_lufs"], -23.0, delta=0.1)
        self.assertAlmostEqual(self.measure(stereo(tone(-33, 20)))["integrated_lufs"], -33.0, delta=0.1)

    def test_3341_case_3_and_4_gates_ignore_quiet_parts(self):
        case3 = tone(-36, 10) + tone(-23, 60) + tone(-36, 10)
        self.assertAlmostEqual(self.measure(stereo(case3))["integrated_lufs"], -23.0, delta=0.1)
        case4 = tone(-72, 10) + tone(-36, 10) + tone(-23, 60) + tone(-36, 10) + tone(-72, 10)
        self.assertAlmostEqual(self.measure(stereo(case4))["integrated_lufs"], -23.0, delta=0.1)

    def test_3341_case_5_relative_gate(self):
        case5 = tone(-26, 20) + tone(-20, 20.1) + tone(-26, 20)
        self.assertAlmostEqual(self.measure(stereo(case5))["integrated_lufs"], -23.0, delta=0.1)

    # ---- EBU Tech 3342 Table 1, loudness range (tolerance +/-1 LU)
    def test_3342_cases_1_to_4(self):
        for levels, want in (((-20, -30), 10), ((-20, -15), 5), ((-40, -20), 20), ((-50, -35, -20, -35, -50), 15)):
            ch = [s for lvl in levels for s in tone(lvl, 20)]
            self.assertAlmostEqual(self.measure(stereo(ch))["lra_lu"], want, delta=1.0, msg=str(levels))

    def test_3342_absolute_gate_drops_near_silence(self):
        # 20 s at -60 dBFS, then 20 s at -72 dBFS (below the -70 LUFS absolute gate): only the first part counts.
        # Without the gate the quiet part would widen the range to 12 LU.
        rate = 16000
        ch = tone(-60, 20, rate=rate) + tone(-72, 20, rate=rate)
        self.assertLess(self.measure(stereo(ch), rate)["lra_lu"], 3.0)

    def test_true_peak_of_clipped_audio_matches_ideal_reconstruction(self):
        # Hard-clipped noise, band-limited to 0.48 x fs (like generated or mastered audio with energy close to
        # Nyquist), against its Whittaker-Shannon reconstruction (the ideal, computed here at 32 points per gap).
        # The K01 defect, a short interpolator, under-read real clipped game audio by up to 0.84 dB: on this
        # signal a 24-tap filter misses by about 0.6 dB and plain 4x by about 0.3; the kit's filter by 0.03.
        for seed in (7, 11, 23):
            x, s = [], seed
            for _ in range(420):
                s = (1103515245 * s + 12345) & 0x7FFFFFFF
                x.append(max(-0.45, min(0.45, ((s >> 8) % 20001 - 10000) / 10000 * 1.5)))
            x = lowpass_decimate(x, 1, 0, taps=151, cutoff=0.48)[80:-20]
            n = len(x)
            for i in range(24):
                x[i] *= i / 24
                x[-1 - i] *= i / 24
            ideal = max(abs(v) for v in x)
            for g in range(n - 1):
                for k in range(1, 32):
                    t = g + k / 32
                    ideal = max(ideal, abs(sum(x[m] * math.sin(math.pi * (t - m)) / (math.pi * (t - m)) for m in range(n))))
            got = self.measure([x], FS, tp=True)["true_peak_dbtp"]
            self.assertAlmostEqual(got, 20 * math.log10(ideal), delta=0.15, msg=f"seed {seed}")

    # ---- EBU Tech 3341 cases 15-23, true peak (tolerance +0.2 / -0.4 dB)
    def test_3341_cases_15_to_19_inter_sample_peaks(self):
        cases = ((4, 0.50, 0.0, -6.0), (4, 0.50, 45.0, -6.0), (6, 0.50, 60.0, -6.0), (8, 0.50, 67.5, -6.0),
                 (4, 1.41, 45.0, 3.0))
        for div, amp, phase, want in cases:
            ch = tapered([amp * math.sin(2 * math.pi * (FS / div) * i / FS + math.radians(phase)) for i in range(FS // 20)], fade_s=0.004)
            got = self.measure(stereo(ch), tp=True)["true_peak_dbtp"]
            self.assertTrue(want - 0.4 <= got <= want + 0.2, f"fs/{div} amp {amp} phase {phase}: {got} dBTP")

    def test_3341_cases_20_to_23_peak_between_samples(self):
        # fs/6 at 0.5 FFS with one period of fs/4 at 1.0 FFS, phase-continuous at zero crossings, made at 4 x fs
        r4 = 4 * FS
        x = [0.5 * math.sin(2 * math.pi * (FS / 6) * i / r4) for i in range(int(0.1 * r4))]
        period6, period4 = 24, 16                     # samples per cycle at 4 x fs for fs/6 and fs/4
        start = (len(x) // 2 // period6) * period6
        burst = [math.sin(2 * math.pi * i / period4) for i in range(period4)]
        x = tapered(x[:start] + burst + x[start:], rate=r4, fade_s=0.005)
        for offset in range(4):
            ch = lowpass_decimate(x, 4, offset)
            got = self.measure(stereo(ch), tp=True)["true_peak_dbtp"]
            self.assertTrue(-0.4 <= got <= 0.2, f"offset {offset}: {got} dBTP")
            self.assertLess(max(abs(s) for s in ch), 0.98, "the samples alone must miss the peak for this to test anything")

    def test_true_peak_at_low_rates_uses_its_own_interpolator(self):
        for rate in (24000, 22050):
            ch = tapered([0.5 * math.sin(2 * math.pi * (rate / 4) * i / rate + math.radians(45)) for i in range(rate // 20)], rate, fade_s=0.004)
            got = self.measure(stereo(ch), rate, tp=True)["true_peak_dbtp"]
            self.assertTrue(-6.4 <= got <= -5.8, f"{rate} Hz: {got} dBTP")

    def test_true_peak_of_near_nyquist_content_is_not_under_read(self):
        # A sine at 0.45 x fs: the samples miss its crest badly, the continuous peak is exactly the amplitude.
        # The 4x example filter of BS.1770 Annex 2, and a 24-tap interpolator, under-read clipped game audio this way
        # by up to 0.84 dB in the K01 check (EBU Tech 3341 allows -0.4).
        # 3/8 x fs: eight sample phases, 45 degrees apart. Both crests (90 and 270 degrees) are a whole number of
        # steps apart, so a 22.5 degree offset keeps every sample 22.5 degrees from either crest (0.69 dB under)
        for rate in (48000, 44100, 24000):
            ch = tapered([0.5 * math.sin(2 * math.pi * 3 / 8 * i + math.radians(22.5)) for i in range(rate // 20)], rate,
                         fade_s=0.004)
            self.assertLess(20 * math.log10(max(abs(s) for s in ch)), -6.5, "samples must miss the crest")
            got = self.measure(stereo(ch), rate, tp=True)["true_peak_dbtp"]
            self.assertAlmostEqual(got, 20 * math.log10(0.5), delta=0.1, msg=f"{rate} Hz")

    def test_short_clips_report_undefined_not_zero(self):
        m = self.measure(stereo(tone(-20, 0.3)), tp=True)
        self.assertIsNone(m["integrated_lufs"], "under one 400 ms block")
        self.assertIsNone(m["lra_lu"], "no full 3 s window")
        self.assertIsNotNone(m["true_peak_dbtp"])
        self.assertIsNone(self.measure(stereo(tone(-20, 2.5)))["lra_lu"])
        self.assertIsNotNone(self.measure(stereo(tone(-20, 3.2)))["lra_lu"])

    # ---- check-mix (ASWG-R001 v1.10)
    def test_check_mix_refuses_a_short_capture_unless_asked(self):
        cap = self.wav("cap.wav", stereo(bursts(-18, 12)))
        rc, out = self.run_tool("check-mix", cap, "--target", "home")
        self.assertEqual(rc, 1, out)
        self.assertIn("at least 30 min", out)
        rc, out = self.run_tool("check-mix", cap, "--target", "home", "--allow-short")
        self.assertEqual(rc, 0, out)
        self.assertIn("provisional", out)

    def test_check_mix_targets_and_true_peak(self):
        real = L.ASWG_MIN_S
        L.ASWG_MIN_S = 2                              # judge a 3 s stand-in capture as if it were long enough
        try:
            home = self.wav("home.wav", stereo(bursts(-18.0 + (-24.0 - L.measure_channels(stereo(bursts(-18, 3)), FS, False)["integrated_lufs"]), 3)))
            rc, out = self.run_tool("check-mix", home, "--target", "home")
            self.assertEqual(rc, 0, out)
            rc, out = self.run_tool("check-mix", home, "--target", "portable")
            self.assertEqual(rc, 1, out)
            self.assertIn("outside -20..-16", out)
            hot = self.wav("hot.wav", stereo(tone(-0.5, 3, freq=FS / 4 * 0.999)))
            rc, out = self.run_tool("check-mix", hot, "--target", "portable")
            self.assertEqual(rc, 1, out)
            self.assertIn("true peak", out)
        finally:
            L.ASWG_MIN_S = real

    # ---- normalize and conventions
    def test_normalize_to_lufs_and_bus(self):
        src = self.wav("music.wav", stereo(bursts(-24, 3)))
        rc, out = self.run_tool("normalize", src, "--lufs", -24, "--out", self.dir / "a.wav")
        self.assertEqual(rc, 0, out)
        self.assertAlmostEqual(L.measure_file(self.dir / "a.wav")["integrated_lufs"], -24.0, delta=0.1)
        rc, out = self.run_tool("normalize", src, "--bus", "music", "--target", "home", "--out", self.dir / "b.wav")
        self.assertEqual(rc, 0, out)
        self.assertIn("house convention", out)
        self.assertAlmostEqual(L.measure_file(self.dir / "b.wav")["integrated_lufs"],
                               L.ASWG["home"] + L.HOUSE["music"], delta=0.1)

    def test_normalize_never_pushes_true_peak_over_the_ceiling(self):
        spiky = self.wav("spiky.wav", stereo([0.9 if i % 9600 == 0 else 0.01 * math.sin(i / 7) for i in range(FS * 4)]))
        rc, out = self.run_tool("normalize", spiky, "--lufs", -10, "--out", self.dir / "c.wav")
        self.assertIn("limiter", out)
        self.assertLessEqual(L.measure_file(self.dir / "c.wav")["true_peak_dbtp"], -1.0 + 0.05)

    def test_conventions_are_labeled_not_a_standard(self):
        rc, out = self.run_tool("conventions")
        self.assertEqual(rc, 0, out)
        self.assertIn("NOT part of ASWG-R001", out)

    # ---- input and CLI
    def test_flac_and_wav_of_the_same_audio_measure_the_same(self):
        import base64
        from test_flacfile import FIXTURES, signal
        flac = self.dir / "s.flac"
        flac.write_bytes(base64.b64decode(FIXTURES["stereo16"]))
        wav = self.wav("s.wav", [[v / 32768.0 for v in c] for c in signal("stereo16")], rate=44100)
        a, b = L.measure_file(flac), L.measure_file(wav)
        self.assertEqual((a["integrated_lufs"], a["true_peak_dbtp"]), (b["integrated_lufs"], b["true_peak_dbtp"]))

    def test_measure_json_and_usage_errors(self):
        f = self.wav("x.wav", stereo(tone(-23, 1)))
        rc, out = self.run_tool("measure", f, "--json")
        self.assertEqual(rc, 0, out)
        self.assertAlmostEqual(json.loads(out)[0]["integrated_lufs"], -23.0, delta=0.1)
        for args in (("measure", self.dir / "missing.wav"), ("measure", str(self.dir / "*.nothing")),
                     ("normalize", f, "--out", self.dir / "y.wav"),
                     ("normalize", f, "--lufs", -20, "--bus", "music", "--out", self.dir / "y.wav")):
            rc, out = self.run_tool(*args)
            self.assertEqual(rc, 2, f"{args}: {out}")
            self.assertNotIn("Traceback", out)
        (self.dir / "bad.wav").write_bytes(b"not audio")
        rc, out = self.run_tool("measure", self.dir / "bad.wav")
        self.assertEqual(rc, 2, out)


if __name__ == "__main__":
    unittest.main(verbosity=1)

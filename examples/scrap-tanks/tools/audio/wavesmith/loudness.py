#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# loudness.py
# Purpose : Measure loudness the way broadcast and console audio teams do (ITU-R BS.1770: integrated LUFS, true
#           peak; EBU Tech 3342: loudness range), check a whole-game mix against the Sony ASWG-R001 targets, and
#           normalize single assets to the kit's house levels.
# Usage   : python tools/audio/wavesmith/wavesmith.py loudness measure assets/audio/**/*.wav          # one line per file
#           python tools/audio/wavesmith/wavesmith.py loudness measure build/capture.wav --json         # machine-readable
#           python tools/audio/wavesmith/wavesmith.py loudness check-mix build/gameplay_capture.wav --target home     # or portable
#           python tools/audio/wavesmith/wavesmith.py loudness normalize vo/line.wav --lufs -24 --out vo/line_n.wav
#           python tools/audio/wavesmith/wavesmith.py loudness mono "assets/audio/**/*.wav"          # survives the mono switch?
#           python tools/audio/wavesmith/wavesmith.py loudness normalize amb/rain.wav --bus ambience --target home --out amb/rain_n.wav
#           python tools/audio/wavesmith/wavesmith.py loudness conventions                               # the house levels table
# Needs   : Python 3.8+ only. Reads 16/32-bit PCM WAV (wavfile.py) and 16/24-bit FLAC (flacfile.py), mono/stereo.
# Exit    : 0 ok / within target, 1 out of target, too short to judge, or true peak too high, 2 usage or bad file
# Notes   : Integrated loudness: K-weighting (BS.1770-5 Tables 1-2, re-derived for any sample rate), 400 ms blocks
#           with 75 percent overlap, gates at -70 LKFS and 10 LU below the absolute-gated level. Loudness range:
#           EBU Tech 3342 (3 s short-term loudness at 10 Hz, gates -70 LUFS and -20 LU, 10th to 95th percentile;
#           full windows only, so a file under 3 s has none: "n/a"; LRA of short clips says little, as 3342 notes).
#           True peak: the BS.1770-5 Annex 2 method with a finer interpolator than its 4x example (oversampled to
#           at least 768 kHz, Kaiser-windowed sinc, 64 taps a phase): the 4x example under-read clipped game audio by up to 0.84 dB
#           against an ideal reconstruction, and Annex 2 prefers higher ratios. LUFS and LKFS are the same unit.
#           check-mix applies ASWG-R001 v1.10 as the standard words it: the WHOLE mix (not dialogue, music or SFX
#           separately), measured over at least 30 minutes of representative gameplay; home -24 +/-2 LKFS, portable
#           -18 +/-2 LKFS, true peak at most -1 dBTP. Record a capture with your engine (Godot: --write-movie).
#           Per-asset levels (`normalize --bus`, `conventions`) are kit house conventions, starting points to tune by
#           ear, not part of any standard. Pure Python: about 4 s per minute of stereo 44.1 kHz audio; other
#           material can cost far more (measured: 27 s per minute of 48 kHz stereo tone plus noise).
#           Memory: a WAV is measured as it is read (measure, check-mix), in under 40 MB whatever its length, so a
#           30-minute capture is fine; record captures as WAV. FLAC, OGG and ffmpeg formats are decoded whole first:
#           about 32 bytes per sample, so roughly 180 MB per minute of 48 kHz stereo (convert long ones to WAV).
#           normalize and mono also hold the whole file (they are for single assets).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   read samples per channel (WAV or FLAC)
#   K-weight each channel (two biquads) -> mean square per 100 ms sub-block
#   integrated: 400 ms blocks = 4 sub-blocks -> block loudness -> absolute gate -> relative gate -> gated mean
#   LRA: 3 s windows = 30 sub-blocks every 100 ms -> gates -70 / -20 LU -> 95th minus 10th percentile
#   true peak: polyphase interpolation (>= 768 kHz), only where a window could beat the running maximum
#   check-mix: duration >= 30 min? integrated within target +/-2? true peak <= -1? -> verdict
#   normalize: gain to the target, capped so true peak stays at or below the ceiling (no limiter here)
#   mono: downmix 0.5 * (L + R) (Web Audio's rule; engines' mono switches do the same) -> loudness lost, and the
#         channel correlation overall and per loud 400 ms block -> out-of-phase content cancels
import argparse
import glob
import json
import math
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audioio  # noqa: E402
import flacfile  # noqa: E402
from wavfile import read_wav_channels, wav_stream  # noqa: E402

ABS_GATE = -70.0            # LKFS, BS.1770 and Tech 3342
REL_GATE_I = -10.0          # LU below the absolute-gated loudness, integrated (BS.1770-2 onward)
REL_GATE_LRA = -20.0        # LU, Tech 3342
SUB_S = 0.1                 # 100 ms: the hop of both the 400 ms blocks (75 percent overlap) and the 3 s windows
TP_MIN_RATE = 768000        # oversample to at least this (16x at 48 kHz); see interpolator() for why not 4x
TP_MAX_FACTOR = 16          # ...but never more than 16x
TP_TAPS = 64                # taps per phase; 24 still under-read near-Nyquist content by up to 0.67 dB (K01)
LOCATE_MARGIN = 10 ** (1.5 / 20)   # coarse-locator margin in true_peak()
# BS.1770-5 Annex 2: the order 48, 4-phase FIR interpolator (Phase 0..3 columns, 12 taps each). Used here only to
# locate candidate peaks cheaply; the reading itself comes from the finer filter in interpolator().
ANNEX2 = [
    [0.0017089843750, 0.0109863281250, -0.0196533203125, 0.0332031250000, -0.0594482421875, 0.1373291015625,
     0.9721679687500, -0.1022949218750, 0.0476074218750, -0.0266113281250, 0.0148925781250, -0.0083007812500],
    [-0.0291748046875, 0.0292968750000, -0.0517578125000, 0.0891113281250, -0.1665039062500, 0.4650878906250,
     0.7797851562500, -0.2003173828125, 0.1015625000000, -0.0582275390625, 0.0330810546875, -0.0189208984375],
    [-0.0189208984375, 0.0330810546875, -0.0582275390625, 0.1015625000000, -0.2003173828125, 0.7797851562500,
     0.4650878906250, -0.1665039062500, 0.0891113281250, -0.0517578125000, 0.0292968750000, -0.0291748046875],
    [-0.0083007812500, 0.0148925781250, -0.0266113281250, 0.0476074218750, -0.1022949218750, 0.9721679687500,
     0.1373291015625, -0.0594482421875, 0.0332031250000, -0.0196533203125, 0.0109863281250, 0.0017089843750],
]
# ASWG-R001 v1.10 (August 2013), recommendations 4, 5, 7 and 10
ASWG = {"home": -24.0, "portable": -18.0}
ASWG_TOL = 2.0
ASWG_TP_MAX = -1.0
ASWG_MIN_S = 30 * 60
# Kit house conventions (NOT a standard): where single assets start before the mix is balanced by ear.
# Dialogue anchors at the platform target; beds sit under it. Short one-shots are matched by true peak instead,
# because gated loudness of a sound shorter than one 400 ms block is undefined.
HOUSE = {"dialogue": 0.0, "music": -4.0, "ambience": -10.0, "sfx": -6.0, "ui": -8.0}
# Mono check, kit conventions (not a standard). Downmixing to 0.5 * (L + R) costs 3.0 LU when both channels carry the
# same sound and 6.0 LU when they are unrelated; more than that means the channels cancel each other.
MONO_MAX_LOSS_LU = 9.0
MONO_MIN_BLOCK_CORR = -0.5    # a loud 400 ms block this anti-correlated loses most of itself in mono
DEBUG = False


class ToolError(Exception):
    """Exit 2: usage or a file that cannot be read."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


# ---- Input --------------------------------------------------------------------------
def read_audio(path):
    """(list of channel sample lists in -1..1, rate): WAV, FLAC and OGG Vorbis with the standard library, MP3 /
    Opus / others through ffmpeg when it is installed (audioio.py)."""
    try:
        return audioio.read_audio(path)
    except audioio.AudioIOError as exc:
        raise ToolError(str(exc))


# ---- K-weighting --------------------------------------------------------------------
def k_weighting(rate):
    """Two biquads ((b0,b1,b2),(a1,a2)) giving BS.1770's pre-filter response at `rate`. The analog parameters are
    the ones that reproduce BS.1770-5 Tables 1 and 2 at 48 kHz (the exam checks that to 1e-8)."""
    f0, gain_db, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / rate)
    vh = 10 ** (gain_db / 20)
    vb = vh ** 0.4996667741545416
    a0 = 1 + k / q + k * k
    shelf = ((vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0,
             2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0)
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / rate)
    d = 1 + k / q + k * k
    highpass = (1.0, -2.0, 1.0, 2 * (k * k - 1) / d, (1 - k / q + k * k) / d)
    return shelf, highpass


class KMeter:
    """K-weighting and 100 ms sub-block mean squares for one channel, fed in any number of chunks (the filter
    state carries over, so the result does not depend on where the chunks split). subs: the finished sub-blocks."""

    def __init__(self, rate):
        self.coef = k_weighting(rate)
        self.n = int(round(SUB_S * rate))
        self.state = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)      # x1 x2 y1 y2 z1 z2, the running sum and count
        self.subs = []

    def feed(self, channel):
        (b0, b1, b2, a1, a2), (c0, c1, c2, d1, d2) = self.coef
        n, out = self.n, self.subs
        x1, x2, y1, y2, z1, z2, acc, count = self.state
        for x in channel:
            y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1 = x1, x
            z = c0 * y + c1 * y1 + c2 * y2 - d1 * z1 - d2 * z2
            y2, y1 = y1, y
            z2, z1 = z1, z
            acc += z * z
            count += 1
            if count == n:
                out.append(acc / n)
                acc, count = 0.0, 0
        self.state = (x1, x2, y1, y2, z1, z2, acc, count)


def sub_block_energy(channel, rate):
    """Mean square of the K-weighted channel per 100 ms sub-block (incomplete last sub-block dropped)."""
    m = KMeter(rate)
    m.feed(channel)
    return m.subs


def lk(power):
    return -0.691 + 10 * math.log10(power) if power > 0 else -math.inf


def window_loudness(subs, width):
    """Loudness of every window of `width` sub-blocks, hop one sub-block (channel powers summed, weight 1)."""
    total = [sum(c[i] for c in subs) for i in range(len(subs[0]))] if subs and subs[0] else []
    out, run = [], sum(total[:width])
    for i in range(len(total) - width + 1):
        if i:
            run += total[i + width - 1] - total[i - 1]
        out.append((lk(max(run, 0.0) / width), max(run, 0.0) / width))
    return out


def integrated(blocks):
    above = [p for l, p in blocks if l > ABS_GATE]
    if not above:
        return -math.inf
    rel = lk(sum(above) / len(above)) + REL_GATE_I
    kept = [p for l, p in blocks if l > ABS_GATE and l > rel]
    return lk(sum(kept) / len(kept)) if kept else -math.inf


def loudness_range(windows):
    """EBU Tech 3342 section 3.1 and its reference MATLAB (gates use >=, percentile index round((n-1)p/100 + 1))."""
    st = [l for l, _ in windows if l >= ABS_GATE]
    if not st:
        return 0.0
    rel = 10 * math.log10(sum(10 ** (l / 10) for l in st) / len(st)) + REL_GATE_LRA
    kept = sorted(l for l in st if l >= rel)
    n = len(kept)
    lo = kept[int(math.floor((n - 1) * 10 / 100 + 1 + 0.5)) - 1]
    hi = kept[int(math.floor((n - 1) * 95 / 100 + 1 + 0.5)) - 1]
    return hi - lo


# ---- True peak ----------------------------------------------------------------------
def bessel_i0(x):
    """Modified Bessel function of the first kind, order 0 (series; enough for Kaiser windows)."""
    total, term, k = 1.0, 1.0, 1
    while term > 1e-12 * total:
        term *= (x / (2 * k)) ** 2
        total += term
        k += 1
    return total


_INTERP = {}


def interpolator(rate, factor=None):
    """(factor, phases): Kaiser-windowed sinc polyphase FIR oversampling to at least TP_MIN_RATE (768 kHz).
    BS.1770-5 Annex 2's 4x example under-read real, clipped game audio by up to 0.84 dB against an ideal
    (FFT) reconstruction in the K01 check, beyond EBU Tech 3341's -0.4 dB; Annex 2 itself says higher
    over-sampling ratios are preferred. `factor` overrides, for tests."""
    # Under-reading from too few interpolated points depends on the ratio, not the rate: 16x keeps it under
    # 0.04 dB at any rate, so low-rate files are not oversampled further (that only costs time)
    factor = factor or max(2, min(TP_MAX_FACTOR, math.ceil(TP_MIN_RATE / rate)))
    if factor in _INTERP:
        return factor, _INTERP[factor]
    if factor == 1:
        return 1, [[1.0]]
    n, beta = TP_TAPS * factor, 8.0
    phases = [[0.0] * TP_TAPS for _ in range(factor)]
    i0b = bessel_i0(beta)
    for i in range(n):
        t = (i - (n - 1) / 2) / factor
        w = bessel_i0(beta * math.sqrt(max(0.0, 1 - (2 * i / (n - 1) - 1) ** 2))) / i0b
        phases[i % factor][i // factor] = (math.sin(math.pi * t) / (math.pi * t) if t else 1.0) * w
    for p in phases:                                   # unity DC gain per phase
        s = sum(p)
        p[:] = [c / s for c in p]
    _INTERP[factor] = phases
    return factor, phases


class PeakMeter:
    """True peak over any number of channels, fed in chunks of any size. Each channel keeps a buffer of the samples
    it still needs (two blocks of `taps` plus whatever has not filled a block yet), so memory does not grow with
    the file. best starts at the caller's sample peak; finish() returns the true peak as a linear amplitude."""

    def __init__(self, rate, channels, best=0.0):
        self.factor, self.phases = interpolator(rate)
        self.taps = len(self.phases[0])
        self.bound = max(sum(abs(c) for c in p) for p in self.phases)
        self.best = best
        self.bufs = [[0.0] * self.taps for _ in range(channels)]   # the leading zeros: room for the first window

    def feed(self, chans):
        for buf, ch in zip(self.bufs, chans):
            buf.extend(ch)
            self._scan(buf)

    def finish(self):
        for buf in self.bufs:
            buf.extend([0.0] * (2 * self.taps))                    # the trailing zeros: the last windows
            self._scan(buf)
        return self.best

    def _scan(self, buf):
        """Every complete block whose next block is complete too, then drops them from the buffer's front."""
        taps = self.taps
        blocks = len(buf) // taps - 1
        if blocks < 1:
            return
        self.best = _scan_peaks(buf, blocks, taps, self.factor, self.phases, self.bound, self.best)
        del buf[:blocks * taps]


def _scan_peaks(padded, blocks, taps, factor, phases, bound, best):
    """The running maximum after interpolating the windows that start in blocks 0..blocks-1 of padded."""
    # A window starting in block c lies inside blocks c and c+1, so max(block c, block c+1) bounds it; an
    # interpolated value is at most that bound times the filter's L1 norm. Skip every block that cannot beat
    # the running maximum (most of real audio), interpolate the rest.
    chunk_max = [max(abs(v) for v in padded[k:k + taps]) for k in range(0, (blocks + 1) * taps, taps)]
    for c in range(blocks):
        if max(chunk_max[c], chunk_max[c + 1]) * bound <= best:
            continue
        for i in range(c * taps, (c + 1) * taps):
            # Stage 1: the cheap 12-tap Annex 2 interpolator, centred on the same sample gap as the fine
            # filter, locates candidates; only a window that comes within LOCATE_MARGIN of the running
            # maximum gets the fine filter. The coarse filter under-read real audio by at most 0.84 dB (K01),
            # so a 1.5 dB margin never skips a true maximum, and dense loud mixes stay affordable.
            mid = i + taps // 2 - 6
            coarse_seg = padded[mid:mid + 12][::-1]
            values = [abs(sum(k * x for k, x in zip(p, coarse_seg))) for p in ANNEX2]
            coarse = max(values)
            if coarse * LOCATE_MARGIN <= best:
                continue
            # Stage 2: fine phases around the coarse maximum only (coarse phase q sits at fine phase q*f/4);
            # phases near the gap's edges are covered when the neighbouring gap is refined
            centre = values.index(coarse) * factor // 4
            seg = padded[i:i + taps][::-1]
            for ph in range(max(0, centre - factor // 4), min(factor, centre + factor // 4 + 1)):
                v = abs(sum(k * x for k, x in zip(phases[ph], seg)))
                if v > best:
                    best = v
    return best


def true_peak(channels, rate):
    """Max over channels of the interpolated absolute value, as a linear amplitude."""
    best = max((max((abs(s) for s in ch), default=0.0) for ch in channels), default=0.0)
    meter = PeakMeter(rate, len(channels), best)
    meter.feed(channels)
    return meter.finish()


def db(x):
    return 20 * math.log10(x) if x > 0 else -math.inf


# ---- Measure ------------------------------------------------------------------------
def measure_channels(channels, rate, want_tp=True):
    if not rate or rate < 1:
        raise ToolError(f"a sample rate of {rate} Hz cannot be measured (a broken file)")
    subs = [sub_block_energy(c, rate) for c in channels]
    frames = len(channels[0]) if channels else 0
    sample_peak = max((max((abs(s) for s in c), default=0.0) for c in channels), default=0.0)
    tp = true_peak(channels, rate) if want_tp and sample_peak > 0 else None
    return _result(subs, sample_peak, tp, frames, rate, len(channels))


def _result(subs, sample_peak, tp, frames, rate, nch):
    i_lufs = integrated(window_loudness(subs, 4))
    # Full 3 s windows only, every 100 ms (as ffmpeg's ebur128 does); a file shorter than 3 s has no loudness range
    windows = window_loudness(subs, 30)
    lra = loudness_range(windows) if windows else None
    return {"integrated_lufs": round(i_lufs, 2) if math.isfinite(i_lufs) else None,
            "lra_lu": round(lra, 2) if lra is not None else None,
            "true_peak_dbtp": round(db(tp), 2) if tp is not None and sample_peak > 0 else None,
            "sample_peak_dbfs": round(db(sample_peak), 2) if sample_peak > 0 else None,
            "seconds": round(frames / rate, 3) if rate else 0.0, "rate": rate, "channels": nch}


def measure_wav_stream(path, want_tp=True):
    """measure_channels for a WAV read chunk by chunk: the same numbers in constant memory."""
    try:
        rate, nch, frames, chunks = wav_stream(path)
    except (OSError, ValueError) as exc:
        raise ToolError(str(exc))
    meters = [KMeter(rate) for _ in range(nch)]
    peak_meter = PeakMeter(rate, nch) if want_tp else None
    sample_peak = 0.0
    for chans in chunks():
        sample_peak = max(sample_peak, max((max((abs(s) for s in c), default=0.0) for c in chans), default=0.0))
        for m, c in zip(meters, chans):
            m.feed(c)
        if peak_meter:
            # every sample is a candidate; starting from the running sample peak only skips windows that cannot win
            peak_meter.best = max(peak_meter.best, sample_peak)
            peak_meter.feed(chans)
    tp = peak_meter.finish() if peak_meter and sample_peak > 0 else None
    return _result([m.subs for m in meters], sample_peak, tp, frames, rate, nch)


def measure_file(path, want_tp=True):
    try:
        with Path(path).open("rb") as f:
            is_wav = audioio.sniff(f.read(16)) == "wav"
    except OSError as exc:
        raise ToolError(f"cannot read {path}: {exc}")
    if is_wav:                              # any length in constant memory
        return measure_wav_stream(path, want_tp)
    channels, rate = read_audio(path)
    return measure_channels(channels, rate, want_tp)


def fmt(v, unit):
    return f"{v:6.1f} {unit}" if v is not None else f"   n/a {unit}"


# ---- Commands -----------------------------------------------------------------------
def expand(patterns):
    files = []
    for p in patterns:
        hits = sorted(glob.glob(p, recursive=True)) if any(ch in p for ch in "*?[") else [p]
        files += [h for h in hits if Path(h).is_file()]
        if not hits or not any(Path(h).is_file() for h in hits):
            raise ToolError(f"no audio file matches {p}")
    return files


def cmd_measure(args):
    rows = []
    for f in expand(args.files):
        m = dict(measure_file(f, not args.no_true_peak), file=Path(f).as_posix())
        rows.append(m)
        if not args.json:
            print(f"{fmt(m['integrated_lufs'], 'LUFS')}  LRA {fmt(m['lra_lu'], 'LU')}  TP {fmt(m['true_peak_dbtp'], 'dBTP')}"
                  f"  {m['seconds']:8.2f} s  {m['file']}")
    if args.json:
        print(json.dumps(rows, indent=1))
    return 0


def correlation(left, right):
    """Phase correlation of two channels, -1 (opposite) .. +1 (identical); 0 for silence."""
    lr = sum(a * b for a, b in zip(left, right))
    ll, rr = sum(a * a for a in left), sum(b * b for b in right)
    return lr / math.sqrt(ll * rr) if ll > 0 and rr > 0 else 0.0


def mono_check(channels, rate):
    """What a stereo sound loses in a mono downmix (0.5 * (L + R)): {stereo_lufs, mono_lufs, loss_lu, corr,
    worst_block_corr, worst_block_s}. None for mono input. Loudness is integrated when the clip is long enough,
    otherwise ungated over the whole clip, so short one-shots get a number too."""
    if len(channels) != 2:
        return None
    left, right = channels
    mono = [0.5 * (a + b) for a, b in zip(left, right)]

    def lufs(chans):
        subs = [sub_block_energy(c, rate) for c in chans]
        v = integrated(window_loudness(subs, 4))
        if not math.isfinite(v):                     # under 400 ms or very quiet: plain K-weighted mean
            total = [sum(c[i] for c in subs) for i in range(len(subs[0]))] if subs and subs[0] else []
            v = lk(sum(total) / len(total)) if total else -math.inf
        return v
    st, mo = lufs([left, right]), lufs([mono])
    n = int(round(0.4 * rate))
    worst, worst_t = 1.0, None
    gate = 10 ** ((ABS_GATE + 0.691) / 10)
    for i in range(0, max(len(left) - n + 1, 1), n // 4 or 1):
        l, r = left[i:i + n], right[i:i + n]
        power = (sum(a * a for a in l) + sum(b * b for b in r)) / max(len(l), 1)
        if power > gate:
            c = correlation(l, r)
            if c < worst:
                worst, worst_t = c, i / rate
    loss = (st - mo) if math.isfinite(st) and math.isfinite(mo) else (math.inf if math.isfinite(st) else None)
    return {"stereo_lufs": round(st, 2) if math.isfinite(st) else None,
            "mono_lufs": round(mo, 2) if math.isfinite(mo) else None,
            "loss_lu": (round(loss, 2) if loss is not None and math.isfinite(loss) else loss),
            "corr": round(correlation(left, right), 3),
            "worst_block_corr": round(worst, 3) if worst_t is not None else None,
            "worst_block_s": round(worst_t, 2) if worst_t is not None else None}


def cmd_mono(args):
    rows, bad = [], 0
    for f in expand(args.files):
        channels, rate = read_audio(f)
        r = mono_check(channels, rate)
        name = Path(f).as_posix()
        if r is None:
            rows.append({"file": name, "mono": True})
            if not args.json:
                print(f"[mono] {name}: already mono")
            continue
        problems = []
        if r["loss_lu"] is not None and r["loss_lu"] > args.max_loss:
            problems.append(f"loses {r['loss_lu']:.1f} LU in mono (more than {args.max_loss:.0f}: the channels cancel)")
        if r["worst_block_corr"] is not None and r["worst_block_corr"] < args.min_corr:
            problems.append(f"correlation {r['worst_block_corr']:+.2f} at {r['worst_block_s']:.1f} s (out of phase: "
                            "that part fades or vanishes in mono)")
        bad += bool(problems)
        rows.append(dict(r, file=name, problems=problems))
        if not args.json:
            loss = "silent" if r["loss_lu"] is None else f"{r['loss_lu']:5.1f} LU"
            print(f"[{'FAIL' if problems else ' OK '}] mono loss {loss}  correlation {r['corr']:+.2f}  {name}" +
                  "".join(f"\n       - {p}" for p in problems))
    if args.json:
        print(json.dumps(rows, indent=1))
    else:
        print(f"[{'FAIL' if bad else ' OK '}] {len(rows)} file(s), {bad} would suffer in mono (players with hearing in "
              "one ear use the mono switch)")
    return 1 if bad else 0


def cmd_check_mix(args):
    m = measure_file(args.capture)
    target, minutes = ASWG[args.target], m["seconds"] / 60
    lines = [f"ASWG-R001 v1.10, {args.target} target {target:.0f} +/-{ASWG_TOL:.0f} LKFS, true peak <= {ASWG_TP_MAX:.0f} dBTP",
             f"capture: {minutes:.1f} min, integrated {fmt(m['integrated_lufs'], 'LKFS')}, LRA {fmt(m['lra_lu'], 'LU')}, "
             f"true peak {fmt(m['true_peak_dbtp'], 'dBTP')}"]
    problems = []
    if m["integrated_lufs"] is None:
        problems.append("the capture is silent (no block above -70 LKFS)")
    elif abs(m["integrated_lufs"] - target) > ASWG_TOL:
        problems.append(f"integrated {m['integrated_lufs']:.1f} LKFS is outside {target - ASWG_TOL:.0f}..{target + ASWG_TOL:.0f}: "
                        f"move the master by {target - m['integrated_lufs']:+.1f} dB")
    if m["true_peak_dbtp"] is not None and m["true_peak_dbtp"] > ASWG_TP_MAX:
        problems.append(f"true peak {m['true_peak_dbtp']:.1f} dBTP is above {ASWG_TP_MAX:.0f} dBTP (lower the loudest bus "
                        "or add a true-peak limiter on the master)")
    short = m["seconds"] < ASWG_MIN_S
    for line in lines:
        print(line)
    for p in problems:
        print(f"[FAIL] {p}")
    if short:
        msg = (f"the capture is {minutes:.1f} min; ASWG-R001 asks for at least {ASWG_MIN_S // 60} min of representative "
               "gameplay (all parts of the game), measured as one whole mix")
        if not args.allow_short:
            print(f"[FAIL] {msg}. Record a longer capture, or pass --allow-short for a provisional reading")
            return 1
        print(f"[warn] {msg}: this result is provisional")
    if problems:
        return 1
    print(f"[ OK ] the whole mix is within ASWG-R001 {args.target} targets" + (" (provisional)" if short else ""))
    return 0


def cmd_normalize(args):
    if (args.lufs is None) == (args.bus is None):
        raise ToolError("give --lufs <target> or --bus <name> (with --target home|portable)")
    out = Path(args.out)
    if out.exists() and not args.overwrite:
        raise ToolError(f"{out} exists (use --overwrite)")
    channels, rate = read_audio(args.file)
    m = measure_channels(channels, rate)
    if args.bus:
        goal = ASWG[args.target] + HOUSE[args.bus]
        label = f"{args.bus} house level {goal:.0f} LUFS ({args.target}; kit house convention, not a standard)"
    else:
        goal, label = args.lufs, f"{args.lufs:.1f} LUFS"
    if m["integrated_lufs"] is None:
        if m["true_peak_dbtp"] is None:
            raise ToolError(f"{args.file} is silent")
        gain = args.tp_ceiling - m["true_peak_dbtp"]          # too short for gated loudness: match by true peak
        print(f"[note] {args.file} is shorter than one 400 ms block or too quiet for gated loudness; matched by true peak")
    else:
        gain = goal - m["integrated_lufs"]
        if m["true_peak_dbtp"] + gain > args.tp_ceiling:
            capped = args.tp_ceiling - m["true_peak_dbtp"]
            print(f"[warn] reaching {label} needs {gain:+.1f} dB, but true peak would pass {args.tp_ceiling:.1f} dBTP; "
                  f"applied {capped:+.1f} dB (a limiter would be needed for the rest)")
            gain = capped
    g = 10 ** (gain / 20)
    try:                                    # any format audioio writes: .wav natively, .ogg and others via ffmpeg
        clipped = audioio.write_audio(out, [[s * g for s in c] for c in channels], rate)
    except audioio.AudioIOError as exc:
        raise ToolError(str(exc))
    after = measure_file(out)
    print(f"[ OK ] {out.as_posix()}: {gain:+.2f} dB -> {fmt(after['integrated_lufs'], 'LUFS')}, "
          f"true peak {fmt(after['true_peak_dbtp'], 'dBTP')} (target {label})")
    return 1 if clipped else 0


def cmd_conventions(args):
    print("Kit house conventions: starting levels for single assets before the mix is balanced by ear.")
    print("NOT part of ASWG-R001 or any standard; the standard measures the whole mix (check-mix).")
    for target, base in ASWG.items():
        print(f"  {target}: " + ", ".join(f"{bus} {base + off:.0f} LUFS" for bus, off in HOUSE.items()))
    print("  one-shots shorter than 0.4 s: matched by true peak (--tp-ceiling, default -1 dBTP)")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description="Loudness per ITU-R BS.1770 / EBU Tech 3342; check a whole-game mix "
                                             "against ASWG-R001; normalize assets to kit house levels.",
                                 epilog="Exit codes: 0 ok, 1 out of target or too short, 2 usage or unreadable file.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="tracebacks")
    sub = ap.add_subparsers(dest="cmd")
    ms = sub.add_parser("measure", parents=[common], help="integrated LUFS, LRA, true peak per file")
    ms.add_argument("files", nargs="+", help="WAV or FLAC files or glob patterns (use quotes for **)")
    ms.add_argument("--json", action="store_true", help="print JSON")
    ms.add_argument("--no-true-peak", action="store_true", help="skip true peak (faster)")
    cm = sub.add_parser("check-mix", parents=[common], help="a whole-game gameplay capture against ASWG-R001")
    cm.add_argument("capture", help="WAV or FLAC of at least 30 minutes of representative gameplay")
    cm.add_argument("--target", choices=list(ASWG), default="home", help="home (-24) or portable (-18)")
    cm.add_argument("--allow-short", action="store_true", help="give a provisional reading for a capture under 30 min")
    nm = sub.add_parser("normalize", parents=[common], help="one asset to a loudness (true peak capped)")
    nm.add_argument("file")
    nm.add_argument("--lufs", type=float, help="target integrated loudness")
    nm.add_argument("--bus", choices=list(HOUSE), help="use the kit house level for this bus")
    nm.add_argument("--target", choices=list(ASWG), default="home", help="platform for --bus levels")
    nm.add_argument("--tp-ceiling", type=float, default=ASWG_TP_MAX, help="true peak ceiling in dBTP (default -1)")
    nm.add_argument("--out", required=True)
    nm.add_argument("--overwrite", action="store_true")
    sub.add_parser("conventions", parents=[common], help="print the kit house levels per bus")
    mo = sub.add_parser("mono", parents=[common], help="what stereo files lose in a mono downmix (phase cancellation)")
    mo.add_argument("files", nargs="+", help="WAV or FLAC files or glob patterns (use quotes for **)")
    mo.add_argument("--max-loss", type=float, default=MONO_MAX_LOSS_LU,
                    help=f"LU a file may lose in mono (default {MONO_MAX_LOSS_LU:.0f}; same sound both sides loses 3, "
                         "unrelated sides 6)")
    mo.add_argument("--min-corr", type=float, default=MONO_MIN_BLOCK_CORR,
                    help=f"lowest correlation a loud 400 ms block may have (default {MONO_MIN_BLOCK_CORR})")
    mo.add_argument("--json", action="store_true", help="print JSON")
    return ap


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = build_parser()
    args = ap.parse_args(argv)
    DEBUG = getattr(args, "debug", False)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        return {"measure": cmd_measure, "check-mix": cmd_check_mix, "normalize": cmd_normalize,
                "conventions": cmd_conventions, "mono": cmd_mono}[args.cmd](args)
    except ToolError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

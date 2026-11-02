#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_oggvorbis.py
# Purpose : Exam for oggvorbis.py: real encoder output (ffmpeg with libvorbis) decodes to what ffmpeg's own
#           decoder returns, the sample count follows the granule positions, every residue type and VQ lookup
#           type decodes, and broken or out-of-scope files are refused instead of decoded wrong.
# Usage   : python tools/audio/wavesmith/test_oggvorbis.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : The fixtures are short clips (base64, padding removed) encoded by ffmpeg 9.0 with libvorbis; the
#           expected values come from ffmpeg's decode of the same files: the per-channel mean and RMS, and
#           32-sample windows at the start, middle and end of each channel as float32 (compared within 1e-4;
#           measured agreement is about 4e-7). Measured coverage of the fixtures: mono and stereo, 22.05, 44.1
#           and 48 kHz, q0 / q6 / q10, short and long blocks with both transition shapes, residue 1 and 2
#           with coupling, several pages per stream, end trimming, and a single-page stream (short44k: its
#           source had 88 samples, which is what the last granule says; ffmpeg 9.0.2 returns 128 there, as it
#           does not trim a stream that fits on one page, so that count is checked against the source).
#           Residue type 0 and VQ lookup type 2 never appear in libvorbis output, so streams built bit by
#           bit in this file carry one spectrum through residue 0, 1 and 2 with lookup 1 and 2; all six must
#           decode the same, and they are compared with libvorbis's own decoder (ffmpeg -c:a libvorbis).
#           The start trim is checked on a fixture whose granules were lowered (libvorbis's rule; ffmpeg
#           keeps those samples, so it cannot be the reference there).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import base64
import cmath
import contextlib
import io
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oggvorbis  # noqa: E402
from wavfile import read_wav_channels  # noqa: E402


def lcg(seed):
    x = seed
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x


# ---- a tiny Vorbis writer for hand-built streams (residue 0, lookup 2, floor 0) ----
class BitWriter:
    """LSB first, as Vorbis packs its bits."""

    def __init__(self):
        self.value, self.n = 0, 0

    def put(self, bits, v):
        self.value |= (v & ((1 << bits) - 1)) << self.n
        self.n += bits

    def bytes(self):
        return self.value.to_bytes((self.n + 7) // 8, "little")


def ogg_page(serial, seq, granule, flags, packets):
    lacing, body = [], b""
    for p in packets:
        lacing += [255] * (len(p) // 255) + [len(p) % 255]
        body += p
    head = b"OggS" + bytes([0, flags]) + struct.pack("<qIII", granule, serial, seq, 0) + bytes([len(lacing)] + lacing)
    return head[:22] + struct.pack("<I", oggvorbis.ogg_crc(head + body)) + head[26:] + body


def vorbis_float(mant, exp):
    """Vorbis packed float for mant * 2 ** exp."""
    return (0x80000000 if mant < 0 else 0) | ((exp + 788) << 21) | abs(mant)


def hand_patterns():
    """Five blocks of (floor Y0, floor Y1, 32 spectrum signs)."""
    r = lcg(5)
    return [(30 + next(r) % 34, 30 + next(r) % 34, [1 if next(r) >> 16 & 1 else -1 for _ in range(32)])
            for _ in range(5)]


def hand_stream(rtype, lookup, floor_type=1):
    """Mono 8 kHz stream with 64-sample blocks: a 2-entry class book, a 4-entry 2-D VQ book holding the grid
    {-1, 1} x {-1, 1} (lookup 1, or the same values spelled out as lookup 2), floor 1 with only its two end
    points, and one residue of the given type. Each block's spectrum is written in that residue's layout, so
    every combination must decode to the same samples."""
    ident = b"\x01vorbis" + struct.pack("<IBIiii", 0, 1, 8000, 0, 0, 0) + bytes([0x66, 1])
    comment = b"\x03vorbis" + struct.pack("<I", 4) + b"exam" + struct.pack("<I", 0) + b"\x01"
    w = BitWriter()
    for c in b"\x05vorbis":
        w.put(8, c)
    w.put(8, 1)                                             # 2 codebooks
    for dims, lengths, look in ((1, [1, 1], 0), (2, [2, 2, 2, 2], lookup)):
        w.put(24, 0x564342); w.put(16, dims); w.put(24, len(lengths)); w.put(1, 0); w.put(1, 0)
        for n in lengths:
            w.put(5, n - 1)
        w.put(4, look)
        if look:
            w.put(32, vorbis_float(-1, 0)); w.put(32, vorbis_float(1, 1)); w.put(4, 0); w.put(1, 0)
            for m in ([0, 1] if look == 1 else [0, 0, 1, 0, 0, 1, 1, 1]):
                w.put(1, m)
    w.put(6, 0); w.put(16, 0)                               # one time domain placeholder
    w.put(6, 0); w.put(16, floor_type)
    w.put(5, 0); w.put(2, 3); w.put(4, 5)                   # floor 1: no partitions, multiplier 4, X = 0, 32
    w.put(6, 0); w.put(16, rtype); w.put(24, 0); w.put(24, 32); w.put(24, 7); w.put(6, 0); w.put(8, 0)
    w.put(3, 1); w.put(1, 0); w.put(8, 1)                   # class 0 uses book 1 in pass 0
    w.put(6, 0); w.put(16, 0); w.put(1, 0); w.put(1, 0); w.put(2, 0); w.put(8, 0); w.put(8, 0); w.put(8, 0)
    w.put(6, 0); w.put(1, 0); w.put(16, 0); w.put(16, 0); w.put(8, 0)
    w.put(1, 1)
    audio = []
    patterns = hand_patterns()
    for y0, y1, spectrum in patterns:
        a = BitWriter()
        a.put(1, 0); a.put(1, 1); a.put(6, y0); a.put(6, y1)
        for part in range(4):
            q = spectrum[part * 8:part * 8 + 8]
            a.put(1, 0)                                     # classword: class 0
            if rtype == 0:
                pairs = [(q[j], q[j + 4]) for j in range(4)]  # type 0 strides each vector across the partition
            else:
                pairs = [(q[2 * j], q[2 * j + 1]) for j in range(4)]
            for x, y in pairs:
                e = (x > 0) + 2 * (y > 0)
                a.put(1, e >> 1); a.put(1, e & 1)           # a Huffman code goes out first bit first
        audio.append(a.bytes())
    total = 32 * (len(patterns) - 1)
    return (ogg_page(7, 0, 0, 2, [ident]) + ogg_page(7, 1, 0, 0, [comment, w.bytes()])
            + ogg_page(7, 2, total, 4, audio))


def floats(b64):
    raw = base64.b64decode(b64 + "=" * (-len(b64) % 4))
    return struct.unpack(f"<{len(raw) // 4}f", raw)


# Encoded by ffmpeg 9.0 with libvorbis (opus: libopus, for the refusal). mono22k carries two tags.
FIXTURES = {
    "mono22k": (
        "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"
        "dk3XlWXTdW3ZdWVbV2VZ+DVVlWXTdW3ZdF3ZdmVXt1VZ1m3RdX1dlWXhN2XZ92Vb131Zt5VhdF3bV2VZ901ZFn7ZloXd1XVfmERRVT1VlV1RVV3X"
        "dF1bV13XtjXVlF3TdW3ZVF1ZVmVZ911X1nVNVWXZlGXbNl1XllVZ9nVXlnVbdF1dN2VZ+FVX1nVXt41jtm1fGF1X901Z1n1VlnVf1nVhmHXb1zVV"
        "1X1Tdn3hdGVd2H3fGGZdF47PdX1flW3hWGXZ+HXhF5Zb14Xfc11fV23ZGFbZNobd941h9n3jWHXbGGZbN7q6Thh+YThu3ziqti10dVtYXt026sZP"
        "uI3fqKmqr5uua/ymLPu6rNvCcPu+cnyu6/uqLBu/KtvCb+u6cuy+T/lc1xdWWRaG1ZaFYdZ1YdmFYanaujK8um8cr60rw+0Ljd9XhqptG8ur28Iw"
        "+7bw28JvHLuxMwYAAAw4AAAEmFAGCg1ZEQDECQBYJMnzLMsSRcuyRFE0RVUVRVFVLU0zTU3zTFPTPNM0TVN1RdNUXUvTTFPzNNPUPM00TdV0VdM0"
        "ZVM0Tdc1VdN2RVWVZdWVZVl1XV0WTdOVRdV0ZdNUXVl1XVdWXVeWJU0zTc3zTFPzPNM0VdOVTVN1XcvzVFPzRNP1RFFVVVNVXVNVZVfzPFP1RE81"
        "PVFUVdM1ZdVUVVk2VdOWTVOVZdNVbdlVZVeWXdm2TVWVZVM1Xdl0Xdd2Xdd2XdkVdknTTFPzPNPUPE81TVN1XVNVXdnyPNX0RFFVNU80VVVVXdc0"
        "VVe2PM9UPVFUVU3UVNN0XVlWVVNWRdW0ZVVVddk0VVl2Zdm2XdV1ZVNVXdlUXVk2VVN2XVe2ubIqq55pyrKpqrZsqqrsyrZt667r6raomrJrmqps"
        "q6qqu7Jr674sy7Ysqqrrmq4qy6aqyrYsy7ouy7awq65r26bqyrory3RZtV3f9m266rq2r8qur7uybOuu7eqybtu+75mmLJuqKdumqsqyLLu2bcuy"
        "L4ym6dqmq9qyqbqy7bqursuybNuiacqyqbqubaqmLMuybPuyLNu26sq67Nqy7buuLNuybQu77Aqzr7qyrbuybQurq9q27Ns+W1d1VQAAwIADAECA"
        "CWWg0JCVAEAUAABgDGOMQWiUcs45CI1SzjkHIXMOQgipZM5BCKGkzDkIpaSUOQehlJRCCKWk1FoIoZSUWisAAKDAAQAgwAZNicUBCg1ZCQCkAgAY"
        "HEfTTNN1ZdkYFssSRVWVZds2hsWyRFFVZdm2hWMTRVWVZdvWdTRRVFVZtm3dV45TVWXZtn1dODJVVZZtW9d9I1WWbVvXhaGSKsu2beu+UUm2bV03"
        "huOoJNu27vu+cSzxhaGwLJXwlV84KoEAAPAEBwCgAhtWRzgpGgssNGQlAJABAAAYpJRRSimjlFJKKcaUUowJAAAYcAAACDChDBQasiIAiAIAAJxz"
        "zjnnnHPOOeecc84555xzzjnnGGOMMcYYY4wxxhhjjDHGGGOMMcYYY4wxxhhjjDHGBADsRDgA7ERYCIWGrAQAwgEAAIQUgpJSKaWUEjnnpJRSSiml"
        "lMhBCKWUUkoppUTSSSmllFJKKaVxUEoppZRSSimhlFJKKaWUUkoJpZRSSimllFJKKaWUUkoppZRSSimllFJKKaWUUkoppZRSSimllFJKKaWUUkop"
        "pZRSSimllFJKKaWUUkoppZRSSimllFJKKaWUUkoppZRSSimllFJKAQAmDw4AUAk2zrCSdFY4GlxoyEoAIDcAAFCKOcYklJBKSCWEEErlGITOSQkp"
        "tVZCCq2ECjponaOQUkutlZRKSZmEEEIooYRSWikltVIyCKGEUEoIIaVSSgmhZVBCCiWUlFJJLbRUSskghFBaCamV1FoKJZWUQSmphJJSKq21lEpK"
        "rYPSUimttdZKSiGVllIHpaSWUimltRZKa621TlIpLaTWUmutlVZKKZ2llEpJrbWWWmsppVZCKa200lopJbXWUmstldRaS62l1lJrraXWSiklpZZa"
        "a621lloqKbWUQimllZJCaqml1koqLYTQUkmllVZaaymllEooJZWUWiqptZZSaKWF0kpJJaWWSioppdRSKqGUElIqoZXUUmuppZZKKi211FIrqZSW"
        "SkqpFAAAdOAAABBgRKWF2GnGlUfgiEKGCSgAABAEABiIkJlAoAAKDGQAwAFCghQAUFhgKF3oghAiSBdBFg9cOHHjiRtO6NAGABiIkJkAoRgiJGQD"
        "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"
    ),
    "stereo44k": (
        "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"
        "QggppRASAAAw4AAAEGBCGSg0ZCUAkAoAABijlHPOSUmlQogx5yCU0lKFEGPOQSilpagxxiCUklJrUWOMQSglpdaiayGUklJKrUXXQiglpdZai1Kq"
        "VEpqrcUYpVSplNZaizFKqXNKrcUYY5RS95Rai7HWKKV0MsYYY63NOedkjDHGWgsAQGhwAAA7sGF1hJOiscBCQ1YCAHkAAAhCSjHGGGMQIaUYY8wx"
        "h5BSjDHGGFSKMcYcYw5CyBhjjDEHIWSMMeecgxAyxhhjzkEInXOOMecghNA5x5hzEELnnGPMOQihc4wx5pwAAKACBwCAABtFNicYCSo0ZCUAEA4A"
        "ABjDmHOMOQadhAoh5yB0DkIqqVQIOQehcxBKSal4DjopIZRSSirFcxBKCaGUlForLoZSSiilpNRSkTGEUkopJaXWijGmhJBSSqm1VowxoYRUUkop"
        "tmKMjaWk1FprrRVjbCwlldZaa60YY4xrKbUWY6zFGGNcS6mlGGssxhjje2otxlhjMcYYn1tqKaZcCwAweXAAgEqwcYaVpLPC0eBCQ1YCALkBAAhC"
        "SjHGmGPOOeecc85JpRhzzjnnIIQQQgghlEox5pxzzkEHIYQQQigZc845ByGEEEIIIYRQUuqYcw5CCCGEEEIIIaXUOecghBBCCCGEEEJKqXPOQQgh"
        "hBBCCCGElFIIIYQQQgghhBBCCCmllEIIIYQQQgghlBJSSimFEEIIJYQSSgglpJRSCiGEEEIppYRSQkkppRRCCKWUUEopoZSQUkoppRBCKKWUUEop"
        "JaWUUkollFJKKSWUUEpKKaWUSiihlFBKKaWUlFJKKZVSSikllFJKCSmllFJKqZRSSimllFJSSimllFIppZRSSimlpJRSSimlUkoppZQSSkkppZRS"
        "SqWUUEoppZRSUkoppZRKCqWUUkoppQAAoAMHAIAAIyotxE4zrjwCRxQyTECFhqwEAFIBAABCKKWUUkopNYxRSimllFKKHKSUUkoppZRSSimllFJK"
        "KZVSSimllFJKKaWUUkoppZRSSimllFJKKaWUUkoppZRSSimllFJKKaWUUkoppZRSSimllFJKKaWUUkoppZRSSimllFJKKaWUUkoBwN0XDoA+Ezas"
        "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"
        "AAD0DkZrwa1lZs3xe+0hDbUjWsupft74iZeIeMmv/HsnvMLqlVlrjl4uzvfIZjm5+zSnW6554vR0u/6+7/2O9bvjFkl8/vdFOSrn10U2l/tobJby"
        "zn0+6vL9W9a/7C5ffx6nvNz61a3/+P/X85N24VPfrne+Gh//1q/+B5/9v56ftAufOkTvfDU+/q1f/So79P96Pu6Lk7t2i/PUZdxfSrmyC/+v5//g"
        "Kv51i+98NW7/dhWv/Oz/9fwfdOGh599cjQdvV/HK2P8F+5WtQ7A3V+PB21W8GrH/+75/0IWPgr2zA5/6dn31q/z4t/zV/6ALz9Tzk3bhU0f9kq6M"
        "+9avfpUd+n89P+3Cp46aZ78aH//Wr36VH///umzSLnzqnn/n8Pz4UX31Kz/+LXfZtEMPPT9peN5+1C/pyrhv7dnkLjz0/LTjUwdKujLuQEmTOx66"
        "Tjs+cpZkj/vWkqzveOg67fjI2ZY97kBJ9o9/6DrteOjaVse4AyXZP36gZ5Ydfug67Uj7m70zU5ut+9rf7+apzd6Zqc3bfe3vd1/7m70zU5u93dHf"
        "7772U3dmarN3ZvT3u6/91J2Z2uydmeq37ms/dXM/9M6MzTajn7q5n9rc2FpzttJc3kpz+WytubNlLm+luXzSmrNlzrHySbIEAA"
    ),
    "loud48k": (
        "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"
        "EEIIIYQQEgAAMOAAABBgQhkoNGQlAJAKAEAYoxRjzklJqTJGKecglNJaZZBSzkEopbVmKaWcg5JSa81SSjknJaXWmikZg1BKSq01lTIGoZSUWmvO"
        "iRBCSq3F2JwTIYSUWouxOSdjKSm1GGNzTsZSUmoxxuacU661FmPNSSmlXGstxloLAEBocAAAO7BhdYSTorHAQkNWAgB5AACQUkoxxhhjTCmlGGOM"
        "MaaUUowxxphTSinGGGPMOacUY4wx5pxjjDHGGHPOMcYYY4w55xhjjDHGnHPOMcYYY8455xhjjDHnnHOMMcaYAACgAgcAgAAbRTYnGAkqNGQlABAO"
        "AAAYw5RzzkEoJZUKIcYgdFBKSq1VCDEGIYRSUmotas45CCGUklJr0XPOQQihlJRai6qFUEopJaXWWnQtdFJKSam1GKOUIoSQUkqttRidEyGEklJq"
        "LcbmnIylpNRajDE252QsJaXWYoyxOeeca621FmOtzTnnXGspthhrbc45p3tsMdZYa3POOZ9bi63GWgsAMHlwAIBKsHGGlaSzwtHgQkNWAgC5AQCM"
        "Uowx5pxzzjnnnHPOSaUYc845CCGEEEIIIZRKMeaccxBCCCGEEEIoGXPOOQchhBBCCCGEUErpnHMQQgghhBBCCKGU0jnnIIQQQgghhBBCKaVzzkEI"
        "IYQQQgghhFJKCCGEEEIIIYQQQgillFJCCCGEEEIIIYQQSimlhBBCCCGEEEIIIZRSSgkhhBBCCCGEEEIopZQSQgghhBBCCCWEUEoppZQQQgihhBBC"
        "CKGUUkopIYRSSikhhBBCKaWUUkIooYQQQgghlFJKKaWUEkIpIYQQQgillFJKKaWUUkIIIYQQSimllFJKKaWEUEIIIZRSSimllFJCKCWEEkIopZRS"
        "SimlhFBCCCGEUEoppZRSSgkhhBJCCKEAAKADBwCAACMqLcROM648AkcUMkxAhYasBADSAgAAQ6y11lprrbXWWmsNUtZaa6211lprrbVGKWuttdZa"
        "a6211lprqbXWWmuttdZaa6211lprrbXWWmuttdZaa6211lprrbXWWmuttdZaa6211lprrbXWWmuttdZaa6211lprrbXWWmuttdZaa6211lprrbXW"
        "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"
        "AQ"
    ),
    "short44k": (
        "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"
        "TovqBRI"
    ),
    "opus": (
        "T2dnUwACAAAAAAAAAAAsClBhAAAAAAn/EAsBE09wdXNIZWFkAQE4AYC7AAAAAABPZ2dTAAAAAAAAAAAAACwKUGEBAAAAVXZd1gE8T3B1c1RhZ3MM"
        "AAAATGF2ZjYzLjEuMTAyAQAAABwAAABlbmNvZGVyPUxhdmM2My4xLjEwMiBsaWJvcHVzT2dnUwAE+AQAAAAAAAAsClBhAgAAAAZBNuECQSJ4g5yK"
        "VlmaiAACGK8U5WAS5Vs7I7fADB4+rzB+Hqr3KproD83cr6Szo7XehY3i8SihkOqTgQC+0U7v+51OhwldJXgGct3gGXC8NeFlnihfBlOcSTEYS8KD"
        "BhhYsCgoQvVTAQY"
    ),
}

EXPECT = {
    "mono22k": {"rate": 22050, "channels": 1, "samples": 11025, "mean_rms": [(0.010859309, 0.298077493)],
                 "windows": [
                     (0, 0, "92UXP9dTMD/VryA/ff8mP/htLj9mXkE/vYNfP/1NWD/whmk/pSNpP9AihD9QaG4/dcN1P4Uxdj/srn8/RPiAP16xjD8AFYA/7CyGPxW3dj/Kzok/L7N/P3BsgD9OAIU/KE53P0TOaj/rHHE/rdZvP1SUUz+fzzw/UndXP1ZYRD8"),
                     (0, 5496, "b/PSPqf52z7Wybg+SIXYPhwqsz5mMMY+ok2aPtVvqD5+UKo+7rmEPn2pTT6KHjM+uOoNPvIOkT22q9A9COCGPf9PJT2Y4+G80lEmvfwcDb4lh0q+vFcFvooMKb7QsW6+vRp5vlVjor40k3++JyrQvpB1yb77cai+pLzNvqbO4L4"),
                     (0, 10993, "KkSfvawbgb2vsDe+Dxs6vle9fr7cQn2+G8CAvitJor5HoZe+wY6zvvKht77Z2cG+iGaxvqo0s74569a+W2a3vmi50b6YC9S+tsGuvksDur4QILW+BkK6vnWDnL6qxH6+ZGmUvpR/Yb414DO+1KhUvoB8HL4TRjW+bNHmvNTXPLw"),
                 ]},
    "stereo44k": {"rate": 44100, "channels": 2, "samples": 13230, "mean_rms": [(0.012280663, 0.272495281), (1.9025e-05, 0.183554162)],
                 "windows": [
                     (0, 0, "us4bP8DyJj9WMTM/ZCg9P9OISD91sk8/wdlXPx4RXT/0SmA/J3JjP4b3YT8MMWE/qeZcP1eTWT8fD1M/tD1MP8BYRj/tWT0/QHE3P9yJLz9A8Sk/CxIkPzu/ID/Olx8/CTAdP3ARHz+19R4/C2IlP9A/Kj/gXTI/F947P16zRD8"),
                     (0, 6599, "g0Q0voagUb6Pdmy+TsSBvu/cir5XDJG+kvOTvsdQk76FAY++3AOHvuPsdr7GLlm+TYQ1vtPYDL4ZiMC9+gFEvQBOwbnI8kA9GfG+Pff/Cz69lzQ+ZydYPtbCdT48WYY+zDyOPk1tkj6R7JI+Bt2PPouAiT5KNoA+9+5oPpKmTT4"),
                     (0, 13198, "gAdOvoAEI75OHfa9rb6uvaKXY71XbQK9Ca9yvJiCm7vza/e6jYrGuyYxiby7NAm98+hivQ6Cpr2Hv+G95SgQvlOuL76GTE6+WXNqvthjgb7MLou+S/2RvkRvlb7/V5W+V2KRvt+iib6QrXy+nvRevoUkO74rPhK+dDLJvS85Vb0"),
                     (1, 0, "EpCovfEkHD5D8rO9Oj2XvQp/Db3UrDk9MWBhPrLYID4AXog+XYoxPjUXpT6YS/I9zR8uPigx9T3k3a49UxowPiDcpj5lkTI++sONPgV7Aj6Lxaw++IRpPuHaYz5Ru7Y+kit7Pp93Sz47+oM+ABOCPpdzsj1OKoA9mAKRPkJMIT4"),
                     (1, 6599, "IOhVPpRioj5crbM+XiN/PoXeeT415BA+GgFYPqaQbD4o5qQ8qqX0Pb4Aez5wiVQ80U4zPtXjCz0lmxY+sucwvSx/3D26zVk93GmOPZCU/rrEupc8LJc5vnA2672QZCm+6vleviXuvL3iRUa+SO+KvlVm/b3iepC+rNuWvowmhb4"),
                     (1, 13198, "wlYWvj8OJr5/izS+GWJCvlPNTr7Y5Vm+lv9jvoEubL4aSHO+Ieh4vuCtfL5oV3+++wWAvrF4f76jUH2+mxh5vmcTdL7lCW2+aZlkvn85W76R6E++bwVEvstXNr4IiCe+ioYYvnRPB77Snuy9k8/IvRODor0qfHy9gEknvb4VxLw"),
                 ]},
    "loud48k": {"rate": 48000, "channels": 2, "samples": 4800, "mean_rms": [(1.125e-06, 0.680521321), (-0.002302539, 0.522429668)],
                 "windows": [
                     (0, 0, "6xDruhkBnD4oYxQ/LN1KP8ftaz/o8HM/yvxhPzgKOD+XBPU+LgZAPj9o/L0wnde+z6ksv4AxW79OYnK/CMlvv1C9U79uMyG/WiC7vnISgL21F30+6csHP/zeQT+8ZWc/Xlx0P1tlZz/q3kE/x7oHP8CufD7q5oC9LGi7vuVUIb8"),
                     (0, 2384, "vT9VP86McT8PNnQ/PfNcP3o8Lj9kDto+bv0APnDSP76ZIva+qB05v6SDY78uw3W/dOxtv4TUTL+2/hW/QHqevgAYlLnEM54+puAVP46+TD+04G0/0MJ1P7iOYz8mMzk/Wl72PhJgQD5QZwC+VcbZvnkdLr9O3Fy/gil0v+6Lcb8"),
                     (0, 4768, "LKxTPxVGIT+Kebs+HOiBPfzye76Zjge/JrhBvzhRZ79SYnS/nXlnv/QEQr9b+we/Xdx9vmpgfD1av7o+TQwhP0aOUz8ArG8/6VtyP5BZWz9YGy0/+L/YPl+LAD7mND6+F4L0voTXN7+e+mG/lB50v09KbL+9i0u/Z+IUv+OZnb4"),
                     (1, 0, "Dyb6vgLYVT9cY0W/7xVVv9zqJ78UtKe+DWMnP+e02j0+aj0/PN/rPa9jWT8ONMy+Akc8viPkFb/fG1K/E+q8vqUfEj8cKvu+2h8vPi3FQ7+mMgU/g0ESvu85DL67di4/KF6fPdTaWr7KQD8+2NdSPvMKO79Ooke/bPggP1/TBL0"),
                     (1, 2384, "cuEFP0b6Tb8OHEs/RLmqPhICPj8ZTyQ/E+upPgK6ST6cRUQ+l2Vbv3kkQr4VNLu+7iP6vtS85j7W40e/kCQJP575N77m1T4/HOkyv20wkD4jt0i/xke7vm4m5T3XY7A+V4epvptN3j7y814+4IW9PQFPh76buj0/6ipIP954Aj8"),
                     (1, 4768, "s1xgvv6u5z4I2WA+FMo5PyRhUTsfGFI/2hFEPxF6IL/W7HY+z2pDP3UzBD2wcV88VG3IvrqHjb7BRE6/umsGvxxP176WMIs+zPRJv6XbQD8cj5M+g/snv3Y4xT0MefI+f0LVPECfRz++XuI9CGv1vjjCHT+ZhL89ZqCkPiLJ/r4"),
                 ]},
    "short44k": {"rate": 44100, "channels": 1, "samples": 88, "mean_rms": [(0.029732719, 0.367771373)],
                 "windows": [
                     (0, 0, "sKxdu2Un3Tx7KHI9zl+5PaQ0+j0ichw+/L06Pn/SWD4DtnU+1NKIPrdhlj7LMaM+fHmvPpQhuz4gAMY+mTfQPo2C2T6s3eE+VHHpPlcF8D7CpPU+MlL6PgT5/T7JZgA/slYBPzC2AT9lkgE/8t0AP6I//z7jxvs+5zH3Pmuj8T4"),
                     (0, 28, "oj//PuPG+z7nMfc+a6PxPv4e6z7HhuM+aAjbPnWu0T6ogcc+upy8Pl/esD4BZKQ+1WKXPofQiT4siHc+ZIBaPs6APD7R7h0+NI/9Pcg3vj10RH09APD6PACyH7pE+AG9eIeAvZwTv71YZPy9hmccvrXyOb63zFa+495yvrT3hr4"),
                     (0, 56, "tfI5vrfMVr7j3nK+tPeGvr4OlL5VnKC+BICsvm7Gt76PWsK+MjDMviBE1b4sdt2+nM/kvjRP674U0/C+BGD1vjLv+L6Gdvu+Yv38vhpr/b7Ewvy+mB77vrJ2+L4T0fS+dzDwvhuR6r41DuS+WqzcvqVo1L6gVcu+/HTBvt3btr4"),
                 ]},
}

# libvorbis's decode (ffmpeg -c:a libvorbis) of hand_stream(0, 2): the first 96 samples.
HAND_REF = (
    "L+OmOzQCgzsFhoU7qKN6O8uwGjsLgbY65+QmvCApcTpevYs82YSNu2zV5Tv4Umc9Rg/gvCk+y70GKdM9V3XLvRF32T14AwG+0x8ZPh5+Tz18yP69"
    "km37vKAo5zs9q3G9aFGvPCw0XD2V9ki8nIBJvGOB4LwrKYS9fDYMPNUAET0N0Ue9hTKDvXRZILzFWkk7JDMQPRA4u7pioYS9u9SWvRrRhTzk2ky9"
    "QN4Eut9oAb3+fAa97OBEPW/19Ty0FTw9gJGnufZQnj1OBgu8qDbGPHxQcTvAiNm92ja1Pfafhr18W3E9Zb/avYnTmT1I9E69zs6CPV8l4b27vyI+"
    "9FM+vhiPMD6iaSq+Wm5VPnI+hr44QI4+Utx6vrvzND43yba9EocEPdByNr0avfM9p/5tvkm3qj540b2+lwmoPjC3ir4f25o+EhXYvn2OBT/BShC/"
    "+ZMNPwJwBb8EcP8+h5Xrvvvz1D47u8i+eFzEPshzub655bM+2RbIvnYs4j5+GMG+"
)


class OggVorbisExam(unittest.TestCase):
    decoded = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def data(self, name):
        b64 = "".join(FIXTURES[name])
        return base64.b64decode(b64 + "=" * (-len(b64) % 4))

    def decode(self, name):
        if name not in self.decoded:                # each fixture is decoded once for the whole exam
            self.decoded[name] = oggvorbis.decode(self.data(name))
        return self.decoded[name]

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = oggvorbis.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    def page_offsets(self, data):
        offsets, pos = [], 0
        while pos < len(data):
            offsets.append(pos)
            pos = oggvorbis._page(data, pos)[-1]
        return offsets

    def test_fixtures_match_ffmpeg(self):
        for name, want in EXPECT.items():
            info, chans, _ = self.decode(name)
            self.assertEqual((info["rate"], info["channels"], info["samples"]),
                             (want["rate"], want["channels"], want["samples"]), name)
            self.assertEqual([len(c) for c in chans], [want["samples"]] * want["channels"], name)
            for c, (mean, rms) in enumerate(want["mean_rms"]):
                got = chans[c]
                self.assertAlmostEqual(sum(got) / len(got), mean, delta=1e-5, msg=f"{name} ch{c} mean")
                self.assertAlmostEqual(math.sqrt(sum(x * x for x in got) / len(got)), rms, delta=1e-5,
                                       msg=f"{name} ch{c} RMS")
            for c, offset, b64 in want["windows"]:
                ref = floats(b64)
                worst = max(abs(a - b) for a, b in zip(chans[c][offset:offset + len(ref)], ref))
                self.assertLess(worst, 1e-4, f"{name} ch{c} samples {offset}..{offset + len(ref) - 1}")

    def test_end_trim_follows_the_last_granule(self):
        info, chans, _ = self.decode("short44k")
        self.assertEqual((info["samples"], info["end_trim"], info["start_trim"]), (88, 40, 0))
        info, _, _ = self.decode("stereo44k")
        self.assertEqual(info["samples"], 13230, "0.3 s at 44.1 kHz, as encoded")

    def test_start_trim_follows_the_first_granule(self):
        data = bytearray(self.data("stereo44k"))
        packets_seen = 0
        for pos in self.page_offsets(bytes(data)):
            flags, granule, _, _, lacing, _, end = oggvorbis._page(bytes(data), pos)
            packets_seen += sum(1 for lv in lacing if lv < 255)
            if packets_seen > 3 and granule >= 0:   # an audio page: move every position 300 samples earlier
                struct.pack_into("<q", data, pos + 6, granule - 300)
                data[pos + 22:pos + 26] = b"\0\0\0\0"
                struct.pack_into("<I", data, pos + 22, oggvorbis.ogg_crc(bytes(data[pos:end])))
        info, chans, _ = oggvorbis.decode(bytes(data))
        _, full, _ = self.decode("stereo44k")
        self.assertEqual((info["start_trim"], info["samples"]), (300, 13230 - 300))
        self.assertEqual(chans[0], full[0][300:])
        self.assertEqual(chans[1], full[1][300:])

    def test_every_residue_and_lookup_type_decodes_the_same(self):
        ref = floats(HAND_REF)
        first = None
        for rtype in (0, 1, 2):
            for lookup in (1, 2):
                info, chans, _ = oggvorbis.decode(hand_stream(rtype, lookup))
                self.assertEqual(info["samples"], 128, f"residue {rtype} lookup {lookup}")
                first = first or chans[0]
                self.assertEqual(chans[0], first, f"residue {rtype} lookup {lookup} differs from residue 0 lookup 1")
        self.assertLess(max(abs(a - b) for a, b in zip(first, ref)), 1e-4, "differs from libvorbis")
        self.assertGreater(max(abs(v) for v in first), 0.1, "the hand-built stream should not be silent")

    def test_imdct_matches_its_definition(self):
        r = lcg(3)
        for m in (32, 128):
            spectrum = [(next(r) % 2001 - 1000) / 1000.0 for _ in range(m)]
            fast = oggvorbis.imdct(spectrum)
            for n in range(0, 2 * m, 7):
                slow = sum(x * math.cos(math.pi / m * (n + 0.5 + m / 2) * (k + 0.5)) for k, x in enumerate(spectrum))
                self.assertAlmostEqual(fast[n], slow, places=9)
        self.assertEqual(len(oggvorbis.imdct([0.0] * 1024)), 2048)
        self.assertTrue(cmath.isclose(oggvorbis._fft([1, 2, 3, 4])[1], complex(-2, 2)))

    def test_huffman_codewords_follow_the_spec_example(self):
        lengths = [2, 4, 4, 4, 4, 2, 3, 3]
        codes = oggvorbis._huffman_codes(lengths, range(8))
        self.assertEqual([format(codes[i], f"0{n}b") for i, n in enumerate(lengths)],
                         ["00", "0100", "0101", "0110", "0111", "10", "110", "111"])
        with self.assertRaises(oggvorbis.VorbisCorrupt):
            oggvorbis._huffman_codes([1, 1, 1], range(3))

    def test_comments_are_returned_not_lost(self):
        info, _, comments = self.decode("mono22k")
        self.assertIn(("title", "Exam tone"), comments)
        self.assertIn(("DESCRIPTION", "for the Vorbis exam"), comments)
        self.assertTrue(info["vendor"])

    def test_read_ogg_gives_interleaved_floats(self):
        path = self.dir / "s.ogg"
        path.write_bytes(self.data("stereo44k"))
        samples, rate, channels = oggvorbis.read_ogg(path)
        _, chans, _ = self.decode("stereo44k")
        self.assertEqual((rate, channels, len(samples)), (44100, 2, 2 * len(chans[0])))
        self.assertEqual((samples[0], samples[1], samples[-1]), (chans[0][0], chans[1][0], chans[1][-1]))

    def test_not_ogg_and_not_vorbis_are_named(self):
        with self.assertRaises(oggvorbis.VorbisError) as ctx:
            oggvorbis.decode(b"RIFF\x24\0\0\0WAVEfmt ")
        self.assertIn("not an Ogg file", str(ctx.exception))
        with self.assertRaises(oggvorbis.VorbisError) as ctx:
            oggvorbis.decode(self.data("opus"))
        self.assertIn("not Vorbis: Opus; convert with ffmpeg", str(ctx.exception))
        with self.assertRaises(oggvorbis.VorbisError) as ctx:
            oggvorbis.decode(hand_stream(1, 1, floor_type=0))
        self.assertIn("floor type 0", str(ctx.exception))

    def test_truncated_streams_fail(self):
        data = self.data("stereo44k")
        with self.assertRaises(oggvorbis.VorbisCorrupt) as ctx:
            oggvorbis.decode(data[:len(data) - 300])
        self.assertIn("truncated", str(ctx.exception))
        last_page = self.page_offsets(data)[-1]
        with self.assertRaises(oggvorbis.VorbisCorrupt) as ctx:
            oggvorbis.decode(data[:last_page])      # cut cleanly between pages: the end page is missing
        self.assertIn("truncated", str(ctx.exception))

    def test_crc_mismatch_and_missing_page_fail(self):
        data = bytearray(self.data("mono22k"))
        data[len(data) // 2] ^= 0x10
        with self.assertRaises(oggvorbis.VorbisCorrupt) as ctx:
            oggvorbis.decode(bytes(data))
        self.assertIn("CRC", str(ctx.exception))
        data = self.data("mono22k")
        offsets = self.page_offsets(data)
        holed = data[:offsets[4]] + data[offsets[5]:]
        with self.assertRaises(oggvorbis.VorbisCorrupt) as ctx:
            oggvorbis.decode(holed)
        self.assertIn("missing", str(ctx.exception))

    def test_chained_stream_is_refused(self):
        data = self.data("short44k")
        with self.assertRaises(oggvorbis.VorbisError) as ctx:
            oggvorbis.decode(data + data)
        self.assertIn("chained", str(ctx.exception))

    def test_towav_writes_the_samples_and_no_tags(self):
        src, wav = self.dir / "t.ogg", self.dir / "t.wav"
        src.write_bytes(self.data("mono22k"))
        rc, out = self.run_tool("towav", src, "--out", wav)
        self.assertEqual(rc, 0, out)
        self.assertIn("clipped", out, "this fixture overshoots full scale")
        samples, rate, _, channels = read_wav_channels(wav)
        _, chans, _ = self.decode("mono22k")
        self.assertEqual((rate, channels, len(samples)), (22050, 1, len(chans[0])))
        self.assertEqual([round(s * 32767) for s in samples[:50]],
                         [round(max(-1.0, min(1.0, v)) * 32767) for v in chans[0][:50]])
        self.assertNotIn(b"Exam tone", wav.read_bytes())
        rc, out = self.run_tool("wav", src, "--out", wav)
        self.assertEqual(rc, 2, "an existing WAV needs --overwrite")
        rc, out = self.run_tool("wav", src, "--out", wav, "--overwrite")
        self.assertEqual(rc, 0, out)

    def test_cli_info_and_exit_codes(self):
        good, bad, corrupt, opus = (self.dir / n for n in ("g.ogg", "bad.ogg", "corrupt.ogg", "o.ogg"))
        good.write_bytes(self.data("mono22k"))
        bad.write_bytes(b"not ogg at all")
        data = bytearray(self.data("stereo44k"))
        data[-10] ^= 0xFF
        corrupt.write_bytes(bytes(data))
        opus.write_bytes(self.data("opus"))
        rc, out = self.run_tool("info", good)
        self.assertEqual(rc, 0, out)
        self.assertIn("22050 Hz, 1 ch, 0.500 s", out)
        self.assertIn("title=Exam tone", out)
        rc, out = self.run_tool("info", bad)
        self.assertEqual(rc, 2, out)
        self.assertIn("[error]", out)
        rc, out = self.run_tool("info", opus)
        self.assertEqual(rc, 2, out)
        self.assertIn("not Vorbis: Opus", out)
        rc, out = self.run_tool("info", corrupt)
        self.assertEqual(rc, 1, out)
        self.assertNotIn("Traceback", out)
        rc, out = self.run_tool("info", self.dir / "missing.ogg")
        self.assertEqual(rc, 2, out)
        self.assertEqual(self.run_tool()[0], 2, "no command prints help and exits 2")


if __name__ == "__main__":
    unittest.main(verbosity=1)

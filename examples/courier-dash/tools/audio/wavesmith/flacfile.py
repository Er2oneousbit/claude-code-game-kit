#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# flacfile.py
# Purpose : Decode FLAC files to samples with the standard library only, so audio tools can post-process what a
#           local ComfyUI saves (it writes FLAC, MP3 or Opus, never WAV) and write a clean WAV with wavfile.py.
#           Decoding keeps the sound and nothing else: the prompt and workflow ComfyUI writes into the file's
#           tags never reach the WAV.
# Usage   : from flacfile import read_flac
#           samples, rate, channels = read_flac("take.flac")       # floats in -1..1, interleaved L R L R
#           python tools/audio/wavesmith/flacfile.py info take.flac          # rate, channels, bits, length, MD5 check
#           python tools/audio/wavesmith/flacfile.py towav take.flac --out take.wav
# Needs   : Python 3.8+ only
# Exit    : 0 ok, 1 the file decodes wrong (CRC or MD5 mismatch, truncated), 2 usage, not FLAC, or unsupported
# Notes   : Scope is what ffmpeg's FLAC encoder writes (ComfyUI's SaveAudio uses it): 16- or 24-bit, mono or
#           stereo, any rate. Every frame's CRC-16 is checked, and the decoded samples are checked against the
#           STREAMINFO MD5 (the end-to-end proof); an all-zero MD5 means the encoder left it unset and is accepted
#           with a note. Other bit depths or channel counts are refused by name, never guessed.
#           Speed: pure Python. Measured numbers are in docs/resources/audio.md (local SFX).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   "fLaC" -> metadata blocks (STREAMINFO: rate, channels, bits, total samples, MD5; skip every other block)
#   until the data ends or all samples are out:
#     frame header (sync, block size, rate, channel layout, bits, number, CRC-8)
#     per channel: subframe = CONSTANT | VERBATIM | FIXED order 0-4 | LPC order 1-32, residual = partitioned Rice
#     undo stereo decorrelation (left/side, side/right, mid/side) -> byte align -> CRC-16 over the frame
#   MD5 of the samples as little-endian signed integers, interleaved -> compare with STREAMINFO
import argparse
import hashlib
import struct
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wavfile import WavNameError, check_wav_name, stats, write_wav  # noqa: E402

MAGIC = b"fLaC"
STREAMINFO_BYTES = 34        # the fixed size of the STREAMINFO block's body
SUPPORTED_BITS = (16, 24)
SUPPORTED_CHANNELS = (1, 2)
BLOCK_SIZES = {1: 192, 2: 576, 3: 1152, 4: 2304, 5: 4608,
               8: 256, 9: 512, 10: 1024, 11: 2048, 12: 4096, 13: 8192, 14: 16384, 15: 32768}
RATES = {1: 88200, 2: 176400, 3: 192000, 4: 8000, 5: 16000, 6: 22050, 7: 24000, 8: 32000, 9: 44100,
         10: 48000, 11: 96000}
BITS = {1: 8, 2: 12, 4: 16, 5: 20, 6: 24, 7: 32}
FIXED_COEFS = {0: (), 1: (1,), 2: (2, -1), 3: (3, -3, 1), 4: (4, -6, 4, -1)}
DEBUG = False


class FlacError(Exception):
    """Exit 2: not a FLAC file, or a FLAC feature outside this decoder's scope."""


class FlacCorrupt(Exception):
    """Exit 1: a FLAC file that does not decode to what it says (CRC or MD5 mismatch, truncated)."""


def _crc8_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
        table.append(c)
    return table


def _crc16_table():
    table = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x8005) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
        table.append(c)
    return table


CRC8, CRC16 = _crc8_table(), _crc16_table()


def crc8(data):
    c = 0
    for b in data:
        c = CRC8[c ^ b]
    return c


def crc16(data):
    c = 0
    for b in data:
        c = ((c << 8) & 0xFFFF) ^ CRC16[(c >> 8) ^ b]
    return c


class BitReader:
    """MSB-first bit reader over bytes, with a small integer cache (fast enough for Rice codes in pure Python)."""

    def __init__(self, data, pos=0):
        self.data, self.pos, self.cache, self.nbits = data, pos, 0, 0

    def _need(self, n):
        while self.nbits < n:
            if self.pos >= len(self.data):
                raise FlacCorrupt("the file ends in the middle of a frame (truncated)")
            self.cache = (self.cache << 8) | self.data[self.pos]
            self.pos += 1
            self.nbits += 8

    def read(self, n):
        if n == 0:
            return 0
        self._need(n)
        self.nbits -= n
        value = self.cache >> self.nbits
        self.cache &= (1 << self.nbits) - 1
        return value

    def signed(self, n):
        v = self.read(n)
        return v - (1 << n) if n and v >> (n - 1) else v

    def unary(self):
        """Count of 0 bits before the next 1 bit (the 1 is consumed)."""
        count = 0
        while True:
            if self.nbits == 0:
                self._need(8)
            if self.cache == 0:
                count += self.nbits
                self.nbits = 0
                continue
            zeros = self.nbits - self.cache.bit_length()
            count += zeros
            self.nbits -= zeros + 1
            self.cache &= (1 << self.nbits) - 1
            return count

    def align(self):
        """Drop the bits left in the current byte."""
        self.nbits -= self.nbits % 8
        self.cache &= (1 << self.nbits) - 1

    def byte_pos(self):
        """Position of the next unread byte (valid when aligned)."""
        return self.pos - self.nbits // 8


def read_streaminfo(data):
    """(info dict, offset of the first frame). Every metadata block except STREAMINFO is skipped."""
    if data[:4] != MAGIC:
        raise FlacError("not a FLAC file (no fLaC marker)")
    pos, info = 4, None
    while True:
        if pos + 4 > len(data):
            raise FlacCorrupt("metadata runs past the end of the file")
        head = data[pos]
        kind, last = head & 0x7F, head & 0x80
        length = int.from_bytes(data[pos + 1:pos + 4], "big")
        if pos + 4 + length > len(data):
            raise FlacCorrupt(f"a metadata block of {length} bytes runs past the end of the file (corrupt file)")
        body = data[pos + 4:pos + 4 + length]
        if kind == 0:
            # a zero-filled tail (a cut, padded download) parses as another STREAMINFO block of length 0
            if length < STREAMINFO_BYTES:
                raise FlacCorrupt(f"STREAMINFO block is {length} bytes, not {STREAMINFO_BYTES} (corrupt file)")
            if info is not None:
                raise FlacCorrupt("a second STREAMINFO block (corrupt file)")
            bits = int.from_bytes(body[10:18], "big")
            info = {"min_block": struct.unpack(">H", body[0:2])[0], "max_block": struct.unpack(">H", body[2:4])[0],
                    "rate": bits >> 44, "channels": ((bits >> 41) & 0x7) + 1, "bits": ((bits >> 36) & 0x1F) + 1,
                    "total": bits & 0xFFFFFFFFF, "md5": body[18:34]}
        pos += 4 + length
        if last:
            break
    if info is None:
        raise FlacCorrupt("no STREAMINFO block")
    if info["bits"] not in SUPPORTED_BITS:
        raise FlacError(f"{info['bits']}-bit FLAC is not supported (this decoder reads 16- and 24-bit)")
    if info["channels"] not in SUPPORTED_CHANNELS:
        raise FlacError(f"{info['channels']}-channel FLAC is not supported (this decoder reads mono and stereo)")
    return info, pos


def _residual(br, block, order, out):
    method = br.read(2)
    if method > 1:
        raise FlacError(f"residual coding method {method} is not supported (reserved in the FLAC format)")
    param_bits, escape = (4, 15) if method == 0 else (5, 31)
    parts = br.read(4)
    for p in range(1 << parts):
        n = (block >> parts) - (order if p == 0 else 0)
        k = br.read(param_bits)
        if k == escape:
            raw = br.read(5)
            out.extend(br.signed(raw) for _ in range(n))
            continue
        for _ in range(n):
            v = (br.unary() << k) | br.read(k)
            out.append((v >> 1) ^ -(v & 1))       # zigzag back to signed


def _subframe(br, block, bps):
    if br.read(1):
        raise FlacCorrupt("subframe padding bit is set")
    kind = br.read(6)
    wasted = 0
    if br.read(1):
        wasted = br.unary() + 1
        bps -= wasted
    if kind == 0:                                   # CONSTANT
        s = [br.signed(bps)] * block
    elif kind == 1:                                 # VERBATIM
        s = [br.signed(bps) for _ in range(block)]
    elif 8 <= kind <= 12:                           # FIXED
        order = kind - 8
        s = [br.signed(bps) for _ in range(order)]
        res = []
        _residual(br, block, order, res)
        c = FIXED_COEFS[order]
        for r in res:
            p = 0
            for j, cj in enumerate(c):
                p += cj * s[-1 - j]
            s.append(p + r)
    elif kind >= 32:                                # LPC
        order = kind - 31
        s = [br.signed(bps) for _ in range(order)]
        precision = br.read(4) + 1
        if precision == 16:
            raise FlacCorrupt("invalid LPC precision")
        shift = br.signed(5)
        if shift < 0:
            raise FlacError("negative LPC shift is not supported (ffmpeg never writes it)")
        coefs = [br.signed(precision) for _ in range(order)]
        res = []
        _residual(br, block, order, res)
        for r in res:
            p = 0
            n = len(s)
            for j in range(order):
                p += coefs[j] * s[n - 1 - j]
            s.append((p >> shift) + r)
    else:
        raise FlacCorrupt(f"reserved subframe type {kind}")
    return [v << wasted for v in s] if wasted else s


def _utf8_number(br):
    first = br.read(8)
    if first < 0x80:
        return first
    extra = 0
    mask = 0x40
    while first & mask:
        extra += 1
        mask >>= 1
    value = first & (mask - 1)
    for _ in range(extra):
        value = (value << 6) | (br.read(8) & 0x3F)
    return value


def _frame(data, pos, info):
    """(channel sample lists, next position)."""
    br = BitReader(data, pos)
    sync = br.read(15)
    if sync != 0x7FFC:
        raise FlacCorrupt(f"no frame sync at byte {pos}")
    br.read(1)                                      # blocking strategy (fixed or variable): not needed to decode
    bs_code, rate_code, layout, bits_code = br.read(4), br.read(4), br.read(4), br.read(3)
    br.read(1)
    _utf8_number(br)
    if bs_code == 6:
        block = br.read(8) + 1
    elif bs_code == 7:
        block = br.read(16) + 1
    elif bs_code in BLOCK_SIZES:
        block = BLOCK_SIZES[bs_code]
    else:
        raise FlacCorrupt(f"reserved block size code {bs_code}")
    if rate_code == 12:
        br.read(8)
    elif rate_code in (13, 14):
        br.read(16)
    bps = info["bits"] if bits_code == 0 else BITS.get(bits_code)
    if bps not in SUPPORTED_BITS:
        raise FlacError(f"a frame says {bps}-bit samples; this decoder reads 16- and 24-bit")
    head_end = br.byte_pos()
    if br.read(8) != crc8(data[pos:head_end]):
        raise FlacCorrupt(f"frame header CRC mismatch at byte {pos}")
    if layout < 8:
        nch = layout + 1
        side = None
    elif layout <= 10:
        nch = 2
        side = {8: 1, 9: 0, 10: 1}[layout]          # which channel carries the side signal (one extra bit)
    else:
        raise FlacCorrupt(f"reserved channel layout {layout}")
    if nch != info["channels"]:
        raise FlacCorrupt(f"a frame has {nch} channels, STREAMINFO says {info['channels']}")
    chans = [_subframe(br, block, bps + (1 if c == side else 0)) for c in range(nch)]
    if layout == 8:                                 # left / side
        chans[1] = [a - b for a, b in zip(chans[0], chans[1])]
    elif layout == 9:                               # side / right
        chans[0] = [a + b for a, b in zip(chans[0], chans[1])]
    elif layout == 10:                              # mid / side
        mid, sd = chans
        left, right = [], []
        for m, s in zip(mid, sd):
            m = (m << 1) | (s & 1)
            left.append((m + s) >> 1)
            right.append((m - s) >> 1)
        chans = [left, right]
    br.align()
    end = br.byte_pos()
    if br.read(16) != crc16(data[pos:end]):
        raise FlacCorrupt(f"frame CRC-16 mismatch at byte {pos}")
    return chans, br.byte_pos()


def stream(data):
    """(info, frames): frames() yields one list of ints per channel for each frame, in order, and checks the
    sample count and the MD5 once the last frame is out (FlacCorrupt then); info gains "md5_status" ('ok' or
    'unset') at that point. Memory: the file plus one frame, whatever the length."""
    info, start = read_streaminfo(data)

    def frames():
        pos, done, total = start, 0, info["total"]
        width = info["bits"] // 8
        md5 = hashlib.md5()
        while pos < len(data) and (not total or done < total):
            chans, pos = _frame(data, pos, info)
            if total and done + len(chans[0]) > total:
                chans = [c[:total - done] for c in chans]
            done += len(chans[0])
            if width == 2:
                md5.update(struct.pack(f"<{len(chans[0]) * len(chans)}h", *(s for f in zip(*chans) for s in f)))
            else:
                md5.update(b"".join((s & 0xFFFFFF).to_bytes(3, "little") for f in zip(*chans) for s in f))
            yield chans
        if total and done < total:
            raise FlacCorrupt(f"decoded {done} samples, STREAMINFO says {total} (truncated)")
        if info["md5"] == bytes(16):
            info["md5_status"] = "unset"
        elif md5.digest() != info["md5"]:
            raise FlacCorrupt("decoded audio does not match the file's MD5 (corrupt file or a decoder bug)")
        else:
            info["md5_status"] = "ok"
    return info, frames


def decode(data):
    """(info, list of int sample lists per channel, md5_status) where md5_status is 'ok' or 'unset'."""
    info, frames = stream(data)
    chans = [[] for _ in range(info["channels"])]
    for frame in frames():
        for c, s in zip(chans, frame):
            c.extend(s)
    return info, chans, info["md5_status"]


def read_flac(path):
    """(samples as floats in -1..1, interleaved for stereo, rate, channels). Raises FlacError / FlacCorrupt."""
    info, chans, _ = decode(Path(path).read_bytes())
    scale = float(1 << (info["bits"] - 1))
    if len(chans) == 1:
        return [s / scale for s in chans[0]], info["rate"], 1
    return [s / scale for pair in zip(*chans) for s in pair], info["rate"], len(chans)


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Decode FLAC (16/24-bit, mono/stereo) with the standard library only.",
                                 epilog="Exit codes: 0 ok, 1 the file decodes wrong, 2 usage or unsupported file.")
    sub = ap.add_subparsers(dest="cmd")
    p_info = sub.add_parser("info", help="rate, channels, bits, length, and whether the audio matches its MD5")
    p_info.add_argument("flac")
    p_wav = sub.add_parser("towav", help="decode to a 16-bit WAV (no tags carried over)")
    p_wav.add_argument("flac")
    p_wav.add_argument("--out", required=True)
    p_wav.add_argument("--overwrite", action="store_true")
    for p in (p_info, p_wav):
        p.add_argument("--debug", action="store_true", help="tracebacks")
    args = ap.parse_args(argv)
    DEBUG = getattr(args, "debug", False)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        data = Path(args.flac).read_bytes()
        info, chans, status = decode(data)
        seconds = len(chans[0]) / info["rate"]
        md5_note = "audio matches its MD5" if status == "ok" else "MD5 unset by the encoder: only frame CRCs checked"
        if args.cmd == "info":
            print(f"[ OK ] {args.flac}: {info['rate']} Hz, {info['channels']} ch, {info['bits']}-bit, "
                  f"{seconds:.3f} s, {md5_note}")
            return 0
        out = Path(args.out)
        check_wav_name(out)                         # before the decode: a wrong name costs nothing
        if out.exists() and not args.overwrite:
            print(f"[error] {out} exists (use --overwrite)", file=sys.stderr)
            return 2
        samples, rate, channels = read_flac(args.flac)
        clipped = write_wav(out, samples, rate, channels=channels)
        st = stats(samples if channels == 1 else samples[0::2], rate)
        print(f"[ OK ] {out}: {seconds:.3f} s, peak {st['peak_dbfs']} dBFS, {md5_note}"
              + (f", {clipped} samples clipped (24-bit to 16-bit)" if clipped else ""))
        return 0
    except FlacCorrupt as exc:
        print(f"[FAIL] {args.flac}: {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 1
    except (FlacError, WavNameError, OSError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

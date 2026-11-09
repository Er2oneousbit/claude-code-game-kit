#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# oggvorbis.py
# Purpose : Decode Ogg Vorbis files to samples with the standard library only, so audio tools can read the .ogg
#           files that libraries, packs and engines ship (Godot and LOVE both favour Ogg Vorbis) and write a
#           clean WAV with wavfile.py. Decoding keeps the sound and nothing else: the comment tags never reach
#           the WAV.
# Usage   : from oggvorbis import read_ogg
#           samples, rate, channels = read_ogg("music.ogg")       # floats around -1..1, interleaved L R L R
#           python tools/audio/wavesmith/oggvorbis.py info music.ogg         # rate, channels, length, tags
#           python tools/audio/wavesmith/oggvorbis.py towav music.ogg --out music.wav
# Needs   : Python 3.8+ only
# Exit    : 0 ok, 1 the file decodes wrong (CRC mismatch, truncated, broken header), 2 usage, not Ogg Vorbis,
#           or unsupported
# Notes   : Scope is Vorbis I as real encoders write it (libvorbis, which ffmpeg's -c:a libvorbis uses): floor
#           type 1, residue types 0, 1 and 2, channel coupling, short and long blocks, any channel count (kept
#           in Vorbis channel order). Every Ogg page's CRC-32 is checked. Start and end follow the granule
#           positions exactly as libvorbis 1.3.7 trims them (compared sample by sample through its own
#           vorbis_synthesis calls): a first page whose granule is below the samples decoded so far loses the
#           difference from the output of its last packet, at most that packet's samples (so not always the
#           very first samples), and the end trim takes at most the last packet's samples (ffmpeg 9.0.2 trims
#           neither a short first page nor a stream that fits on one page). A Vorbis stream multiplexed with video (Theora) or a Skeleton track decodes, the
#           other streams skipped. A stream that stops after a whole page without the end-of-stream flag (a cut
#           capture) decodes with a [warn], its end taken from that last page's granule position like an end
#           page's; a file that stops inside a page or a packet is truncated (exit 1). towav reads the channel
#           count from the identification header and refuses more than 2 before decoding anything.
#           Floor type 0 (never written by libvorbis), chained streams and Ogg files
#           holding only another codec (Opus, FLAC, Speex) are refused by name, never guessed.
#           Limits: a page CRC proves nothing (anyone can recompute it), so a setup header may ask for at most
#           65536 entries and 1M VQ values per codebook and 262144 entries and 2M values in all (real libvorbis
#           files peak at 6561, 52488, 13411 and 61254), one packet may span at most 4 MB of pages (the bit
#           reader keeps 45 bytes per packet byte; the exam's libvorbis fixtures peak at 3.9 KB per packet), and
#           a file may decode to at most 16384 samples per byte
#           of file (at least 4M; digital 5.1 silence, the most compressible real file measured, is about 1600).
#           Past a limit: VorbisLimit (exit 2), naming it; decode(data, max_values=N) raises the output limit.
#           Accuracy: within 5e-7 of ffmpeg's decoder on every sample of a 47-file libvorbis corpus (q-1 to
#           q10, 11.025 to 48 kHz, mono to 5.1); the difference is float32 against double rounding.
#           Speed (measured, CPython 3.12): about 0.13 s per second of 44.1 kHz stereo at q3 and 0.2 s at q10;
#           Python 3.8 is about 25% slower, 5.1 surround about 0.6 s per second.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   Ogg pages ("OggS", CRC-32 each) -> pick the Vorbis logical stream -> join lacing segments into packets,
#     remembering the granule position (running sample count) of the last packet that ends on each page
#   header 1 identification: channels, rate, the short and long block sizes
#   header 3 comments: vendor + KEY=value list (returned to the caller, never written to the WAV)
#   header 5 setup: codebooks (Huffman lengths -> codewords, VQ lookup 1 or 2), floors (type 1),
#     residues (0, 1, 2), mappings (submaps + coupling steps), modes (block size flag + mapping)
#   per audio packet:
#     mode -> block size n (short or long) and the neighbours' sizes, which shape the window
#     per channel: floor 1 points (or 'unused': the channel is silent in this block)
#     residue vectors per submap (classification words, then up to 8 passes of VQ partitions)
#     undo magnitude/angle coupling -> spectrum = residue * floor curve -> inverse MDCT -> window
#     overlap-add with the previous block: output runs from the centre of the previous window to this one's
#   trim (libvorbis's rule): first granule < samples decoded so far -> drop the difference from the start of
#     that page's last packet's output; last page granule -> cut the end (both at most one packet's samples)
import argparse
import cmath
import math
import struct
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wavfile import WavNameError, check_wav_name, stats, write_wav  # noqa: E402

MAGIC = b"OggS"
# What a BOS page of another codec starts with, so a wrong file is named instead of called corrupt
OTHER_CODECS = ((b"OpusHead", "Opus"), (b"\x7fFLAC", "FLAC"), (b"fLaC", "FLAC"), (b"Speex   ", "Speex"),
                (b"\x80theora", "Theora video"), (b"fishead\0", "Skeleton"), (b"PCM     ", "PCM"))
PAD = 64            # spare slots at the end of residue vectors: a partition may overrun by part of a VQ vector
# Limits (see the header): what one setup header may build, and what one file may decode to
MAX_BOOK_ENTRIES = 1 << 16
MAX_BOOK_VALUES = 1 << 20
MAX_SETUP_ENTRIES = 1 << 18
MAX_SETUP_VALUES = 1 << 21
MAX_VALUES_PER_BYTE = 1 << 14
MIN_VALUES_ALLOWED = 1 << 22
MAX_PACKET_BYTES = 1 << 22      # BitReader keeps one 8-byte int per byte offset (45x the packet in memory, measured)
DEBUG = False


class VorbisError(Exception):
    """Exit 2: not an Ogg Vorbis file, or a Vorbis feature outside this decoder's scope."""


class VorbisLimit(VorbisError):
    """The file asks for more than this decoder allows (see Limits in the header): refused, not decoded."""


class VorbisCorrupt(Exception):
    """Exit 1: an Ogg Vorbis file that does not decode to what it says (CRC mismatch, truncated, broken header)."""


class _EndOfPacket(Exception):
    """A read ran past the end of a packet. Vorbis defines this as a normal condition inside audio packets
    (the rest of that floor or residue is zero), so it never leaves this module."""


# ---- Ogg layer ----
def _crc_table():
    table = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
        table.append(c)
    return table


CRC32 = _crc_table()


def ogg_crc(data):
    """Ogg's CRC-32 (polynomial 0x04C11DB7, MSB first, no reflection, initial 0, no final xor)."""
    c = 0
    table = CRC32
    for b in data:
        c = ((c << 8) & 0xFFFFFFFF) ^ table[(c >> 24) ^ b]
    return c


def _page(data, pos):
    """(flags, granule, serial, seq, lacing, body offset, end offset) for the page at pos; CRC checked."""
    n = len(data)
    if pos + 27 > n:
        raise VorbisCorrupt(f"the file ends inside a page header at byte {pos} (truncated)")
    if data[pos:pos + 4] != MAGIC:
        raise VorbisCorrupt(f"no Ogg page at byte {pos} (damaged file)")
    version, flags = data[pos + 4], data[pos + 5]
    granule, serial, seq, crc = struct.unpack_from("<qIII", data, pos + 6)
    nseg = data[pos + 26]
    body = pos + 27 + nseg
    if body > n:
        raise VorbisCorrupt(f"the file ends inside a page header at byte {pos} (truncated)")
    lacing = data[pos + 27:body]
    end = body + sum(lacing)
    if end > n:
        raise VorbisCorrupt(f"the file ends inside the page at byte {pos} (truncated)")
    if version != 0:
        raise VorbisCorrupt(f"Ogg page version {version} at byte {pos} (only version 0 exists)")
    page = bytearray(data[pos:end])
    page[22:26] = b"\0\0\0\0"                       # the CRC is computed with its own field zeroed
    if ogg_crc(page) != crc:
        raise VorbisCorrupt(f"page CRC mismatch at byte {pos} (damaged file)")
    return flags, granule, serial, seq, lacing, body, end


def _codec_name(packet):
    for sig, name in OTHER_CODECS:
        if packet.startswith(sig):
            return name
    return "an unknown codec"


def read_packets(data, warnings=None):
    """Packets of the first Vorbis logical stream as [bytes, granule or None, eos flag]. The granule is set on
    the last packet that ends on a page (Ogg stores one granule per page, for that packet). A stream that stops
    after a whole page and a whole packet without the end-of-stream flag is read up to there, and a note goes
    into `warnings` (a list) when one is given."""
    if data[:4] != MAGIC:
        raise VorbisError("not an Ogg file (no OggS page at the start)")
    pos, chosen, others = 0, None, []
    packets, partial, expect = [], None, None
    while True:
        if pos >= len(data):
            if partial is not None:
                raise VorbisCorrupt("the file ends in the middle of a packet, without the stream's last page "
                                    "(truncated)")
            if chosen is None or len(packets) < 4:
                raise VorbisCorrupt("the file ends before the stream's last page (truncated)")
            if warnings is not None:        # a capture or dump cut between pages: every page whole, CRCs good
                warnings.append(f"no end-of-stream page: the stream stops after page {(expect - 1) & 0xFFFFFFFF} "
                                f"(a cut capture or dump?); decoded to that page's granule position")
            return packets
        flags, granule, serial, seq, lacing, p, end = _page(data, pos)
        here = pos
        pos = end
        if chosen is None:
            # all BOS (beginning of stream) pages come first; each carries one codec's first header packet
            if not flags & 2:
                if others:
                    raise VorbisError(f"not Vorbis: {others[0]}; convert with ffmpeg "
                                      f"(for example: ffmpeg -i in.ogg -c:a libvorbis out.ogg)")
                raise VorbisCorrupt("the Ogg file has no stream header page")
            first = data[p:p + (lacing[0] if lacing else 0)]
            if first.startswith(b"\x01vorbis"):
                chosen = serial
            else:
                others.append(_codec_name(first))
                continue
        if serial != chosen:
            continue                                # another stream multiplexed in (video, skeleton): skip
        if expect is not None and seq != expect:
            raise VorbisCorrupt(f"page sequence jumps from {expect - 1} to {seq} at byte {here} (a page is missing)")
        expect = (seq + 1) & 0xFFFFFFFF
        if flags & 1 and partial is None:
            raise VorbisCorrupt(f"page at byte {here} continues a packet that never started")
        if not flags & 1 and partial is not None:
            raise VorbisCorrupt(f"a packet is cut short before the page at byte {here}")
        last = None
        for lv in lacing:
            if partial is None:
                partial = bytearray()
            partial += data[p:p + lv]
            if len(partial) > MAX_PACKET_BYTES:
                raise VorbisLimit(f"a packet of over {MAX_PACKET_BYTES} bytes at byte {here}: over this decoder's "
                                  f"limit (real Vorbis packets stay under a few kilobytes); convert it with ffmpeg "
                                  f"if it is genuine")
            p += lv
            if lv < 255:                            # a segment under 255 bytes ends the packet
                packets.append([bytes(partial), None, False])
                partial, last = None, len(packets) - 1
        if last is not None:
            packets[last][1] = granule
            packets[last][2] = bool(flags & 4)
        if flags & 4:                               # EOS: the logical stream ends here
            if partial is not None:
                raise VorbisCorrupt("the last page ends in the middle of a packet")
            break
    if data[pos:pos + 4] == MAGIC and pos + 6 <= len(data) and data[pos + 5] & 2:
        raise VorbisError("chained Ogg stream (a second stream follows the first): not supported; "
                          "split or re-encode it with ffmpeg")
    return packets


def identification(data):
    """The Vorbis identification header (rate, channels, block sizes, bitrates) from the stream's first page
    alone, without decoding: the BOS pages come first and Vorbis's own holds just that packet."""
    if data[:4] != MAGIC:
        raise VorbisError("not an Ogg file (no OggS page at the start)")
    pos, others = 0, []
    while pos < len(data):
        flags, _, _, _, lacing, p, end = _page(data, pos)
        if not flags & 2:
            break
        first = data[p:p + (lacing[0] if lacing else 0)]
        if first.startswith(b"\x01vorbis"):
            return _read_identification(first)
        others.append(_codec_name(first))
        pos = end
    if others:
        raise VorbisError(f"not Vorbis: {others[0]}; convert with ffmpeg "
                          f"(for example: ffmpeg -i in.ogg -c:a libvorbis out.ogg)")
    raise VorbisCorrupt("the Ogg file has no stream header page")


# ---- bit reading (Vorbis packs bits LSB first) ----
def _words(packet):
    """For every byte offset, the 8 bytes starting there as one little-endian integer: any read of up to 57
    bits is then one list index, one shift and one mask, which is what keeps Huffman decoding tolerable."""
    b = bytes(packet) + bytes(24)
    fb = int.from_bytes
    return [fb(b[i:i + 8], "little") for i in range(len(packet) + 16)]


class BitReader:
    def __init__(self, packet, pos=0):
        self.w, self.pos, self.limit = _words(packet), pos, len(packet) * 8

    def read(self, n):
        if n == 0:
            return 0
        if n > 32:
            lo = self.read(32)
            return lo | (self.read(n - 32) << 32)
        p = self.pos
        v = (self.w[p >> 3] >> (p & 7)) & ((1 << n) - 1)
        self.pos = p + n
        if self.pos > self.limit:
            raise _EndOfPacket()
        return v


def ilog(x):
    """Vorbis ilog: the number of bits needed to hold x (0 for x <= 0)."""
    return x.bit_length() if x > 0 else 0


def _float32(x):
    """Vorbis's packed float: 21-bit mantissa, 10-bit exponent biased by 788, sign bit."""
    mant = x & 0x1FFFFF
    if x & 0x80000000:
        mant = -mant
    return math.ldexp(mant, ((x & 0x7FE00000) >> 21) - 788)


def _lookup1_values(entries, dims):
    """The largest r with r ** dims <= entries (lookup type 1 stores one value list shared by every axis)."""
    r = int(entries ** (1.0 / dims))
    while (r + 1) ** dims <= entries:
        r += 1
    while r > 0 and r ** dims > entries:
        r -= 1
    return r


# ---- codebooks ----
class Codebook:
    """Huffman decode table plus the VQ vectors. fast[i] = (entry << 6) | length for codes up to fbits long,
    indexed by the next fbits bits of the stream; -1 sends the decoder to the dictionaries of longer codes."""
    __slots__ = ("dims", "entries", "fast", "fmask", "longs", "vq")

    def __init__(self, dims, lengths, vq):
        self.dims, self.entries, self.vq = dims, len(lengths), vq
        used = [i for i, n in enumerate(lengths) if n]
        if not used:
            self.fast, self.fmask, self.longs = [-1], 0, []
            return
        if len(used) == 1:
            # one used entry: libvorbis treats it as a tree with no branches; any bits decode to it
            n = lengths[used[0]]
            fb = min(n, 11)
            self.fast, self.fmask, self.longs = [(used[0] << 6) | n] * (1 << fb), (1 << fb) - 1, []
            if n > fb:
                self.fast = [-1] * (1 << fb)
                self.longs = [(n, (1 << n) - 1, {k: (used[0] << 6) | n for k in range(1 << fb)})]
            return
        codes = _huffman_codes(lengths, used)
        maxlen = max(lengths[i] for i in used)
        fb = min(maxlen, 11)
        fast = [-1] * (1 << fb)
        longs = {}
        for i in used:
            n = lengths[i]
            rc = int(format(codes[i], f"0{n}b")[::-1], 2)       # the stream sends the code's first bit first
            value = (i << 6) | n
            if n <= fb:
                for k in range(1 << (fb - n)):
                    fast[rc | (k << n)] = value
            else:
                longs.setdefault(n, {})[rc] = value
        self.fast, self.fmask = fast, (1 << fb) - 1
        self.longs = [(n, (1 << n) - 1, longs[n]) for n in sorted(longs)]

    def slow(self, bits):
        for _, mask, table in self.longs:
            v = table.get(bits & mask)
            if v is not None:
                return v
        return -1


def _huffman_codes(lengths, used):
    """Codewords in entry order, each the lowest free leaf of its length (libvorbis's _make_words)."""
    marker = [0] * 33
    codes = {}
    for i in used:
        n = lengths[i]
        entry = marker[n]
        if n < 32 and entry >> n:
            raise VorbisCorrupt("a codebook's Huffman lengths overfill the code tree (broken setup header)")
        codes[i] = entry
        for j in range(n, 0, -1):                   # move the markers on the path above the leaf just taken
            if marker[j] & 1:
                if j == 1:
                    marker[1] += 1
                else:
                    marker[j] = marker[j - 1] << 1
                break
            marker[j] += 1
        for j in range(n + 1, 33):                  # longer markers dangling from the taken leaf move too
            if (marker[j] >> 1) == entry:
                entry = marker[j]
                marker[j] = marker[j - 1] << 1
            else:
                break
    return codes


def _read_codebook(br, budget):
    """One codebook. budget = [entries, VQ values] still allowed in this setup header (spent here)."""
    if br.read(24) != 0x564342:
        raise VorbisCorrupt("codebook sync pattern missing (broken setup header)")
    dims, entries = br.read(16), br.read(24)
    if dims < 1 or entries < 1:
        raise VorbisCorrupt(f"a codebook with {dims} dimension(s) and {entries} entries (broken setup header)")
    if entries > MAX_BOOK_ENTRIES or entries > budget[0]:
        raise VorbisLimit(f"a codebook with {entries} entries: over this decoder's limit "
                          f"({MAX_BOOK_ENTRIES} per codebook, {MAX_SETUP_ENTRIES} in all; real files use under 7000)")
    budget[0] -= entries
    lengths = [0] * entries
    if not br.read(1):                              # not ordered: one length per entry, maybe sparse
        sparse = br.read(1)
        for i in range(entries):
            if not sparse or br.read(1):
                lengths[i] = br.read(5) + 1
    else:                                           # ordered: runs of entries per increasing length
        length, i = br.read(5) + 1, 0
        while i < entries:
            count = br.read(ilog(entries - i))
            if i + count > entries or (count and length > 32):
                raise VorbisCorrupt("ordered codebook lengths run past the entry count (broken setup header)")
            lengths[i:i + count] = [length] * count
            i += count
            length += 1
    lookup = br.read(4)
    vq = None
    if lookup in (1, 2):
        if entries * dims > MAX_BOOK_VALUES or entries * dims > budget[1]:
            raise VorbisLimit(f"a codebook of {entries} x {dims} values: over this decoder's limit "
                              f"({MAX_BOOK_VALUES} per codebook, {MAX_SETUP_VALUES} in all; real files use under 60000)")
        budget[1] -= entries * dims
        minimum, delta = _float32(br.read(32)), _float32(br.read(32))
        value_bits, sequence = br.read(4) + 1, br.read(1)
        nvals = _lookup1_values(entries, dims) if lookup == 1 else entries * dims
        mult = [br.read(value_bits) * delta + minimum for _ in range(nvals)]
        vq = []
        for e in range(entries):
            vec, last = [], 0.0
            if lookup == 1:
                div = 1
                for _ in range(dims):
                    v = mult[(e // div) % nvals] + last
                    vec.append(v)
                    if sequence:
                        last = v
                    div *= nvals
            else:
                for k in range(e * dims, e * dims + dims):
                    v = mult[k] + last
                    vec.append(v)
                    if sequence:
                        last = v
            vq.append(tuple(vec))
    elif lookup != 0:
        raise VorbisCorrupt(f"codebook lookup type {lookup} (only 0, 1 and 2 exist)")
    return Codebook(dims, lengths, vq)


def _scalar(book, br):
    """Next entry number from book (Huffman only)."""
    p = br.pos
    x = br.w[p >> 3] >> (p & 7)
    e = book.fast[x & book.fmask]
    if e < 0:
        e = book.slow(x)
        if e < 0:
            raise _EndOfPacket()                    # no such codeword: libvorbis stops this decode the same way
    p += e & 63
    if p > br.limit:
        raise _EndOfPacket()
    br.pos = p
    return e >> 6


# ---- setup header: floors, residues, mappings, modes ----
class Floor1:
    __slots__ = ("pclass", "cdims", "csubs", "cmaster", "csubbooks", "mult", "X", "order", "low", "high",
                 "range", "ybits")


def _read_floor1(br, nbooks):
    f = Floor1()
    partitions = br.read(5)
    f.pclass = [br.read(4) for _ in range(partitions)]
    f.cdims, f.csubs, f.cmaster, f.csubbooks = [], [], [], []
    for _ in range(max(f.pclass) + 1 if f.pclass else 0):
        f.cdims.append(br.read(3) + 1)
        subs = br.read(2)
        f.csubs.append(subs)
        f.cmaster.append(br.read(8) if subs else -1)
        f.csubbooks.append([br.read(8) - 1 for _ in range(1 << subs)])
    f.mult = br.read(2) + 1
    rangebits = br.read(4)
    f.X = [0, 1 << rangebits]
    for c in f.pclass:
        f.X.extend(br.read(rangebits) for _ in range(f.cdims[c]))
    if len(f.X) > 65 or len(set(f.X)) != len(f.X):
        raise VorbisCorrupt("floor 1 has more than 65 points or a repeated X (broken setup header)")
    books = [b for b in f.cmaster if b >= 0] + [b for s in f.csubbooks for b in s if b >= 0]
    if any(b >= nbooks for b in books):
        raise VorbisCorrupt("floor 1 names a codebook that does not exist (broken setup header)")
    f.order = sorted(range(len(f.X)), key=f.X.__getitem__)
    # each new point is predicted from its nearest already-known neighbours on either side
    f.low, f.high = [0, 0], [0, 0]
    for i in range(2, len(f.X)):
        x = f.X[i]
        below = [j for j in range(i) if f.X[j] < x]
        above = [j for j in range(i) if f.X[j] > x]
        f.low.append(max(below, key=f.X.__getitem__))
        f.high.append(min(above, key=f.X.__getitem__))
    f.range = (256, 128, 86, 64)[f.mult - 1]
    f.ybits = ilog(f.range - 1)
    return f


class Residue:
    __slots__ = ("type", "begin", "end", "psize", "ncls", "classbook", "books")


def _read_residue(br, rtype, books):
    r = Residue()
    r.type, r.begin, r.end = rtype, br.read(24), br.read(24)
    r.psize, r.ncls, r.classbook = br.read(24) + 1, br.read(6) + 1, br.read(8)
    cascade = []
    for _ in range(r.ncls):
        low = br.read(3)
        high = br.read(5) if br.read(1) else 0
        cascade.append(high * 8 + low)
    r.books = [[br.read(8) if (c >> j) & 1 else -1 for j in range(8)] for c in cascade]
    if r.classbook >= len(books) or books[r.classbook].dims < 1:
        raise VorbisCorrupt("a residue names a classification codebook that does not exist (broken setup header)")
    for row in r.books:
        for b in row:
            if b >= 0 and (b >= len(books) or books[b].vq is None or books[b].dims < 1):
                raise VorbisCorrupt("a residue names a codebook without VQ values (broken setup header)")
    return r


def _read_setup(packet, channels):
    if packet[:7] != b"\x05vorbis":
        raise VorbisCorrupt("the third packet is not a Vorbis setup header")
    br = BitReader(packet, 56)
    try:
        budget = [MAX_SETUP_ENTRIES, MAX_SETUP_VALUES]
        books = [_read_codebook(br, budget) for _ in range(br.read(8) + 1)]
        for _ in range(br.read(6) + 1):             # time domain transforms: placeholders, always 0
            if br.read(16) != 0:
                raise VorbisCorrupt("nonzero time domain transform type (broken setup header)")
        floors = []
        for _ in range(br.read(6) + 1):
            ftype = br.read(16)
            if ftype == 0:
                raise VorbisError("floor type 0 is not supported (libvorbis has never written it); "
                                  "re-encode with ffmpeg -c:a libvorbis")
            if ftype != 1:
                raise VorbisCorrupt(f"floor type {ftype} (only 0 and 1 exist)")
            floors.append(_read_floor1(br, len(books)))
        residues = []
        for _ in range(br.read(6) + 1):
            rtype = br.read(16)
            if rtype > 2:
                raise VorbisCorrupt(f"residue type {rtype} (only 0, 1 and 2 exist)")
            residues.append(_read_residue(br, rtype, books))
        mappings = []
        for _ in range(br.read(6) + 1):
            mappings.append(_read_mapping(br, channels, len(floors), len(residues)))
        modes = []
        for _ in range(br.read(6) + 1):
            blockflag, window, transform, mapping = br.read(1), br.read(16), br.read(16), br.read(8)
            if window or transform or mapping >= len(mappings):
                raise VorbisCorrupt("a mode has a nonzero window/transform type or a missing mapping")
            modes.append((blockflag, mapping))
        if not br.read(1):
            raise VorbisCorrupt("setup header framing bit missing")
    except _EndOfPacket:
        raise VorbisCorrupt("the setup header ends early (broken file)") from None
    return {"books": books, "floors": floors, "residues": residues, "mappings": mappings, "modes": modes,
            "mode_bits": ilog(len(modes) - 1)}


def _read_mapping(br, channels, nfloors, nresidues):
    if br.read(16) != 0:
        raise VorbisCorrupt("mapping type other than 0 (broken setup header)")
    submaps = br.read(4) + 1 if br.read(1) else 1
    coupling = []
    if br.read(1):
        bits = ilog(channels - 1)
        for _ in range(br.read(8) + 1):
            mag, ang = br.read(bits), br.read(bits)
            if mag == ang or mag >= channels or ang >= channels:
                raise VorbisCorrupt("a coupling step names an invalid channel pair (broken setup header)")
            coupling.append((mag, ang))
    if br.read(2):
        raise VorbisCorrupt("mapping reserved bits are set (broken setup header)")
    mux = [br.read(4) for _ in range(channels)] if submaps > 1 else [0] * channels
    subs = []
    for _ in range(submaps):
        br.read(8)                                  # unused time configuration
        floor, residue = br.read(8), br.read(8)
        if floor >= nfloors or residue >= nresidues:
            raise VorbisCorrupt("a mapping names a floor or residue that does not exist (broken setup header)")
        subs.append((floor, residue))
    if any(m >= submaps for m in mux):
        raise VorbisCorrupt("a channel maps to a submap that does not exist (broken setup header)")
    return {"coupling": coupling, "mux": mux, "submaps": subs}


def _read_identification(packet):
    if len(packet) < 30 or packet[:7] != b"\x01vorbis":
        raise VorbisCorrupt("the first packet is not a Vorbis identification header")
    version, channels, rate, bmax, bnom, bmin = struct.unpack_from("<IBIiii", packet, 7)
    if version != 0:
        raise VorbisError(f"Vorbis version {version} is not supported (only Vorbis I, version 0, exists)")
    bs0, bs1 = 1 << (packet[28] & 15), 1 << (packet[28] >> 4)
    if not channels or not rate or not 64 <= bs0 <= bs1 <= 8192 or not packet[29] & 1:
        raise VorbisCorrupt("invalid identification header (channels, rate, block sizes or framing bit)")
    return {"rate": rate, "channels": channels, "bitrate_nominal": bnom, "bitrate_max": bmax,
            "bitrate_min": bmin, "blocksizes": (bs0, bs1)}


def _read_comments(packet):
    """(vendor, [(key, value), ...]) keys as written (Vorbis keys are case-insensitive)."""
    if packet[:7] != b"\x03vorbis":
        raise VorbisCorrupt("the second packet is not a Vorbis comment header")
    try:
        pos = 7
        (n,) = struct.unpack_from("<I", packet, pos)
        vendor = packet[pos + 4:pos + 4 + n].decode("utf-8", "replace")
        pos += 4 + n
        (count,) = struct.unpack_from("<I", packet, pos)
        pos += 4
        comments = []
        for _ in range(count):
            (n,) = struct.unpack_from("<I", packet, pos)
            if pos + 4 + n > len(packet):
                raise struct.error("comment runs past the packet")
            text = packet[pos + 4:pos + 4 + n].decode("utf-8", "replace")
            pos += 4 + n
            key, _, value = text.partition("=")
            comments.append((key, value))
    except struct.error:
        raise VorbisCorrupt("the comment header ends early (broken file)") from None
    return vendor, comments


# ---- audio packets ----
def _floor1_read(f, books, br):
    """Raw floor 1 Y values, or None when the channel is unused in this block."""
    if not br.read(1):
        return None
    Y = [br.read(f.ybits), br.read(f.ybits)]
    for c in f.pclass:
        cbits = f.csubs[c]
        csub = (1 << cbits) - 1
        cval = _scalar(books[f.cmaster[c]], br) if cbits else 0
        subs = f.csubbooks[c]
        for _ in range(f.cdims[c]):
            book = subs[cval & csub]
            cval >>= cbits
            Y.append(_scalar(books[book], br) if book >= 0 else 0)
    return Y


def _inverse_db():
    # floor1_inverse_dB_table: 256 steps of a geometric scale from 1.0649863e-07 up to 1.0
    step = math.log(1.0649863e-07) / 255.0
    return [math.exp(step * (255 - i)) for i in range(256)]


INVERSE_DB = _inverse_db()


def _floor1_curve(f, Y, n):
    """The floor curve (n linear amplitudes) from the decoded Y values: predict each point from its neighbours,
    apply the coded offset, then draw integer lines between the points that matter (step 2 flags)."""
    X, rng = f.X, f.range
    final = [0] * len(X)
    step2 = [False] * len(X)
    final[0], final[1] = Y[0], Y[1]
    step2[0] = step2[1] = True
    for i in range(2, len(X)):
        lo, hi = f.low[i], f.high[i]
        x0, y0, x1, y1 = X[lo], final[lo], X[hi], final[hi]
        dy = y1 - y0
        off = abs(dy) * (X[i] - x0) // (x1 - x0)
        pred = y0 - off if dy < 0 else y0 + off
        val = Y[i]
        if val:
            highroom, lowroom = rng - pred, pred
            room = (highroom if highroom < lowroom else lowroom) * 2
            step2[lo] = step2[hi] = step2[i] = True
            if val >= room:
                final[i] = val - lowroom + pred if highroom > lowroom else pred - val + highroom - 1
            elif val & 1:
                final[i] = pred - ((val + 1) >> 1)
            else:
                final[i] = pred + (val >> 1)
        else:
            final[i] = pred
    mult, db = f.mult, INVERSE_DB
    out = []
    lx, ly = 0, min(255, max(0, final[f.order[0]] * mult))
    for i in f.order[1:]:
        if not step2[i]:
            continue
        hx, hy = X[i], min(255, max(0, final[i] * mult))
        _line(lx, ly, hx, hy, out, db)
        lx, ly = hx, hy
        if lx >= n:
            break
    if lx < n:
        out.extend([db[ly]] * (n - lx))
    return out[:n]


def _line(x0, y0, x1, y1, out, db):
    """Bresenham-style integer line from (x0, y0) to (x1, y1), x1 excluded, appended as amplitudes."""
    adx = x1 - x0
    if adx <= 0:
        return
    dy = y1 - y0
    if dy == 0:
        out.extend([db[y0]] * adx)
        return
    ady = abs(dy)
    base = ady // adx                               # C division truncates toward zero; keep that sign rule
    if dy < 0:
        base, sy = -base, -base - 1
    else:
        sy = base + 1
    ady -= abs(base) * adx
    y, err = y0, 0
    append = out.append
    append(db[y])
    for _ in range(adx - 1):
        err += ady
        if err >= adx:
            err -= adx
            y += sy
        else:
            y += base
        append(db[y])


def _residue(r, books, br, vectors, skip, half):
    """Add one residue's decoded values into vectors (one list per channel of this submap, each half + PAD
    long). skip marks channels that are 'do not decode'. Running out of packet ends the decode quietly."""
    ch = len(vectors)
    if r.type == 2:
        if all(skip):
            return
        size = half * ch
        work, wskip = [[0.0] * (size + PAD)], [False]   # type 2: one interleaved vector for all channels
    else:
        size, work, wskip = half, vectors, skip
    begin, end = min(r.begin, size), min(r.end, size)
    psize = r.psize
    nparts = (end - begin) // psize
    if nparts > 0:
        classbook = books[r.classbook]
        cpc, ncls, rbooks = classbook.dims, r.ncls, r.books
        cls = [[0] * (nparts + cpc) for _ in work]
        W, limit = br.w, br.limit
        pos = br.pos
        try:
            for stage in range(8):
                p = 0
                while p < nparts:
                    if stage == 0:
                        for j in range(len(work)):
                            if wskip[j]:
                                continue
                            temp = _scalar(classbook, br)
                            cl = cls[j]
                            for i in range(cpc - 1, -1, -1):     # one classword packs cpc base-ncls digits
                                cl[p + i] = temp % ncls
                                temp //= ncls
                        pos = br.pos
                    for _ in range(cpc):
                        if p >= nparts:
                            break
                        for j in range(len(work)):
                            if wskip[j]:
                                continue
                            bi = rbooks[cls[j][p]][stage]
                            if bi < 0:
                                continue
                            book = books[bi]
                            fast, fmask, vq, v = book.fast, book.fmask, book.vq, work[j]
                            off = begin + p * psize
                            stop = off + psize
                            if r.type == 0:
                                # type 0 interleaves each VQ vector across the partition with a stride
                                step = psize // book.dims
                                for k in range(step):
                                    x = W[pos >> 3] >> (pos & 7)
                                    e = fast[x & fmask]
                                    if e < 0:
                                        e = book.slow(x)
                                        if e < 0:
                                            raise _EndOfPacket()
                                    pos += e & 63
                                    if pos > limit:
                                        raise _EndOfPacket()
                                    o = off + k
                                    for val in vq[e >> 6]:
                                        v[o] += val
                                        o += step
                            else:
                                while off < stop:
                                    x = W[pos >> 3] >> (pos & 7)
                                    e = fast[x & fmask]
                                    if e < 0:
                                        e = book.slow(x)
                                        if e < 0:
                                            raise _EndOfPacket()
                                    pos += e & 63
                                    if pos > limit:
                                        raise _EndOfPacket()
                                    for val in vq[e >> 6]:
                                        v[off] += val
                                        off += 1
                            br.pos = pos
                        p += 1
        except _EndOfPacket:
            br.pos = limit + 1
    if r.type == 2:
        inter = work[0]
        for j in range(ch):
            vectors[j][:half] = inter[j:size:ch]


def _audio_packet(setup, ident, packet):
    """(blockflag, previous long flag, next long flag, per-channel spectra or None for silent) or None when
    the packet is not an audio packet or ends before its header."""
    br = BitReader(packet)
    ch = ident["channels"]
    try:
        if br.read(1):
            return None
        mode = br.read(setup["mode_bits"])
        if mode >= len(setup["modes"]):
            return None
        blockflag, mapping_i = setup["modes"][mode]
        prev_long = next_long = 0
        if blockflag:
            prev_long, next_long = br.read(1), br.read(1)
    except _EndOfPacket:
        return None
    half = ident["blocksizes"][blockflag] // 2
    mapping, books, floors = setup["mappings"][mapping_i], setup["books"], setup["floors"]
    floor_y = []
    for c in range(ch):
        f = floors[mapping["submaps"][mapping["mux"][c]][0]]
        try:
            floor_y.append(_floor1_read(f, books, br))
        except _EndOfPacket:
            floor_y.append(None)
            br.pos = br.limit + 1
    # a channel coupled to a nonzero channel still carries residue, even when its own floor is unused
    no_residue = [y is None for y in floor_y]
    for mag, ang in mapping["coupling"]:
        if not no_residue[mag] or not no_residue[ang]:
            no_residue[mag] = no_residue[ang] = False
    res = [[0.0] * (half + PAD) for _ in range(ch)]
    for s, (_, residue_i) in enumerate(mapping["submaps"]):
        idx = [c for c in range(ch) if mapping["mux"][c] == s]
        _residue(setup["residues"][residue_i], books, br, [res[c] for c in idx], [no_residue[c] for c in idx],
                 half)
    res = [v[:half] for v in res]
    for mag, ang in reversed(mapping["coupling"]):
        _uncouple(res[mag], res[ang])
    spectra = []
    for c in range(ch):
        if floor_y[c] is None:
            spectra.append(None)
            continue
        f = floors[mapping["submaps"][mapping["mux"][c]][0]]
        curve = _floor1_curve(f, floor_y[c], half)
        spectra.append([a * b for a, b in zip(res[c], curve)])
    return blockflag, prev_long, next_long, spectra


def _uncouple(m, a):
    """Square polar (magnitude / angle) back to two channels, in place."""
    for j in range(len(m)):
        M, A = m[j], a[j]
        if M > 0:
            if A > 0:
                a[j] = M - A
            else:
                a[j] = M
                m[j] = M + A
        else:
            if A > 0:
                a[j] = M + A
            else:
                a[j] = M
                m[j] = M - A


# ---- inverse MDCT (an N/4-point complex FFT inside a DCT-IV) and windows ----
_FFT_TWIDDLES = {}
_MDCT_TWIDDLES = {}
_WINDOWS = {}


def _fft(a):
    """Radix-2 complex FFT (forward sign) of a power-of-two list; list comprehensions per level keep it fast."""
    n = len(a)
    if n <= 4:
        if n == 4:
            a0, a1, a2, a3 = a
            s0, d0, s1, d1 = a0 + a2, a0 - a2, a1 + a3, (a1 - a3) * -1j
            return [s0 + s1, d0 + d1, s0 - s1, d0 - d1]
        if n == 2:
            return [a[0] + a[1], a[0] - a[1]]
        return list(a)
    tw = _FFT_TWIDDLES.get(n)
    if tw is None:
        tw = _FFT_TWIDDLES[n] = [cmath.exp(-2j * math.pi * k / n) for k in range(n // 2)]
    even, odd = _fft(a[0::2]), _fft(a[1::2])
    t = [o * w for o, w in zip(odd, tw)]
    return [e + x for e, x in zip(even, t)] + [e - x for e, x in zip(even, t)]


def imdct(spectrum):
    """Vorbis inverse MDCT: M = len(spectrum) coefficients to 2M samples,
    y[n] = sum_k X[k] cos(pi / M * (n + 1/2 + M/2) * (k + 1/2)), unscaled as libvorbis defines it."""
    M = len(spectrum)
    H = M >> 1
    tw = _MDCT_TWIDDLES.get(M)
    if tw is None:
        tw = _MDCT_TWIDDLES[M] = [cmath.exp(-1j * math.pi / M * (k + 0.125)) for k in range(H)]
    # DCT-IV of length M: pack even and reversed odd coefficients as complex, twiddle, FFT, twiddle
    c = [complex(a, b) * w for a, b, w in zip(spectrum[0::2], spectrum[M - 1::-2], tw)]
    d = [z * w for z, w in zip(_fft(c), tw)]
    u = [0.0] * M
    u[0::2] = [z.real for z in d]
    u[M - 1::-2] = [-z.imag for z in d]
    # the IMDCT is the DCT-IV unfolded by its symmetries (shifted by M/2, mirrored, negated)
    return u[H:] + [-v for v in reversed(u)] + [-v for v in u[:H]]


def _window(n, left_n, right_n):
    """Vorbis power-sine window for a block of n with the given left and right overlap lengths."""
    key = (n, left_n, right_n)
    w = _WINDOWS.get(key)
    if w is None:
        def slope(size, phase):
            return [math.sin(math.pi / 2 * math.sin((i + 0.5) / size * math.pi / 2 + phase) ** 2)
                    for i in range(size)]
        ls = n // 4 - left_n // 2
        rs = 3 * n // 4 - right_n // 2
        w = ([0.0] * ls + slope(left_n, 0.0) + [1.0] * (rs - ls - left_n) + slope(right_n, math.pi / 2)
             + [0.0] * (n - rs - right_n))
        _WINDOWS[key] = w
    return w


def _overlap(prev, prev_n, cur, cur_n):
    """Samples from the centre of the previous window to the centre of this one: the previous block's right half
    plus this block's left half, aligned on their overlap centres (n_prev/4 + n_cur/4 samples)."""
    off = prev_n // 4 - cur_n // 4
    if prev is None and cur is None:
        return [0.0] * (prev_n // 4 + cur_n // 4)
    if prev is None:
        prev = [0.0] * (prev_n // 2)
    if cur is None:
        cur = [0.0] * cur_n
    if off >= 0:
        total = prev_n // 4 + cur_n // 4
        return prev[:off] + [a + b for a, b in zip(prev[off:total], cur)]
    s = -off
    return [a + b for a, b in zip(prev, cur[s:s + prev_n // 2])] + cur[s + prev_n // 2:cur_n // 2]


# Python errors a broken file can still provoke deep in the maths: reported as a broken file, never a traceback
_BROKEN = (IndexError, KeyError, ValueError, ZeroDivisionError, OverflowError, struct.error)


def decode(data, max_values=None):
    """(info, list of float sample lists per channel, comments as [(key, value), ...]). max_values caps the
    samples decoded (all channels); default: MAX_VALUES_PER_BYTE per byte of data, at least MIN_VALUES_ALLOWED."""
    info, comments, chunks = stream(data, max_values)
    out = [[] for _ in range(info["channels"])]
    for chunk in chunks():
        for c, s in zip(out, chunk):
            c.extend(s)
    return info, out, comments


def stream(data, max_values=None):
    """(info, comments, chunks) without holding the decoded audio: the headers are read here (their errors
    raised here), chunks() yields lists of float samples per channel in order, trimmed exactly as decode() trims,
    and fills in info's samples, start_trim and end_trim when it ends. Memory: the packets (about the file's
    size) plus the audio between two granule positions, normally under a second."""
    if max_values is None:
        max_values = max(MIN_VALUES_ALLOWED, MAX_VALUES_PER_BYTE * len(data))
    try:
        info, comments, gen = _stream(data, max_values)
    except _BROKEN as exc:
        raise VorbisCorrupt(f"broken file ({type(exc).__name__}: {exc})") from None

    def chunks():
        try:
            yield from gen
        except _BROKEN as exc:
            raise VorbisCorrupt(f"broken file ({type(exc).__name__}: {exc})") from None
    return info, comments, chunks


def _stream(data, max_values):
    warnings = []
    packets = read_packets(data, warnings)
    if len(packets) < 3:
        raise VorbisCorrupt("the stream ends before its three Vorbis headers")
    ident = _read_identification(packets[0][0])
    vendor, comments = _read_comments(packets[1][0])
    setup = _read_setup(packets[2][0], ident["channels"])
    info = dict(ident)
    info.update({"samples": None, "vendor": vendor, "start_trim": None, "end_trim": None, "warnings": warnings})
    return info, comments, _audio(packets[3:], setup, ident, info, max_values, len(data))


def _audio(packets, setup, ident, info, max_values, size):
    """The decode loop behind stream(). Output stays pending until a granule position settles it: a trim only
    ever touches the output of the packet that carries the first granule or of the last one, so everything
    before the latest granule packet's own output is handed out."""
    ch = ident["channels"]
    bs0, bs1 = ident["blocksizes"]
    pending, pend_at = [[] for _ in range(ch)], 0   # output not handed out yet, from output index pend_at
    count, prev, prev_n = 0, None, 0
    first_count = first_granule = None      # samples decoded and granule at the first page that has one
    cut_at, cut = 0, 0                      # the start trim: cut samples from output index cut_at
    end_granule, end_made = None, 0
    handed = 0

    def take(n):
        """The first n pending samples per channel, without the start trim's samples when they are among them."""
        nonlocal pending, pend_at
        part, pending = [p[:n] for p in pending], [p[n:] for p in pending]
        lo = cut_at - pend_at
        if cut and 0 <= lo < n:
            part = [p[:lo] + p[lo + cut:] for p in part]
        pend_at += n
        return part

    for packet, granule, eos in packets:
        made = 0                            # samples this packet adds to the output
        try:
            decoded = _audio_packet(setup, ident, packet)
        except IndexError:
            raise VorbisCorrupt("an audio packet points outside its vectors (broken file)") from None
        if decoded is not None:
            blockflag, prev_long, next_long, spectra = decoded
            n = bs1 if blockflag else bs0
            left = bs1 // 2 if blockflag and prev_long else bs0 // 2
            right = bs1 // 2 if blockflag and next_long else bs0 // 2
            win = _window(n, left, right)
            blocks = [None if s is None else [a * b for a, b in zip(imdct(s), win)] for s in spectra]
            if prev is not None:                    # the very first block only primes the overlap
                for c in range(ch):
                    pending[c].extend(_overlap(prev[c], prev_n, blocks[c], n))
                made = prev_n // 4 + n // 4
                count += made
                if count * ch > max_values:
                    raise VorbisLimit(f"the file decodes to more than {max_values} samples ({size} bytes of "
                                      f"file; real Vorbis stays under about 2000 samples per byte): refused. "
                                      f"Convert it with ffmpeg if it is genuine")
            prev, prev_n = [None if b is None else b[n // 2:] for b in blocks], n
        if granule is not None and granule >= 0:
            if first_granule is None and not eos:
                # libvorbis (vorbis_synthesis_blockin): a first granule below the samples decoded so far drops
                # the difference from the output of the packet that carries it, at most what that packet made
                first_count, first_granule = count, granule
                cut = min(max(0, count - granule), made)
                cut_at = count - made
            end_granule, end_made = granule, made
            ready = count - made - pend_at          # all but this packet's output, which a trim may still cut
            if ready > 0:
                part = take(ready)
                handed += len(part[0])
                yield part
    last = count
    if end_granule is not None:
        # output index i >= first_count sits at stream position first_granule + (i - first_count); the end
        # granule ends the stream there. Like libvorbis, the end trim takes at most the last packet's samples
        want = end_granule if first_granule is None else first_count + end_granule - first_granule
        last = max(count - end_made, cut_at + cut, min(count, want))
    part = take(last - pend_at)
    handed += len(part[0])
    if part[0]:
        yield part
    info.update({"samples": handed, "start_trim": cut, "end_trim": count - last})


def read_ogg(path):
    """(samples as floats, interleaved for stereo, rate, channels). Raises VorbisError / VorbisCorrupt."""
    info, chans, _ = decode(Path(path).read_bytes())
    if len(chans) == 1:
        return chans[0], info["rate"], 1
    return [s for frame in zip(*chans) for s in frame], info["rate"], len(chans)


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Decode Ogg Vorbis with the standard library only.",
                                 epilog="Exit codes: 0 ok, 1 the file decodes wrong, 2 usage or unsupported file.")
    sub = ap.add_subparsers(dest="cmd")
    p_info = sub.add_parser("info", help="rate, channels, length, bitrate, encoder and tags")
    p_info.add_argument("ogg")
    p_wav = sub.add_parser("towav", aliases=["wav"], help="decode to a 16-bit WAV (mono or stereo, no tags)")
    p_wav.add_argument("ogg")
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
        if args.cmd != "info":
            out = Path(args.out)
            check_wav_name(out)                     # before the decode: a wrong name costs nothing
            if out.exists() and not args.overwrite:
                print(f"[error] {out} exists (use --overwrite)", file=sys.stderr)
                return 2
        data = Path(args.ogg).read_bytes()
        if args.cmd != "info":
            channels = identification(data)["channels"]
            if channels > 2:                        # from the header: refused before the (slow) decode
                raise VorbisError(f"{channels}-channel audio: the WAV writer here is mono or stereo only; "
                                  f"downmix with ffmpeg -ac 2 first")
        info, chans, comments = decode(data)
        for note in info["warnings"]:
            print(f"[warn] {args.ogg}: {note}", file=sys.stderr)
        seconds = info["samples"] / info["rate"]
        kbps = f", nominal {info['bitrate_nominal'] // 1000} kbit/s" if info["bitrate_nominal"] > 0 else ""
        if args.cmd == "info":
            print(f"[ OK ] {args.ogg}: {info['rate']} Hz, {info['channels']} ch, {seconds:.3f} s "
                  f"({info['samples']} samples){kbps}, encoder '{info['vendor']}', page CRCs ok")
            for key, value in comments:
                print(f"       {key}={value}")
            return 0
        samples =chans[0] if len(chans) == 1 else [s for frame in zip(*chans) for s in frame]
        clipped = write_wav(out, samples, info["rate"], channels=len(chans))
        st = stats(chans[0], info["rate"])
        print(f"[ OK ] {out}: {seconds:.3f} s, peak {st['peak_dbfs']} dBFS"
              + (f", {clipped} samples clipped (Vorbis can overshoot full scale)" if clipped else ""))
        return 0
    except VorbisCorrupt as exc:
        print(f"[FAIL] {args.ogg}: {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 1
    except (VorbisError, ValueError, OSError) as exc:  # ValueError: WavNameError, or a rate the WAV cannot hold
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

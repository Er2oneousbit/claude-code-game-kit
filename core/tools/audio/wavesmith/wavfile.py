#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# wavfile.py
# Purpose : Shared helper for the audio tools: write 16-bit mono or stereo PCM WAV files (optionally with a
#           'smpl' loop chunk that Godot, Unity and most samplers read as loop points), read mono or stereo WAVs
#           back (8 / 16 / 24 / 32-bit integer PCM or 32 / 64-bit float, plain or WAVE_FORMAT_EXTENSIBLE header),
#           and measure them (peak, loudness, duration, clicks at a loop seam).
# Usage   : from wavfile import write_wav, read_wav, stats
#           write_wav("out.wav", samples, 44100, loop=(0, len(samples) - 1))
#           python tools/audio/wavesmith/wavesmith.py wav stats assets/audio/x.wav
#           python tools/audio/wavesmith/wavesmith.py wav normalize assets/audio/x.wav --peak -3    # too-quiet generated audio
#           python tools/audio/wavesmith/wavesmith.py wav loop music.wav --crossfade 2 --end 95    # seamless loop from a download
# Notes   : Standard library only. Samples are floats in -1..1; anything outside is clipped and
#           counted, so a caller can warn. The smpl loop end is the last sample played (inclusive),
#           as the WAV spec says.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import math
import struct
from pathlib import Path

# fmt chunk format tags read here; WAVE_FORMAT_EXTENSIBLE names one of the first two in its sub-format GUID, whose
# last 12 bytes are the same for every standard format
TAG_PCM, TAG_FLOAT, TAG_EXTENSIBLE = 1, 3, 0xFFFE
GUID_TAIL = bytes.fromhex("000010008000" "00aa00389b71")
INT_BITS = (8, 16, 24, 32)
FLOAT_BITS = (32, 64)
# full scale per integer sample width in bytes (24-bit is widened to 32 bits first, so its scale is shifted too)
INT_SCALE = {1: 127.0, 2: 32767.0, 3: float(8388607 << 8), 4: 2147483647.0}
READS = "8 / 16 / 24 / 32-bit integer PCM or 32 / 64-bit float"


class WavFormatError(ValueError):
    """A WAV whose sample format this module does not read (ADPCM, A-law, ...): ffmpeg may still read it."""


def to_pcm16(samples):
    """(bytes, clipped_count) for float samples in -1..1."""
    out = bytearray()
    clipped = 0
    for s in samples:
        if s > 1.0:
            s, clipped = 1.0, clipped + 1
        elif s < -1.0:
            s, clipped = -1.0, clipped + 1
        out += struct.pack("<h", int(round(s * 32767)))
    return bytes(out), clipped


class WavNameError(ValueError):
    """A WAV was about to be written under another format's name (out.ogg holding RIFF bytes)."""


def check_wav_name(path):
    """Raises WavNameError unless path ends in .wav (any case): WAV bytes never go out under another name."""
    if Path(path).suffix.lower() not in (".wav", ".wave"):
        raise WavNameError(f"{path}: this writes a WAV, so the name must end in .wav (for OGG or MP3, write the .wav "
                           f"and convert it: wavesmith.py formats convert x.wav --out x.ogg)")


def write_wav(path, samples, rate, loop=None, channels=1):
    """Write a 16-bit WAV (stereo: samples interleaved L R L R). loop=(start, end) in frames adds a forward
    'smpl' loop (end inclusive). Returns the number of clipped samples. The path must end in .wav. ValueError for
    a rate the header cannot hold (a WAV or Vorbis header can say 0xFFFFFFFF Hz: the byte-rate field is 32 bits)."""
    check_wav_name(path)
    if not 1 <= rate <= 0xFFFFFFFF // (2 * channels):
        raise ValueError(f"{path}: a sample rate of {rate} Hz cannot be written to a WAV (the header's byte-rate "
                         f"field is 32 bits; a source that says this is broken)")
    data, clipped = to_pcm16(samples)
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * 2 * channels, 2 * channels, 16)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(data)) + data
    if len(data) % 2:
        chunks += b"\0"
    if loop:
        start, end = loop
        period_ns = int(round(1e9 / rate))
        smpl = struct.pack("<9I", 0, 0, period_ns, 60, 0, 0, 0, 1, 0)
        smpl += struct.pack("<6I", 0, 0, start, end, 0, 0)    # cue id, type 0 = forward, start, end, fraction, forever
        chunks += b"smpl" + struct.pack("<I", len(smpl)) + smpl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks)
    return clipped


def read_wav(path):
    """(samples as floats, rate, loop or None) from a mono 16-bit WAV written by write_wav (or similar)."""
    samples, rate, loop, channels = read_wav_channels(path)
    if channels != 1:
        raise ValueError(f"{path}: stereo; use read_wav_channels")
    return samples, rate, loop


def read_wav_channels(path):
    """(samples as floats, interleaved for stereo, rate, loop or None, channels) from a mono or stereo WAV in any
    format _fmt accepts. WavFormatError (a ValueError) for a sample format it does not read."""
    raw = Path(path).read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a WAV file")
    pos, fmt, data, loop = 12, None, None, None
    while pos + 8 <= len(raw):
        cid, size = raw[pos:pos + 4], struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = _fmt(path, body)
        elif cid == b"data":
            data = body
        elif cid == b"smpl" and len(body) >= 60 and struct.unpack("<I", body[28:32])[0] > 0:
            loop = struct.unpack("<II", body[44:52])
        pos += 8 + size + (size % 2)
    if fmt is None or data is None:
        raise ValueError(f"{path}: missing fmt or data chunk")
    channels, rate, bits, is_float = fmt
    samples = _decode(data, bits, is_float)
    frames = len(samples) // channels
    samples = samples[:frames * channels]            # a partial last frame goes the way of a partial sample
    if loop:
        # some writers store the frame count as the loop end (the spec says last frame): clamp, never index past
        start, end = loop[0], min(loop[1], frames - 1)
        loop = (start, end) if 0 <= start < end else None
    return samples, rate, loop, channels


def _fmt(path, body):
    """(channels, rate, bits, is_float) from a fmt chunk's body. ValueError for a broken chunk or more than two
    channels, WavFormatError for a sample format this module does not read."""
    if len(body) < 16:
        raise ValueError(f"{path}: the fmt chunk is cut short ({len(body)} of 16 bytes): a broken WAV")
    tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", body[:16])
    what = f"format tag {tag:#06x}"
    if tag == TAG_EXTENSIBLE:
        # ffmpeg writes this longer header for 24 and 32-bit PCM and for 16-bit above 48 kHz; wBitsPerSample is
        # the container size, which is what the data holds
        if len(body) < 40:
            raise ValueError(f"{path}: the extensible fmt chunk is cut short ({len(body)} of 40 bytes): a broken WAV")
        sub, tail = struct.unpack("<I", body[24:28])[0], body[28:40]
        tag = sub if tail == GUID_TAIL else None
        what = f"extensible sub-format {sub:#06x}" if tail == GUID_TAIL else "an extensible header with an unknown GUID"
    if channels not in (1, 2):
        raise ValueError(f"{path}: {channels} channels: only mono and stereo WAVs are read (mix it down first)")
    # 32-bit is what Godot's movie writer records (--write-movie): reading it as 16-bit turns speech
    # into what looks like white noise, a mistake made once while checking a game's audio
    if not (tag == TAG_PCM and bits in INT_BITS or tag == TAG_FLOAT and bits in FLOAT_BITS):
        raise WavFormatError(f"{path}: {bits}-bit, {what}: wavfile.py reads {READS}; with ffmpeg installed, "
                             f"`wavesmith.py formats convert` reads it and writes a 16-bit WAV")
    if rate < 1:
        raise ValueError(f"{path}: the WAV says its sample rate is {rate} Hz: a broken WAV")
    return channels, rate, bits, tag == TAG_FLOAT


def _decode(raw, bits, is_float):
    """Floats (integer PCM scaled to -1..1) from little-endian sample bytes; a partial last sample is dropped."""
    width = bits // 8
    n = len(raw) // width
    raw = raw[:n * width]
    if is_float:
        return list(struct.unpack(f"<{n}{'f' if width == 4 else 'd'}", raw))
    scale = INT_SCALE[width]
    if width == 1:                    # 8-bit WAV is unsigned: 128 is silence
        return [(v - 128) / scale for v in raw]
    if width == 3:                    # no struct code for 3 bytes: put each sample in the top of an int32
        wide = bytearray(n * 4)
        wide[1::4], wide[2::4], wide[3::4] = raw[0::3], raw[1::3], raw[2::3]
        return [v / scale for v in struct.unpack(f"<{n}i", wide)]
    return [v / scale for v in struct.unpack(f"<{n}{'i' if width == 4 else 'h'}", raw)]


def wav_stream(path, chunk_frames=48000):
    """(rate, channels, frames, chunks) for a WAV of any length in constant memory: chunks() yields one list of
    floats per channel for up to chunk_frames frames at a time. Same formats and errors as read_wav_channels."""
    path = Path(path)
    size = path.stat().st_size
    with path.open("rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise ValueError(f"{path}: not a WAV file")
        fmt, data = None, None
        while data is None or fmt is None:
            h = f.read(8)
            if len(h) < 8:
                break
            cid, n = h[:4], struct.unpack("<I", h[4:])[0]
            if cid == b"fmt ":
                fmt = _fmt(path, f.read(n))
                f.seek(n % 2, 1)
            elif cid == b"data":
                data = (f.tell(), min(n, size - f.tell()))     # a recorder that never fixed the size: up to the end
                f.seek(data[1] + data[1] % 2, 1)
            else:
                f.seek(n + n % 2, 1)
    if fmt is None or data is None:
        raise ValueError(f"{path}: missing fmt or data chunk")
    channels, rate, bits, is_float = fmt
    width = bits // 8
    frames = data[1] // (width * channels)

    def chunks():
        with path.open("rb") as f:
            f.seek(data[0])
            left = frames
            while left > 0:
                n = min(chunk_frames, left)
                raw = f.read(n * width * channels)
                n = len(raw) // (width * channels)
                if n == 0:
                    return
                vals = _decode(raw[:n * width * channels], bits, is_float)
                yield [vals] if channels == 1 else [vals[c::channels] for c in range(channels)]
                left -= n

    return rate, channels, frames, chunks


def fix_stream_sizes(raw):
    """(bytes, fixed) for WAV bytes a streaming service sent before it knew the length: the RIFF and data size
    fields are placeholders (0xFFFFFFxx) that run past the end. Walks the chunks, sets a data size that runs past
    the end to the bytes actually there and a RIFF size that does to the file length - 8; the samples are not
    touched. Anything that is not a RIFF WAVE, or whose sizes already fit, comes back unchanged (fixed False)."""
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return raw, False
    out = bytearray(raw)
    pos, fixed = 12, False
    while pos + 8 <= len(out):
        cid, size = out[pos:pos + 4], struct.unpack("<I", out[pos + 4:pos + 8])[0]
        if pos + 8 + size > len(out):
            if cid == b"data":            # only the data chunk can be cut short by streaming: the rest is samples
                struct.pack_into("<I", out, pos + 4, len(out) - pos - 8)
                fixed = True
            break
        pos += 8 + size + (size % 2)
    if struct.unpack("<I", out[4:8])[0] > len(out) - 8:
        struct.pack_into("<I", out, 4, len(out) - 8)
        fixed = True
    return bytes(out), fixed


def stats(samples, rate, loop=None):
    """Numbers to judge a sound without hearing it."""
    n = len(samples)
    peak = max((abs(s) for s in samples), default=0.0)
    rms = math.sqrt(sum(s * s for s in samples) / n) if n else 0.0
    out = {
        "seconds": round(n / rate, 3) if rate else 0.0,
        "peak_dbfs": round(20 * math.log10(peak), 1) if peak > 0 else -120.0,
        "rms_dbfs": round(20 * math.log10(rms), 1) if rms > 0 else -120.0,
    }
    if loop and n:
        # a click at the seam shows as a jump between the last and first looped samples, compared with
        # the typical step between neighbours
        start, end = loop
        steps = [abs(samples[i + 1] - samples[i]) for i in range(n - 1)]
        typical = sorted(steps)[int(len(steps) * 0.99)] if steps else 0.0
        seam = abs(samples[start] - samples[end])
        out["loop_seam_step"] = round(seam, 4)
        out["loop_seam_ok"] = seam <= max(typical, 0.02)
    return out


def crossfade_loop(samples, rate, seconds, channels=1):
    """Blend the last `seconds` into the start (equal power) and cut them off, so the end flows into the
    start: a seamless loop from any recording. Stereo samples are interleaved; the fade works per frame.
    Raises ValueError when the fade is too long for the clip."""
    frames = len(samples) // channels
    n = int(seconds * rate)
    if n <= 0 or n * 2 >= frames:
        raise ValueError(f"a {seconds} s crossfade is too long for a {frames / rate:.1f} s clip")
    keep = (frames - n) * channels
    body, tail = list(samples[:keep]), samples[keep:]
    for i in range(n):
        a = i / n
        fade_in, fade_out = math.sin(a * math.pi / 2), math.cos(a * math.pi / 2)
        for c in range(channels):
            j = i * channels + c
            body[j] = body[j] * fade_in + tail[j] * fade_out
    return body


def main(argv=None):
    """CLI: measure a WAV, normalize it to a target peak (generated audio often comes out too quiet), or make
    it loop seamlessly (generators such as Suno do not)."""
    import argparse
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Measure a WAV, or normalize it to a peak level (writes 16-bit).",
                                 epilog="Exit codes: 0 ok, 1 silent file, 2 usage or unreadable file.")
    sub = ap.add_subparsers(dest="command", required=True)
    st = sub.add_parser("stats", help="length, peak and loudness (dBFS)")
    st.add_argument("wav")
    nm = sub.add_parser("normalize", help="scale so the loudest sample sits at --peak dBFS (keeps loop points)")
    nm.add_argument("wav")
    nm.add_argument("--peak", type=float, default=-3.0, help="target peak in dBFS (default -3)")
    nm.add_argument("--out", help="write here instead of replacing the input")
    nm.add_argument("--overwrite", action="store_true", help="let --out replace a file that already exists")
    lp = sub.add_parser("loop", help="crossfade the end into the start and write loop points (Godot, Unity)")
    lp.add_argument("wav")
    lp.add_argument("--crossfade", type=float, default=2.0, help="seconds of overlap (default 2)")
    lp.add_argument("--start", type=float, default=0.0, help="cut this many seconds off the start first (an intro)")
    lp.add_argument("--end", type=float, help="cut everything after this second first (a fade-out or outro)")
    lp.add_argument("--out", help="write here instead of replacing the input")
    lp.add_argument("--overwrite", action="store_true", help="let --out replace a file that already exists")
    args = ap.parse_args(argv)
    try:
        if args.command != "stats":
            check_wav_name(getattr(args, "out", None) or args.wav)
            if args.out and Path(args.out).exists() and not args.overwrite:   # no --out: in place, as asked
                raise ValueError(f"{args.out} exists (use --overwrite, or leave out --out to change the input in place)")
        samples, rate, loop, channels = read_wav_channels(args.wav)
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    mono = [sum(samples[i:i + channels]) / channels for i in range(0, len(samples), channels)]
    before = stats(mono, rate)
    if args.command == "stats":
        print(f"{args.wav}: {before['seconds']} s, {channels} ch, {rate} Hz, peak {before['peak_dbfs']} dBFS, "
              f"loudness {before['rms_dbfs']} dBFS RMS" + (f", loop {loop}" if loop else ""))
        return 0
    if args.command == "loop":
        first = int(args.start * rate) * channels
        last = int(args.end * rate) * channels if args.end else len(samples)
        try:
            looped = crossfade_loop(samples[first:last], rate, args.crossfade, channels)
            frames = len(looped) // channels
            write_wav(args.out or args.wav, looped, rate, (0, frames - 1), channels)
        except ValueError as exc:                   # a fade too long, or a rate the header cannot hold
            print(f"[error] {exc}", file=sys.stderr)
            return 2
        print(f"[ OK ] {args.out or args.wav}: {frames / rate:.2f} s loop ({args.crossfade} s crossfade), loop points written")
        return 0
    peak = max((abs(s) for s in samples), default=0.0)
    if peak < 1e-6:
        print(f"[FAIL] {args.wav} is silent, nothing to normalize")
        return 1
    gain = 10 ** (args.peak / 20) / peak
    try:
        write_wav(args.out or args.wav, [s * gain for s in samples], rate, loop, channels)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    print(f"[ OK ] {args.out or args.wav}: gain {20 * math.log10(gain):+.1f} dB, peak now {args.peak} dBFS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

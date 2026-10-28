#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# wavfile.py
# Purpose : Shared helper for the audio tools: write 16-bit mono or stereo PCM WAV files (optionally with a
#           'smpl' loop chunk that Godot, Unity and most samplers read as loop points), read them
#           back, and measure them (peak, loudness, duration, clicks at a loop seam).
# Usage   : from wavfile import write_wav, read_wav, stats
#           write_wav("out.wav", samples, 44100, loop=(0, len(samples) - 1))
#           python tools/audio/wavfile.py stats assets/audio/x.wav
#           python tools/audio/wavfile.py normalize assets/audio/x.wav --peak -3    # too-quiet generated audio
#           python tools/audio/wavfile.py loop music.wav --crossfade 2 --end 95    # seamless loop from a download
# Notes   : Standard library only. Samples are floats in -1..1; anything outside is clipped and
#           counted, so a caller can warn. The smpl loop end is the last sample played (inclusive),
#           as the WAV spec says.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import math
import struct
from pathlib import Path


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


def write_wav(path, samples, rate, loop=None, channels=1):
    """Write a 16-bit WAV (stereo: samples interleaved L R L R). loop=(start, end) in frames adds a forward
    'smpl' loop (end inclusive). Returns the number of clipped samples."""
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
    """(samples as floats, interleaved for stereo, rate, loop or None, channels) from a 16-bit PCM WAV."""
    raw = Path(path).read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a WAV file")
    pos, rate, samples, loop, channels, bits = 12, None, None, None, 1, 16
    while pos + 8 <= len(raw):
        cid, size = raw[pos:pos + 4], struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", body[:16])
            # 32-bit is what Godot's movie writer records (--write-movie): reading it as 16-bit turns speech
            # into what looks like white noise, a mistake made once while checking a game's audio
            if tag != 1 or channels not in (1, 2) or bits not in (16, 32):
                raise ValueError(f"{path}: only mono or stereo 16-bit or 32-bit integer PCM is supported")
        elif cid == b"data":
            width = 4 if bits == 32 else 2
            n = len(body) // width
            scale = 2147483647.0 if width == 4 else 32767.0
            samples = [v / scale for v in struct.unpack(f"<{n}{'i' if width == 4 else 'h'}", body[:n * width])]
        elif cid == b"smpl" and len(body) >= 60 and struct.unpack("<I", body[28:32])[0] > 0:
            loop = struct.unpack("<II", body[44:52])
        pos += 8 + size + (size % 2)
    if rate is None or samples is None:
        raise ValueError(f"{path}: missing fmt or data chunk")
    frames = len(samples) // channels
    if loop:
        # some writers store the frame count as the loop end (the spec says last frame): clamp, never index past
        start, end = loop[0], min(loop[1], frames - 1)
        loop = (start, end) if 0 <= start < end else None
    return samples, rate, loop, channels


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
    ap = argparse.ArgumentParser(description="Measure a 16-bit WAV, or normalize it to a peak level.",
                                 epilog="Exit codes: 0 ok, 1 silent file, 2 usage or unreadable file.")
    sub = ap.add_subparsers(dest="command", required=True)
    st = sub.add_parser("stats", help="length, peak and loudness (dBFS)")
    st.add_argument("wav")
    nm = sub.add_parser("normalize", help="scale so the loudest sample sits at --peak dBFS (keeps loop points)")
    nm.add_argument("wav")
    nm.add_argument("--peak", type=float, default=-3.0, help="target peak in dBFS (default -3)")
    nm.add_argument("--out", help="write here instead of replacing the input")
    lp = sub.add_parser("loop", help="crossfade the end into the start and write loop points (Godot, Unity)")
    lp.add_argument("wav")
    lp.add_argument("--crossfade", type=float, default=2.0, help="seconds of overlap (default 2)")
    lp.add_argument("--start", type=float, default=0.0, help="cut this many seconds off the start first (an intro)")
    lp.add_argument("--end", type=float, help="cut everything after this second first (a fade-out or outro)")
    lp.add_argument("--out", help="write here instead of replacing the input")
    args = ap.parse_args(argv)
    try:
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
        except ValueError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 2
        frames = len(looped) // channels
        write_wav(args.out or args.wav, looped, rate, (0, frames - 1), channels)
        print(f"[ OK ] {args.out or args.wav}: {frames / rate:.2f} s loop ({args.crossfade} s crossfade), loop points written")
        return 0
    peak = max((abs(s) for s in samples), default=0.0)
    if peak < 1e-6:
        print(f"[FAIL] {args.wav} is silent, nothing to normalize")
        return 1
    gain = 10 ** (args.peak / 20) / peak
    write_wav(args.out or args.wav, [s * gain for s in samples], rate, loop, channels)
    print(f"[ OK ] {args.out or args.wav}: gain {20 * math.log10(gain):+.1f} dB, peak now {args.peak} dBFS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

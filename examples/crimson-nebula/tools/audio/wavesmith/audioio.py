#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# audioio.py
# Purpose : One way in and out for every audio file Wavesmith touches: WAV, FLAC and OGG Vorbis are read with the
#           standard library alone (wavfile.py, flacfile.py, oggvorbis.py); MP3, Opus, AAC and anything else are read
#           through ffmpeg when it is installed; OGG Vorbis (and any format ffmpeg writes) is written through ffmpeg.
#           With nothing installed every WAV / FLAC / OGG Vorbis path works, and the others say how to convert.
# Usage   : python tools/audio/wavesmith/wavesmith.py formats check              # what this machine can read and write
#           python tools/audio/wavesmith/wavesmith.py formats info assets/audio/music/theme.ogg
#           python tools/audio/wavesmith/wavesmith.py formats convert raw/door.mp3 --out assets/audio/sfx/door.wav
#           python tools/audio/wavesmith/wavesmith.py formats convert music/theme.wav --out music/theme.ogg --loop
# Needs   : Python 3.8+ only; ffmpeg (optional: https://ffmpeg.org, found on PATH or in WAVESMITH_FFMPEG) for MP3,
#           Opus and AAC input and for writing OGG
# Exit    : 0 ok, 1 a conversion failed, 2 usage, unreadable file or a format that needs ffmpeg when it is missing
# Notes   : Files are recognised by their first bytes, not their names (an Ogg also by its other BOS pages, so
#           Vorbis next to a Skeleton or Theora stream is read natively). ffmpeg runs as a separate program on local
#           files only (-protocol_whitelist file: a playlist-style input cannot make it open a URL), with -nostdin,
#           decoding to a temporary 16-bit WAV that wavfile.py reads, so no
#           output parsing depends on ffmpeg's version (16 bits is plenty for lossy sources). A WAV whose sample
#           format wavfile.py does not read (ADPCM, A-law, ...) goes through ffmpeg too. `convert --loop` keeps a WAV's 'smpl' loop as LOOPSTART /
#           LOOPLENGTH comments in the OGG, the convention RPG Maker reads (verify in RPG Maker MZ); Godot and Unity
#           set OGG loops in their import settings instead. stream_audio() hands any readable file out in chunks
#           of about a second (loudness measures long captures that way). ffmpeg is never shipped with the kit:
#           its builds are LGPL or GPL, a choice each game makes (docs/resources/audio.md).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   sniff the first bytes: RIFF/WAVE -> wavfile; fLaC -> flacfile; OggS + vorbis -> oggvorbis; anything else -> ffmpeg
#   an Ogg whose first BOS page is another codec (Skeleton, Theora): oggvorbis.identification scans the BOS pages
#     (they all come before any data page); a Vorbis one among them -> oggvorbis, none -> ffmpeg
#   ffmpeg read : ffmpeg -nostdin -v error -i <file> -c:a pcm_s16le <tmp.wav> -> wavfile -> channels
#   write       : .wav -> wavfile (16-bit, loop kept); other suffix -> tmp WAV -> ffmpeg (OGG: libvorbis, loop tags)
import argparse
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flacfile  # noqa: E402
from wavfile import WavFormatError, read_wav_channels, wav_stream, write_wav  # noqa: E402

FFMPEG_ENV = "WAVESMITH_FFMPEG"
CHUNK_FRAMES = 48000         # stream_audio: frames per channel handed out at a time (about 1 s)
NATIVE = ("WAV (8 / 16 / 24 / 32-bit PCM, 32 / 64-bit float)", "FLAC", "OGG Vorbis")
OGG_QUALITY = 6              # libvorbis -q:a: 6 is about 192 kbit/s stereo, transparent for game music
FFMPEG_TIMEOUT_S = 600
SNIFF_BYTES = 64             # enough for the first page header and the start of its packet
OGG_BOS_SCAN_BYTES = 1 << 20 # stream_audio / info: how far to look for a Vorbis BOS page behind other streams'
                             # (each BOS page holds one header packet; 1 MiB covers more streams than any file has)
DEBUG = False


class AudioIOError(Exception):
    """A file that cannot be read or written (exit 2): the message says what to do."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def find_ffmpeg():
    """The ffmpeg to use: WAVESMITH_FFMPEG if it names a file, else ffmpeg on PATH, else None."""
    env = os.environ.get(FFMPEG_ENV, "").strip()
    if env:
        return env if Path(env).is_file() else None
    return shutil.which("ffmpeg")


def oggvorbis_module():
    """The pure-Python Vorbis decoder (oggvorbis.py next to this file), or None when it is not there."""
    try:
        import oggvorbis
        return oggvorbis
    except ImportError:
        return None


def sniff(data):
    """'wav', 'flac', 'ogg-vorbis', 'ogg-opus', 'ogg' (another codec) or 'other', from the first bytes."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:4] == b"OggS":
        head = data[28:36]
        if head[:7] == b"\x01vorbis":
            return "ogg-vorbis"
        if head[:8] == b"OpusHead":
            return "ogg-opus"
        return "ogg"
    return "other"


def sniff_ogg(data, kind):
    """kind from sniff(), refined for an Ogg whose first BOS page is not Vorbis (a Skeleton or Theora header): the
    decoder's own BOS scan finds a Vorbis stream further on ('ogg-vorbis'), or there is none ('ogg', ffmpeg's)."""
    if kind != "ogg":
        return kind
    mod = oggvorbis_module()
    if mod is None:
        return kind
    try:
        mod.identification(data)
    except Exception as exc:          # not Vorbis, or the scan ran off the data: ffmpeg's file
        dbg(f"no Vorbis stream among the BOS pages: {exc}")
        return kind
    return "ogg-vorbis"


def sniff_file(path):
    """sniff() of a file from its first bytes, reading on through the BOS pages only for an Ogg that needs it."""
    with Path(path).open("rb") as f:
        head = f.read(SNIFF_BYTES)
        kind = sniff(head)
        if kind == "ogg":
            kind = sniff_ogg(head + f.read(OGG_BOS_SCAN_BYTES), kind)
    return kind


def _from_flac(data, path):
    try:
        info, chans, _ = flacfile.decode(data)
    except (flacfile.FlacError, flacfile.FlacCorrupt) as exc:
        raise AudioIOError(f"{path}: {exc}")
    scale = float(1 << (info["bits"] - 1))
    return [[s / scale for s in c] for c in chans], info["rate"]


def _from_wav(path, fallback=True):
    """Channels and rate of a WAV; a sample format wavfile.py does not read goes to ffmpeg when it is installed
    (fallback=False for ffmpeg's own output, so a bad decode cannot loop)."""
    try:
        samples, rate, _, channels = read_wav_channels(path)
    except WavFormatError as exc:
        if fallback and find_ffmpeg():
            dbg(f"{exc}; decoding with ffmpeg instead")
            return _via_ffmpeg(path, "a WAV")
        raise AudioIOError(str(exc))
    except ValueError as exc:
        raise AudioIOError(str(exc))
    return [samples[c::channels] for c in range(channels)], rate


def _from_vorbis(data, path, mod):
    try:
        info, chans, _ = mod.decode(data)
    except Exception as exc:          # the decoder's own error classes: report, never a traceback
        if type(exc).__name__ == "VorbisLimit" and find_ffmpeg():
            dbg(f"{path}: {exc}; decoding with ffmpeg instead")
            return _via_ffmpeg(path, "OGG Vorbis")
        raise AudioIOError(f"{path}: {exc}")
    for note in info.get("warnings", ()):
        print(f"[warn] {path}: {note}", file=sys.stderr)
    if "bits" in info:                # integer samples (a decoder that mirrors flacfile.py exactly)
        scale = float(1 << (info["bits"] - 1))
        chans = [[s / scale for s in c] for c in chans]
    return [list(c) for c in chans], info["rate"]


def _via_ffmpeg(path, kind):
    ff = find_ffmpeg()
    if not ff:
        raise AudioIOError(f"{path} is {kind}: reading it needs ffmpeg (https://ffmpeg.org; put it on PATH or set "
                           f"{FFMPEG_ENV}), or convert it to WAV, FLAC or OGG Vorbis first")
    with tempfile.TemporaryDirectory() as tmp:
        out = _ffmpeg_to_wav(ff, path, Path(tmp))
        try:
            return _from_wav(out, fallback=False)
        except AudioIOError as exc:
            raise AudioIOError(f"{path}: {exc} (decoded by ffmpeg; more than 2 channels are not supported)")


def _ffmpeg_to_wav(ff, path, tmp):
    """ffmpeg's decode of path as a 16-bit WAV in the folder tmp; returns its path."""
    out = tmp / "decoded.wav"
    # local files only: a playlist-style input (HLS, concat) cannot make ffmpeg open a URL; an absolute path
    # cannot be mistaken for an option (a file named -x.mp3)
    cmd = [ff, "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-i", str(Path(path).resolve()),
           "-c:a", "pcm_s16le", str(out)]
    dbg(" ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=FFMPEG_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioIOError(f"{path}: ffmpeg did not run: {exc}")
    if r.returncode != 0 or not out.is_file():
        raise AudioIOError(f"{path}: ffmpeg could not decode it: {(r.stderr or '').strip()[-300:]}")
    return out


def read_audio(path):
    """(list of channel sample lists in -1..1, rate) from WAV, FLAC or OGG Vorbis (standard library) or anything
    ffmpeg reads (when installed)."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise AudioIOError(f"cannot read {path}: {exc}")
    kind = sniff_ogg(data, sniff(data))
    dbg(f"{path}: {kind}")
    if kind == "wav":
        return _from_wav(path)
    if kind == "flac":
        return _from_flac(data, path)
    if kind == "ogg-vorbis":
        mod = oggvorbis_module()
        if mod is not None:
            return _from_vorbis(data, path, mod)
        return _via_ffmpeg(path, "OGG Vorbis")
    names = {"ogg-opus": "OGG Opus", "ogg": "an OGG file that is not Vorbis", "other": "not WAV, FLAC or OGG"}
    return _via_ffmpeg(path, names[kind])


class VorbisTooBig(AudioIOError):
    """The pure-Python Vorbis decoder hit its output limit part-way through a stream (ffmpeg may still read it)."""


def _batched(frames, nch):
    """Joins small decoder chunks into lists of about CHUNK_FRAMES frames per channel."""
    buf, n = [[] for _ in range(nch)], 0
    for part in frames:
        for b, p in zip(buf, part):
            b.extend(p)
        n += len(part[0]) if part else 0
        if n >= CHUNK_FRAMES:
            yield buf
            buf, n = [[] for _ in range(nch)], 0
    if n:
        yield buf


def stream_audio(path, via_ffmpeg=False):
    """(rate, channels, chunks) for anything read_audio reads, without holding the decoded file: chunks() yields
    one list of floats in -1..1 per channel, about CHUNK_FRAMES frames at a time. WAV is read in place, FLAC and
    OGG Vorbis are decoded as they go, other formats (or via_ffmpeg) through ffmpeg into a temporary WAV that is
    read the same way and deleted when chunks() ends. Errors inside chunks() are AudioIOError (VorbisTooBig when
    the Vorbis decoder's output limit stops it: retry with via_ffmpeg)."""
    path = Path(path)
    try:
        kind = sniff_file(path)
    except OSError as exc:
        raise AudioIOError(f"cannot read {path}: {exc}")
    mod = oggvorbis_module() if kind == "ogg-vorbis" else None
    if via_ffmpeg or kind not in ("wav", "flac") and mod is None:
        names = {"ogg-vorbis": "OGG Vorbis", "ogg-opus": "OGG Opus", "ogg": "an OGG file that is not Vorbis",
                 "other": "not WAV, FLAC or OGG"}
        return _stream_via_ffmpeg(path, names.get(kind, kind))
    if kind == "wav":
        try:
            rate, nch, _, chunks = wav_stream(path, CHUNK_FRAMES)
        except WavFormatError as exc:
            if find_ffmpeg():
                dbg(f"{exc}; decoding with ffmpeg instead")
                return _stream_via_ffmpeg(path, "a WAV")
            raise AudioIOError(str(exc))
        except (OSError, ValueError) as exc:
            raise AudioIOError(str(exc))

        def wav_chunks():
            try:
                yield from chunks()
            except (OSError, ValueError) as exc:
                raise AudioIOError(str(exc)) from None
        return rate, nch, wav_chunks
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise AudioIOError(f"cannot read {path}: {exc}")
    if kind == "flac":
        try:
            info, frames = flacfile.stream(data)
        except (flacfile.FlacError, flacfile.FlacCorrupt) as exc:
            raise AudioIOError(f"{path}: {exc}")
        scale = float(1 << (info["bits"] - 1))

        def flac_chunks():
            try:
                for part in _batched(frames(), info["channels"]):
                    yield [[s / scale for s in c] for c in part]
            except (flacfile.FlacError, flacfile.FlacCorrupt) as exc:
                raise AudioIOError(f"{path}: {exc}") from None
        return info["rate"], info["channels"], flac_chunks
    try:
        info, _, parts = mod.stream(data)
    except Exception as exc:          # the decoder's own error classes: report, never a traceback
        raise AudioIOError(f"{path}: {exc}")
    for note in info.get("warnings", ()):
        print(f"[warn] {path}: {note}", file=sys.stderr)

    def ogg_chunks():
        try:
            yield from _batched(parts(), info["channels"])
        except Exception as exc:
            if type(exc).__name__ == "VorbisLimit":
                raise VorbisTooBig(f"{path}: {exc}") from None
            raise AudioIOError(f"{path}: {exc}") from None
    return info["rate"], info["channels"], ogg_chunks


def _stream_via_ffmpeg(path, kind):
    ff = find_ffmpeg()
    if not ff:
        raise AudioIOError(f"{path} is {kind}: reading it needs ffmpeg (https://ffmpeg.org; put it on PATH or set "
                           f"{FFMPEG_ENV}), or convert it to WAV, FLAC or OGG Vorbis first")
    tmp = Path(tempfile.mkdtemp(prefix="wavesmith_"))
    # chunks() deletes the folder when it ends; a caller that never starts it (an error between the two calls)
    # would leave ffmpeg's WAV behind for good, so the process end is the backstop
    atexit.register(shutil.rmtree, str(tmp), ignore_errors=True)
    try:
        out = _ffmpeg_to_wav(ff, path, tmp)
        rate, nch, _, chunks = wav_stream(out, CHUNK_FRAMES)
    except (OSError, ValueError) as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise AudioIOError(f"{path}: {exc} (decoded by ffmpeg; more than 2 channels are not supported)")
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    def ffmpeg_chunks():
        try:
            yield from chunks()
        except (OSError, ValueError) as exc:
            raise AudioIOError(f"{path}: {exc}") from None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return rate, nch, ffmpeg_chunks


def _write_wav(path, interleaved, rate, loop=None, channels=1):
    """write_wav with its ValueError (a rate the header cannot hold, a wrong suffix) as an AudioIOError."""
    try:
        return write_wav(path, interleaved, rate, loop=loop, channels=channels)
    except ValueError as exc:
        raise AudioIOError(str(exc)) from None


def write_audio(path, channels, rate, loop=None, quality=OGG_QUALITY):
    """Writes channels (lists in -1..1) to path: .wav natively (16-bit, loop chunk kept), anything else through
    ffmpeg (OGG as libvorbis; the loop as LOOPSTART / LOOPLENGTH comments; the same samples give the same bytes).
    Returns the samples clipped."""
    path = Path(path)
    frames = len(channels[0]) if channels else 0
    interleaved = [s for frame in zip(*channels) for s in frame] if len(channels) > 1 else list(channels[0])
    if path.suffix.lower() == ".wav":
        return _write_wav(path, interleaved, rate, loop=loop, channels=len(channels))
    ff = find_ffmpeg()
    if not ff:
        raise AudioIOError(f"writing {path.suffix or 'that format'} needs ffmpeg (https://ffmpeg.org; PATH or "
                           f"{FFMPEG_ENV}); without it, write a .wav (every engine imports WAV)")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "source.wav"
        clipped = _write_wav(src, interleaved, rate, channels=len(channels))
        cmd = [ff, "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "file", "-i", str(src)]
        if path.suffix.lower() == ".ogg":
            cmd += ["-c:a", "libvorbis", "-q:a", str(quality)]
            if loop:
                start, end = loop
                cmd += ["-metadata", f"LOOPSTART={start}", "-metadata", f"LOOPLENGTH={end - start + 1}"]
        # bitexact: a fixed OGG stream serial (else random) and no ffmpeg version tag, so the same audio written
        # twice is the same bytes (the DAW round trip tells "already in the game" by its SHA-256)
        cmd += ["-fflags", "+bitexact", "-flags:a", "+bitexact"]
        # ffmpeg writes next to its input in the temp folder (the suffix still picks the format); the destination
        # changes only once the run has succeeded, so a run that dies part-way leaves no broken file there and
        # never replaces a good one
        staged = Path(tmp) / ("encoded" + path.suffix)
        cmd.append(str(staged))
        dbg(" ".join(cmd))
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=FFMPEG_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AudioIOError(f"{path}: ffmpeg did not run: {exc}")
        if r.returncode != 0 or not staged.is_file():
            raise AudioIOError(f"{path}: ffmpeg could not write it: {(r.stderr or '').strip()[-300:]}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(str(staged), str(path))
            except OSError:                         # another drive: the temp folder is seldom the game's
                shutil.copyfile(str(staged), str(path))
        except OSError as exc:
            raise AudioIOError(f"{path}: cannot write it: {exc}")
    dbg(f"{path}: {frames} frames written")
    return clipped


# ---- Commands ------------------------------------------------------------------------------------------------------
def cmd_check(args):
    ff = find_ffmpeg()
    vorbis = oggvorbis_module() is not None
    print(f"[ OK ] read without installing anything: WAV, FLAC" + (", OGG Vorbis" if vorbis else ""))
    print(f"[ OK ] write without installing anything: WAV")
    if ff:
        print(f"[ OK ] ffmpeg found ({ff}): also reads MP3, Opus, AAC and more; writes OGG Vorbis")
    else:
        print(f"[note] no ffmpeg (PATH or {FFMPEG_ENV}): MP3 / Opus / AAC input and OGG output need it; "
              "everything else works")
    return 0


def cmd_info(args):
    path = Path(args.file)
    try:
        kind = sniff_file(path)
    except OSError as exc:
        raise AudioIOError(f"cannot read {path}: {exc}")
    chans, rate = read_audio(path)
    frames = len(chans[0]) if chans else 0
    how = {"wav": "wavfile.py", "flac": "flacfile.py"}.get(kind) or (
        "oggvorbis.py" if kind == "ogg-vorbis" and oggvorbis_module() else "ffmpeg")
    if kind == "wav":
        try:
            wav_stream(path)              # reads the header only: did read_audio need ffmpeg for this one?
        except WavFormatError:
            how = "ffmpeg"
        except (OSError, ValueError):
            pass
    peak = max((abs(s) for c in chans for s in c), default=0.0)
    print(f"[ OK ] {path.as_posix()}: {kind}, {rate} Hz, {len(chans)} channel(s), {frames / rate if rate else 0:.3f} s, "
          f"peak {peak:.3f} (read by {how})")
    return 0


def cmd_convert(args):
    out = Path(args.out)
    if out.exists() and not args.overwrite:
        raise AudioIOError(f"{out} exists (use --overwrite)")
    src = Path(args.file)
    chans, rate = read_audio(src)
    loop = None
    if args.loop:
        try:
            loop = read_wav_channels(src)[2] if sniff(src.read_bytes()[:16]) == "wav" else None
        except ValueError:
            loop = None
        if loop is None:
            print("[note] --loop: the source has no WAV loop point to keep")
    out.parent.mkdir(parents=True, exist_ok=True)
    clipped = write_audio(out, chans, rate, loop=loop, quality=args.quality)
    # Lossy sources (OGG, MP3) can decode a little above full scale even when the original never clipped
    print(f"{'[warn]' if clipped else '[ OK ]'} {out.as_posix()}: {len(chans[0]) / rate:.3f} s, {rate} Hz, "
          f"{len(chans)} channel(s)"
          + (f", loop {loop[0]}..{loop[1]} kept as LOOPSTART / LOOPLENGTH" if loop and out.suffix.lower() == ".ogg" else "")
          + (f", {clipped} samples clipped (the source peaks above full scale: lower it first, e.g. "
             f"`loudness normalize`)" if clipped else ""))
    return 1 if clipped else 0


def build_parser():
    ap = argparse.ArgumentParser(description="Read and write game audio formats: WAV, FLAC and OGG Vorbis with the "
                                             "standard library; MP3, Opus and OGG output through ffmpeg if installed.",
                                 epilog="Exit codes: 0 ok, 1 conversion clipped or failed, 2 usage or a format that "
                                        "needs ffmpeg when it is missing.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="show ffmpeg command lines and tracebacks")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check", parents=[common], help="what this machine can read and write")
    i = sub.add_parser("info", parents=[common], help="format, rate, channels, length, peak")
    i.add_argument("file")
    c = sub.add_parser("convert", parents=[common], help="any readable file to .wav (native) or .ogg / others (ffmpeg)")
    c.add_argument("file")
    c.add_argument("--out", required=True, help="output path; the suffix picks the format")
    c.add_argument("--quality", type=int, default=OGG_QUALITY, help=f"OGG Vorbis quality 0..10 (default {OGG_QUALITY})")
    c.add_argument("--loop", action="store_true", help="keep a WAV loop point (OGG: LOOPSTART / LOOPLENGTH comments)")
    c.add_argument("--overwrite", action="store_true")
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
    if not args.cmd:
        ap.print_help()
        return 2
    DEBUG = args.debug
    try:
        return {"check": cmd_check, "info": cmd_info, "convert": cmd_convert}[args.cmd](args)
    except AudioIOError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

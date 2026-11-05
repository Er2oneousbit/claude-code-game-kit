#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# midifile.py
# Purpose : A small Standard MIDI File writer (format 1) for the DAW round trip (daw.py): a conductor track with the
#           tempo, the time signature and named markers, so a DAW's bar grid lines up with a music piece, plus one note
#           track per channel of a chiptune song (chiptune.py's text patterns turned into notes). Also reads back what
#           it wrote (the exams check the bytes both ways).
# Usage   : python tools/audio/wavesmith/midifile.py song assets/audio/src/theme.song.json --out build/theme.mid
#           python tools/audio/wavesmith/midifile.py grid --bpm 96 --bars 8 --out build/grid.mid      # tempo + bars only
#           python tools/audio/wavesmith/midifile.py dump build/theme.mid                             # what is in it
# Needs   : Python 3.8+ only (chiptune.py, same folder, for songs)
# Exit    : 0 ok, 2 usage, a song error or an unreadable file
# Notes   : 480 ticks per quarter note. A chiptune step is 1 / steps_per_beat of a beat and a beat is a quarter note,
#           so a step is round(480 / steps_per_beat) ticks (exact for 1, 2, 3, 4, 5, 6, 8, 10, 12, 15 and 16). Melodic
#           channels get MIDI channels 1, 2, 3 ... (10 is skipped); the drums channel plays on MIDI channel 10 with the
#           General MIDI drum notes (k kick 36, s snare 38, h closed hat 42, o open hat 46, c crash 49), one step long.
#           Velocity follows each channel's volume (the loudest channel is 112). Notes outside MIDI's 0..127 are left
#           out and counted. The sounds themselves (waves, envelopes) are not in MIDI: the file carries the notes, so
#           you can re-orchestrate them in a DAW.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   conductor: tempo (FF 51, microseconds per quarter), time signature (FF 58), markers (FF 06) at ticks
#   song:      chiptune.load_song -> per channel events_for (start step, steps, token) -> note on / note off at ticks
#   track:     events sorted by tick (note offs before note ons at the same tick) -> delta times (variable-length
#              quantities) -> MTrk chunk ending in FF 2F 00
#   file:      MThd (format 1, track count, 480) + every MTrk
import argparse
import struct
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PPQ = 480                   # ticks per quarter note
DRUM_CHANNEL = 9            # MIDI channel 10, counted from 0
GM_DRUMS = {"k": 36, "s": 38, "h": 42, "o": 46, "c": 49}
TOP_VELOCITY = 112
SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
DEBUG = False


class MidiError(Exception):
    """Exit 2: a song or file problem."""


def vlq(n):
    """A MIDI variable-length quantity (7 bits a byte, the high bit set on all but the last)."""
    if n < 0:
        raise MidiError(f"negative delta time {n}")
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def meta(kind, data):
    return bytes([0xFF, kind]) + vlq(len(data)) + data


def track_chunk(events):
    """MTrk bytes from [(tick, order, event bytes)]: sorted by tick, then order (note offs 0 before note ons 1)."""
    body, now = b"", 0
    for tick, _, ev in sorted(events, key=lambda e: (e[0], e[1])):
        body += vlq(tick - now) + ev
        now = tick
    body += vlq(0) + meta(0x2F, b"")
    return b"MTrk" + struct.pack(">I", len(body)) + body


def smf_bytes(tracks):
    """A format 1 file from a list of event lists (the first is the conductor track)."""
    return b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), PPQ) + b"".join(track_chunk(t) for t in tracks)


def conductor(bpm, beats_per_bar=4, name="", markers=()):
    """Tempo, time signature, an optional track name and [(tick, text)] markers."""
    if not 1 <= bpm <= 1000:
        raise MidiError(f"bpm must be 1..1000, not {bpm}")
    if not 1 <= beats_per_bar <= 255:
        raise MidiError(f"beats per bar must be 1..255, not {beats_per_bar}")
    ev = []
    if name:
        ev.append((0, 0, meta(0x03, name.encode("utf-8"))))
    ev.append((0, 0, meta(0x51, int(round(60_000_000 / bpm)).to_bytes(3, "big"))))
    ev.append((0, 0, meta(0x58, bytes([beats_per_bar, 2, 24, 8]))))      # n / 4, 24 clocks a click, 8 32nds a beat
    for tick, text in markers:
        ev.append((int(tick), 0, meta(0x06, text.encode("utf-8"))))
    return ev


def bar_ticks(bars, beats_per_bar=4):
    return bars * beats_per_bar * PPQ


def note_number(token, octave_shift=0):
    """MIDI note number of a chiptune note token (C4 = 60), or None."""
    import chiptune
    m = chiptune.NOTE.match(token)
    if not m:
        return None
    letter, acc, octave = m.group(1).upper(), m.group(2), int(m.group(3)) + octave_shift
    return 12 * (octave + 1) + SEMITONE[letter] + (1 if acc == "#" else -1 if acc == "b" else 0)


def song_tracks(song, name=""):
    """(tracks, info) for a loaded chiptune song: the conductor first, then one track per channel that has notes."""
    import chiptune
    spb = song.get("steps_per_beat", 4)
    tick = lambda step: int(round(step * PPQ / spb))                      # noqa: E731
    channels = song["_channels"]
    loudest = max([c["volume"] for c in channels.values()] + [1e-9])
    tracks, skipped, midi_ch, notes, total = [conductor(song["bpm"], 4, name)], 0, 0, 0, 0
    for cname, ch in channels.items():
        events, total = chiptune.events_for(song, cname)
        if not events:
            continue
        drums = ch["wave"] == "drums"
        if drums:
            chan = DRUM_CHANNEL
        else:
            chan, midi_ch = midi_ch, midi_ch + 1 + (midi_ch + 1 == DRUM_CHANNEL)
            if chan > 15:
                raise MidiError("more than 15 melodic channels: MIDI has 16 channels, one of them for drums")
        vel = max(1, min(127, int(round(TOP_VELOCITY * ch["volume"] / loudest))))
        ev = [(0, 0, meta(0x03, cname.encode("utf-8")))]
        for start, length, token in events:
            num = GM_DRUMS.get(token) if drums else note_number(token, ch["octave"])
            if num is None or not 0 <= num <= 127:
                skipped += 1
                continue
            on, off = tick(start), tick(start + (1 if drums else length))
            ev.append((on, 1, bytes([0x90 | chan, num, vel])))
            ev.append((off, 0, bytes([0x80 | chan, num, 0])))
            notes += 1
        tracks.append(ev)
        dbg(f"channel {cname}: MIDI channel {chan + 1}, {len(events)} events")
    return tracks, {"notes": notes, "skipped": skipped, "steps": total}


def write_song(song_path, out, name=""):
    """Writes the song's notes to out. Returns the info dict."""
    import chiptune
    try:
        song = chiptune.load_song(song_path)
    except chiptune.SongError as exc:
        raise MidiError(str(exc))
    tracks, info = song_tracks(song, name or Path(song_path).name.split(".")[0])
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(smf_bytes(tracks))
    return info


# ---- reading back (the exams, and `dump`) ------------------------------------------------------------------------
def read_smf(data):
    """{"ppq", "tracks": [[(tick, kind, values)]]}: kind "note" (channel, note, velocity, end tick), "tempo"
    (bpm), "timesig" (beats, denominator), "marker" / "name" (text). Raises MidiError on a malformed file."""
    if data[:4] != b"MThd":
        raise MidiError("not a MIDI file (no MThd)")
    _, fmt, ntracks, ppq = struct.unpack(">IHHH", data[4:14])
    pos, tracks = 14, []
    for _ in range(ntracks):
        if data[pos:pos + 4] != b"MTrk":
            raise MidiError(f"expected MTrk at byte {pos}")
        size = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        body, pos = data[pos + 8:pos + 8 + size], pos + 8 + size
        i, now, running, out, open_notes = 0, 0, 0, [], {}

        def read_vlq():
            nonlocal i
            n = 0
            while True:
                b = body[i]
                i += 1
                n = (n << 7) | (b & 0x7F)
                if not b & 0x80:
                    return n
        while i < len(body):
            now += read_vlq()
            status = body[i]
            if status & 0x80:
                i += 1
                running = status
            else:
                status = running
            if status == 0xFF:
                kind = body[i]
                i += 1
                n = read_vlq()
                d, i = body[i:i + n], i + n
                if kind == 0x51:
                    out.append((now, "tempo", round(60_000_000 / int.from_bytes(d, "big"), 3)))
                elif kind == 0x58:
                    out.append((now, "timesig", (d[0], 2 ** d[1])))
                elif kind in (0x03, 0x06):
                    out.append((now, "name" if kind == 0x03 else "marker", d.decode("utf-8", "replace")))
            elif status >> 4 in (0x8, 0x9):
                note, vel = body[i], body[i + 1]
                i += 2
                ch = status & 0x0F
                if status >> 4 == 0x9 and vel:
                    open_notes[(ch, note)] = (now, vel)
                elif (ch, note) in open_notes:
                    start, v = open_notes.pop((ch, note))
                    out.append((start, "note", (ch, note, v, now)))
            else:
                raise MidiError(f"unexpected status byte {status:#04x}")
        tracks.append(sorted(out, key=lambda e: (e[0], e[1])))
    return {"format": fmt, "ppq": ppq, "tracks": tracks}


def build_parser():
    ap = argparse.ArgumentParser(description="Write Standard MIDI Files for a DAW: a chiptune song's notes, or a "
                                             "tempo and bar grid.",
                                 epilog="Exit codes: 0 ok, 2 usage, a song error or an unreadable file.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="per-channel detail and tracebacks")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("song", parents=[common], help="a chiptune song file's notes, one track per channel")
    s.add_argument("song")
    s.add_argument("--out", required=True)
    g = sub.add_parser("grid", parents=[common], help="tempo, time signature and a marker on every bar")
    g.add_argument("--bpm", type=float, required=True)
    g.add_argument("--bars", type=int, required=True)
    g.add_argument("--beats-per-bar", type=int, default=4)
    g.add_argument("--out", required=True)
    d = sub.add_parser("dump", parents=[common], help="print what a MIDI file holds")
    d.add_argument("file")
    return ap


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


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
        if args.cmd == "song":
            info = write_song(args.song, args.out)
            print(f"[ OK ] {Path(args.out).as_posix()}: {info['notes']} note(s)"
                  + (f", {info['skipped']} outside MIDI's range left out" if info["skipped"] else ""))
        elif args.cmd == "grid":
            if args.bars < 1:
                raise MidiError("bars must be 1 or more")
            marks = [(bar_ticks(b, args.beats_per_bar), f"bar {b + 1}") for b in range(args.bars)]
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_bytes(smf_bytes([conductor(args.bpm, args.beats_per_bar, "grid", marks)]))
            print(f"[ OK ] {Path(args.out).as_posix()}: {args.bars} bars at {args.bpm:g} BPM")
        else:
            info = read_smf(Path(args.file).read_bytes())
            print(f"format {info['format']}, {len(info['tracks'])} track(s), {info['ppq']} ticks a quarter")
            for k, t in enumerate(info["tracks"]):
                notes = [e for e in t if e[1] == "note"]
                other = [f"{kind} {val}" for _, kind, val in t if kind != "note"]
                print(f"  track {k + 1}: {len(notes)} note(s); " + "; ".join(other[:6]))
        return 0
    except MidiError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, IndexError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

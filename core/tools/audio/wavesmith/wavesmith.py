#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# wavesmith.py
# Purpose : Wavesmith, the kit's audio tool: one front door for every audio job in a game. Measure and check
#           loudness, describe sound events and music as data, make and check whole sound sets, build dialogue
#           subtitles and captions, voice lines on your own GPU, make sound effects from code or from a local model,
#           and run the exams. Each subcommand is a module in this folder that also runs on its own.
# Usage   : python tools/audio/wavesmith/wavesmith.py list                       # every subcommand, one line each
#           python tools/audio/wavesmith/wavesmith.py check                      # what is ready on this machine
#           python tools/audio/wavesmith/wavesmith.py test                       # every exam (standard library only)
#           python tools/audio/wavesmith/wavesmith.py loudness measure "assets/audio/**/*.wav"
#           python tools/audio/wavesmith/wavesmith.py dialogue lint data/dialogue.json --root assets/audio --pseudo
#           python tools/audio/wavesmith/wavesmith.py <subcommand> --help        # that tool's own options
# Notes   : Python 3.8+ and the standard library for everything except the GPU tools (voice: Qwen3-TTS in its own
#           environment; sfx and sets with Stable Audio: a local ComfyUI). README.md in this folder walks through
#           every subcommand; docs/resources/audio.md has the background and the evidence. Exit codes are the
#           subcommand's own: 0 ok, 1 the task failed (or a check found problems), 2 environment or usage.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   argv[0] names a subcommand -> import its module from this folder -> module.main(rest of argv) -> its exit code
#   list:  the table below
#   check: Python version; the GPU tools' own check commands (voice, sfx), each reported, none required
#   test:  every test_*.py in this folder in its own process (same Python) -> one line each -> exit 1 if any failed
import importlib
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# subcommand -> (module in this folder, what it is for). Order is the order `list` prints.
SUBCOMMANDS = {
    "loudness": ("loudness", "LUFS, loudness range and true peak (BS.1770); check a whole-game mix against ASWG-R001; "
                             "normalize to house levels; mono downmix check"),
    "events":   ("audio_events", "sound events as data: takes, pitch and volume ranges, voice caps, cooldowns, "
                                 "ducking; validate, audit, golden vectors"),
    "sets":     ("sound_sets", "families of sounds made and checked together: footsteps per surface, ambience beds, "
                               "the code-made UI set"),
    "dialogue": ("dialogue", "dialogue.json and voice files to the built file the engines read, SRT / WebVTT, "
                             "subtitle lint (--pseudo: will translations fit?)"),
    "music":    ("music", "adaptive music: bar grid, bar-aligned loops, stems, stingers, transition plans, tempo"),
    "access":   ("access", "accessibility rules every engine follows: slider gains per bus, caption arrows"),
    "babble":   ("babble", "gibberish voices (blips) with exact typewriter timing"),
    "voice":    ("local_tts", "spoken lines on your GPU (Qwen3-TTS): design a voice once, say lines in 10 languages"),
    "sfx":      ("local_sfx", "sound effects and ambience loops on your GPU (Stable Audio 3 in a local ComfyUI)"),
    "synth":    ("sfx_synth", "retro sound effects from code: presets, seeds, recipes (ship-safe)"),
    "chiptune": ("chiptune", "chiptune songs written as text patterns, with loop points"),
    "eleven":   ("eleven_audio", "ElevenLabs (paid, your API key): sound effects and music"),
    "fish":     ("fish_tts", "Fish Audio text to speech (paid, your API key)"),
    "wav":      ("wavfile", "WAV helpers: stats, normalize to a peak, seamless loops"),
}
GPU_CHECKS = (("voice", ["check"]), ("sfx", ["check"]))
TEST_TIMEOUT_S = 900


def usage():
    print("Wavesmith: the kit's audio tool. python tools/audio/wavesmith/wavesmith.py <subcommand> [options]\n")
    print("  list      this table          check     what is ready here          test      run every exam\n")
    for name, (_, what) in SUBCOMMANDS.items():
        print(f"  {name:9} {what}")
    print("\n<subcommand> --help shows that tool's options. Exit codes: 0 ok, 1 task failed, 2 environment or usage.")


def run_sub(name, argv):
    module = importlib.import_module(SUBCOMMANDS[name][0])
    rc = module.main(argv)
    return rc if isinstance(rc, int) else 0


def cmd_check():
    ok = sys.version_info >= (3, 8)
    print(f"[{' OK ' if ok else 'FAIL'}] Python {sys.version.split()[0]} (Wavesmith needs 3.8 or newer)")
    print("[ OK ] standard-library tools ready: " + ", ".join(n for n in SUBCOMMANDS if n not in ("voice", "sfx")))
    for name, args in GPU_CHECKS:
        print(f"[....] {name}: running `{name} {' '.join(args)}` (optional: only for that tool)")
        try:
            rc = run_sub(name, args)
        except SystemExit as exc:                       # argparse exits for its own reasons
            rc = exc.code if isinstance(exc.code, int) else 2
        if rc:
            print(f"[note] {name} is not ready here (exit {rc}); everything else works without it")
    return 0 if ok else 2


def cmd_test(names):
    tests = sorted(HERE.glob("test_*.py"))
    if names:
        tests = [t for t in tests if t.stem[5:] in names or t.stem in names]
        if not tests:
            print(f"[error] no exam named {', '.join(names)} (have: {', '.join(t.stem[5:] for t in sorted(HERE.glob('test_*.py')))})",
                  file=sys.stderr)
            return 2
    failed = []
    for t in tests:
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, "-B", str(t)], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=TEST_TIMEOUT_S, cwd=str(HERE),
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            tail = [ln for ln in (r.stdout + r.stderr).strip().splitlines() if ln.startswith(("Ran ", "OK", "FAILED"))]
            good = r.returncode == 0
        except subprocess.TimeoutExpired:
            tail, good = [f"timed out after {TEST_TIMEOUT_S} s"], False
        print(f"[{' OK ' if good else 'FAIL'}] {t.name:28} {' '.join(tail)}  ({time.time() - t0:.1f} s)")
        if not good:
            failed.append(t.name)
    print(f"[{'FAIL' if failed else ' OK '}] {len(tests) - len(failed)} of {len(tests)} exam(s) passed"
          + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help", "list"):
        usage()
        return 0 if argv else 2
    sub, rest = argv[0], argv[1:]
    if sub == "check":
        return cmd_check()
    if sub == "test":
        return cmd_test(rest)
    if sub not in SUBCOMMANDS:
        print(f"[error] unknown subcommand {sub!r}; `list` shows them all", file=sys.stderr)
        return 2
    return run_sub(sub, rest)


if __name__ == "__main__":
    sys.exit(main())

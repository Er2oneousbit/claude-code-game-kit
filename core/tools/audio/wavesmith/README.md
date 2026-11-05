# Wavesmith: the kit's audio tool

Wavesmith does every audio job a game needs from one front door, `tools/audio/wavesmith/wavesmith.py`:
- measure loudness and check the whole mix
- describe sound events and adaptive music as data, which every engine plays the same way
- make and check whole sets of sounds
- build subtitles and captions for dialogue
- voice lines on your own GPU
- make sound effects from code or from a local model
- edit sounds by hand in a DAW and bring them back levelled and logged (REAPER, or any DAW through stems)

It is Dotwork's audio sibling (`tools/art/dotwork/`). Claude (or you) orchestrates; the tools do the measuring and
the making.

Everything except the two GPU tools (`voice`, `sfx`) is Python 3.8+ and the standard library: nothing to install.
Each subcommand is a module in this folder that also runs on its own (`python tools/audio/wavesmith/loudness.py ...`).
The background, the sources and the measured proofs are in `docs/resources/audio.md`.

Tested on Windows 11, an RTX 5060 Ti 16 GB, ComfyUI 0.43.0, Godot 4.7.2, LÖVE 11.5 and headless Chromium. Those
numbers describe that setup and are not promises. The standard-library tools also pass every exam on Linux (Ubuntu
26.04, Python 3.14); macOS is first exercised by `.github/workflows/audio.yml`.

## Contents
1. [First run](#first-run-no-gpu)
2. [Subcommands](#subcommands)
3. [Data files a game writes](#data-files-a-game-writes)
4. [The engines' side](#the-engines-side)
5. [Editing in a DAW](#editing-in-a-daw)
6. [GPU tools: setup](#gpu-tools-setup)
7. [Licences](#licences)
8. [Exams](#exams)

## First run (no GPU)
```
python tools/audio/wavesmith/wavesmith.py list                       # every subcommand
python tools/audio/wavesmith/wavesmith.py check                      # what is ready on this machine
python tools/audio/wavesmith/wavesmith.py sets ui --out assets/audio/ui      # 12 UI sounds made from code
python tools/audio/wavesmith/wavesmith.py loudness measure "assets/audio/ui/*.wav"
python tools/audio/wavesmith/wavesmith.py test                       # every exam, about 3 minutes
```
The UI sounds are ship-safe. Each `.sfx.json` says so: no model and no samples were used, so there is no licence
question.

## Subcommands
| Subcommand | Module | What it does | Typical call |
|---|---|---|---|
| `loudness` | loudness.py | LUFS, LRA and true peak (ITU-R BS.1770-5, EBU Tech 3342); check a whole-game capture against ASWG-R001; normalize to house levels; mono downmix check | `loudness check-mix capture.wav --target home` |
| `events` | audio_events.py | Sound events as data: takes, pitch and volume ranges, no-repeat picks, voice caps, cooldowns, buses, ducking. Validate, audit, golden vectors | `events audit data/audio_events.json --root assets/audio` |
| `sets` | sound_sets.py | Families of sounds made and checked together: footsteps per surface, ambience beds, the code-made UI set. Writes their events | `sets check data/sound_sets.json --ship` |
| `dialogue` | dialogue.py | dialogue.json and voice files become the built file the engines read: per-character typewriter timing, subtitle cues, SFX captions. Also SRT / WebVTT export and lint (`--pseudo`: will translations fit?) | `dialogue lint data/dialogue.json --root assets/audio --pseudo` |
| `access` | access.py | The accessibility rules every engine follows: slider gains per bus (never twice down one branch) and caption arrows. Golden vectors | `access gains data/audio_events.json --sfx 0.5` |
| `music` | music.py | Adaptive music: bar grid in samples, bar-aligned loops, stems, stingers, a transition map, plans, tempo estimates | `music loop raw.wav --bpm 96 --bars 8 --out music/explore.wav` |
| `babble` | babble.py | Gibberish voices (blips) with exact typewriter timing | `babble "Fresh bread!" --voice baker --out vo/baker_1.wav` |
| `voice` | local_tts.py | Spoken lines on your GPU (Qwen3-TTS): design a voice from a description once, then say lines in it. 10 languages | `voice say --ref smith_ref.wav --lines smith.txt --language German --out vo/smith_de.wav` |
| `sfx` | local_sfx.py | Sound effects and ambience loops on your GPU (Stable Audio 3 in a local ComfyUI). Takes are ranked; you pick by ear | `sfx make "heavy wooden door creaking" --seconds 2.5 --out build/audition/door.wav` |
| `synth` | sfx_synth.py | Retro sound effects from code: presets, seeds, recipes (ship-safe) | `synth coin --variants 5 --out build/audition/coin.wav` |
| `chiptune` | chiptune.py | Chiptune songs written as text patterns, with loop points | `chiptune theme.song.json --out music/theme.wav` |
| `eleven` | eleven_audio.py | ElevenLabs: sound effects and music. Paid, your API key | `eleven sfx --text "..." --out x.wav` |
| `fish` | fish_tts.py | Fish Audio text to speech. Paid, your API key | `fish say --voice <id> --text "..." --out x.wav` |
| `wav` | wavfile.py | WAV helpers: stats, normalize to a peak, seamless loops | `wav loop raw.wav --crossfade 2 --out loop.wav` |
| `daw` | daw.py | The DAW round trip: a REAPER project per set, music track or folder, rendered back headless; WAV stems, MIDI and markers for any other DAW, imported back by name. Unchanged sounds keep their bytes, edited ones are levelled to their bus and logged (Modified? yes) | `daw reaper footsteps`, then `daw reaper --reexport assets_src/daw/footsteps` |
| `midi` | midifile.py | Standard MIDI files: a chiptune song's notes (one track per channel, drums on channel 10), or a tempo and bar grid | `midi song theme.song.json --out build/theme.mid` |
| `formats` | audioio.py | Read WAV (8 to 32-bit PCM, float, extensible headers), FLAC and OGG Vorbis with nothing installed (flacfile.py, oggvorbis.py), MP3 / Opus / AAC through ffmpeg if installed; convert to WAV, or to OGG with ffmpeg (loop points kept) | `formats convert theme.ogg --out theme.wav` |

`wavesmith.py <subcommand> --help` lists that tool's options. Exit codes are the subcommand's own:
- 0: ok
- 1: the task failed, or a check found problems
- 2: environment or usage

## Data files a game writes
The game creates these files itself. Each one is checked by its subcommand, and its format is in that module's header
and in `docs/resources/audio.md`.
- data/audio_events.json: buses, ducking and every sound event (`events validate`, `events audit`)
- data/music.json: tracks, stems, stingers and transitions (`music validate --root assets/audio`)
- data/dialogue.json: speakers, lines and sequences (`dialogue build ... --out data/dialogue/en.built.json`)
- data/sound_sets.json: sets to make and check (`sets make`, `sets check`, `sets events --merge`)

## The engines' side
The engines' runtimes follow the golden files in `data/golden/`. Each is written by its reference module
(`events vectors --write`, `music vectors --write`, `access vectors --write`) and checked in CI (`--check`), so every
engine makes the same decisions from the same data. Each engine has the audio director, the music director and the
access rules, with their golden tests:
- web: src/core/audioDirector.ts, audioAccess.ts, musicDirector.ts and dialogue.ts, with
  src/shell/audioPlayer.ts, musicPlayer.ts and subtitles.ts.
- web-3d: the same core files.
- Godot: scripts/core/audio_director.gd, music_director.gd and audio_access.gd, with scripts/shell/music_player.gd and
  the subtitle bar's arrows.
- Unity: Assets/Scripts/Core/AudioDirector.cs, MusicDirector.cs and AudioAccess.cs, with
  Assets/Scripts/Game/AudioEventPlayer.cs (run in Play mode by Assets/Tests/PlayMode/AudioPlayModeTests.cs) and
  MusicPlayer.cs (compiled, not yet run in Play mode).
- LÖVE: src/core/audio_director.lua, music_director.lua and audio_access.lua, with src/shell/music_player.lua and
  the subtitles' arrows.
- Bevy: src/logic/audio_director.rs, music_director.rs and audio_access.rs (logic only).
- C++/SDL2: src/core/AudioDirector.hpp, MusicDirector.hpp and AudioAccess.hpp (logic only).
- Unreal: the GameKitShell plugin's GameKitAudioDirector.h, GameKitMusicDirector.h and GameKitAudioAccess.h (logic
  only; the plugin ships disabled, engines/unreal FLOW.md says how to turn it on).

- RPG Maker MZ: game/js/plugins/GameAudio.js, an engine-free plugin with all three, tested with Node against the
  golden files (the overlay itself is a proof of concept: everything that touches MZ says verify in RPG Maker MZ).

## Editing in a DAW
```
python tools/audio/wavesmith/wavesmith.py daw reaper footsteps                     # a set: one region per sound
python tools/audio/wavesmith/wavesmith.py daw reaper --reexport assets_src/daw/footsteps   # after editing in REAPER
python tools/audio/wavesmith/wavesmith.py daw export explore build/daw_explore     # any other DAW: stems, MIDI, markers
python tools/audio/wavesmith/wavesmith.py daw import build/daw_explore --daw "FL Studio"   # renders/<name>.wav back
```
- REAPER is found from `--reaper`, `REAPER_BIN` or its default install folder. The re-export runs it headless
  (`-renderproject`) with a throwaway `-cfgfile` folder in the temp folder, so your own REAPER settings are never
  touched. Tested with REAPER 7.84 on Windows 11 (about 15 s a render); macOS and Linux are untested (verify).
- The working folder (`assets_src/daw/<name>`) holds the project, copies of the sounds and `<name>/wavesmith_daw.json`,
  all with relative paths: it can be committed. The .gitignore leaves out REAPER's backups, peak files and render/.
  Run `--reexport` and `import` from the game root (or pass `--root`).
- A sound whose audio did not change keeps its file byte for byte. A changed one is levelled to its bus (music: the
  stems together, by their mix) and logged. A file changed in the game meanwhile, a renamed region and an unknown
  render are refused and named.
- The details, and what FL Studio and Ableton can and cannot do: `docs/resources/audio.md`, "Editing by hand in a
  DAW".

## GPU tools: setup
- `voice` runs Qwen3-TTS in its own Python environment, so Wavesmith stays standard-library only. Setup steps are in
  `docs/resources/audio.md` (Voice).
  - Set `HF_HOME` to wherever the weights live, in the shell that runs it. Otherwise the first run quietly starts a
    multi-GB download into the default cache, and it looks like a hang.
  - `voice check` names whatever is missing and says where the model will run: `--device auto` uses an NVIDIA GPU,
    else Apple's Metal, else the CPU (about 20x realtime; fine for a handful of lines).
- `sfx`, and `sets make` with local_sfx sets, need a running ComfyUI (0.43.0 or newer) with Stable Audio 3.
  `sfx check` names the missing files. ComfyUI itself runs on NVIDIA, AMD, Intel and Apple hardware (its README);
  only NVIDIA was measured here.
- Everything else needs no GPU and runs with Python 3.8+ on Windows and Linux (tested) and should on macOS (untested) (docs/resources/audio.md,
  "Hardware").
- Never clone a real person's voice without their written permission. Designed voices are the documented path.

## Licences
`LICENSES.md` lists every model Wavesmith can load, with its licence and what that means for shipping. In short:
- Code-made sounds (`synth`, `chiptune`, `babble`, and the `sets ui` set) are yours.
- Qwen3-TTS is Apache-2.0.
- Stable Audio output is under the Stability AI Community License. `sets check --ship` refuses it until you clear that
  licence.

## Exams
`wavesmith.py test` runs every `test_*.py` in this folder in its own process, one line each, and exits 1 if any
failed. `test_daw.py` uses a stand-in REAPER; with `REAPER_BIN` set it also runs the real one (`ReaperLiveExam`,
about 3.5 minutes; skipped without it). `wavesmith.py test music dialogue` runs just those exams. Each exam also runs
on its own: `python tools/audio/wavesmith/test_music.py`.

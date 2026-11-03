# Audio: music and SFX sources and tools

Libraries, generators, editors, and implementation hints. Prompts for AI audio tools live in `docs/BRIEFS.md`.

> **Read this caveat.** Written from general knowledge plus video notes, not live-checked. Sites change terms, go offline, or rename
> licenses. The license that matters is the one on the **specific asset page on the day you download it**. Save the license text in
> `docs/licenses/` and log the asset in `docs/ASSET_LOG.md` via `/asset-intake`. Anything marked **(verify)** is the most likely to have changed.

## Music
**Libraries (existing tracks)**
- `incompetech.com` (Kevin MacLeod). Huge catalog, CC BY. Attribution required, easy to comply with.
- `opengameart.org` music section. Mixed licenses per file, filter for CC0 or CC BY.
- `freemusicarchive.org`. Per-track license, filter by commercial use.
- `pixabay.com/music`. Pixabay content license, read terms for games and redistribution. **(verify)**
- `itch.io/game-assets/tag-music`. Many packs, license varies per pack, many CC0.
- `kenney.nl` audio packs. CC0, mostly short loops and jingles.
- `freesound.org` for loops and ambience beds, per-file license (filter CC0).

**Make your own**
- This kit: `python tools/audio/wavesmith/wavesmith.py chiptune <song>.json --out <music>.wav` renders a song written as text patterns
  (two pulse channels, triangle bass, noise drums) and writes loop points into the WAV, so Godot and Unity loop it
  with default import settings. The song format is in the script's header; `--solo <channel>` renders one part.
  Claude can write the song file; log the result as AI-assisted (`pre-generated`) in `docs/ASSET_LOG.md`.
- Generated locally (K02, 2026-11-01, two rounds: 6 game-music prompts at 80 to 150 BPM, 3 seeds each, scored by
  whether the take kept the tempo asked for):

  | Model | Licence | Tempo within 2 % | Time per 24 s (16 GB GPU) |
  |---|---|---|---|
  | ACE-Step 1.5 turbo | MIT (ACE-Step's card: generated music may be used commercially; Comfy-Org's repackaging says Apache-2.0) | 17 of 18 | 12 s |
  | Stable Audio Open 1.0 | Stability AI Community License | 15 of 18 | 5 s |
  | Stable Audio 3 medium | Stability AI Community License | 11 of 18 | 2 s |

  ACE-Step 1.5 is the one to use: it takes the tempo, meter and key as inputs, and its output may ship. It runs in
  ComfyUI 0.43 or newer with Comfy-Org's ACE-Step-1.5 files (the all-in-one turbo checkpoint is 9.6 GB), through
  ComfyUI's own "Text to Audio (ACE-Step 1.5)" template. Wavesmith has no subcommand for it yet. On every take run
  `wavesmith.py music tempo <take>.wav` (it can read half or double the tempo), then `music loop` at the tempo you asked for, then
  `loudness normalize` (takes peak above 0 dBTP), and listen. Stable Audio output stays out of what ships unless you
  have cleared its licence.
- Generated: `python tools/audio/wavesmith/wavesmith.py eleven music --prompt "..." --instrumental --out <music>.wav --loop-crossfade 2 --log`
  (ElevenLabs, your API key, a paid plan for music). Suno has no official API (third-party "Suno API" sites resell
  their own credits and do not carry your plan's rights): use its web app, then
  `python tools/audio/wavesmith/wavesmith.py wav loop <download>.wav --crossfade 2 --end <s> --out <music>.wav` for a seamless loop.
- `LMMS` (free DAW), `BeepBox` (browser chiptune), `Bosca Ceoil` (simple tracker), `Furnace` (chip tracker),
  `FamiTracker`, `SunVox`, `Reaper` (cheap, full DAW), `Cakewalk`/`Ardour` (free DAWs).
- Sample sources: `freesound.org`, Sonniss bundles (see SFX).

**Commission**
- Bandcamp or itch.io composers, game-dev Discords, r/gamemusic. Get the license in writing: buyout vs
  license, platforms, soundtrack release rights.

**Implementation**
- Godot: `AudioStreamPlayer` plus buses. Unreal: MetaSounds. C++/SDL2: `SDL_mixer` or `miniaudio` or `OpenAL Soft`.
  Bevy: built-in `AudioPlayer` (OGG, WAV); more control from an audio crate such as bevy_kira_audio **(verify its Bevy version)**.
- Adaptive music middleware: `FMOD Studio`, `Wwise`. Both have indie-friendly tiers. **(verify current terms)**

**AI music tools** (Suno, Udio and similar): license terms and Steam disclosure are the risk. **(verify)**
Suno: paid plans grant commercial use for tracks made while subscribed, free-plan tracks are non-commercial (E34, **verify**).
Prompt patterns: `docs/BRIEFS.md` > Music with Suno. Log prompts and outputs in `ASSET_LOG.md` if used.

## Adaptive music: bars, loops, stems, transitions
Describe the music once in data/music.json (you create it); `tools/audio/wavesmith/music.py` checks it and its files, and every engine's
music director plans the same transitions; the web, Godot and LÖVE players (and Unity's, not yet run in Play mode) change
track on the sample the plan names.
```json
{
  "version": 1, "sample_rate": 44100, "start": "explore",
  "tracks": {
    "explore": {"bpm": 96, "beats_per_bar": 4, "bars": 9, "loop_start_bar": 1,
                "stems": {"pads": "music/explore_pads.wav", "drums": "music/explore_drums.wav"}},
    "combat": {"bpm": 96, "beats_per_bar": 4, "bars": 4, "stems": {"full": "music/combat.wav"}}
  },
  "stingers": {"alarm": {"file": "music/alarm.wav", "bars": 1}},
  "transitions": [
    {"from": "explore", "to": "combat", "quantize": "beat", "fade_ms": 120, "sync": true},
    {"from": "combat", "to": "explore", "quantize": "bar", "fade_ms": 500, "stinger": "alarm"}
  ],
  "default_transition": {"quantize": "bar", "fade_ms": 250}
}
```
- Everything is counted in samples: beat k starts at floor(k * 60 * rate / bpm + 0.5). A track plays its intro
  (bars before `loop_start_bar`) once, then loops to its last bar. Stems of a track start together and stay locked:
  turn layers up and down with the player's stem gain (drums in when the action starts).
- `quantize`: `immediate`, `beat`, `bar`, `phrase` (`phrase_bars`, default 4) or `loop_end`. `fade_ms` fades the old
  track out from the switch point. `sync` enters the new track at the same place in its bar (same BPM and meter). A
  `stinger` plays at the switch point and the new track enters after the stinger's `bars`. Rules match the exact
  pair first, then `"from": "*"`, then `"to": "*"`, then `default_transition`. The engines' directors read the file
  as it is and do not validate it: run `validate` after every edit. An unknown quantize or stinger name is an error
  in every engine (`"stinger": ""` means none); a `sync` that is not `true` or `false`, or a `phrase_bars` that is not
  a whole number, is caught only by `validate`.
- `python tools/audio/wavesmith/wavesmith.py music loop raw/explore.wav --bpm 96 --bars 9 --out assets/audio/music/explore_pads.wav` cuts
  a render or recording to whole bars, adds what rings past the loop end back onto the start (no click, the tail is
  kept) and writes the loop point on the grid (a 'smpl' chunk Godot and Unity read). `validate data/music.json --root
  assets/audio` checks rates, stem lengths and shapes, loop points on the grid, stingers and the map. `plan --from
  explore --to combat --at 3.2` shows when a change would happen; `tempo` estimates a file's BPM (half or double is
  possible) to see whether a generated piece kept the tempo it was asked for; `grid` prints bar times.
- Engines: src/core/musicDirector.ts and src/shell/musicPlayer.ts (web; route it through the audio player's music
  bus with `player.bus("music")` so the slider and dialogue ducking apply). They follow data/golden/music.json,
  written by `music.py vectors --write` (the reference); the web player's Chromium check renders transitions offline
  and finds every switch, stinger, loop wrap and bar marker on its planned sample (44.1 kHz at 96 BPM included,
  where beats fall on half samples). The same planner in every engine, tested against data/golden/music.json:
  scripts/core/music_director.gd (Godot), Assets/Scripts/Core/MusicDirector.cs (Unity), src/core/music_director.lua
  (LÖVE), src/logic/music_director.rs (Bevy), src/core/MusicDirector.hpp (C++),
  Plugins/GameKitShell/.../GameKitMusicDirector.h (Unreal), game/js/plugins/GameAudio.js (RPG Maker MZ, tested in
  Node; verify in RPG Maker MZ). Players:
  - Godot, scripts/shell/music_player.gd: stems fed through AudioStreamGenerators on one shared timeline. Measured
    with Movie Maker at 44.1 kHz: 0 frames off over 661,500 frames, with loop wraps, a synced switch, a fade and a
    stinger; on the real audio driver, switches on the planned frame.
  - LÖVE, src/shell/music_player.lua: a QueueableSource mixer, sample-exact in its own mix (tested sample by sample
    in Lua); what you hear trails the queue by about 93 ms.
  - Unity, Assets/Scripts/Game/MusicPlayer.cs: AudioSource.PlayScheduled on the DSP clock. Compiled against Unity
    6000.6 and in the editor, not yet run in Play mode: verify it by ear.
  - Bevy, C++ and Unreal have the planner only: their games mix audio their own way (Unreal: a Quartz clock can
    start sounds on the planned sample).
- Godot plays a WAV's loop from the sample after loop_begin to loop_end, so the 'smpl' points `music.py loop` writes
  make a plain AudioStreamPlayer loop one sample short each pass (it drifts by a sample a loop); the kit's
  music_player.gd measures and corrects this. Import music WAVs as PCM, not the default QOA compression.

## Voice
- Pre-generated lines: `python tools/audio/wavesmith/wavesmith.py fish say --voice <id> --text "..." --out <voice>.mp3` (Fish Audio,
  your key in `FISH_API_KEY`; `check` shows the developer API balance, which is billed apart from a subscription;
  `voices --licensed --search <words>` finds a voice ID). ElevenLabs and others work too (`docs/BRIEFS.md`, Voice).
- Lines written while the game runs (an LLM NPC) cannot be pre-recorded: see the live voice in
  `examples/gatekeeper-godot` and the key rules in `SOP-15`.
- Never pick a library voice that imitates a real person or a famous character, even if it is marked licensed.
- Babble instead of words (the gibberish blips many 2D games play while a speech bubble types out): this kit's
  `python tools/audio/wavesmith/wavesmith.py babble "Halt! Who goes there?" --voice knight --out assets/audio/voice/halt.wav` makes it
  from code, so there is no account, cost or license question. Voices: baker, knight, smith, sprite, golem
  (`--list`; tune with `--set f0=... --set metal=...`); `--variants 3` writes takes to compare, `--lines <file>`
  voices a whole script. Each WAV gets `<name>.timeline.json` with the time each character should appear: drive
  the typewriter reveal from it so text and voice stay in step. Questions rise at the end, exclamations get louder.
  `--bank-dir <folder>` swaps the synth for recorded syllables (`ba.wav`, `ko.wav`, ...) if you want a real voice's
  colour.

**Local voices, on your own GPU** (`tools/audio/wavesmith/local_tts.py`, Qwen3-TTS; no account, nothing per line)
- Design a character's voice once from a description, then voice every line in it:
  `python tools/audio/wavesmith/wavesmith.py voice design "gruff older blacksmith, deep gravelly voice, slow speech" --out
  assets_src/voice/smith_ref.wav`, then `python tools/audio/wavesmith/wavesmith.py voice say --ref assets_src/voice/smith_ref.wav
  --lines docs/dialog/smith.txt --out assets/audio/voice/smith.wav` (`smith_1.wav`, `smith_2.wav` ...). Listen to
  the reference first; a different `--seed` or a clearer description gives another voice. Spoken barks work as
  plain words ("Hyah!", "Ha ha ha!"). For voices deeper or stranger than a person: `--pitch -5` (a giant, also
  slower) or `+5` (a small creature), `--ring-hz 40` (metal, golems, robots).
- **Never clone a real person's voice without their written permission.** Designed voices are the documented
  path. A recording works only with `--ref-text "<its exact words>" --ref-origin self` (your own voice) or
  `--ref-origin permission` (the speaker agreed in writing); every `.gen.json` and `--log` row records where the
  voice came from.
- Without an NVIDIA GPU: `--device auto` (the default) falls back to Apple's Metal, then the CPU (measured: about
  20x realtime on an 8-core desktop CPU; see Hardware below). `--device cuda` insists on the GPU.
- Speed: about 3x slower than realtime on a 16 GB RTX 5060 Ti (a 3 s line takes about 10 s, plus about 30 s to load
  the model per run, so voice a whole `--lines` script in one run). Pre-made lines only, not live speech.
- **Other languages.** `--language` takes one of the ten the model cards list: Chinese, English, Japanese,
  Korean, German, French, Russian, Portuguese, Spanish, Italian (anything else stops before the model loads). The
  same designed voice speaks them all: clone the reference once, voice each language's script with
  `say --ref <the same ref> --lines <lines>.<lang>.txt --language German --out ...`.
- Measured 2026-11-01: one designed English voice, the same four lines in five languages, each line transcribed by
  Whisper large-v3-turbo with its language forced, and compared with WavLM to the voice's reference:

  | Language | Error | Same voice as reference | Notes |
  |---|---|---|---|
  | English | WER 0.0 % | 0.978 (min 0.975) | |
  | German | WER 5.6 % | 0.972 (min 0.963) | one word misheard ("drei" as "dry") |
  | Spanish | WER 5.0 % | 0.961 (min 0.931) | one word ("Tráeme") |
  | French | WER 32.4 % | 0.963 (min 0.949) | mostly word splitting ("demain" heard as "de main"), some accent |
  | Japanese | CER 74.5 % | 0.940 (min 0.908) | the rate is inflated (Whisper writes kana where the script has kanji) but one word was mispronounced, and 3 of 4 seeds ran away on one line |

  A different designed voice scores 0.38 against the same reference, so the character stays recognizable in every
  language. Treat German, Spanish and French takes as usable after a listen; get a native listener before shipping
  Japanese (or Chinese and Korean, not measured).
- **Translations and bark lines from a local language model are drafts.** A local model (tested: Qwen3-14B,
  Apache-2.0, through llama.cpp's llama-server, MIT; none of its drafting code ships in the kit) can draft other languages and
  more variety for barks. In the kit's test, 112 of 136 translation drafts passed the checks below. The model also
  invented placeholders: on one-word strings such as language names it wrote whole sentences with `{name}` and
  `{n}` in them. So every draft needs:
  - **Placeholder survival:** the exact set of `{name}`, `%d` and similar tokens as the source; a draft that adds or
    drops one is rejected, not fixed by hand.
  - **A back-translation check:** translate the draft back and compare it with the source; low similarity is a flag
    to look at (short UI labels paraphrase a lot), not an automatic fail.
  - **A human review** before anything ships: tone, register, plural forms and gender agreement are not checked by
    any of the above. Japanese and other languages far from English need a native reader.
  Bark variants need the same placeholder check, plus a check that they really differ from the original and from
  each other: asked loosely, the model repeated the source line or added `{name}` everywhere.
- **Takes that never end.** Now and then the model misses its end and keeps talking (seen in Japanese). Every line is
  capped at about twice a natural reading (3 s plus 0.15 s a character, 0.30 for Chinese, Japanese and Korean); a
  take that reaches the cap is not written, the run says which line, and exits 1: voice it again with another
  `--seed`.
- Set `HF_HOME` in the shell that runs `say` to wherever the weights are: a shell without it looks in the default
  cache and starts a multi-gigabyte download that looks like a hang.
- Setup (one time). The model runs in its own Python environment so the kit's tools stay standard-library only:
  ```
  uv venv tts-env --python 3.12
  uv pip install --python tts-env qwen-tts torch torchaudio --torch-backend cu130   # your CUDA: cu128, cu126 ...
  setx LOCAL_TTS_PYTHON "<full path>\tts-env\Scripts\python.exe"                     # macOS/Linux: export ... /bin/python
  # open a new terminal here: setx does not change the one it ran in
  python tools/audio/wavesmith/wavesmith.py voice check        # names what is missing: the env, torch, qwen-tts, or CUDA
  ```
  Weights download on first use into the Hugging Face cache (`HF_HOME`, default `~/.cache/huggingface`):
  Qwen3-TTS-12Hz-1.7B-VoiceDesign (design) and Qwen3-TTS-12Hz-1.7B-Base (say), about 4.3 GB each;
  `--model 0.6b` uses `Qwen3-TTS-12Hz-0.6B-Base` (2.4 GB). All Apache-2.0 per their model cards
  (https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base, checked 2026-10-31). Outputs: 24 kHz mono WAV, -3 dBFS peak.
- Setup gotchas seen on an RTX 50-series (Blackwell) PC, 2026-10-31:
  - Install torch with `--torch-backend cu130` (or your CUDA). `--extra-index-url` with
    `--index-strategy unsafe-best-match` silently picks PyPI's newer CPU-only torch; `check` then reports no CUDA.
  - Scoring speech with Whisper: on a CUDA 13 torch, faster-whisper (CTranslate2) fails with `cublas64_12.dll`
    missing; the transformers Whisper pipeline works on the same torch.
  - qwen-tts prints a banner to stdout when imported; local_tts's worker moves it to stderr (no action needed).
- Voice bake-off K01 (2026-10-31): 5 designed personas x 22 lines (10 speech-bubble lines with name and number
  traps, 12 barks), scored with Whisper large-v3-turbo word error rate and WavLM speaker similarity to the
  persona's reference (different personas score 0.26-0.78 against each other; two deep male voices scored 0.93,
  hence `--pitch` / `--ring-hz` for a golem):

  | Variant | Word error rate | Same voice as reference | Speed (x realtime) | Verdict |
  |---|---|---|---|---|
  | Qwen3-TTS 1.7B, design then clone | 0.013 | 0.957 | 3.4 | default: clearest, steadiest voice, Apache-2.0 |
  | Chatterbox Turbo (clone) | 0.018 | 0.949 | 0.8 | not used: flattest delivery, watermarked |
  | Chatterbox (clone) | 0.020 | 0.951 | 1.5 | not used: watermarked, reads [laugh]-style tags as words |
  | Qwen3-TTS VoiceDesign per line | 0.018 | 0.856 | 3.2 | not used: the voice drifts line to line |

  Chatterbox (MIT) was tested but is not wired in: every output carries an inaudible Perth watermark, and its
  watermarker needs `setuptools<81` (it imports `pkg_resources`; without it every line fails with
  `'NoneType' object is not callable`). How much emotion each variant can carry is still being judged by ear.

## SFX
**Libraries**
- `kenney.nl` audio. CC0. Interface sounds, impacts, sci-fi, RPG. Great default.
- `freesound.org`. Per-file license. Filter by CC0. Always check, it mixes CC0, BY, and NC.
- `opengameart.org` SFX. Mixed.
- `sonniss.com` GDC Game Audio Bundles. Large royalty-free packs released around GDC each year. **(verify current terms)**
- `pixabay.com/sound-effects`, `mixkit.co`, `zapsplat.com`. Each has its own license, Zapsplat free tier
  has attribution rules. **(verify)**
- Warning: BBC Sound Effects archive license is non-commercial. Fine for learning, not for a Steam release. **(verify)**

**Generators (retro SFX in seconds)**
- This kit: `python tools/audio/wavesmith/wavesmith.py synth jump --variants 5 --out build/audition/jump.wav` writes five takes to
  compare (presets: jump, coin, land, fall, hit, pickup, blip, laser, explosion). Each WAV gets a JSON recipe;
  `--from <recipe>` re-renders it exactly and `--set key=value` tweaks one number.
- Generated: `python tools/audio/wavesmith/wavesmith.py eleven sfx --text "old iron gate creaking open" --seconds 2 --out <sfx>.wav --mono --log`
  (about 10 credits per second; free-plan output is non-commercial and is logged as PLACEHOLDER).
  Generated audio can come back very quiet: `python tools/audio/wavesmith/wavesmith.py wav stats|normalize <file>`.
- Local, on your own GPU (no account, no per-sound cost): `python tools/audio/wavesmith/wavesmith.py sfx make "heavy wooden door
  creaking open" --seconds 2.5 --out build/audition/door.wav` renders 6 takes with Stable Audio 3 through a local
  ComfyUI, trims and normalizes them, and keeps the best 3 (`door_1.wav` is the top-ranked) with a `.gen.json` each.
  `--loop` makes ambience beds loop seamlessly, `--mono` suits positional one-shots, `--model small-sfx` gives a
  second opinion. `local_sfx.py check` says what is missing. Setup: ComfyUI 0.43.0 or newer, plus
  stable_audio_3_medium.safetensors (ComfyUI's checkpoints folder) and t5gemma_b_b_ul2.safetensors (its text_encoders folder) from
  `huggingface.co/Comfy-Org/stable-audio-3`. About 2 s per take on a 16 GB RTX 5060 Ti once the model is loaded.
  - **You pick by ear.** The ranking is technical only (clipping, silence, length, loop seam): it cannot hear
    whether a take matches the prompt. A meaning-based score did not fix that either: in the K01 bake-off the
    CLAP text-audio model ranked correct retro jumps and coin arpeggios low. Listen to the kept takes and choose.
  - **License (verify, read it yourself before shipping):** Stable Audio 3 is under the Stability AI Community
    License (Last Updated July 5, 2024): free while you and your affiliates make under USD 1M a year in total
    revenue, from any source; commercial use requires registering at `stability.ai/community-license`; you own
    the outputs as far as the law allows, and the outputs may not be used to train or improve another
    foundational generative model. The text encoder (T5Gemma) is under Google's Gemma Terms of Use. Each WAV's
    `.gen.json` and `--log` row record the model and license.
  - Bake-off K01 (2026-10-31, 29 prompts covering clean UI, retro, realistic foley, stylized and ambience,
    3 seeds each, scored with CLAP text-audio similarity plus mel spectrograms):

    | Model | CLAP | Own prompt ranked #1 of 29 | Seconds per take | Verdict |
    |---|---|---|---|---|
    | Stable Audio 3 medium | 0.283 | 75% | 1.6 | default: best on every style, clean lengths |
    | Stable Audio 3 small-sfx | 0.229 | 59% | 1.5 | second opinion: wins some creature and foley prompts, weak on retro |
    | Stable Audio 3 small-sfx base (50 steps) | 0.186 | 40% | 5.0 | not used |
    | Stable Audio Open 1.0 | 0.175 | 34% | 4.5 | not used: smears short sounds to 1-1.5 s, clips most |

    Not one of them nails "count" prompts ("four footsteps"); render takes and pick. For precise retro
    blips the sfx_synth presets above are still the better tool.
- `sfxr` / `jsfxr` (browser), `Bfxr`, `ChipTone`, `LabChirp`. Output is yours to use.

**Edit and process**
- `Audacity` (free), `Reaper`, `Ocenaudio`. Normalize, trim silence, add tiny fades to avoid clicks.
- Formats: every Wavesmith tool that reads audio (loudness, events audit, dialogue, music, sets) reads WAV (mono or
  stereo, 8 / 16 / 24 / 32-bit PCM or 32 / 64-bit float, plain or extensible header), FLAC and OGG Vorbis with nothing
  installed, and MP3, Opus, AAC or anything else ffmpeg reads when ffmpeg is installed (on PATH, or
  `WAVESMITH_FFMPEG` naming it), including a WAV in another sample format such as ADPCM. Files are recognised by
  their bytes, not their names.
  - `wavesmith.py formats check`: what this machine can read and write.
  - `wavesmith.py formats info <file>`: format, rate, channels, length, peak, and which decoder read it.
  - `wavesmith.py formats convert <file> --out <file>.wav`: anything readable to WAV, with nothing installed.
    `--out <file>.ogg` writes OGG Vorbis through ffmpeg (`--quality 0..10`; `--loop` keeps a WAV loop point as the
    LOOPSTART / LOOPLENGTH comments RPG Maker reads, verify in RPG Maker MZ). A lossy source can decode slightly above
    full scale: convert then warns, counts the clipped samples and exits 1.
  - The OGG Vorbis decoder (`oggvorbis.py`) is plain Python: measured within 5e-7 of ffmpeg's decoder on every
    sample of 47 libvorbis files (q-1 to q10, 11.025 to 48 kHz, mono to 5.1), with exact sample counts. It takes
    about 0.13 to 0.2 s per second of 44.1 kHz stereo (CPython 3.12), fine for checking and converting, not for
    playback. It refuses floor type 0 (no real encoder writes it), chained streams, and Opus or FLAC inside Ogg,
    by name, and a file that asks for far more than real Vorbis ever does (codebook sizes, or more samples per byte
    than any real file decodes to: the limits are in its header); with ffmpeg installed, such a file goes to ffmpeg
    instead. Where ffmpeg 9.0.2 and the file's own sample count disagree (streams that fit on one Ogg page), the
    decoder follows the file.
  - ffmpeg is never shipped or installed by the kit; Wavesmith only runs it as a separate program. Its licence is
    in `tools/audio/wavesmith/LICENSES.md`.
- FLAC to WAV with nothing installed: `python tools/audio/wavesmith/flacfile.py towav <file>.flac --out <file>.wav` (16/24-bit,
  mono/stereo; checks the file's MD5). Tags do not carry over, which matters for ComfyUI's FLACs: they hold the
  full prompt and workflow, local paths included (`tools/art/comfy_local.py strip` cleans a FLAC in place).
  `oggvorbis.py towav` does the same for OGG Vorbis.
- Layer 2 to 3 sounds per important event (impact plus tail plus pitch variation). Randomize pitch ±5 percent
  and rotate 3 to 5 variants for anything that repeats.

**DIY foley**
- Phone or cheap recorder, quiet room, record then edit. Zero license questions.

**Implementation hints**
- Keep SFX short, mono for positional, 44.1 kHz or 48 kHz, WAV in source control, OGG for shipping if size matters.
- Bus structure: Master > Music, SFX, UI, Voice. Expose volume sliders from day one.

## Sound events: variants, voices, ducking
Describe every game sound once in data/audio_events.json (you create it), and each engine's audio director
decides how it plays: which take (never the same one twice in a row), its pitch and volume within a range, how
many copies may sound at once, a minimum gap between plays, and how far dialogue ducks the music.
```json
{
  "version": 1, "seed": 1,
  "buses": {"master": {}, "music": {"parent": "master", "volume_db": -4}, "sfx": {"parent": "master"},
            "ui": {"parent": "master"}, "dialogue": {"parent": "master"}, "ambience": {"parent": "master"}},
  "ducking": [{"trigger": "dialogue", "targets": ["music", "ambience"], "depth_db": -8,
               "attack_ms": 80, "release_ms": 400}],
  "events": {
    "step_stone": {"bus": "sfx", "files": ["sfx/step_stone_1.wav", "sfx/step_stone_2.wav", "sfx/step_stone_3.wav"],
                   "pick": "random_no_repeat", "pitch_semitones": [-1, 1], "volume_db": [-3, 0],
                   "max_voices": 4, "cooldown_ms": 60, "caption": "[footsteps]"},
    "ui_click": {"bus": "ui", "files": ["ui/click.wav"], "max_voices": 2}
  }
}
```
- `pick`: `random_no_repeat` (default), `shuffle` (every take once per round, no repeat across rounds),
  `sequence`, or `random`. `steal`: `oldest` (default: the oldest copy stops) or `none` (the new play is refused).
  `max_voices` defaults to 8, `pitch_semitones` and `volume_db` to no change. Event ids are lowercase ASCII.
  `seed` is a whole number from 0 to 2^53 - 1 (9007199254740991): engines that read JSON numbers as doubles hold
  nothing larger exactly.
- Ducking is a straight line in dB: down to `depth_db` over `attack_ms` while anything plays on the trigger bus,
  back over `release_ms` after it stops; a new line during the release dips again from where it is.
- `python tools/audio/wavesmith/wavesmith.py events validate data/audio_events.json --root assets/audio` checks the file and that
  every take exists. `audit --root assets/audio` warns about sounds that will repeat identically (fewer than 3 takes
  and no pitch range), `random` picks, takes that differ by more than 3 LU (fix with `loudness.py normalize`), and
  missing captions (deaf and hard-of-hearing players miss uncaptioned sounds; UI and music are exempt). With
  `--root`, a bed whose files all have a loop point may be a single file.
- The engines (each game has only its own): src/core/audioDirector.ts with src/shell/audioPlayer.ts (web; Web
  Audio, works offline too), scripts/core/audio_director.gd (Godot), Assets/Scripts/Core/AudioDirector.cs (Unity,
  no UnityEngine dependency), src/core/audio_director.lua (LÖVE), src/logic/audio_director.rs (Bevy),
  src/core/AudioDirector.hpp (C++), Plugins/GameKitShell/.../GameKitAudioDirector.h (Unreal),
  game/js/plugins/GameAudio.js (RPG Maker MZ). Each is tested
  against `data/golden/audio.json`, written by
  `audio_events.py vectors --write` (the reference); randomness is a Park-Miller generator, so every engine makes the
  same choices from the same seed. Proven 2026-11-01: TypeScript in Vitest and in headless Chromium (an offline
  render showed the duck envelope within 0.001 dB, pitches exact, the voice cap held), GDScript headless with GUT,
  C# under dotnet test (plus 400 random scenarios), Lua headless in LÖVE 11.5, all with zero difference.

## Sound sets: footsteps per surface, ambience beds, a UI set
Sounds come in families, and a family fails in ways one file never shows: footsteps for four surfaces out of five, a
"footstep" that is two steps, one take much louder than its siblings. `tools/audio/wavesmith/sound_sets.py` makes a family in
one go and checks it as one. Describe the sets in data/sound_sets.json (you create it):
```json
{
  "version": 1, "out_dir": "assets/audio", "target": "home",
  "sets": {
    "footsteps": {"generator": "local_sfx", "bus": "sfx", "kind": "oneshot", "seconds": 0.6, "takes": 4, "onsets": 1,
                  "mono": true, "prompt": "one single footstep on {}, close up, dry, isolated, one step only",
                  "variants": {"stone": "a stone floor", "wood": "old wooden floorboards", "grass": "soft grass"},
                  "event": {"pitch_semitones": [-1, 1], "volume_db": [-2, 0], "max_voices": 4, "cooldown_ms": 80,
                            "caption": "[footsteps]"}},
    "ambience": {"generator": "local_sfx", "bus": "ambience", "kind": "loop", "seconds": 12, "takes": 1,
                 "prompt": "{}, ambience, steady background, no music, no voices",
                 "variants": {"cave": "a cave, water drips and low wind", "rain_roof": "steady rain on a roof"},
                 "event": {"caption": "[{variant}]"}},
    "chimes": {"generator": "sfx_synth", "bus": "ui", "takes": 2, "onsets": 1,
               "variants": {"bright": {"wave": "sine", "freq": 1320, "sustain": 0.05, "decay": 0.2, "volume": 0.4}}}
  }
}
```
- `python tools/audio/wavesmith/wavesmith.py sets ui --out assets/audio/ui` writes the built-in UI set from code: click, hover,
  confirm, back, error, toggle on and off, open, close, notify, a slider tick and a typewriter tick (`type`, for
  dialogue). Each file's `.sfx.json` says `"ship_safe": true`: no model and no samples, so no license question.
- `plan` lists what `make` would render; `make` renders every variant (local_sfx sets need ComfyUI with Stable Audio
  3, see the SFX section) and sets each file to its bus's house level (see Loudness below: the loudest 400 ms for
  one-shots, integrated loudness for loops, true peak never over -1 dBTP; loop points are kept). Files are named
  `<set>_<variant>_<n>.wav` in `<out_dir>/<set>/`, without `_<n>` when `takes` is 1.
- For one-shots with `onsets`, `make` renders `renders` takes (default twice `takes`, at least 4), counts each
  one's attacks and keeps the ones with the right count first, in local_sfx's rank order; it only fills up with the
  others when too few pass (check then flags them). In the kit's own run, Stable Audio 3 answered "a single short
  crunch" in packed snow with 0.6 to 0.8 s of crunching: 4 of 16 renders counted as one step with `attack_gap_s`
  0.45, so snow sits in its own set with `"renders": 16`.
- `check` fails a set when a take is missing or extra, a one-shot has a different number of attacks than `onsets`
  (Stable Audio often answers "a footstep" with two or three), takes of one variant are more than 3 LU apart, a file
  is more than 2 LU from its bus level, a loop has no loop point or clicks at the seam, or a file has no sidecar
  naming where it came from. `check --ship` also fails every file that is not ship-safe: Stable Audio output is
  under the Stability AI Community License, so clear that first (see the SFX section).
- `events data/sound_sets.json --root assets/audio --merge data/audio_events.json` adds one event per variant
  (`footsteps_stone`, ...: its takes, `random_no_repeat`, plus the set's `event` fields; `{variant}` in a caption
  becomes the variant's name) and refuses to write a file that would not pass `audio_events.py validate`.
- The attack counter is a 5 ms envelope: an attack is a rise above -18 dB of the file's loudest moment after at
  least 40 ms below -24 dB, and attacks less than `attack_gap_s` apart (default 0.2 s; walking puts steps 0.25 s or
  more apart) count as one, so the heel and toe of one step stay one step. It flags takes to listen to; it does not
  hear. Crunchy surfaces (snow, gravel) can flag a single step: listen, and if the step is single, raise that set's
  `attack_gap_s` rather than deleting good takes.

## Loudness: measure, check the mix, normalize
How loud a game sounds is measured, not guessed. `tools/audio/wavesmith/loudness.py` (no installs) gives the numbers the
platform holders and broadcasters use: integrated loudness in LUFS (ITU-R BS.1770-5), loudness range in LU (EBU
Tech 3342) and true peak in dBTP.
- `python tools/audio/wavesmith/wavesmith.py loudness measure "assets/audio/**/*.wav"`: one line per file (`--json` for scripts).
  Files under 0.4 s have no integrated loudness and files under 3 s no loudness range; it says "n/a" there.
- **Check the whole mix.** Sony's ASWG-R001 (v1.10, August 2013) is the published game target: the average loudness
  of the *whole* game, "measured as a whole" and not dialogue, music or effects separately, over "a minimum of 30
  minutes" of play that covers all parts of the game, at **-24 LKFS (+/-2) on home consoles and PC** or
  **-18 LKFS (+/-2) on handhelds and phones**, with true peak at most **-1 dBTP**. Record a 30-minute capture
  (Godot: `--write-movie capture.png` writes the frames plus a 32-bit `capture.wav`; it needs a window, Movie
  Maker crashes under `--headless`) and run
  `python tools/audio/wavesmith/wavesmith.py loudness check-mix capture.wav --target home`.
  It refuses to judge a shorter capture unless you pass `--allow-short` (then the verdict says provisional), and
  says how far to move the master or which peak to tame. A WAV capture is measured as it is read, in under 40 MB
  of memory at any length (measured: a 10-minute 48 kHz stereo capture peaked at 38 MB, as did a 1-minute one,
  against 508 MB for 1 minute before); FLAC, OGG and MP3 are decoded whole first, about 180 MB per minute of
  48 kHz stereo, so record long captures as WAV.
- **Single assets: kit house conventions, not a standard.** Before the mix is balanced by ear, assets start at
  levels relative to the platform target: dialogue at the target, music 4 LU under, effects 6, UI 8, ambience beds
  10 (`loudness.py conventions` prints the table). `loudness.py normalize vo/line.wav --bus dialogue --target home
  --out ...` applies it, or `--lufs -24` any level; true peak never goes past `--tp-ceiling` (default -1 dBTP):
  when the level cannot be reached without a limiter, it says so and stops at the ceiling. One-shots under 0.4 s are
  matched by true peak instead. These numbers are starting points; tune by ear in the game.
- Proof (K01, 2026-11-01): on 815 files (the SFX and voice bake-offs plus kit samples), integrated loudness matched
  pyloudnorm within 0.005 LU once pyloudnorm's two departures from BS.1770 are removed (its default filter
  approximates the K-weighting, and it counts a partial last block the standard leaves out), and ffmpeg's ebur128
  within 0.1 LU on all but one short clip; loudness range matched ffmpeg within 0.05 LU when ffmpeg's own
  percentile rounding is applied (ffmpeg reads a meaningless ~20 LU for clips with four or fewer 3 s windows); true
  peak was within 0.2 dB of an ideal reconstruction on 806 of 808 files (median 0.003 dB; the two others are
  heavily clipped full-band clips, 0.27 and 0.38 dB off, where ffmpeg is off by 0.38 and 0.46). The exam reproduces
  EBU Tech 3341 cases 1-5 and 15-23 and Tech 3342 cases 1-4.

## Dialogue and subtitles: typewriter, cues, captions
Write the lines once in data/dialogue.json (you create it); `tools/audio/wavesmith/dialogue.py` turns them and their voice
files into data/dialogue/en.built.json, the file each engine's dialogue reader loads (format v0: optional fields are
only ever added), and into SRT or WebVTT files for trailers and video captures.
```json
{
  "version": 1, "locale": "en",
  "speakers": {"guard": {"name": "Guard", "color": "#7FA7D9"}, "merchant": {"name": "Merchant"}},
  "lines": [
    {"id": "guard.halt", "speaker": "guard", "text": "Halt! The gate stays shut until dawn.",
     "audio": "voice/guard_halt.wav", "timeline": "voice/guard_halt.timeline.json"},
    {"id": "merchant.offer", "speaker": "merchant", "text": "Rope, lanterns, bread. Fair prices, friend.",
     "audio": "voice/merchant_offer.wav"},
    {"id": "guard.bark_alert", "speaker": "guard", "text": "Over there!", "kind": "bark",
     "priority": 80, "interrupt": "always", "cooldown_s": 8}
  ],
  "sequences": {"gate": [{"line": "guard.halt", "at": 0.5},
                         {"line": "merchant.offer", "after": "guard.halt", "gap_s": 0.4}]}
}
```
- Typewriter reveal, one time per character: exact from a babble.py `.timeline.json`; estimated from any other
  voice file (spread over its voiced part with pauses at punctuation: right for a typewriter, not for lip sync); at
  the speaker's `cps` when a line has no audio yet. The engines use the reveal list only when it has one entry per
  character of the text they show; otherwise (a translation, the pseudo locale, a list built for another take) they
  type at 30 characters a second, faster when that would not finish within the line's `duration_s`, so a line always
  ends fully shown (`dialogue.py` `reveal_count`, the reference; Godot, LÖVE, web and web 3D follow
  data/golden/dialogue.json, written by `dialogue.py vectors --write`).
- Subtitle cues follow the published guidelines (checked 2026-11-01): at most 40 characters a line (Xbox
  Accessibility Guideline 104 calls longer lines long; Netflix allows 42), at most 2 lines, line breaks at
  punctuation and bottom-heavy, at least 5/6 s and at most 7 s on screen, and a reading speed of at most 20
  characters a second (Netflix, adults; `--audience children` uses 17). Exports name the speaker whenever it changes
  and again after a minute of silence (XAG 104); SRT has no voice tag, so its `NAME: ` prefix is laid out within
  the 40 characters, and lint warns about a line whose first cue has no room for it.
- `kind: "bark"` lines are short reactions the game fires itself: `priority`, `interrupt` (`never`, `lower`,
  `always`) and `cooldown_s` say what may cut in; lint warns about a bark without a cooldown.
- SFX captions: build with `--events data/audio_events.json` and every event with a `caption` becomes one (with
  `caption_priority` and `caption_min_s`; `"directional": true` on sounds whose side of the screen matters, so the
  game draws an arrow, as XAG 104 asks). Subtitles and SFX captions should have separate settings toggles.
- `python tools/audio/wavesmith/wavesmith.py dialogue build data/dialogue.json --root assets/audio --events data/audio_events.json --out
  data/dialogue/en.built.json`; `lint` reports reading speed, short and long cues, words too long to break, unknown
  speakers and missing files (`--strict` makes warnings fail); `export data/dialogue/en.built.json --sequence gate
  --format vtt --out gate.vtt` writes a sequence at absolute times.
- `lint --pseudo` asks what happens when the text is translated and the voice stays (subtitled, not dubbed): every
  line goes through the kit's pseudo-locale (accented, 40 % longer, in brackets; tools/golden_vectors.py `pseudo()`,
  the same text the engines show in locale "pseudo"), is revealed over the same voice timing and cut into cues by the
  same rules, and gets the same warnings, marked "(pseudo, +40 %)"; captions must still fit one line. A line that
  reads at 18 characters a second in English needs about 25 in a language 40 % longer: give it more time now.
- Proven 2026-11-01: the exam, and the web reader in headless Chromium with three babble lines: all 25 blips found in
  the rendered audio, each blip's character shown on the first 60 fps frame at or after the sound starts (0.4 ms of
  sample rounding at most, so never more than one frame late), and the exported SRT cues shown with the same text
  from start to end and gone after it (16 checks). The same check fails when the reveal is moved 20 ms either way or
  a cue is held 0.1 s too long.

## Accessibility: mono, volume sliders, directional captions
SOP-20 asks for a mono switch, a volume slider per bus and an arrow on captions for sounds from off screen. The
settings already hold them (settings.audio master, music, sfx, ui, voice, mono; access.captions_sfx); this is how the
audio side keeps its part.
- **Mono survives the switch.** Players with hearing in one ear turn on mono, and the browser then plays
  0.5 * (L + R) (the Web Audio down-mix rule; other engines' mono options were not checked). A stereo sound
  whose channels are out of phase cancels itself there. `python tools/audio/wavesmith/wavesmith.py loudness mono "assets/audio/**/*.wav"`
  prints what each stereo file loses (3 LU when both sides carry the same sound, 6 LU when they are unrelated) and
  fails a file that loses more than 9 LU or has a loud 400 ms stretch with correlation below -0.5 (kit conventions,
  not a standard; `--max-loss`, `--min-corr`). Fix it at the source: flip one channel's polarity back, or narrow
  the stereo widener.
- **Sliders reach the buses.** The rule is tools/audio/wavesmith/access.py (`access gains` shows what each bus of a
  game's events file gets), followed by every engine against data/golden/access.json. On web and web-3d,
  `player.applySettings(shell.settings.audio)` after the settings change
  sets every bus of data/audio_events.json from its slider (src/core/audioAccess.ts, `SLIDER_FOR_BUS`: music,
  sfx and ambience, ui, voice for dialogue, master); a bus whose parent already follows the same slider is not turned
  down a second time, so ambience under sfx moves with the sfx slider once. LÖVE: a source's volume is the product of
  the gains along its bus chain (src/core/audio_access.lua). Unity: Assets/Scripts/Game/AudioEventPlayer.cs. Godot's
  shell already sets its own AudioServer buses from the sliders.
- **Arrows on directional captions (web, web-3d, Godot, LÖVE).** Mark the event `"directional": true` in
  audio_events.json
  (dialogue.py copies it into the built captions), then pass where the sound is:
  `shell.subtitles.caption("growl", { dx, dy, halfW, halfH })` with the source's offset from the view's centre and
  half the view's size (in 3D, the source projected to the screen). Nothing is added while the source is on screen;
  off screen it gets one of eight arrows, on the side it comes from ("← [growl]", "[growl] ↗"). Godot:
  `subtitle_bar.caption("growl", {dx, dy, half_w, half_h})`; LÖVE: `subtitles:caption("growl", from)`, which draws
  the arrow as a shape because LÖVE's default font has none of the arrow glyphs. Unity, Bevy, C++, Unreal and RPG Maker MZ have
  `CaptionArrow` / `caption_arrow` for your own caption UI.
- Proven 2026-11-01 in headless Chromium: six stereo ambience beds and an out-of-phase test file through a node set up
  like the mono switch came out equal to 0.5 * (L + R) to 1.5e-8, and `loudness.py mono` predicted the loudness of
  Chromium's mono render within 0.01 LU on all seven; the AudioPlayer with sliders set played every bus at its slider
  times its volume_db within 0.001 dB, ambience included (the same check with the double-count guard removed is 12 dB
  off and fails).

## Hardware: what runs where
Most of Wavesmith needs nothing but Python 3.8 or newer: no GPU, no installs, and no operating-system code (all its exams pass
on Windows with Python 3.8, 3.9, 3.12 and 3.13 and on Linux, Ubuntu 26.04 with Python 3.14, measured 2026-11-01; macOS untested). The two
model-backed tools have their own needs:

| Subcommand | Needs | Without an NVIDIA GPU |
|---|---|---|
| loudness, events, sets (check, ui), dialogue, music, access, babble, synth, chiptune, wav, formats | Python 3.8+ | runs anywhere Python does (macOS untested) |
| formats (MP3, Opus input; OGG output) | ffmpeg, optional | WAV, FLAC and OGG Vorbis need nothing |
| voice (local_tts) | a separate Python with torch and qwen-tts | `--device auto` (the default) uses an NVIDIA GPU, else Apple's Metal (mps), else the CPU. CPU measured: a 2.4 s line in 47 s (about 20x realtime, 8-core desktop CPU, plus about 30 s to load), transcribed word for word, same voice as on the GPU (0.961). Apple Metal is not tested here |
| sfx, sets make (local_sfx) | a running ComfyUI with Stable Audio 3 | ComfyUI's own README lists NVIDIA, AMD (ROCm on Linux, and on Windows 11), Intel Arc, Apple silicon and Ascend, and its Windows portable build can run on the CPU alone; Wavesmith only talks to it over HTTP. Measured here on NVIDIA only |
| eleven, fish | an API key (paid services) | no local hardware at all |

Local language-model drafts (Voice) were tested with llama.cpp's llama-server; other local servers that speak the
same OpenAI-style chat API should work the same way, but were not tested here, and none of them ships in the kit.

Back to the index: `docs/RESOURCES.md`.

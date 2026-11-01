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
- This kit: `python tools/audio/chiptune.py <song>.json --out <music>.wav` renders a song written as text patterns
  (two pulse channels, triangle bass, noise drums) and writes loop points into the WAV, so Godot and Unity loop it
  with default import settings. The song format is in the script's header; `--solo <channel>` renders one part.
  Claude can write the song file; log the result as AI-assisted (`pre-generated`) in `docs/ASSET_LOG.md`.
- Generated: `python tools/audio/eleven_audio.py music --prompt "..." --instrumental --out <music>.wav --loop-crossfade 2 --log`
  (ElevenLabs, your API key, a paid plan for music). Suno has no official API (third-party "Suno API" sites resell
  their own credits and do not carry your plan's rights): use its web app, then
  `python tools/audio/wavfile.py loop <download>.wav --crossfade 2 --end <s> --out <music>.wav` for a seamless loop.
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

## Voice
- Pre-generated lines: `python tools/audio/fish_tts.py say --voice <id> --text "..." --out <voice>.mp3` (Fish Audio,
  your key in `FISH_API_KEY`; `check` shows the developer API balance, which is billed apart from a subscription;
  `voices --licensed --search <words>` finds a voice ID). ElevenLabs and others work too (`docs/BRIEFS.md`, Voice).
- Lines written while the game runs (an LLM NPC) cannot be pre-recorded: see the live voice in
  `examples/gatekeeper-godot` and the key rules in `SOP-15`.
- Never pick a library voice that imitates a real person or a famous character, even if it is marked licensed.
- Babble instead of words (the gibberish blips many 2D games play while a speech bubble types out): this kit's
  `python tools/audio/babble.py "Halt! Who goes there?" --voice knight --out assets/audio/voice/halt.wav` makes it
  from code, so there is no account, cost or license question. Voices: baker, knight, smith, sprite, golem
  (`--list`; tune with `--set f0=... --set metal=...`); `--variants 3` writes takes to compare, `--lines <file>`
  voices a whole script. Each WAV gets `<name>.timeline.json` with the time each character should appear: drive
  the typewriter reveal from it so text and voice stay in step. Questions rise at the end, exclamations get louder.
  `--bank-dir <folder>` swaps the synth for recorded syllables (`ba.wav`, `ko.wav`, ...) if you want a real voice's
  colour.

**Local voices, on your own GPU** (`tools/audio/local_tts.py`, Qwen3-TTS; no account, nothing per line)
- Design a character's voice once from a description, then voice every line in it:
  `python tools/audio/local_tts.py design "gruff older blacksmith, deep gravelly voice, slow speech" --out
  assets_src/voice/smith_ref.wav`, then `python tools/audio/local_tts.py say --ref assets_src/voice/smith_ref.wav
  --lines docs/dialog/smith.txt --out assets/audio/voice/smith.wav` (`smith_1.wav`, `smith_2.wav` ...). Listen to
  the reference first; a different `--seed` or a clearer description gives another voice. Spoken barks work as
  plain words ("Hyah!", "Ha ha ha!"). For voices deeper or stranger than a person: `--pitch -5` (a giant, also
  slower) or `+5` (a small creature), `--ring-hz 40` (metal, golems, robots).
- **Never clone a real person's voice without their written permission.** Designed voices are the documented
  path. A recording works only with `--ref-text "<its exact words>" --ref-origin self` (your own voice) or
  `--ref-origin permission` (the speaker agreed in writing); every `.gen.json` and `--log` row records where the
  voice came from.
- Speed: about 3x slower than realtime on a 16 GB RTX 5060 Ti (a 3 s line takes about 10 s, plus about 30 s to load
  the model per run, so voice a whole `--lines` script in one run). Pre-made lines only, not live speech.
- Setup (one time). The model runs in its own Python environment so the kit's tools stay standard-library only:
  ```
  uv venv tts-env --python 3.12
  uv pip install --python tts-env qwen-tts torch torchaudio --torch-backend cu130   # your CUDA: cu128, cu126 ...
  setx LOCAL_TTS_PYTHON "<full path>\tts-env\Scripts\python.exe"                     # macOS/Linux: export ... /bin/python
  python tools/audio/local_tts.py check        # names what is missing: the env, torch, qwen-tts, or CUDA
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
- This kit: `python tools/audio/sfx_synth.py jump --variants 5 --out build/audition/jump.wav` writes five takes to
  compare (presets: jump, coin, land, fall, hit, pickup, blip, laser, explosion). Each WAV gets a JSON recipe;
  `--from <recipe>` re-renders it exactly and `--set key=value` tweaks one number.
- Generated: `python tools/audio/eleven_audio.py sfx --text "old iron gate creaking open" --seconds 2 --out <sfx>.wav --mono --log`
  (about 10 credits per second; free-plan output is non-commercial and is logged as PLACEHOLDER).
  Generated audio can come back very quiet: `python tools/audio/wavfile.py stats|normalize <file>`.
- Local, on your own GPU (no account, no per-sound cost): `python tools/audio/local_sfx.py make "heavy wooden door
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
- FLAC to WAV with nothing installed: `python tools/audio/flacfile.py towav <file>.flac --out <file>.wav` (16/24-bit,
  mono/stereo; checks the file's MD5). Tags do not carry over, which matters for ComfyUI's FLACs: they hold the
  full prompt and workflow, local paths included (`tools/art/comfy_local.py strip` cleans a FLAC in place).
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
- Ducking is a straight line in dB: down to `depth_db` over `attack_ms` while anything plays on the trigger bus,
  back over `release_ms` after it stops; a new line during the release dips again from where it is.
- `python tools/audio/audio_events.py validate data/audio_events.json --root assets/audio` checks the file and that
  every take exists. `audit --root assets/audio` warns about sounds that will repeat identically (fewer than 3 takes
  and no pitch range), `random` picks, takes that differ by more than 3 LU (fix with `loudness.py normalize`), and
  missing captions (deaf and hard-of-hearing players miss uncaptioned sounds; UI and music are exempt). With
  `--root`, a bed whose files all have a loop point may be a single file.
- The engines (each game has only its own): src/core/audioDirector.ts with src/shell/audioPlayer.ts (web; Web
  Audio, works offline too), scripts/core/audio_director.gd (Godot), Assets/Scripts/Core/AudioDirector.cs (Unity,
  no UnityEngine dependency), src/core/audio_director.lua (LÖVE). Each is tested against `data/golden/audio.json`, written by
  `audio_events.py vectors --write` (the reference); randomness is a Park-Miller generator, so every engine makes the
  same choices from the same seed. Proven 2026-11-01: TypeScript in Vitest and in headless Chromium (an offline
  render showed the duck envelope within 0.001 dB, pitches exact, the voice cap held), GDScript headless with GUT,
  C# under dotnet test (plus 400 random scenarios), Lua headless in LÖVE 11.5, all with zero difference.

## Sound sets: footsteps per surface, ambience beds, a UI set
Sounds come in families, and a family fails in ways one file never shows: footsteps for four surfaces out of five, a
"footstep" that is two steps, one take much louder than its siblings. `tools/audio/sound_sets.py` makes a family in
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
- `python tools/audio/sound_sets.py ui --out assets/audio/ui` writes the built-in UI set from code: click, hover,
  confirm, back, error, toggle on and off, open, close, notify, a slider tick and a typewriter tick (`type`, for
  dialogue). Each file's `.sfx.json` says `"ship_safe": true`: no model and no samples, so no license question.
- `plan` lists what `make` would render; `make` renders every variant (local_sfx sets need ComfyUI with Stable Audio
  3, see the SFX section) and sets each file to its bus's house level (see Loudness below: the loudest 400 ms for
  one-shots, integrated loudness for loops, true peak never over -1 dBTP; loop points are kept). Files are named
  `<set>_<variant>_<n>.wav` in `<out_dir>/<set>/`, without `_<n>` when `takes` is 1.
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
How loud a game sounds is measured, not guessed. `tools/audio/loudness.py` (no installs) gives the numbers the
platform holders and broadcasters use: integrated loudness in LUFS (ITU-R BS.1770-5), loudness range in LU (EBU
Tech 3342) and true peak in dBTP.
- `python tools/audio/loudness.py measure "assets/audio/**/*.wav"`: one line per file (`--json` for scripts).
  Files under 0.4 s have no integrated loudness and files under 3 s no loudness range; it says "n/a" there.
- **Check the whole mix.** Sony's ASWG-R001 (v1.10, August 2013) is the published game target: the average loudness
  of the *whole* game, "measured as a whole" and not dialogue, music or effects separately, over "a minimum of 30
  minutes" of play that covers all parts of the game, at **-24 LKFS (+/-2) on home consoles and PC** or
  **-18 LKFS (+/-2) on handhelds and phones**, with true peak at most **-1 dBTP**. Record a 30-minute capture
  (Godot: `--write-movie capture.png` writes the frames plus a 32-bit `capture.wav`; it needs a window, Movie
  Maker crashes under `--headless`) and run
  `python tools/audio/loudness.py check-mix capture.wav --target home`.
  It refuses to judge a shorter capture unless you pass `--allow-short` (then the verdict says provisional), and
  says how far to move the master or which peak to tame.
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
Write the lines once in data/dialogue.json (you create it); `tools/audio/dialogue.py` turns them and their voice
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
  the speaker's `cps` when a line has no audio yet.
- Subtitle cues follow the published guidelines (checked 2026-11-01): at most 40 characters a line (Xbox
  Accessibility Guideline 104 calls longer lines long; Netflix allows 42), at most 2 lines, line breaks at
  punctuation and bottom-heavy, at least 5/6 s and at most 7 s on screen, and a reading speed of at most 20
  characters a second (Netflix, adults; `--audience children` uses 17). Exports name the speaker whenever it changes
  and again after a minute of silence (XAG 104).
- `kind: "bark"` lines are short reactions the game fires itself: `priority`, `interrupt` (`never`, `lower`,
  `always`) and `cooldown_s` say what may cut in; lint warns about a bark without a cooldown.
- SFX captions: build with `--events data/audio_events.json` and every event with a `caption` becomes one (with
  `caption_priority` and `caption_min_s`; `"directional": true` on sounds whose side of the screen matters, so the
  game draws an arrow, as XAG 104 asks). Subtitles and SFX captions should have separate settings toggles.
- `python tools/audio/dialogue.py build data/dialogue.json --root assets/audio --events data/audio_events.json --out
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
  whose channels are out of phase cancels itself there. `python tools/audio/loudness.py mono "assets/audio/**/*.wav"`
  prints what each stereo file loses (3 LU when both sides carry the same sound, 6 LU when they are unrelated) and
  fails a file that loses more than 9 LU or has a loud 400 ms stretch with correlation below -0.5 (kit conventions,
  not a standard; `--max-loss`, `--min-corr`). Fix it at the source: flip one channel's polarity back, or narrow
  the stereo widener.
- **Sliders reach the buses (web, web-3d).** `player.applySettings(shell.settings.audio)` after the settings change
  sets every bus of data/audio_events.json from its slider (src/core/audioAccess.ts, `SLIDER_FOR_BUS`: music,
  sfx and ambience, ui, voice for dialogue, master); a bus whose parent already follows the same slider is not turned
  down a second time, so ambience under sfx moves with the sfx slider once.
- **Arrows on directional captions (web, web-3d).** Mark the event `"directional": true` in audio_events.json
  (dialogue.py copies it into the built captions), then pass where the sound is:
  `shell.subtitles.caption("growl", { dx, dy, halfW, halfH })` with the source's offset from the view's centre and
  half the view's size (in 3D, the source projected to the screen). Nothing is added while the source is on screen;
  off screen it gets one of eight arrows, on the side it comes from ("← [growl]", "[growl] ↗").
- Proven 2026-11-01 in headless Chromium: six stereo ambience beds and an out-of-phase test file through a node set up
  like the mono switch came out equal to 0.5 * (L + R) to 1.5e-8, and `loudness.py mono` predicted the loudness of
  Chromium's mono render within 0.01 LU on all seven; the AudioPlayer with sliders set played every bus at its slider
  times its volume_db within 0.001 dB, ambience included (the same check with the double-count guard removed is 12 dB
  off and fails).

Back to the index: `docs/RESOURCES.md`.

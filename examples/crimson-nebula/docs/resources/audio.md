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
- `sfxr` / `jsfxr` (browser), `Bfxr`, `ChipTone`, `LabChirp`. Output is yours to use.

**Edit and process**
- `Audacity` (free), `Reaper`, `Ocenaudio`. Normalize, trim silence, add tiny fades to avoid clicks.
- Layer 2 to 3 sounds per important event (impact plus tail plus pitch variation). Randomize pitch ±5 percent
  and rotate 3 to 5 variants for anything that repeats.

**DIY foley**
- Phone or cheap recorder, quiet room, record then edit. Zero license questions.

**Implementation hints**
- Keep SFX short, mono for positional, 44.1 kHz or 48 kHz, WAV in source control, OGG for shipping if size matters.
- Bus structure: Master > Music, SFX, UI, Voice. Expose volume sliders from day one.

Back to the index: `docs/RESOURCES.md`.

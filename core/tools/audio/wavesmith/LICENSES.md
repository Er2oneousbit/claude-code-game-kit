# Wavesmith licence register

Every model or service Wavesmith can call, with its licence and what that means for a game that ships. Checked
2026-11-01 against each model card or licence page (sources in `docs/EVIDENCE.md`). Licences can change upstream, so
re-check the cards before you ship.

| Subcommand | What it loads | Licence | Ship the output? |
|---|---|---|---|
| `synth`, `chiptune`, `babble` (and `sets ui`) | nothing: sound made from code | yours | yes |
| `voice` | Qwen3-TTS-12Hz-1.7B-VoiceDesign, -1.7B-Base, -0.6B-Base (Qwen) | Apache-2.0 (model cards) | yes. Never clone a real person's voice without written permission; every `.gen.json` records where the voice came from |
| `sfx`, `sets make` (local_sfx sets) | Stable Audio 3 medium or small-sfx (Stability AI), with the T5Gemma text encoder | Stability AI Community License: free under USD 1M annual revenue, Enterprise licence above; "you own outputs"; the bundled T5Gemma encoder carries Google's Gemma terms | only after you have checked that licence for your game. `sets check --ship` refuses these files until then, and the kit's own examples never contain them |
| `eleven` | ElevenLabs API (paid, your key) | your ElevenLabs plan's terms | per your plan; read them for games |
| `fish` | Fish Audio API (paid, your key) | your Fish Audio plan's terms | per your plan; read them for games |
| `loudness`, `events`, `sets check`, `dialogue`, `music`, `wav` | nothing: measuring and data tools | n/a | n/a |
| `formats` (and every tool above, for MP3, Opus or AAC input) | WAV, FLAC and OGG Vorbis: nothing (the decoders are in this folder). Other formats, and OGG output: ffmpeg, only if you installed it | ffmpeg: LGPL 2.1 or later; "If those parts get used the GPL applies to all of FFmpeg" (ffmpeg.org/legal.html, checked 2026-11-01). Many ready-made builds include the GPL parts | yes: converting does not change who owns the sound. The kit ships no ffmpeg and only runs it as a separate program; if your game ships ffmpeg itself, follow that page's checklist |

## Music models looked at, not wired in (K02, 2026-11-01, two rounds)
| Model | Licence as read | Verdict |
|---|---|---|
| ACE-Step 1.5 (turbo) | MIT on ACE-Step's card ("You can strictly use the generated music for commercial purposes"); Apache-2.0 on Comfy-Org's ComfyUI repackaging | tested in K02 round 2: tempo within 2 % in 17 of 18 takes, the best of the models tried; its output may ship. Runs in ComfyUI 0.43+ (no Wavesmith subcommand yet) |
| Stable Audio Open 1.0 | Stability AI Community License; its card says it is "better at generating sound effects and field recordings than music" | tested in K02 (tempo within 2 % in 15 of 18 takes); same shipping rule as `sfx` |
| MusicGen / AudioCraft | CC BY-NC 4.0 (weights) | do not use: non-commercial |
| YuE2-3B | CC BY-NC 4.0 plus individual creator permission | do not use for a studio or company |
| InspireMusic, SongBloom, Tencent SongGeneration | licence could not be verified | do not use until it can be |

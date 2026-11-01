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

## Music models looked at, not wired in (K02, 2026-11-01)
| Model | Licence as read | Verdict |
|---|---|---|
| ACE-Step 1.5 | MIT; card: "You can strictly use the generated music for commercial purposes" | the candidate for a music subcommand; not installed or tested yet |
| Stable Audio Open 1.0 | Stability AI Community License; its card says it is "better at generating sound effects and field recordings than music" | tested in K02 (tempo within 2 % in 15 of 18 takes); same shipping rule as `sfx` |
| MusicGen / AudioCraft | CC BY-NC 4.0 (weights) | do not use: non-commercial |
| YuE2-3B | CC BY-NC 4.0 plus individual creator permission | do not use for a studio or company |
| InspireMusic, SongBloom, Tencent SongGeneration | licence could not be verified | do not use until it can be |

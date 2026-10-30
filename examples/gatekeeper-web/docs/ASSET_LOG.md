# Asset Log

> Every third-party or AI-assisted asset gets a row BEFORE it is used. Use `/asset-intake`.
> Source of truth for credits screens, store disclosures, and license audits.
> Where to find things: `docs/RESOURCES.md` (index into `docs/resources/`).

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | tileset | `public/assets/art/tilemap_packed.png` | https://kenney.nl/assets/tiny-dungeon | Kenney | CC0 |  | no | no | 2026-10-21 | Tiny Dungeon 1.0: 12x11 tiles of 16 px |
| A-0002 | sfx | removed 2026-10-23 (was open_001.ogg, error_004.ogg, select_002.ogg; replaced by ElevenLabs sounds) | https://kenney.nl/assets/interface-sounds | Kenney | CC0 |  | no | no | 2026-10-21 | gate opens, turned away, guard speaks |
| A-0003 | sfx | `public/assets/audio/gate-open.mp3` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: heavy wooden town gate creaking open, iron hinges groaning, a chain rattling, no music; model eleven_text_to_sound_v2; replaces Kenney open_001 (gate opens); peak-normalized to -3 dBFS (was -0.1) |
| A-0004 | sfx | `public/assets/audio/turned-away.mp3` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: armored guard stamps a spear butt on cobblestones, firm wooden thud and a chainmail clink, no music; model eleven_text_to_sound_v2; replaces Kenney error_004 (turned away); peak-normalized to -3 dBFS (was -10.9) |
| A-0005 | sfx | `public/assets/audio/guard-talk.mp3` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: short soft rustle of leather and chainmail, a guard shifting his weight, no music; model eleven_text_to_sound_v2; replaces Kenney select_002 (the guard speaks); peak-normalized to -3 dBFS (was -10.1) |
| A-0006 | sfx | `public/assets/audio/gate-ambience.wav` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: medieval town gate at dusk, light wind, distant crowd murmur, a torch crackling nearby, no music; model eleven_text_to_sound_v2; new: ambience loop; peak-normalized to -6 dBFS (was -2) |

## Rules
- "AI-assisted?" uses one of: `no`, `dev-only` (AI helped, nothing AI-made ships), `pre-generated` (AI output ships in the build), `live` (generated at runtime). Steam's disclosure is built from the `pre-generated` and `live` rows (see SOP-04).
- Unknown license means it does not go in. Prototype-only (NC) assets are tagged `PLACEHOLDER` in Notes and replaced before release.
- Store the license text or a screenshot of the license page next to the asset or in `docs/licenses/`.
- AI-assisted: record tool, date, prompt summary, how much was edited by hand. Needed for store disclosure forms.
- Keep `CREDITS.md` generated from this table (see `/release-check`).

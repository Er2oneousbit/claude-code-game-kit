# Asset Log

> Every third-party or AI-assisted asset gets a row BEFORE it is used. Use `/asset-intake`.
> Source of truth for credits screens, store disclosures, and license audits.
> Where to find things: `docs/RESOURCES.md` (index into `docs/resources/`).

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | tileset | `public/assets/art/tilemap_packed.png` | https://kenney.nl/assets/tiny-dungeon | Kenney | CC0 |  | no | no | 2026-10-21 | Tiny Dungeon 1.0: 12x11 tiles of 16 px, no spacing |
| A-0002 | art | `docs/concepts/final/Preview.png` | https://kenney.nl/assets/tiny-dungeon | Kenney | CC0 |  | no | no | 2026-10-21 | concept reference C-0001 (not shipped in the game) |
| A-0003 | sfx | removed 2026-10-23 (was glass_002.ogg, confirmation_002.ogg, open_001.ogg, glitch_003.ogg; replaced by ElevenLabs sounds) | https://kenney.nl/assets/interface-sounds | Kenney | CC0 |  | no | no | 2026-10-21 | oil pickup, key, door/win, caught |
| A-0004 | sfx | `public/assets/audio/oil-refill.mp3` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: lantern oil poured from a small glass flask, a clear liquid glug glug, then a soft whoomp as a lantern flame flares brighter, no music; model eleven_text_to_sound_v2; replaces Kenney glass_002 (oil); peak-normalized to -3 dBFS (was -16.6) |
| A-0005 | sfx | `public/assets/audio/key-found.mp3` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: old wooden chest creaking open and an iron key picked up with a bright jingle, no music; model eleven_text_to_sound_v2; replaces Kenney confirmation_002 (key); peak-normalized to -3 dBFS (was 0) |
| A-0006 | sfx | `public/assets/audio/door-escape.mp3` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: old wooden door unlocked with a key and swinging open, then an airy whoosh of night air, no music; model eleven_text_to_sound_v2; replaces Kenney open_001 (win); peak-normalized to -3 dBFS (was 0) |
| A-0007 | sfx | `public/assets/audio/ghost-caught.mp3` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: ghostly wail swooping close, cold spectral whoosh, a lantern flame snuffed out, no music; model eleven_text_to_sound_v2; replaces Kenney glitch_003 (caught); peak-normalized to -3 dBFS (was -1.3) |
| A-0008 | sfx | `public/assets/audio/haunted-ambience.wav` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: dark haunted house interior ambience, low eerie drone, faint distant wind, occasional soft wooden creak, no music; model eleven_text_to_sound_v2; new: ambience loop; peak-normalized to -6 dBFS (was -21) |

## Rules
- "AI-assisted?" uses one of: `no`, `dev-only` (AI helped, nothing AI-made ships), `pre-generated` (AI output ships in the build), `live` (generated at runtime). Steam's disclosure is built from the `pre-generated` and `live` rows (see SOP-04).
- Unknown license means it does not go in. Prototype-only (NC) assets are tagged `PLACEHOLDER` in Notes and replaced before release.
- Store the license text or a screenshot of the license page next to the asset or in `docs/licenses/`.
- AI-assisted: record tool, date, prompt summary, how much was edited by hand. Needed for store disclosure forms.
- Keep `CREDITS.md` generated from this table (see `/release-check`).

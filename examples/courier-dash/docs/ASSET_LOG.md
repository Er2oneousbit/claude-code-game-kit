# Asset Log

> Every third-party or AI-assisted asset gets a row BEFORE it is used. Use `/asset-intake`.
> Source of truth for credits screens, store disclosures, and license audits.
> Where to find things: `docs/RESOURCES.md` (index into `docs/resources/`).

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | 3d | source: `assets_src/character-female-c.glb`, `assets_src/Textures/colormap.png`; shipped: `public/assets/models/characters/courier.glb` | https://kenney.nl/assets/mini-characters | Kenney | CC0 |  | no | yes | 2026-10-21 | the courier (32 animations: idle, walk, sprint, pick-up, die...). Shipped file re-exported by `tools/blender/prep_export.py --pivot keep --class npc` (texture embedded, names cleaned) |
| A-0002 | 3d | `public/assets/models/platformer/crate.glb`, `public/assets/models/platformer/flag.glb`, `public/assets/models/platformer/Textures/colormap.png` | https://kenney.nl/assets/platformer-kit | Kenney | CC0 |  | no | no | 2026-10-21 | parcels (crate) and the depot flag |
| A-0003 | 3d | `public/assets/models/suburban/` (8 files) | https://kenney.nl/assets/city-kit-suburban | Kenney | CC0 |  | no | no | 2026-10-21 | town houses, trees, fences |
| A-0004 | 3d | `public/assets/models/roads/` (4 files) | https://kenney.nl/assets/city-kit-roads | Kenney | CC0 |  | no | no | 2026-10-21 | street tiles |
| A-0005 | sfx | removed 2026-10-23 (was select_002.ogg, confirmation_002.ogg, error_006.ogg, tick_002.ogg; replaced by ElevenLabs sounds) | https://kenney.nl/assets/interface-sounds | Kenney | CC0 |  | no | no | 2026-10-21 | pickup, delivered, caught, last seconds |
| A-0006 | 3d | `public/assets/models/space/rover.glb` | https://kenney.nl/assets/space-kit | Kenney | CC0 |  | no | no | 2026-10-21 | the patrol robot |
| A-0007 | sfx | `public/assets/audio/parcel-pickup.mp3` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: cardboard parcel picked up, quick soft thump and a bright cheerful two-note toy chime, no music; model eleven_text_to_sound_v2; replaces Kenney select_002 (pickup); peak-normalized to -3 dBFS (was -15.3) |
| A-0008 | sfx | `public/assets/audio/parcel-delivered.mp3` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: cheerful toy doorbell ding-dong with a small coin jingle, parcel delivered, cartoon, no music; model eleven_text_to_sound_v2; replaces Kenney confirmation_002 (delivered); peak-normalized to -3 dBFS (was -5.5) |
| A-0009 | sfx | `public/assets/audio/robot-caught.mp3` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: small toy robot alarm buzz and a short descending electronic boop, playful, caught, no music; model eleven_text_to_sound_v2; replaces Kenney error_006 (caught); peak-normalized to -3 dBFS (was -5.1) |
| A-0010 | sfx | `public/assets/audio/clock-tick.mp3` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: single crisp wooden clock tick, short and dry, no music; model eleven_text_to_sound_v2; replaces Kenney tick_002 (last seconds); peak-normalized to -3 dBFS (was -3.9) |
| A-0011 | sfx | `public/assets/audio/town-ambience.wav` | ElevenLabs API (/v1/sound-generation) | ElevenLabs (generated) | ElevenLabs non-commercial terms: PLACEHOLDER | Created in collaboration with ElevenLabs (elevenlabs.io) | pre-generated | yes | 2026-10-23 | PLACEHOLDER; prompt: calm toy town street ambience in daytime, distant birds, soft breeze, faint far-off traffic hum, no music; model eleven_text_to_sound_v2; new: ambience loop; peak-normalized to -6 dBFS (was -33.4) |

## Rules
- "AI-assisted?" uses one of: `no`, `dev-only` (AI helped, nothing AI-made ships), `pre-generated` (AI output ships in the build), `live` (generated at runtime). Steam's disclosure is built from the `pre-generated` and `live` rows (see SOP-04).
- Unknown license means it does not go in. Prototype-only (NC) assets are tagged `PLACEHOLDER` in Notes and replaced before release.
- Store the license text or a screenshot of the license page next to the asset or in `docs/licenses/`.
- AI-assisted: record tool, date, prompt summary, how much was edited by hand. Needed for store disclosure forms.
- Keep `CREDITS.md` generated from this table (see `/release-check`).

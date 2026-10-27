# Asset Log

> Every third-party or AI-assisted asset gets a row BEFORE it is used. Use `/asset-intake`.
> Source of truth for credits screens, store disclosures, and license audits.
> Where to find things: `docs/RESOURCES.md` (index into `docs/resources/`).

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | tileset | `assets/art/pixel_platformer/tilemap_packed.png`, `assets/art/pixel_platformer/tilemap-backgrounds_packed.png` | https://kenney.nl/assets/pixel-platformer | Kenney | CC0 |  | no | no | 2026-10-21 | Pixel Platformer 1.2: tiles and backgrounds (18 px grid, no spacing). The characters sheet was removed 2026-10-22 when the fox (A-0006) replaced the alien |
| A-0002 | sfx | removed 2026-10-22 (was phaseJump1.ogg, pepSound1.ogg, lowDown.ogg) | https://kenney.nl/assets/digital-audio | Kenney | CC0 |  | no | no | 2026-10-21 | jump, coin, fall |
| A-0003 | sfx | removed 2026-10-22 (was impactSoft_medium_000.ogg) | https://kenney.nl/assets/impact-sounds | Kenney | CC0 |  | no | no | 2026-10-21 | landing thud |
| A-0004 | music | removed 2026-10-22 (was jingles_NES00.ogg) | https://kenney.nl/assets/music-jingles | Kenney | CC0 |  | no | no | 2026-10-21 | goal jingle |
| A-0005 | music | removed 2026-10-22 (was level1.ogg) | https://opengameart.org/content/5-chiptunes-action | Juhani Junkala (SubspaceAudio) | CC0 |  | no | yes | 2026-10-21 | level music, loops seamlessly; "Level 1.wav" re-encoded to OGG Vorbis (13 MB to 2.4 MB) with PyAV |
| A-0006 | sprite | `assets/art/sunny_land_fox/` (12 files) | https://opengameart.org/content/sunny-land-2d-pixel-art-pack | Luis Zuno (ansimuz) | CC0 |  | no | no | 2026-10-22 | Player fox (idle, run, jump). Replaced the Kenney alien. |
| A-0007 | sfx | `assets/audio/sfx/jump.wav`, `assets/audio/sfx/coin.wav`, `assets/audio/sfx/fall.wav`, `assets/audio/sfx/land.wav` | made in this project with `tools/audio/sfx_synth.py` (recipes in `assets/audio/src/*.sfx.json`) | Coyote Hop | the game's own license |  | pre-generated | no | 2026-10-22 | Presets written by Claude (Opus 5.5), rendered by code; jump and coin volume lowered to match the old mix. Replaces A-0002, A-0003 |
| A-0008 | music | `assets/audio/music/theme.wav`, `assets/audio/music/goal.wav` | made in this project with `tools/audio/chiptune.py` (songs in `assets/audio/src/*.song.json`) | Coyote Hop | the game's own license |  | pre-generated | no | 2026-10-22 | Notes composed by Claude (Opus 5.5) as song files, rendered by code, 16-bar theme at 150 bpm plus goal fanfare. Replaces A-0004, A-0005 |

## Rules
- "AI-assisted?" uses one of: `no`, `dev-only` (AI helped, nothing AI-made ships), `pre-generated` (AI output ships in the build), `live` (generated at runtime). Steam's disclosure is built from the `pre-generated` and `live` rows (see SOP-04).
- Unknown license means it does not go in. Prototype-only (NC) assets are tagged `PLACEHOLDER` in Notes and replaced before release.
- Store the license text or a screenshot of the license page next to the asset or in `docs/licenses/`.
- AI-assisted: record tool, date, prompt summary, how much was edited by hand. Needed for store disclosure forms.
- Keep `CREDITS.md` generated from this table (see `/release-check`).

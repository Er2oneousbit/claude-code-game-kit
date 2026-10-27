# Resources: where to look for what

> Index only. Claude: when asked to find music, SFX, art, fonts, or tools, open the matching file below, suggest from it,
> then search the web for anything newer and label results "found live" vs "from the list".
> Licenses are the risk. The license on the specific asset page on the day you download it is the one that counts.
> Anything marked **(verify)** in these files was not live-checked.

## Start here (one safe default per need)
| Need | Default pick | Why | More options |
|---|---|---|---|
| Any license question | The cheat sheet | CC0 first, then CC BY, never NC in a release | `resources/licenses.md` |
| Music | `incompetech.com` (CC BY), make it in `LMMS` / `BeepBox`, or write a chiptune with `tools/audio/chiptune.py` | Big catalog, easy attribution, or zero license questions | `resources/audio.md` |
| SFX | `kenney.nl` audio (CC0), retro: `tools/audio/sfx_synth.py` or `jsfxr` | Safe license, instant results | `resources/audio.md` |
| 2D art | `kenney.nl` (CC0), palettes from `lospec.com` | Consistent style for prototypes | `resources/art.md` |
| 3D art | `kenney.nl`, `quaternius.com`, `polyhaven.com` (all CC0) | Kits that match each other | `resources/art.md` |
| Fonts | `fonts.google.com` (mostly OFL) | Ship the license file | `resources/art.md` |
| UI and icons | Kenney UI (CC0), `game-icons.net` (CC BY) | Credit game-icons | `resources/art.md` |
| Real terrain, roads, rivers | National elevation portal + OpenStreetMap (attribution) | Real landscape as a height grid | `resources/world-and-levels.md` |
| AI generators and MCP servers | Read the table, adopt one at a time with an ADR | Terms, pricing and output rights vary | `resources/ai-tools.md` |
| How others built whole games | Worked examples | Learn the order of work | `resources/pipelines.md` |
| Books, docs, talks, store pages | *Game Programming Patterns*, engine docs, GDC Vault | Fundamentals | `resources/learning-and-release.md` |

## Files
| File | What is in it |
|---|---|
| `resources/licenses.md` | License cheat sheet, AI content note |
| `resources/audio.md` | Music libraries, DAWs and trackers, SFX libraries, generators, editing, implementation |
| `resources/art.md` | 2D and 3D libraries and tools, AI 3D generators, UI, fonts, VFX and shaders |
| `resources/world-and-levels.md` | Real-world map data, level editors |
| `resources/ai-tools.md` | AI tools and MCP servers named in videos, each with caveats |
| `resources/pipelines.md` | Creature animation pipeline, prototype-then-art pipeline, one-week RTS, budget stack, workspace pattern |
| `resources/learning-and-release.md` | Books, docs, talks, marketing and release channels |
| `EVIDENCE.md` | Where every claim came from, graded A to X |
| `evidence/` | Raw video notes and field reports (archive, not rules) |

Prompt patterns for generators (images, 3D, voice, SFX, music, motion video) are in `docs/BRIEFS.md`, not here.

## How Claude should use these files
1. If the request is vague, ask what mood, genre, length, and loop behavior the asset needs.
2. Suggest 3 to 5 options from the right file, with license notes. Prefer CC0, then CC BY.
3. Search the web for anything newer or for a specific style, and mark results as "found live" or "from the list".
4. Before anything enters the repo, run `/asset-intake` (it logs to `docs/ASSET_LOG.md`).
5. New source or tool worth keeping: add a row to the right file and, if it changes a rule, a row in `EVIDENCE.md`.

## Add your own favorites
- (music)
- (sfx)
- (art)
- (tools)

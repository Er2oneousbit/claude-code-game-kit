# Scrap Tanks: Game Design Document

> Living document. Short beats complete. Update with `/gdd-sync` when reality diverges from this page.
> Last reviewed: 2026-10-21

## Identity
- **Working title:** Scrap Tanks (a codename is fine, do not spend time on the name yet)
- **One-line pitch:** A one-screen tank brawl in a scrapyard: your tractor-tank against raiders whose behavior tree you can read over their heads (flank, fire, cover, retreat).
- **Genre:** top-down arena shooter, wave survival
- **Perspective:** 3/4 top-down (55 degree camera), one fixed screen; 2D sprites rendered from 3D models
- **Reference games (2 to 3) and what you borrow from each:** Wii Play Tanks for shells and cover, Nuclear Throne for one-screen waves, XCOM for enemies that visibly take cover
- **The twist:** none, it is a kit example: every enemy shows the behavior-tree branch it is running, and the whole fight is engine-free C++ that plays in a unit test.

## Pillars (3 max)
Pillars decide arguments. If a feature does not serve one, it goes to the Parking lot.
1. **Cover is life**: shells stop at crates, rocks and trees; positioning beats twitch aim. Rules out hitscan weapons and see-through cover.
2. **Read the raiders**: each enemy shows its current intent (FLANK, FIRE, COVER, RETREAT) and only shoots what it can see. Rules out hidden aimbots.
3. **Short and replayable**: three waves, two to three minutes, R restarts. Rules out menus, upgrades and saves.

## Core loop
```
pick cover -> peek and trade shots -> a raider breaks or retreats (scrap drops) -> grab scrap to repair or push -> back to cover
```
Time per loop: 5 to 15 seconds. The fun must be present in this loop before anything else gets built.

Loop at three time scales (if you cannot fill all three, the game's structure is not clear yet):
| Scale | What the player does | Why they keep going |
|---|---|---|
| Every ~30 seconds | | |
| Every ~10 minutes | | |
| Whole session | | |

## Player fantasy and target audience
- Fantasy: 
- Audience: 
- Comparable games (2 to 3) and what we do differently: 

## Scope tiers
| Tier | Contents | Done means |
|---|---|---|
| **Toy** | Core mechanic playable in a gray box | Someone wants to keep playing for 2 minutes |
| **Vertical slice** | 1 polished level or loop, art, audio, UI, save | Looks and feels like the final game |
| **MVP / Release** | Minimum content that makes a shippable product | Passes `/release-check` |
| **Stretch** | Everything else | Only after release scope is locked |

Current tier: **Vertical slice** (built, bot-verified; human playtest pending)

Claude scopes work by this line (SOP-08 "Tiers"). Move it with `/next-tier` when the tier's "Done means" is met.

## Content list (MVP)
| Item | Count | Status |
|---|---|---|
| Levels / areas | | |
| Enemies / obstacles | | |
| Player abilities | | |
| Music tracks | | |
| SFX sets | | |

## Systems overview
List each system in one line and link to `ARCHITECTURE.md` for how it is built.
Mark which ones the **vertical slice** needs. Everything marked "no" waits, otherwise the AI invents assumptions you never tested.
| System | One line | In the vertical slice? |
|---|---|---|
| Health and damage | | yes |
| Weapons / abilities | | one only |
| Enemies and bosses | | 1 or 2 types, 1 boss |
| XP, skill trees, economy, world map, save | | no |

## Controls
| Action | Keyboard/Mouse | Gamepad |
|---|---|---|
| Drive (tank controls) | W/S forward and back, A/D turn | Left stick |
| Aim turret | Mouse | Right stick |
| Fire | Left mouse or Space | Right trigger or A |
| Restart | R | Start |

## Tunables that define feel
List the numbers that make the game feel right (gravity, jump height, coyote time, hit stop, camera lag).
These live in data, not code. File: `src/core/Tuning.hpp` (speeds, turn rates, reload, damage, sight range, waves).

## Art and audio direction
- Style, tone, and the kinds of enemies/NPCs the player sees: toy scrapyard: Kenney tractors with cannons, police-tractor raiders, one shovel-tractor heavy
- Palette / resolution / camera: `docs/CONCEPTS.md`; 1280x720 logical; fixed camera, 55 degrees
- Music mood and references (see `RESOURCES.md`): none in the slice
- SFX style: scrapyard sounds generated with ElevenLabs (placeholder, non-commercial terms): cannon booms (yours heavier), metal
  clangs, a crunchy explosion, a ratchet-and-clink pickup, a windy scrapyard loop
- Fill the style fragments in `BRIEFS.md` from this section.

## First-time user experience (FTUE, from E05 in `docs/EVIDENCE.md`)
Teach the mechanics by playing, not by a wall of text. Example from a shipped browser game: level 1 introduces the basic tool, level 2 forces the harder tool (a stain the basic tool cannot clear), level 3 adds the timer. Lock out advanced options until the lesson is passed.
| Lesson | Mechanic taught | How we know they got it |
|---|---|---|
| 1 | | |

## Platform and engine target
- Engine: see `ENGINE.md`. Storefront: <Steam first is the simple default; web (itch.io) or handheld targets change input and performance budgets>.
- Input: <keyboard + mouse / controller / both>

## Assumptions to test (feeds the vertical slice)
Write these BEFORE building so you know what the slice is for.
| Assumption | How we will know (observable) |
|---|---|
| The hook comes through in the first minutes | |
| The core mechanic feels good | |
| The art style works | |
| The setting carries a full game | |

## Risks and unknowns
| Risk | Why it matters | How we test it cheaply |
|---|---|---|
| | | |

## Out of scope (explicit)
- 

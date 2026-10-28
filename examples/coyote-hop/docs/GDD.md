# Coyote Hop: Game Design Document

> Living document. Short beats complete. Update with `/gdd-sync` when reality diverges from this page.
> Last reviewed: 2026-10-26

## Identity
- **Working title:** Coyote Hop (a codename is fine, do not spend time on the name yet)
- **One-line pitch:** A one-level speedrun platformer that exists to show how forgiving jump timing (coyote time, jump buffer) feels.
- **Genre:** 2D platformer, speedrun
- **Perspective:** 2D side
- **Reference games (2 to 3) and what you borrow from each:** Celeste for jump forgiveness, any speedrun game for the timer
- **The twist:** none, it is a kit example. The level is data and a test proves every gap is jumpable.

## Pillars (3 max)
Pillars decide arguments. If a feature does not serve one, it goes to the Parking lot.
1. **Jumps feel fair**: a jump that looked right works (coyote time, buffer). Rules out pixel-perfect gaps.
2. **Tiny and finished**: one level, one minute. Rules out menus, saves and more levels.
3. **Numbers in one place**: every tunable in `scripts/game/tuning.gd`. Rules out magic numbers in scripts.

## Core loop
```
run -> jump a gap -> land or fall (respawn, fall counter) -> next gap -> back to run
```
Time per loop: 1 to 2 seconds. The fun must be present in this loop before anything else gets built.

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

Current tier: **Toy, finished on purpose**. Art, audio and a HUD are in, but it stays a one-level kit example: no vertical slice is planned.

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
| Move left / right | A / D or the arrow keys | D-pad left / right |
| Jump (hold for the full height, tap for a short hop) | Space, W or Up | A (bottom face button) |
| Restart the run | R | none |
| Debug overlay (coyote and buffer time, velocity, on floor) | F1 | none |

## Tunables that define feel
List the numbers that make the game feel right (gravity, jump height, coyote time, hit stop, camera lag).
These live in data, not code. File: `scripts/game/tuning.gd`
- Run 120 px/s, ground acceleration 900 px/s^2, air 600 px/s^2
- Gravity 900 px/s^2, max fall 420 px/s, jump 340 px/s (apex about 67 px, 3.7 tiles), jump cut 0.45
- Coyote time 0.10 s, jump buffer 0.12 s
- Camera zoom 2x with position smoothing (snapped on respawn)

## Art and audio direction
- Style, tone, and the kinds of enemies/NPCs the player sees: 
- Palette / resolution / camera: 
- Music mood and references (see `RESOURCES.md`): 
- SFX style: 
- Fill the style fragments in `BRIEFS.md` from this section.

## First-time user experience (FTUE, from E05 in `docs/EVIDENCE.md`)
Teach the mechanics by playing, not by a wall of text. Example from a shipped browser game: level 1 introduces the basic tool, level 2 forces the harder tool (a stain the basic tool cannot clear), level 3 adds the timer. Lock out advanced options until the lesson is passed.
| Lesson | Mechanic taught | How we know they got it |
|---|---|---|
| 1 | | |

## Platform and engine target
- Engine: see `ENGINE.md`. Storefront: none, it is a kit example. `export_presets.cfg` exports Windows, Linux and Web.
- Input: keyboard and gamepad

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
- More levels, menus, saves and settings (pillar 2)
- Enemies, hazards other than falling, power-ups
- Key remapping, touch controls, online leaderboards

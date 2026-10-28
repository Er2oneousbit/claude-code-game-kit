# Ghost Lantern: Game Design Document

> Living document. Short beats complete. Update with `/gdd-sync` when reality diverges from this page.
> Last reviewed: 2026-10-21

## Identity
- **Working title:** Ghost Lantern (a codename is fine, do not spend time on the name yet)
- **One-line pitch:** A top-down dungeon escape where ghosts hunt you but fear your lantern, and the lantern is running out of oil.
- **Genre:** top-down action, short escape runs
- **Perspective:** 2D top-down, 16 px tiles
- **Reference games (2 to 3) and what you borrow from each:** Pac-Man for ghosts with readable personalities, Luigi's Mansion for light as the weapon, Darkwood for the shrinking circle of safety
- **The twist:** the lantern is both shield and timer. Brighter keeps ghosts away but burns oil faster.

## Pillars (3 max)
Pillars decide arguments. If a feature does not serve one, it goes to the Parking lot.
1. **Readable ghosts**: you can tell what a ghost is about to do (color and motion tell its mood). Rules out random, twitchy AI.
2. **Light is the resource**: every choice is about oil. Rules out weapons, health packs, a second resource.
3. **One more run**: a run lasts a minute or two, and after a death one key (R) restarts the room instantly. Rules out long levels, saves, lives.

## Core loop
```
move through dark rooms -> ghosts react to your light -> grab oil or the key, or get caught -> choose: brighten (safe, costly) or dim (cheap, risky) -> back to move
```
Time per loop: 5 to 10 seconds. The fun must be present in this loop before anything else gets built.

Loop at three time scales (if you cannot fill all three, the game's structure is not clear yet):
| Scale | What the player does | Why they keep going |
|---|---|---|
| Every ~30 seconds | Cross a room past one or two ghosts | Oil pickups and the next door |
| Every ~10 minutes | Clear the slice's three rooms, retry after a catch | Beat your time and oil left |
| Whole session | (slice: one sitting) | Out of scope until the slice is fun |

## Player fantasy and target audience
- Fantasy: the last light in a haunted place; you are weak, the dark is not
- Audience: browser players with five minutes, game-jam crowd; keyboard first 
- Comparable games (2 to 3) and what we do differently: 

## Scope tiers
| Tier | Contents | Done means |
|---|---|---|
| **Toy** | Core mechanic playable in a gray box | Someone wants to keep playing for 2 minutes |
| **Vertical slice** | 1 polished level or loop, art, audio, UI, save | Looks and feels like the final game |
| **MVP / Release** | Minimum content that makes a shippable product | Passes `/release-check` |
| **Stretch** | Everything else | Only after release scope is locked |

Current tier: **Toy**

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
| | | |

## Tunables that define feel
List the numbers that make the game feel right (gravity, jump height, coyote time, hit stop, camera lag).
These live in data, not code. File: `<path to tuning data>`

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

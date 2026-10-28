# Courier Dash: Game Design Document

> Living document. Short beats complete. Update with `/gdd-sync` when reality diverges from this page.
> Last reviewed: 2026-10-26

## Identity
- **Working title:** Courier Dash (a codename is fine, do not spend time on the name yet)
- **One-line pitch:** A 90-second 3D delivery dash: carry parcels across a tiny town one at a time while a patrol robot you can read (and dodge) guards the streets.
- **Genre:** 3D arcade, stealth-lite, score attack
- **Perspective:** 3D third person, fixed-angle chase camera (high and behind, never rotates)
- **Reference games (2 to 3) and what you borrow from each:** Crazy Taxi for the run-the-clock delivery loop, Metal Gear's guard "!" for a robot you can read, Pac-Man for patrol routes you learn
- **The twist:** none, it is a kit example: the whole run (rules, robot, bots) is engine-free TypeScript, so the scenario pair also runs as unit tests.

## Pillars (3 max)
Pillars decide arguments. If a feature does not serve one, it goes to the Parking lot.
1. **Read the robot**: its state always shows (light color, "!" tell, sound) and it can only chase what it saw (inside its cone, not through buildings, after the "!" pause). Touching it always ends the run, seen or not. Rules out instant detection and hidden rolls.
2. **Every second counts**: one parcel at a time, a 90 s clock, sprint is a limited resource. Rules out inventories and upgrades.
3. **One more run**: a run lasts 1 to 2 minutes and R restarts at once. Rules out menus, saves and loading between runs.

## Core loop
```
pick a parcel -> route past the robot -> deliver at the flag (+1, chime) -> next parcel or a risky shortcut -> back to pick
```
Time per loop: 10 to 20 seconds. The fun must be present in this loop before anything else gets built.

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
| Move | WASD or arrow keys | Left stick or D-pad |
| Sprint (uses stamina) | Shift | A or right trigger |
| Restart run | R | Start |

## Tunables that define feel
List the numbers that make the game feel right (gravity, jump height, coyote time, hit stop, camera lag).
These live in data, not code. File: `src/core/tuning.ts` (walk and sprint speed, stamina, robot speeds, sight cone, alert time, run length).

## Art and audio direction
- Style, tone, and the kinds of enemies/NPCs the player sees: bright toy-town, Kenney mini characters and suburban kit; one patrol rover with a colored state light
- Palette / resolution / camera: `docs/CONCEPTS.md` color bible; full window; fixed high chase camera
- Music mood and references (see `RESOURCES.md`): none in the slice
- SFX style: toy-town sounds generated with ElevenLabs (placeholder, free plan): a cardboard thump and chime for pickup, a
  doorbell for delivery, a toy-robot buzz when caught, a wooden clock tick in the last 10 s, a calm town ambience loop
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

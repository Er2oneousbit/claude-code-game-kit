# Graveyard Shift: Game Design Document

> Living document. Short beats complete. Update with `/gdd-sync` when reality diverges from this page.
> Last reviewed: 2026-10-21

## Identity
- **Working title:** Graveyard Shift (a codename is fine, do not spend time on the name yet)
- **One-line pitch:** A night in a haunted graveyard: gather twelve lost souls and slip out the gate before dawn, choosing every moment whether to light your lantern (fast, but seen) or creep in the dark (hidden, but slow).
- **Genre:** 3D stealth, score attack
- **Perspective:** 3D third person, high fixed camera behind the keeper
- **Reference games (2 to 3) and what you borrow from each:** Thief for light as a liability, Pac-Man for ghosts on readable routes, Luigi's Mansion for the lantern-in-the-dark mood
- **The twist:** every night is a new graveyard (generated from a seed, shown on the HUD, replayable with `--seed N`); the first night is the hand-made yard. It is also a kit example: the scene is built from code, the nights run as Unity PlayMode tests (8 hand-made and 8 generated), and the shipped player replays a test night exactly.

## Pillars (3 max)
Pillars decide arguments. If a feature does not serve one, it goes to the Parking lot.
1. **Light is a choice**: lit you move fast and see far, but ghosts notice you from 9 m; dark you creep, nearly invisible. Rules out a lantern that is always right.
2. **Read the ghosts**: every ghost glows its state (blue patrol, yellow suspicious or searching, red hunting) and pauses with a "?" before a hunt. Rules out instant detection.
3. **One more night**: a night is under three minutes, getting caught costs time not the run, R restarts, and the next night is a yard you have not seen. Rules out saves mid-night and long losses.

## Core loop
```
pick the next soul -> light or dim -> slip past a ghost (or get caught: back to the gate, a soul slips away) -> soul collected -> back to pick
```
Time per loop: 10 to 25 seconds. The fun must be present in this loop before anything else gets built.

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

Current tier: **Vertical slice** (built, bot-verified; one user playtest, 2026-10-23; outside playtests pending)

Claude scopes work by this line (SOP-08 "Tiers"). Move it with `/next-tier` when the tier's "Done means" is met.

## Content list (MVP)
| Item | Count | Status |
|---|---|---|
| Levels / areas | 1 hand-made yard (night 0, about 4,400 m2, three wings) plus a generated yard per later night (a main body and 1 to 3 wings, 4,000 to 5,200 m2; `Assets/Scripts/Core/LevelGenerator.cs`, SOP-17) | Built; 250 night seeds pass every invariant (EditMode); at Normal the bots' careful keeper escapes 5 of 8 generated nights, always lit 0 |
| Enemies / obstacles | Ghosts: one per patrol loop (typically 8), plus 2, 4 or 6 on Normal, Hard, Insane | Built |
| Difficulty | Easy (the original light), Normal (darker), Hard, Insane (only the lantern lights the yard) | Built; how dark is too dark is a playtest question |
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
| Move | WASD or arrows | Left stick |
| Lantern on or off | Space or F | Y (button 3) |
| Restart night | R | Start |

## Tunables that define feel
List the numbers that make the game feel right (gravity, jump height, coyote time, hit stop, camera lag).
These live in data, not code. File: `Assets/Config/SO_GraveyardSetup.asset` (Inspector), defaults in `Assets/Scripts/Core/GameTuning.cs` (`dev.py exec SceneBuilder.ResetTuning` copies them over).

## Art and audio direction
- Style, tone, and the kinds of enemies/NPCs the player sees: cosy-spooky Kenney graveyard: the keeper, three ghosts, crypts, gravestones, pines
- Palette / resolution / camera: `docs/CONCEPTS.md`; night blues, warm lantern, cyan souls; fixed high camera
- Music mood and references (see `RESOURCES.md`): music box and celesta over a low cello drone, "cute creepy": two Suno takes that alternate per night (brief in `BRIEFS.md`)
- SFX style: soft, slightly magical, generated with ElevenLabs: a glassy chime per soul, a startled ghostly gasp when a ghost notices, a shriek when caught; a night ambience loop (wind, crickets, owl) under everything; in the world, each soul whispers where it floats, each ghost moans louder as it grows wary, footsteps and a lantern crackle follow the keeper
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

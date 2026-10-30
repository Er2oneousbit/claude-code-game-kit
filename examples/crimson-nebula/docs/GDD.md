# Project_Crimson_Nebula: Game Design Document

> Living document. Short beats complete. Update with `/gdd-sync` when reality diverges from this page.
> Last reviewed: 2026-10-28. Written from the make-a-game interview; *(Claude's pick)* marks what Claude chose.

## Identity
- **Working title:** Project_Crimson_Nebula (codename)
- **One-line pitch:** A neon-night kart racer where the track rewrites one section every lap: spot the change first,
  take the new line, boost past the pack.
- **Genre:** Arcade kart racer with items
- **Perspective:** 3D, chase camera behind the kart
- **Reference games (2 to 3) and what you borrow from each:** Mario Kart: readable item boxes, close pack racing, a
  race anyone can follow.
- **The twist:** the track changes each lap (a shortcut opens, a lane closes, a ramp appears). Changes are seeded, so a
  race replays exactly.

## Pillars (3 max)
Pillars decide arguments. If a feature does not serve one, it goes to the Parking lot.
1. **Read the change**: every change glows its warning before you reach it; the driver who spots it first gains.
   Rules out: changes that pop in under your wheels, changes you cannot see coming.
2. **Close and loud**: the pack stays within striking distance; near misses, last-corner passes. Rules out: runaway
   leads, long empty straights.
3. **Neon tells you everything**: color is information (the new route glows, closed lanes flash red, item boxes
   pulse). Rules out: decoration that hides the racing line.

## Core loop
```
spot the glowing change ahead -> pick a line (maybe burn the boost) -> gain or lose places -> the next lap rewrites another section -> back
```
Time per loop: one section, about 10 seconds; one lap about 40 seconds *(Claude's pick)*.

Loop at three time scales:
| Scale | What the player does | Why they keep going |
|---|---|---|
| Every ~30 seconds | Reads a changed section, picks old or new line, grabs an item box | Gaining a place on a good read |
| Every ~10 minutes | Races a few 3-lap races on different seeds | Winning (1st place) to unlock |
| Whole session | Works through unlocks (karts, tracks, item types) | The next unlock |

## Player fantasy and target audience
- Fantasy: the sharp-eyed racer who sees the shortcut before anyone else.
- Audience: the developer and friends; races should feel frantic.
- Comparable games (2 to 3) and what we do differently: Mario Kart (fixed tracks; here they change every lap).

## Scope tiers
| Tier | Contents | Done means |
|---|---|---|
| **Toy** | One looping neon track, you + 3 AI karts, 3 laps; one section changes per lap with a ~2 s warning glow; item boxes give one item (boost); results screen with the finishing order | Someone wants to keep playing for 2 minutes |
| **Vertical slice** | 1 polished track with several change types, more items, art, audio, UI | Looks and feels like the final game |
| **MVP / Release** | A few tracks, unlocks for 1st place (karts, tracks, item types), menus, music | Passes `/release-check` |
| **Stretch** | Everything else (split-screen, online) | Only after release scope is locked |

Current tier: **Toy**

Claude scopes work by this line (SOP-08 "Tiers"). Move it with `/next-tier` when the tier's "Done means" is met.

## Content list (MVP)
| Item | Count | Status |
|---|---|---|
| Levels / areas | 1 track for the toy, 3 to 4 for release *(Claude's pick)* | not started |
| Enemies / obstacles | 3 AI rival karts; changing sections | not started |
| Player abilities | drive, drift, use item | not started |
| Music tracks | 0 for the toy; synthwave later | not started |
| SFX sets | placeholders from `tools/audio/sfx_synth.py` | not started |

## Systems overview
| System | One line | In the toy? |
|---|---|---|
| Kart driving | Arcade handling: accelerate, steer, brake, drift | yes |
| Track | A loop of sections, each with a base layout and change variants | yes |
| Track changes | Seeded schedule: which section changes on which lap, telegraphed ~2 s ahead | yes |
| Laps and positions | Checkpoints, lap count, race order, finish | yes |
| Items | Item boxes, one held item, boost only | yes |
| Rival AI | Follow a racing line, take or skip the changed route, use the boost | yes |
| HUD and results | Position, lap, item; finishing order | yes |
| Unlocks, menus, music, more items | | no |

## Controls
| Action | Keyboard/Mouse | Gamepad |
|---|---|---|
| Accelerate | W / Up | Right trigger *(Claude's pick)* |
| Brake / reverse | S / Down | Left trigger |
| Steer | A D / Left Right | Left stick |
| Drift (hold) | Shift | Right bumper |
| Use item | Space | A (south button) |

## Tunables that define feel
Kart top speed, acceleration, steering rate, grip, drift charge, boost strength and time, AI speed spread, warning
time before a change. These live in one constants module, not scattered: `src/logic/tuning.rs`.

## Art and audio direction
- Style, tone: neon night. A dark track with glowing edges, synthwave colors. Changes light up as they happen.
- Palette / resolution / camera: dark blue-black ground, magenta and cyan edges, red for closed lanes, a bright new-route
  glow *(Claude's pick)*; chase camera behind and above the kart.
- Music mood and references: synthwave (later tier).
- SFX style: synthy placeholders (engine hum, boost whoosh, item pickup).
- First version: karts built in code from simple shapes (body, four wheels, a driver), not bare cubes.

## First-time user experience (FTUE, from E05 in `docs/EVIDENCE.md`)
| Lesson | Mechanic taught | How we know they got it |
|---|---|---|
| 1 | Lap 1 has no change: just driving and an item box | They finish lap 1 and use the boost |
| 2 | Lap 2's first change is a lane closing with a long warning | They switch lanes before the closure |

## Platform and engine target
- Engine: see `ENGINE.md` (Bevy 0.20). Storefront: none yet; Windows desktop first.
- Input: keyboard and gamepad.

## Assumptions to test (feeds the vertical slice)
| Assumption | How we will know (observable) |
|---|---|
| Changes read in time at speed | A bot that follows the glowing new line beats one that ignores it over 20 seeds; playtesters say "I saw it coming" |
| A change is a choice, not just an obstacle | The new route is faster but riskier; bots split on it, and it is not always right to take it |
| Win-only unlocks feel fair | AI catch-up comes from the track and items, never from secretly faster AI; a clean race wins |

## Risks and unknowns
| Risk | Why it matters | How we test it cheaply |
|---|---|---|
| Kart handling feels bad | Nothing else matters if driving is not fun | Tune in the toy first; play before adding changes |
| Changes are unreadable from a chase cam | Pillar 1 fails | Warning glow time as a tunable; the bot pair plus a playtest question |
| Rubber-band AI feels cheap with win-only unlocks | Players quit | AI speed spread as a tunable; log the gap at the finish |

## Out of scope (explicit)
- Split-screen and online multiplayer (solo against AI until the racing is fun)
- For the toy only: more items, unlocks, menus, music

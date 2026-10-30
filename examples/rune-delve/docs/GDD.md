# Rune Delve: Game Design Document

> Living document. Short beats complete. Update with `/gdd-sync` when reality diverges from this page.
> Last reviewed: 2026-10-22

## Identity
- **Working title:** Rune Delve (a codename is fine, do not spend time on the name yet)
- **One-line pitch:** A rune-mage clears three orc-held rooms of a dungeon with three spells, where a ward timed to an orc's wind-up beats any amount of spell spam.
- **Genre:** top-down action, room clearer
- **Perspective:** 3D, high top-down camera that follows the mage
- **Reference games (2 to 3) and what you borrow from each:** Hades for readable telegraphs and short rooms, Diablo for top-down spell casting, Sekiro for a well-timed block that turns defence into offence
- **The twist:** none, it is a kit example: every ability, effect and attribute is Gameplay Ability System C++ (no Blueprints), the content is imported and the map made by headless editor Python, and two autoplay bots test the main pillar.

## Pillars (3 max)
Pillars decide arguments. If a feature does not serve one, it goes to the Parking lot.
1. **Timing beats spam**: the ward blocks one swing and staggers the orc (double damage) if it meets a wind-up; spammed, it wastes mana and leaves you open. Bolts cost mana. Rules out a best button.
2. **Read the orcs**: an orc raises its weapon and glows before every swing, sleeping orcs wake to bolt noise or a hit, and a "!" shows when one has spotted you. Rules out unreadable hits.
3. **One more delve**: three rooms in about three minutes, death restarts the delve, R restarts any time. Rules out long runs and saves mid-delve.

## Core loop
```
pick a target -> bolt from range -> an orc winds up next to you -> ward (stagger, burst it down) or dash away -> room cleared, gate opens, health back -> next room
```
Time per loop: 3 to 8 seconds per exchange, about a minute per room. The fun must be present in this loop before anything else gets built.

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
| Move | WASD | Left stick |
| Aim | Mouse | Right stick |
| Bolt | Left mouse | Right trigger |
| Ward | Right mouse | Left trigger |
| Dash | Space | A (south button) |
| Restart delve | R | Start |

## Tunables that define feel
List the numbers that make the game feel right (gravity, jump height, coyote time, hit stop, camera lag).
These live in data, not code. File: `Config/DefaultGame.ini`, section /Script/RuneDelve.RDTuning (a `UDeveloperSettings` class, also under Project Settings > Game > Rune Delve Tuning).

## Art and audio direction
- Style, tone, and the kinds of enemies/NPCs the player sees: chunky low-poly Kenney Mini Dungeon: stone rooms, torches, barrels; orc grunts and one big orc warden
- Palette / resolution / camera: `docs/CONCEPTS.md`; warm torchlight on grey stone, blue rune-light for spells, red for danger; top-down camera
- Music mood and references (see `RESOURCES.md`): none in the slice
- SFX style: dark-fantasy sounds generated with ElevenLabs (placeholder, non-commercial terms): an arcane zap per bolt, a shimmer
  for the ward, a clang when a ward blocks, orc grunts and swings, a dungeon drip-and-rumble loop
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

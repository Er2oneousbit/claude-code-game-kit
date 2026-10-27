# Vertical Slice Brief

> The smallest playable build that tests the assumptions in `GDD.md`. Not the whole game.
> Why this works: a design doc is the source of truth, and a small slice gets real feedback before you scale (F2, F4 in `docs/EVIDENCE.md`).
> Worked example from a creator series: `docs/resources/pipelines.md`; raw notes: `docs/evidence/field-reports.md`.

## Why a brief
"Build me a Zelda-like" makes the AI fill every gap with its own assumptions, so you get its game, not yours.
The GDD plus this brief gives it the context to build the one thing you want to test.

## Fill this in
- **Slice name:** First Delve
- **Assumptions it tests (copy from GDD):** (1) a well-timed ward beats spamming every spell; (2) wind-ups and the "!" make orcs readable; (3) a three-room delve invites another
- **In scope (be stingy):** three rooms with gates, the mage (move, aim, bolt, ward, dash), health and mana, orc grunts and an orc warden with telegraphed swings, sight and hearing, room-clear heal, HUD, a few sounds
- **Out of scope:** loot, levelling, more spells, menus, music, saves, a settings screen
- **Debug tools in scope:** command line `-autoplay=weaver|masher`, `-seed=N`, `-god`, `-debugai` (orc states over heads); console variable `rd.DebugAI`
- **Done when (observable):** a player can clear three rooms and the warden or die, and restart; check, test and smoke pass; a packaged build runs a delve
- **How we judge it:** does the hook come through, is it fun, does the art and tone work, does the new mechanic work

## Prompt to paste (adapt the brackets)
```
Before you write any code, read docs/GDD.md, docs/CONCEPTS.md and docs/VERTICAL_SLICE.md. If anything is unclear or you
would have to assume something, ask me questions first. Wait for my answers.

Then build the vertical slice described there, and ONLY that. Use placeholder art: pixel-art sprites drawn with tools/art/pixel_sprite.py (check must pass), never dots or bare shapes.
Follow docs/sop/SOP-01.
Test as you go with `python tools/dev.py check`, `test`, and `smoke` after each step. Do not add systems that are out of scope.
Include the debug tools listed in the brief, behind a debug flag.
When it runs, play it yourself where you can, take screenshots from several angles, and run the SOP-09 interaction smoke checklist.

When done: list what is built, what you assumed, what is NOT built, how to run it, and a proposed next step.
```

## Answering the clarifying questions
- Getting questions back is good: the AI understood the assignment. Answer fast; it is a prototype.
- Say "use your best judgment" where you do not care. Be precise only where the test depends on it, above all **controls** (keys and gamepad).
- **Death rule:** prefer "restart the current room" unless the death rule is what you are testing. Full resets feel bad in play (E09).

## First build review
- Expect crude placeholder art and code-made sounds. Judge the loop, not the look.
- Typical first-pass problems: enemies too tough, no health drops, weak puzzle, death sends you too far back.
- Take notes while you play, then `/playtest-report` turns them into tasks.

## Art in parallel with mechanics
Mechanics feedback and art generation are independent. Ask Claude for the **asset pack request** in `docs/BRIEFS.md` (character first, then actions,
enemies, tiles, UI), paste each block into the generator, bring results back through `/asset-intake`.
Integration: one `assets/` folder by type, file names exactly as in the prompt pack, `tools/art/chroma_key.py` for magenta backgrounds,
log every file in `ASSET_LOG.md`, then ask Claude to wire it in and **playtest immediately**: animations, draw order, and difficulty usually break here.

## The loop after the slice
1. Play it. Log notes with `/playtest-report`.
2. Mark each GDD assumption confirmed, refuted, or unknown in the table below.
3. Describe each gap as an observable problem ("needed two more rooms to feel progression").
4. Send gaps back, patch, repeat. Plan several rounds before scaling.
5. Only then expand systems, art, and music (`SOP-08`), one mechanic at a time: add it, play until the game is fun
   again, and find how it combines with what is there before adding the next (tip, E49). Art and animation come last.

## Results log
| Round | Date | Assumptions confirmed | Assumptions refuted | Next change |
|---|---|---|---|---|
| 1 | 2026-10-22 | none: one seed, both bots died in room 2 | (1) as built: the ward (0.9 s) outlasted the wind-up (0.6 s), so a ward raised early still blocked | Ward 0.45 s inside a 0.7 s wind-up, ward cooldown 2 s |
| 2 | 2026-10-22 | (1) partly: over 8 seeds weaver 41, masher 23 of 80 | (3): nobody cleared a delve | Grunts 12 damage, mana regen 12, room-clear heal 60 |
| 3 | 2026-10-22 | (1): weaver 62, masher 56; the warden stopped both bots | (3) still: weaver 2/8 clears | Warden 180 health, 1.4 s recovery (the stagger window matters) |
| 4 | 2026-10-22 | (1): weaver 71, masher 55 of 80; full clears 5/8 against 0/8; the masher's wards met no swing in any run | none | (2) and (3) need human players: is a 0.45 s ward window fair by eye? |
| 5 | 2026-10-26 | (1) after the review fixes (a ward now stops one swing, as designed): weaver 65, masher 55 of 80; clears 3/8 against 0/8 | none, but the gap sits exactly on the test's thresholds (10 and 3) | Not retuned; the next tuning pass should restore a margin over the thresholds |

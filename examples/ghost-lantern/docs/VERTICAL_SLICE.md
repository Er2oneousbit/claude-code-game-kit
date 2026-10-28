# Vertical Slice Brief

> The smallest playable build that tests the assumptions in `GDD.md`. Not the whole game.
> Why this works: a design doc is the source of truth, and a small slice gets real feedback before you scale (F2, F4 in `docs/EVIDENCE.md`).
> Worked example from a creator series: `docs/resources/pipelines.md`; raw notes: `docs/evidence/field-reports.md`.

## Why a brief
"Build me a Zelda-like" makes the AI fill every gap with its own assumptions, so you get its game, not yours.
The GDD plus this brief gives it the context to build the one thing you want to test.

## Fill this in
- **Slice name:** Three Dark Rooms
- **Assumptions it tests (copy from GDD):** (1) ghosts that fear light are readable and fun to dodge; (2) brighten-vs-dim is a real choice; (3) a run of one to two minutes makes you want another
- **In scope (be stingy):** one map of three connected rooms, the wizard with a lantern (oil drains, brighter drains faster), one ghost type with utility AI (chase, flee the light, wander) and A* pathing, oil pickups, a key, an exit door, caught = restart the run, sounds for pickup, catch and win
- **Out of scope:** more ghost types, menus, saves, music, multiple levels, combat, health
- **Debug tools in scope:** behind `?debug`: draw ghost paths and their current top-scoring action, infinite oil (key I), ghosts frozen (key G). Plus an `?autoplay` bot for smoke tests (F7).
- **Done when (observable):** a player can start, reach the key and the exit through three rooms, get caught or win, and restart; `check`, `test`, `smoke` pass
- **How we judge it:** does the hook come through, is it fun, does the art and tone work, does the new mechanic work
- **When it is done:** run `/next-tier`. It checks the evidence and, on a yes, starts production (`docs/PRODUCTION.md`).

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
| 1 | 2026-10-21 | (2) brighten-vs-dim is a real choice: with the lantern the bot escapes on 6/6 seeds (37 to 48 oil left, two pickups needed), without it it is caught on 6/6 | none yet | (1) and (3) need human players: readability and "one more run" |

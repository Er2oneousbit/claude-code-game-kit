# Your First 60 Minutes on a New Game

> The order of work that most of the reviewed videos followed in some form (F2, F3, F4 in `docs/EVIDENCE.md`). Do it once per new game.
> Commands say `python`; on macOS and Linux use `python3` if `python` is missing.
> Times are rough. Skip nothing; shorten anything.

## Fast lane: something playable in your first session
First game, or you want to feel the idea before planning it? Do this first, then the full route below. The toy becomes
the first test of your idea, and nothing here is wasted.
1. **Health check.** Say: "Run doctor and fix what it finds." Wait for green.
2. **Ask for a toy, not a game.** Say: "Make <your idea in one line> playable as a tiny toy: one screen, the main
   action, placeholder characters made for this game (2D: pixel art drawn with tools/art/pixel_sprite.py; 3D: simple
   modeled figures from a few shapes, such as a kart with wheels and a driver; never dots or bare boxes), no menus. Put the numbers I might tweak in one place." Claude plans in pseudocode,
   builds it, and runs `check` and `test`.
3. **Play it and take notes.** Say "run the game" (or run `python tools/dev.py run`; Unity and Unreal open the editor: press Play there). Play for a few minutes and write
   down what you like and what you don't, in plain words: "the jump is floaty", "too easy", "I can't see the enemies",
   "love the sound". Paste the notes back to Claude: it logs them (`/playtest-report`) and fixes the top one first.
4. **Two or three rounds** of play, complain, adjust. Then say: "Write what we learned into the GDD", and carry on with
   step 2 of the full route. (Made with the kit's interview? `docs/GDD.md` already holds your approved plan: skip
   the brainstorm and the identity block, review the GDD instead, and go on from References.)
Still true in the fast lane: mechanics before art, and never "make the whole game" in one prompt (see the rules below).

## Full route
| Min | Step | Output | Where |
|---|---|---|---|
| 0 to 5 | **Engine setup and health check.** Follow "Version and setup" in `docs/ENGINE.md` (Godot: install GUT, run `python tools/dev.py import` once), write the exact engine version there, run `python tools/dev.py doctor` until green. Then `claude` and `/start-session`. | Green doctor, a session that knows the project | `docs/ENGINE.md` |
| 5 to 15 | **Brainstorm.** "Give me five concepts for [genre or idea] that suit [engine] on [my hardware]. Then I pick one and you deepen it: mechanics, enemies, look, what to cut." Name the engine and tools in the first message. | One chosen concept with a deeper pass | chat |
| 15 to 25 | **GDD identity block.** Pitch in one line, 3 pillars, core loop at 30 seconds, 10 minutes, a session. Assumptions to test. | Filled top of `GDD.md` | `docs/GDD.md` |
| 25 to 35 | **References.** Collect 3 to 5 mood images or screenshots, generate 2 to 4 in-game mockups (a paid generator only after the Budget check row and a priced first take, `/gen-brief`), lock one FINAL per scene. Write the color bible. | Locked concepts, palette | `docs/CONCEPTS.md`, `docs/BRIEFS.md` style fragments |
| 35 to 45 | **Slice brief.** In scope, out of scope, debug tools, done-when. Be stingy. | Filled brief | `docs/VERTICAL_SLICE.md` |
| 45 to 50 | **Budget check.** Which effort level, how much of the weekly limit you can spend, credit caps on generator APIs. | First row of the "Budget and cost log" in `ROADMAP.md` | `docs/sop/SOP-12-job-plan-and-model-roles.md` |
| 50 to 60 | **Kick off.** Paste the slice prompt from `VERTICAL_SLICE.md`. Answer its questions fast. Let it build with placeholders. | First playable slice in progress | `docs/sop/SOP-01-feature-workflow.md` |

## Rules that save the most pain
- **No whole-game prompts.** The slice first. Rework after a vague one-shot cost one creator 1.5 hours (E26).
- **Show, do not describe.** References and mockups beat paragraphs (F3).
- **Mechanics before art.** Placeholders until the loop is fun (F4): plain tiles for levels, placeholder pixel-art sprites
  for characters and key objects (`tools/art/pixel_sprite.py`, never dots; 3D: figures built from simple shapes). If it is not fun with crude figures, polished art will not save it.
- **Grow one toy at a time.** Add one mechanic, play until it is fun again, then the next. Combine new toys with old ones so
  they play off each other. Never add three at once (tip, E49).
- **Tell Claude your machine.** GPU, RAM, target platform. It sizes the graphics to fit (E27).
- **Know what breaks.** Interaction bugs are the norm: run the `SOP-09` interaction smoke checklist on every build (F1).
- **Do not clone.** Learn from famous games, ship your own (`SOP-04`).

## After the first hour
- Play the slice, `/playtest-report`, iterate (`VERTICAL_SLICE.md`, "The loop after the slice").
- Plan the rest as jobs with tests (`SOP-12`), one fresh session each.
- Art and audio prompts: `/gen-brief`. Sources: `docs/RESOURCES.md`.

# Brief: procedural generation, as a kit skill proven on Graveyard Shift

Run with the `/goal` line in `PROCGEN_GOAL.txt`. This file is the brief; the goal line is the definition of done.

## Why
Graveyard Shift plays the same hand-made yard every night (`Level.Graveyard()` in
`examples/graveyard-shift/Assets/Scripts/Core/Level.cs`; the seed only moves the ghosts' start). The owner wants each
night to be a new graveyard, and the kit has no guidance for procedural generation. Build the guidance as a skill
backed by a SOP, the way `/game-ai` is backed by SOP-14, and prove it on Graveyard Shift the way SOP-14 was proven
there. The hard part of procedural levels is not making them, it is proving every one is fair: that is the center of
both deliverables.

## Read first
- Root `CLAUDE.md` (the kit's rules: evidence grades, no em dashes, header blocks, the dev.py contract, the scaffold-time
  paths that make the kit-root link check report about 71 hits).
- `core/docs/sop/SOP-14-game-ai.md` and `core/.claude/skills/game-ai/SKILL.md`: the shape to follow.
- `core/docs/EVIDENCE.md` (how sources are graded and cited) and `core/docs/evidence/video-notes.md`.
- Graveyard Shift, in `examples/graveyard-shift/`: README.md, HOW_IT_WAS_MADE.md (section 6 defines the bot trio and
  the pillar result), Assets/Scripts/Core/Level.cs, Assets/Scripts/Game/LevelBuilder.cs and GraveyardGame.cs, and the
  EditMode and PlayMode tests.
- `CLAUDE.local.md` for the Unity editor path.

## Deliverables
1. **Evidence.** Find and actually read (WebFetch, URL recorded) at least three sources on practical procedural level
   generation; at least two must earn grade A or B under the kit's rules, because only those can back SOP rules.
   Candidates to check, not to assume: Shaker, Togelius and Nelson, *Procedural Content Generation in Games* (Springer
   2016, free at pcgbook.com); Derek Yu on Spelunky's level generator; Kate Compton's GDC talk on practical procedural
   generation; Red Blob Games; Boris the Brave. Summarize each into `core/docs/evidence/video-notes.md` (or the notes
   file EVIDENCE.md points to) and add `E##` rows to `core/docs/EVIDENCE.md`.
2. **SOP-17**, a new file core/docs/sop/SOP-17-procedural-generation.md, shaped like SOP-14: goal, when to use it (and when a
   hand-made level is the better answer), steps, engine notes, done when, common mistakes. Every rule cites an `E##`
   source graded A or B, or `K01` (this kit's own tests, i.e. what the Graveyard work proves); everything weaker is a
   labelled tip. Steps that must be in it: write the invariants (what every level must satisfy) before the generator;
   one seed in, the same level out, shown on screen and reproducible from the command line; generate, validate,
   reject and retry with a capped number of attempts and a hand-made fallback; property tests over many seeds;
   bot playthroughs over generated levels (SOP-14 step 6); a bad seed found becomes a regression test.
3. **Skill** `core/.claude/skills/procgen/SKILL.md`, shaped like `game-ai`, pointing at SOP-17. Update every place that
   lists or counts skills (root `CLAUDE.md` "15 skills", `README.md` skills line, `core/CLAUDE.md`, `core/docs/sop/README.md`
   if it indexes SOPs), so the counts and lists are right.
4. **Graveyard Shift generates its nights.**
   - An engine-free generator in `Assets/Scripts/Core/` (no UnityEngine types, like the rest of Core):
     `LevelGenerator.Generate(int seed)` returns a `Level`. Seed 0 returns the hand-made yard (`Level.Graveyard()`), so the
     existing tests and the bot trio's hand-made baseline keep their meaning.
   - Normal play uses a new seed each night (derived so that it is reproducible, for example from the nights played),
     shown on the HUD; `--seed N` replays a night exactly, as now.
   - Invariants (refine them, then write them down in the SOP's worked example): the six souls are reachable on foot
     from the keeper's start; souls are spread out (a minimum distance apart and from the start); every soul has
     cover within reach so dark sneaking is possible; the gate is reachable; each of the three ghost routes is a closed
     loop on walkable ground and does not start on top of the keeper; no prop overlaps another, the start, the gate or
     a soul. Keep the existing level validation tests and make them run over generated levels too.
   - EditMode property tests: at least 200 seeds, every invariant, printing the count of seeds checked.
   - Fairness by bots: run the existing trio (careful, dark, lit; HOW_IT_WAS_MADE section 6) over at least 8
     generated seeds and print the escape counts per bot. The pillar result must hold on generated nights (careful
     escapes more than lit) or the run must tune the generator until it does, or stop and report why not.
   - Three screenshots of three different generated yards (the Unity smoke capture options or `GameKitCapture`),
     paths printed.
5. **Docs.** Graveyard Shift: a section in its HOW_IT_WAS_MADE.md (what is generated, the invariants, seeds tested, what the
   checks caught), README and GDD updated, the Verified table updated with real numbers. Kit: `CHANGELOG.md` entry
   under the unreleased version, README tested table row for the skill's worked example.

## Constraints
- Do not commit or push: the owner commits. Before changing Graveyard Shift, back it up:
  `robocopy` or a Python copy of `examples/graveyard-shift` to `D:\kt\graveyard-backup` without `Library`.
- Unity runs in batch mode only, through the example's tools/dev.py (`check`, `test`, `smoke`, `exec SceneBuilder.Build`), never the
  GUI. Work in the scratch copy `D:\kt\gs` (it has a Library; refresh its Assets from the example first), then copy
  changed files back, `.meta` files included, and confirm with a recursive diff of `Assets`.
- After kit changes: `python scripts/sync_examples.py D:/kt/<fresh>` twice; the second run must say "0 synced" for every
  example. Merge any `.gold` by hand.
- Kit rules: no em dashes; every new source file gets the header block (Purpose, Usage, Notes, pseudocode, Authored with
  the model); tunables in a constants block; the dev.py contract unchanged.
- Truth: never mark a claim verified unless this run verified it; every source fact needs the URL read this run;
  anything unverified is marked **(verify)**.
- Models: Sonnet subagents for wide reading and for independent review; do not use Fable (the owner approves Fable case
  by case). Optional cheap second opinion: `python core/tools/second_opinion.py` with a narrow brief (the owner's Kimi
  plan runs out fast).
- Budget: stop and report if blocked, or after 80 turns.

# Distill Report

> First written 2026-10-19 by the distill run (`DISTILL_PROMPT.md`); rules and experiments rechecked against
> `core/docs/EVIDENCE.md`, the SOPs and the README on 2026-11-02. The per-component "still unverified" table of the
> first version is retired, because it went stale as the example games were built: what was tested, and how, is the
> README table "What was tested and what was not", and everything still open, untested or never tried is in
> `KNOWN_ISSUES.md` (each item links its GitHub issue). Grades and IDs: `core/docs/EVIDENCE.md`. What changed: `CHANGELOG.md`.

## Top 10 rules the kit enforces
| # | Rule | Grade | Lives in |
|---|---|---|---|
| 1 | Never guess commands: `python tools/dev.py check / test / smoke / build / run / clean / doctor`, same exit codes on every engine | A (K01) | `CLAUDE.md`, every `dev.py` |
| 2 | No whole-game prompts. GDD, then a vertical slice, then scale | B (F2) | `FIRST_HOUR.md`, `VERTICAL_SLICE.md`, `SOP-12` |
| 3 | References, mockups and a color bible before any art | B (F3) | `CONCEPTS.md`, `SOP-12` |
| 4 | Mechanics before art. Playable with gray boxes first | B (F4) | `SOP-01`, `SOP-12` |
| 5 | One job per fresh session, every job ends with a test | B (F2) | `SOP-12`, `SOP-07` |
| 6 | Run the 11-point interaction smoke checklist before calling any 3D build done | B (F1, seven independent creators) | `SOP-09`, `CLAUDE.md` |
| 7 | Visual self-checks from several angles and frames | C (F10), kept because it is cheap | `SOP-09` |
| 8 | Every asset logged with license and AI bucket (no, dev-only, pre-generated, live) before it enters the repo | A (F11) | `SOP-04`, `ASSET_LOG.md` |
| 9 | 3D by script, scripts kept, every asset through `validate_asset.py` | B (F8) + A (K01) | `SOP-11` |
| 10 | Budget the effort. Unattended runs only on a branch, auto mode, deny rules on, `/goal` conditions that demand printed proof | B (F5), A (F19) | `SOP-12`, `SOP-07` |
Also enforced as policy: never ship a clone of a commercial game (F17, `SOP-04`).

## Claims that stay unproven
Outside the kit's own code (that is `KNOWN_ISSUES.md`), these claims keep their grade in `EVIDENCE.md` until someone
tests them, and none of them is a rule:
- The creature animation pipeline (E02, grade C): never reproduced outside the creator's video.
- "Claude drives Unreal and Blender without an MCP" (E27, C) and the Unity MCP claims (E17, D; E20, C).
- Every time and cost figure from videos (E19, E25, E26, E27, E62, all C): your plan, effort and models give
  different numbers.
- AI tool terms, prices and output rights: marked **(verify)** in the docs (see `KNOWN_ISSUES.md`, "Docs marked
  (verify)").
- Whether the kit saves tokens: plausible, never measured (experiment 6).

## Experiments worth your time (each turns "reported" into "tested")
1. **Adopt a Godot game that was not made with the kit** (`new_game.py --adopt --engine godot`), then run `dev.py
   check`, `test`, `smoke` and `build`. The Godot overlay already passes all four in a scaffolded project (README
   table); a game with its own layout and history is the real test of `--adopt`.
2. **Validate real models** inside Blender: Kenney CC0 FBX and OBJ models already pass (README table); still to try
   are a Tripo draft and one of your own. Add any problem the validator missed as a new exam case.
3. **Run the vertical slice prompt on a tiny slice of a real game** at medium effort. Log time and percent of weekly
   limit in `ROADMAP.md`. That is your own F5 data point instead of a YouTuber's.
4. **Open a scaffolded project in interactive Claude Code** and look at `/hooks` and `/permissions`. The hook, a deny
   rule and a subagent were confirmed in a headless session; those two views were not (README table).
5. **A/B the smoke checklist:** have Claude build the same small 3D room twice, once with the `SOP-09` checklist in
   the prompt and once without, and count the bugs you find. If the checklist does not cut bugs, it does not deserve
   to be a rule.
6. **A/B the kit itself on tokens:** build the same tiny slice twice in fresh sessions, once in a kit project and once
   in a bare engine project, same prompt and model. Compare tokens (`/cost`, or `claude -p --output-format json`),
   fix-up rounds and bugs found later.
7. **Play an example as a human**, for instance Ghost Lantern (`examples/ghost-lantern`): three runs, then
   `/playtest-report`. No example has been played by a human tester yet; the bots proved the lantern matters, and
   only players can confirm the ghosts are readable and that you want another run (its VERTICAL_SLICE assumptions 1
   and 3).

# Distill Report (2026-10-19)

> **Snapshot from 2026-10-19, before most of the example games.** Several "unverified" rows were verified later. The
> README table "What was tested" is current and wins wherever the two differ.

> One page: what the kit now enforces, what is still unproven, and the experiments that would prove it.
> Grades and IDs: `core/docs/EVIDENCE.md`. What moved where, and the fixes from the independent review: `CHANGELOG.md`.

## Top 10 rules the kit now enforces
| # | Rule | Grade | Lives in |
|---|---|---|---|
| 1 | Never guess commands: `python tools/dev.py check / test / smoke / build / run / clean / doctor`, same exit codes on every engine | A (K01) | `CLAUDE.md`, every `dev.py` |
| 2 | No whole-game prompts. GDD, then a vertical slice, then scale | B (F2) | `FIRST_HOUR.md`, `VERTICAL_SLICE.md` |
| 3 | References, mockups and a color bible before any art | B (F3) | `CONCEPTS.md`, `SOP-12` |
| 4 | Mechanics before art. Playable with gray boxes first | B (F4) | `SOP-01`, `SOP-12` |
| 5 | One job per fresh session, every job ends with a test | B (F2) | `SOP-12`, `SOP-07` |
| 6 | Run the 11-point interaction smoke checklist before calling any 3D build done | B (F1, six independent creators) | `SOP-09`, `CLAUDE.md` |
| 7 | Visual self-checks from several angles and frames | C (F10), kept because it is cheap | `SOP-09` |
| 8 | Every asset logged with license and AI bucket (no, dev-only, pre-generated, live) before it enters the repo | A (F11) | `SOP-04`, `ASSET_LOG.md` |
| 9 | 3D by script, scripts kept, every asset through `validate_asset.py` | B (F8) + A (K01) | `SOP-11` |
| 10 | Budget the effort. Unattended runs only on a branch, auto mode, deny rules on, `/goal` conditions that demand printed proof | B (F5), A (F19) | `SOP-12`, `SOP-07` |
Also enforced as policy: never ship a clone of a commercial game (F17).

## Top things still unverified
| # | Claim or component | Why it matters |
|---|---|---|
| 1 | Unity overlay: verified on 6000.6.6f1 (2026-10-20) except `run`. A real game project is untested | Your first Unity game |
| 2 | Unreal `dev.py`: all commands but `run`/`genproj` verified on UE 5.8 with a minimal C++ project (2026-10-20). A real game project is untested | The first real Unreal game is the real test |
| 3 | Godot `dev.py` `build` (export) never run. The rest passed against real Godot 4.7.2 and GUT 9.7.1 on 2026-10-20 (`CHANGELOG.md` 2.0.1) | Adopting a real Godot project proves the rest |
| 4 | C++ overlay: built, tested and smoke-run against real SDL2 via vcpkg on Windows (2026-10-20). Linux/macOS untested | A real C++ game build is the real-project test |
| 5 | Claude Code config shapes: skill frontmatter loads (seen while building the kit); hooks, permission rules and subagents in a scaffolded project not confirmed live | One `/hooks`, `/permissions` and `/agents` check settles it |
| 6 | `validate_asset.py` not run on FBX and OBJ files or on real (non-synthetic) assets; it now runs inside Blender 5.2.2 and with the `bpy` module | Real assets have quirks synthetic ones do not |
| 7 | AI tool terms, prices and output rights (Tripo plans, ElevenLabs, Lovable, Higgsfield, Patina) | Commercial rights decide what can ship |
| 8 | The creature animation pipeline (E02) | Never reproduced outside the creator's video |
| 9 | "Claude drives Unreal and Blender without an MCP" (E27) and the Unity MCP claims (E17, E20) | Tool choice for any Unreal or Unity game |
| 10 | Every time and cost figure from videos (E19, E25, E26, E27) | Your plan, effort and models give different numbers |
| 11 | Web overlay: verified in headless Chromium only (2026-10-21). Firefox, Safari, mobile browsers and `run` (dev server) untested | Players use all of them; audio formats differ |
| 12 | SOP-15 local-model runtimes: WebLLM (headed Chromium) and NobodyWho (Godot 4.7.2) now run in the Gatekeeper examples on one Windows machine with an RTX GPU. LLMUnity, Llama-Unreal, NVIGI, CPU-only machines, Mac and Linux not run | Players' hardware varies far more than one dev machine |
| 13 | Whether the kit saves tokens: plausible from this session (summarized tool output, one-call asset intake, early test failures), not measured | Experiment 6 measures it |
(`yt_transcript.py` was run against live YouTube on 2026-10-21; see CHANGELOG 0.2.2 pass 7.)

## Experiments worth your time (each turns "reported" into "tested")
1. **Adopt a real Godot project** (`new_game.py --adopt --engine godot`), then run `dev.py check`, `test`, `smoke` with real Godot, and after installing export templates `dev.py build --preset "<preset>" --out build/<name>`. The build step closes unverified item 3.
2. **Validate three real models** inside Blender: a Kenney CC0 asset, a Tripo draft, one of your own. Add any problem the validator missed as a new exam case. Closes item 6.
3. **Run the vertical slice prompt on a tiny slice of a real game** at medium effort. Log time and percent of weekly limit in `ROADMAP.md`. That is your own F5 data point instead of a YouTuber's.
4. **Open a scaffolded project in Claude Code** and run `/hooks`, `/agents`, and one skill. Paste any error to Claude. Closes item 5.
5. **A/B the smoke checklist:** have Claude build the same small 3D room twice, once with the `SOP-09` checklist in the prompt and once without, and count the bugs you find. If the checklist does not cut bugs, it does not deserve to be a rule.
6. **A/B the kit itself on tokens:** build the same tiny slice twice in fresh sessions, once in a kit project and once in a bare engine project, same prompt and model. Compare tokens (`/cost`, or `claude -p --output-format json`), fix-up rounds and bugs found later. Closes item 13.
7. **Play Ghost Lantern as a human** (`examples/ghost-lantern`): three runs, then `/playtest-report`. The bots proved the lantern matters; only players can confirm the ghosts are readable and that you want another run (its VERTICAL_SLICE assumptions 1 and 3).

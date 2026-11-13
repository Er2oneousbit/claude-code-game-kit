# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Someone here wants to make a game?

If the person in this session is not maintaining the kit but wants a game ("make me a game", "how do I use this", "where do I start"), use the `make-a-game` skill. **A bare `Start` (or `start`, `hi`, `help`) as the first message is the README's front-door instruction: run `make-a-game` right away, without asking whether they maintain the kit and without a status report, even when memory says they do.** Maintainers ask for kit work in words. Use the `make-a-game` skill (`.claude/skills/make-a-game/`): it asks a few questions, creates their game folder next to the kit, and hands them over to it. Never build a game inside the kit folder. Everything below is for maintaining the kit.

## What this repo is

The **Claude Code Game Kit**, not a game. `scripts/new_game.py` stitches the universal `core/` plus one engine overlay from `engines/<id>/` into a new game project, or adopts an existing one. MIT licensed. Version lives in `KIT_VERSION` in `scripts/new_game.py`; bump it together with a `CHANGELOG.md` entry, by the same semver rules the kit gives games (`core/docs/sop/SOP-06-build-and-release.md` "Versioning": MINOR for new features, PATCH for fixes, MAJOR when existing projects need manual changes).

Most of the tree is **template content that ships into generated games**:
- `core/CLAUDE.md` and `core/.claude/` (settings, SessionStart hook, 25 skills, 5 subagents, Bug and Feel issue forms in `.github/`) configure the *generated* game. Claude Code surfaces the `core/.claude/skills` as directory-scoped skills when you touch files under `core/`. Do not invoke them for kit work: they assume a game's layout (HANDOFF and ROADMAP under docs/ at the root, a dev.py under tools/, and so on).
- Paths inside `core/` docs are written as they will be after scaffolding (core/docs/GDD.md becomes docs/GDD.md), and each engine's ENGINE.md becomes docs/ENGINE.md. That is why `check_links.py` at the kit root reports about 249 hits (249 on 2026-11-13, 0.15.3) that are fine in a generated project: scaffold-time paths, the kit-root `make-a-game` skill's game-folder paths, GitHub-only `../../issues/N` links, and released CHANGELOG lines that name files at their old paths. `scripts/check_links_baseline.txt` lists them (sorted `file: kind: target` lines), so the check with `--baseline` fails only on a hit the list lacks: a new break. After a change that adds or removes a known hit on purpose, refresh the list with `--write-baseline` and review its diff. Run it from a clean checkout or a worktree: untracked notes at the kit root (and `CLAUDE.local.md`) add hits of their own.
- `{{GAME_NAME}}` `{{GAME_SLUG}}` `{{ENGINE}}` `{{ENGINE_LABEL}}` `{{DATE}}` `{{AUTHOR}}` in any UTF-8 file are substituted at scaffold time. Keep them intact in templates.
- Profile placeholders come from `profiles/*.json` (`--profile`): a line that is only `# {{FOOTER}}` or `// {{FOOTER}}` becomes the footer comment or disappears, a `{{PROFILE_STYLE}}` line becomes the profile's style bullets, `{{FOOTER_RULE}}` becomes the STYLE.md footer rule. Starter code uses `{{FOOTER}}`; kit tools (`core/tools/`, every `dev.py`, the hook, `check_scripts.gd`, `GameKitBuild.cs`, `GameKitScenes.cs`, `GameKitCapture.cs`) carry no footer and name no author.

## Commands

Python 3.8+, standard library only for the scaffolder, `doctor.py`, `check_links.py`, the hook, and every `dev.py`.

```
python scripts/new_game.py --list-engines
python scripts/new_game.py --name "Test" --engine godot --dest <scratch-dir> --dry-run   # preview
python scripts/new_game.py --name "Test" --engine godot --dest <scratch-dir> --debug     # real, lists every file
python scripts/new_game.py --name "Test" --engine godot --dest <existing-dir> --adopt    # never overwrites; conflicts -> <file>.gold
python scripts/new_game.py --name "Test" --engine godot --dest <existing-dir> --upgrade  # replaces kit files you never edited (hash-based)
```
Exit codes: 0 ok, 1 unresolved placeholders in output, 2 usage or environment error.

After changing anything that ships into games, bring the examples up to date (copies outside the repo, content-based):
`python scripts/sync_examples.py <scratch>/<fresh>` then again into another fresh folder, which must report "0 synced"
everywhere. A `[warn] ... .gold` line means the game edited that file: merge the kit's version in by hand.
Then `python scripts/check_examples.py` runs doctor, check, test and smoke in every example (engine env vars as the
`dev.py` files document them, `GUT_DIR` pointing at a GUT 9.x `addons/gut/` for the Godot ones; a missing toolchain is
skipped by name) and fails if the run leaves tracked changes in `examples/`. Examples catch what the kit's own tests
miss: kit code that leans on the starter's types or claims a common name, and fonts that cannot draw a language.

Verify a change by scaffolding every affected engine into a scratch dir outside this repo, then inside each output run `python tools/doctor.py` (also runs the link check) and `python tools/dev.py -h` (paths relative to the generated project). A second `--adopt` run on the same output must produce no conflicts.

Tool exams: `scripts/run_exams.py` runs every `test_*.py` under `core/tools` and `scripts` from one table (the source
of truth for what each exam needs beyond the standard library: Pillow and numpy, bpy on uv's Python 3.13, git, GIMP 3,
Inkscape 1.x, a REAPER_BIN or ASEPRITE_BIN) and prints one line per exam: pass/fail/skipped (a missing tool is a skip
naming the tool, never a fail), unique tests (never unittest's `Ran N`), time. Before a release, run it again on the
oldest supported Python: `Path.write_text(newline=)` and `Path.resolve()` on missing relative paths behave differently
there, and 0.7.2 shipped broken on 3.8 and 3.9 because only 3.14 was run. An exam file without a row makes `--list`
and every run print a warning: add it to the table. Any single exam still runs on its own (`python <path>`).
```
python scripts/run_exams.py --list                   # the table: name, path, needs, note
python scripts/run_exams.py                          # the default set on this Python (about 15 minutes)
python scripts/run_exams.py --python 3.8,3.14        # once per version through `uv run --python` (this Python without uv)
python scripts/run_exams.py --only doctor --only new_game
python scripts/run_exams.py --changed main           # just the exams covering files changed since that ref
python scripts/run_exams.py --live                   # also the live exams (a real ComfyUI/TRELLIS, a Cycles render) and the
                                                     # live parts (REAPER_BIN, ASEPRITE_BIN, PIXELORAMA_BIN: hidden without --live)
python scripts/run_exams.py --jobs 4                 # exams at once; exit 0 all passed, 1 an exam failed, 2 setup problem
python core/tools/audio/wavesmith/wavesmith.py test  # the Wavesmith rows on their own (about 3 minutes)
python core/tools/check_links.py --root . --also core --also core/docs --skip-dir examples --skip-dir .claude/worktrees --baseline scripts/check_links_baseline.txt
                                                     # kit root: exit 1 only on a hit the baseline lacks (249 known on 2026-11-13);
                                                     # add --write-baseline to rewrite the list after an intended change
git ls-files -coz --exclude-standard -- core engines scripts profiles examples '*.md' | grep -zv /licenses/ | LC_ALL=C.UTF-8 xargs -0 grep -nIP "\x{2014}"   # em dash check, must print nothing: tracked and new files only (a plain grep -r also reads the examples' node_modules and Library), -I skips binaries, docs/licenses/ holds verbatim third-party license texts
```
Machine-specific engine paths and quirks for running `dev.py` in scratch projects go in `CLAUDE.local.md` (gitignored, loaded by Claude Code). Env vars the wrappers read: `GODOT_BIN`, `UNITY_EDITOR`, `UE_ROOT`, `VCPKG_ROOT`, `LOVE_BIN`, `RPGMZ_EXE` (optional), `CARGO_TARGET_DIR` (optional, Bevy). Unity and Unreal are adopt-first (create the engine project, then `--adopt`); RPG Maker MZ gets MZ's files with `dev.py setup --from <a new MZ project>` (the kit ships none of MZ); keep C++ and Unreal scratch projects at a short path (vcpkg and UBT hit Windows path limits).
`.vscode/settings.json` points CMake at `engines/cpp-sdl2/skeleton` (presets `debug`/`release`, vcpkg manifest, doctest).

## How the scaffolder composes a project

Order in `new_game.py` (later steps win):
1. Copy `core/` with placeholder substitution. Binary files are copied verbatim.
2. Write the engine's ENGINE.md and FLOW.md into the game's docs folder as ENGINE.md and ENGINE_FLOW.md. The generated CLAUDE.md `@`-imports the first.
3. Copy `engines/<id>/skeleton/` on top. A skeleton file at the same path overrides the core file within the same run.
4. Create `<assets_dir>/.gitkeep`, except when `assets_dir` is `Content` (Unreal).
5. `.gitignore` = `core/.gitignore` + `gitignore.append` under a marker line, appended once in adopt mode. `.claude/settings.json` = `deep_merge(core, settings.patch.json)` (lists unioned, dicts recursive, scalars patch-wins), then merged into any existing file in adopt or upgrade mode three ways (`merge_user`) against the kit settings and .gitignore rules recorded in `.game-kit.json` (`kit_settings`, `kit_gitignore`): the user's values and deletions stay, rules the kit removed go, only new kit entries are added. Both are skipped by the tree copy.
6. Write `.game-kit.json` (version, profile, history, per-file hashes; a pre-0.3.0 `.gold-standard.json` is read and replaced), optional `git init` (never commits).
7. Scan output for unresolved `{{...}}`. The generated doctor.py is exempt because it contains the pattern on purpose.

Engines are discovered from `engines/*/engine.json`; folders starting with `_` are skipped. New engine: copy `engines/_template/` and follow its README, no scaffolder changes.

## The dev.py command contract

Each `engines/<id>/skeleton/tools/dev.py` implements `check | test | smoke | build | run | clean | doctor | ship`, exit codes 0 ok / 1 task failed / 2 environment or usage problem, global `--debug` and `-h` documenting env vars (`GODOT_BIN`, `UE_ROOT`, ...). Global options must work before or after the subcommand. Destructive `clean` (Unity, Unreal) must never hang: without `--yes` it prompts only on an interactive TTY, and exits 2 asking for `--yes` in a non-interactive shell or on a closed stdin. Every engine accepts `clean --yes`. `doctor` also calls the core `doctor.py`. Keep all nine in step when the contract changes. The web and web-3d overlays also have `setup` (npm install + headless browser); their `dev.py` and `smoke.mjs` are identical except for names, and so are `src/shell/`, `src/core/` (plus web-3d's `follow.ts`) and `data/` (`scripts/test_kit_docs.py` checks): the shell meets the renderer only through `engines/web/skeleton/src/shell/host.ts` (`engines/web/skeleton/src/game/phaserHost.ts`, `engines/web-3d/skeleton/src/game/threeHost.ts`), so change both together. `rpgmaker-mz` has `setup` too (plus `--from`, which copies MZ's files into `game/`), and its `smoke.mjs` is the web one serving `game/` through `serve.mjs`: carry fixes across. Scenario options on `smoke` (`--until`, `--fail-on`, `--screenshot`, `--record`) exist on web, web-3d, cpp-sdl2 (game options after `--` there), unity (PlayMode tests named Smoke, captures through `GameKitCapture.cs`), rpgmaker-mz (the web smoke serving `game/`) unreal (`--until`/`--fail-on`/`--filter`; capture from the game, tests run without a renderer) bevy (game options after `--`; headless without capture options, a window with them) and love2d (an off-screen window by default, `--headless` for none, game options after `--`; LÖVE's error screen waits for a key, so conf.lua's `love.errorhandler` must exit 1 in automated runs); godot has `--screenshot`/`--record` only (a windowed run through `tools/capture.gd` after the headless smoke); keep them alike. Unity has `exec Class.Method` and Unreal `exec <script.py>` for editor scripts. `ship` is the same everywhere: `split_ship` hands everything after it to `tools/cloud/ship.py` (OpenTofu, five providers), adding the engine's web build (`SHIP_SITE`) as `--site` for a static site; it needs no engine. `python core/tools/cloud/test_ship.py` is its exam (the real-OpenTofu cases run when `TOFU_BIN` or `tofu` is found).

## Evidence rules for docs

Every claim in the SOPs that comes from an outside source or a test (a video, a doc, a measurement, a number) cites a source ID from `core/docs/EVIDENCE.md`; standard engineering practice (bisecting, small commits, a question per playtest) needs none (`E##` sources, `F##` cross-source findings, `K01` = this kit's own tests), graded A to X. A tip becomes a SOP rule only at grade A or B; grade C and D stay labeled tips. New source: summarize into `core/docs/evidence/video-notes.md`, add an `E##` row, cite it where used. Specifics that are not live-checked are marked **(verify)**. `DISTILL_PROMPT.md` and `DISTILL_GOAL.txt` re-run the whole cleanup; `DISTILL_REPORT.md` lists the enforced rules, the outside claims still unproven and the experiments to run; open kit issues live in `KNOWN_ISSUES.md`.

## Conventions (from `core/docs/STYLE.md`, also applied to this repo's own files)

- No em dashes anywhere.
- Source files and tool scripts get the header block (`Purpose / Usage / Notes / Authored`, plus pseudocode for non-trivial logic) and credit Claude with the model in `Authored`, never a person. Starter code ends with a `{{FOOTER}}` line (the profile's footer, or nothing); kit tools have no footer. Neither goes on generated, data, or third-party files.
- Tunables in a constants block at the top. User-facing errors print `[error] ...` without a traceback unless `--debug`.
- Permission rules (`core/.claude/settings.json`, `settings.patch.json`): never allow-list a git subcommand with a wildcard (flags like `--output` write files; Claude Code's built-in read-only checks already cover safe git reads); put a `*` before subcommands in ask rules (`dev.py *clean*`) so option-first forms match; give every Bash rule a PowerShell twin; use `Edit(path)`, never `Write(path)` (ignored). Recheck changes in a live Claude Code session in a scaffolded project (`/permissions`, `/hooks`).
- Text encoding: every script calls `stream.reconfigure(encoding="utf-8", errors="replace")` on stdout/stderr at startup, and every captured `subprocess` call passes `encoding="utf-8", errors="replace"`. Windows pipes are cp1252 until Python 3.15; test with names containing "Í" or a right double quote (bytes cp1252 cannot decode), not just "é".
- Path filters must match paths **relative to the project root**, never `Path.parts` of an absolute path (the Windows temp dir is itself named `Temp`; see CHANGELOG 0.2.1).
- Check the README "What was tested" table before assuming something works. Eight of the nine overlays are verified against real toolchains on Windows; `rpgmaker-mz` is not yet (built without RPG Maker MZ, checked against a fake MZ project; its engine steps say (verify)) (gaps: Unity `run` past the GUI editor's Hub sign-in, Unreal Blueprint-only `package`, Linux/macOS).

# SOP-06: Build and Release

## Goal
Reproducible builds and a boring release day.

## Steps
1. **Freeze scope.** Only bug fixes after the release candidate cut. New ideas go to Parking lot.
2. **Clean release build** from a clean clone: `python tools/dev.py clean --yes` (every engine accepts it; Unity and Unreal ask without it), then `check`/`test`/`smoke` (Godot re-imports automatically), then the **release command** in `docs/ENGINE_FLOW.md`, section "Packaging":
   Godot `build --preset "<preset>" --out <path>`, C++ `build --preset release`, Unreal `package --config Shipping`, Unity `build`.
3. **Run `/release-check`.** It walks the checklist below and reports gaps.
4. **Test the shipped artifact**, not the editor. Fresh machine or clean user profile if possible.
5. **Tag and archive.** Tag the commit, archive build artifacts and debug symbols, record versions in HANDOFF.
6. **Post-release.** Triage feedback into ROADMAP, update TROUBLESHOOTING with known issues. Shipping to Steam and itch.io, signing and CI: `SOP-21`; the post-launch loop: "After launch" below.

## Versioning (Semantic Versioning, adapted for games)
Version numbers are `MAJOR.MINOR.PATCH` (semver.org). Before the first full release the game lives in **0.x**, where
anything may still change; **1.0.0 is the full production release** (the store launch, "done" by the GDD's release tier).

| Change | Before 1.0 (in development) | After 1.0 (released) | Examples |
|---|---|---|---|
| Big step: a milestone, new system, new content chunk | `0.MINOR`: 0.3.0 -> 0.4.0 | `MINOR`: 1.2.0 -> 1.3.0 | Vertical slice done, a new level set, crafting added |
| Small tweak: fixes, balance, polish | `0.0.PATCH`: 0.4.0 -> 0.4.1 | `PATCH`: 1.3.0 -> 1.3.1 | Bug fix, tuning pass, typo, performance fix |
| Breaking for players: saves or progress stop carrying over, a sequel-sized overhaul | (anything goes before 1.0) | `MAJOR`: 1.x -> 2.0.0 | New save format without migration, a 2.0 remake |
Rules:
- A MINOR bump resets PATCH to 0 (0.4.3 -> 0.5.0); a MAJOR bump resets both (1.7.2 -> 2.0.0).
- Pre-release builds before a launch: `1.0.0-rc.1`, `1.0.0-rc.2` (release candidates), then `1.0.0`. Playtest builds also get
  a dated tag `playtest-YYYYMMDD` (SOP-05).
- Suggested milestone mapping (ROADMAP): M0 toy `0.1.0`, M1 vertical slice `0.2.0`, each content milestone a further `0.x.0`,
  M3 release candidate `1.0.0-rc.N`, launch `1.0.0`.
- **One source of truth:** the version lives in one place and the game reads it from there (title screen, crash logs, save
  files). Godot: Project Settings `application/config/version`; web: the version field of package.json; C++: CMake `project(... VERSION x.y.z)`;
  Bevy: `version` in `Cargo.toml` (code reads `env!("CARGO_PKG_VERSION")`);
  Unity: Player Settings version; Unreal: `ProjectVersion` in the project settings **(verify the field for your engine version)**.
- The git tag matches it exactly: `v0.4.1`. Record it in `docs/HANDOFF.md` and in the save file's version field.
- Bump the version in the same commit as the change log entry, and only when a build goes to someone (testers, players).

## Release checklist (summary, `/release-check` has the full version)
- [ ] Version number set and displayed in game
- [ ] Debug features off or gated (cheat keys, debug overlay, verbose logs)
- [ ] `CREDITS.md` complete from `ASSET_LOG.md`, no `PLACEHOLDER` assets remain
- [ ] Licenses for engine, middleware, fonts shipped where required
- [ ] Engine license obligations: Unreal Release Form submitted before launch (royalty reporting above the revenue threshold), Unity plan tier matches revenue and funding **(verify current terms)**
- [ ] Godot: export preset filters exclude `tests/*`, `tools/*`, `addons/gut/*`, `assets_src/*` (sources and review sheets) and `.game-kit.json` (the kit's file record); `dev.py build` fails when the .pck holds any of them
- [ ] Save files versioned and migration tested
- [ ] Settings persist: audio volumes, display mode, key bindings
- [ ] Gamepad and keyboard both complete the game; prompts follow the device in use
- [ ] Accessibility baseline met (SOP-20 step 1): subtitles and captions, text size and 200 % scaling, no colour-only information, remapping and no required holds, shake and flash safety, difficulty changeable in play
- [ ] `python tools/credits.py --check` passes; CREDITS.md and THIRD_PARTY_LICENSES.md ship with the build
- [ ] Performance budget met on lowest target hardware (SOP-10)
- [ ] Crash and error logging works, log file location documented
- [ ] Store page assets ready: capsule art, screenshots, trailer, description, AI disclosure if applicable (SOP-04: pre-generated and live content, guardrails for live)
- [ ] Legal: privacy policy if collecting data, age ratings if required by the store **(verify per store)**

Publishing and store uploads (Steam, Roblox, itch) often need your own logged-in clicks. Claude can prepare builds, checklists and text, but expect to press the final buttons yourself. Key art and thumbnails come from an image generator, with Claude writing the brief.

## Putting it online (a web build or a server)
`python tools/dev.py ship --target aws|azure|gcp|linode|do --kind static|container` deploys with OpenTofu
(`tools/cloud/README.md`): `--check` validates offline, `--plan` shows what it would make, `--apply --yes` applies
exactly that plan, `--destroy --yes` removes everything it made. Read the plan before applying (it costs money), set
the budget alert (`--budget`, `--alert-email`; by hand on Linode and DigitalOcean), keep the state in `deploy/` (it is
git-ignored, and destroy needs it), and use a deploy login with only the rights the recipe needs. The recipes are
validated offline and not yet run against a real account **(verify on the first apply)**.

## After launch (standard practice)
- **Hotfix flow:** a crash or a save-breaking bug gets a PATCH release (versioning above) from a branch off the release
  tag, with only that fix, the same release check, then a merge back. Upload to a beta branch first (SteamPipe `SetLive`,
  `SOP-21` step 3), play it, then set it live by hand.
- **Patch notes** for every release, in players' words, newest first: what changed for them, known issues, thanks for
  reports. Template: version and date, then "Fixed", "Changed", "Added", "Known issues". Post them where players are
  (the Steam event or news page, itch devlog).
- **Reviews and refunds:** read every review in the first weeks; reply to bug reports with the fix version. Refund
  reasons (Steam shows them in the partner reports, verify) are a bug list. Do not argue with reviews.
- **Community:** one place for reports (the GitHub Bug and Feel forms, `SOP-03`, or a Discord with a bug channel), and a
  pinned post with the known issues. Triage weekly (`/triage-issues`).
- **Saves across updates:** every update loads every older save version (`SOP-19` step 3); a save from a newer build is
  never overwritten.
- **Mod support (decide, then write it down):** none, data-only (JSON or Lua data the game reads from a mods folder), or
  scripts. Data-only is the safe default: load mods after the base data, validate them like settings (bad values fixed
  and logged), never let a mod write outside its folder. State the policy and the license terms for mod authors on the
  store page or in the game's README.

## Done when
- The tagged build was tested as the shipped artifact, `/release-check` has no open gaps, and versions are recorded in HANDOFF.

## Common mistakes
- Testing only in the editor.
- Leaving debug cheats enabled.
- Discovering missing license text the night before launch.

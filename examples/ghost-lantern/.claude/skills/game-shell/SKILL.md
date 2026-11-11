---
name: game-shell
description: Build or fix the game's shell - title screen, main menu, settings, pause, credits, loading, saved settings, save files with versions and backups, control rebinding, gamepad navigation and button prompts, localization and the pseudo-locale, crash logs, consent-first telemetry. Use when the user asks for menus, an options screen, saving, key rebinding, controller support, translations or "make it feel like a real game". Follows SOP-19, with SOP-20 for the accessibility settings.
---

# Game shell

Follow `docs/sop/SOP-19-front-end-and-settings.md` (and `docs/sop/SOP-20-accessibility.md` for what the settings must do).

1. **See what is there:** the overlay's shell (`docs/ENGINE.md`, `docs/ENGINE_FLOW.md`): Godot, LÖVE, web, web-3d,
   Unity, Unreal, Bevy and C++/SDL3 ship working screens, crash files, the bug report key, the juice demo, the
   pseudo-locale drive and analog input for the game; RPG Maker MZ keeps MZ's own screens and settings, ships the
   rules as plugins (GameShell, GameJuice) and puts the accessibility settings that fit on MZ's Options screen
   (GameAccess); ENGINE_FLOW says what is left. Never write a second settings or save system next to the kit's.
2. **Scope:** which parts the request needs (screens, settings, saves, input, localization, logs, telemetry). Confirm it
   is in ROADMAP Now (SOP-01).
3. **Behavior changes go through the spec:** `tools/golden_vectors.py` first, `--write`, then the port and its tests
   against `data/golden/shell.json`.
4. **Saves:** bump the save version for any change to the data's shape, add the migration and a test that loads a real
   file from the old version (SOP-19 step 3).
5. **Input:** actions, not keys; full gamepad navigation with a visible focus; prompts follow the last device; new
   actions get defaults for keyboard and gamepad and appear in the rebinding screen.
6. **Text:** every new visible string goes through `tr()` with a key in the English string table (data/i18n/en.json
   where the overlay ships the shell); placeholders, not concatenation; plurals per category.
7. **Prove it:** `check`, `test`, `smoke`, and, where the overlay ships the scripted front end (every overlay with a shell), the scenario runs from `docs/ENGINE_FLOW.md`: `--drive menus` (settings file changes), `--drive pseudo --locale pseudo`
   (nothing clipped), `--drive crash` (a crash file); screenshots of the changed screens with
   `--drive show:<screen> --screenshot`. Elsewhere (RPG Maker MZ has no `--drive`: MZ's own screens) make the same
   checks by hand, as `/release-check` 7c says.
8. **Report:** what changed, the save version, the screenshots, anything left (verify).

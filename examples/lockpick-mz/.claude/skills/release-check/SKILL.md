---
name: release-check
description: Run the pre-release checklist for a playtest build, demo, or store release. Use when the user says they are preparing to ship, cut a build, upload to Steam or itch, or asks "are we ready". Audits licenses, debug flags, credits, saves, settings, and builds.
---

# Release check

Follow `docs/sop/SOP-06-build-and-release.md`. Engine packaging details: `docs/ENGINE_FLOW.md`.

Work through each item. For each give **PASS**, **FAIL**, or **UNKNOWN** with evidence (file, command output). Never mark PASS from assumption.

1. **Build:** `python tools/dev.py clean --yes` (every engine accepts it), then `check`, `test`, `smoke` (Godot re-imports by itself; a project that has no tests yet exits 2 "nothing ran": report that as UNKNOWN, not PASS), then the release command from `docs/ENGINE_FLOW.md` "Packaging" (Godot `build --preset ... --out ...`, C++ `build --preset release`, Unreal `package --config Shipping`, Unity `build`). All pass from a clean state.
2. **Version:** follows SOP-06 "Versioning" (0.x before launch, 1.0.0 at full release, MINOR for big steps, PATCH for tweaks), lives in one place, shown in game, matches the tag and the save files.
3. **Debug off:** cheat keys, debug overlays, verbose logs, test levels not reachable in release. Godot: the export preset's Resources > Filters exclude `tests/*`, `tools/*` and `addons/gut/*` (the default "export all" ships them). Search the code for debug flags and list any that ship enabled.
4. **Credits:** `python tools/credits.py --check` passes (CREDITS.md and THIRD_PARTY_LICENSES.md match the asset log; it fails on an asset with no license or a PLACEHOLDER row). Both files ship with the build.
4b. **Assets and licenses:** every third-party, AI-assisted or shipped media file (art, audio, fonts, models) maps to a row in `docs/ASSET_LOG.md`. No `PLACEHOLDER` rows remain. License evidence exists. Generate or update `CREDITS.md` from the log with required attributions.
5. **Third-party licenses:** engine, middleware, fonts, libraries. Required notices shipped. Engine terms: Unreal Release Form filed, Unity plan matches revenue and funding **(verify current terms)**.
6. **Saves and settings:** save version field present, load of an older save tested, settings persist (audio, display mode, key bindings).
7. **Input:** keyboard-only and gamepad-only can complete the game, remapping works where promised, prompts match the device in use (no keyboard glyphs while a gamepad is active).
7b. **Accessibility (SOP-20 step 1, F33 to F37):** subtitles on by default with speaker names, two lines of about 40 characters and an adjustable background; captions for important sounds; smallest text at least 18 px at 1080p (9 px at 1280x800 on Steam Deck); text scales to 200 %; nothing carried by colour alone; every action remappable, no required holds; separate volumes and mono; shake and full-screen effects with an intensity and an off switch, reduce motion works; no more than three full-screen flashes in any one second; difficulty changeable in play. Evidence: screenshots at text 200 % and with subtitles at the largest size, the pseudo-locale smoke (`--drive pseudo --locale pseudo`), a recorded burst of the brightest effect.
7c. **Shell scenarios:** `smoke --drive menus` changes the settings file, `--drive crash` writes a crash file, telemetry writes nothing before consent (SOP-19). Engines without the scripted front end: the same checks by hand.
8. **Performance:** budget met on min spec (SOP-10), numbers recorded.
9. **Logging:** errors go to a log file, location documented, no personal data logged.
10. **Store readiness (SOP-21, SOP-23):** Steam capsules at the listed sizes with logo only, at least five gameplay screenshots of 1920x1080 or more, accessibility options listed in the description; page assets, description, AI-content disclosure if applicable (build it from the `pre-generated` and `live` rows of `ASSET_LOG.md` plus any AI-made store art, SOP-04 explains the buckets), age rating or content questionnaires, privacy policy if data is collected. Mark store-policy items **UNKNOWN: verify current requirements** unless confirmed against the store's current documentation this session.
11. **Artifact test:** run the packaged build, not the editor.

Output: a table of results, a short list of blockers, and a recommended order to fix them.

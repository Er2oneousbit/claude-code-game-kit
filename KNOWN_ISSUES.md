# Known issues and untested parts

Everything known to be broken, flaky, unproven or never tried, in one place (2026-10-27). Fixed bugs are in
`CHANGELOG.md`; what *was* tested, and how, is the README table "What was tested and what was not". The kit and the
examples were built and tested on one Windows 11 machine.

## The kit

### Never run or not run end to end
- **macOS and Linux:** untested throughout (the scaffolder ran on Linux in an earlier version only). Tool and binary
  names for GIMP and Inkscape on those systems are unverified.
- **RPG Maker MZ overlay:** never run against RPG Maker MZ (it was not installed). Checked only against a fake MZ
  project; the editor side (Plugin Manager annotations, `js/plugins.js`, Deployment, `run --editor`) is marked (verify).
- **Unity:** `run` opens the editor, but on the test machine it stopped at Unity's Hub sign-in, so a loaded editor is
  not confirmed. Batchmode commands are unaffected.
- **Unreal:** `package` on a Blueprint-only project is not verified (C++ projects are).
- **Bevy:** Windows only (Linux needs ALSA and udev dev packages, named in the docs but not tried); a web (WASM)
  build is not wired into `dev.py`; the starter moves in fixed 1/60 s ticks with no render interpolation, so motion
  can look uneven on high refresh rate screens; `--features dev` (dynamic linking) was not tried.
- **Skills no new user has run yet:** `/procgen` on a fresh game, `/triage-issues` on a real game's issues. The Bug
  and Feel issue forms parse, but nobody has looked at them rendered on GitHub.
- **Web and web-3d overlays:** run only in Chromium (headless and headed). Firefox, Safari and mobile browsers are
  untested, and their audio formats differ.
- **Local AI:** only on an RTX 5060 Ti. Other GPUs, CPU-only and browsers other than Chromium are untested.
- **Graphics drawn in code** (`tools/art/pixel_sprite.py`): exam passes, not yet used inside a game build.
- **`tools/art/chroma_key.py`:** tested on synthetic images, not on real AI sprites.

### Tools with commands not yet run live
- **`tools/art/pixellab.py`:** `image`, v3 `character`, `animate`, `animate-character`, top-down `tileset`, `ui`,
  `font`, `object`, `pixelate`, `tiles-pro`, `outfit`. It also lacks PixelLab's newer Pro Flash models, style images
  and pinned last frames (the MCP server has them; SOP-16 says which tool to use).
- **`tools/audio/eleven_audio.py`:** music is tested offline only (the free plan refuses music).
- **`tools/second_opinion.py`:** only the Kimi Code CLI is supported.

### Bugs and doubts
- **`tools/blender/prep_export.py`:** a possible error on meshes shared by several objects (multi-user meshes), never
  reproduced.
- **Docs marked (verify):** facts about outside services (prices, plans, menu paths, license terms) that were not
  checked live. They are the most likely to be out of date.

## The examples
None of the example games has been played by a human tester; the bots and tests are the only proof they play as
intended. Their art and audio are for non-commercial use (`examples/LICENSE.md`). Each game's own
`docs/HANDOFF.md` "Known broken or flaky" carries its items below.

### Gatekeeper (Godot): 12 review findings, not fixed yet
From an adversarial review (Claude Fable 5.1, 2026-10-26); the web twin got the matching fixes, this one has not.
1. Picking the scripted guard while the model loads shows the intro twice, and the game swaps to the model mid-game.
2. "Start over" reloads the scene, so the 1.1 GB model unloads and loads again on every restart (and a restart
   during a load runs two loads at once).
3. A line typed while the guard is thinking is cleared and lost.
4. An engine error is reported as "model too slow", and a failing model costs the full 12 s timeout on every line
   without handing over to the scripted guard.
5. The voice cache saves a reply before checking it is audio, so one bad answer breaks that line for good.
6. The README's "real model" check (`--llm --autoplay`) passes even when the model is missing (it falls back).
7. The test `test_nothing_changes_after_the_end` compares a value with itself, so it cannot fail.
8. The live eval counts keyword-fallback answers as model hits.
9. Model load, warm-up and one history call have no timeout: a hung driver would leave "Loading..." forever.
10. Rule tests the web twin has (score limits, "no single answer opens the gate", the intent list matching the
    regex) are missing here. The rules themselves are correct.
11. The scripted `--autoplay` run ends with `ERROR: 1 resources still in use at exit` (exit code still 0). No fix
    found; `dev.py smoke` is unaffected.
12. An exported build would show players the developer hint "run: python tools/setup_ai.py", because the model file
    is not packed into builds.

### Rune Delve (Unreal)
- **Balance at its limit:** after the review fixes the weaver bot clears 3 of 8 dungeons (was 5) against the
  masher's 0; the pair test passes exactly on its thresholds, with no margin. Tuning is on hold.
- `-quitatend` exits 0 even when the mage dies (Unreal 5.8 needs a forced exit for a non-zero code).
- Replays under `-nullrhi` (no renderer) differ from rendered runs; cause unknown (`docs/TROUBLESHOOTING.md`).

### Graveyard Shift (Unity)
- `Smoke_D` (careful bot scores at least the always-dark bot) is flaky: it sits at the 104 cap and one run in two
  gave 103. The bot trio is not exactly repeatable.
- Generated nights are easier than the hand-made yard (the dark bot escapes 6 of 8 generated against 2 of 8).
- A low rock the ghosts' NavMesh climbs (0.75 m) blocks the keeper's CharacterController (0.3 m); the fix moved the
  tuned balance and was reverted.
- Built with Mono only; IL2CPP builds were not made or compared.

### Scrap Tanks (C++/SDL2)
- Line of sight is checked center to center, so a 1.9 m tank whose center is hidden cannot be seen even when its
  edge shows (a known limit, written in its docs).

### Lockpick (RPG Maker MZ)
- An untested proof of concept: it has never run inside RPG Maker MZ, only against stand-ins.

### Coyote Hop, Courier Dash, Ghost Lantern, Gatekeeper (web)
- No open bugs after their reviews. Not yet played by a human.

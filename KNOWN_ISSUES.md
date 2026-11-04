# Known issues and untested parts

Everything known to be broken, flaky, unproven or never tried, in one place (2026-11-03). Fixed bugs are in
`CHANGELOG.md`; what *was* tested, and how, is the README table "What was tested and what was not". The kit and the
examples were built and tested on one Windows 11 machine.

## The kit

### 0.8.0 follow-ups (juice, shell, LÖVE, CI)
- **CI workflow** not yet run on GitHub-hosted runners (Actions is disabled on this repository, so it cannot run
  until that is turned on): [#40](https://github.com/Er2oneousbit/claude-code-game-kit/issues/40).
- **LÖVE:** macOS and Linux packaging, LÖVE 11.4 itself and the POSIX save rename not run: [#41](https://github.com/Er2oneousbit/claude-code-game-kit/issues/41).
- **Godot shell:** crash files need Godot 4.5+, untested on 4.3 and 4.4: [#46](https://github.com/Er2oneousbit/claude-code-game-kit/issues/46).
- **Unreal:** the GameKitShell plugin builds and passes its tests in a Blueprint-only project (headless), but turning
  it on from the editor's Plugins window is not tried: [#47](https://github.com/Er2oneousbit/claude-code-game-kit/issues/47).
- **Shell screens** ship for Godot, LÖVE and web only; Unity, Unreal, Bevy, C++/SDL2 and web-3d ship the tested
  logic and the screens are built in the engine; RPG Maker MZ keeps MZ's own screens and ships no juice or shell
  port (its ENGINE_FLOW maps the rules onto MZ). Display settings the browser cannot apply (vsync, resolution) are stored only.

### 0.8.1 follow-ups (Dotwork)
- **The new lanes not yet run together on one full game** (each was proven in a small test game; qa pack ran on a
  1,435-file test game): [#48](https://github.com/Er2oneousbit/claude-code-game-kit/issues/48).
- **Anticipation** proven on keypoints and a mocked render, not yet on a rendered sprite:
  [#49](https://github.com/Er2oneousbit/claude-code-game-kit/issues/49).
- **Image to 3D:** TRELLIS shapes come out wrong on pixel art and the cause is not found (needs a 24 GB Linux GPU):
  [#50](https://github.com/Er2oneousbit/claude-code-game-kit/issues/50).
- **Cyrillic glyph font** not made (the `bdf` lane may already cover it with an OFL font, untried):
  [#51](https://github.com/Er2oneousbit/claude-code-game-kit/issues/51).
- **Store art** not yet checked by a real Steamworks upload:
  [#52](https://github.com/Er2oneousbit/claude-code-game-kit/issues/52).
- **UI kit prompt glyphs** are generic; swapping in official console glyphs is not documented or tested:
  [#53](https://github.com/Er2oneousbit/claude-code-game-kit/issues/53).
- **Hand polish (Aseprite, Pixelorama):** a character whose clips have different canvas sizes cannot be polished
  in either editor (both refuse it at build) ([#82](https://github.com/Er2oneousbit/claude-code-game-kit/issues/82)); an edit made by a person
  in either editor's window is not tried yet ([#65](https://github.com/Er2oneousbit/claude-code-game-kit/issues/65)); partly transparent layer pixels are not compared with
  Pixelorama's own blend ([#66](https://github.com/Er2oneousbit/claude-code-game-kit/issues/66)); reading Pixelorama 1.2.4 files is built from its release-candidate source
  ([#67](https://github.com/Er2oneousbit/claude-code-game-kit/issues/67)); spells, VFX, status marks, animated props, balloons and vehicles have no hand-polish path
  ([#68](https://github.com/Er2oneousbit/claude-code-game-kit/issues/68)).

### Art workflow outside Godot
Dotwork is Godot-first: other engines get PNGs, sheets with their JSON, `.fnt` fonts and a manifest, and no overlay
outside Godot reads them yet (no animation, tile map, font, UI, lighting, particle or icon import). One issue per
engine: web [#55](https://github.com/Er2oneousbit/claude-code-game-kit/issues/55), web-3d
[#56](https://github.com/Er2oneousbit/claude-code-game-kit/issues/56), Unity
[#57](https://github.com/Er2oneousbit/claude-code-game-kit/issues/57), Unreal
[#58](https://github.com/Er2oneousbit/claude-code-game-kit/issues/58), Bevy
[#59](https://github.com/Er2oneousbit/claude-code-game-kit/issues/59), C++/SDL2
[#60](https://github.com/Er2oneousbit/claude-code-game-kit/issues/60), LÖVE
[#61](https://github.com/Er2oneousbit/claude-code-game-kit/issues/61), RPG Maker MZ
[#62](https://github.com/Er2oneousbit/claude-code-game-kit/issues/62). The umbrella, a manifest spec with golden
fixtures that every loader is tested against: [#83](https://github.com/Er2oneousbit/claude-code-game-kit/issues/83).

### Audio (Wavesmith) follow-ups
- **Not run:** either `audio.yml` on GitHub, macOS or Python 3.10 ([#75](https://github.com/Er2oneousbit/claude-code-game-kit/issues/75), a sibling of #40); voice and sfx
  off NVIDIA (Apple, AMD) ([#76](https://github.com/Er2oneousbit/claude-code-game-kit/issues/76)); RPG Maker MZ's GameAudio.js inside MZ ([#78](https://github.com/Er2oneousbit/claude-code-game-kit/issues/78)).
- **Planned:** a music-render subcommand for ACE-Step 1.5 ([#80](https://github.com/Er2oneousbit/claude-code-game-kit/issues/80)); a listen-and-rate page for takes, and a
  check of the deep babble presets for clicks between blips ([#94](https://github.com/Er2oneousbit/claude-code-game-kit/issues/94)).
- **Open question:** may the kit's examples ship Stable Audio output ([#92](https://github.com/Er2oneousbit/claude-code-game-kit/issues/92))?

### Ideas and evaluations
- **img2threejs:** code-only Three.js models from a reference image, for web-3d and image to 3D ([#71](https://github.com/Er2oneousbit/claude-code-game-kit/issues/71)).
- **Gameplay visual review:** Claude reviews smoke screenshots against the art direction ([#72](https://github.com/Er2oneousbit/claude-code-game-kit/issues/72)).
- **Experiments:** does the kit save tokens ([#19](https://github.com/Er2oneousbit/claude-code-game-kit/issues/19)), and does the SOP-09 smoke checklist cut bugs ([#20](https://github.com/Er2oneousbit/claude-code-game-kit/issues/20)), each as an A/B run.

### Planned
- **Steam:** a platform-services layer with a null backend and one adapter per engine
  ([#84](https://github.com/Er2oneousbit/claude-code-game-kit/issues/84)); an automated Steam Deck pass ([#85](https://github.com/Er2oneousbit/claude-code-game-kit/issues/85)); `dev.py ship` for
  SteamPipe and itch.io with a dry run ([#86](https://github.com/Er2oneousbit/claude-code-game-kit/issues/86)).
- **Localization round trip:** export, local-model drafts, review, re-import and checks
  ([#87](https://github.com/Er2oneousbit/claude-code-game-kit/issues/87)).
- **Checks:** frame-time budgets in smoke and CI ([#90](https://github.com/Er2oneousbit/claude-code-game-kit/issues/90)); an automated accessibility sweep of the shell
  screens ([#91](https://github.com/Er2oneousbit/claude-code-game-kit/issues/91)).
- **Starting a game:** genre starters with a tested core loop ([#89](https://github.com/Er2oneousbit/claude-code-game-kit/issues/89)).
- **Examples:** bring them onto the 0.8 systems ([#88](https://github.com/Er2oneousbit/claude-code-game-kit/issues/88)); designed-voice dialogue in one example
  ([#93](https://github.com/Er2oneousbit/claude-code-game-kit/issues/93)).
- **Kit tools for recurring jobs:** `/file-issue` and `issues.py new` [#156](https://github.com/Er2oneousbit/claude-code-game-kit/issues/156); `publish_check.py` over a commit
  range and a private term list [#157](https://github.com/Er2oneousbit/claude-code-game-kit/issues/157); a script that runs every exam on the supported Pythons [#158](https://github.com/Er2oneousbit/claude-code-game-kit/issues/158); one that runs
  every example's doctor, check, test and smoke [#159](https://github.com/Er2oneousbit/claude-code-game-kit/issues/159).
- **Game feel:** recipes for common effects built from the juice primitives, added per game as needed [#170](https://github.com/Er2oneousbit/claude-code-game-kit/issues/170);
  shooting effects (muzzle flash, tracer, firing light, wall debris) [#164](https://github.com/Er2oneousbit/claude-code-game-kit/issues/164); a blood on/off setting [#171](https://github.com/Er2oneousbit/claude-code-game-kit/issues/171).
- **Accessibility:** screen reader and menu narration [#165](https://github.com/Er2oneousbit/claude-code-game-kit/issues/165); motor access beyond remapping [#166](https://github.com/Er2oneousbit/claude-code-game-kit/issues/166);
  cognitive access [#167](https://github.com/Er2oneousbit/claude-code-game-kit/issues/167); shell screens for Unity, Unreal, Bevy and C++ [#168](https://github.com/Er2oneousbit/claude-code-game-kit/issues/168); colour-blind modes tested
  beyond the demo palettes [#169](https://github.com/Er2oneousbit/claude-code-game-kit/issues/169).
- **RPG Maker MZ and web-3d:** the juice and shell modules the other overlays ship
  ([#175](https://github.com/Er2oneousbit/claude-code-game-kit/issues/175)).

### Never run or not run end to end
- **macOS and Linux:** untested throughout (the scaffolder ran on Linux in an earlier version only). Tool and binary
  names for GIMP and Inkscape on those systems are unverified ([#12](https://github.com/Er2oneousbit/claude-code-game-kit/issues/12)).
- **RPG Maker MZ overlay:** never run against RPG Maker MZ (it was not installed). Checked only against a fake MZ
  project; the editor side (Plugin Manager annotations, `js/plugins.js`, Deployment, `run --editor`) is marked (verify).
- **Unity:** `run` opens the editor, but on the test machine it stopped at Unity's Hub sign-in, so a loaded editor is
  not confirmed. Batchmode commands are unaffected.
- **Unreal:** `package` on a Blueprint-only project is not verified (C++ projects are).
- **Bevy:** Windows only (Linux needs ALSA and udev dev packages, named in the docs but not tried); a web (WASM)
  build is not wired into `dev.py`; the starter moves in fixed 1/60 s ticks with no render interpolation, so motion
  can look uneven on high refresh rate screens; `--features dev` (dynamic linking) was not tried.
- **Skills no new user has run yet:** `/next-tier` (dry run on Crimson Nebula stopped at the toy as it should: no human playtest; not yet run on a real game
  at a tier change), `/procgen` on a fresh game, `/triage-issues` on a real game's issues. The Bug
  and Feel issue forms parse, but nobody has looked at them rendered on GitHub.
- **Web and web-3d overlays:** run only in Chromium (headless and headed). Firefox, Safari and mobile browsers are
  untested, and their audio formats differ.
- **Local AI:** only on an RTX 5060 Ti. Other GPUs, CPU-only and browsers other than Chromium are untested.
- **Graphics drawn in code** (`tools/art/pixel_sprite.py`): exam passes, not yet used inside a game build.
- **`tools/art/chroma_key.py`:** tested on synthetic images, not on real AI sprites.

- **`tools/art/dotwork/`:** model lanes ran on one machine only (RTX 5060 Ti 16 GB, 64 GB RAM, Windows 11), and only
  Godot gets engine resources (`--engine none` gives PNGs, sheets and the manifest). The model's in-between rotation
  views stay approximate; back views and faceless designs cannot be checked for facing (`rot_swap` fixes a pair by
  hand). The art flaws found in 0.7.0 review (#22 to #28) are fixed in 0.7.1. Skeleton clips: walk, run, idle,
  attack, jump, cast and shoot ran live on one test character (front and back strikes read weakly, see the README's
  characters (skeleton) row); hurt and death are not rendered live yet.

### Tools with commands not yet run live
- **`tools/art/comfy_local.py`:** `check` (with `--workflow`) ran live against ComfyUI 0.43.0; `run` and `strip`
  only against the exam's stand-in server. A real `run` of a SpriteKiln workflow is the next step.
- **`tools/art/pixellab.py`:** `image`, v3 `character`, `animate`, `animate-character`, top-down `tileset`, `ui`,
  `font`, `object`, `pixelate`, `tiles-pro`, `outfit`. It also lacks PixelLab's newer Pro Flash models, style images
  and pinned last frames (the MCP server has them; SOP-16 says which tool to use; [#16](https://github.com/Er2oneousbit/claude-code-game-kit/issues/16)).
- **`tools/audio/wavesmith/eleven_audio.py`:** music is tested offline only (the live music request returned HTTP 402, "not available").
- **`tools/second_opinion.py`:** only the Kimi Code CLI is supported.

### Bugs and doubts
- **Docs marked (verify):** facts about outside services (prices, plans, menu paths, license terms) that were not
  checked live. They are the most likely to be out of date.
- **Tools without an exam:** `core/.claude/hooks/session_context.py`, `tools/art/frames_to_gif.py` and several Dotwork helpers ([#14](https://github.com/Er2oneousbit/claude-code-game-kit/issues/14)).

## The examples
None of the example games has been played by a human tester; the bots and tests are the only proof they play as
intended ([#21](https://github.com/Er2oneousbit/claude-code-game-kit/issues/21)). Their art and audio are for non-commercial use (`examples/LICENSE.md`). Each game's own
`docs/HANDOFF.md` "Known broken or flaky" carries its items below.

### Gatekeeper (Godot): review findings fixed, some proven only without the model
From an adversarial review (Claude Fable 5.1, 2026-10-26); the web twin got the matching fixes first.
Fixed in 0.8.3: the model load and restart lifecycle (#1), the line typed while the guard thinks (#2), model errors
and timeouts (#3: an error or two timeouts in a row hand the session to the scripted guard; history calls and
`reset()` time out too; proven with a stand-in chat, the load path itself still needs the real plugin), the voice
cache written before the reply was checked (#4), the checks that could not fail (#5: `--llm --autoplay` exits 1 on
the scripted guard, the after-the-end rule test compares with a snapshot, the eval counts only labels from the
model, and the three rule tests the web twin had are here too), the exported build's developer hint and the
autoplay exit leak (#6).
- An exported build with the real plugin, and the model in `models/` next to the game, has not been tried (the
  `.gdextension` library export and the model load from there are (verify)).

### Rune Delve (Unreal)
- **Balance at its limit:** after the review fixes the weaver bot clears 3 of 8 dungeons (was 5) against the
  masher's 0; the pair test passes exactly on its thresholds and now says so (a margin line and a warning). Retuning
  the ward waits for a human playtest ([#7](https://github.com/Er2oneousbit/claude-code-game-kit/issues/7)).
- Replays under `-nullrhi` (no renderer) differ from rendered runs, and two `-nullrhi` runs can differ: every bolt
  dirties the runtime NavMesh, which rebuilds in real time. Taking bolts off the NavMesh made rendered and `-nullrhi`
  runs match on 8 seeds but made the editor's bot pair vary from run to run, so it is not in
  (`docs/TROUBLESHOOTING.md`, [#8](https://github.com/Er2oneousbit/claude-code-game-kit/issues/8)).
- Sight and bolt noise never cross an open gate, so the next room's orcs sleep through a fight at its door. Letting
  them through moved the bot pair from weaver 65 / masher 55 (3 of 8 clears against 0) to 77 / 52 (7 against 0),
  so it waits for a balance decision ([#140](https://github.com/Er2oneousbit/claude-code-game-kit/issues/140)).

### Graveyard Shift (Unity)
- The bot trio is not quite repeatable: two ghosts close together can part by a millimeter between runs, so
  always-lit's hand-made catches read 12 or 14 (cause not found; probably not physics timing or job threads;
  [#160](https://github.com/Er2oneousbit/claude-code-game-kit/issues/160)). Careful and
  always-dark now replay exactly, so `Smoke_D` at the 104 cap no longer flakes (#9, fixed in 0.8.3).
- Generated nights are easier than the hand-made yard (the dark bot escapes 6 of 8 generated against 2 of 8).
- A low rock the ghosts' NavMesh climbs (0.75 m) blocks the keeper's CharacterController (0.3 m); the fix moved the
  tuned balance and was reverted. Both wait for a balance decision ([#10](https://github.com/Er2oneousbit/claude-code-game-kit/issues/10)).
- Built with Mono only; IL2CPP builds were not made or compared.
- One of the two intro narrator takes (`narrator_intro_1`) still says "Gather all six" on a twelve-soul night: it
  needs re-voicing with the same voice, which is a paid generation
  ([#138](https://github.com/Er2oneousbit/claude-code-game-kit/issues/138)).

### Scrap Tanks (C++/SDL2)
- Scouts can never reach their RETREAT branch: one hit leaves them above the threshold and a second destroys them.
  Raising the threshold or lowering damage moved the cover-against-charging balance the pillar test checks, so it
  waits for a balance decision ([#152](https://github.com/Er2oneousbit/claude-code-game-kit/issues/152)).

### Lockpick (RPG Maker MZ)
- An untested proof of concept: it has never run inside RPG Maker MZ, only against stand-ins.

### Coyote Hop, Courier Dash, Ghost Lantern, Gatekeeper (web)
- No open bugs after their reviews. Not yet played by a human.
- Ghost Lantern's keeper and ghosts are placeholder sprites ([#17](https://github.com/Er2oneousbit/claude-code-game-kit/issues/17)).

# Known issues and untested parts

Everything known to be broken, flaky, unproven or never tried, in one place (2026-11-11). Fixed bugs are in
`CHANGELOG.md`; what *was* tested, and how, is the README table "What was tested and what was not". The kit and the
examples were built and tested on one Windows 11 machine.

## The kit

### 0.8.0 follow-ups (juice, shell, LÖVE, CI)
- **CI workflow** not yet run on GitHub-hosted runners (Actions is disabled on this repository, so it cannot run
  until that is turned on): [#40](https://github.com/Er2oneousbit/claude-code-game-kit/issues/40).
- **LÖVE:** macOS and Linux packaging, LÖVE 11.4 itself and the POSIX save rename not run: [#41](https://github.com/Er2oneousbit/claude-code-game-kit/issues/41).
- **Unreal:** turning the GameKitShell plugin on the way the Plugins window does (its `.uproject` entry) is verified
  headless in a Blank Blueprint project on UE 5.8 (`check` builds both modules, `test` passes); the window itself, the
  restart and the editor's "modules are missing, rebuild?" prompt are not tried
  ([#47](https://github.com/Er2oneousbit/claude-code-game-kit/issues/47)).
- **Shell screens** ship for Godot, LÖVE, web, web-3d (web's shell over Three.js since 0.14.5), Unity, Unreal, Bevy
  and C++/SDL3; RPG Maker MZ keeps MZ's own screens and gets the juice and shell rules as plugins and the accessibility
  settings on MZ's Options screen (0.14.5, checked against stand-ins only:
  [#280](https://github.com/Er2oneousbit/claude-code-game-kit/issues/280)). Credits screens show Markdown marks as
  typed, and `show:credits` exists only on Bevy and Unreal
  ([#284](https://github.com/Er2oneousbit/claude-code-game-kit/issues/284)). Display settings the browser cannot
  apply (vsync, resolution) are stored only.
  The four new shells (#168) were checked by their drives, tests, sweep and screenshots, never played by hand: no
  real gamepad pressed, no narration heard, no `dev.py run` session. Unity reads bindings on both the Input Manager
  and the Input System (0.14.4), but the Input Manager's d-pad and trigger axes (6, 7, 9, 10) are the Windows layout
  (verify), and there is no line spacing inside one wrapped paragraph; Unreal's screens were not tried in a running
  game or PIE (viewport focus, input mode, Quit), on Windows every pad reports as an Xbox one (XInput or GameInput;
  PlayStation glyphs need the WinDualShock plugin), and nothing speaks its narration lines yet; Bevy's exclusive
  fullscreen keeps the monitor's video mode instead of `display.resolution`; C++/SDL3's text is SDL's 8x8 ASCII font
  (English only, `readable_font` is bold, its pseudo locale is ASCII, non-integer text sizes look uneven). Since 0.14.4
  all four have crash files, the F8 bug report, the pseudo-locale drive and the juice demo; Unreal's crash drive plants
  its error rather than crashing the editor (an unattended editor crash can upload a report to Epic), so the hook has
  not run on a real fatal error (verify); C++'s juice demo draws no shake angle; Bevy's shell plays no sounds, so its
  demo has no hit sound or caption ([#168](https://github.com/Er2oneousbit/claude-code-game-kit/issues/168)).
- **Analog input** reaches the game through the shell in every engine with one since 0.14.4 (#274); it is tested
  with injected pads and models only, never a physical pad.
- **Frame-time budgets** (0.14.5): every smoke reports frame times and fails a p95 over budget; headless runs measure
  logic only, the starters have no stress scene (an idle prototype is measured), there is no CI baseline, Unreal's
  smoke says "not measured" (no frame-sampling Smoke test ships) and headless Chromium cannot go below about 16.7 ms
  ([#281](https://github.com/Er2oneousbit/claude-code-game-kit/issues/281)).

### 0.8.1 follow-ups (Dotwork)
- **Cyrillic glyph font** not made (the `bdf` lane may already cover it with an OFL font, untried):
  [#51](https://github.com/Er2oneousbit/claude-code-game-kit/issues/51).
- **Store art** not yet checked by a real Steamworks upload:
  [#52](https://github.com/Er2oneousbit/claude-code-game-kit/issues/52).
- **UI kit prompt glyphs** are generic; swapping in official console glyphs is not documented or tested:
  [#53](https://github.com/Er2oneousbit/claude-code-game-kit/issues/53).
- **Hand polish (Aseprite, Pixelorama):** an edit made by a person
  in either editor's window is not tried yet ([#65](https://github.com/Er2oneousbit/claude-code-game-kit/issues/65)); spells, VFX, status marks, animated props, balloons and vehicles have no hand-polish path
  ([#68](https://github.com/Er2oneousbit/claude-code-game-kit/issues/68)).

### 0.14 follow-ups (shaders, C++ on SDL3, cloud deploy)
- **Shader recipes** match their golden images in all nine engines on one Windows machine; not checked: C++ on Metal
  and Linux, Unreal's translucent `M_Kit_*` assets and a Post Process variant, KitShaders.js inside a real RPG Maker MZ
  game, Unity HDRP, other GPUs, web exports of Godot and Bevy:
  [#260](https://github.com/Er2oneousbit/claude-code-game-kit/issues/260).
- **Cloud deploy** (`dev.py ship`, OpenTofu modules for AWS, Azure, GCP, Linode, DigitalOcean): validated offline
  only, never applied to a real account; Linode and DigitalOcean have no budget API (set an alert by hand); the
  least-privilege logins in `tools/cloud/README.md` are unchecked
  ([#252](https://github.com/Er2oneousbit/claude-code-game-kit/issues/252)).
- **Accessibility sweep** (`tools/access/sweep.py`): runs on Godot, LÖVE, web, web-3d, Unity, Unreal, Bevy and C++/SDL3
  (Unreal's report is in its 1920x1080 design with measured widths and no overlap boxes); the "play" placeholder scene is not in its tour; it checks what the engine reports, so a look at
  screenshots is still needed; a real Steam Deck (Proton, on-screen keyboard, suspend) is not tried
  ([#91](https://github.com/Er2oneousbit/claude-code-game-kit/issues/91),
  [#85](https://github.com/Er2oneousbit/claude-code-game-kit/issues/85)).
- **Cognitive and motor settings** have screens in all eight engines with a shell (see Shell screens above); the auto-repeat delay and interval
  (0.35 s, 0.15 s) are the kit's starting point, not from a source; the one-handed layouts are not tried with
  players who play one-handed.
- **Narration** (#165): the lines are checked, the speaking is not: no screen reader has been tried with the web page
  or Godot's AccessKit support (Godot 4.5+), and LÖVE's `say` and `spd-say` routes are untried on macOS and Linux;
  on Windows LÖVE opens PowerShell for each line, which can flash a console window
  ([#165](https://github.com/Er2oneousbit/claude-code-game-kit/issues/165)).
- **Second-model reviews** of Wavesmith's codecs and the tools listed in
  [#261](https://github.com/Er2oneousbit/claude-code-game-kit/issues/261) are done.
- **Godot under GPU load:** Godot 4.7.2 crashed in 2 of 5 windowed shader checks, and once in a font reimport, while
  other engines used the GPU (never alone); `dev.py` now says so; rerun, or `check --no-shaders`.

### 0.15 follow-ups (characters from an idea)
- **Paid routes measured once:** Tripo image tasks (10 credits each), a P2 model from views (110) and a rig with three
  clips (55) ran live on 2026-11-11; P1 models, text-to-model, high-quality textures and the direct Gemini route
  (needs a billed key) have only run against stand-ins (verify).
- **UV coverage:** the rebake lifted a 120-part Tripo character from 29% to 46%, under the hero floor of 60%; such a
  model ships with `--accept-uv` and a logged waiver until a packer can nest islands
  ([#293](https://github.com/Er2oneousbit/claude-code-game-kit/issues/293)).
- **Seen on screen or not:** a rigged character was loaded and its clips measured in every 3D engine, but only Godot
  and LÖVE (as sprites) were looked at; skinned drawing in a Bevy window and the web-3d page, Unreal playing the clips
  in a level, Unity's run-time load in a player build and URP 2D lights reading a normal map are (verify). The Godot
  2D route loads the sheets through Godot's importer (`DotworkAssets`, #307), checked in its GUT test against the
  golden character; the Godot starter does not draw it, so a rendered character walking in a Godot window is (verify).
- **Bevy projects sharing one `CARGO_TARGET_DIR`:** fixed for new projects in 0.15.1
  ([#294](https://github.com/Er2oneousbit/claude-code-game-kit/issues/294)): the shader check example is named after
  the game (`[[example]]` in `Cargo.toml`), so each game links its own `debug/examples/<slug>_shader_check.pdb`.
  `--upgrade` keeps a `Cargo.toml` the game edited (its `version` line), so a project from 0.15.0 or older still
  builds `shader_check` and shares that one `.pdb` until the `[[example]]` table from the fresh skeleton's
  `Cargo.toml` is copied in; until then, LNK1140 (`limit exceeded for program database`) means: delete that `.pdb`
  and build again.
- **Strip rebuild limits:** a fused scarf or cape rebuilt by `rig chain` loses folds, knots and fringes, and the
  original stays painted on the body under it.

### 0.15.1 follow-ups
- **Credits under reduce motion:** LÖVE and C++ seem to start a CREDITS.md taller than the text area below the
  visible area, found by reading the code, not run (verify)
  ([#302](https://github.com/Er2oneousbit/claude-code-game-kit/issues/302)).
- **Rebaked Tripo textures:** the rebake writes Tripo's JPEG colour maps as PNG, so a main file grows (5.0 to 11.5 MB
  on one character) ([#303](https://github.com/Er2oneousbit/claude-code-game-kit/issues/303)).
- **Gemini:** Google calls `generateContent` legacy and points to its Interactions API; moving needs a billed live run
  ([#304](https://github.com/Er2oneousbit/claude-code-game-kit/issues/304)). Whether `gemini-3.1-flash-lite-image`
  accepts `imageSize`, and whether image replies are always PNG, are (verify).
- **Not seen yet:** Unity's isometric showcase framing (#297) passed its bounds test but the scene was not opened on an
  isometric pack; Bevy's all-`#[ignore]` `[SKIP]` line is tested against cargo's summary format only (verify).
- **Flaky exam:** `scripts/test_dev_py.py` failed 7 cases once under a Bevy build's CPU load
  ([#305](https://github.com/Er2oneousbit/claude-code-game-kit/issues/305)).

### Art workflow outside Godot
Since 0.14.5 every engine reads Dotwork's asset manifest (`core/tools/art/dotwork/ASSET_MANIFEST.md`) through its
own importer, each tested against the golden fixture in `core/data/golden/dotwork/`; Godot too since
[#307](https://github.com/Er2oneousbit/claude-code-game-kit/issues/307) (`DotworkAssets`, for packs with no Godot
resources), and Dotwork's Godot map scenes now take the spec's variant pick, so a map shows the same tile in every
engine. Spec 1.1.0 (0.15.0, [#285](https://github.com/Er2oneousbit/claude-code-game-kit/issues/285)) defined the rules
the first importers left open (corners4 terrain layers, isometric placement, the variant pick, stamps layers, the
extra kinds per engine) and every importer follows them on the golden maps. Still true: a Godot map scene painted
before #307 keeps its old variants until its pack runs again; the Godot importer's TileSet has no terrain sets (paint
by hand with Dotwork's own TileSet), and the Godot starter draws no Dotwork art; a corners4 terrain shape thinner than
2 cells has no tile (the validator refuses the map; Godot's own painter improvises a one-corner tile there); RPG Maker
MZ converts no maps. Per engine (additive
blending in Bevy and Unreal, Unreal tile animation, Niagara and font kerning, MZ autotiles, maps and parallaxes,
Phaser multi-page fonts, and others):
[#286](https://github.com/Er2oneousbit/claude-code-game-kit/issues/286). The importers ran on the golden pack and the
model-free example packs, not yet on a real game's art.

### Audio (Wavesmith) follow-ups
- **Not run:** either `audio.yml` on GitHub, macOS or Python 3.10 ([#75](https://github.com/Er2oneousbit/claude-code-game-kit/issues/75), a sibling of #40); voice and sfx
  off NVIDIA (Apple, AMD) ([#76](https://github.com/Er2oneousbit/claude-code-game-kit/issues/76)); RPG Maker MZ's GameAudio.js inside MZ ([#78](https://github.com/Er2oneousbit/claude-code-game-kit/issues/78)).
- **Planned:** a music-render subcommand for ACE-Step 1.5 ([#80](https://github.com/Er2oneousbit/claude-code-game-kit/issues/80)); a listen-and-rate page for takes, and a
  check of the deep babble presets for clicks between blips ([#94](https://github.com/Er2oneousbit/claude-code-game-kit/issues/94)).
- **Open question:** may the kit's examples ship Stable Audio output ([#92](https://github.com/Er2oneousbit/claude-code-game-kit/issues/92))?

### Ideas and evaluations
- **img2threejs:** code-only Three.js models from a reference image, for web-3d and image to 3D ([#71](https://github.com/Er2oneousbit/claude-code-game-kit/issues/71)).
- **Gameplay visual review:** Claude reviews smoke screenshots against the art direction ([#72](https://github.com/Er2oneousbit/claude-code-game-kit/issues/72)).
- **Strata, a local LLM runner:** a `second_opinion.py` backend next to Kimi and the engine for local text drafts
  ([#206](https://github.com/Er2oneousbit/claude-code-game-kit/issues/206)).
- **Experiments:** does the kit save tokens ([#19](https://github.com/Er2oneousbit/claude-code-game-kit/issues/19)), and does the SOP-09 smoke checklist cut bugs ([#20](https://github.com/Er2oneousbit/claude-code-game-kit/issues/20)), each as an A/B run.

### Planned
- **Steam:** a platform-services layer with a null backend and one adapter per engine
  ([#84](https://github.com/Er2oneousbit/claude-code-game-kit/issues/84)); `dev.py ship` for SteamPipe with a dry run
  ([#86](https://github.com/Er2oneousbit/claude-code-game-kit/issues/86): the itch.io half is wired, `ship --target
  itch` with butler and a dry run, tested with a stand-in butler only, a real upload still to verify).
- **Localization round trip:** export, local-model drafts, review, re-import and checks
  ([#87](https://github.com/Er2oneousbit/claude-code-game-kit/issues/87)).
- **Starting a game:** genre starters with a tested core loop ([#89](https://github.com/Er2oneousbit/claude-code-game-kit/issues/89)).
- **Examples:** bring them onto the 0.8 systems ([#88](https://github.com/Er2oneousbit/claude-code-game-kit/issues/88)); designed-voice dialogue in one example
  ([#93](https://github.com/Er2oneousbit/claude-code-game-kit/issues/93)).
- **Kit tools for recurring jobs:** a coverage run over every exam, to find code no exam executes
  ([#282](https://github.com/Er2oneousbit/claude-code-game-kit/issues/282)).
- **Game feel:** recipes for common effects built from the juice primitives, added per game as needed [#170](https://github.com/Er2oneousbit/claude-code-game-kit/issues/170);
  shooting effects (muzzle flash, tracer, firing light, wall debris) [#164](https://github.com/Er2oneousbit/claude-code-game-kit/issues/164); a blood on/off setting [#171](https://github.com/Er2oneousbit/claude-code-game-kit/issues/171).
- **More local 3D lanes after Bozzetto:** tiling PBR materials on FLUX.2 klein
  ([#200](https://github.com/Er2oneousbit/claude-code-game-kit/issues/200)); motion reference video with Wan 2.2 in place of Seedance
  ([#201](https://github.com/Er2oneousbit/claude-code-game-kit/issues/201)).
- **A flagship game:** one small finished game that uses every lane (planning, 2D and 3D art, audio, game feel,
  quality checks) in one place, its making documented
  ([#204](https://github.com/Er2oneousbit/claude-code-game-kit/issues/204)).

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
  Godot gets engine resources straight from Dotwork; the other engines import its asset manifest (see "Art workflow
  outside Godot"). The model's in-between rotation
  views stay approximate; back views and faceless designs cannot be checked for facing (`rot_swap` fixes a pair by
  hand). The art flaws found in 0.7.0 review (#22 to #28) are fixed in 0.7.1. Skeleton clips: walk, run, idle,
  attack, jump, cast and shoot ran live on one test character (front and back strikes read weakly, see the README's
  characters (skeleton) row); hurt and death are not rendered live yet.

### Tools with commands not yet run live
- **`tools/art/comfy_local.py`:** `check` (with `--workflow`) ran live against ComfyUI 0.43.0; `run` and `strip`
  only against the exam's stand-in server. A real `run` of a SpriteKiln workflow is the next step.
- **`tools/art/pixellab.py`:** `tiles-pro`, `outfit` and the legacy 8-direction `object` (10 to 25 generations each,
  with no price check to ask first). Every other command has run live (2026-11-04, then 2026-11-13 for `vfx --pro`).
  Pro Flash (`--pro-flash`), style images and pinned last frames were added for
  [#16](https://github.com/Er2oneousbit/claude-code-game-kit/issues/16): image, object with a style image,
  character and 8-direction object from `--source-image-id`, and `animate --last-frame` ran live on 2026-11-13 (19
  generations); `edit` and `pixelate --pro-flash`, `ui --style-image` and `animate-character --end-frame` only against
  the exam's stand-in server. Pro Flash inpainting and target palettes stay MCP-only.
- **`tools/audio/wavesmith/eleven_audio.py`:** music is tested offline only. ElevenLabs offers its music API on paid
  plans only: on a free plan the request returns HTTP 402, "Music API is not available for free users" (retried
  2026-11-04 with credits left; a refused request spends none). Sound effects run live on the free plan.
- **`tools/second_opinion.py`:** only the Kimi Code CLI is supported.

### Bugs and doubts
- **Docs marked (verify):** facts about outside services (prices, plans, menu paths, license terms) that were not
  checked live. They are the most likely to be out of date.
- **Code no exam runs:** the 0.14.5 pass gave doctor, `frames_to_gif.py` and Dotwork's unrun commands exams; Dotwork's
  audition render and qa_pack's fallback for rows without a `source` still have none
  ([#282](https://github.com/Er2oneousbit/claude-code-game-kit/issues/282)).
- **Bozzetto:** TRELLIS.2 characters with baked textures
  landed under the `npc` class's 55% UV coverage floor on two seeds; 0.15.1's `--rebake auto` (the local default)
  lifts both to 59 and 60%, on those two models only so far
  ([#203](https://github.com/Er2oneousbit/claude-code-game-kit/issues/203)). `rig`: bipeds only; the Unity Humanoid
  route is untested. `rig retarget` (#205) is tested on Quaternius' Universal Animation Library (Standard) and in
  Godot only; the Mixamo path is documented but not tried (it needs an Adobe login), other Quaternius packs' rigs are
  unchecked, and twist about a bone's axis is matched only as far as the rest poses agree
  ([#205](https://github.com/Er2oneousbit/claude-code-game-kit/issues/205)).

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
- Nothing known broken. The ward window (0.45 s) is tuned by bots only: a human playtest decides
  ([#7](https://github.com/Er2oneousbit/claude-code-game-kit/issues/7)).

### Graveyard Shift (Unity)
- Generated nights are easier than the hand-made yard (the dark bot escapes 6 of 8 generated against 2 of 8).
- A low rock the ghosts' NavMesh climbs (0.75 m) blocks the keeper's CharacterController (0.3 m); the fix moved the
  tuned balance and was reverted. Both wait for a balance decision ([#10](https://github.com/Er2oneousbit/claude-code-game-kit/issues/10)).
- Built with Mono only; IL2CPP builds were not made or compared.

### Scrap Tanks (C++/SDL3)
- Hiding spots are judged by one line to the spot's centre (with a 0.35 m margin); sight itself counts hull edges.

### Lockpick (RPG Maker MZ)
- An untested proof of concept: it has never run inside RPG Maker MZ, only against stand-ins.

### Coyote Hop, Courier Dash, Ghost Lantern, Gatekeeper (web)
- No open bugs after their reviews. Not yet played by a human.

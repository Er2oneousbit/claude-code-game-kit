# Changelog

0.4.0 is the first public release. Versions before it were internal builds, renumbered from 2.x and 3.x into 0.x
(same order, same contents); 0.3.1 was the release candidate and was never published, so its work is in 0.4.0.

## 0.5.0 (2026-10-28): Bevy overlay
### New engine overlay: `bevy` (Bevy 0.20, Rust), asked for by a player after the first release
- **`engines/bevy/`:** `dev.py` with the full contract on cargo: `check` (rustfmt `--check`, then clippy on every
  target, or `cargo check` without clippy), `test` (`cargo test`, counts the `test result` lines; none ran is exit 2),
  `smoke` (headless, `--until`, `--fail-on`, `--timeout`, game options after `--`, `--screenshot` and `--record` as PNG
  in a window), `build` (release exe), `run`, `clean` (asks before deleting a `CARGO_TARGET_DIR` outside the project;
  never hangs), `doctor` (cargo, rustc against Bevy's `rust-version`, clippy, rustfmt, git, MSVC through vswhere,
  ALSA and udev on Linux). Builds run uncaptured so the long first compile shows progress; the game then runs
  captured with a timeout. A game that refuses its command line is exit 2, not a failed test.
- **Starter game, split for headless runs:** `engines/bevy/skeleton/src/game/mod.rs` is the simulation (`FixedUpdate` at 60 Hz, input only
  through an `Intent` resource, bots as `Autoplay` modes); `present.rs` next to it holds the camera, sprites and keyboard and
  is added only with a window; `app.rs` builds the App per mode. Smoke and capture runs step time by exactly one
  1/60 s tick per frame (`TimeUpdateStrategy::ManualDuration`, built from the same `Duration` as the fixed step), so N
  frames are N ticks on any machine. `logic/` is engine-free (math helpers, a seeded xorshift `Rng` whose sequence a
  test pins). Tests: 12 unit tests and 4 headless App tests (`engines/bevy/skeleton/tests/headless.rs`).
- **Gotcha 1 in its ENGINE.md:** Claude's Bevy knowledge lags the pinned version, so it checks APIs in the 0.20
  source under `~/.cargo/registry`. Writing the overlay hit three such changes (`On<Add<T>>` instead of
  `On<Add, T>`, `Replace` renamed `Discard`, events now `Message`s).
- Tested on Windows 11 (Rust 1.99.1, MSVC 14.44): every command, with six planted failures; the release exe ran from a
  clean folder with its console hidden (`windows_subsystem`) and `dev.py` still read its output; a missing asset fails
  a windowed smoke run but not a headless one, as gotcha 8 says. First build 14.5 minutes. Linux, macOS and web
  (WASM) untested (`KNOWN_ISSUES.md`).
- Bevy rows in SOP-06 (version source), SOP-14 (navigation and decisions), SOP-17 (seeded generation),
  `resources/audio.md` and `resources/learning-and-release.md`; Bevy in `CHOOSING_AN_ENGINE.md`, the README and the
  `make-a-game` engine table (Rust install check). `engines/_template/README.md` points code-only engines at it too.
- **Scaffolder:** Rust keywords and crate names (`fn`, `type`, `std`, `bevy`...) are reserved slugs, so a game named
  "Type" or "Bevy" gets `type_game`, a package name cargo accepts.

### New example: `examples/crimson-nebula` (Bevy)
- A neon kart racer made through the `make-a-game` interview: one loop, you against three bots over three laps, a lane
  closes on lap 2 behind a 2 s warning, a random change on lap 3, boost items. The race is engine-free Rust, so the bot
  pair runs in `cargo test`: the bot that reads the changes beats the one that ignores them on 20 of 20 seeds. 40
  tests, a full headless race in `smoke --until RACE_OVER`. No human playtest yet. Gallery and tested-table rows added.

### Kit gaps found while building the Bevy racing example (Project_Crimson_Nebula)
- **`smoke --record-from N` (Bevy):** `--record` always started at frame 1, so filming a moment 70 s into a race
  meant hundreds of frames nobody wanted. Other overlays still record from the first frame.
- **3D games got 2D art instructions:** FIRST_HOUR's fast lane and the make-a-game "crude on purpose" warning named
  only pixel-art sprites drawn with `pixel_sprite.py`. Both now give the 3D floor too (figures built from a few
  shapes, never bare boxes). Synced into the examples.

## 0.4.0 (2026-10-27): first public release
### `KNOWN_ISSUES.md`: every open bug and untested part in one place
- The kit's untested parts (macOS and Linux, real RPG Maker MZ, Unity `run` past the Hub sign-in, Blueprint-only
  Unreal `package`, PixelLab commands not run live, skills no new user has run) and each example's open items:
  Gatekeeper Godot's 12 unfixed review findings, Rune Delve's zero-margin balance and its `-quitatend` and `-nullrhi`
  quirks, Graveyard Shift's flaky `Smoke_D`, easier generated nights and Mono-only build, Scrap Tanks' center-to-center
  sight, Lockpick's untested status. Each game's `docs/HANDOFF.md` "Known broken or flaky" carries its own items.

### Security pass on the kit's own repo (`/publish-repo` and gitleaks 8.30.1)
- **False positives in every game:** gitleaks' `generic-api-key` rule read the SHA-256 hashes in `.game-kit.json`
  as keys (kit files with "key" in the name, `chroma_key.py`): 18 hits in the kit's history. Games now ship a
  `.gitleaks.toml` that keeps the default rules and skips only that file.
- **Unreal's Android File Server token:** Epic's templates put a `SecurityToken` in `Config/DefaultEngine.ini`, with
  network connections allowed. Rune Delve's was never live (no Android build, off in shipping); it now has network
  connections off and the token cleared. `publish_check.py` warns while both are set (exam 11/11), and SOP-13 says
  so. The kit's history was then squashed to one commit before going public, so the old token is gone.
- **Fix: `scripts/sync_examples.py` never synced `.claude/settings.json`** (not hash-tracked: `--upgrade` merged the
  kit's new rules into the work copy, but only tracked files came back). It now copies the merged file back when it
  changed; the examples got the `gh` rules this way, every rule they had kept.
- Result: `gitleaks git` finds nothing in the history, `publish_check` 0 FAIL, 0 WARN. The private repo takes pull
  requests from collaborators only; Issues stay open.

### Player reports from GitHub Issues: `/triage-issues`, `tools/issues.py`, Bug and Feel forms (17 skills)
- **Issue forms in every game** (`.github/ISSUE_TEMPLATE/`): *Bug report* (what happened, steps, how often, version,
  seed, platform, files) and *Feel or balance* (which part, what happened on screen before how it felt, kept playing
  or not, how far, an optional fix idea that is read but not obeyed). They ask what happened before what the player
  thinks of it, so observations stay apart from opinions.
- **`tools/issues.py`** (`check`, `list`, `show N`): reads issues through `gh`, read-only (it runs only `gh auth
  status`, `repo view`, `issue list`, `issue view`, `label list`). Reporter text is untrusted input, so it strips what
  a person cannot see but a model reads (ANSI escapes, control and bidi characters, zero-width, Unicode tag characters
  and variation-selector runs), warns when it removed any, fences every body and comment between markers with a random
  per-run nonce (a report cannot forge the end marker), skips comments GitHub hid as spam, and lists links without
  opening them. Exam 14/14 offline; live and read-only against a public repo.
- **`/triage-issues`** sorts reports (bug, feel, needs info, duplicate, out of scope, suspicious), runs bugs through
  `/bug-hunt` from the repro step, logs feel reports by issue number (not username) and tunes one value at a time with
  the game's bot or pillar checks before and after; a change from a single report is a proposal to the owner. Every
  reply, label or close is shown and needs a yes; `Fixes #N` in the commit closes the issue.
- SOP-03 "Reports from GitHub Issues", SOP-13 (Issues in the lock-down table; a public repo means anyone's text
  reaches Claude), the game's CLAUDE.md and the SOP index point to it.
- **Permissions** (`.claude/settings.json`): `tools/issues.py` is allowed (read-only), every `gh` write asks
  (`issue comment/close/edit/...`, `label`, `api`, `repo create/edit`, `release`), and `gh auth token`,
  `gh auth status -t` (both print the login token) and `gh repo delete` are denied.

### Two more Pixel Lab videos (E66: same creator as E07 and E61, grade C; E67: PixelLab's own tutorial, A for the features as its tool descriptions state them, D for its quality claims)
- **Vendor rule** in the evidence ledger's scale: a vendor's own docs or videos are A for what the product does
  (features, limits, prices, terms), while claims about how good its results are stay capped at D until an independent
  source or a kit test shows them.
- E67, SOP-16 tips: one style image across a whole set (Pro Flash), variants and states by chained edits, inpainting
  to separate layers for outfits, room on the canvas before a big motion, per-direction prompts and named effect
  colors on 8 directions, mirroring, a pinned last frame for clean loops, and PixMiniMax's pricing by canvas (132 px
  cheaper than 128 for long clips). `pixellab.py` lacks Pro Flash, style images and the last frame: the tips name the
  MCP tools.
- SOP-16 tips: the same developer compared both paths on one character (4-frame sheets from a general image tool,
  animated in code, walked stiffly and drifted; PixelLab's 8-frame walk was clearly smoother); make each character
  once and animate from it (`animate-character --from`); keep animation smoothness even across a game (a fluid hero
  beside choppy enemies looks wrong); Claude Desktop setup (the token goes in a config file, then a full quit).
- Left out: his "always allow" on the MCP's prompts (the kit asks per call), the unpriced higher tier, and how
  PixelLab works inside (his guess, not something he measured).

### Fable bug hunt, Coyote Hop (7 findings, all measured in the real scene; fixed)
- After the flag the fox could run off the level and fall forever, and coins still counted: controls lock at the
  flag, the fall check keeps running, coins after it are ignored.
- A buffered tap jumped full height (67 px against about 19 for a tap on the ground), and a second tap in the air cut
  the hop again: the jump is cut whenever it is not held while rising, once per jump.
- The camera panned back from the death point after a fall or R; `JumpMath` ignored the physics step (apex 64.22 px
  on paper, 67.16 in game; now an optional `dt` term); the speedrun clock ran from boot (now from the first input);
  R left the goal jingle playing and the fox facing left.
- 14 new GUT tests (10 fail on the old code), 38 in all; the bot is unchanged at 8.52 s, 11/11 coins, 0 falls
  (re-run by hand on Godot 4.7.2).

### PixelLab pixel art, opt-in (`tools/art/pixellab.py`), and three videos (E61 to E63)
- **`tools/art/pixellab.py`:** images, characters in 4 or 8 directions, animations of a frame and top-down tilesets
  (tile PNGs plus a tileset.json with each tile's corners for autotiling) from PixelLab's API; the token from
  `PIXELLAB_API_KEY`, never printed; prints each request's cost, polls background jobs, checks every PNG, extracts
  zips only inside `--out`; `--log` writes the ASSET_LOG row and evidence (prompt, plan, cost, SHA-256). Exam 17/17
  offline against the published spec. Live on the owner's trial: `check` and one 16 px `character --legacy` (1
  generation: 4 directions, 24x24 frames under `<out>/Idle/rotations/`); the other commands not yet run live.
- **SOP-16:** a PixelLab section: the tool, the official MCP server (`claude mcp add` run by you, not pasted into a
  chat; never allow-list its tools), and the cheapest-path-first rule (tip, E61). `gen-brief` runs an API tool the user
  approved instead of only handing over a prompt, one take first.
- **Evidence:** E61 (the Wingnut series: the slice was not fun until combat, a dungeon and Pixel Lab animation),
  E62 (one RTS prompt at every Opus 5.5 effort level, $3.80 to $70; a detailed brief at low cost what high did: a
  SOP-12 tip), E63 (a 3D AI animation roundup: video mocap needs a cleanup pass, a SOP-11 tip; five tools in
  `resources/ai-tools.md`).

### Pre-release review (an independent go/no-go read of the front door, each finding re-checked)
- **The front door is one word now: open the kit folder, open Claude Code, type `Start`.** Tested headless (Claude
  Code 2.1.302): a bare "Start" used to get "make a game or work on the kit?" (or, for the maintainer, a status
  report); the root CLAUDE.md and the `make-a-game` skill now treat it as a game request. START_HERE and the README
  give VS Code steps next to the desktop app and the terminal.
- **`make-a-game` interviews before it builds.** It greets the person (the kit kick-starts the two of you making a
  game), gives the project a random codename from the new `scripts/codename.py` (Project_<Color>_<Word>, re-rolled
  if that folder already exists next to the kit; real dice, since a model's "random" picks repeat), then asks thirteen
  questions one at a time as multiple-choice prompts (free text always allowed, "you decide" where it fits; the last
  asks for the author name, passed to `new_game.py --author`, Git's user.name offered as the default), and drafts a one-page plan under the GDD
  template's headings (three proposed pillars, core loop, toy scope, out of scope, assumptions to test). Only after
  a yes does it pick the engine and create the folder; the approved plan goes into the game's `docs/GDD.md`.
- **The examples' license line said all their assets are CC0.** The art is; most sound effects were generated on an
  ElevenLabs free plan (non-commercial), and Graveyard Shift's voices and music carry Fish Audio's and Suno's terms.
  `examples/LICENSE.md` and the README say so now.
- **Fix: the ElevenLabs free-plan credit lacked the required "elevenlabs.io".** ElevenLabs' help page: free-plan
  content you publish must carry "elevenlabs.io" or "11.ai"; Eleven Music is credited by name. `eleven_audio.py`
  now writes "Created in collaboration with ElevenLabs (elevenlabs.io)", and every example's credits were updated.
- START_HERE promised macOS 13+, Linux and 4 GB of RAM: now Windows 10+, tested on Windows, the others untested.
- "About 15 minutes" (no timed run behind it) became "your first session" in the README, START_HERE, the make-a-game
  skill and FIRST_HOUR. Nine examples, not eight, most with a GIF; `examples/README.md` lists lockpick-mz.
- CHOOSING_AN_ENGINE no longer says Godot export and Web `run` were untested; DISTILL_REPORT.md is labeled a
  2026-10-19 snapshot; the PROCGEN brief files are listed in the README; Godot's floor names the tested 4.7.2; the
  web examples ask for Node 22.12+; Lockpick MZ's files say "the owner" like the others.

### After the first build: play, take notes, paste them back
- The game's CLAUDE.md has a "When it first becomes playable" section: when the toy first runs (and after the slice or
  a big feature), Claude hands the game over: play it, write down what you like and what you don't, paste the notes
  back, and iterate from there. FIRST_HOUR's fast lane says the same; `/playtest-report` takes the owner's own notes
  without the tester interview; `make-a-game` previews the loop at the hand-over.

### "Crude on purpose" warning before the first build
- **Crude, not abstract** (the owner's first real game drew its characters as dots): characters and key objects get
  a recognizable figure (head, body, arms, legs, drawn in code or a CC0 placeholder via `fetch_asset.py`), never a dot
  or a bare shape; only floors, walls and level blocks stay boxes. Said in the game's CLAUDE.md, FIRST_HOUR,
  VERTICAL_SLICE, SOP-01, SOP-12, START_HERE and `make-a-game`.
- Mechanics before art (F4) used to live only in FIRST_HOUR. Now a warning box says it where it counts: under the plan
  in `make-a-game` before the "build it" yes, in the game's CLAUDE.md before the toy and the slice (placeholders only;
  no generated or bought art or audio for the toy unless asked), and in START_HERE. Polishing art for a game that
  turns out not to work wastes time, usage and money.

### While building: short updates and progress screenshots
- The game's CLAUDE.md asks for one short line per build step instead of a wall of text, and a screenshot after each
  step that changes the screen (`smoke --screenshot captures/progress/NN-<what>.png`), checked by Claude before it
  posts the link; a short GIF at the first playable build (`smoke --record`, `frames_to_gif.py`, Pillow on a yes).
  `captures/` is gitignored. Tested on a scratch web game: screenshot, 25 frames, a 6 KB GIF, nothing staged.
  Godot and Unreal have no `smoke --screenshot` yet: Claude says so and skips the pictures.

### First art drawn in code: `tools/art/pixel_sprite.py` (no more dots)
The owner's first real game was built from dots and shapes, and its first playtest verdict was "unplayable". A sprite
script written in another session (a 32x32 steampunk hero, walk and punch in four directions) fixed it at no cost.
- **`tools/art/pixel_sprite.py`** (standard library only): a sprite is a Python file that paints rectangles on a 32x32
  grid; the tool adds the outline and ground shadow, mirrors left to right, packs an atlas PNG with a JSON layout and a
  preview. `check` grades any atlas against the **first-art floor** (figure height, colors, fill, outline): dots, flat
  circles and one-color boxes fail. `example` copies the reference hero (`tools/art/sprites/example_hero.py`), the
  original script ported to the sprite-file format: 0 pixels differ across its 32 frames. Exam 10/10.
- **Every game draws its own characters:** a three-line brief from the GDD (silhouette, features and prop, palette)
  in each sprite file's header; the reference hero only teaches the technique, and building it unchanged warns.
- The game's CLAUDE.md, FIRST_HOUR, VERTICAL_SLICE, SOP-01, SOP-12, SOP-16, START_HERE and `make-a-game` make these
  sprites the minimum for a first build (3D: a modeled figure or a CC0 model); `check` must pass before a build is shown.

### Fable bug hunt, Rune Delve (7 findings, plus a README line; all fixed)
- **Fix: rooms 2 and 3 (warden included) could be sniped from a doorway:** a shot orc only woke if the mage stood in
  its room. A hit now always wakes it. **Fix: the ward blocked every swing in its window** (docs: one swing); a block
  now ends the ward. **Fix: damage landed on the first frame of the swing clip:** the clip now starts so its contact
  frame (0.25 s, measured) meets the hit.
- The warden no longer spawns on a grunt's tile (24 of 200 seeds; the test covers 300); the dash covers 650 cm at any
  frame rate with i-frames to the end; the mage ignores its own bolt; the bots see orcs by the room they stand in.
- Weaver 71 -> 65 of 80, clears 5/8 -> 3/8 (the multi-block ward was carrying it); masher unchanged (55, 0/8). The
  Pair test passes exactly on its thresholds. Not fixed yet: `-quitatend` exits 0 on MAGE_DOWN (UE 5.8 needs a
  forced exit for a non-zero code); `-nullrhi` replays differ (cause unknown, in TROUBLESHOOTING).

### Fable bug hunt, Graveyard Shift (10 findings, plus 1 the fixes exposed; all fixed)
- **Fix: a ghost near the start caught the keeper every frame after a respawn** (35 catches in a second, a soul each):
  tired ghosts never catch, and a 1.5 s grace follows a catch. **Fix: after a catch the lit keeper could slip out
  through the slowly closing gate** and be locked outside: the gate snaps shut.
- **Fix: "cover" counted props too low to hide behind** (crypts and graves under chest height): cover is now
  height-based, every generated yard changed (pins re-made, 250 seeds: 0 problems, 0 fallbacks). A broken first save no
  longer blacks out every launch; ghosts no longer freeze re-requesting a path each frame, and a search ends after 12 s;
  area seams belong to one area; ghost loop order uses an exact key; bot nights never touch the player's save; the
  property test checks the generator's rejects instead of its own filter; ghost corners stand in open ground (the
  new yards exposed one the NavMesh could not reach).
- Pillar holds: careful beats always-lit by 18 (hand-made) and 55 (generated); generated careful now escapes 5 of 8.
  Tests 101 -> 112, smoke 15 -> 20. `Smoke_D` (careful >= dark, both at the 104 cap) is flaky by one night: noted.
  The docs/procgen pictures show pre-fix yards.

### Fable bug hunt, Courier Dash (6 findings, no high; fixed)
- **Fix: the robot could stay in "search" forever** when it last saw the courier in a pocket it does not fit (between
  a small tree and the fence): it now searches the nearest spot it can reach, with an approach timeout. A chase pinned
  on a tree corner paths around (or gives up to search) after 0.5 s without progress.
- **Fix: the `?debug` path line never drew** (Three r186 cannot grow a buffer made empty): preallocated now.
- The clock counts integer steps (90 s is exactly 5400) and a delivery in the step the clock runs out does not win;
  keys held through a restart no longer start the next run at once; GDD pillar 1 says what the game does (touching
  the robot always ends the run; it chases only what it saw). Tests 53 -> 60; every documented margin unchanged.

### Fable bug hunt, Scrap Tanks (6 findings; 5 fixed, 1 documented as a known limit)
- **Fix: raiders froze** for up to 7 s (48 of 80 scenario fights) on firing spots inside a nav-grid island the
  pathfinder cannot reach. The grid now knows what is reachable from the player start, the spot pickers skip the
  rest, and a tank with no path drives straight at its goal.
- **Fix: a shell that reached a crate first still damaged the tank behind it** (a human aiming at a hull edge); the
  earliest blocker now stops the shell. Also: `--seed` refuses negative and overflowing numbers, a stray Mix_Init
  is gone, stale "Ogg" wording fixed; center-to-center sight on a 1.9 m tank is written down as a known limit.
- The pillar holds: cover 25/40, charging 11/40 (was 10), the same in debug and release; the smoke seed moved from 4
  to 7 (the cover bot now loses seed 4). Tests 41 -> 46 cases; the five new ones fail on the old code.

### Fable bug hunt, Gatekeeper web (9 findings, 4 proven with failing tests; fixed)
- **Fix: "Start over" while the guard was thinking applied the old reply to the new game:** with "Captain Wren
  sent me" in flight, the new game began at trust 65 and one greeting opened the gate, the one-line win the design
  forbids. Replies from an earlier run are dropped now.
- A model load that stalls (no progress for 60 s) or a worker that fails to start falls back to the scripted guard
  instead of a stuck page; an engine error, or two timeouts in a row, switch the session to the scripted guard (a dead
  model cost 12 s per line); a line typed while the guard thinks stays in the box; no doubled intro; a double click
  on Start over restarts once; player lines are cut to MAX_INPUT before they are stored or sent.
- The real-model scenario fails on any fallback now (`--fail-on "FALLBACK,(fallback),model failed to load"`): it
  passed even when the scripted guard did the work. Tests 42 -> 58, including "no single line opens the gate".

### Adversarial review of the new tools (Fable, 16 findings, all proven or reasoned; fixed)
- **Security, `pixellab.py`:** the token no longer follows a redirect to another host (urllib copies headers on
  redirects; proven with two local servers, now a test); downloads and zip members are capped in size and limited to
  expected file types and names (no `desktop.ini`, `.exe` or `a.png:stream`); broken base64, cut-off answers and
  over-long names are service failures, not crashes.
- **`pixellab.py` correctness:** `edit`/`fix` no longer use (and delete) a `<name>_job` folder; a character zip that
  answers 423 is waited for, and a new free `fetch --character-id` collects a paid character later; multi-direction
  animations report the summed cost; `--overwrite` removes the previous run's files; `--log` destinations, a file in
  place of a folder and `prop` under 32 px are refused before anything is spent. Exam 30/30 -> 38/38.
- **`pixel_sprite.py`:** malformed or oversized PNGs are a clean `[error]` (they crashed or could ask for tens of GB);
  a dark figure with a proper outline passes the floor; a leftover preview stops the build before anything is
  written. Exam 10/10 -> 13/13.
- **Godot capture:** bursts are timed in real milliseconds (monitors are not all 60 Hz) and old frames are cleared
  first (a second, shorter recording counted the first one's frames). **`codename.py`:** a folder named "Project
  Ivory Golem" now blocks Project_Ivory_Golem, matching the scaffolder's slug.

### `pixellab.py` covers the rest of PixelLab
- New commands: `animate-character` (template or skeleton-v3 motions on a character made by `character`, whose id is
  now saved in its pixellab.gen.json), `vfx`, `ui`, `font`, `object` (1 or 8 directions), `prop`, `edit`, `pixelate`,
  `fix` (reduce colors, correct, unzoom, remove background, normal map), `iso-tile`, `tileset --kind sidescroller`, and
  `tiles-pro` and `outfit`, marked **[paid plan only]** as PixelLab rules it. Results that come as storage links are
  downloaded without the token (it goes only to the API host) and checked to be the file type they claim.
- Exam 17/17 -> 30/30. Live on the owner's new Pixel Apprentice plan (6.1 generations): prop, vfx, iso-tile, sidescroller
  tileset, edit and fix work; the live run found that `GET /map-objects/{id}` answers 423 while generating (now polled
  as "still working") and that a sidescroller tileset costs 2, not 1. SOP-16 lists every command with its cost and the
  owner's game's lessons (fix the base sprite first; template animation drops big props, skeleton-v3 keeps them).

### Screenshots and bursts on Godot (from the owner's game's kit feedback)
- Godot's `smoke` gains `--screenshot FILE`, `--record DIR` and `--record-every MS`, like web: after the headless smoke
  passes, the new `tools/capture.gd` runs the main scene in a real window (headless Godot renders nothing) and saves
  the last frame and/or a frame every N. Verified on Godot 4.7.2 with a moving test node (30 frames, real motion, GIF).
- The game's CLAUDE.md: anything that moves (an attack, a jump, a walk) is shown as a burst and GIF, not a still.
  Unreal still has no capture option.

### Fix: Godot pixel scaling (from the owner's game's kit feedback)
- The Godot template left `canvas_items` stretch with Godot's default aspect and fractional scale, though ENGINE.md
  promised integer scaling: on a 3440x1440 screen, wide black bars and uneven pixels. It now sets `viewport`,
  `expand`, `integer` on the 640x360 base (divides 720p, 1080p, 1440p, 4K) and a 1920x1080 window; ENGINE.md says a
  3D game switches to `canvas_items`. Read back with a ProjectSettings probe in Godot 4.7.2; `check` and `smoke` pass.

### Kimi bug hunt, Ghost Lantern (4 findings: 2 fixed, 1 a doc fix, 1 a design choice)
- **Fix: escaping and being caught in the same frame ended the run as "caught"** (and two ghosts in reach logged two
  catches). Ghosts no longer move once the run has ended, and a run ends once.
- Ghost think and repath timers keep their leftover time, so ghosts decide at the same rhythm at any frame rate.
- The GDD's "death restarts the room instantly" now says one key (R) does; the smoke scenarios rely on the caught
  state staying on screen. The 0.05 s frame-time cap stays: it is there so a stalled tab cannot teleport the player.
- Re-proved: check, 40 tests, and the scenario pair on seeds 1 to 6 (lantern bot escapes 6/6, dark bot caught 6/6).

### Kimi front-door review (README, START_HERE, CHOOSING_AN_ENGINE: 12 findings, 11 confirmed or partly)
- README quick start: the setup commands say to run inside the new game folder, and `python3` on macOS/Linux; the MZ
  bullet under "Already have a project?" says no `--adopt`, and Deployment is (verify); the opening line says six
  engines are tested and MZ is a proof of concept; Unreal `run` and `genproj` are listed as verified (Rune Delve), the
  second-opinion exam as 24/24.
- START_HERE: VS Code steps for moving into the game folder; Unity and Unreal open their editor (press Play); the
  "about 20 minutes" setup estimate is gone (no timed run). CHOOSING_AN_ENGINE: Blueprint-only Unreal packaging and
  web-3d `clean` are named as untested.

### Kimi on-ramp review (make-a-game, codename.py, the game's CLAUDE.md, FIRST_HOUR: 12 findings, all confirmed or partly)
- `make-a-game` checks Node for RPG Maker MZ too (its setup, test and smoke need it), and re-rolls the codename when
  the game goes somewhere other than next to the kit and the name is taken there.
- **`codename.py`:** files count as taken names, a `--check-dir` that is a file or unreadable is an error (exit 2)
  instead of a silent pass, and the pick is made among the free names, so "no free name" means exactly that.
- The game's CLAUDE.md: "run the game" on Unity and Unreal opens the editor (press Play); a project without tests
  records the gap instead of being stuck; C++/SDL2 screenshots are `.bmp`; each GIF gets its own frames folder and
  file, so the second one no longer fails or picks up old frames.
- FIRST_HOUR: a game from the interview skips the brainstorm and reviews its approved GDD instead; paid mockups only
  after the budget row and a priced first take; Unity and Unreal "press Play".
- `/start-session` no longer runs git in a folder without Git.

### Kimi docs review, SOP-15 and SOP-17 (8 findings: 7 confirmed or partly, 1 refuted)
- **SOP-15 promised a model mistake costs "a weird line of text", while the Gatekeeper examples let the model's intent
  label move trust.** It now says so: treat a label that feeds the rules like a button the player may fake and bound it
  (no single line opens the gate there; two can, by design). publish_check is described as printing names and line
  numbers only; the fine-tune data size and a WebLLM doc claim are marked (verify).
- **SOP-17 checked reachability against the NavMesh only,** though its own example had a rock the NavMesh walked and
  the character controller could not: walk a sample through the player's controller too. Engine quirks in the
  Godot and RPG Maker MZ rows (also SOP-14's Godot row) are marked (verify).

### Kimi docs review, SOP-13, SOP-14, SOP-16 (14 findings, all confirmed or partly)
- **Fix, SOP-13: the fresh-history steps could push the old history.** `git checkout --orphan` had no branch name and
  the old `main` was never replaced; now: orphan branch, commit, delete and rename to `main`, check `git log` first.
- **Fix, SOP-13: README screenshots went in after the repo was public.** They are added and checked for desktops,
  paths and emails while it is still private. The "read, don't reuse" license row is a `LICENSE` saying all rights
  reserved (publish_check fails without a LICENSE); GitHub menu paths and Suno/Udio terms are marked (verify).
- **Fix, SOP-16: re-exports failed.** Every art tool refuses to replace an output without `--overwrite`; the SOP says
  so, and the sprite-sheet row shows the real Blender launch line. PixelLab's trial size, test status and license
  are sourced (E61, K01) or marked (verify).
- SOP-14: "none built in" claims marked (verify), "old but stable" became "no recent release" (E40 judges licenses
  and versions, not quality), the C++ row cites E40, the E54 line is a tip, and a kit-only example path is named in words.

### Kimi docs review, SOP-09 to SOP-12 (4 findings, all confirmed; SOP-09 and SOP-10 clean)
- SOP-12: every job ends with `check` and `test` (plus `smoke` or a scenario when it touches the running game), as the
  game's CLAUDE.md already required; the model-role table marks model names and prices (verify).
- SOP-11: the creature pipeline is labeled tips (F16 is grade C); the mocap license note cites the new E65 (the
  Motion2MixamoRig and Prompt2Rig READMEs, grade A, re-read before shipping).

### Kimi docs review, SOP-05 to SOP-08 (2 findings, both confirmed; SOP-06 and SOP-08 clean)
- **Fix: Unreal projects did not send fonts, .glb/.obj models, .flac, .jpeg, .tif, .hdr or .aseprite through Git LFS.**
  The overlay's `.gitattributes` replaces the core one; it now carries every core pattern too.
- SOP-07: bypass-permissions mode is no longer called "popular in videos" (one grade-C video, E27).

### Kimi docs review, SOP-01 to SOP-04 (each finding re-checked)
- **SOP-04, AI disclosure:** the Steam "AI-assisted development" example no longer lists scaffolded code (AI-written
  code that ships is output in the build: a (verify) note says to check where the current form puts it); itch.io is
  answered from its own categories, where shipped AI code counts under Code, not from the Steam buckets; the video's
  rules of thumb are labeled tips (E22, grade C); the plan-or-tier note carries (verify); the naming step says RPG
  Maker MZ has folder and format rules instead of file prefixes.
- **The citation rule says what the kit does:** claims from outside sources or tests (a video, a doc, a measurement, a
  number) cite an `E##`/`F##`/`K01` and follow the grades; standard engineering practice is uncited. It used to say
  "every rule", which no SOP followed (SOP-01 to SOP-03 cite nothing; about 1 in 10 bullets elsewhere). CLAUDE.md,
  EVIDENCE.md, the SOP index and the README.
- **SOP-02:** "Done when" asks for a test that fails without the fix, or, where none is feasible, the smoke run or a
  written manual check.

### Blender scripts: exit codes and version drift (E64)
- **Fix: a crashed Blender script exited 0.** Without `--python-exit-code 1` (before `-P`) Blender returns 0 after a
  traceback (tested on 5.2.2; after `-P` the flag does nothing). The Blender tools catch their own errors, but
  `--debug` re-raises and import errors escape. Every documented launch line, the three Blender exams and SOP-11 now
  pass it. It caught one at once: `test_prep_export.py` crashed under `blender -P` (the script's folder is not on
  `sys.path` there, only under the `bpy` wheel) and had been reporting exit 0; fixed, 17/17 in both.
- **Fix: `render_sprites.py --engine eevee` on Blender 4.2 to 4.5,** where EEVEE's id is `BLENDER_EEVEE_NEXT`: it tries
  both ids now.
- **SOP-11:** a tip block for Claude-written `bpy` scripts (name the Blender version, data API over operators, boolean
  solvers, units, measure before rendering, generate/critique/patch) and an unguarded-code warning on Blender MCP
  servers; the video-mocap tip gains a license check (SMPL-X, GVHMR and MANO weights are non-commercial by default).
- **Evidence:** E64 (an X article on models writing Blender Python; the claims that held on 5.2.2 are K01, two that did
  not were left out). E63 corrected: Motion2MixamoRig, Charakuru, Prompt2Rig as its own row with repo links.

### New engine overlay: `rpgmaker-mz` (RPG Maker MZ), an untested proof of concept
Asked for by the owner ("add in rpg maker"); built on a machine without RPG Maker MZ, so every step that needs the
editor or the engine is marked (verify) and the README, the engine chooser, the make-a-game skill and the example label it an untested proof of concept.
- **Layout:** the MZ project lives in `game/` (the editor's Deployment then exports the game, not the kit). The kit
  ships none of MZ: `rmmz_core.js` carries no license (unlike MV's MIT core), so `dev.py setup --from <a new MZ project>`
  copies MZ's own files in from your install, never over yours, and registers the game's plugins in `js/plugins.js`.
- **Plugins:** `GameCore.js` holds the rules with no RPG Maker objects, so Node's test runner loads the same file the
  game does; `GameMain.js` is the glue. `engines/rpgmaker-mz/skeleton/tests/support/mzFake.js` runs a glue plugin against small stand-ins for MZ's
  classes (labeled as such: it proves the code runs, not that MZ agrees).
- **`dev.py`:** `check` runs `node --check` on every plugin, compares each own plugin's `/*:` annotation with its
  `registerCommand` calls, validates the database JSON (lists start with null) and `js/plugins.js` (files present,
  the game's plugins on and in order); `test` is `node --test` with the count parsed; `smoke` serves `game/` with a
  small `serve.mjs` and boots it in headless Chromium (the web smoke, with `--query`, `--until`, `--fail-on`, captures);
  `build` is a plain web copy; `run --editor` opens RPG Maker MZ through `RPGMZ_EXE`.
- **Tested here:** a scaffold, a fake MZ project (stand-in core scripts) for `setup --from`, `smoke` and `build`, five
  planted faults that `check` must catch, a re-adopt with no conflicts, and adopting a project kept at the root.
- **Example `examples/lockpick-mz`:** a lockpicking minigame plugin (an event command runs it, a switch holds the
  result). The scenario pair over 40 seeds: a careful player opens 40, sloppy copies of it 40 and 37, a key-masher 1
  (the first careful bot opened none: it reacted late instead of reading the pick's motion). Only its two plugins are
  in the repo; `.gitignore` keeps MZ's files out. Never run in real MZ.
- **Elsewhere:** `check_links.py` knows the files MZ's editor makes later (a fresh MZ game's doctor was warning about
  nine); the README, CLAUDE.md, CHOOSING_AN_ENGINE, the `make-a-game` skill, and SOP-14 and SOP-17's engine tables
  include MZ.

### Procedural generation: new SOP-17 and the `/procgen` skill (16 skills, 17 SOPs)
- **SOP-17 "Procedural generation":** write the invariants before the generator; one seed, one level (your own PRNG,
  exact lattice coordinates, the seed on screen and `--seed N`, pinned fingerprints); skeleton first, then fill;
  generate, validate, reject and retry with a cap and a hand-made fallback; property tests over hundreds of seeds; the
  scenario bots on the hand-made level and on 8 or more generated seeds; bad seeds become regression tests. Engine notes
  for all six overlays (Unity measured, the rest marked **(verify)**).
- **`/procgen`** (`core/.claude/skills/procgen/`) runs it, shaped like `/game-ai`.
- **Evidence:** E56 (Shaker, Togelius and Nelson, *Procedural Content Generation in Games*, ch. 1 and 12, A), E57
  (Microsoft's System.Random remarks: no cross-version promise for seeded sequences, A), E58 (Kazemi on Spelunky's
  generator, C), E59 (Boris the Brave on Enter the Gungeon, C); findings F28 to F31 (A, A, A, B). Kate Compton's
  generator essay was not readable (HTTP 403) and is not cited.
- **Worked example, `examples/graveyard-shift`:** night 0 is the hand-made yard, every later night a generated one
  (`LevelGenerator.Generate(seed)` in the engine-free Core, the seed on the HUD, `--seed N` and `--handmade`). 250
  night seeds pass every invariant in an EditMode property test (0 problems, 0 fallbacks); the walk grid was checked
  against the real NavMesh on 17 yards (never looser); the bot trio on 8 generated nights: careful escapes 7, always
  dark 6, always lit 0 (hand-made yard unchanged: 2, 2, 0). These are the first, smaller yards; the 4x yards'
  numbers are in the README and SOP-17. The checks caught eight things on the way, among them the
  same code and seed building different yards in Unity's Mono and in .NET 8 (float rounding; fixed with a 1/16 m
  lattice) and a NavMesh that walks over a 0.75 m rock the keeper cannot climb. Story and limits: the example's
  HOW_IT_WAS_MADE.md, "Later: a new graveyard every night".
- An independent Sonnet review found the soul reachability check disabled by a comment (good yards never tripped it);
  fixed, and every invariant now has a test that feeds it a broken yard. The example has 86 EditMode tests and 12
  smoke tests, all passing (2026-10-23).
- Graveyard Shift: the owner walked out of the open gate and fell forever. The gate and both south corners (the wall
  model's off-center pivot) had been open since the first build. A test that walks the keeper into every gap reproduced
  it (6 of 6 south pushes fell), then invisible blockers on the wall line, left out of the NavMesh bake, and a fall
  safety net fixed it; the trio's escapes are unchanged. Lesson for SOP-17 users: also test that the player cannot
  leave the level, on the hand-made level as well as generated ones.
- Graveyard Shift grew from the owner's playtest ("4 times the size, it's too easy"): irregular yards (a main body plus
  wings, a union of rectangles on the wall grid, about 4x the area), crypts with roofs and doors, a hinged iron gate
  that opens on the last soul, grass and Nature Kit trees and bushes outside the wall (CC0, A-0027), 12 souls, a 300 s
  night, and a title screen with Easy, Normal, Hard and Insane (each darker, two more ghosts; Insane lights only the
  lantern), saved in a v3 save with a migration test. The checks caught a second cross-runtime rounding bug (ghost cell
  widths), a test score that still counted six souls, a property test too slow for its timeout (boxes now computed
  once: 6x faster), and a careful bot that waited with its lantern lit; the bot fix restored the lantern pillar on both
  kinds of yard. SOP-17's worked example has the new numbers.
- `--shot FILE` (Graveyard Shift) saves one real frame, HUD included, from a windowed player: batch mode never runs
  OnGUI, so that is how the seed label was proven (`examples/graveyard-shift/docs/procgen/hud_seed_48947.png`).
- Brief and goal line for the run: `PROCGEN_PROMPT.md`, `PROCGEN_GOAL.txt`.

### Several agents on one job (SOP-12, worked example)
- **`tools/second_opinion.py`:** asks another vendor's model (Kimi Code CLI 2.3) for a read-only review and prints the answer
  (`--ask`, `--files`, `--model`, `--out`, `--check`). The reviewer runs as `tools/second_opinion/kimi-agent.md`, whose tool
  allowlist is Read, Grep and Glob, because the CLI's prompt mode approves its own tool calls (E55). Handles a login error
  that exits 0, Kimi's resume-session noise, timeouts and a PATH that has not caught up with a fresh install. Exam 23/23.
- **SOP-12 "Several agents on one job":** coordinator, wide readers, hard calls, second opinion; verify every finding,
  keep outside helpers read-only, data leaves the machine. Worked example: this kit's five-reviewer audit (48 findings, 2
  wrong) and Kimi K3's review of the Godot export change, which found the stale "build is untested" notes (fixed).
- Dogfooding caught one bug on two paths: a review that quoted the login-error strings, and stderr echoing the source of a
  file Kimi read, both tripped the tool's own login check; it now counts only a line that starts like the CLI's error
  (regression tests).
- Kimi's own review of the tool (verified before fixing) found three more: an error line on stderr still discarded a real
  review (seen once live: now it counts only when no answer came back); a timeout waited for any child process holding
  the pipes (measured 20 s past a 2 s timeout; now the whole process tree is stopped); and a quoted, indented "To resume
  this session" line was stripped from the answer. Six regression tests, two with real processes.
- A usage or rate limit (met for real: a 429 "5-hour usage limit" after a day of reviews) is now exit 2 with the CLI's
  own message, not "no answer, rerun with --debug"; any other CLI `error:` line is shown too.
- A limit hit mid-review (met for real: the engines audit wrote progress notes, then ran out) is exit 2 too, and the
  partial notes are saved to `--out` marked INCOMPLETE instead of being thrown away.

### Audio you make yourself (`tools/audio/`)
- **`sfx_synth.py`:** retro sound effects from presets (jump, coin, land, fall, hit, pickup, blip, laser, explosion),
  standard library only. Seeds give repeatable variations (`--variants 5` to audition), every WAV gets a JSON recipe
  that re-renders it byte for byte, `--set` tweaks one parameter. Exam 10/10.
- **`chiptune.py`:** renders a song written as JSON text patterns (pulse, triangle, saw, sine, noise, drums) to a WAV;
  loops get a `smpl` loop chunk, release tails wrap onto the start, so Godot loops it seamlessly with default import
  settings. Errors name the pattern, channel and step. Exam 10/10 (it caught a 17-level triangle that overshot).
- **Coyote Hop sounds like itself now:** all four effects, the goal jingle and a new 16-bar theme were made with the two
  tools (song files in `assets/audio/src/`); the Kenney and SubspaceAudio audio left the project. Notes checked by FFT
  against the song file, the in-game recording shows music, jump sweeps and the jingle, loop points read by Godot (new
  GUT test, 24/24). Levels matched to the old mix (`MUSIC_DB` -8 to -3).

### Kimi audit, slice 3: Graveyard Shift on Kimi K3.1 Pro
Kimi read the example's C# game, tests and docs (read-only, `--model kimi-code/k3.1-pro`); two Sonnet agents reproduced
each finding. Of 10: 9 confirmed, 1 partly right, none refuted (the best slice so far).
- **Game:** the escape needs the gate fully open and the keeper in its doorway (it counted 3 m inside the wall, mid-swing);
  extra ghosts no longer start on a base ghost's corner (`examples/graveyard-shift/Assets/Scripts/Core/GhostPlan.cs`); saving is one atomic `File.Replace`, and a
  save left as `.tmp` still loads; Insane's gate light is off.
- **Tests:** a bot night that never ends fails; the gate-reach check means something (it was met by the start); one broken
  yard per LevelCheck problem (16, matched on the message: eight had none); the yard print covers models, outline, gate
  and start (re-pinned, .NET 8 and Mono agree); no light but the keeper's on Insane.
- **Balance, the owner's call:** the trio's lantern tests run at Easy; careful against always-dark is asserted on the
  hand-made yard and logged on generated nights (bots see in the dark); `Smoke_N` logs Normal. SOP-14 step 6 now says
  to assert only gaps the bots can perceive (K01).

### Kimi audit, slice 1: the kit tools (every finding verified before fixing)
Kimi K3 read `scripts/new_game.py` and every `core/tools` script (read-only, `tools/second_opinion.py`); a separate
Sonnet agent reproduced each finding. Of 6: 3 confirmed, 1 partly right, 2 refuted. It also cleared the scaffolder and
the hook, and noticed the audit brief named a hook folder that does not exist.
- **`chiptune.py`:** a release over 2 s overflowed the mix (traceback), and a string `bpm` crashed. Song numbers are now
  checked with ranges and named in the error (exit 2), and the mix leaves room for the longest release. Existing songs
  render byte for byte the same. Exam 12/12.
- **`fetch_asset.py`:** a wrong `--root` (no `docs/ASSET_LOG.md`) and a log without its table exited 1 and downloaded first;
  now exit 2 before any download. Exam 18/18.
- **`eleven_audio.py`:** a mistyped `--format` spent a request before failing, and `pcm_*` into `.mp3` wrote a WAV under an
  .mp3 name; the format must now fit the file type before anything is sent. Exam 18/18.
- **`sfx_synth.py`:** `--from` with `--variants` silently wrote one file; refused now (with `--seed` too). Exam 11/11.
- Refuted, kept as hardening or a comment: `wavfile.py stats` cannot hit the claimed crash from the CLI, but loop points
  past the data are now clamped on read (exam 7/7); `svg_export.py --area drawing` sizes correctly because Inkscape lists
  the root first (reproduced at 340 px), now said in a comment.

### Maintenance
- **`--upgrade` leaves deleted files deleted:** a kit file the project had (it is in `.game-kit.json`) and removed on
  purpose, such as a starter test for a rule the game replaced, came back on every upgrade. Now it stays out and the
  summary lists it; only files new to the project are added. Found when the RPG Maker MZ example dropped its starter test.
- **`tools/second_opinion.py` model names:** the help's own examples (`--model k3`, `k2.8`) fail on Kimi Code 2.3 with
  "not configured in config.toml"; the CLI wants provider/model (`--model kimi-code/k3`, `--model kimi-code/k3.1-pro`). Help and usage
  now say so, and an unknown model is a usage error (exit 2) that names the fix, not "no answer" (exit 1). Exam 24/24.
- **`scripts/sync_examples.py`:** brings every example up to the current kit through copies outside the repo, syncing by
  file content (the recorded kit hash), never overwriting a file a game edited (those come back as `.gold` to merge).
  Names and engines come from each example's `.game-kit.json`. Documented in the root CLAUDE.md.
- **Owner branding:** Rune Delve's `.game-kit.json` author and two lines of its `CLAUDE.md` named the owner (it was
  adopted without an explicit author, so the scaffolder took the git user name); now "the owner" like the others.
- **Iteration timelines:** Graveyard Shift, Coyote Hop and Gatekeeper (Godot) open their HOW_IT_WAS_MADE.md with a table
  of every change after the game first worked: what prompted it (the owner's words or a failed check), what changed,
  and what proved it. The examples' rules now ask for one; the examples index describes the iterated games.
- **`PROCGEN_PROMPT.md` and `PROCGEN_GOAL.txt`:** a brief and a `/goal` line for the next piece of work, a procedural
  generation skill (SOP-17) proven on Graveyard Shift's nights.

### Kimi audit, slice 2b: C++/SDL2, Unity and Unreal overlays
5 findings; a Sonnet agent confirmed 5, a second look refuted 1: 4 real.
- **C++ `dev.py test` passed `ctest --no-tests=error`,** which needs CMake 3.26 (cmake.org: "Added in version 3.26")
  while the kit supports 3.21, so `test` failed on 3.21 to 3.25. The flag is gone; the existing "No tests were found"
  check covers that case. Checked: Scrap Tanks' tests pass with the change.
- **Stale notes:** the Unity EditMode test template said "untested against a real Unity install" (it ran on 6000.6.6f1);
  the Unity `dev.py` header said `run` was "not exercised" (it launches and waits at Hub licensing, gotcha 10).
- **Unreal FLOW.md** showed the `test` command without the `-TestExit="Automation Test Queue Empty"` that `dev.py` passes.
- Refuted: "Unity lacks a PowerShell twin for `python3 ... clean`". Every engine twins PowerShell rules for `python`
  only (`python3` is not a Windows command); the verifier had misread Unreal's file as having both.

### Kimi audit, slice 2a: Godot, web and web-3d overlays
3 findings, all verified (2 confirmed, 1 partly), all low severity, none refuted; the contract, version pins, boot
markers and engine.json keys checked clean.
- **web-3d FLOW.md** pointed to "Scenario runs" in the web overlay's FLOW.md, which a web-3d project never contains; the
  options are now written out in it (including `--timeout`, `--record-every`, `--gpu`).
- **`smoke --frames`** accepted up to 100000 but the run had a fixed time limit; the limit now grows with the frames
  (web frames/20 s, Godot frames/60 s) and the help says so. `--timeout` help says it lengthens the whole run.
- **`smoke --record-every`** took 0 or negative values (a screenshot loop as fast as the browser allows); now 1 or more.
  Checked live: web and web-3d smoke pass, `--record-every 0` is refused, Godot passes a 3000-frame smoke.

### A live voice, bring your own key (`tools/audio/fish_tts.py`, Gatekeeper)
- **`fish_tts.py`:** Fish Audio text to speech: `check` (developer API balance, billed apart from a subscription),
  `voices` (library search, `--licensed`), `say` (one line to mp3, wav or opus, with a `.gen.json`). Key in
  `FISH_API_KEY`, never printed or saved. Exam 8/8 offline; live on the user's account.
- **Gatekeeper (Godot) speaks:** `examples/gatekeeper-godot/scripts/game/guard_voice.gd` voices every guard line, including the ones the local model
  improvises, using the player's own key read at runtime. Text first, voice queued behind it, cached per line, off in
  headless runs unless `--voice`, off for the session on 401/402/403. Live: 5 lines at about 2 s each, then 0 to 1 ms
  from the cache; bad key and no key both leave the game playable. 4 new GUT tests (24 in all).
- **SOP-15:** a prototype exception (tip, K01) for reading the player's own key from the environment; a release still
  goes through your server.
- **`wavfile.py` reads 32-bit WAV:** Godot's movie writer records 32-bit samples; read as 16-bit, the game's speech looked
  like white noise in the first check. Exam 6/6.

### Generated audio, opt-in (`tools/audio/eleven_audio.py`, `wavfile.py`)
- **`eleven_audio.py`:** ElevenLabs sound effects and music with your own key (`ELEVENLABS_API_KEY`, on Windows read
  from the saved user variable too, so no restart). `check` shows plan and credits; `--log` writes the ASSET_LOG row
  and evidence (prompt, model, plan, SHA-256) and marks free-plan output PLACEHOLDER (non-commercial, needs credit);
  `--dry-run` spends nothing; usage mistakes are refused before a request is sent; the key is never printed or
  saved (an exam test checks every output). Exam 18/18 offline.
- **Live on a free plan** it found three bugs, all fixed with regression tests: the API's raw PCM is stereo (read as
  mono a 1 s sound came out 2 s long), "music is not available for free users" (402) was reported as a rate limit,
  and the request ID and per-request cost are in `x-trace-id` and `character-cost`.
- **`wavfile.py` commands:** `stats`, `normalize` (generated audio came back at -60 dBFS) and `loop` (crossfade any
  download into a seamless loop with loop points; closes the "Suno does not loop" gap in BRIEFS). Exam 6/6 (with
  32-bit reading, below).
- **Graveyard Shift has generated sound:** five effects and a night ambience loop from ElevenLabs (275 credits), the
  Unity setup gained ambience and music loops, `SceneBuilder` finds sounds in any format, `AudioSetupTests` checks the
  wiring (36 EditMode tests, smoke 5/5).
- **Graveyard Shift's world sounds:** souls whisper where they float (find them by ear), ghosts moan louder as they grow
  wary or hunt, footsteps follow the distance walked (lit or dark), the lantern crackles while lit (`examples/graveyard-shift/Assets/Scripts/Game/GraveyardAudio.cs`,
  215 more free credits). The listener moved from the camera to the keeper. Three sounds came back too quiet and were
  normalized; positional sounds are mono (40 EditMode tests).
- **Graveyard Shift's ghosts whisper and the night has an ending:** Fish Audio voice lines from the ghost's position
  when it notices you, and when it catches you; at dawn the yard warms to sunrise with birdsong (ElevenLabs), then the
  screen fades to the end card with the Suno loss sting (an escape fades sooner, to the win music). `EndSequence` is a
  pure timeline function with EditMode tests (42). `fish_tts.py say` takes `--text` several times (one file each) and
  `--log` (one ASSET_LOG row and evidence for the set). Exam 10/10.
- **Graveyard Shift's voice cast** (Fish Audio, free model): a narrator (intro on the first night of a launch, escape and
  dawn outros over ducked end music), the keeper's barks (souls, gate, low time, caught) and more ghost lines (lost you,
  gave up), 29 lines on one shared voice channel that queues instead of talking over. The owner's verdict was "voices are
  no good, keep them for now": every voice row is PLACEHOLDER in the asset log. A 30 s mix rendered at the game's real
  volumes peaks at -1.5 dBFS (43 EditMode tests).
- **Graveyard Shift's music came from Suno** (the owner's paid plan, web app, from the brief in its `BRIEFS.md`): two takes,
  looped where each track best matches its opening (found by spectral similarity, not tempo), crossfaded with
  `wavfile.py loop`, encoded to OGG (23 MB to under 2 MB each, exact length, clean seam). They alternate per finished
  night and stream instead of sitting in memory (38 EditMode tests). A first try pasted the generic template and got
  non-game music: the kit's Suno template is now labelled as a template, and briefs say "video game background music".

### Front page and the last untested commands
- **README gallery:** "Made with the kit", seven example thumbnails (one frame of each GIF, about 250 KB in all, in
  `media/gallery/`) linking to each example, and a three-line pitch. The README's first-engine advice matches START_HERE.
- **Godot `build` works without the editor:** the skeleton ships `export_presets.cfg` (Windows Desktop, Linux, Web; tests,
  tools and docs excluded) and `dev.py build` with no options exports this computer's preset to `build/<os>/<game>`. All three
  export from Windows in seconds and the exe boots (coyote-hop too).
- **Verified for the first time:** `run` on Godot (`BOOT_OK` in Godot's log), web and web-3d (dev server, game boots),
  C++ (Scrap Tanks in a window) and Unreal (editor up in 35 s); Unreal `genproj` and `genproj --vscode` on Rune Delve;
  `validate_asset.py` on OBJ; in a live Claude Code session, the SessionStart hook, a deny rule on `.env` and the
  `code-reviewer` subagent. Unity `run` launches the editor, but the GUI editor waited at licensing on the test machine:
  Unity ENGINE.md gotcha 10 (sign in to Unity Hub first).
- **Blender 6 ready:** the Blender tools no longer touch `use_nodes` (deprecated, removed in 6.0) on Blender 5 and later.
- **Coyote Hop has a fox:** playtest verdict on the Kenney alien hero was "horrible, looks like an alien". Replaced by the
  CC0 Sunny Land fox (ansimuz, A-0006) with idle, run and jump animations, fetched with `fetch_asset.py`; GIF, gallery
  thumbnail and the example's HOW_IT_WAS_MADE updated. Bot result unchanged (8.52 s, 11/11), exported exe checked.

### Sanity audit (2026-10-22, five reviewers, every finding checked before fixing)
- **Tools:** the scaffolder decodes `git config user.name` as UTF-8 (a name like "Łukasz" crashed it on Windows) and
  takes a profile footer with backslashes literally; it no longer copies `node_modules`, `.godot`, `build`, `dist` or
  `vcpkg_installed` out of an overlay, and a truncated upgrade list now says how many files it left out.
  `fetch_asset.py` matches license names as whole words ("Not permitted" no longer passes as MIT), caches each URL in its
  own folder (two packs called pack.zip no longer mix), prefers License.txt over Credits.txt, and builds the log entry
  before copying anything (an asset log without rows crashed it half way). Exam 16/16 (4 regression tests).
  `doctor.py` honours `tools/check_links.ignore` for placeholders and survives an impossible HANDOFF date;
  `frames_to_gif.py` reconfigures stderr and works on older Pillow.
- **Overlays:** Unity and Unreal `clean` with a closed stdin gives the `--yes` message instead of a crash; Godot `run`/`build`
  and C++ `run` exit 2 for a missing or non-executable binary; web and web-3d `smoke --record-every` (milliseconds);
  Unreal `check --config Shipping` is a usage error (exit 2: the editor target only builds Debug, DebugGame, Development);
  stale "not executed" notes removed from the Unreal flow guide and the Godot `dev.py`; the web flow guide documents its
  scenario options; web-3d gains an "Assets and audio" section.
- **Docs and evidence:** the README and the engine chooser now agree with START_HERE (first game: the browser); SOP-04
  says unknown licenses never go in; single-source practices in SOP-09, SOP-12 and SOP-15 are labelled as tips; missing
  (verify) marks on SOP-13's legal and GitHub limits and SOP-15's usage policy; F4 now lives in SOP-01 too; stale counts fixed.
- **Examples:** gatekeeper-web and gatekeeper-godot no longer use Git LFS (examples rule 6); making-of counts and gap lists
  corrected (graveyard-shift U7 and U8, rune-delve R5, gatekeeper-godot 9 scripts and 20 tests, coyote-hop profile line).
- Not fixed, unverified: a possible Blender multi-user mesh error in `prep_export.py` (no reproduction).

### Neutral kit, renumbered
- **No author branding in the kit.** Kit tools end without a footer; file headers credit Claude and the model only (the
  `for {{AUTHOR}}` part of template headers is gone, the owner is named once in the game's `CLAUDE.md`). The owner's
  profile was replaced by a neutral `profiles/example.json`; profiles still add a footer and style to *your* games.
  The example games were re-rendered with the default profile and re-baselined so `--upgrade` stays quiet. Copyright
  lines are unchanged.
- **Versions:** the first public release is 0.4.0 (planned as 0.3.1). Earlier internal builds were renumbered from 2.x and 3.x into 0.x
  (same order); nothing compares versions, so only labels changed.
- **Saboteur bots, git rules for parallel agents, a milestone performance guard** (tips, E54: Cinderbelt, an open source browser
  game built on one weekly limit): SOP-14, SOP-05 and SOP-10 gain them, and E54 joins F9.
- **itch.io AI disclosure** (tip, E53, verify): SOP-04 now covers itch.io beside Steam (mandatory on asset pages since 2024-11,
  a field on game pages). A visual novel developer's report (E52) joins F9 (one model writes, another reviews).
- **Price one job before many; one acceptance suite per system** (tips, E51: a web ARPG MMO's 100-day report): SOP-12 and
  SOP-09 gain them, and E51 joins F5 (cost is real) and F9 (a second model reviews; cheap models for side jobs).
- **The cheap ways through must lose** (F32, grade B: E54, E60 and the kit's bot pairs): SOP-14 step 6's pair rule now
  cites it. From E60 (a one-line honey physics puzzle whose validator plays every level and its mirror) two tips: every
  hand-made level passes its own pair (the answer and sloppy copies win, lazy generic answers lose), and a player's
  exploit is measured across all levels before it is fixed. Playgama's MCP server joins `resources/ai-tools.md` (verify).
- **When prompting stops fixing an animation, change the setup** (tip, E50: a UE5 jet ski racer's account): SOP-11 now says to
  reach for sockets, IK, hand poses and physics assets after the third failed prompt, and to check from the game camera. F1 gains a seventh source.
- **Fun first, one toy at a time** (tip, E49): `FIRST_HOUR.md`, `VERTICAL_SLICE.md` and `START_HERE.md` say to grow a
  game one mechanic at a time, playing until it is fun again before the next, and to combine mechanics. It joins F4.

### Beginner on-ramp
- **`START_HERE.md`**: plain-English path from download to a playable toy: what plan Claude Code needs, desktop app or
  terminal, Python, unzipping properly (not inside OneDrive), permission and trust prompts, what to type, what to do
  when setup fails or the usage limit hits, a short glossary. The README's "New to this?" line points to it.
- **Kit-root skill `make-a-game`** (`.claude/skills/`): open Claude Code in the kit folder and say "I want to make a
  game". Claude asks three questions, picks the engine (browser by default for a first game), checks the installs,
  runs `new_game.py`, `setup`, `doctor` and `smoke`, writes the idea into the new GDD and HANDOFF, and hands over to
  a session in the game folder. The root CLAUDE.md sends game requests there.
- **FIRST_HOUR "Fast lane"**: a playable toy in about 15 minutes before the planning steps (now "Full route").
- Verified by a dry run (K01): a context-free reader role-playing a beginner (12 findings, 11 applied), then real
  headless Claude Code sessions in a fresh copy of the kit: "hi i downloaded this from github. i want to make a game"
  led to a scaffolded, set-up web game in 3 replies, and `/start-session` plus the fast lane there built a tested,
  playable frog toy (19 tests, smoke passes). Fixes from the run: name the engine, mention the trust prompt, one
  command per permission prompt.

### Local language models, built and measured (SOP-15)
- **Two new examples, `examples/gatekeeper-web` and `examples/gatekeeper-godot`:** talk your way past a guard run by a small
  language model on the player's own machine (WebLLM on WebGPU in the browser; the NobodyWho plugin with a GGUF model in
  Godot). The model only labels the player's line and speaks one sentence; game rules decide. Scripted fallback for every
  failure, recorded-output fixtures shared by both, real-model scenario runs, a live eval (93% on 14 lines, about 190 ms per
  reply on an RTX 5060 Ti), a setup script that verifies the model download against the logged SHA-256.
- SOP-15 gains "Worked examples" with what building them measured: one job per call (64% to 93%), avoid thinking-mode
  models for NPCs, models copy their input's format, constrained output fixes shape not sense, how to package the runtime.

### Art pipeline (new SOP-16, SOP-11 updated)
- `tools/blender/render_sprites.py`: a 3D model and one of its animations into a sprite sheet (directions x frames,
  transparent, same framing and lighting per cell, JSON layout); `--list-actions`, `--action`, `--ignore` for helper meshes
  (with a warning when one dwarfs the model). Exam 17/17; a Kenney CC0 character's walk rendered for real. Correction made later
  in this release: the "stray sphere" first blamed on Kenney's file was Blender's glTF importer adding a bone display shape;
  the shared import now removes it (see the web-3d example notes below).
- `tools/blender/prep_export.py`: apply transforms, pivot to the bottom center, clean names, one glTF preset, LODs, then
  `validate_asset` on the result. Exam 17/17.
- `tools/art/gimp_batch.py` (GIMP 3: flatten, resize with pixel-art interpolation, palette, export; one GIMP process per
  batch, per-file results) and `tools/art/svg_export.py` (Inkscape: pages or object ids at exact widths or scales, checks
  every output because Inkscape exits 0 on skipped exports). Exams 13/13 and 12/12 against the installed programs.
- SOP-16 "2D art pipeline": source and export folders, which tool for which job, pixel-art and vector rules.
  Evidence E47 (GIMP), E48 (Inkscape), finding F27.

### New engine overlay: `web-3d` (Three.js)
- Three.js r186 + TypeScript + Vite, with the web overlay's tooling unchanged (`dev.py`, Vitest, headless Chromium smoke,
  scenario options). The starter scene renders real frames in headless software WebGL, BOOT_OK is logged after the first
  rendered frame, and the loop uses `THREE.Timer` (`THREE.Clock` is deprecated since r183). Engine-free example: a
  critically damped spring follow (`src/core/follow.ts`) with tests. ENGINE.md wires Blender's `prep_export.py` to `GLTFLoader`.
- Verified on Windows: setup, check, test, build, smoke, doctor; a frame-loop exception and a renderer failure both fail smoke;
  re-adopt and upgrade clean.
- **Example `examples/courier-dash`** (built only with the kit, like ghost-lantern): a 90-second 3D delivery run past a patrol
  robot. Kenney CC0 models through `fetch_asset.py`, `prep_export.py` and `validate_asset.py`; an FSM robot (SOP-14) with a
  sight cone drawn exactly as far as it sees; the whole run engine-free and fixed-step, so the scenario pair runs in Vitest
  (careful bot wins from all 4 robot starts, reckless bot is caught from all 4) and the browser runs end with the same
  numbers. Kit gaps it found, all fixed in this release:
  1. `fetch_asset.py --base DIR` keeps sub-paths (Kenney models point to `Textures/` beside them; flat copies broke that).
  2. `validate_asset.py` failed every palette-textured (colormap) model on UV layout: it now detects palette and
     color-only texturing and skips the layout checks there (`[info]` line instead).
  3. Object names with hyphens (`character-female-c`) were flagged; the name rule and `prep_export` cleaning allow them.
  4. `prep_export.py --ignore NAME` drops helper objects, like `render_sprites.py`.
  5. The stray `Icosphere` on rigged models is Blender's glTF importer adding a bone display shape, not part of the file:
     the shared import removes it (earlier notes in this release blamed the Kenney file; corrected).
  6. SOP-14 had no Web 3D rows: navigation (grid A* in `src/core`, `@recast-navigation/three`, `three-pathfinding`),
     decision (`yuka`) and the debug view (E40 extended).
  7. SOP-06 says a web game reads its version from package.json, but the overlays could not import JSON: both web
     tsconfigs set `resolveJsonModule`, both ENGINE.md files show the one-line import.
  8. Headless `smoke --record` of a WebGL game captured 38 frames of a one-minute run (software rendering): the web-3d
     ENGINE.md says to record with `--headed` (425 frames).
  9. A source model moved without its `Textures/` folder exported without its texture and the result still validated:
     `validate_asset.py` reads the glTF's own file references, and `prep_export.py` refuses such a source before
     exporting. Exams: validate 22/22, prep 17/17.
- `CHOOSING_AN_ENGINE.md` gains "Not in the kit yet": GameMaker, Defold, LÖVE, Pygame, Ren'Py, MonoGame, Bevy, raylib,
  Babylon.js and PlayCanvas, Roblox, PICO-8, UEFN, Stride/O3DE/Flax, Ink/Twine, with what an overlay for each would map to.
- The scaffolder's footer placeholder also accepts Lua comments (`-- {{FOOTER}}`), so Lua overlays need no kit change.

### Versioning guidance
- SOP-06 "Versioning": Semantic Versioning for games. 0.x while in development (MINOR for big steps, PATCH for tweaks),
  1.0.0 for the full production release, release candidates as `1.0.0-rc.N`, MAJOR after launch only when saves or progress
  break; one source of truth per engine, tag matches. Linked from SOP-05, the ROADMAP milestones and `/release-check`.

### Kit fixes found by the examples
- `fetch_asset.py`: types `plugin` and `model`; accepts weak-copyleft component licenses (EUPL, MPL, LGPL).
- Web overlay: `smoke --headed` (real GPU, for WebGPU games) and `--gpu` (headless WebGPU flags); the page template declares
  an empty favicon and smoke ignores the browser's favicon probe (a headed run's 404 failed smoke).
- `check_links.py` and examples: downloaded-not-committed files are listed in the project's `tools/check_links.ignore`.
- **Example `examples/scrap-tanks`** (built only with the kit, C++ / SDL2): a one-screen tank brawl against raiders on a
  behavior tree (ADR in the example), sprites rendered from Kenney 3D kits, the fight engine-free and fixed-step so the
  scenario pair runs in doctest over 40 seeds (cover 25, charging 10). Kit gaps it found, all fixed in this release:
  1. C1: the C++ overlay's next steps said "set the exact engine version"; it now names VCPKG_ROOT, CMake and the first build.
  2. C2: `render_sprites.py --world-size` and `--pivot origin` for sprite sets that share a scale and stack (hull and
     turret); the JSON records pixels_per_meter and the pivot; the fit warning projects real vertices per direction.
  3. C3: meshes stored double-sided (every face twice, back to back, as in Kenney's Tower Defense Kit) rendered black in
     Cycles: `render_sprites.py` removes the inner twin, `validate_asset.py` warns. Exams 24/24 and 23/23.
  4. C4: the C++ skeleton passes `project(... VERSION)` into the code (`GAME_VERSION`, `--version`, the BOOT_OK line).
  5. C5: C++ `dev.py smoke` gains the web overlays' scenario options (`--until`, `--fail-on`, `--timeout`,
     `--screenshot`, `--record`); game options after `--` go to `Game::configure()`; `frames_to_gif.py` reads BMP frames.
  6. C6: SOP-14 "Test it" says to run the pair over many seeds and assert a gap, and a worked-examples table records what
     the three AI examples' scenario pairs caught (an always-aimed AI erases cover; sight is not a clear shot).
- **Example `examples/graveyard-shift`** (built only with the kit, Unity 6.6, without the editor UI): a night-time stealth
  game, lantern on or off, three ghosts on a C# state machine with Unity's NavMesh, the scene built by an editor script,
  a versioned save with a migration. A bot trio (careful, always lit, always dark) over 8 seeds refuted the lantern pillar
  until hunts tired and a catch cost a soul instead of the night (careful 44, dark 40, lit 23). Kit gaps it found, all
  fixed in this release:
  1. U1: Unity `dev.py exec Class.Method` runs a static editor method headless; the skeleton's `GameKitScenes.cs`
     creates a starter scene and adds scenes to Build Settings, so scenes can come from code.
  2. U2: `validate_asset.py` reports a uniform FBX unit scale (0.01 or 100) as info, not an unapplied-scale warning. Exam 24/24.
  3. U3: SOP-14's Unity row and FLOW.md say Unity Behavior graphs are editor-authored (graph classes internal in 1.0.16).
  4. U4: Unity `dev.py smoke` matches the other overlays: `--filter`, `--graphics`, `--screenshot`, `--record`,
     `--record-every`, `--until`, `--fail-on`; `GameKitCapture.cs` renders camera frames to PNG.
  5. U5: Unity ENGINE.md gotcha 9: ScriptableObject field defaults only seed a new asset, so tests must load the asset.
  6. U6: `build/` and `Build/` are one folder on Windows: Unity `smoke` refuses capture paths in the player folder and
     the docs capture into `Logs/`.
  7. U7: Unity 6.6 writes a `.slnx` solution; the overlay's `.gitignore` and ENGINE.md list it beside `*.sln`.
  8. U8: when Unity's Package Manager server fails to start, Unity exits 1 before compiling; `dev.py` said "compile
     failed". It now exits 2 and says to run the command again (seen once, gone on the retry).
  SOP-14's worked examples gain the row and two lessons (test a toggle with three bots; a chase that never ends makes
  caution lose).
- **Example `examples/rune-delve`** (built only with the kit, Unreal Engine 5.8, without the editor UI): a top-down
  dungeon room-clearer. Every spell is Gameplay Ability System C++ (abilities, effects, attribute set, native tags;
  numbers from the ini at the moment of use), orcs use AI Perception (sight and hearing) on a runtime NavMesh, input is
  Enhanced Input built in C++, and all content (120 assets and the map) comes from one headless Python script. A bot pair
  (weaver times the ward, masher spams) over 8 seeds: 71 against 55 of 80, full clears 5/8 against 0/8. Kit gaps it found:
  1. R1: Unreal `dev.py exec <script.py>` runs editor Python headless (the pythonscript commandlet; a traceback fails it);
     the flow guide gains "Content from scripts" (Interchange naming, maps, always-cook paths).
  2. R2: the flow guide's test macro used `EAutomationTestFlags::ApplicationContextMask`, which no longer compiles
     (`EAutomationTestFlags_ApplicationContextMask` since 5.5).
  3. R3: `AutomationOpenMap` called inside a latent command queues its PIE start behind every later command, so a
     multi-run smoke test hangs; the flow guide gives the working pattern (request PIE directly).
  4. R4: Unreal `smoke` gains `--filter`, `--until` and `--fail-on` like the other overlays.
  5. R5: the generated README said "a Unreal Engine 5 game"; the template now says "a game made with <engine>".
  6. R6: in a fresh C++ project the editor cannot load the game module until it is compiled, and `exec`, `test` and
     `smoke` reported a bare failure; they now exit 2 with "run `python tools/dev.py check` first".
  7. R7: with a space in the project path, Unreal read the backslashes of the `-script=` path as escapes (`
`, `	`),
     so `exec` could not find the script; it now passes the path with forward slashes.
  8. R8: loading assets by path in a C++ constructor runs when the module loads, before a fresh clone has content, and
     the error fails every editor command: Unreal ENGINE.md gotcha 12 (load in `BeginPlay`).
  SOP-14's worked examples gain the row.
- All eight examples upgraded to this kit version with `--upgrade` (through copies outside the repo; the scaffolder refuses a
  destination inside the kit), re-verified. Seen once and not reproduced in three reruns: Godot 4.7.2 crashed (0xC0000005)
  on the first headless import of a fresh gatekeeper-godot copy; rerun `dev.py check` if it happens.

## 0.3.0 (2026-10-21): Claude Code Game Kit, ready to share
Publish prep: the kit is now meant for anyone, not one owner's machine. New name, a fill-in profile instead of hard-coded
preferences, a fifth engine (browser games), two AI SOPs, two example games, and the tools those examples showed were missing.

### Renamed and made neutral
- **"Claude Game Dev Gold Standard" is now the "Claude Code Game Kit".** Project metadata moved from `.gold-standard.json` to
  `.game-kit.json` (`kit_version` replaces `gold_standard_version`); the old file and the old `.gitignore` marker are still
  read, and the old file is replaced on the next `--adopt` or `--upgrade`. `GOLD_VERSION` is now `KIT_VERSION`.
- **Profiles** (`profiles/`, `--profile FILE`): author, an optional file footer and extra working-style lines for the game's
  `CLAUDE.md`. The default is neutral: no footer, author from the profile, else `git config user.name`. The owner's
  preferences ship as a labelled example profile. The profile is stored in `.game-kit.json` and reused on upgrade. Starter
  code ends with a `{{FOOTER}}` line that becomes the footer or disappears; `{{PROFILE_STYLE}}` and `{{FOOTER_RULE}}` fill
  `CLAUDE.md` and `docs/STYLE.md`. The kit's own tools keep the kit's credit.
- Personal data removed: project names, machine paths (now in a gitignored `CLAUDE.local.md`), the VS Code CMake path
  (`${workspaceFolder}`), first names, "pasted by you" phrasing in the evidence notes.
- MIT `LICENSE`, kit `.gitignore`, README rewritten with a beginner quick start (install table, three commands, first session).

### New engine overlay: `web` (Phaser 4 + TypeScript + Vite)
- `dev.py` with the same contract plus `setup`; runs the project-local tools through `node` (no npx or .cmd shims). `check` =
  `tsc --noEmit`, `test` = Vitest, `build` = Vite (relative paths, uploads to itch.io as-is), `smoke` = the production build in
  headless Chromium through Playwright: fails on console errors, page errors, failed requests and HTTP 4xx/5xx (a missing asset),
  and supports `--query`, `--until`, `--fail-on`, `--screenshot` and `--record` for scenario runs.
- Points Claude at the 28 agent skills Phaser ships in its npm package (version-matched API docs), and at the v3-to-v4 migration.
- Verified with planted failures: a type error and a failing test exit 1, no tests exits 2, a boot exception, `Log.error` and a
  missing asset fail smoke, `--frames 0` exits 2, `clean` removes what it says. Re-adopt and upgrade give no conflicts.
- Engines can set `setup_step` in `engine.json` (printed as step 3 of the scaffolder's next steps).

### New SOPs and skills
- **SOP-13 Publish to GitHub** and `/publish-repo`: license choice (code and assets can differ), what you may not
  redistribute, personal data and secrets, private first, lock-down settings (ruleset, secret scanning, two-factor), go public.
- **SOP-14 Game AI** and `/game-ai`: perception, decision, movement; FSM, behavior tree, utility, planners with when to use
  each; navigation and AI debug tools per engine; testing. Sources E36 to E40 (official engine docs, Game AI Pro), F20 to F22.
- **SOP-15 Language models in your game:** cloud vs local small models, key safety (never in a client), rate and spend limits,
  fallbacks, model licenses for shipped weights, runtimes per engine, constrained output, testing with recorded responses, and a
  reality check on training your own model (published GPU-hours for 1 to 4B models vs a LoRA on one consumer GPU).
  Sources E41 to E46, F23 to F26.

### New tools (all with exams)
- `tools/publish_check.py`: what would be published, and what should not be (no LICENSE, secret files, token-shaped strings,
  files GitHub rejects, personal paths, personal emails in history, PLACEHOLDER assets). Exam 10/10.
- `tools/fetch_asset.py`: download a pack (cached in gitignored `.asset_cache/`), copy only the picked files, save the license
  text as evidence, add the `ASSET_LOG.md` row. Refuses NC/ND licenses unless `--placeholder`, never overwrites, refuses zip
  path escapes. Exam 9/9.
- `tools/art/frames_to_gif.py`: PNG frames (web `smoke --record`, Godot `--write-movie`) to a small looping GIF.

### Scaffolder and checks
- `--upgrade`: a `.gold` conflict now records the kit version it offered, so a merged file does not conflict again on every
  upgrade; new kit `.gitignore` rules are appended to existing projects (only on `--upgrade`; `--adopt` leaves the file alone).
- `check_links.py`: references into generated folders (`node_modules/`, `build/`, ...) are not checkable and no longer reported;
  `package-lock.json` joins the files that appear later. Exam 11/11.

### Examples (`examples/`, all rights reserved, free to reference)
- **Coyote Hop** (Godot): one-level platformer with Kenney and OpenGameArt CC0 assets, a level reachability test and an autoplay bot.
- **Ghost Lantern** (web), built using only the kit: utility-AI ghosts, A*, separation steering, and a scenario pair (escapes with
  the lantern on 6/6 seeds, caught without it on 6/6). Its run exposed six kit gaps, all fixed above except a tile-index helper.
- Every example has a HOW_IT_WAS_MADE page; rules in `examples/README.md`.
- Example assets are stored in plain git, not LFS, so GitHub's "Download ZIP" gives working examples (games made with the kit
  still default to LFS).

## 0.2.2 (2026-10-20): audit fixes
A multi-agent audit of 0.2.1 confirmed 142 findings (7 high, 57 medium, 78 low) after independent verification. Fixes land in passes.

### Pass 1: permissions and secrets
- **Removed the `git diff/log/show/branch:*` allow rules.** Prefix rules match any flags, so `git log --output=<file>` could overwrite
  the project's dev.py (then run it through the allowed `python tools/dev.py`) and `git branch -D` deleted branches, all without a prompt. Claude
  Code's built-in read-only checks already run the safe forms of these commands without prompting. Added ask rules for `git switch`,
  `restore`, `clean`, `stash drop` and `branch -d/-D/-f/-m/-M`.
- Removed the bare `Read`/`Glob`/`Grep` allows: inside the project they changed nothing, outside it they auto-approved reads of
  ~/.ssh and similar. Added `Read(~/.ssh/**)` and `Read(~/.aws/**)` denies.
- Removed every `Write(path)` rule (Claude Code never consults them and warns at startup; the `Edit` twins already cover writes).
- Deny and .gitignore now cover `*.jks`, `*.p12`, `*.pfx`, `*.p8` as well. Godot denies the real credentials file,
  `.godot/export_credentials.cfg` (the old rule named a root file Godot 4 never writes). Unreal denies `Config/DefaultCrypto.ini`
  and ENGINE.md warns about signing passwords in `DefaultEngine.ini`.
- Unity/Unreal `clean` and Unreal `package` ask rules are now `dev.py *clean*` / `*package*`, so the option-first form
  (`dev.py --debug clean --yes`) no longer slips past them. Unreal's usage line now puts options after the command.
- PowerShell twins for the allow, ask and key deny rules (Claude Code's PowerShell tool ignores `Bash(...)` rules); README says
  Windows needs Git for Windows. Deny also covers `rm -fr`, `git push -f` and `Remove-Item -Recurse`.
- SessionStart hook: command uses `"${CLAUDE_PROJECT_DIR}"` (it failed after Claude cd'd into a subfolder) and ends in `|| true`;
  output is UTF-8 (cp1252 pipes cut it off on non-Latin text); says "unknown" instead of "0" when git fails; counts untracked files
  individually; after compact/resume it no longer tells Claude to run /start-session mid-task.
- Godot `clean --deep` keeps `.godot/export_credentials.cfg` (it deleted the only copy of export passwords and the PCK key).
- Unreal `dev.py`: `--platform` limited to Win64/Linux/Mac and paths with cmd.exe metacharacters refused before any `.bat` call
  (both allowed command injection through the auto-allowed dev.py); `--filter` validated so it cannot add `-ExecCmds` commands.
- `doctor` fails when `.claude/settings.json` does not parse or has no deny rules (Claude Code would silently drop it).
- core/CLAUDE.md guardrail lists exactly what is secret and no longer claims permissions alone block every route.
- Verified with Claude Code 2.1.302 in `-p` mode on a generated Unity project: `git log --output`, `git diff --output`, `git branch -D`
  and `dev.py --debug clean --yes` are blocked (no file written, branch and Library/ kept); `dev.py doctor`, `git status` and
  `git log --oneline` still run without a prompt. Unreal `test`/`smoke` re-run against UE 5.8 with the new argument checks.

### Pass 2: Godot (what adopting an existing project would hit)
- **Adopt:** the kit's scripts call the `Log` autoload, but adopt (correctly) never edits an existing `project.godot`, so `check` and
  `smoke` failed right after the documented adopt steps. `engine.json` can now carry `adopt_hints`; the scaffolder prints them under the
  `[merge]` line. FLOW.md has an "Adopting an existing project" section and README's adopt notes give the real steps (Godot and C++).
- **Non-ASCII output:** Godot `dev.py` decoded engine output as cp1252 (strict), so a game named "Ícaro" made `smoke` and `test` crash
  with exit 2. Output is now decoded and printed as UTF-8.
- **Stale class cache:** Godot learns `class_name` globals only on import, so every new class made `check` fail on valid code and `test`
  silently skip its file. `check`, `test` and `smoke` now re-run import when `.godot/` is missing or the class_name set changed
  (stamp file dev_class_names.txt inside .godot/); ENGINE.md no longer calls import "once per clone".
- **`test` false passes:** GUT exits 0 when a test file has a parse error, the cache is stale, or `--filter` matches nothing, and
  `test` reported "passed". It now requires a non-zero test count and no skip/error markers: parse errors exit 1, nothing-ran exits 2.
- `check` also fails scripts that load but are broken by a dependency ("Failed to load script"), so `check <file>` matches `smoke`.
- `import` fails when Godot logs asset import errors (Godot exits 0).
- Godot below 4.3 is unsupported (no `--import`, or exit 1 after a clean quit); `doctor` now fails there. ENGINE.md and engine.json say 4.3+.
- `build --out` is resolved inside the project, as Godot does.
- **CoyoteTimer:** a zero window blocked jumping while grounded, and the shipped test asserted that. Grounded jumps now always work, a
  consumed jump stays used until the next landing, and the tests cover zero window, re-arming and same-contact double jumps (8 tests).
- FLOW.md: stale "not executed" note replaced, command table no longer split by a paragraph, `doctor` row and new Common errors rows.
- Verified on Godot 4.7.2 with GUT 9.7.1: adopt into an existing project then follow the documented steps (check, test 8/8, smoke
  pass); a project named "Ícaro" passes check/test/smoke; a new class_name plus its test re-imports automatically (9/9); filter
  with no match exits 2; parse-error test file exits 1; broken transitive dependency fails `check main.gd`; broken PNG fails import.
  On Godot 4.3, a fresh project without GUT passes check and smoke; `doctor` fails on 4.0.4 and 4.2.2.

### Pass 3: text encoding (Windows pipes default to cp1252)
- Every kit script (new_game, doctor, check_links, yt_transcript, chroma_key, validate_asset, session hook, all four dev.py) switches
  stdout/stderr to UTF-8 with replacement at startup. Before, printing a path under a user like "Łukasz", a CJK game name, a ♪
  caption or a non-Latin log line crashed with UnicodeEncodeError (exit 2), in new_game's case after the whole project was written.
- C++ and Unreal `dev.py` decode captured tool output as UTF-8 with replacement (Godot was fixed in pass 2): a byte like 0x8D or 0x9D
  (in "Í" or a right double quote) made the cp1252 decoder raise and the real result was never evaluated.
- Slugs fold accents instead of dropping letters ("Café Über" -> cafe_uber, was caf_ber). A name with no Latin letters now gets a clear
  error and a new `--slug` option instead of "no usable letters or digits".
- `--name` and `--author` reject control characters and undecodable bytes before anything is written (a newline produced broken
  generated code with exit 0). Unexpected-error messages are cut to 300 characters instead of dumping a whole file.
- Adopt appends its block to an existing .gitignore in binary mode, keeping the user's bytes and CRLF/LF as they were (it used to
  decode with errors="ignore", silently deleting non-UTF-8 bytes, and rewrite every line ending).
- doctor reads ASSET_LOG.md with replacement and runs each check on its own, so one bad file no longer hides every other result.
- yt_transcript `--out` creates its folder and reports write errors as `[error]` with exit 2.
- C++ CMakeLists adds `/utf-8` for MSVC (kit sources are UTF-8; CJK code pages warned C4819 and garbled non-ASCII names).
- Verified: names "Café Über", "東方 Quest", "東方" (error, then `--slug touhou`), "Ōkami" with --debug, a dest under "Łukasz", all
  piped; adopt into a CRLF .gitignore with a cp1252 byte (original bytes kept, CRLF block, re-adopt byte-identical); doctor on a
  cp1252 ASSET_LOG still reports a missing GDD.md; C++/Unreal run() return "“Ícaro”" where the 0.2.1 decoder raised on 0x8d;
  Unity doctor with UNITY_EDITOR under a Cyrillic folder; real Godot check/smoke for "Łukasz Quest" inside that folder; real MSVC
  build of "Ünïcødé Quest" with 0 C4819, smoke and test passing.

### Pass 4: false passes, hangs and exit codes (all four dev.py)
- **Hangs end:** timeouts on Godot import/check/test/smoke (the tail of a hung run is printed), C++ test/smoke, Unity batchmode,
  and `stdin=DEVNULL` on captured runs. `--frames` is bounded 1 to 100000 (Godot treats 0 as "never quit"; the C++ exe used `atoi`,
  so overflow ran forever; it now uses strict `strtol`).
- **C++ Debug asserts:** in `--smoke` mode main.cpp sends MSVC assert/CRT reports to stderr instead of a modal dialog that nobody can
  click; `smoke` now fails in seconds with "Assertion failed ..." instead of hanging.
- **No false passes:** C++ `test` runs CTest with `--no-tests=error` and exits 2 when nothing is registered; Unreal "no tests
  matched" exits 2 like Unity and Godot (nothing ran is a setup gap, not a failing test).
- **Environment problems exit 2 everywhere:** missing or non-executable binaries (PermissionError, a folder or `.app` given as the
  executable; `.app` bundles are resolved), Unity project already open in another editor (Unity 6.6 logs nothing for this, so the
  held `Temp/UnityLockfile` is tested; a stale lockfile does not trigger it), Unreal missing engine scripts, Unreal paths over 260
  characters.
- **`clean` tells the truth:** it reports files it could not delete (locked by an editor or game) and refuses to delete through a
  link or junction, instead of printing OK after `rmtree(ignore_errors=True)`.
- Unreal: Linux/macOS use `BatchFiles/{Linux,Mac}/Build.sh`; `genproj` uses UBT `-projectfiles` (launcher installs have no
  GenerateProjectFiles script) with a new `--vscode` option; toolchain detection is per line and skipped when the output has compiler
  errors (a "Visual Studio 2022" folder plus C3861 no longer reads as "install Build Tools"); doctor counts a missing git.
- Unity: `build` defaults to the host OS player (StandaloneOSX / StandaloneLinux64 off Windows) and `--out` is relative to the project.
- C++ doctor reports cmake and vcpkg separately (the CMake hint names the Build Tools copy) and warns on project paths over 100
  characters.
- All dev.py and new_game.py: `--debug` prints the traceback but keeps exit 2; output is line-buffered and flushed before children.
- engines/_template/README.md lists these rules for new overlays.
- Verified: C++ (MSVC, short build path): Debug assert fails smoke in 7 s with the assert text; a boot hang fails at 120 s; `--frames 0`,
  `99999999999`, `5x` exit 2 in dev.py and in the exe; BUILD_TESTS=OFF exits 2; clean with an open file reports 2 items left.
  Godot 4.7.2: hang in `_ready` fails at 120 s; GODOT_BIN set to a folder exits 2 with a hint; clean --deep with a locked file reports
  it. Unity 6000.6.6f1: check/test/build exit 2 while a second Unity holds the project, pass after it exits; UNITY_EDITOR set to a
  folder exits 2. UE 5.8: check/test/smoke pass; no-match filter exits 2; `genproj --vscode` writes a .code-workspace; a 261-character
  path exits 2 with the move hint; C3861 in a "Visual Studio 2022" folder exits 1.

### Pass 5: adopt safety and an upgrade path (new_game.py)
- **Conflict copies no longer break the build:** they are named `<file>.gold` (`coyote_timer.gd.gold`, `FixedTimestep.cs.gold`,
  `CMakeLists.txt.gold`), which engines ignore. The old `<stem>.gold<ext>` names were live sources: Godot let the kit copy win the
  `class_name` registry, Unity hit CS0101 duplicate types and duplicate asmdef names.
- **`--upgrade`:** every file the kit writes is hashed into `.gold-standard.json`. On upgrade, a file you never edited is replaced
  with the new kit version; a file only you changed is kept quietly; a file both sides changed gets a `.gold` copy. Plain `--adopt`
  uses the same rules but never replaces anything. Projects from 0.2.1 or earlier have no hashes yet: their first `--upgrade` behaves
  like adopt (`.gold` for every difference); after merging, later upgrades are automatic.
- An existing `.gold` is never overwritten (a half-merged one stays; the new copy goes to `.gold2`), and an identical one is reused.
- All writes are atomic (temp file + rename), including the user's `.gitignore` and `.claude/settings.json`; settings are only
  rewritten when the merge adds something.
- Re-adopting keeps the original `{{DATE}}` (from the metadata), so untouched files compare equal on any later day; comparisons fold
  CRLF to LF on both sides, and generated text is always LF. A kit-root `.gitattributes` keeps a Windows clone of the kit LF.
- `.gold-standard.json` is kept and extended (original scaffold date and adopted flag, `last_adopt`/`last_upgrade`, a history with
  unmerged files per run), written LF.
- The placeholder check scans only files this run wrote (a user's own `{{TOKEN}}` files or `doctor.py.gold` no longer make adopt exit 1).
- One plan for all files: an engine skeleton file replaces the core file of the same path without leaving a phantom `.gold`.
- A `--dest` inside the kit (including the old default of `./<slug>` when run from the kit root) is refused with a hint.
- `--git-init` creates branch `main` (git 2.28+, with a fallback), matching SOP-05. The report says "would" under `--dry-run`, prints
  the merge reminder only when there are conflicts, and prints `cd "<path>"` quoted with forward slashes (works in Git Bash).
- Unity: the build entry point is now `GameKitBuild` (it was `BuildScript`, a class name adopted projects often already have), and the
  starter tests live in the game namespace.
- Verified: fresh scaffold + re-adopt (0 conflicts, history recorded, 77 files hashed); upgrade with two kit copies (kit-only change
  upgraded, both-changed file got `.gold` with the user's live file intact, user-only GDD edit kept with no `.gold`, half-merged
  `.gold` preserved and `.gold2` written); all 78 files converted to CRLF then re-adopted: 0 spurious conflicts; Unity 6000.6.6f1 adopt
  over a user `FixedTimestep.cs` and their own global `BuildScript`: `.cs.gold` not compiled, check/test/smoke/build pass, `game.exe`
  built; Godot 4.7.2 adopt over a user `coyote_timer.gd`: `.gd.gold` absent from the class cache, check/test/smoke pass.

**Upgrading a project made with an earlier kit:** `python scripts/new_game.py --name "<Game>" --engine <id> --dest <project> --upgrade`.
On a 0.2.1-or-older project, expect `.gold` copies for every changed kit file the first time; the tools are the important ones
(tools/dev.py, tools/doctor.py, tools/check_links.py, tools/hooks/session_context.py, the C++ vcpkg.json): replace those with their
`.gold` unless you edited them, merge docs you edited, delete the `.gold` files, and the next upgrade is automatic.

### Pass 6: docs, skills and SOPs (38 findings)
- **Release flow works on every engine:** `/release-check` and SOP-06 start with `dev.py clean --yes`, which Godot and C++ rejected
  (exit 2). Both now accept `--yes`; the release steps note Godot re-imports by itself, and that "nothing ran" is UNKNOWN, not PASS.
- **3D validation actually applies budgets:** SOP-11, its Done-when and `/model-pipeline` pass `--class <prop|kit|hero|npc>` (without it
  the loose `any` preset passed over-budget assets). New SOP-11 "Export and naming" (one export setting set, `prop_`/`kit_`/`chr_`/
  `npc_`/`anim_` names). `/model-pipeline` finds Blender via `BLENDER_BIN`, PATH or the default install, or uses the bpy module via uv.
- **LFS for every engine:** a core `.gitattributes` (text normalization plus LFS for images, audio, 3D, video, fonts) ships into Godot,
  Unity and C++ projects; Unreal keeps its own. SOP-05 says so and asks for `git lfs install` before the first commit.
- **Concept art no longer ships:** CONCEPTS.md keeps FINAL boards in `docs/concepts/final/`, outside the engine content tree.
- **Skills match their SOPs and the docs they edit:** `/end-session` quotes HANDOFF's real headings and updates Last updated and Branch;
  `/perf-pass` and SOP-10 fill the ARCHITECTURE Budgets table; `/new-feature` parks pillar orphans (owner override recorded) and gains
  a close-out step; `/gdd-sync` bumps "Last reviewed"; `/adr` says where an ADR reference goes; `/asset-intake` and SOP-04 point at
  the file that actually holds naming conventions.
- **Done-when criteria that can be met:** SOP-09 allows "nothing ran" (exit 2) on a project with no tests yet, recorded in HANDOFF;
  SOP-04 and `/release-check` scope asset logging to third-party, AI-assisted and shipped media.
- **Store and engine terms:** SOP-04 adds store page and marketing art to the Steam disclosure (sources disagree, **(verify)**);
  SOP-06 and `/release-check` add the Unreal Release Form and Unity plan limits; CHOOSING_AN_ENGINE gains a license-cost row.
- **Godot export:** FLOW Packaging and `/release-check` exclude `tests/*`, `tools/*`, `addons/gut/*` from the export preset.
- **Engine docs:** Unreal gets an adopt-first Setup section (no spaces in the name, close the editor, `setx UE_ROOT`, `git lfs install`)
  and a correct `package` row; Unity ENGINE.md has the full adopt command, the Hub path for `UNITY_EDITOR`, Unity 6 settings paths
  and the PlayMode folder; C++ ENGINE/FLOW give vcpkg port names (`sdl2-image`, not `SDL2_image`), the pinned-baseline gotcha and one
  consistent asset-path rule; the C++ Release exe is a GUI-subsystem binary (no console window), Debug keeps its console for smoke.
- **Honest status everywhere:** Unity is "all but `run`" in README, CHOOSING_AN_ENGINE, DISTILL_REPORT and the dev.py header; the kit
  CLAUDE.md gap list matches README; DISTILL_PROMPT no longer tells a re-run to mark Unity and Unreal untested; DISTILL_REPORT
  experiment 1 includes the Godot export it claims to close; README's validate_asset exam is 12 + 4 cases.
- **Evidence:** CHOOSING_AN_ENGINE no longer cites E27 for a claim it contradicts; SOP-12 cites E26 (not E21) for the 1.5 to 2 hour
  figure; SOP-11 labels the single-creator vegetation steps as a grade C tip; EVIDENCE.md says how to get a transcript with
  `tools/yt_transcript.py`; ai-tools.md no longer calls the Unity overlay untested; the engine template README drops Unity from
  "engines to add" and points at an overlay to copy.
- Verified: C++ Release exe is GUI subsystem and Debug CONSOLE (PE header), Debug smoke still passes; `clean --yes` exits 0 on Godot
  and C++; all four generated projects pass doctor and the link check; re-adopt has no conflicts.

### Pass 7: tools and engine code (34 findings)
- **yt_transcript** (11): `--whisper` runs on the CPU by default; it let ctranslate2 pick CUDA on any NVIDIA PC and crashed with
  "cublas64_12.dll is not found". `--device cuda` is opt-in and falls back to the CPU. Audio is downloaded as-is and decoded by PyAV,
  so no system ffmpeg is needed. The install line pins `av<19` (PyAV 19 breaks faster-whisper 1.2.x) and that failure gets a clear
  message. Missing libraries exit 2 with the install line; failures print the real reason (yt-dlp's ERROR line) and only suggest
  `--whisper` when it could help. Text from every path is one flat line with HTML entities decoded and `>>` speaker marks dropped.
  Regional `--lang` codes work with whisper. URL parsing accepts `/live/`, rejects non-YouTube hosts and stray `nav=`; ids starting
  with `-` are documented (`--`). `--model` picks the whisper size; the ~0.5 GB download and its location are documented; `--debug`
  progress goes to stderr, never into the transcript.
- **doctor and check_links** (8): one shared skip list (Unity Library/Temp/Logs/obj/UserSettings, `.vs`, `out`, `vcpkg_installed`,
  `cmake-build-*`, venvs) and folders are pruned while walking instead of filtered after a full walk (40,000 files in Library/: 0.3 s).
  Vendored `addons/`, `Plugins/`, `Packages/` and folders listed in `tools/check_links.ignore` (or `--skip-dir`, doctor `--ignore`) are
  skipped. check_links no longer flags `res://` paths, `#anchors`, `%20` or `<spaced paths>`, `~~~` fences or links inside inline code,
  and now catches titled links, reference-style links and wrong letter case (which passed on Windows and broke on Linux and GitHub);
  links resolve from their own file, as GitHub and VS Code do. doctor flags only the kit's six placeholders (a game's own
  `{{PLAYER_NAME}}` is fine), reads HANDOFF's "Last updated" date (mtime only as a fallback), counts a filled sample asset row, ignores
  Unreal `.uasset`/`.umap` noise, knows more media types and finds Unity's `Assets/` with exact case.
- **chroma_key** (3): `--despill` uses standard spill suppression (it left magenta fringes pink and did nothing for green); every
  output is planned first and the run refuses, writing nothing, when an output would replace a source image, two inputs share a name,
  or an output exists without `--overwrite`. The exam has the STYLE header and footer and covers all of it (14 checks).
- **validate_asset** (2): UV islands are linked by vertex position, so a flat-shaded glTF (vertices split at every hard edge) no longer
  reads as one island per face; a faceted UV-sphere exam case proves it (128 islands with the old code, 1 now). The exam re-launches
  through `bpy.app.binary_path` inside Blender, where `sys.executable` cannot import bpy.
- **Scaffolder** (2): slugs that are CMake reserved targets, the C++ skeleton's own target names or C# keywords (`test`, `core`, `void`,
  `event`, ...) get a `_game` suffix with a notice, and such a `--slug` is refused. File errors in new_game.py and every dev.py name
  the file and exit 2.
- **Engine code** (8): Unreal `.gitignore` keeps the committed `Build/` files (icon, PakBlacklist, platform resources) and ignores the
  VS Code workspace and `.ignore`; `package` writes to the ignored `Packaged/` (on Windows `build/` and `Build/` are one folder).
  Unity ignores a leftover `InitTestScene*.unity`. C++ VS Code tasks use `python3` on Linux and macOS, and the Mac debug config uses
  lldb. FixedTimestep (C++ and Unity) treats NaN or negative frame time as zero and a non-positive `max_frame` as 0.25 s (a negative
  value was UB in C++). C++ smoke feeds one tick per frame, so N smoke frames are N game updates on any machine. main.cpp names its
  window, logical-size and tick constants; skeleton headers are complete. Unity's test suite grows from 4 to 10 cases (accumulator,
  alpha, NaN, max_frame, dropped flag, zero max_steps). Godot and C++ `run()` keep the output so far on a timeout or Ctrl+C and
  print its last lines.
- Verified: live YouTube (captions API, yt-dlp subtitles, whisper on CPU, `--device cuda` on an RTX 5060 Ti falling back after the
  real cuBLAS error, ffmpeg hidden from PATH, PyAV 19 message, unavailable video); doctor scenarios and 40k-file timing; check_links
  exam 10/10; chroma_key exam 14/14; validate_asset exam 17/17 with the bpy module and 17/17 inside Blender 5.2.2; MSVC build of a game
  named "Test" (slug test_game) with 11/11 doctest cases, and the old FixedTimestep line fails the new NaN test; Unity 6000.6.6f1 10/10
  EditMode tests; `git check-ignore` on the Unity and Unreal rules; Godot 4.7.2 check/test/smoke and a `_ready` hang that now ends at
  120 s showing its last printed line.

### Evidence: Biskey Games Ep. 5 (E35)
- New source E35 (grade C, same creator as E07 to E10, so no finding changes grade and no SOP rule changes).
- `BRIEFS.md`: "Asset hand-off" prompt (analyze attachments, split code bugs from art gaps, list missing assets, no code until
  confirmed) and 2D pipeline tips 11 to 15: preview sheets as GIFs (near-identical walk frames, cycles that must return to frame 1),
  fresh chat for a direction that keeps failing, frame-by-frame corrections, transition/edge/cliff tiles instead of outlined tiles,
  iteration budget for a slice.
- `resources/ai-tools.md`: PixelLab row (API image prices from the official page; animation price and plans **(verify)**).
- `evidence/video-notes.md`: Ep. 5 row.

## 0.2.1 (2026-10-20): Windows fixes, real Godot run, Suno briefs
First run on a Windows host (Python 3.14) after installing v21.

### Fixed
- `tools/check_links.py` and `tools/doctor.py` (placeholder scan) matched their skip-folder names against the **absolute** path. Any project
  under a folder named `Temp`, `build`, `Library`, `Logs`, `Saved` and so on was skipped entirely and reported clean. On Windows the temp dir is
  `...\AppData\Local\Temp`, so `test_check_links.py` failed 2 of 5 there. Both now match paths relative to the project root. Exam 5/5 on Windows;
  a planted broken link and placeholder are caught in a project scaffolded under a `build` folder.

- Godot `dev.py check` failed on every script that used an autoload ("Identifier not found: Log"), because `--check-only --script` runs
  outside the project's autoloads. It now runs one Godot launch with the new `engines/godot/skeleton/tools/check_scripts.gd`, which loads each script inside the
  project. The checker skips itself (recompiling the running script crashes Godot 4.7.2 with signal 11). `check` also skips `tests/` until
  GUT is installed, since test scripts extend `GutTest`.

- Unreal `dev.py test`/`smoke` could never pass: `UnrealEditor-Cmd` writes automation results only to its log file, not stdout, so the
  parser saw no `Result={Success}` lines. Now runs with `-abslog=Saved/Logs/dev_automation.log` and parses that file.
- Unreal `dev.py check` skips Blueprint-only projects (no `Source/`) and exits 2 with an install hint when MSVC or the Windows SDK is
  missing (was a generic exit 1). Build output is streamed and kept for that check.
- Unity and Unreal `clean` crashed with `EOFError` in Git Bash under Claude Code, which reports a TTY with nobody to answer.
  They now exit 2 and ask for `--yes`.
- Unity `smoke` could never pass out of the box (no Smoke tests shipped). Added `engines/unity/skeleton/Assets/Tests/PlayMode/BootSmokeTests.cs` and its asmdef:
  loads the first Build Settings scene, runs 120 frames, fails on any logged error. It skips the test runner's own `InitTestScene<guid>`,
  which Unity inserts into Build Settings during PlayMode runs (an earlier draft loaded that scene and passed with no game scene at all).
- Unity `test`/`smoke` exit 2 with the reason when nothing ran (no match, or all ignored). `build` prints the `[ERROR]` lines from
  `BuildScript` and passes its exit 2 (no scenes) through.

- C++/SDL2 `vcpkg.json` used `{{GAME_SLUG}}` as the package `name`; slugs have underscores, which vcpkg rejects, so the first configure of
  any multi-word game failed. `name`/`version-string` removed (optional for a project manifest) and a `builtin-baseline` added (vcpkg
  release 2026.07.29, commit 9e593bb1). The vcpkg bundled with Visual Studio refuses a manifest without a baseline.
- Unreal `check` also exits 2 (with the fix) when the .NET Framework SDK is missing or an open editor's Live Coding blocks the build.

### Tested (first real engine run)
- C++/SDL2 on Windows with VS 2022 Build Tools 17.14 (MSVC 14.44), its bundled CMake 3.31 and vcpkg, SDL2 2.32.10, doctest 2.5.3:
  `doctor`, `check`, `test`, `smoke`, `build --preset release`, `clean`. Planted compile error (`check` 1), failing test (`test` 1) and boot
  `LOG_ERROR` (`smoke` 1). A project under a ~120-character path failed with C1083 (Windows path limit); documented.
- Unreal 5.8 with VS 2022 Build Tools and a minimal C++ project: `check` (about 1 minute), `test`, `smoke`, `package` (about 4 minutes,
  writes `build/Windows/<Game>.exe`), `clean`; planted compile error and `Result={Fail}` test both caught. UE 5.8 also needs the
  .NET Framework 4.8 SDK component, which the C++ workload does not include.
- Unity 6000.6.6f1 on Windows, project from `Unity -batchmode -createProject` then `--adopt`: `doctor`, `check`, `test`, `smoke`,
  `build`, `clean` all run. Planted compile error (`check` 1), failing assert (`test` 1), error during scene load (`smoke` 1), no scene
  (`smoke` 2, `build` 2). `build` wrote the player (Build/game.exe). The Test Framework is built in on 6.6.
- Unreal 5.8 (launcher install, Windows, no MSVC) with a Blueprint-only project copied from `TP_BlankBP`: `doctor`, `check` (skip, and
  exit 2 on missing SDK with a stub `Source/`), `test --filter System.Core.Math` (40 passed), no-match filter (1), `clean`. Not verified:
  C++ compile, a failing test (cannot plant one without C++), `smoke` with real tests, `package` (UAT stopped with "does not look like
  uproject file but no targets have been found", most likely the missing Windows SDK).
- Godot 4.7.2 on Windows (console and plain exe) with GUT 9.7.1: `doctor`, `import`, `check`, `test`, `test --filter`, `smoke`, `clean`
  pass on a fresh scaffold, and planted failures are caught (broken script: `check` exits 1; bad call at boot: `smoke` exits 1; failing assert:
  `test` exits 1). `build` and `run` not executed. README, FLOW, CHOOSING_AN_ENGINE and DISTILL_REPORT updated.
- `test_validate_asset.py` 16/16 on Windows with bpy 5.2.2 under Python 3.13 via `uv`. There is no bpy wheel for Python 3.14; the
  `[ENV ]` messages now say so and give the `uv` command.

### Added
- `core/docs/BRIEFS.md` > Music with Suno: field guide, palette line, eight-track starter set, loop and retro tips, rights note.
  `resources/audio.md` points at it. Sources E33 (prompting guides, B for the core field rules) and E34 (rights reporting, C) in `EVIDENCE.md`.

## 0.2.0 (2026-10-19): the distill
Delivered as zip v21. `.gold-standard.json` in new projects records `0.2.0`. Earlier zips (v1 to v20) were all `0.1.0`.
Done with Claude (Opus 5.5) in one session, following `DISTILL_PROMPT.md`. Nothing that came from a source was deleted: it moved.

### Added
- `core/docs/EVIDENCE.md`: ledger of 32 sources (E01 to E32) plus this kit's own tests (K01), graded A to X, with sponsor flags.
  19 cross-source findings (F1 to F19) say which rules came from where.
- `core/docs/FIRST_HOUR.md`: the first 60 minutes on a new game (brainstorm, GDD identity, references, slice brief, budget, kick off).
- `CHOOSING_AN_ENGINE.md`: decision tree and comparison of the four overlays, plus where Roblox and browser stacks stand.
- `core/tools/blender/validate_asset.py` and its exam `test_validate_asset.py`: triangle budget, size, unapplied scale, pivot, naming,
  missing UVs, UV coverage, islands, overlap, texel spread, missing textures. Exam 16/16 with the `bpy` 5.2.2 module.
  Closes a dangling reference: SOP-11 had pointed at this script since v1 but it did not exist.
- `core/tools/check_links.py` and `test_check_links.py` (5/5): broken markdown links and backticked paths. `doctor.py` now runs it (warnings).
- `CHANGELOG.md` (this file).

### Moved
| From | To |
|---|---|
| `RESOURCES.md` license cheat sheet | `core/docs/resources/licenses.md` |
| Music, SFX | `core/docs/resources/audio.md` |
| Art 2D, Art 3D, AI 3D generators, UI, fonts, VFX | `core/docs/resources/art.md` |
| Map data, level tools | `core/docs/resources/world-and-levels.md` |
| Learning, marketing and release | `core/docs/resources/learning-and-release.md` |
| AI tools and MCP table | `core/docs/resources/ai-tools.md` |
| Creature animation pipeline, Biskey pipeline, RTS week, budget stack, workspace pattern | `core/docs/resources/pipelines.md` |
| SOP-12 "Techniques seen in the video", Chong-U workflow bullets | `core/docs/resources/pipelines.md` |
| Video and community table (all rows, verbatim) | `core/docs/evidence/video-notes.md` |
| AAA cost section and the seven "data points" (verbatim) | `core/docs/evidence/field-reports.md` |
| SOP-11 Blender MCP recipe, agent comparison, self-check notes | `core/docs/evidence/field-reports.md` (end) |
| VERTICAL_SLICE clarifying-question, first-build and integration detail | `core/docs/evidence/field-reports.md` (end) |

### Promoted to rules (grade B or A)
- Interaction smoke checklist rewritten as one table of eleven checks (F1, six independent creators) in `SOP-09`.
- References and mockups before building (F3), mechanics before art (F4), one job per fresh session (F2), a debug panel early (F7) in `SOP-12` and `VERTICAL_SLICE.md`.
- Effort and budget table (F5) and a `/goal` long-run recipe (F19) in `SOP-12`. The "state in files survives a crash" note (F15) is grade C, kept because the kit's HANDOFF design already does it.
- Kept as labeled grade C tips because they are cheap: multi-angle self-checks (F10), the UV acceptance check (F12), stylized over realistic meshes (F13).
- Steam AI disclosure buckets (F11, grade A) in `SOP-04`, cited to the Steamworks page.
- Unattended runs and bypass-permissions mode (F18) in `SOP-07`.

### Tightened
- `core/docs/RESOURCES.md`: 364 lines to a 49-line index with a "start here" pick per need.
- `core/CLAUDE.md`: 93 to 75 lines. Adds FIRST_HOUR and EVIDENCE rows, the smoke-checklist reminder, `doctor` in the command contract.
- `SOP-11`: 107 to 90 lines, restructured, cites sources, points at the real validator.
- `SOP-12`: 86 to 61 lines, rebuilt around steps, model roles, effort and budget, long runs.
- `VERTICAL_SLICE.md`: generic, adds debug tools and self-testing to the prompt.
- `SOP-05` and `SOP-06` gained "Done when", `SOP-09` gained "Common mistakes"; the SOP index sentence now matches reality.
- Engine `FLOW.md` files share "Packaging (...)" and a final "Field notes (reported, unverified)" section; Unity gained a packaging section.
- Every reference to the old single `RESOURCES.md` in skills, agents and docs now points at the right split file.

### Cut
- Nothing from sources. Duplicate wording between SOP-11, SOP-12 and RESOURCES was merged into one place each.

### Fixed after the independent review (a reviewer agent read the kit cold)
- Every `dev.py` now accepts global options after the command (`dev.py build --debug`, `dev.py build --preset release`, `dev.py package --config Shipping`). Before, the documented forms exited 2. Parse test 8/8 across all four engines.
- Unity and Unreal `clean` no longer hang in a non-interactive shell: they exit 2 and ask for `--yes`. SOP-06 and `/release-check` use `clean --yes` and name each engine's real release command.
- One start order everywhere (README, scaffolder output, FIRST_HOUR): doctor, engine setup (Godot: GUT and `dev.py import`), then FIRST_HOUR.
- `ARCHITECTURE.md` gained the Budgets section that four other docs pointed at.
- `/asset-intake` logs the four AI buckets instead of yes/no.
- Grades corrected: F1 counts six independent creators, F10 is C, E22 is C, E30 and E31 are D. Grade C rules are labeled as tips.
- Secrets are denied for Edit and Write too, not only Read. The session hook tries `python3` then `python`. Unreal and other `ask` rules cover the `python3` spelling.
- `.gold-standard.json` version is now 0.2.0. ROADMAP has a Budget and cost log and one Now limit (3). `/end-session` uses HANDOFF's real headings.
- Stale wording fixed (Unity "see below", video-notes recipe pointer, CONCEPTS "clean up later", STYLE model line, license caveat path).

### Not done (on purpose)
- No Roblox or browser overlay. Recorded as next experiments instead of building untested scaffolding.
- Unity and Unreal overlays are still untested against real installs.

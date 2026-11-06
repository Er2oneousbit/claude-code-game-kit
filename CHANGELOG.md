# Changelog

0.4.0 is the first public release. Versions before it were internal builds, renumbered from 2.x and 3.x into 0.x
(same order, same contents); 0.3.1 was the release candidate and was never published, so its work is in 0.4.0.

## 0.13.2 (unreleased): fixes from Fable reviews of the Pixelorama lane, the engine wrappers and the shipped tools
- Engine wrappers (web, web-3d, RPG Maker MZ, Bevy, LÖVE): `smoke --data-dir` no longer rewrites a file that is
  not UTF-8 text (a binary save came back as replacement characters, or was deleted): such files are left out and
  left alone, and a project folder (`src/`, `assets/`, `public/`, `dist/` ...) is refused as the data dir. The wait
  for N frames is raced against a timeout, so a page that freezes after booting fails instead of hanging. Bevy and
  LÖVE delete a stale screenshot and their own old frames before a capture run and fail on a missing screenshot or
  an empty recording (both were `[ OK ]`). RPG Maker MZ `run --port` takes 1-65535 (a usage error, exit 2) (#251).
- Engine wrappers (Godot, Unity, Unreal): Unreal `test`/`smoke` fail when the editor exits non-zero after some
  tests passed (a crash after two passes was `[ OK ]`), and a test named "Test Failed ..." is no longer a failure.
  Godot `smoke --record` deletes only its own `f00000.png` frames (and their `.import`), not every `f*.png` (a picture
  of yours named fox.png went); Unity only `frame_000000.png`. Godot's import-before-check (0.13.1, #195) compares with
  the last import, so a touched or re-saved asset is imported once, not on every command (checked with Godot 4.7.2);
  capture folders inside the project get a `.gdignore`. Godot `check <file>` resolves the file against the project
  and refuses one outside it (exit 2). Godot `build` and Unreal `build`, `package` and `genproj` stop after 4 hours
  (they had no timeout); Unity `check` names a timeout as one (#250).
- A second-model review of these fixes (Kimi K3.1 Pro) found more, now fixed: the web smoke's `--data-dir` guards
  look at the real folder (a symlink to `src/` passed) and ignore letter case (`SRC` passed on Windows), symlinks
  inside the data dir are never read or written through, and the localStorage read-back has a deadline (#256);
  Godot's `.gdignore` goes only into a folder of captures (`--screenshot assets/shot.png` hid every asset), an asset
  changed within a second of an import is seen, and with `--engine none` every scene and TileSet an earlier Godot
  re-export wrote is kept, whatever the frame count now names them; a terrain added in Pixelorama is an edit (#257);
  `image_diff` refuses 16-bit palette PNGs (a ZeroDivisionError) and PNGs without IEND and applies grey and RGB
  transparency, `check_links`/`doctor` count a dangling symlink as missing, the doctor and `credits.py` read UTF-16
  and BOM asset logs, and `comfy_local` strips APP and COM segments between a progressive JPEG's scans (#258).
- `comfy_local.py`: two outputs with one name in different ComfyUI subfolders are both kept (one replaced the
  other, or the run stopped half saved); a long name keeps its extension (every output was skipped after the GPU
  time); redirects are never followed (the local-only check covered only the first address); a JPEG loses anything
  after its end-of-image marker (a motion photo's video and XMP survived the strip); the log row's folder uses
  forward slashes on Windows. `yt_transcript.py` gives yt-dlp a time limit; `issues.py` fences issue titles with the
  run's nonce like bodies (#248).
- Shipped tools: `credits.py` splits ASSET_LOG rows on unescaped pipes only (an author "Ana \| Band" shifted
  every later column and credited the wrong licence) and says plainly when the log is not UTF-8 (exit 2, was a
  traceback). `image_diff.py` reports a cut PNG as unreadable (exit 2) and makes the `--diff` folder. `doctor.py`
  checks required files with their exact letter case (on Windows a lower-case gdd.md passed for the GDD), reads
  UTF-16 and cp1252 files for placeholders, and documents exit 2. `check_links.py` checks markdown that is not UTF-8,
  skips a fence indented in a list item, and no longer reads `[Bug]: crash on load` as a reference definition; its
  `read_text` is shared with the doctor (#247).
- Dotwork Pixelorama: a corrupt or crafted `.pxo` is refused with a message naming the field, not a Python
  exception: an encrypted or unknown-compression member, a member cut short, `tags` or layer `effects` that are not
  lists, animated opacity with list or dict keys or a list transition, a v8 `image_size` of non-numbers, a tilemap
  cell index of infinity or NaN, tile data or terrain data of the wrong type; an unreadable terrain colour falls
  back to Pixelorama's default (#246). The extension's exit wait (found by inspection) is #255.
- Dotwork Pixelorama: a re-export with `--engine none` kept the tilemap's TileSet and scenes out of the files it
  wrote, so it deleted them as stale (and said "0 files changed"); they are now kept, and a deleted file counts as a
  change. A tilemap `.pxo` with a pixel layer, a frame or a tile's terrain added in Pixelorama is an edit now: kept
  when the game's map changes, not rebuilt without them (the build record hashes the tile data) (#245).

## 0.13.1 (2026-11-05): fixes to `bozzetto.py rig`, `tools/token_audit.py`, `tools/fetch_asset.py`, the scaffolder, the paid PixelLab and ElevenLabs clients, `tools/publish_check.py`, the SessionStart hook, `tools/second_opinion.py` and the Wavesmith DAW round trip from second-model reviews, and four older tool bugs
Kimi K3.1 Pro reviews of 0.13.0 (`tools/second_opinion.py`), each finding checked against the code; one more was
found by the real run that verified the rig fixes.
- Older open bugs: `daw import` refuses a render at another sample rate than its sound, naming the rate the game
  expects (it was taken as an edit and written at the render's rate) (#194). Godot's `dev.py` imports before `test`,
  `smoke` and `check` when an asset is new or changed (no `<file>.import`, or newer than it), not only when class
  names change; checked with Godot 4.7.2: a new .svg is imported once, the next run is quiet (#195). Dotwork's
  `setup --check` reads ComfyUI's V3 loader lists (`["COMBO", {"options": ...}]`) through one
  `comfy_local.loader_options`, shared with Bozzetto (#197). `comfy_local.py` strips EXIF and XMP from WebP and
  JPEG outputs as it does from uploads (ComfyUI's WebP node writes the workflow there) (#198).
- Rune Delve (Unreal): a bot delve under `-fixedfps` now plays the same with a renderer and under `-nullrhi` (#8). The
  runtime NavMesh builds its tiles on worker threads and the engine picks the finished ones up on whichever frame they
  are done in, real time, while the orcs already path on it (the first differing frame was frame 5); the flying bolt
  also counted for navigation, so it rebuilt its tile every frame it flew. Fix: the bolt is off the NavMesh, and under
  `-fixedfps` the game mode finishes every pending tile right after the navigation system ticks and before any actor
  does (`ARDGameMode::FinishNavBuild`); and an orc's movement component ticks after its path following (the engine
  orders neither, so now and then the movement ticked first, braked for one frame without a request, and the delve
  played out differently). New: `-tracedelve` logs one line per frame (positions, health, orc states)
  and `examples/rune-delve/tools/unreal/replay_check.py` runs a seed rendered and under `-nullrhi` and reports the first frame that
  differs. Found by a Fable 5.1 agent; checked here on weaver seed 6 and masher seed 4 (identical traces). The delves
  changed (no bolt holes, no random brakes): alone, the pair fell one under both pillar thresholds (weaver 61, masher
  52, clears 2/8). With #140, an open gate now joins two rooms for sight and hearing (`FRDLevel::SensesInto`): a mage
  in the doorway used to pull a room's sleeping orcs one at a time, since only the orc a bolt hit woke; a core test and
  a regression stage (every room 1 orc awake 10 frames after a doorway shot) pin it. Together the pair measures weaver
  73, masher 47 of 80, clears 6/8 against 0/8 and passes (margins 16 and 3); the thresholds are unchanged.
- Scrap Tanks example: RETREAT is now documented as the heavy's alone (the README, GDD and HANDOFF said every raider
  could retreat, but a scout is at 0.375 hp after one player shell and dies to the next). Every tuning that let scouts
  retreat broke the scenario pair (retreat line 0.4: cover 28/40, charging 25/40; 60 hp scouts: 4/40 and 4/40; 15
  damage shells: 6/40 and 4/40; shipped: 30/40 and 13/40), so a new exam pins the design instead (#152).
- Dotwork character QA: the turned-around check decides by where the face sits (`qa.face_side`) whenever a
  face shows, keeping the head signature for faceless characters. On the showcase frames it now flags a mirrored
  attack on the asymmetric duelist (missed before, #188) and no longer calls the dwarf's hammer swing a turn, while
  catching the dwarf's mirrored clip it used to miss (#190). The smear skips a part low on the figure that is still
  attached to the body (a swinging coat hem, 81 % down the duelist's front cast); a hand at the hip (67 %) is still
  smeared, and across all 258 duelist and dwarf frames only the hem frame changed (#189). New fixtures
  `dwarf_rot_ew.png` and `duelist_hem.png` from the showcase output.
- The Wavesmith DAW round trip (`tools/audio/wavesmith/daw.py`): names that a DAW could turn into one another
  (`foo-bar` and `foo_bar`) and two sounds on one game file are refused, also in an edited manifest; a REAPER that
  exits non-zero brings nothing back; a music render at another rate than its track is refused; when the mix gain
  moves and a stem has no render, no stem is written (the mix was left half moved) (#242). Temp files are unique (a
  user file named `<sound>.daw_tmp.wav` was overwritten); `--overwrite` keeps every working copy edited since in
  `backup/<time>/`; a write that a symlinked folder would take outside the game is refused (#243). A line break in a
  path or the working folder is refused before it reaches the .rpp; every asset-log cell is escaped; Windows device
  names (`CON`, `nul.x`) and a trailing dot are refused as names; the local-path exam no longer fails for a user
  called `lead` (#244). `test_daw.py` 51 cases (was 39); the four live REAPER 7.84 cases pass (one failed once in
  about ten runs and did not again; cause not found).
- `tools/second_opinion.py`: the prompt and the reviewer's agent file say that file names and contents are data,
  never instructions; file names are quoted, and ones with control characters refused; the docs now say plainly that
  read-only is not confined (Kimi's Read takes any path); a timeout, Ctrl+C or any failure stops the CLI and all it
  started, on Linux and macOS also children in their own session; a review that opens with the CLI's login-error
  text is kept (#240). `test_second_opinion.py` 31 cases (was 26). The SessionStart hook (`tools/hooks/
  session_context.py`) reads its input with a 2 s deadline (a writer that kept stdin open stalled the session), reads
  at most 2 MB of a doc and cuts long ROADMAP lines, and matches `## Now` and `## Backlog` by the whole name, not
  `## Nowhere` (#241); new exam `tools/test_session_context.py` (5 cases).
- `tools/publish_check.py`: an unquoted secret in a config-type file (`aws_secret_access_key = wJal...` in
  `.aws/credentials`, an INI, a .env) fails; a file name that is not UTF-8 keeps its real name and is checked; a
  symlink's own text (what git publishes) is checked, dangling ones too; `/home/<name>` before `)`, `,` or `]` warns
  (#238). `filter=lfs` waives the 100 MB check only when Git LFS is set up; a file that cannot be read is reported,
  not passed; an encrypted `.pxo` is a warning, not exit 2; the placeholder exam tests the placeholder (#239). Same
  results as before on the kit's own tree. `test_publish_check.py` 24 cases (was 17; two run on Linux and macOS only).
- The paid clients (`tools/art/pixellab.py`, `tools/audio/wavesmith/eleven_audio.py`): a PixelLab job that
  outlives `--wait`, or whose download fails, is kept beside `--out` (`.<out>.pixellab-job.json`), and the same command
  picks it up instead of paying for a second generation (the old advice was "rerun"); a connection that drops during
  a paid request says it may have been charged, in both clients (#234). ElevenLabs: `--loop-crossfade` is checked
  before paying, and a fade the answer cannot hold keeps the audio unlooped instead of throwing it away; an empty,
  JSON or HTML answer is refused before anything is saved or logged; answers are capped at 256 MB; variants saved
  before a later one fails are logged (#235). An unknown or missing plan tier is no longer logged as a paid,
  commercial licence: `--log` stops and asks for `--plan` (#236). PixelLab's summed cost shows every known charge
  and says when a job reported none; a cost given as text or a success answer that is not an object no longer
  crashes after paying; a key echoed in a server message is printed as `<key>`; Windows device names and names that
  differ only in case are refused before writing; the asset log has one writer at a time (`fetch_asset.log_lock`,
  also used by `fetch_asset.py`) and an evidence file is never overwritten (#237). Exams: `test_pixellab.py` 57
  (was 50), `test_eleven_audio.py` 31 (was 23), `test_fetch_asset.py` 42 (was 39).
- `scripts/new_game.py`, the scaffolder: every write goes through a new, unique temp file (a fixed
  `<file>.newgame-tmp` destroyed a user file of that name); a symlinked kit file or folder is left alone and reported,
  never written through or replaced, and settings.json, .gitignore and the record refuse to write through one (#230). A
  record made by a newer kit is refused (an older kit's `--upgrade` downgraded untouched files; `--force` to do it on
  purpose); the record's shape is checked before any write; `.gold-standard.json` is deleted only when it was the
  record read (#231). `.game-kit.json` now keeps the kit's own settings and .gitignore rules, and `--adopt` and
  `--upgrade` merge against them three ways: your values stay yours (the kit's `model` no longer overwrote yours),
  a rule the kit removed is removed, a rule or key you deleted stays deleted, only what is new in the kit is added
  (#232). A file with NUL bytes or a binary type is copied byte for byte even when it decodes as UTF-8; `<` and `>`
  are refused in names (they reach the web overlays' `<title>`); a case-only kit rename on Windows or macOS upgrades
  instead of leaving a `.gold`; `sync_examples.py` copies back through a temp file (#233). `test_new_game.py` 26
  cases (was 15).
- `tools/fetch_asset.py` (a security review: it takes any URL and any archive): downloads are HTTPS only (`--allow-http`,
  and `--allow-local` for a `file://` pack already on this computer), never follow a redirect from HTTPS down to HTTP,
  stop at `--max-mb` (default 4096) and 1800 s, and record the final URL; a ZIP is refused before unpacking past 20,000
  entries, 16 GB unpacked or a 200:1 entry; the cache folder is the URL's full SHA-256 (10 hex digits of SHA-1 could be
  made to collide) (#225). A pack whose own licence file says all rights reserved, non-commercial, no derivatives or
  personal use only is refused against a free `--license` unless `--license-mismatch "why"` (logged); "not CC0" and
  "MIT; no resale" are no longer read as plain licences (#226). Two ZIP entries that land on one file are refused (#227).
  `--page` loses its login and its query and fragment (tokens) unless `--keep-page-query`; a local `file://` path
  never reaches the records; every line separator, CR included, is a space in a log cell; IDs keep counting past
  A-9999; an absolute `--to` is logged project-relative (#228). If writing the evidence or the log fails, the files the
  run copied are removed again, and the log is replaced in one step (#229). The asset-intake skill now names the tool
  and says when an unclear licence may come in as a PLACEHOLDER. `test_fetch_asset.py` 39 cases (was 30).
- Bozzetto docs-versus-code review: a Tripo task the last run left running was paid for again on a re-run; it is now
  asked for its result first, and a run stops rather than pay twice while it is still running (#221). `rig check`
  said ready with a refused Tripo key, and `rig make --wait` did not reach UniRig's steps (#222). `rig` now bends
  every bone and fails a mesh that does not move, so "checks that the rig really deforms" is true (#223). README:
  the ComfyUI address options (`COMFYUI_URL`, `--url`, `--allow-remote`), every timeout, the Tripo defaults (45
  credits, `--max-credits` 100), Ctrl-C leaving a ComfyUI job queued, the missing make and rig options, what `--hash`
  covers, the class, quality and material defaults, `.jpeg` references, the 9.0 GB download (8.3 GiB), unvalidated
  LODs, the full list of rig checks (#224). `test_rig.py` 32 cases; each new one fails on the code before it.
- `tools/token_audit.py`: a non-number in a session log's usage field went through `int()`, whose error message printed
  the value; such a line now counts as malformed and nothing of it is shown, and an unexpected error prints only its
  type (`--debug` keeps the traceback). The folder `CLAUDE_CONFIG_DIR` names is shown as `$CLAUDE_CONFIG_DIR`, so the
  promise "environment variables by name only" holds for it too (#217).
- `tools/token_audit.py`: a settings file of valid JSON but the wrong shape (`[]`, numbers where objects go) aborted
  the whole audit; it is now a per-file error like broken JSON (#218). `@~/` imports resolve against the user's home,
  not the parent of `CLAUDE_CONFIG_DIR` (#219). A session-log record over 64 MiB is skipped unread instead of held in
  memory; folded and literal YAML descriptions (`description: >-`) are counted in full (#220).
- `test_token_audit.py`: 27 cases (was 20), one per fix (each fails on 0.13.0's code), plus a check that no socket is
  opened and no file changes; every CLI call now stays inside the fake tree (five could read parent `CLAUDE.md` files
  above it) (#220).
- The weight check never caught NaN weights: they were filtered out (`NaN > 0` is false) before the check. NaN,
  infinite and negative weights now fail the rig (#208).
- Tripo: each step's actual cost is checked against `--max-credits` and the balance before the next paid call, not
  only the printed quote (#209). Every paid task goes into `assets_src/bozzetto/<name>/rig/tripo/tasks.json` as it is created and as it
  finishes; a run that fails after paying keeps them, and a re-run reuses them (a fresh download link, nothing paid
  twice; `--no-reuse` to pay again) (#210).
- `unirig.log` held absolute local paths (UniRig's arguments and output) in `assets_src/`, which is committed; the
  project, the UniRig checkout and the home folder are now `<project>`, `<unirig>` and `~` there (#211).
- A step that exits 0 without its output fails the run; earlier outputs are removed first, so `--overwrite` can
  never pass an older model's rig along (#212).
- UniRig wrote `raw_data.npz` next to the input model, in the game's models folder (its extract joins the output
  folder with the absolute input path, and `join` keeps only the second). UniRig now works on a copy of the input
  in the work folder, and the models folder stays clean. Found by the real run that verified these fixes.
- Checked before any GPU or paid work: `--animate` clip names, a positive `--wait`, an `--out` outside the project
  (refused with logging on, as `make` does); a relative `UNIRIG_DIR` now works on Linux and macOS (#213).
- Asset log: the source is found by its Path cell only, so a re-rigged unlogged input is never named as its own
  source; `--names keep` is logged as "bone names kept", not "Mixamo names" (#214).
- `rig/patch_unirig.py --check` requires the patched code itself, not just its marker comment (#215).
- Bone mapping refuses instead of guessing: the hips are the bone both legs hang from (a ground root keeps its
  name); a model facing sideways or backward, an arm under 3 bones and a partly Mixamo-named rig are refused with
  the fix to make (#216).
- `test_rig.py`: 27 cases (was 15): one per fix, including NaN and negative weights, a lost Tripo result fetched
  again without paying, a stale rig, and the five new skeleton shapes. Real run: UniRig on the beekeeper passed
  with every fix (562 s with a local LLM runner holding the GPU, about 85 s without).
- Graveyard Shift (Unity): the always-lit bot's "12 or 14 catches between runs" (#160) was not reproduced: a
  frame-by-frame record of every bot night (`examples/graveyard-shift/Assets/Tests/PlayMode/FrameTrace.cs`, `GRAVEYARD_FRAMETRACE=<dir>`)
  matched to the last digit over eleven process runs of the eight lit nights (144,000 frames each; alone, in
  parallel, with a graphics device, inside the full smoke), and over three runs of the 11-02 code where it was seen.
  No game code changed. Two new smoke tests guard the replay: `Smoke_R10` plays the lit bot's closest-pass night
  twice and compares every frame and the catches, `Smoke_R11` walks two ghosts head-on through each other's
  avoidance four times (`examples/graveyard-shift/Assets/Tests/PlayMode/ReplayTests.cs`). 26 smoke tests (was 24; HANDOFF said 23).

## 0.13.0 (2026-11-05): /token-audit, what a project's Claude Code sessions spend tokens on
- **`/token-audit`** (22 skills) and **`tools/token_audit.py`**: a read-only audit of what a project's Claude Code
  sessions spend tokens on, after a video's audit prompt (E154, description only, grade D). The tool reads files,
  never the network, and changes nothing: memory files loaded at the start (CLAUDE.md in the project and its
  parents, the user's, CLAUDE.local.md, the auto-memory index, @imports one level deep) with sizes estimated at
  4 characters per token; model, effort and hooks from the three settings files; proxy and gateway variables by
  name only; `.mcp.json` server names; subagent models; skill description sizes; and the newest session log's
  cache read, cache write, input and output tokens, counted once per API response (one response is written as
  several lines), with first and last turn context, model switches and cache lifetimes. What it cannot see (MCP
  tool counts and deferral, `/usage`, scheduled tasks) is printed as UNKNOWN with the command to run. The skill
  adds `/context`, `/usage`, the MCP servers and scheduled work Claude can see, and writes one table sorted by
  cost plus the single highest-leverage change. The 5k and 10k memory thresholds and the deferral claim are tips,
  not rules. Exam `test_token_audit.py` (20 tests, Python 3.8 and 3.14). SOP-07 points to it. Built on 2026-11-02
  and parked on a side branch; its video source is E154 (it was E141 there, a number main later gave to Pixelorama).
- KNOWN_ISSUES: Strata, a local LLM runner, as an idea (#206).

## 0.12.0 (2026-11-05): rigged characters, picture to game, and an interview that asks about 3D art and sound
0.8.3 to 0.11.0 below were on `main` or side branches without a tag; this release tags them all.

- `bozzetto.py rig`: a skeleton, skin weights and clips for a character in the game, logged as "rig of A-NNNN".
  `rig make <name>` uses UniRig on your own GPU (free; a checkout patched by `tools/bozzetto/rig/patch_unirig.py` runs on standard
  wheels, no flash_attn or Triton) or `--with tripo` (paid API credits, quoted and checked against `--max-credits`
  and the balance before anything is uploaded). Both go through `rig_finish.py`: a weight check that fails the rigs
  that came back with exit 0 here (unweighted, NaN, everything on glTF's placeholder bone or on one bone), Mixamo
  bone names found by the skeleton's shape (`mixamorig:Hips` ...), Tripo's 1.0 m output scaled back, and for UniRig
  three looping clips (idle, wave, walk). `rig check` says which route is ready. Exam `test_rig.py` (15 cases: stand-in
  UniRig and Tripo, rigs built in Blender). Tested live: UniRig 85 s, Tripo 29 s and 45 credits (K01, E152, E153)
  (#199, #205 part 2).
- `make-a-game`: the art-source question (8b) is asked for 3D games too, with 3D options (shapes in code plus packs,
  their own models, Bozzetto with its 16 GB card and statue-only characters said plainly, paid 3D services), and a new
  sound-source question (8c: Wavesmith in code, their own, local AI, paid). The interview is 15 questions; the plan, the
  install check (the graphics card for Bozzetto and local audio) and the hand-over carry both answers, and the GDD
  template has a Sound source line. Before, a 3D game was never offered Bozzetto and no game was asked about sound
  (#204: the flagship game is made through this interview like any user's).
- `workflows/picture-to-game/`: one generated picture each to a tree (Bozzetto, a grove of six in Godot) and to a
  character that walks in, waves and idles in Godot: Bozzetto for the mesh, UniRig for the skeleton and skin weights
  (first a scratch runner, now `bozzetto.py rig`), and a Blender
  script that finds spine, legs and arms in an unlabelled
  auto-rig from its shape and keys idle, wave and walk loops. Failures shown: a look-alike first prompt, the budget
  check refusing the textured character twice (UV coverage 51%, 53%), three UniRig problems on a Blackwell GPU
  (Triton on Windows, a pickled class in the checkpoint, flash_attn wrong at head_dim 16 giving a rig that deforms
  nothing with exit 0), and a vertex-coloured model rendering white in Godot. EVIDENCE E151 (UniRig and its data),
  E152 (the runs) (#199, #202, #203).
- `tools/bozzetto/rig/patch_unirig.py` and `mha_sdpa.py` (first in the showcase's `src/`): UniRig runs on standard wheels only (no flash_attn,
  no Triton, no community builds): a PyTorch SDPA stand-in for flash_attn's attention class (same weights, within 1e-7),
  `sdpa` for the skeleton model, PTv3's own attention, and a weights-only allowlist for the skin checkpoint. Same
  skeleton, skin weights within run-to-run noise, tested on a fresh clone (#199).

## 0.11.0 (2026-11-05, first tagged with 0.12.0): Bozzetto, local 3D models from a picture or a prompt
- Bozzetto, the kit's local 3D asset lane (`tools/bozzetto/`, in every game): `bozzetto.py make <name> --image
  <picture>` or `--prompt "..."` (FLUX.2 klein 4B draws the picture first, as Dotwork loads it) makes a textured mesh
  with TRELLIS.2 4B through a local ComfyUI 0.43.0+ (built-in nodes, BiRefNet background removal inside the shipped
  workflow), then cleanup.py in Blender (merge, loose fragments, normals, decimation to the class budget, height in
  metres, pivot at the bottom centre), `tools/blender/prep_export.py` (the one glTF preset, LODs per class) and
  `validate_asset.py --class`: nothing reaches the models folder unless the budget passes. It writes the ASSET_LOG row
  (pre-generated AI, models, seed, prompt, "Built with DINOv3"), the evidence file and, the first time, the model
  licence texts into `docs/licenses/`; sources, reports, a record and a turntable preview stay in
  `assets_src/bozzetto/<name>/`; `--sprites` renders a sheet for 2D games; `--reference-only` auditions pictures for
  seconds each. The models folder follows the engine (`public/assets/models` on web and web-3d). `check` lists what is
  missing (nodes, model files with pinned URLs, Blender or the bpy module); every check runs before GPU time. Pinned
  register `models.lock.json` and `LICENSES.md` (MIT; the DINOv3 licence's use list is flagged as an open question;
  RMBG-2.0 and nvdiffrast are refused). Live on a 16 GB RTX 5060 Ti (K01, E150): about 5 minutes a model warm (#193).
- Bozzetto: turntable.py renders a contact sheet (and frames for a GIF) with render_sprites.py's camera and light.
  Exams: test_bozzetto.py offline (a stand-in ComfyUI and a canned mesh; the Blender part runs on Blender or the
  bpy module) and test_bozzetto_live.py (one real run; it skips without a GPU setup) (#193).
- comfy_local.py reads ComfyUI's "3d" outputs and saves `.glb` with the glTF extras removed (Save 3D Model writes the
  whole prompt, local paths included, there); `strip` does the same by hand (#193).
- Docs: SOP-11 "Local generation", the `/model-pipeline`, `/gen-brief` and `/asset-intake` skills, BRIEFS (the
  earlier "not recommended" note replaced), the resources pages, EVIDENCE E147 to E150, import notes in the Godot,
  web-3d, Unity, Unreal and Bevy ENGINE.md (Unity, Unreal and Bevy marked verify), and
  `workflows/bozzetto-showcase/` (a prop and a character from prompt to engine, failures included) (#193).
- Docs: SOP-11 "Which tool for which job", every 3D tool (Bozzetto, `tools/blender/`, the skill, what has no tool) on
  one table with where its docs are (#193).
- Bozzetto: a `--material vertex` model rendered white in Godot (4.7 imports glTF `COLOR_0` but leaves
  `vertex_color_use_as_albedo` off). The Godot ENGINE.md has the loop that turns it on, Bozzetto's README says so, the
  web-3d ENGINE.md says Three.js needs nothing (GLTFLoader sets `vertexColors` by itself), and the Unity, Unreal and
  Bevy notes say to check (#202).
- Bozzetto: a validator that crashes (any exit but 0, 1 and 2, or no report) stops make before anything is copied
  or logged, and an old validation report from an earlier run is removed first, so it can never pass a model (#193).
- Bozzetto: the `--sprites` sheet is rendered before the asset log is written, so it gets its place in the row,
  the record and the evidence file with its hash (it shipped unlogged); its layout `.json` counts as a file in the
  way (#193).
- Bozzetto: a `--image` reference loses its metadata before it is stored or sent to ComfyUI: EXIF (a photo's GPS
  position), XMP, IPTC and comments from JPEG and WebP (`comfy_local.strip_jpeg`, `strip_webp`, `strip_picture`), and
  `strip_png` now also drops eXIf and tIME, for Dotwork's saved PNGs too. JPEG and WebP references were copied byte
  for byte, and a PNG kept its EXIF (#193).
- Bozzetto: `--material vertex` works. TRELLIS.2's vertex-colour mesh has no UV map, so validate_asset.py failed
  every one after the GPU run; cleanup.py now adds one (Smart UV Project) to a mesh without, and the colours survive
  export. Each job queues only the branch it saves, so a vertex job no longer runs the unwrap and the bakes, and a
  texture job no longer paints vertex colours it throws away (#193).

## 0.10.0 (2026-11-05, first tagged with 0.12.0): the DAW round trip
- Wavesmith: the DAW round trip (`wavesmith.py daw`, daw.py). `daw reaper <set|track|folder>` writes a plain-text
  REAPER project in `assets_src/daw/<name>/`: one named region per sound (a set from data/sound_sets.json, or a
  folder with `--bus`) or one track per stem of a data/music.json track (its tempo, time signature and loop markers),
  the bus loudness targets in the project notes, the sounds copied into `media/`, and no absolute path anywhere, so
  the folder can be committed. `daw reaper --reexport <folder>` renders it headless (`reaper -newinst -nosplash
  -ignoreerrors -cfgfile <temp>/reaper.ini -renderproject`, Wavesmith's own render settings in a copy of the project)
  with a throwaway configuration folder set to Dummy Audio, so the user's REAPER settings are never read or written.
  A sound whose audio did not change keeps its file byte for byte; an edited one is levelled to its bus by the sound
  sets rules (music: the stems together, by their mix), keeps its loop point and mono, and gets a `hand_edits`
  sidecar entry and an ASSET_LOG row (`Modified? yes`, one per working folder, updated on later runs) with an
  evidence file; an edit undone in the DAW puts the original back. A renamed region, an unknown render and a game
  file changed meanwhile (`--force`) are refused by name; missing media stops it before REAPER runs; a REAPER that
  hangs on a dialog is stopped after `--timeout`. Every other DAW: `daw export` writes WAV stems, a sequence of every
  sound, markers (CSV and an Audacity label track), MIDI for music and HOW_TO.txt; `daw import` takes the renders
  back by name (case, spaces and dashes forgiven, near misses named, missing ones kept) with the same levelling and
  logging. FL Studio and Ableton Live: the stems route only (verify). `daw check`, `daw --help` and `wavesmith.py
  check` say whether REAPER was found (#191).
- Wavesmith: midifile.py (`wavesmith.py midi`), a standard-library MIDI writer: a chiptune song's notes (one track
  per channel, drums on channel 10 with General MIDI notes), or a tempo and bar grid (#191).
- Wavesmith: review fixes in the DAW round trip. A sound at another sample rate than the REAPER project renders in
  a pass of its own at its own rate, so an untouched one is no longer resampled and logged as an edit (music stems
  must share one rate). OGG files are written with ffmpeg's `-fflags +bitexact` (a fixed stream serial), so the same
  audio is the same bytes and a second re-export finds an edited OGG already in the game. OGG loops keep their
  LOOPSTART / LOOPLENGTH. `daw export` keeps an OGG or FLAC's own bytes in `originals/`, so an undone edit puts the
  exact file back. The working copies are checked against the SHA-256 they were made with: an edit saved into one
  is said and counts as an edit, and is never put back as the original. A manifest's root must lead up to the game
  root it was made from (run from there, or `--root`). A game file that cannot be replaced (held open) is a named
  problem, and the files written before it are still recorded. `midi grid --bpm` below 4 is an `[error]`, not a
  traceback (#191).
- Wavesmith: test_daw.py checks the round trip offline against a stand-in REAPER (golden .rpp text, no local path
  in any project file, untouched and edited round trips, conflicts, renames, music stems, a hanging REAPER, the
  universal route); `ReaperLiveExam` runs the real REAPER when `REAPER_BIN` is set (checked with REAPER 7.84 on
  Windows 11: about 15 s a render, %APPDATA%/REAPER untouched, a project REAPER saved itself still round-trips).
  test_midifile.py checks the MIDI bytes (#191).
- Games: the .gitignore leaves out REAPER's backups and peak files and the render folder each re-export refills (#191).

## 0.9.0 (2026-11-05, first tagged with 0.12.0): Pixelorama checked against the real release
- Dotwork: Pixelorama 1.2.4 is checked against the release. A live exam (`PixeloramaLiveExam`, run when
  `PIXELORAMA_BIN` is set, about 13 s) has the real Pixelorama open, save and export Dotwork's `.pxo` files headless
  through a small extension in a user folder of its own: the version 8 files it saves (cels cropped to their
  pixels) read back equal to the game's frames and to Pixelorama's own export, an untouched re-export changes no
  file, and a pixel set in Pixelorama changes only its frame, its sheet and the manifests. The reader needed no change;
  an offline exam pins the shape 1.2.4 saves. Dotwork keeps writing version 7 (1.2.3 reads every cel as a whole
  canvas). The README now says Pixelorama refills a blank export folder with the file's own folder (#67).
- Dotwork: a Pixelorama re-export carries blend modes (all 22), clipping masks, groups that blend their own layers
  (with their opacity) and animated layer opacity (every keyframe curve) instead of stopping. Pixelorama 1.2.4 has two
  composites that disagree: its command-line export blends Normal layers on the CPU and leaves those features out,
  its window blends on the GPU with a shader that applies them. A project of Normal layers now composites as the
  command-line export does, byte for byte (Godot's float math, alpha x opacity and the result truncated to 8 bits,
  where Dotwork rounded before); one with a blend mode, a clipping mask or a blending group composites as the shader
  does, which lands 85 to 94 % of pixels equal to Pixelorama's window and nearly all the rest one or two steps off
  (the GPU rounds near a half step its own way). A frame of one layer at full opacity is still copied as it is. Layer
  effects still stop the re-export, now saying they run only on the GPU. Offline, a fixture of small projects
  Pixelorama itself composited pins both; the live exam checks the headless one exactly and, with
  `PIXELORAMA_WINDOW=1`, the windowed one (fixes #66).
- Dotwork: Pixelorama tilemap layers. A visible tilemap layer no longer stops a re-export: it is drawn from its tiles
  and cells, every flip and transpose as Pixelorama draws them, and composited like a pixel layer. A tilemap project
  of your own in `<src_dir>/pixelorama/tilemaps/` re-exports to `<art_dir>/tilemaps/<name>/`: the tileset atlas at
  its tile size, a TileSet from Dotwork's writer (terrains, peering bits, probabilities, a `surface` custom data layer
  and full-tile collision from each tile's user data), a TileMapLayer scene per frame and a JSON map for every engine
  (with `--engine none`, the PNG and the JSON). `dotwork.py pixelorama` also builds a tilemap project from each map
  scene mapbuild painted and each square TileSet no map uses; each tile carries its atlas slot, so after Pixelorama
  renumbers its tiles an edited tile still lands in its slot and an edited cell in the map scene (only its
  `tile_map_data` lines), and the TileSet is never rewritten. A tile Pixelorama added (Auto or Stack tile mode) stops
  the re-export and says to draw in Manual mode. `verify` now checks that every TileMapLayer cell finds its tile.
  Checked against Pixelorama 1.2.4 (the live exam has it save tilemaps and edit a cell and a tile: only the atlas, the
  map and the manifest change) and Godot 4.7.2 (a Movie Maker capture of both kinds of map equals Dotwork's drawing
  on every opaque pixel).
- Dotwork: a Dotwork panel inside Pixelorama 1.2.4 (an extension, source in `tools/art/dotwork/pixelorama_extension/`).
  `dotwork.py pixelorama --install-extension` copies it into Pixelorama's extensions folder and writes a small config
  beside it (which Python, `dotwork.py` and game folder to use, and Godot for `verify`; one row per game; Pixelorama's
  own settings are not touched), and you enable it once in Edit > Preferences > Extensions. For the `.pxo` open in
  Pixelorama the Dotwork tab shows which game asset it is, its game files, Dotwork's QA notes on it, why a re-export
  would stop and whether the file holds a folder of your machine (`dotwork.py pixelorama --info`); Re-export to game
  saves the file with its export folder blank and runs `pixelorama --reexport --clear-export-path` in the background,
  then shows the result; Next asset and Show in game folder do what they say. A missing config, a Python or game
  folder that moved, or a `.pxo` from elsewhere gets a message saying what to run. The live exam installs the panel
  into its own user folder, sets a pixel in Pixelorama and drives the panel's refresh and re-export: the game changes
  exactly as with the command line (with real `verify` when `GODOT_BIN` is set); the panel's text helpers run under
  plain Godot offline. The tab's look and its clicks in Pixelorama's window still need a look by eye.
- Dotwork: `dotwork.py log` no longer logs hand work as AI output. Every row said "Dotwork (local ComfyUI)" and
  "generated locally", so a tilemap drawn in Pixelorama or a frame added in Aseprite read as model output in
  `ASSET_LOG.md` and the credits. A file's origin now comes from its manifest row (models, or no model and a
  Pixelorama or Aseprite source, workflow or polish note, or drawn in code), and the Source, Author, License and
  AI-assisted cells name only the origins the pack holds: a pack you drew is "drawn by hand in Pixelorama", "own
  work" and AI-assisted `no`; a pack of model output with a frame you added stays `pre-generated` and names both. A
  code-drawn frame you touched up stays "drawn in code" (its Modified? column says `yes`).
- Godot: `dev.py check` skips folders Godot ignores (a `.gdignore` in them, as `tools/art/dotwork/` has). It compiled
  Dotwork's Pixelorama extension, whose scripts use Pixelorama's classes, and failed every new Godot game.

## 0.8.3 (2026-11-05, first tagged with 0.12.0): fixes, and real-world maps when a game is set in a real place
- Real-world maps: when a game is set in a real place, its CLAUDE.md and the make-a-game interview now offer
  OpenStreetMap and national elevation data (already listed in `docs/resources/world-and-levels.md`) once, as an
  option; the tooling is planned (#192).
- `docs/resources/world-and-levels.md` lists elevation sources by region (US, European national portals, global),
  with the surface-versus-bare-earth and non-commercial traps; every licence there is marked (verify).
- Gatekeeper (Godot): "Start over" resets the game in place, so the loaded model stays and a reply still on its way
  is dropped; both start buttons wait for a model load, which gives one intro instead of two (#1).
- Gatekeeper (Godot): a line typed while the guard is still thinking (or after the game ended) stays in the box
  instead of being cleared and lost; Enter again sends it once Bram has answered (#2).
- Gatekeeper (Godot): a plugin error is reported as `model error`, not "too slow"; an error or `MAX_SLOW_REPLIES`
  (2) timeouts in a row drop the model for the session and the scripted guard plays on at once (`MODEL_LOST`),
  instead of a 12 s timeout on every line; the history calls in `reply()` and `reset()` have the reply timeout too,
  and a failed warm-up fails the load. Proven with a stand-in chat (the example's new test_guard_brain.gd exam) (#3).
- Gatekeeper (Godot): a voice reply is cached only once it is known to play; a 200 that is not audio is skipped and
  leaves no file, and a broken cached file is dropped so the line is fetched again (#4).
- Gatekeeper (Godot): the checks can fail now: `--llm --autoplay` logs `MODEL_MISSING` and exits 1 when the run
  played the scripted guard; the after-the-end rule test compares with a snapshot instead of the state with itself;
  the live eval counts only labels from the model and reports fallbacks apart (`tally()`, unit tested); the trust
  clamp, "no single line opens the gate" and "the regex lists exactly the intents" tests from the web twin (#5).
- Gatekeeper (Godot): an exported build no longer tells players to run the developer's setup script; it names what
  is missing and looks for the model in a `models` folder next to the game (not in the .pck). Scripted `--autoplay`
  stops its sounds and waits 0.2 s before quitting, so it no longer ends with `1 resources still in use at exit` (#6).
- Rune Delve (Unreal): the bot pair test states its margin over the pillar thresholds (named constants, logged as
  `[test] pair: margin ...`) and warns when it passes with none, as it does now (weaver 65 against 55, 3 clears
  against 0). The balance is not retuned: that waits for a human playtest (#7).
- Rune Delve (Unreal): `-quitatend` exits 3 after `MAGE_DOWN` or `TIMEOUT` (it always gave 0: UE 5.8 drops the code
  of a clean exit); the world still shuts down cleanly, then the process ends with the code. The `-nullrhi` drift is
  traced to the runtime NavMesh, which every bolt rebuilds in real time; not fixed yet (#8).
- Graveyard Shift (Unity): `Smoke_D` no longer flakes at the 104 cap. Its 103 was a night starting a frame late:
  `LevelBuilder` sized the ground and props after their colliders existed with auto sync off, so the keeper's first
  step waited for a physics step that came or not by real time spent loading. `Build` now ends with
  `Physics.SyncTransforms()`; `Smoke_R6` runs the first frames with no physics step (old code: 0.000 m walked).
  Careful and always-dark replay exactly; always-lit's catches still read 12 or 14 (two ghosts passing close) (#9).
- Scrap Tanks (C++/SDL2): sight counts a tank's two hull edges, not only its center, so a raider with its flank
  showing past cover is seen (a new test slides a tank behind the center rock). The pillar still holds and moved:
  cover 30 of 40 seeds, charging 13 of 40, debug and release alike (was 25 and 11) (#11).
- Scrap Tanks (C++/SDL2): the skilled bot's HIDE search skips spots no nav path reaches, as the two Tactics pickers
  already did, so it no longer picks a nav-island spot and stalls against the center rock (20 such picks in a new
  test_arena.cpp sweep on the old code). The scenario pair is unchanged (#153).
- LÖVE: `check`, `smoke`, `--screenshot`, `--record` and `--data-dir` work in a project folder whose path has a
  character outside the Windows code page ("Í", a curly quote). `io.open` took the path in the code page, so
  `check` reported every file as `cannot read the file` and `smoke` said "the game does not compile". The checker
  and the new `TextStore.file` (the folder store and main.lua's captures) open files with `_wfopen`, `_wremove`
  and `_wrename` through the FFI on Windows; a boot file the checker cannot read is reported as that (#98).
- Web, LÖVE: `smoke --drive menus` reaches master volume 0.5 from any start value, as Godot does since #43: it
  presses left or right until the live setting is there (`slideAction` in the web shell's new `driveLogic.ts`,
  `Drive.slide_action` in LÖVE). A data folder holding 0.3 drove web to 0 and aborted, and left LÖVE at 0.3 (#133).
- Web, Web 3D, RPG Maker MZ: `smoke --record DIR` clears the folder's old `f<digits>.png` frames before the run, as
  LÖVE does, so a shorter run after a longer one no longer leaves the earlier run's tail in the folder that
  `frames_to_gif.py` is pointed at. `scripts/test_dev_py.py` runs all three `smoke.mjs` under node with stand-in
  vite and Playwright modules (#134).
- Web 3D: `dev.py smoke -h` says what `--drive`, `--data-dir` and `--locale` do in this skeleton (it has no shell
  screens: a drive answers `DRIVE_ABORT`), instead of the web overlay's scenario list; the wording lives in
  `DRIVE_HELP`, `DATA_DIR_HELP` and `LOCALE_HELP` next to `BOOT_MARKER`, so the two dev.py files stay alike. Web and
  Web 3D `smoke.mjs` skip the data-dir checks of a scenario that answered `DRIVE_ABORT` or `DRIVE_IGNORED`, so a
  refused drive no longer also reports `settings.json missing` (#135).
- RPG Maker MZ: `setup --from` names the project file it copied (`open game/Project1.rmmzproject ...`); it said
  `game/game.rmmzproject`, but the copy keeps the name the editor gave the new project. The overlay's ENGINE.md
  and FLOW.md and the dev.py header say to open the `.rmmzproject` file in `game/` (#136).
- Web, Web 3D, LÖVE: a typewriter subtitle with no reveal data that fits the shown text (none built, or a
  translation or the pseudo locale made it longer) types at 30 characters per second, faster when that would not
  finish within the line's duration, so the whole line shows before it is removed; long pseudo-locale lines
  vanished about two-thirds typed. LÖVE had the same gap for a hand-written `duration_s` with no reveal list.
  Godot already spreads such a line over its duration (#162).
- Web: the pseudo-locale drive no longer depends on machine speed. The subtitle clock stands still for the whole
  tour (`SubtitleBar.holdTime`), so the line the juice demo says while loading stays untyped and skipped, and the
  finished line is still up when the pause screen is checked. With the loading screen held 4 s and the pause 2 s
  late the old drive counted 256 labels; it counts 258, as at normal speed (#163).
- `fetch_asset.py`: an empty `docs/ASSET_LOG.md`, or one without its table, names the command that puts the log
  back rendered (`python <kit>/scripts/new_game.py --dest . --upgrade --restore docs/ASSET_LOG.md`); it said to
  restore it "from the kit", whose copy is a template with scaffold-time placeholders that doctor then reports (#173).
- Scrap Tanks (C++/SDL2): make_sprites.py checks the bpy launcher (uv, or `BPY_PYTHON`) and the kit's render tool
  before the first job and stops with `[error]` and exit 2 instead of a traceback; a render that dies before its
  first `[..]` line shows its last output lines; `--debug` prints each command and all output; a Windows path in
  `BPY_PYTHON` keeps its backslashes. A new exam, test_make_sprites.py, runs it with stand-in renderers (#154).
- Scrap Tanks (C++/SDL2): the README, HANDOFF and ROADMAP give the current doctest count, 66 test cases with 29 of
  them the kit's (fixed timestep, golden vectors, audio and shell files), not 61 and 15 or 46 (#155).
- Kit: `scripts/sync_examples.py` has an exam, `scripts/test_sync_examples.py`. It builds a fake kit and example in a
  temp folder (never the real examples) and checks that a kit change syncs, a game's edit stays and is reported as a
  .gold, settings.json and .gitignore come back merged, a binary file syncs, a CRLF copy is no change, a failed
  upgrade copies nothing back, and a second run says 0 synced without touching .game-kit.json (#13).
- Kit: `scripts/codename.py` and `scripts/new_game.py` have exams, `scripts/test_codename.py` (taken folders and
  files in any spelling, one free name left is the one picked, every name taken, a file as --check-dir, --seed) and
  `scripts/test_new_game.py` (a fake kit: new, adopt and upgrade rules, the profile footer, exit codes 1 and 2).
  doctor.py, session_context.py, frames_to_gif.py and yt_transcript.py still have none (#14).
- Docs: DISTILL_REPORT.md drops its stale 2026-10-19 "still unverified" table (Godot `build`, the Claude Code
  config checks and `run` on several engines were done since) in favor of the README table and KNOWN_ISSUES.md; it
  keeps the enforced rules (rechecked against EVIDENCE.md: F1 now has seven creators), the outside claims still
  unproven, and the experiments, each saying what is already done (#15).
- Blender: `prep_export.py` gives linked duplicates (objects sharing one mesh) their own mesh copy before applying
  transforms. Blender applied the transform to the shared mesh once and left the other objects with a leftover
  scale, so the export kept an unapplied scale and only the validator warned. test_prep_export.py has the case,
  two posts on one mesh with different scales and rotations (#18).
- Godot: review sheets and sources under `assets_src/` no longer ship in builds. The folder holds an empty
  `.gdignore` (Godot never imports it) and the three export presets exclude `assets_src/*`; a Windows, Linux
  and Web export of a game with a sheet there had it in the .pck before and has not now. Dotwork refuses a
  backdrop, logo, font or diorama sprite in a folder Godot ignores, naming it, instead of writing a scene that
  opens with a missing resource (#29).
- Art, audio and Blender tools check every file they write before they write any, and refuse an existing one
  without `--overwrite`: the `.gen.json` record beside a new output (`pixellab.py`, `comfy_local.py`,
  `eleven_audio.py`, `fish_tts.py`; the paid tools stop before spending, `comfy_local.py` before queueing and
  before writing any file of a job), the layout `.json` beside a `render_sprites.py` sheet, and an existing
  `wav normalize|loop --out` (new `--overwrite`; without `--out` the input is still changed in place).
  `sfx_synth.py` refuses a `--recipe` that names the `--out` WAV, which it replaced with JSON (#30).
- Malformed input is a clean `[error]` and exit 2, not a traceback: `pixel_sprite.py check` on a palette PNG
  whose PLTE is not whole 3-byte colors, and `chiptune.py` (with or without `--check`) on a song whose
  `channels`, `patterns` or `order` has the wrong type (`"channels": []`). `pixellab.py` downloads (also zip
  members) and `comfy_local.py strip` require a whole PNG, IHDR first and IEND last; a bare 8-byte signature
  was saved as an image. The `wavfile.py stats` item was fixed in 0.8.2 (#31).
- Small tool fixes: `chiptune.py` wraps a release tail longer than the looping song onto the loop whole (it
  folded into `mix[i - end]`, so all past one loop was lost); `svg_export.py` counts a nonzero Inkscape exit as
  a failure and calls an `--overwrite` target written only when its timestamp moved (an old file from the last
  second passed); `pixellab.py` gives every download of a job its own name (two links with one base name
  overwrote each other); `prep_export.py` refuses an LOD path that is the source (`--overwrite` replaced it);
  `eleven_audio.py check` exits 2 on an invalid key instead of `[ OK ] ... plan unknown`, which it still says
  for a key without the User read permission; `comfy_local.py` uploads with `overwrite=false`, so ComfyUI keeps
  its own input file of the same name and the node gets the name ComfyUI chose (#32).
- Engine smoke and capture fail when a capture failed: C++/SDL2 needs the game's end-of-run line (a game that quit
  early passed as "120 frames"; an early quit now passes only after `--until`'s marker) and a failed `--record`
  frame is an `[ERROR]`; Unity deletes an old screenshot before the run and fails on a missing one (it warned, and a
  stale file passed), a capture that cannot be saved is a test error, `GameKitCapture.Finish()` is documented as
  what saves the screenshot, and `GameKitScenes` throws when `SaveScene` fails; Godot's `capture.gd` exits 2 when
  the main scene does not load or `--frames` / `--every-ms` is not a whole number (blank capture, exit 0); web,
  web-3d and RPG Maker MZ `smoke.mjs` report a recorded frame that failed to save (it was swallowed). C++, Unity,
  Godot and the web smokes check each `--screenshot` and `--record` after the run. Web, web-3d and RPG Maker MZ
  `run` exit 2 when node or the launcher is missing (it gave 1). A new exam, `scripts/test_dev_py.py`, runs every
  engine's dev.py with the engine call faked (#33).
- `yt_transcript.py --whisper` without faster-whisper tries the captions first and exits 2 only when transcription
  is reached (it exited 2 before trying captions that would have worked); WebVTT cue identifiers (`1 Hello ...`)
  and NOTE, STYLE and REGION blocks stay out of the transcript. A new exam, `tools/test_yt_transcript.py`, runs on
  canned captions, offline (#34).
- Web 3D: `smoothDamp` (src/core/follow.ts) lands on the target and stops when a step would reach or cross it, so
  a follow already moving fast toward its target no longer overshoots (`smoothDamp(9, 10, 100, 0.2, 1/60)` gave
  10.42); new tests start with velocity toward and away from the target. No other engine has a smoothDamp; the
  juice springs and their golden vectors are unchanged (#35).
- Every engine's `dev.py`: on Windows a command with a timeout runs in a job object (`WinJob`, ctypes), and a
  timeout or Ctrl+C ends the whole job, so a grandchild whose parent already exited no longer keeps running and
  holding the output pipe (`taskkill /T` only finds children through living parents). A normal exit only lets go
  of the job; untimed commands (`run`, a browser a dev server opens) are left as before. `scripts/test_dev_py.py`
  runs a real orphan against each engine's `run` (#36).
- Every engine's `dev.py` on Linux and macOS: killing an untimed command (Ctrl+C) also kills what it started. Such a
  command shares dev.py's process group (so a terminal's Ctrl+C still reaches it as before), and `os.killpg` on it
  failed, which left a build server or test workers running when dev.py ran without a terminal; `kill_tree` now
  finds its descendants through `ps` and kills each. A timed command is still killed as its own group. Run live on
  Linux (Ubuntu under WSL, every engine but Unity, whose editor always runs timed); macOS's `ps` is (verify).
  `scripts/test_dev_py.py` fakes the process-group calls (#37).
- Dotwork: a job cancelled in ComfyUI (Cancel in the queue, `/interrupt`, taken off the queue or a restart) is
  reported with the render it was (`hero/walk/f: cancelled in ComfyUI ...`) and says that running the same command
  again resumes; any other failed job names its render too. `comfy_local.py` raises `JobCancelled` (a `JobError`)
  for both cancel cases. The interrupted status itself has been read since 0.7.5 (it said `failed: no message`
  before); the Dotwork exam's stand-in ComfyUI answers a cancelled job now (#38).
- Shell (Godot, LÖVE, web, web-3d): `telemetry.csv` has one column set in every engine, `time,session,event,detail`
  (UTC in whole seconds with a `Z`, a random 8-digit hex id per launch). LÖVE wrote seconds since launch
  (`session_s`), web had no session column and kept milliseconds, Godot's time had no `Z`. The reference
  (`tools/golden_vectors.py`) now writes `data/golden/telemetry.json` (header, session id, time and CSV quoting), and
  each of the four ports has a golden test for it (#42).
- Godot: `smoke --drive menus` reaches master volume 0.5 from any start value: it presses left or right until the
  live setting is there, instead of ten fixed presses left from 1.0, so a `--data-dir` seeded with 0.3 ended at 0
  and failed (#43).
- LÖVE: `dev.py smoke` without `--data-dir` runs in a fresh `build/smoke-data/` (as Godot does), so test runs no
  longer leave logs and crash files in the player's save folder, and `--drive menus` no longer rewrites the
  player's `settings.json` (master 0.5, reduce motion on). A hand-run `lovec . --smoke N --drive <scenario>` with no
  `--data-dir` stops with `DRIVE_IGNORED` and exit 1 instead of driving the save folder (#44, #107).
- Web, Web 3D: a settings file's language code is 2 to 12 code points, as the reference counts, not UTF-16 units
  (`String.length`), which differ for characters outside the Basic Multilingual Plane. Two new `settings_load`
  vectors in `shell.json` cover both directions; all eight ports pass them (#45).
- Unreal: the GameKitShell plugin works in a Blueprint-only project. `dev.py check` no longer refuses it there: it
  builds the engine's `UnrealEditor` target with `-Project`, which compiles only the plugin into its own
  `Binaries/`; `test` before that exits 2 with "run check first" instead of "no tests matched". Proven on UE 5.8
  in a project from the Blank Blueprint template (70 `GameKit.*` tests pass headless). Turning the plugin on from
  the editor's Plugins window is still untried (#47).
- Godot: a focused slider no longer looks like a hovered one. Godot's `Slider` has no focus style and draws one
  highlight for both, so the settings screen's sliders are now `FocusSlider` (`focus_slider.gd` in the shell
  scripts), an `HSlider` that draws the theme's focus outline on top while it has keyboard or gamepad focus (the
  `HSlider` focus style, else the `Button` one, so a Dotwork UI kit theme's outline shows too). New
  `test_ui_theme.gd` exam (#54).
- Web: the pseudo-locale drive counts the same labels on every run (258 on the template, 12 runs; it gave 260 or
  261). The juice demo's subtitle was counted on the loading screen with or without its first typed character: a
  subtitle line still typing now carries `data-settling` and the check skips it, the drive checks the line again
  once `finish()` has shown it, and it waits for the "saved" toast to leave after the menu has checked it. Each
  check logs `PSEUDO_SCREEN <screen> labels N problems M`, as LÖVE does. `finish()` shows the whole line even when
  the text is longer than its timing allows (pseudo text is 40 % longer, so it stopped at about two thirds) (#63).
- Dotwork: a `.pxo` that Pixelorama saved with the folder you last exported to (a full path on your machine) is named
  by `dotwork.py pixelorama` and `pixelorama --reexport` with a `[warn]` line, and `publish_check.py` warns about it
  too (it sits in the zipped project data, which the text scan cannot read). The new `--clear-export-path` blanks it
  in place; every other entry of the file stays as it was and the round trip gives the same frames. Without the
  flag, Dotwork does not rewrite the file (#69).
- Unity: `MusicPlayer` undoes a change asked back before its switch, as the Godot, LÖVE and web players do:
  `Request("combat")` then `Request("explore")` before the bar line leaves explore playing on instead of restarting
  it from the top. The decisions moved into Core `MusicQueue` (six EditMode tests); run once in Play mode with
  generated tones. Godot: a change asked while the current track waits out a stinger is planned from where that
  track enters (a beat or immediate switch could fall in the gap, so the track never sounded), as the other players
  plan it (#70).
- Wavesmith: the OGG Vorbis decoder trims a short first page the way libvorbis 1.3.7 does, checked sample by sample
  against libvorbis's own decode: the extra samples leave the output of that page's last packet, at most that
  packet's samples, not the first samples of the file (the count was right, the samples were not). The end trim takes
  at most the last packet's samples, as in libvorbis. A real Theora plus Vorbis file (ffmpeg test sources) is a new
  fixture and decodes as ffmpeg and libvorbis decode its audio (#73).
- Wavesmith: an OGG Vorbis stream that stops after a whole page without the end-of-stream flag (a cut capture or
  dump) decodes with a `[warn]` naming the missing end page; its end comes from that last page's granule position,
  as an end page's would. A file that stops inside a page or a packet is still truncated (exit 1). `oggvorbis.py
  towav` reads the channel count from the identification header (new `identification()`) and refuses 5.1 before
  decoding instead of after (#74).
- Wavesmith: `loudness measure` and `check-mix` read FLAC, OGG Vorbis and ffmpeg formats as they decode, as they
  already read WAV: 3 minutes of 48 kHz stereo tone plus noise peaked at 71 MB as FLAC (was 1.47 GB) and 49 MB as
  OGG (was 0.94 GB), the same numbers to the last digit. New `flacfile.stream()`, `oggvorbis.stream()` and
  `audioio.stream_audio()`; ffmpeg's temporary WAV is streamed and deleted. Profiled: on dense material the true
  peak's coarse locator runs on nearly every sample; it now works a run of blocks at a time with the same sums,
  34 s to 21 s per minute of 48 kHz stereo tone plus white noise, and the header says what drives the cost (#77).
- Unity: AudioEventPlayer and the access sliders run in Play mode, in three new PlayMode tests
  (`AudioPlayModeTests.cs`, `dev.py test --mode PlayMode --filter Audio`) on real AudioSources with generated
  clips: 24 plays of a four-take event never repeat a take back to back and keep pitch and volume in range, a
  dialogue duck takes the music bus to -4 / -8 / -4 / 0 dB on the planned times, and each slider changes only its
  own buses (ambience under sfx follows the sfx slider once). Passed on Unity 6000.6.6f1 (#79).
- Dotwork aseprite: `--reexport` refuses a `.aseprite` with two tags of one name (case ignored, as Windows file
  names are) before writing anything; each numbered its frames from 00, so the second overwrote the first one's and
  the shipped clip came back mixed with verify passing. An export that names one file twice is refused too. Checked
  in Aseprite 1.3.18 on fixtures the exam builds there (a new live exam, run when `ASEPRITE_BIN` is set) (#81).
- Dotwork aseprite: build refuses an asset whose frames are not all one size, naming the sizes, before any source
  is written, as `pixelorama` does. The sprite took the first frame's size, so an untouched round trip shipped the
  other clips padded or cropped to it, off their anchor, with verify passing. One canvas per clip in either editor
  is still open (#82).
- CI: the game's `ci.yml` has a blank line between the "Music director vectors" and "Audio accessibility vectors"
  steps, as between every other pair; nothing changes at run time (#95).
- Dotwork bdf: the strings are read as `fonts-check` reads them (`fontcheck.read_strings`), so a PO `msgstr ""` with
  continuation lines, `\"` and `\n` escapes, non-ASCII text and `.pot` files are checked and subset. The lane read
  only the empty first line (the font shipped without that string's letters while the pack said every character was
  covered) and turned non-ASCII on a `\u` line into mojibake. Coverage compares the composed (NFC) form and skips
  control and format characters as `fonts-check` does; a string's place reads `file:string id` (#96).
- Dotwork hand polish: `aseprite --reexport` and `pixelorama --reexport` with `--engine none` skip the Godot verify,
  as `pack --engine none` does, and end with `[ OK ] re-exported (N files changed; no Godot verify with --engine
  none)`, exit 0. They wrote the game, then always ran verify and exited 2 (no `project.godot`, or no `GODOT_BIN`),
  so a successful re-export read as a failure. With Godot the line now counts the changed files too (#99).
- Dotwork pixelorama: build compares an existing `.pxo` by what it shows, as `aseprite` does (the tags, the frame
  count, each frame's look and its time on screen), not by its bytes. Pixelorama rewrites the project data on each save,
  so a file only opened and saved, or polished and re-exported, was "kept: it differs from the game's frames" on
  every build, and `--overwrite` then replaced the user's layers and palette with Dotwork's flat file (#100).
- Dotwork log: `log --pack` writes "Modified? yes" in `docs/ASSET_LOG.md` when any row of the pack carries a polish
  note from either editor, also after an earlier note (`qa ...; hand-polished in Aseprite`). It matched only the
  exact note `hand-polished in Aseprite`, so every Pixelorama polish was logged as unmodified (#101).
- Dotwork bdf: a malformed or hostile BDF stops with `[error] <font>: line N: ...` (exit 2) before any array is made:
  a BBX past 256 px or below 0 (`BBX 200000 200000` allocated 40 GB), a BBX of fewer than four numbers, a bad
  `FONT_ASCENT`, `ENCODING` or `DWIDTH`, a bitmap row that is not hex, or more rows than the BBX height; these
  crashed as "unexpected failure". A glyph too big for the 256 px page at its `scale` is named, and `scale` is a
  whole number from 1 to 16 (#108).
- Dotwork aseprite: build writes the palette and frame list Aseprite loads to the work folder and removes both after
  the run, also when it fails. The `<name>.gpl` stayed beside every `.aseprite` in the game's tracked sources; ones
  an earlier build left there are not used and can be deleted (#109).
- Dotwork skill: step 2 quotes the lock's GPU memory per tier, 8 GB for sprites, 12 GB for rotation and 16 GB for
  animation (it said 16 GB for rotation, so a 12 GB card was turned away); a Dotwork exam now compares the skill's
  and the README's numbers with `models.lock.json` (#110).
- Scaffolder: `.game-kit.json` records the slug, and `--adopt`/`--upgrade` take the name, slug and engine from it
  (`--dest <game> --upgrade` is enough). A different `--engine` is refused with exit 2 (it mixed a second overlay
  into the project and rewrote the record), a different `--name` or `--slug` too unless `--rename`, which keeps
  the recorded slug unless `--slug` is given. The README's "same command with `--upgrade`" without the original
  `--slug` re-derived it, so CMake targets, the Cargo package and the LÖVE save folder changed silently. A record
  from an older kit has no slug: it is derived from the recorded name, with an `[info]` line. `sync_examples.py`
  passes the recorded slug (#97).
- Doctor: the asset-log check also looks in `public/assets` (web, web-3d) and `game/img` (RPG Maker MZ), so media
  there with no filled `ASSET_LOG.md` row gets the `[WARN]` line as in the other overlays; it looked only for
  `assets`, `Assets` and `Content` and reported those projects healthy. New exam `tools/test_doctor.py` (#104).
- fetch_asset.py: a ShareAlike license (`CC BY-SA 4.0`, `CC-BY-SA 3.0`, "share-alike") is still accepted, now with
  `[warn] ShareAlike: derivatives of this asset must be released under the same license; check SOP-04 before
  shipping` and `SHAREALIKE` in the log row's Notes, also on `--dry-run`. "CC BY" matched inside "CC BY-SA", so
  the pack was logged as a plain CC BY asset with no note (#105).
- Scaffolder: `--upgrade --restore <path>` puts a kit file you deleted back, rendered for the game (name, date,
  footer), and records it, so the next `--upgrade` treats it as untouched. The "left out N kit file(s) you deleted"
  line said to copy one back from the kit, which leaves a raw template (`# {{FOOTER}}`, `{{GAME_NAME}}`) that the
  next upgrade took for your edit and answered with a `.gold`. `doctor.py` now scans the overlays' source files
  (`.gd .tscn .cs .cpp .h .rs .lua .ts .js .html` and more, not only docs and config) and reports the profile
  tokens `{{FOOTER}}`, `{{PROFILE_STYLE}}` and `{{FOOTER_RULE}}` too (#122).
- Scaffolder: a `.game-kit.json` that does not parse (truncated by a crash or a bad merge), is not UTF-8 or holds no
  JSON object stops `--adopt` and `--upgrade` with `[error] .game-kit.json is not valid JSON (...)`, exit 2, and is
  left as it was. It was taken as a project with no record: `--upgrade` claimed a pre-0.3 kit, wrote a `.gold` for
  every file that differed and replaced the record, losing the scaffold date, history and profile (#123).
- Docs: `engines/_template/README.md` no longer tells a new overlay's `dev.py` to include the footer line (kit tools
  carry none); it asks for the header block instead, says starter files end with a `{{FOOTER}}` line, and its
  checklist checks both (#124).
- Golden vectors: the reference reports `Infinity` or `NaN` in a settings resolution or a save version as a
  problem, as the ports do (the default resolution; `bad version`), instead of raising `OverflowError` or
  `ValueError`. Four new cases in `data/golden/shell.json` pin the ports to it; they pass on every engine whose
  reader accepts or refuses the constants (refused counts as `unreadable`, also one problem) (#132).
- Godot: the three export presets exclude `.game-kit.json`, so Windows, Linux and Web builds no longer carry the
  kit's record (version, profile, upgrade history and a hash per kit file; Godot exports `.json` as a resource).
  `dev.py build` lists the exported .pck and fails naming any `.game-kit.json`, `tests/`, `tools/`, `docs/`,
  `addons/gut/`, `data/golden/` or `assets_src/` file inside, so a preset edited in the editor cannot bring them
  back unseen. Checked on all three presets with Godot 4.7.2 (92 files, was 93). The other engines' builds take an
  allow list or their asset folder only and never had it (#161).
- Dotwork bdf: one font takes at most `MAX_PAGES` (64) pages of 256 px. Past it the run stops with `[error] bdf
  <name>: N glyphs at scale S need P pages of 256 px (limit 64); keep fewer glyphs (drop "all") or lower "scale"`
  (exit 2) before any page is allocated or the last run's font is removed. `"all": true` on a large CJK font at a
  high `scale` allocated and wrote thousands of PNGs first (#172).
- Wavesmith: the WAV reader reads 8 and 24-bit PCM, 32 / 64-bit float and WAVE_FORMAT_EXTENSIBLE headers (what
  ffmpeg writes for 24 and 32-bit PCM and for 16-bit above 48 kHz), whole or streamed. Only 16 and 32-bit integer
  PCM with a plain header were read, so a 24-bit DAW export or voice line stopped every tool, `formats convert`
  included. A WAV in another sample format (ADPCM, A-law) goes through ffmpeg when it is installed and names it when
  it is not; `formats info` says which decoder read it (#102).
- Wavesmith flacfile.py: a STREAMINFO block shorter than 34 bytes (a header that says length 0, or a real file
  zeroed after its STREAMINFO by a cut, padded download), a second STREAMINFO block, or a metadata block that runs
  past the end of the file is a named corrupt file (`[FAIL]`, exit 1; `[error]`, exit 2, from the tools that read
  audio) instead of a `struct.error` traceback (#111).
- Wavesmith dialogue: `lint` and `build` name a malformed dialogue.json instead of printing a traceback: a file that
  is not an object is `[error]` (exit 2); a line that is not an object, an id that is not a string, `speakers` or
  `sequences` of the wrong type, a sequence that is not a list of steps, a speaker's `cps` of 0 or less, and any
  other value of the wrong type are `[FAIL]` lines (exit 1), and nothing is written (#112).
- Wavesmith music: `grid` and `loop` refuse a `--bpm` outside 20..400, `--bars` below 1 or `--beats-per-bar` outside
  1..16 with `[error] ...` (exit 2), the ranges `validate` applies to music.json; `--bpm 0` divided by zero, `--bars 0`
  failed packing the loop and `--bpm -96` printed negative bar times. `validate` on a file that is not a JSON object
  names it and exits 1 instead of crashing on its summary line (#113).
- Wavesmith events: `validate` and `audit` exit 2, not 1, when the events file cannot be read or is not JSON, as the
  header and every other Wavesmith tool say; a CI step reading 1 as "the file has problems" misread a wrong path
  (#114).
- Wavesmith loudness: `mono --json` stays JSON when a file cancels completely in mono: `loss_lu` is `null` with
  `"cancels": true` instead of `Infinity`, which jq and `JSON.parse` refuse, and the problem reads "the mono downmix
  is silent: the channels cancel" instead of "loses inf LU". The JSON paths of `measure` and `mono` refuse any
  non-finite value instead of writing it (#115).
- Wavesmith dialogue: the SRT export lays a cue out again when the speaker's `NAME: ` prefix would push its first
  line past the 40-character limit, so a 38-character line by "Research lead" reads `RESEARCH LEAD:` over the text
  instead of one 53-character line. When the cue cannot fit even then, `lint` and `build` warn about the line and
  `export` names the cue, so the display name or the opening can be shortened (WebVTT's `<v Name>` was fine) (#116).
- Docs: SOP-18, SOP-19, `/game-feel`, `/game-shell` and KNOWN_ISSUES say what RPG Maker MZ and web-3d ship: MZ has no
  juice or shell port (its ENGINE.md now says so, and ENGINE_FLOW maps the rules onto MZ's own screens, shake and
  flash), web-3d has the tested logic but no screens, and the `--drive` scenario runs are for Godot, LÖVE and web,
  with the same checks by hand elsewhere. A new kit exam, `scripts/test_kit_docs.py`, checks these lines against the
  engines in the tree (#103).
- web-3d ENGINE.md: the `src/core/` layout line names the modules that are there (juice, settings, bindings, saves,
  i18n, user data, dialogue and the three audio modules) instead of timers, math, RNG and state machines, which never
  were, and says there is no `src/shell/`; the web ENGINE.md line gains coyote, hold toggle, dialogue and the audio
  modules. `test_kit_docs.py` checks both lines against `src/core/` (#117).
- Bevy FLOW.md: the audio vectors line gives the three working commands (`wavesmith.py events vectors --write`,
  `music vectors --write`, `access vectors --write`) instead of a bare `vectors --write`, which `wavesmith.py`
  refuses. `test_kit_docs.py` checks every Wavesmith command the docs give against its subcommands (#118).
- Docs: `docs/resources/ai-tools.md` no longer says PixelLab was never run live; it points at SOP-16, which lists the
  commands that were (now `fix reduce-colors`, as the README says, not every `fix` operation).
  `test_kit_docs.py` checks that the README and SOP-16 lists agree (#119).
- Evidence ledger: K02, the local music-generation test cited by `docs/resources/audio.md`, has a row (machine,
  prompts, takes, results, grade); K01 points at the README "What was tested" table instead of describing the six
  engines of 0.2; two rules on grade C sources are labelled tips, as the ledger requires ("Tell Claude your machine",
  E27; the death rule, E09). `test_kit_docs.py` checks that every cited E, F and K ID has a row (#120).
- README, START_HERE and the SOP index match the tree: 23 short SOPs (game feel, the shell, accessibility, Steam and
  itch, balancing and marketing were missing from the list), one example for every engine but LÖVE, ten example
  games, and the SOP-16 row names `/dotwork`. `test_kit_docs.py` checks the counts against the folders and that
  every skill is in the SOP index (#121).
- Bevy: a save slot whose primary file is not valid UTF-8 (torn inside a multibyte character) can be saved again.
  `save_store::write_to` read it with `read_to_string` and returned `cannot read ...: stream did not contain valid
  UTF-8` on every later save; it now counts the file as unreadable, as `load_from` and the other ports do, writes
  the new save and keeps the good `.bak` (#106).
- Music directors: a `quantize` the reference does not know (a typo such as `"bars"`) is an error in Godot
  (`push_error`, empty plan), C++ (throws), Unreal (an empty plan with the new `FGameKitMusicPlan::Error`) and web and
  web 3D (throws); it planned a phrase change. Unreal refuses an unknown stinger name (it played a one-bar stinger) and
  C++ and Unreal plan `"stinger": ""` as no stinger, as `music.py` does (C++ threw `unknown stinger`). `music validate`
  requires `sync` to be `true` or `false` and `phrase_bars` a whole number, 1 or more, the two fields the engines read
  differently; docs/resources/audio.md says the directors do not validate the file (#125).
- C++/SDL2, Unreal: the audio director counts an event's variants from `files`, as `audio_events.py` does, not from
  `lengths_ms` (a random pick could never choose a file past the last length); fewer lengths than files is refused
  (C++ when the director is made, Unreal at `Play`). `max_voices` 0 with steal `oldest` throws in C++ and is an error
  in Unreal; both read past the voice list (the Unreal editor crashed on `Array index out of bounds: -1`). Unreal's
  `Play` returns the new `EGameKitPlayResult::Error` with the reason in `FGameKitPlayDecision::Error` for an unknown
  event or a time earlier than the last call (it said `Capped`), and `Duck` takes an optional `OutError` (#126).
- Wavesmith events: `validate` caps `seed` at 2^53 - 1 (9007199254740991), the largest whole number the engines
  that read JSON numbers as doubles (Godot, Unity, Unreal, web, LÖVE, RPG Maker MZ) hold exactly; it accepted any
  size and said "ports compute with it exactly", so a seed of 2^53 + 1 played other takes in Godot and Unreal and
  threw in Unity. Unity's own limit moves from 9e15 to the same 2^53 - 1, and data/golden/audio.json has a case at
  that seed, which all nine engines pass (#127).
- Godot, Unity, Bevy: a slot whose `.bak` holds a save from a newer game version refuses every write, as C++ and
  Unreal already did. The three wrote a new primary, and the save after it copied that file over the newer `.bak`,
  so the newer build's progress was lost on the second save. The rule is in the `save_load` docstring and SOP-19
  step 3, and every port has a file test for it (#128).
- Unity, Godot: a bus whose `parent` is not text (a number, null) hangs under master, as `access.py` says. Unity threw
  `parent must be text` while applying the settings; Godot returned the number as the parent and stopped on a script
  error (`Invalid operands 'float' and 'String'`). data/golden/access.json has a case with such parents, which all
  nine engines pass (#129).
- Godot: `Spring.squash_xy()` gives the squash scale as two 64-bit numbers, as every other port does, and the golden
  test compares those; `squash()` still packs them into a `Vector2` for a sprite's scale. The test compared the
  32-bit `Vector2`, which a large amount pushes past the file's tolerance: data/golden/juice.json has a point at
  100.3 (the old test was off by 3.05e-6 there), which all eight engines with the juice module pass (#130).
- Golden vectors: the C++/SDL2 and Unreal exams compare whole results, as the other ports do. C++ checks a play
  decision's field set against audio.json and that every case type it has a checker for appears in juice.json and
  shell.json (a shell.json with no `pseudo` case passed); Unreal compares shake, hitstop, follow and spring steps as
  objects, so a field the reference adds to `expect` fails there too (planted `time` fields and a missing `pseudo`
  case passed the old checks). juice.json, shell.json and telemetry.json have tolerance 1e-9 instead of 1e-6, at
  which a float32 port of the easing curves or hitstop would have passed; every engine passes at 1e-9 (#131).
- Godot, LÖVE: the subtitle typewriter uses a line's reveal list only when it has one entry per character of the
  text, as web and web 3D do; otherwise the line types at 30 characters a second, faster when that would not finish
  within `duration_s`. A list shorter than the text (a translation, the pseudo locale, data built for another take)
  stopped the count at its length, so the line never showed in full and Godot's `is_fully_shown()` never turned
  true. The rule is Wavesmith's new `dialogue.py` `reveal_count`, and `wavesmith.py dialogue vectors --write`
  writes data/golden/dialogue.json (27 steps: lists that fit, are too short or too long, no list, no duration, a
  zero duration, code points), which Godot, LÖVE, web and web 3D pass (#174).
- Unreal: `dev.py test` and `smoke` report an editor that exits non-zero before any test passed as a crash,
  `[FAIL] the editor exited with code N before any test finished` and exit 1, instead of "no tests matched" and
  exit 2. An empty filter stays exit 2: UE 5.8 exits 255 there too, but logs "No automation tests matched" first,
  and that line decides. Unity (no results file) and Godot (a non-zero exit) already gave 1 (#176).
- Wavesmith music: `validate` checks `default_transition`, which every rule inherits, as it checks a `transitions`
  entry: a value that is not an object (it passed, then `plan` crashed), an unknown `quantize` (which the engine
  directors refuse since #125), a `fade_ms` outside 0..10000, a non-boolean `sync`, a bad `phrase_bars` or an
  unknown stinger is a named problem (#177).
- Crimson Nebula (Bevy): the Ignorer dodges a closed lane only once that barrier has zapped it (`Racer::zapped_by`,
  cleared when the kart leaves the section), as its header and HOW_IT_WAS_MADE say. Any earlier bonk (a lap 1 wall,
  the lap 2 zap) made it swerve from the section entrance, before the barrier had started, so on seeds with two
  closures it missed the lap 3 zap. Reading now wins 20 of 20 seeds by 0.6 to 1.9 s (was 0.4 to 1.9 s); a new bot
  test gives the Ignorer an earlier bonk and expects the lap 2 zap (#137).
- Crimson Nebula (Bevy): a barrier that goes live beside a kart already in its section (a lapped player) leaves
  that kart alone until it leaves the section (`Racer::closure_grace`), as GDD pillar 1 promises ("changes that pop
  in under your wheels" are ruled out). It moved the kart up to 8 m across the track in one tick and zapped it. The
  bot balance is unchanged (no bot is ever lapped) (#141).
- Crimson Nebula (Bevy): Enter on the results starts a new race under `--autoplay` too, as the results line
  offers (it did nothing, so `dev.py run -- --autoplay reader` could only be left with Esc); the bot drives the new
  race. The README and HOW_IT_WAS_MADE say "race again on a new seed", not "a new track": the loop never changes,
  the seed picks which sections change (#142).
- Crimson Nebula (Bevy): HOW_IT_WAS_MADE gives the loop's 12 control points (it said 24), and it and the GDD no
  longer promise a "long" lap 2 warning: every change warns `WARN_TIME` (2 s) ahead. The README's `dev.py test`
  line drops its stale "78 tests" (98 run now; the kit's exams grow with every sync) (#143).
- Examples: the Ghost Lantern, Courier Dash, Coyote Hop and Lockpick MZ READMEs no longer give a test count (120,
  144, 78 and 16; 143, 164, 90 and 36 ran at 0.8.2). Each sync brings in more kit exams, so the lines say what the
  tests cover instead (#144).
- Examples: asset logs without licence evidence are marked or fixed. Lockpick MZ drops its empty A-0001 template
  row (it has no third-party assets). Crimson Nebula's A-0001 (Bevy's built-in Fira Mono subset) gets a
  licence file, the font's own name table quoted as stored (copyright, designer, "Open Font License,
  version 1.1 or later" and its URL), with the author column taken from it; the full OFL text is not in the crate and
  is still to be saved (verify). Gatekeeper Godot's A-0005 (the live Fish Audio voice) says plainly that no terms are
  stored yet (#145).
- Graveyard Shift (Unity): the GDD, ARCHITECTURE, HANDOFF and both READMEs describe the game as built: one ghost
  per patrol loop plus the difficulty's extras (not three), a night of five minutes at most (not under three), and a
  v3 save with v1 and v2 migrations; the `Smoke_E` comment names the 8 generated yards it checks, not 16 (#146).
- Graveyard Shift (Unity): after a catch the ghost that made it goes home, as the code said it did. The sweep that
  tires hunters measured from the keeper after his respawn at the gate, so a catch more than 30 m out (most of them
  on the 4x yards) left the catching ghost hunting the empty spot. It now tires the ghost at the catch and hunters
  within 30 m of the catch or the start; `Smoke_R7` catches the keeper 64 m from the start (old code: the catcher
  still hunting). Escapes are unchanged on the asserted trios; catches moved (hand-made lit 14 to 11, generated
  careful 23 to 20, lit 13 to 20) (#147).
- Graveyard Shift (Unity): Esc reaches the title screen after a `--difficulty` launch, as the HUD says. The reload
  read the same command line, skipped the title again, and Esc only restarted the night. The command line is read
  once per session (`GraveyardGame.CommandLine`) and Esc (`BackToTitle`) spends its difficulty; the title saves
  the next one. `Smoke_R8` (old code: no title after Esc) (#148).
- Graveyard Shift (Unity): the two narrator takes re-voiced on 2026-10-23 are normalized to peak -3 dBFS like
  the rest of the cast (they played 2.6 dB louder), with Wavesmith's `wavfile.py normalize`, which also writes their
  real header sizes. The nine ghost voice files had the same streamed placeholder sizes (RIFF 0xFFFFFF24, data
  0xFFFFFF00, about 4 GB); their headers are set to the real sizes, samples unchanged. Unity's importer read every
  one to the end of the file (4.830 s for `narrator_escape_1`), so the end card's music duck was never stuck. Two
  EditMode tests check every WAV header and the narrator peak (old files: 11 headers and 2 peaks reported); the
  ASSET_LOG rows say what changed. The mix still needs ears (#139).
- Graveyard Shift (Unity): the ASSET_LOG rows and licence evidence for the two re-voiced narrator lines give the
  text and hash of the files that ship ("Twelve", not "Six"); HOW_IT_WAS_MADE says three lines said six and one,
  `narrator_intro_1`, still does. An EditMode test checks every `.gen.json` sidecar's text and hash against
  `docs/licenses/` (old evidence: both lines reported). Re-voicing `narrator_intro_1` is still to do (#138).
- Rune Delve (Unreal): GDD pillar 3 says what the game does: death ends the delve and R (or Start) begins it again
  at once (it said "death restarts the delve"; the README was already right) (#151).
- Rune Delve (Unreal): three Core checks test what the game runs. `RDRules::Regen`, which nothing called, is gone with
  its two checks, and a Regressions stage measures the mage's live regeneration through the GAS effect (12.00 mana in
  1 s); the orc brain test follows a blocked swing's stagger (Recover, then Staggered for all of `StaggerSeconds`,
  the next wind-up only after it) instead of an unreachable wind-up interrupt, and the header says so; the masher's
  low-mana check asserts the ward it casts and the bolt it then cannot. Three mutants (double regen, a stagger
  ignored in Recover, a masher that bolts past its ward) pass the old checks and fail the new ones. The bot pair is
  unchanged (#150).
- Rune Delve (Unreal): orcs stand down when the mage falls. The brain gets `bTargetAlive`, and a Hunt or a Windup
  with the mage dead goes to Sleep, so no orc keeps winding up at the body with the red telegraph and the swing sound
  while "You fell" is up; a hunting orc plays walk only while it moves, as the mage does, so it no longer walks in
  place when blocked or waiting. The OrcBrain test and a new Regressions stage (the awake grunt kills the mage, then
  every orc must sleep on its idle clip; old code: a room 1 orc in HUNT on the walk clip) cover it. The bot pair
  totals are unchanged (#149).
- Wavesmith fish_tts.py: a WAV from `say` is saved with its real RIFF and data sizes. Fish Audio streams WAVs, so
  both header fields came as placeholders near 4 GB (`0xFFFFFF24`, `0xFFFFFF00`) and were saved as received;
  readers that size a buffer from the header misread them. `wavfile.py`'s new `fix_stream_sizes` walks the chunks
  and sets only the two fields (samples unchanged); the `.gen.json` record keeps `sha256` (the file as written) and
  `sha256_as_received`. MP3 and Opus are saved as received (#178).
- Graveyard Shift (Unity): the HUD's bottom-left label shows "(Esc: title screen)" only on a played night; a bot
  night (`--autoplay`), where Esc does nothing, says `(autoplay careful)` (or `lit`, `dark`) instead. The label is
  `Hud.LevelLabel`, kept current like `SeedLabel`, and the new `Smoke_R9` checks both nights (old code: the hint on
  the bot night) (#179).
- Dotwork: the skeleton's run, idle, attack and jump clips (and cast and shoot) were rendered live on a test character
  in 4 directions and passed the in-game verify, with no code change. The README's characters (skeleton) row says
  what they look like: side views follow the skeleton, front and back strikes read weakly, a held item can leave the
  hand; hurt and death are still to render (#39).
- Dotwork: `"anticipation"` was rendered live (attack, cast and shoot, with and without it, 4 directions) with no
  code change: the side views show the wind-up, the front and back views barely change. The README says so, and that
  `"holds": true` on a plain skeleton shoot holds the rest frame before the arm comes up (with anticipation the hold
  lands on the drawn-back aim); Godot's verify counted every held frame (#49).
- Dotwork qa pack: no longer stops with a TypeError (exit 2) on a game with a lit TileSet (the lighting lane's normal
  map rows give `tile_px` as a `[w, h]` list; only art rows vote on the tile size now), and no longer reports store
  art, the game icon and the boot splash as accidental upscales (they are scaled up by whole numbers on purpose; 5
  false findings). Found by running the 0.8.1 lanes together on a full test game: store, screens, bdf, diorama, vfx,
  uikit, lighting, the Latin fonts, holds / smear / shaders and `capture` all packed, 231 resources load in `verify`,
  and `qa pack` gives the 13 findings it gave before (#48).
- Dotwork: `"holds"` (and `"smear"`) on a skeleton attack, cast or shoot centre on the skeleton's own strike frame
  (`pose.STRIKE`: mid swing, mid thrust, the shot's recoil) instead of the measured peak, which on a plain shoot is
  the arm coming up, so the aim hold landed on the rest frame. A new render records which control frames
  SpriteKiln's frame select kept (`frame_select` in the clip's meta.json) to place it; older clips assume an even
  loop, and a trim that cuts the strike off keeps the measured peak (#180).
- Dotwork store: without `"focus"`, the lane's own key art renders no longer lose the hero's head in `small_capsule`
  and `library_hero` (the widest sizes keep under half the height, and the centre crop started below where the
  prompt puts the hero's top): each size's default focus moves up just far enough to keep that top edge, so sizes
  whose centre crop kept it are unchanged. Your own `source` art stays centred; the README says to set `"focus"`
  when its subject is off centre (#181).
- Graveyard Shift (Unity): `narrator_intro_1` says "Gather all twelve" (it said "six" on a twelve-soul night): one
  Fish Audio take with the same free model and voice, normalized to the narrator's -3 dBFS peak like the other two
  re-voiced lines (-17.9 LUFS, the old take -17.7), and a local transcriber hears the new line word for word. The
  ASSET_LOG row, licence evidence and HOW_IT_WAS_MADE say so. A new EditMode test checks every narrator line names
  `LevelCheck.SoulCount` (old take: "six" reported), and the evidence check also covers a sidecar's hash as received.
  Checked by ear on 2026-11-04 (#138).
- `pixellab.py`: `animate` asks for transparent frames when its first frame has transparency (PixelLab filled them
  with flat grey), and a v3 `character` refuses `--directions 4` and `--shading` before sending (PixelLab answered
  422 to both after the request went out). Found making Ghost Lantern's sprites; `image`, a v3 `character`,
  `animate` and `animate-character --mode skeleton-v3` are now run live (#17).
- `pixellab.py`: `ui`, `object` and `prop` print and record what they cost. Their POST answers `"usage": null`
  and the finished resource has no usage, so a live 192 px UI panel (10 generations) said nothing and saved
  `"cost": ""`; the cost now comes from the background job the POST names (found in a live run, 2026-11-04).
- `pixellab.py`: an `object` that comes back as several candidates (1 direction, `--size` 170 or less: a live 64 px
  crate gave 16) saves them all as `candidate_NN.png` and exits 0. It exited 2 and saved nothing, though the
  candidates were already paid for (10 generations); `object -h` says how many candidates each size gives.
- `pixellab.py`: `fix --op unzoom` keeps a sprite's transparency. PixelLab answers opaque (a live 32 px crate came
  back with near-white corners), so each output pixel now takes the most common alpha of its source block.
  `fix --op correct` prints the colour count before and after and, when it went up (10 in, 235 out live), the
  `fix --op reduce-colors --colors N` line that brings it back. Standard library only, through `image_diff.py` (#184).
- `doctor.py` (web): warns when a game's src/shell/app.ts is present but its src/main.ts never reaches it through
  its imports, naming `/game-shell` (or deleting `src/shell/`). Gatekeeper (web) carried the whole shell unused
  since the 0.8.0 sync and nothing noticed; a scene that imports the shell but is never loaded does not count (#182).
- Gatekeeper (web): the kit's shell is wired in (title, menus, settings, pause, credits; `smoke --drive` works).
  "Play" shows the start panel and the AI guard loads from there as before; `?autoplay` skips the shell, so the
  README's scenario and real-model commands are unchanged. Key presses in the chat box stay out of the shell's
  key bindings (W, A, S, D, Space and Enter); Escape pauses. Quit to title ends the conversation, Play again
  starts a new one with the guard already loaded (#182).
- Dotwork hand polish: a character whose clips have different frame sizes (two packs wrote it) can be polished
  in Aseprite and Pixelorama. Both builds give it one canvas, the widest and the tallest, each clip centred on
  its bottom edge so the feet stand on one line; the re-export crops each clip back to its own size (frames,
  sheets and sheet data), and art drawn outside a clip's box stops it with the frame's name. An untouched round
  trip changes no file and a second build leaves the source alone (Aseprite 1.3.18 live). Effects keep one
  frame size (#82).
- Dotwork README, "Image to 3D": the wrong TRELLIS shapes on pixel art came from blowing the sprites up with
  nearest neighbour first; given at their own 64 px size the barrel and the crate came back the right shape in
  3 of 3 seeds, and the local DINOv2 matches an independent re-implementation of the original network on the
  same weights (measured 2026-11-04 on the 16 GB card). Image to 3D stays out of Dotwork (#50).
- Dotwork aseprite: the palette scan reads pixels with Pillow's `get_flattened_data` instead of `Image.getdata`,
  which warns from Pillow 12 and is removed in Pillow 14; the older Pillow that Python 3.8 installs has no
  `get_flattened_data` and keeps `getdata`. The exam turns a DeprecationWarning from the scan into a failure (#185).
- Dotwork characters: a still pose named like one of the character's actions in a direction that action has a clip
  (the battle set's `cast` beside a `cast` action facing west) no longer replaces the clip with its one still frame;
  with `holds` or `smear` that stopped the export on an IndexError after every render was done. The still ships
  beside the clip as `<pose>_pose_<dir>` (an assumption line says so) and takes its own `clip_fix` entry. Found
  re-rendering the party example's duelist.
- Wavesmith: `loudness normalize` matches a one-shot shorter than 400 ms by its loudest 400 ms (momentary loudness,
  padded with silence; new `max_momentary()`, which `sets make` now shares) instead of pushing its true peak to the
  ceiling. With `--bus sfx` a 0.2 s blip landed about 25 LU over its bus while a longer effect sat at -30 LUFS: a
  level jump in every mix, seen in the Wavesmith showcase's whole-mix check. A UI sound from `sets ui` normalized to
  `--bus ui` now gets +0.0 dB (was about +15). `conventions` and docs/resources/audio.md say so.
- Dotwork characters: the turned-around check (`qa.turned_around`) runs now. A side or diagonal clip that faces its
  twin's way from some frame on, frame 0 included, gets a QA note naming the clip, the frame and its file, with the
  audition command and the `clip_fix` seed that retakes it (the rendered clip, `attack_e` for a mirrored
  `attack_w`); it replaces the generic "possible turn-around" note, which skipped frame 0. A rapier held back in a
  wind-up is not a turn: the exam checks a real one from the showcase duelist (#186).
- Dotwork characters: the smear no longer drags the coat and boots on a lunge. A frame where the body made most of
  the change (half or more of the moved pixels in its thick mass, a step or a lunge) is not smeared, with a QA note
  saying so; otherwise the body's mass and the feet are left out, the part is one piece and where it was is the
  nearest piece that left, so a boot that stepped elsewhere no longer bends the motion across the body. On the
  showcase duelist's real frames the west attack takes that left a checker trail (seeds 4244 and 4246) and the west
  cast are now skipped, the east cast smears the hand only, and a blade swing still smears (#187).
- Dotwork characters: a symmetric character's west clip ships as the exact mirror of its east clip, with the same
  holds. Odd-width frames were centred rounding left in both views, so a west frame sat 1 px off its twin and the
  peak measure could hold another frame: the showcase dwarf's two-smash attack held frames 0 and 2 east but 4 and 6
  west. A mirrored view now rounds the other way.

## 0.8.2 (2026-11-01): fixes from a fresh review of 0.8.1
A Sonnet review of the 0.8.1 release found these; each fix has a test. Also #64 (Aseprite rebuilds kept hand polish).
- Dotwork hand polish: a frame or clip added in the editor takes only its sibling's provenance (models, workflow,
  routes, blend) in the manifest, never its holds, checks or prompt.
- Dotwork pixelorama: a project's size is checked from its data.json before any image is read (frames held, cels
  unpacked, layers, tags); blending large canvases uses bounded memory.
- Dotwork hand polish: a tag holds at most 100 frames in both editors (Aseprite's 101st frame became a bogus
  animation); an untagged character export says so.
- Dotwork pixelorama: `build --overwrite` keeps the replaced file as `<name>.pxo.bak`, which the game's `.gitignore`
  now ignores (it would not go through LFS).
- Dotwork aseprite: building again keeps a `.aseprite` that differs from the game's frames (it may hold hand
  polish); `--overwrite` replaces it and keeps the old file as `<name>.aseprite.bak`, which games ignore; a source
  that still shows the game's frames is left untouched (#64).
- Dotwork aseprite: a source is indexed only when that loses nothing (at most 255 opaque colours, no partly clear
  pixels); portraits and other many-colour images stay RGB, so an untouched round trip no longer changes them.
- Wavesmith fixes from the 0.8.1 review: the OGG Vorbis decoder refuses files that ask for far more than real Vorbis
  does (codebook and output limits; a malformed file is a clean error, never a traceback); no tool writes WAV bytes
  under another format's name (loudness normalize and music loop write OGG through ffmpeg); sound_sets out_dir stays
  inside the project; the LÖVE and web music players undo a change asked back before its switch, as Godot's does;
  loudness measures a WAV as it reads it (a 30-minute capture in under 40 MB); WebVTT export escapes markup; ffmpeg
  reads local files only; the validators name values of the wrong type instead of crashing; audio.yml runs Python
  3.10 and 3.13.
- README: nine engines, eight tested against their real toolchains (the intro still said eight and seven).

## 0.8.1 (2026-11-01): Wavesmith, Pixelorama, audio in every engine, and Dotwork's store, UI, VFX and lighting lanes
Released as 0.8.1 at the user's call: by the kit's own rule (SOP-06) new features are a MINOR bump, and 0.9.0 is kept
for the next release.
- Wavesmith: the audio tools are one package, `tools/audio/wavesmith/`, with one front door (`wavesmith.py list`,
  `check`, `test`, and a subcommand per tool: loudness, events, sets, dialogue, music, babble, voice, sfx, synth,
  chiptune, eleven, fish, wav). Every module keeps its name and still runs on its own; docs, CI, the engines'
  headers and the golden files point at the new paths.
- Upgrading from 0.8.0: `new_game.py --upgrade` adds `tools/audio/wavesmith/` but never deletes kit files, so the
  old copies stay in the game's tools/audio/ folder (they still run, but go stale). Delete these files directly in
  tools/audio/ (not in wavesmith/): babble.py, chiptune.py, eleven_audio.py, fish_tts.py, flacfile.py, local_sfx.py,
  local_tts.py, local_tts_worker.py, sfx_synth.py, wavfile.py and their exams (test_babble.py, test_chiptune.py,
  test_eleven_audio.py, test_fish_tts.py, test_flacfile.py, test_local_sfx.py, test_local_tts.py, test_sfx_synth.py,
  test_wavfile.py). The 0.7.x releases shipped only sfx_synth.py, chiptune.py, wavfile.py, eleven_audio.py,
  fish_tts.py and their exams. Keep tools/audio/wavesmith/.
- Dotwork: new `uikit` lane: one Godot Theme (`assets/ui/theme_<name>.tres`) for every settings / pause menu control
  in every state (buttons, check boxes, switches, sliders, option buttons, popup menus, scroll bars, tabs, line edits,
  spin boxes, tooltips, item lists, progress bars, labels, panels, separators), drawn in code in the window styles.
- Dotwork: focus is a ring in its own colour drawn outside each control, never a brighter hover; tests compare focus
  and hover pixel by pixel for every focusable control (Godot's sliders draw one highlight for both: a known limit).
- Dotwork: input prompt glyphs for the kit's shell (`assets/ui/glyphs/<glyph_name>.png`, 16 px tall, plus
  a glyphs.json of widths): keycaps labelled from the glyph font, mouse buttons, and generic gamepad shapes for the xbox_, ps_
  and pad_ names, with no maker logos; `keys` adds any rebound key.
- Dotwork: `uikit` also ships a pointer and a pointing-hand cursor, a preview scene with every control, and a
  labelled review sheet of every state and glyph.
- Dotwork: verify checks each UI kit Theme's items inside Godot and walks the preview's focus chain with ui_down /
  ui_up (`UIKIT_FOCUS_RESULT PASS`); the exam (`core/tools/art/dotwork/tests/test_dotwork.py`) also runs the lane exams in `EXTRA_EXAMS`.
- Dotwork: new `store` lane: key art and every Steam capsule and library size (whole-number scaling only, the logo on
  the calmest spot), a logo wordmark from a glyph font, achievement icons with greyed twins, the game icon and a
  multi-size `.ico`, Steam's app and shortcut icons, and a boot splash; `"apply": true` sets the icon and splash in
  `project.godot`, and verify loads them. The Dotwork README's "Store art (Steam sizes)" table is checked against the
  Steamworks pages read on 2026-11-01.
- Dotwork: new `screens` lane: title, loading and credits screens as Godot scenes over a backdrop; they use the UI kit
  theme when the game has one.
- Dotwork: new `capture` command: any scene recorded with Godot's Movie Maker at a fixed frame rate (trailer frames),
  with a contact strip and an optional GIF. The Godot overlay's capture.gd stays the tool for real-time bursts.
- Dotwork: new `bdf` lane: a downloaded bitmap font (such as an OFL CJK pixel font) cut down to the characters the
  game's strings use, with a coverage check that names each missing character and where it is used; the licence
  travels with the font. No font ships in the kit.
- Dotwork: new `diorama` lane (2.5D): tiles as 3D floors and blocks, props and characters as pixel-crisp billboards,
  lit, under a tilted camera.
- Dotwork: the exam checks that no shipped file holds an unresolved placeholder token or an em dash.
- Dotwork: new `vfx` lane drawn in code: arrow, energy bolt and orb projectiles with a looping flight animation and a
  trail that fades along its length (sprite strip, Line2D with a stepped ramp gradient, or world-space
  GPUParticles2D); ground puffs (dust, footstep, landing ring), a pickup twinkle and a level-up burst, as one-shots
  that end on an empty frame; particle kinds (dust, sparkle, ember) as a GPUParticles2D scene with a mask texture, a
  ParticleProcessMaterial stepping through the colour ramp, and a JSON of the emitter for other engines.
- Dotwork: one-shot particle scenes arm themselves with a small Start AnimationPlayer, because Godot 4.7.2 stops a
  one-shot GPUParticles2D that starts emitting from the scene file without bursting or sending `finished`; verify
  checks every particle emitter and Line2D trail it instantiates. An example spec and an exam come with the lane.
- Dotwork animation polish, all opt-in (an old spec gives byte-identical files): frame holds (`"holds"`: per-frame
  SpriteFrames durations, by default a held wind-up and a hit-stop around the peak frame of attack, cast and shoot; the
  sheet JSON carries them for other engines), smear frames (`"smear"`: the peak-motion frame redrawn with the moving
  part dragged back, in its own colours), anticipation for skeleton attacks (`"anticipation"`: lean away, sink, draw
  back, then strike), and `"shaders": true` for a damage flash and a pixel-grid dissolve material. Palette variants
  inherit holds and smear.
- Dotwork: verify compiles every ShaderMaterial it loads and counts held SpriteFrames frames. The exam ran its last
  extra lane exam twice, so its printed totals since the uikit lane were one class too high; it counts each test once.
- Dotwork: new `lighting` lane (no model): normal maps for every SpriteFrames frame with a lit SpriteFrames copy,
  lit TileSet copies whose per-tile normals stay seamless, prop normal maps with a LightOccluder2D traced from the
  alpha, and a lit demo scene (CanvasModulate, PointLight2D with shadows). Normal maps are OpenGL style (green up), as
  Godot 4 expects; verify checks that each normal map decodes to unit normals facing the camera, that occluders have
  a polygon and that lights have a texture. Lanes listed as late (lighting) run after every other lane, so one pack
  can light what it just made.
- Dotwork: `dotwork.py qa pack [--json OUT] [--lineup OUT.png]`, a read-only style check across a game's whole Dotwork
  asset set from its manifests: pixel scale, each lane's palette lock, outline colour and thickness, light side, figure
  height in tiles, contrast on the ground tiles, and colour-blind separation (Machado 2009) of gauge fills, status
  marks, button states and palette swaps; `--lineup` draws every character and prop at game scale on a ground tile
  for a by-eye check. It catches a planted 2x upscale, an off-palette prop, a mirrored prop and a red / green gauge
  pair, and found 9 real problems (no false alarms) in a 1,435-file test game.
- Dotwork: Latin glyph fonts (`tools/art/dotwork/glyphs/dialogue_latin.txt`: all of Latin-1 Supplement and Latin
  Extended-A, curly quotes, en dash, ellipsis, euro; `tools/art/dotwork/glyphs/title_brass_latin.txt`: every accented
  capital plus title punctuation). French, Italian, German, Spanish, Portuguese, Polish, Czech, Hungarian and Turkish
  render; ASCII glyphs and old fonts are unchanged.
- Dotwork: font coverage check (`dotwork.py fonts-check --font F --strings FILE`, or `"check"` on a font entry) lists
  every character the game's strings (JSON, CSV, PO, text) use that the font lacks, with language and string id, and
  exits 1. Glyph files can reserve accent rows and name invisible characters (`char U+00A0`).
- Dotwork: built-in colours are colour-blind safe: the exp and limit gauge fills and the burn status mark are darker,
  so no two built-in gauges or status marks collapse for a player with protanopia, deuteranopia or tritanopia (checked
  as drawn on the palette). The save-point glow and chimney smoke of animated props stay on the palette, as the README
  always said. **Old specs get the new exp, limit and burn colours and the snapped frames.** A new exam keeps both.
- Dotwork README "Image to 3D (tested, not part of Dotwork)" and a BRIEFS.md note: TRELLIS was audited and run on a
  16 GB card (it needed changes to load offline and on that GPU, and its shapes on pixel art were wrong), TRELLIS.2
  needs 24 GB, and Hunyuan3D 2.0's licence excludes the EU, UK and South Korea, so no image-to-3D model is
  recommended; the 2.5D path is the `diorama` lane. E107-E112 join EVIDENCE.md (E112, the trial itself, graded X).
- Dotwork: `dotwork.py pixelorama` and `pixelorama --reexport`, the hand-polish round trip with Pixelorama `.pxo` files.
  Dotwork reads and writes them itself (no install needed), writing `pxo_version` 7 (Pixelorama 1.2.x) and reading
  7 and 8. Each project has one tag per animation, frames timed by their holds and the asset's own colours as the
  palette. Visible pixel layers and groups are composited; any layer feature that cannot be reproduced exactly stops
  the re-export with its name. A `.pxo` that may hold polish is never overwritten without `--overwrite`.
- Dotwork: the Aseprite and Pixelorama round trips share `handpolish.py`, which fixes both:
  - frames are timed by their holds, and holds survive the trip (they were dropped);
  - no crash on games with status-mark, spell or talking-portrait sheets;
  - spells and VFX are no longer grouped into one effect and renamed;
  - each effect keeps its own speed, and SpriteFrames keep their animation order;
  - a file listed by two packs counts once;
  - only what changed is written: an untouched frame keeps its file byte for byte, an untouched round trip rewrites
    no manifest, and a changed file keeps its row's provenance (a frame drawn in code never gains a model list);
  - a tag name that could leave the export folder is refused.
- Kit: `.pxo` joins `.aseprite` in `.gitattributes` (LFS), doctor's media list and publish_check's; SOP-16 and
  `docs/resources/art.md` name the Pixelorama round trip.
- `tools/audio/wavesmith/loudness.py`: measure integrated loudness (ITU-R BS.1770-5), loudness range (EBU Tech 3342) and true
  peak; check a whole-game capture against Sony's ASWG-R001 targets (home -24, portable -18 LKFS, true peak -1 dBTP,
  at least 30 minutes); normalize single assets to labeled house levels with a true-peak ceiling. No installs.
  Checked against pyloudnorm and ffmpeg on 815 files; its true peak reads clipped audio up to 0.84 dB closer to an
  ideal reconstruction than the standard's 4x example filter.
- SOP-19 and `/dotwork` point to the `uikit` lane for prompt glyphs and a menu Theme with a visible focus ring.
- Audio events: describe each sound once in data/audio_events.json (takes, pitch and volume ranges, no-repeat or
  shuffle picks, voice caps with stealing, cooldowns, buses, dialogue ducking). An audio director in Godot, LÖVE,
  web, web-3d and Unity makes the same decisions from the same seed (golden vectors `data/golden/audio.json`, owned
  by `tools/audio/wavesmith/audio_events.py vectors --write / --check`, which CI also runs); the web overlay plays them
  through Web Audio. audio_events.py validates and audits the file (repetition, loudness spread between takes,
  missing captions). Only the web overlay wires the director to a player so far.
- Dialogue: `tools/audio/wavesmith/dialogue.py` builds a game's dialogue source and its voice files into the dialogue.built.json
  the shells read (per-character typewriter reveal, exact from babble timelines and estimated from other voice files),
  subtitle cues that follow Xbox Accessibility Guideline 104 and the Netflix timed text guides (40 characters, two
  lines, 5/6 s to 7 s, 20 characters a second, 17 for children), SFX captions from audio_events.json, lint, and SRT /
  WebVTT export with the speaker named on every change. The built format gains two optional fields (`max_cue_s`,
  `directional` on captions); the shells' readers load it unchanged.
- Sound sets: `tools/audio/wavesmith/sound_sets.py` makes and checks whole families of sounds (footsteps per surface and
  ambience beds through local_sfx, takes leveled to their bus; a twelve-sound UI set made from code, ship-safe) and
  fails a set on missing or extra takes, double attacks in one-shots, takes more than 3 LU apart, loops without a
  clean loop point, or files with no licence record (`check --ship` also fails Stable Audio output until its licence
  is cleared); it writes their audio_events.json entries.
- Audio accessibility: `loudness.py mono` reports what each stereo file loses when the mono switch sums it
  (0.5 * (L + R), the Web Audio rule) and fails out-of-phase content, block by block (SOP-20 step 5 names it); on web
  and web-3d the settings volume sliders now reach the audio director's buses (`AudioPlayer.applySettings`, never
  twice down one branch), and captions marked directional get an arrow on the side an off-screen sound comes from
  (XAG 104). Godot, Unity and LÖVE have the director but not this player layer yet.
- Dialogue: `dialogue.py lint --pseudo` checks every line through the kit's pseudo-locale (40 % longer, the same
  `pseudo()` as the golden vectors) over the same voice timing, and warns where a translated subtitle would be too
  fast to read, too long for a cue, or a caption would not fit one line.
- Adaptive music: a game's music.json describes tracks on a BPM and bar grid (intro plus loop, synced stems),
  stingers and a transition map (now, next beat, bar, phrase or loop end, fades, synced entry); `tools/audio/wavesmith/music.py`
  cuts bar-aligned loops, validates stems and loop points, plans transitions, estimates tempo and owns the golden
  vectors `data/golden/music.json` (CI checks them); the web music player changes track on the exact planned sample.
  For music made locally, ACE-Step 1.5 is the recommended model (tempo within 2 % in 17 of 18 takes, against 15 and
  11 for the two Stable Audio models, and its output may ship; MIT, run through ComfyUI's own template, no Wavesmith
  subcommand yet); Stable Audio output stays out of anything that ships unless its licence is cleared. Sound sets keep one-shots with the right number
  of attacks first.
- Voice: `local_tts.py` speaks the ten languages its model lists (`--language` is checked before the model loads)
  and stops a take that never ends (a per-line cap at about twice a natural reading; the take is not kept and the run
  says which line to voice again). Measured in five languages with Whisper and a speaker model: German, Spanish and
  French are usable after a listen, Japanese needs a native listener.
- Audio in every code engine but Unreal: Wavesmith's new `access` subcommand owns `data/golden/access.json` (the
  volume-slider to bus mapping and the caption arrows; CI checks it). Godot, LÖVE, Unity, Bevy and C++/SDL2 get the
  music director and the access logic beside the audio director, each tested against all three golden files; Godot
  and LÖVE get music players, slider-to-bus volumes and caption arrows in their subtitle shells, and Unity gets
  `AudioEventPlayer` and a `MusicPlayer` scheduled on the sample (compiled and tested, not yet run in Play mode). A new
  audio case covers a stolen voice that stops ducking when its replacement ends.
- Translations and bark lines drafted by a local language model are drafts (docs/resources/audio.md, SOP-19 step 6):
  the placeholders must survive exactly, back-translation flags drift, and a person reviews before anything ships.
  No language-model drafting code ships in the kit.
- Audio logic in every engine: Unreal's GameKitShell plugin (GameKitAudioDirector.h, GameKitMusicDirector.h,
  GameKitAudioAccess.h; 13 new golden tests, 68 GameKit tests in all) and RPG Maker MZ (GameAudio.js, tested in
  Node; verify in RPG Maker MZ) now follow the same audio, music and access golden vectors as the other seven
  engines. RPG Maker MZ's `setup` puts a newly added kit plugin before the game's plugins that load after it.
- Every audio format: Wavesmith reads WAV, FLAC and OGG Vorbis with nothing installed (new oggvorbis.py, a
  pure-Python Vorbis decoder within 5e-7 of ffmpeg's on 47 files) and MP3, Opus or AAC through ffmpeg when it is
  installed (optional, never shipped); a new `formats` subcommand (check, info, convert, OGG output with loop
  points); loudness, events audit, dialogue and music read them all.
- Every OS: a new audio.yml workflow (in every game, and a copy for the kit repository itself) runs every Wavesmith
  exam and the golden checks on Linux, Windows and macOS (Python 3.9 and 3.12) when the audio tools change; all 18
  exams pass on Linux (Ubuntu 26.04, Python 3.14) in a scaffolded game. macOS is untested here, and the workflow has
  not run on GitHub yet.
- Every backend: `voice --device auto|cuda|mps|cpu` (auto: NVIDIA, then Apple Metal, then the CPU; a CPU take ran
  at about 20x real time and transcribed exactly); docs/resources/audio.md gains "Hardware: what runs where"
  (everything but voice and sfx needs only Python 3.8+). Apple Metal and AMD are untested.
- SOP-04 measures loudness instead of normalizing peaks, pointing at `tools/audio/wavesmith/loudness.py`. EVIDENCE.md: the 0.8.0
  rows (E69-E92) had one cell more than the table's header, so GitHub showed each finding in the Grade column; every
  row has seven cells again. New rows E100-E106 (Steam store pages, a CJK pixel font) and E120-E125 (loudness).
- `scripts/sync_examples.py`: a run with nothing to sync leaves the examples untouched (it added a history entry to
  every example on each run). The kit's em dash check reads tracked and new files only.

## 0.8.0 (2026-11-01): the polish release (LÖVE, game feel, the shell, accessibility, shipping)
- **New engine: LÖVE (`love2d`, LÖVE 11.5, Lua).** `check` compiles every .lua with LÖVE's own LuaJIT in a separate
  checker, `test` runs the project's own runner inside LÖVE with no window, `smoke` boots a small off-screen window (or
  `--headless`) with `--screenshot` / `--record` through a canvas, `build` packages a .love and a fused Windows exe.
  LÖVE's error screen waits for a key even without a window, so conf.lua's error handler makes every automated run exit
  1 instead of hanging: proven with planted syntax errors in main.lua, conf.lua and a module, and a runtime error.
- **Game feel for every code engine** (`SOP-18`, `/game-feel`): screen shake (trauma), hitstop, 14 easing curves, a
  follow camera with deadzone and look-ahead that is the same at any frame rate, input buffer, coyote time, spring and
  squash, and a flash limiter. One reference, `tools/golden_vectors.py`, writes `data/golden/juice.json` and
  `shell.json`; every port's tests check all 41 cases: Godot 48 GUT tests, LÖVE 94, web 86, web-3d 89, Unity 95 EditMode
  tests, Unreal 55 automation tests (the GameKitShell plugin, off by default), Bevy 55, C++/SDL2 26 with 598 assertions.
- **The shell** (`SOP-19`, `/game-shell`): title, menus, settings, pause, credits and loading screens; settings with
  validation that keeps unknown keys; versioned saves with migrations, atomic writes and a backup; actions with
  rebinding (swap within a group) and button prompts that follow the device; string tables, plurals and a pseudo-locale;
  log files, crash files and a bug-report key; telemetry that writes nothing until the player agrees. Godot, LÖVE and web
  ship the screens; Unity, Unreal, Bevy and C++/SDL2 ship the tested logic; RPG Maker MZ maps the rules onto its own
  screens. New smoke scenarios: `--drive menus | crash | pseudo | pseudo-plant | show:<screen>`, `--data-dir`, `--locale`,
  `--compare`. The flash limiter is always on; the `flash_limit` setting only softens flashes.
- **Accessibility** (`SOP-20`): the baseline every kit game ships (subtitles and captions, text size and 200 % scaling,
  no colour-only information, remapping and no required holds, shake and flash safety, difficulty), from the Game
  Accessibility Guidelines, the Xbox Accessibility Guidelines 101, 104, 117 and 118 and WCAG 2.3.1, all read this release.
- **Shipping** (`SOP-21`, `docs/LEGAL.md`): Steam store assets, SteamPipe uploads, achievements, Steam Cloud, demos,
  Playtest, Next Fest, Steam Deck review, butler for itch.io, SignTool, and a legal fill-in checklist; from Valve's,
  itch.io's and Microsoft's docs read this release. `tools/credits.py` builds CREDITS.md and THIRD_PARTY_LICENSES.md from
  the asset log and refuses assets with no license or a PLACEHOLDER; `.github/workflows/ci.yml` runs `check` and `test`
  per engine on a hosted runner (not yet run on GitHub: verify on your first push).
- **Balancing and marketing** (`SOP-22`, `SOP-23`), a bug severity scale and release bar (`SOP-02`), pacing for
  hand-made levels (`SOP-17`), lighting and post-processing (`SOP-16`, `SOP-11`), and "After launch" (hotfixes, patch
  notes, mods) in `SOP-06`; the release check gains the accessibility baseline and the credits check.
- **`tools/image_diff.py`:** visual regression for `smoke --compare` (a standard-library PNG reader).
- **Evidence:** E69 to E92 and findings F33 to F39.
- **Examples:** all ten carry the new files and pass check, test and smoke; the Godot examples keep their own window
  and controls (the Shell applies display and input only after the player saves settings or the kit's front end
  starts). Follow-ups are issues #40 to #47 (`KNOWN_ISSUES.md`).
- **Local audio tools** (no account, no per-use cost):
  - `tools/audio/babble.py`: gibberish character voices for speech bubbles, made from code (no model). Five voices,
    `--variants` takes, `--lines` for a whole script, and a `.timeline.json` per line with the time each character
    should appear, so a typewriter reveal stays in step with the voice.
  - `tools/audio/local_sfx.py`: sound effects and seamless ambience loops from a text prompt on your own GPU (Stable
    Audio 3 through a local ComfyUI). It renders several takes, trims and normalizes them, ranks them on technical
    checks and keeps the best few for you to pick by ear; a `.gen.json` per file records model, seed, prompt and
    license.
  - `tools/audio/local_tts.py`: character voices on your own GPU with Qwen3-TTS (Apache-2.0): design a voice from a
    description once, then voice speech bubbles and barks in it; `--pitch` / `--ring-hz` for giants, creatures and
    golems. The model runs in a separate Python environment (`LOCAL_TTS_PYTHON`), so the kit stays standard library
    only; `check` names what is missing.
  - `tools/audio/flacfile.py`: FLAC to samples or WAV with the standard library (16/24-bit, mono/stereo), checked
    against the file's MD5.
  - `tools/art/comfy_local.py` saves audio from Save Audio nodes and strips FLAC tags (where ComfyUI writes the prompt
    and workflow, local paths included), as it already did for PNG text chunks.

## 0.7.6 (2026-10-31): Dotwork rehearsal fixes
- **Fix: Dotwork's clip drift check stopped clean clips.** A clip whose colours were a shade off the sprite's (a
  shirt or hands across a colour-bin edge) counted as drift, which stopped the townsfolk and party-member examples in
  a fresh game. Such a pixel now counts as the sprite's own when it is within 16 RGB of one of its colours; real drift
  (an object another view has) is still caught.
- **Dotwork:** a possible turn-around note names the fix (`"skeleton": [action]`) when the action has a skeleton.
- **Dotwork: animated props take `"slab": "remove"`,** like props: a flat ground slab baked into the base render is
  stripped before anything is animated from it. Only entries with the flag re-render.
- **Dotwork README:** four-legged mounts are not walking characters yet (use a two-legged mount, or a `vehicles` entry
  that turns but does not walk).
- **Lospec palettes in the art resources and the Dotwork README:** the download formats, how a `.hex` palette plugs
  into Dotwork as is (checked with `clean`: every pixel on the palette), and crediting the palette's creator (palette
  pages show no license; the old line said "free to use").
- **SOP-12:** what a local model did as a second opinion (tested, not shipped): 2 or 3 of 5 planted bugs per run
  against 5 of 5 for a Claude subagent, about 5 minutes a review, the `llama-server` settings that read prompts 3.5 times
  faster, and the rules if you try it anyway. Kimi stays the second opinion.

## 0.7.5 (2026-10-31): Dotwork jumps, four more motions, spells drawn in code
- **Fix: Dotwork skeleton jumps stayed on the ground.** Every frame was pinned back to the feet line twice, so front
  and back jumps shipped as standing frames. Airborne actions (jump by default) now keep the clip's height; a
  platformer, whose physics already lifts the body, turns it off per action (`airborne: false`). Only jump clips
  re-render after an upgrade.
- **Dotwork: skeleton motions for hurt, cast, shoot and death** (death is a one-shot that ends lying down). The
  existing walk, run, idle, attack and jump skeletons are unchanged, so no cached clip re-renders.
- **Dotwork: new `spells` lane,** spells drawn in code for additive blending: fire, ice, bolt, heal, wind, burst
  (one-shots), orb and aura (loops). Exact, repeatable, no GPU.
- **Dotwork: battle backgrounds can drift two cloud layers** (`scroll`), drawn in the picture's own sky colours.
- **Dotwork: animated props take any motion** (`"kind": "clip"`, Wan 2.2), one-shot or loop, with the ground shadow
  removed and the palette locked.
- **Dotwork: isometric terrain transitions** between two materials, painted with Godot's terrain tool and checked by
  `verify` (every shared corner must agree).
- **Fix: `comfy_local.py` on a cancelled job.** A job stopped with Cancel or `/interrupt` now says "interrupted at
  node N (type)" instead of "failed: no message", and a job taken off ComfyUI's queue before it ran stops the wait
  within about 10 s instead of waiting out `--wait`.

## 0.7.4 (2026-10-31): Gatekeeper starts again, in-game AI download
- **Fix: Gatekeeper (Godot) could not be started.** The start panel's text grew past the 640x360 window and pushed
  both buttons off the bottom, so the game sat on its opening message with nothing to click. Panels now pin to the
  bottom edge and grow upward, the start text and buttons use a smaller font, and the wall notice no longer overflows.
- **Gatekeeper: "Download the AI guard" on the start screen.** Run from the Godot project on Windows without the
  model, the game offers to run `examples/gatekeeper-godot/tools/setup_ai.py` in the background (the scripted guard stays playable) and says
  when to run the game again.
- **Gatekeeper: the model load times out.** Loading plus the warm-up reply had no limit, so a stuck load hung the
  start screen; after `LOAD_TIMEOUT_S` (90 s) the scripted guard takes over, and a late finish is ignored.
- **Docs: Godot version wording.** The Godot ENGINE.md template and the `make-a-game` install step recommended
  "4.3 or newer", which read as the target. They now say to use the latest 4.x stable (tested on 4.7.2) and call
  4.3 the floor. Gatekeeper's ENGINE.md had the template's placeholder unfilled; it now says 4.7.2.

## 0.7.3 (2026-10-30): Python 3.8 and 3.9 work again
- **Fix: seven tools crashed on Python 3.8 and 3.9** (the kit's floor is 3.8). `Path.write_text(newline=)` only
  exists from 3.10, so `--log` and `--out` in `fetch_asset.py`, `comfy_local.py`, `pixellab.py`, `eleven_audio.py`,
  `fish_tts.py`, `sfx_synth.py` and `second_opinion.py` raised a TypeError; they now write the same bytes with
  `write_bytes`. On Windows before 3.10, `Path.resolve()` leaves a relative path that does not exist yet relative,
  so the 0.7.0 "inside the project" checks refused valid outputs; those paths are made absolute first.
  `fetch_asset.py`'s zip containment check is now lexical, so a name Windows cannot store is refused cleanly on 3.8
  instead of crashing. All 13 standard-library exams pass on 3.8.20, 3.9.25 and 3.14.7; every engine scaffolds and
  runs `dev.py -h`, doctor and the session hook on 3.8. Reported by a review of the coming local second-opinion work.
- **Fix: `tools/check_links.py`** stripped a leading `.` from folder names (`lstrip("./")`), so references into
  generated folders like `.godot/` were checked instead of skipped. Test added.
- Maintainer note in `CLAUDE.md`: run the exams on the oldest supported Python before a release.
- All 10 examples synced.

## 0.7.2 (2026-10-30): neutral wording
- Help examples and test fixtures in `tools/art/pixellab.py` use neutral sample subjects; a Dotwork title default is
  now "MY GAME".
- The game `CLAUDE.md` template words its comment rule for any reader; the examples' write-ups, handoffs and the
  local pixel-art write-up describe tests and services without account, device or schedule details.
- `scripts/codename.py`: one colour word changed.
- Known issues: a cancelled ComfyUI job reads as "failed: no message" in Dotwork (#38); skeleton clips other than
  walk are not rendered live yet (#39).
- All 10 examples synced.

## 0.7.1 (2026-10-30): Dotwork lanes, audit fixes and neutral wording
- **Dotwork vehicles:** the 8-direction set is labelled from the views themselves (a mirror-pair test picks the
  source's facing), so each file shows its direction (fixes #23). The model's in-between views stay approximate.
- **Palette swaps** (`recolor.py`): an enemy entry `{"recolor_of": "guard_hound", "hue": 150}` makes a recoloured
  copy with no render, keeping its ramps and the palette; a `recolor` command does the same for any PNGs.
- **`clean` command** (`pxclean.py`): finds the pixel grid of upscaled or generated pixel art, keys the background,
  snaps to the palette and drops stray pixels, with no model; refuses when the two axes disagree.
- **Widgets lane:** HP/MP-style gauges (TextureProgressBar), buttons in five states and a panel, one Godot Theme per
  window style, drawn in code; Dotwork's `ui` example gains a HUD.
- **Transitions and weather lanes:** fades, iris, wipes, blinds, a battle swirl and a mosaic as rule images played by
  one shader; rain, snow, fog, ash, embers, leaves and sand as seamless scrolling layers (Dotwork's `screen` example).
- **Status lane:** 16 status-effect loops drawn in code (poison, sleep, haste and more), each as frames, a sheet and
  an autoplaying scene (Dotwork's `status` example).
- **Portrait expressions:** `"expressions": true` (or a list, or your own wordings) makes happy, angry, sad, surprised
  and hurt portraits from the neutral one by a palette-locked edit; `face_only` keeps hair, clothes and framing
  identical. A beard that hides the mouth makes a faint expression.
- **Icons:** only the largest size renders and 16 px is reduced from it, so both sizes are one design; a missing size
  fails the run. Props, icons and portraits no longer start ComfyUI when everything is cached.
- **Enemy shadows:** the light-grey baked ground slab is removed and a dark dithered contact shadow is drawn in code as
  a Shadow child of the scene (fixes #28, #26). Props opt in with `"slab": "remove"`; white pockets in props are
  flagged with their box.
- **NPCs lane:** townspeople the cheap way (code-drawn idles, a rotation and three walk clips, about 8 minutes), and
  `variants` that recolour a finished NPC across every frame into new characters with no render, keeping skin tones.
  Palette swaps now keep an animation's near-identical shades together, so a variant's colours match from every side.
- **Dotwork fixes from a Kimi K3.1 Pro pass** over the new lanes: deletes and writes never go through a symlink or
  junction; each pack cleans only the files its own manifest lists (enemy, balloon, battle-background and scene packs
  used to wipe each other's output); spec text is escaped in Godot files; enemies stand with their feet on the shadow;
  a corrected vehicle `rot_order` re-renders; white pockets must be enclosed; font paths, case-only name clashes,
  the expression cache and transition sizes fixed.
- **Character clip cleanup:** leftover white render background is found in the raw frames and removed with its rim,
  skipped on designs that wear white (fixes #22); the ground shadow is removed with one decision per clip, so it no
  longer blinks (fixes #25); a clip that turns toward the camera is trimmed to its good frames, or stops with an
  `audition` command to run, unless `allow_drift` is set (fixes #24).
- **State props from one base:** chest and door states keep only the moving part of each edit (the lid, the door
  panel) and stay pixel-identical elsewhere, so a chest opens instead of changing shape (fixes #27).
- **Ambient props:** new animprops kinds `flame`, `flag`, `smoke`, `spin` and `sway`, animated in code from one render
  so they loop exactly; an unknown kind now stops the run.
- **Neutral wording:** sample text and comments no longer refer to any particular project.
- **Character variants and 8 directions:** an outfit variant edits the south sprite once and builds a whole
  character from it; a hue variant is a palette swap with no render; characters can have 8 directions.
- **Facing fix for every character:** the rotation model sometimes swaps a character's east and west views, so an
  east walk faced west. Dotwork now checks each east/west pair by where the face sits and swaps a wrong pair (cached
  rotations too, re-rendering the clips made from them); back views and faceless designs are flagged, and
  `rot_swap` fixes a pair by hand. A new design also retires an old 8-direction rotation.
- **Genre-neutral prompts:** no built-in template assumes a setting any more; `design.style`, `design.genre` and
  `design.setting` in the spec or config set it. The example specs keep their own subjects.
- **Talking portraits:** talk and blink frames limited to the mouth and eye bands, as a SpriteFrames (idle, talk,
  blink) and a scene.
- **Side-view and isometric tiles:** platformer tilesets (Match Sides terrain, one-way platform caps, a seamless
  parallax background) and 2:1 isometric floors and blocks (`platformer` and `iso` examples).
- **Pose-driven clips:** `"skeleton": ["walk"]` fits a skeleton to the sprite and animates it with Wan 2.2
  Fun-Control, which keeps motion and facing steady. Needs the new optional `pose` model tier (19.3 GB, Apache-2.0,
  pinned with hashes).
- Every example spec is now checked for keys Dotwork does not read (one lane read a key the checker missed).
- Exam 54/54; in a fresh Godot game the `ui`, `screen` and `status` examples load 79 resources.
- **Fixes from a second Kimi K3.1 Pro pass** over the 0.7.0 security fixes: ElevenLabs, Fish Audio and PixelLab check
  that the asset log has a table before a paid call (one without a table failed only after spending), PixelLab refuses
  a folder as a one-file output even with `--overwrite`, the Unreal wrapper stops UnrealBuildTool and its compilers on
  Ctrl+C, and `tools/fetch_asset.py` refuses Windows device names (`CON`, `NUL`, `COM1`) and names ending in a space
  or dot.
- **Neutral wording:** the kit, its docs and the examples speak of "the user" (or "you") and never describe the
  person who maintains the kit. A game's `CLAUDE.md` says `Developer: <author>`; with no author given, the
  scaffolder writes "the user".

## 0.7.0 (2026-10-30): Dotwork, local pixel art on your own GPU
Pixelorama follows as 0.7.x.
- **New tool `tools/art/dotwork/`, Dotwork** (opt-in; Pillow + numpy; Godot first): local pixel art for a whole game from
  a JSON spec, through ComfyUI on 127.0.0.1. Lanes: characters (4 directions; idle, walk, attack, battle and emote poses;
  auditions), props with collision scenes, layered terrain and maps painted from text (buildings, interiors, cliffs,
  animated water, fences, pipes and rails), effects and spells, enemies, battle backgrounds, scenes, icons, portraits,
  8-direction vehicles, state props (chest, door, switch, save point), sprite edits and normal maps, image to pixel
  art, and code-drawn pixel fonts, window skins, balloons and hit effects. Outputs go into `assets/` (SpriteFrames,
  TileSets, scenes, `.fnt` fonts), `assets_src/` (sources, review sheets, `.aseprite` round trip) and a manifest that
  `dotwork.py log` turns into the ASSET_LOG row (`pre-generated` or `no`, with every model's license); `verify` loads
  every asset in the game and runs its smoke. `setup --check` lists the pinned models per tier (15 to 33 GB, all
  Apache-2.0) and never downloads; SpriteKiln (GPL-3.0) is read from the user's own clone at run time, never bundled;
  `style_refs` is empty by default. `--engine none` writes PNGs, sheets and the manifest for other engines. Exam
  `tools/art/dotwork/tests/test_dotwork.py` 34/34 offline; in a freshly made Godot 4.7.2 game the `ui` example packs and verifies. Built
  in a ComfyUI test session and reviewed there (correctness, security, kit readiness, art QA) before the port.
  Fixed while rendering the kit samples: big sprites (a 192 px boss) are no longer cropped by a fixed refine
  canvas, and the default palettes gained 24 sky and backdrop colours (env 136, objects 168; every old colour kept),
  so backdrops no longer collapse into flat bands.
  SOP-16 (a Dotwork tip and "bring 3 or 4 of your own sprites"), `/gen-brief`, `/asset-intake` and `resources/art.md`
  point at it.
- **New skill `/dotwork` (19 skills)** and an art-source question in the interview: for a 2D game, `make-a-game`
  asks where the finished art comes from (drawn in code plus free packs, their own art, a paid AI service such
  as PixelLab, or Dotwork on their own GPU). The answer goes into the GDD's new "Art source" line, picks Godot when
  Dotwork is chosen and no engine is named, and adds a graphics card check (nothing is installed for it during setup).
  `/dotwork` runs the tool end to end: tier check, `setup --check` with a yes per download, a first run with no
  GPU, specs from the GDD and BRIEFS, review of every sheet, the in-game proof and the asset log row.
- **Godot `export_presets.cfg`:** each preset's options section now holds the two template keys, so imports and
  exports no longer log `Cannot get keys from nonexistent section` three times. Windows, Linux and Web exports
  rechecked.
- **From a stranger run-through of 0.7.0** (a fresh agent following only the newcomer docs): doctor points a game
  with Dotwork packs at `dotwork.py log` instead of only `/asset-intake`; the Godot GUT warning names the docs section, and
  that section gives the release URL and the copy step for installing without the editor; SOP-16 says its 108 GB
  list is the first experiment's (Dotwork's tiers: about 78 GB for all three), marks 8-direction objects as made in
  Dotwork, notes that Dotwork renames SpriteKiln's rotation files, and says the first Dotwork run needs `GODOT_BIN` or
  `--engine none`. Dotwork's own findings were fixed in the tool: a wrong folder is refused (exit 2), `setup --check`
  lists every model offline with its save-as name and VRAM/RAM per tier, `log` updates a pack's existing row, a
  first-run box in its README, Python 3.8, and help on every command. A Kimi K3.1 Pro audit then found, among smaller
  items: `audition --promote` discarding every cached render of the character, spec names reaching file paths raw
  (font export names, character actions, directions; one reached a folder delete), and the ground lane crashing with
  `--engine none`; all fixed with tests (exam 34/34).
- **Security and reliability fixes from a Kimi K3.1 Pro audit of the whole kit** (83 findings, each checked against
  the code; 6 were not real, the high and medium ones are fixed with a test or reproduction each; the lows are listed
  in KNOWN_ISSUES):
  - `tools/fetch_asset.py`: a malicious zip could write outside `--to` with `--take`/`--base` (it planted
    `.claude/settings.local.json`, whose hooks Claude Code runs). Unsafe entries (`..`, absolute, drive) refuse the
    whole pack with exit 2 (was 1), every copy and `--to` stay inside the project, `--license-file` must be a pack
    entry, file names Windows cannot store and case-only duplicates are refused, and download URLs are recorded
    without user, password, query or fragment (signed URLs were written into the evidence file and asset log).
  - `tools/publish_check.py` catches snake_case secret names (`client_secret`, `AWS_SECRET_ACCESS_KEY`, GDScript
    `:=`) and scans UTF-16 and UTF-32 files with a BOM (Windows PowerShell 5 writes UTF-16 by default).
  - ElevenLabs, Fish Audio and PixelLab clients send the API key only to a redirect on the same https host and port,
    and refuse a redirect to plain http (ElevenLabs and Fish forwarded the key to any host). PixelLab refuses
    direction names from a response that could leave `--out`. ElevenLabs and Fish check the asset log and output
    paths before spending credits.
  - Bevy `clean --yes` refuses to delete the project or a folder above it (a repo's cargo config file with
    `target-dir = "."` made it delete the game) and deletes only folders cargo marked with `CACHEDIR.TAG`. Bevy
    smoke runs exactly N fixed ticks for `--smoke N` (it ran N-1), with a test.
  - Every engine's `dev.py` kills the whole process tree on a timeout or Ctrl+C and never waits forever for a
    grandchild holding the output pipe; Unreal reports a hung editor as exit 1, not 2.
  - `scripts/new_game.py` fills profile footers in templates with Windows line endings, checks every kit file it
    plans (not only the ones written this run) for unresolved placeholders, compares binary `.gold` copies byte for
    byte, refuses a backtick or `*/` in names and authors (they broke the RPG Maker MZ plugins), and reserves CMake's
    Visual Studio targets and Windows device names. `scripts/sync_examples.py` treats any failed upgrade as a
    failure and copies nothing back for it.
  - 45 text files in the maintainer's checkout had Windows line endings on disk (git stored them as LF); converted.
  - Smaller hardening from the same audit: `tools/issues.py` removes more invisible characters from issue text
    (without flagging ordinary emoji), `tools/publish_check.py` warns about large text files it does not scan and
    catches more home-folder paths, `tools/second_opinion.py` keeps `--files` and `--out` inside the project,
    `tools/fetch_asset.py` records `--page` without a login, the RPG Maker MZ test server stays inside `game/` and
    answers only local host names, and the Unreal wrapper checks project and target names before batch files.
- **`scripts/sync_examples.py`** hashes binary files raw, like the scaffolder. It folded CRLF in every file, and a
  PNG's signature holds one, so binary kit files (Dotwork's palette swatches, the first in the kit) never synced.
- **README "Experimental: local pixel art (ComfyUI)"** and **`workflows/local-pixel-art/README.md`**: the test host
  (RTX 5060 Ti 16 GB, Ryzen 7 5700G, 64 GB RAM, Windows 11), what was installed and on what licenses, benchmarks per
  asset type: characters, props, icons, portraits, UI, isometric pieces, seamless 128 px terrain, corner autotiles, a
  4-direction idle/walk/kick set exported to Godot 4, effects with casting and firing poses, rotate, edit, inpaint,
  normal maps, image to pixel art, scenes and maps; the first night's tests; what has not run yet; and the lessons.
- **New tool `tools/art/comfy_local.py`** (standard library only) drives a ComfyUI server on this machine: `check` (server, GPU, free VRAM; `--workflow` lists missing node types and the models a workflow
  names), `run` (an API-format workflow with `--set NODE.INPUT=VALUE`, `--seed`, `--image NODE=png`, `--dry-run`; saves
  the outputs without ComfyUI's embedded prompt and workflow, never overwrites without `--overwrite`, writes
  `comfy_local.gen.json`, and `--log` adds the ASSET_LOG row with the models to license-check), and `strip` for PNGs
  saved by hand. Talks only to a server on this machine unless `--allow-remote` (ComfyUI has no login). Exam
  `test_comfy_local.py` 25/25 against a stand-in server; `check --workflow` live on ComfyUI 0.43.0 with five
  SpriteKiln workflows; a live `run` is still to do (KNOWN_ISSUES). `/gen-brief` and SOP-16 point at it.
- **`resources/art.md`: a pixel art editor table** (Aseprite, Pixelorama, LibreSprite, Piskel, Lospec Pixel Editor,
  GrafX2, Pyxel Edit, Krita, GIMP): cost and license, platforms, what each is good for; licenses from secondary pages,
  marked (verify) where they disagree. SOP-16's tool table gets a hand-polish row.
- **SOP-16:** the local results table covers every asset type now; new tips: the refine step, a style collage,
  klein's non-linear strength, extending the palette first, stripping ComfyUI's embedded workflow before sharing.
- **Dotwork, a local asset tool, in the write-up:** a JSON spec in; Godot SpriteFrames (4 directions, west
  generated for asymmetric characters), a match-corners TileSet, additive effect scenes, 9-slice NinePatchRect scenes and
  a manifest out, proven by an import into a kit-scaffolded project. GIFs of two characters in 4 directions, effects,
  stills and a painted terrain demo, plus timing and what a review still catches.
- **Aseprite round trip in the write-up:** Dotwork writes one `.aseprite` per character (a tag per animation), effect
  and still, then re-exports after hand polish and re-runs the Godot proof; lossless with no edits (0 of 120 PNGs
  changed). A before/after of a scripted cleanup, the Windows and Lua quirks, and SOP-16's "Hand polish as a round
  trip" tip.
- **Ground layers and maps from text in the write-up:** one TileSet for a stack of layers (base variants, a blob
  overlay layer per terrain, decals, relief, collision, a surface tag), a text-map-to-Godot-scene builder, 38
  reviewed materials, a 112-color environment palette, and a verified 24x15 town square. SOP-16 now prefers blob
  overlays over corner tiles in Godot.
- **Buildings, interiors and fonts in the write-up:** roof and facade structure tiles with trim on every open side,
  fixtures placed from the map, an inn room in three furniture views, and a glyph tool that builds BMFont `.fnt`
  fonts from text bitmaps (a dialogue font and a damage-number font, both loaded by Godot). SOP-16: fonts are not a
  generation job.
- **Battle art in the write-up:** battle backgrounds at an exact 2x, enemies with trapped-white cleanup, a party
  battle set with 7 still poses, code-drawn window skins, title fonts, and a mock battle screen composed from the
  packs. SOP-16: judge a set together on a mock screen before game code.
- **Spells, props, symbols and balloons in the write-up:** a 12-spell effect library, 61 props each with a collision
  scene (a trunk footprint for walk-behind tops), a symbols font mapped to Unicode, and emote balloons. SOP-16: ship
  props as scenes with a footprint.
- **Cliffs, a world map and connectors in the write-up:** plateaus with a cliff-face strip and stairs, a world map
  painted from text, code-drawn fences, pipes and rails, and every blob tile per texture variant so long edges stop
  repeating. All 12 spells now clean. SOP-16: variants need every edge tile; paint the bank under water.
- **Auditions in the write-up and SOP-16:** render several seeds and motion wordings of one clip onto a sheet and
  pick by eye; the asymmetric test character's west punch now swings the brass fist in profile (1 clean take of 8).
- **Clean redos in the write-up:** an attack demo (the effect spawned on the peak frame), sprite tools (edit,
  inpaint, normal map), image to pixel art beside a plain shrink, and isometric props, all from Dotwork.
- **Licensing catch:** the first image VAE in that setup was the FLUX.2 [dev] non-commercial file. Every image made
  with it (and everything rotated or animated from one) is withdrawn from the write-up; the numbers and lessons
  stay. SOP-16 now says to check each model file's repository, license and hash, not the model's name.
- **SOP-16 tips from Dotwork:** Godot terrain needs every wang16 tile twice for narrow shapes, fill the base terrain
  first, Wan at cfg 1.0 ignores negatives, remove ground shadows before the palette lock, back views grow faces, a
  review sheet with per-clip trims and re-seeds, decor overlays for a repeating 32 px tile.
- **SOP-16, E68, `resources/ai-tools.md`:** the local pipeline's results are described on their own terms, without
  comparisons to other services. Examples synced.

## 0.6.1 (2026-10-29): local pixel art with ComfyUI
A documented local route for AI pixel art: ComfyUI and the SpriteKiln node pack on your own GPU,
free per image. Docs only; no new tool.
- **SOP-16 "Generating pixel art locally":** hardware it ran on, model tiers and their sizes (core 38 GB, about 108 GB
  for all), measured results per job, where it fits (concepts, variants and style references; final sprites still need
  polish), one palette for both, the review routine for node packs (quarantine, pin, patch, no auto-update), models
  only as `.safetensors`/`.gguf` pinned by hash, no `--listen`, per-model licenses, and what to log. New row in its tool
  table.
- **`resources/ai-tools.md`:** a ComfyUI + SpriteKiln row.
- **`/gen-brief`:** offers a local ComfyUI first for concepts and variants when the user runs one.
- **Evidence:** E68, a local setup and test (grade C: one machine; its timings and lessons are tips).

## 0.6.0 (2026-10-28): tiers that move, and a production phase
From field testing: past its toy, Claude kept answering "that is not part of the vertical slice".
Cause: the GDD's `Current tier:` line drives every scope check (SOP-08, SOP-01, `/new-feature`), and nothing ever
moved it.
- **New skill `/next-tier` (18 skills):** checks the current tier's evidence (MET, NOT MET or UNKNOWN with the file or
  command: checks pass, a human playtest in PLAYTEST_LOG, the slice's "Done when", the GDD assumptions tested), then
  moves the GDD tier line, marks the ROADMAP milestone, and pulls Parking lot items that now fit into Next. The user
  can move on without some evidence; the skill records what and why. One tier per run; going back is allowed.
- **The greenlight (vertical slice to MVP / Release) starts production:** new `docs/PRODUCTION.md` (a template until
  then) with milestones Alpha, Beta and Release candidate by exit criteria, a backlog sized S, M or L with a pillar per
  item, content progress (greybox, playable, final), a definition of done for content, risks and a cut list. Every
  milestone still ends with a playtest; a system that stops being fun goes "back to prototyping".
- **Scope follows the tier:** SOP-08 gets a "Tiers" table (where scope comes from and where a new idea goes, per
  tier). In production, an idea that serves a pillar goes to the backlog with a size, never "not part of the slice";
  only ideas outside the pillars or in GDD "Out of scope" are pushed back. SOP-01, `/new-feature`, `/gdd-sync`,
  `/start-session`, `/end-session` and the game's CLAUDE.md follow it, and offer `/next-tier` when the user keeps
  asking for work past the current tier.
- **No deadlines:** the ROADMAP milestone table loses its Target column (milestones M2 Alpha, M3 Beta, M4 Release
  candidate added); progress is counted in items and content, never dates.
- **SessionStart hook:** prints the current tier, and after the greenlight "Production backlog: N of M done" (cut items
  do not count). Fails soft like the rest of the hook.
- Existing games: `--upgrade` brings the skill, PRODUCTION.md and the unedited SOPs and skills. GDD.md and ROADMAP.md
  are yours, so they get a `.gold` copy: the new GDD line and milestone rows are optional.

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
  per-run nonce (a report cannot Dotwork the end marker), skips comments GitHub hid as spam, and lists links without
  opening them. Exam 14/14 offline; live and read-only against a public repo.
- **`/triage-issues`** sorts reports (bug, feel, needs info, duplicate, out of scope, suspicious), runs bugs through
  `/bug-hunt` from the repro step, logs feel reports by issue number (not username) and tunes one value at a time with
  the game's bot or pillar checks before and after; a change from a single report is a proposal to the user. Every
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
  offline against the published spec. Live: `check` and one 16 px `character --legacy` (1
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
- **The examples' license line said all their assets are CC0.** The art is; most sound effects were generated under
  ElevenLabs' non-commercial terms (placeholders), and Graveyard Shift's voices and music carry Fish Audio's and Suno's terms.
  `examples/LICENSE.md` and the README say so now.
- **Fix: the ElevenLabs free-plan credit lacked the required "elevenlabs.io".** ElevenLabs' help page: free-plan
  content you publish must carry "elevenlabs.io" or "11.ai"; Eleven Music is credited by name. `eleven_audio.py`
  now writes "Created in collaboration with ElevenLabs (elevenlabs.io)", and every example's credits were updated.
- START_HERE promised macOS 13+, Linux and 4 GB of RAM: now Windows 10+, tested on Windows, the others untested.
- "About 15 minutes" (no timed run behind it) became "your first session" in the README, START_HERE, the make-a-game
  skill and FIRST_HOUR. Nine examples, not eight, most with a GIF; `examples/README.md` lists lockpick-mz.
- CHOOSING_AN_ENGINE no longer says Godot export and Web `run` were untested; DISTILL_REPORT.md is labeled a
  2026-10-19 snapshot; the PROCGEN brief files are listed in the README; Godot's floor names the tested 4.7.2; the
  web examples ask for Node 22.12+; Lockpick MZ's files use the neutral default author like the others.

### After the first build: play, take notes, paste them back
- The game's CLAUDE.md has a "When it first becomes playable" section: when the toy first runs (and after the slice or
  a big feature), Claude hands the game over: play it, write down what you like and what you don't, paste the notes
  back, and iterate from there. FIRST_HOUR's fast lane says the same; `/playtest-report` takes the user's own notes
  without the tester interview; `make-a-game` previews the loop at the hand-over.

### "Crude on purpose" warning before the first build
- **Crude, not abstract** (a test project drew its characters as dots): characters and key objects get
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
A test project was built from dots and shapes, and its first playtest verdict was "unplayable". A sprite
script (a 32x32 steampunk hero, walk and punch in four directions) fixed it at no cost.
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
- Exam 17/17 -> 30/30. Live: prop, vfx, iso-tile, sidescroller
  tileset, edit and fix work; the live run found that `GET /map-objects/{id}` answers 423 while generating (now polled
  as "still working") and that a sidescroller tileset costs 2, not 1. SOP-16 lists every command with its cost and the
  lessons from field testing (fix the base sprite first; template animation drops big props, skeleton-v3 keeps
  them).

### Screenshots and bursts on Godot (from field testing)
- Godot's `smoke` gains `--screenshot FILE`, `--record DIR` and `--record-every MS`, like web: after the headless smoke
  passes, the new `tools/capture.gd` runs the main scene in a real window (headless Godot renders nothing) and saves
  the last frame and/or a frame every N. Verified on Godot 4.7.2 with a moving test node (30 frames, real motion, GIF).
- The game's CLAUDE.md: anything that moves (an attack, a jump, a walk) is shown as a burst and GIF, not a still.
  Unreal still has no capture option.

### Fix: Godot pixel scaling (from field testing)
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
Asked for in a kit session ("add in rpg maker"); built on a machine without RPG Maker MZ, so every step that needs the
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
- Graveyard Shift: a playtester walked out of the open gate and fell forever. The gate and both south corners (the wall
  model's off-center pivot) had been open since the first build. A test that walks the keeper into every gap reproduced
  it (6 of 6 south pushes fell), then invisible blockers on the wall line, left out of the NavMesh bake, and a fall
  safety net fixed it; the trio's escapes are unchanged. Lesson for SOP-17 users: also test that the player cannot
  leave the level, on the hand-made level as well as generated ones.
- Graveyard Shift grew from a playtest ("4 times the size, it's too easy"): irregular yards (a main body plus
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
- A usage or rate limit (met for real: a 429 "5-hour usage limit") is now exit 2 with the CLI's
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
- **Balance, a judgment call:** the trio's lantern tests run at Easy; careful against always-dark is asserted on the
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
- **Personal branding:** Rune Delve's `.game-kit.json` author and two lines of its `CLAUDE.md` carried a personal name
  (it was adopted without an explicit author, so the scaffolder took the git user name); now the neutral default like
  the others.
- **Iteration timelines:** Graveyard Shift, Coyote Hop and Gatekeeper (Godot) open their HOW_IT_WAS_MADE.md with a table
  of every change after the game first worked: what prompted it (the user's words or a failed check), what changed,
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
- **`fish_tts.py`:** Fish Audio text to speech: `check` (developer API balance),
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
- **Live** it found three bugs, all fixed with regression tests: the API's raw PCM is stereo (read as
  mono a 1 s sound came out 2 s long), "music is not available" (402) was reported as a rate limit,
  and the request ID and per-request cost are in `x-trace-id` and `character-cost`.
- **`wavfile.py` commands:** `stats`, `normalize` (generated audio came back at -60 dBFS) and `loop` (crossfade any
  download into a seamless loop with loop points; closes the "Suno does not loop" gap in BRIEFS). Exam 6/6 (with
  32-bit reading, below).
- **Graveyard Shift has generated sound:** five effects and a night ambience loop from ElevenLabs, the
  Unity setup gained ambience and music loops, `SceneBuilder` finds sounds in any format, `AudioSetupTests` checks the
  wiring (36 EditMode tests, smoke 5/5).
- **Graveyard Shift's world sounds:** souls whisper where they float (find them by ear), ghosts moan louder as they grow
  wary or hunt, footsteps follow the distance walked (lit or dark), the lantern crackles while lit (`examples/graveyard-shift/Assets/Scripts/Game/GraveyardAudio.cs`). The listener moved from the camera to the keeper. Three sounds came back too quiet and were
  normalized; positional sounds are mono (40 EditMode tests).
- **Graveyard Shift's ghosts whisper and the night has an ending:** Fish Audio voice lines from the ghost's position
  when it notices you, and when it catches you; at dawn the yard warms to sunrise with birdsong (ElevenLabs), then the
  screen fades to the end card with the Suno loss sting (an escape fades sooner, to the win music). `EndSequence` is a
  pure timeline function with EditMode tests (42). `fish_tts.py say` takes `--text` several times (one file each) and
  `--log` (one ASSET_LOG row and evidence for the set). Exam 10/10.
- **Graveyard Shift's voice cast** (Fish Audio, free model): a narrator (intro on the first night of a launch, escape and
  dawn outros over ducked end music), the keeper's barks (souls, gate, low time, caught) and more ghost lines (lost you,
  gave up), 29 lines on one shared voice channel that queues instead of talking over. The verdict was "voices are
  no good, keep them for now": every voice row is PLACEHOLDER in the asset log. A 30 s mix rendered at the game's real
  volumes peaks at -1.5 dBFS (43 EditMode tests).
- **Graveyard Shift's music came from Suno** (web app, from the brief in its `BRIEFS.md`): two takes,
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
  `for {{AUTHOR}}` part of template headers is gone, the author is named once in the game's `CLAUDE.md`). The personal
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
Publish prep: the kit is now meant for anyone, not one machine. New name, a fill-in profile instead of hard-coded
preferences, a fifth engine (browser games), two AI SOPs, two example games, and the tools those examples showed were missing.

### Renamed and made neutral
- **"Claude Game Dev Gold Standard" is now the "Claude Code Game Kit".** Project metadata moved from `.gold-standard.json` to
  `.game-kit.json` (`kit_version` replaces `gold_standard_version`); the old file and the old `.gitignore` marker are still
  read, and the old file is replaced on the next `--adopt` or `--upgrade`. `GOLD_VERSION` is now `KIT_VERSION`.
- **Profiles** (`profiles/`, `--profile FILE`): author, an optional file footer and extra working-style lines for the game's
  `CLAUDE.md`. The default is neutral: no footer, author from the profile, else `git config user.name`. The old
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
  `/perf-pass` and SOP-10 fill the ARCHITECTURE Budgets table; `/new-feature` parks pillar orphans (overrides recorded) and gains
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

# How Graveyard Shift was made

The kit's Unity 3D example, and its fourth "only what is in the kit" run (after ghost-lantern, courier-dash and
scrap-tanks). One Claude Code session (Claude Opus 5.5) on Windows 11 with Unity 6000.6.6f1, 2026-10-21. The owner picked
the concept; Claude did the rest by following the kit's documents and tools, without opening the Unity editor's UI, and
recorded every place the kit fell short. Each gap was fixed **in the kit** and pulled in with `new_game.py --upgrade`.

## Iteration timeline: how the game changed after it first worked
The first build (sections 1 to 8) ended with a playable night and silent-ish Kenney interface sounds. Everything after
that came from the owner listening, playing and reacting, one change at a time. Each row: what prompted it (the owner's
words, or a check that failed), what changed, and what proved it. Details in the "Later" sections further down.

| # | Day | Prompted by | What changed | Proof |
|---|---|---|---|---|
| 1 | 10-21 | The bot trio refuted the lantern pillar | Ghost sight and speeds redesigned until careful play beats always-dark and always-lit (section 6) | Trio over 8 seeds, 34 EditMode tests |
| 2 | 10-22 | Owner: try generated audio, each example a different way | 5 Kenney effects replaced and a night ambience added with ElevenLabs (free plan, so non-commercial: PLACEHOLDER) | 275 credits; the ambience came back at -60 dBFS and was normalized; 3 bugs in the new tool found live and fixed |
| 3 | 10-22 | No music at all | A Suno brief written; the owner made the music in Suno's web app | First try: "not very video gamey" (the generic template had been pasted); the fixed brief got "cute creepy" |
| 4 | 10-22 | Suno does not make loops | Both takes kept and looped where each best matches its opening (spectral similarity), crossfaded, OGG, alternating per night, streamed | Exact length after encoding, seam smaller than an ordinary sample step; owner on the phone: "I can't even tell there is a loop" |
| 5 | 10-22 | Owner: use the free credits on the game | Soul whispers (find souls by ear), ghost moans by state, footsteps by stride, lantern crackle; the listener moved from the camera to the keeper | 40 EditMode tests; 3 sounds too quiet, normalized |
| 6 | 10-22 | Owner: voice for the game | Ghost whispers (Fish Audio) when they notice and catch you; a dawn chorus | 41 tests |
| 7 | 10-22 | Owner: "what is the dawn chorus for if we have the Suno music?" | It got a job instead of being cut: the owner's design of the ending, dawn first, then a screen fade to the end card with its music (`EndSequence`) | The timeline is a pure function with EditMode tests (42) |
| 8 | 10-22 | Owner: narrator, keeper and more ghost lines | A cast of 29 lines on one shared voice channel that queues instead of talking over | 43 tests; a voice reel sent to the phone |
| 9 | 10-22 | Owner after the reel: "voices are no good, but keep them for now" | Kept as scaffolding, every voice row marked PLACEHOLDER so the release check flags them | Asset log |
| 10 | 10-22 | A 30 s mix rendered at the game's real volumes, on the phone | Owner: "walking is too loud": footsteps halved (about 6 dB) | Re-rendered mix: "better" |
| 11 | 10-22 to 23 | Owner: "is each night a new graveyard?" (it was not) | Generated nights: night 0 is the hand-made yard, every later night a new yard from a seed on the HUD; the kit gained `/procgen` and SOP-17 from it | 250 seeds pass every invariant; 8 generated nights with the bot trio: careful escapes 7, always lit 0; eight things caught on the way ("Later: a new graveyard every night") |
| 12 | 10-23 | Owner, playing the build: "lol if you go out the gate you fall forever" | Invisible blockers on the wall line at the gate and the south corners (holes since the first build), a fall safety net, and `Smoke_K` that walks the keeper into every gap | Reproduced first (6 of 6 pushes fell), then 10 of 10 stay inside; the trio's escapes unchanged |
| 13 | 10-23 | Owner: "4 times the size, it's too easy", roofs and doors, an actual gate; then: not square, grass and trees outside, a title screen with Easy to Insane, two more ghosts a step | Irregular 4x yards, buildings with roofs and doors, a swinging iron gate, the world outside the wall, difficulties, 12 souls and a 300 s night ("Later: four times the yard") | 87 tests; the trio at Normal: careful escapes 5 of 8 generated nights, always lit 0; eight things caught on the way |
| 14 | 10-23 | The owner's first playtest of the build: the title text was clipped and the window small; the narrator spoke over the title; the difficulties all looked the same; lantern out, the legs froze; the lantern was not in his hands; caught with every soul, the gate stayed open, and outside it he fell | Six fixes, each found in the code or the player's own log before changing anything ("Later: the first playtest of the big yards") | 89 tests, 14 smoke; brightness away from the lantern measured from the built player at each difficulty: 53 to 0.9 instead of 60 to 46 |
| 15 | 10-23 | The owner: "anything we can have Kimi do?" (Kimi K3.1 had just shipped) | A read-only Kimi audit of this game: 10 findings, 9 confirmed, all fixed ("Later: a second opinion"); the trio's lantern tests moved to Easy | 101 tests, 15 smoke; careful 104 = dark 104 on the hand-made yard at Easy |
| 16 | 10-26 | A review (Fable) that proved ten bugs with tests in a scratch copy | All ten fixed, plus one the fixes exposed ("Later: review fixes") | 112 tests, 20 smoke; careful still escapes far more than always-lit on both kinds of night |
| next | | The Suno win music and loss stings | Slots ready (`win_music_a/b`, `loss_sting_a/b`), silent until the files arrive | |

What the timeline shows: the plan never said "add a narrator" or "the dawn chorus opens the ending". Those came from a
person hearing the game and saying what was wrong. Rendering audio to the owner's phone made that loop minutes long
instead of "open Unity, play a night".

## The rule
Allowed: what a kit user has after scaffolding (docs, SOPs, skills, `tools/`, the Unity overlay) plus the sources the
kit's resource lists name, and Unity packages the kit's docs point at. Not allowed: outside scripts or tools.
Exceptions are listed at the end.

## 1. Create, adopt, verify (FIRST_HOUR)
Unity is adopt-first (`docs/ENGINE.md`): make the Unity project, then lay the kit over it.
```
"<Unity.exe>" -batchmode -nographics -createProject D:/kt/gy -quit
python scripts/new_game.py --name "Graveyard Shift" --engine unity --dest D:/kt/gy --adopt
python tools/dev.py doctor && python tools/dev.py check && python tools/dev.py test
```
The skeleton's boot smoke test said, correctly, that there was no scene yet. Making one meant the editor UI, which this
run does not use.
**Kit gap U1:** no way to run editor code from the command line. Fixed: `dev.py exec Class.Method` runs a static editor
method in batchmode, and the skeleton's `Assets/Editor/GameKitScenes.cs` has `CreateStarterScene` and
`AddToBuildSettings`, so scenes can come from code. This game's `SceneBuilder.Build` uses both.

## 2. Concept and GDD
Claude offered three Unity concepts, each built on Unity parts no example had used; the owner picked "Graveyard Shift"
(NavMesh agents, 3D third person, a versioned save). The GDD got three pillars: **light is a choice**, **read the
ghosts**, **one more night**.

## 3. Assets: fetch and validate
```
python tools/fetch_asset.py --url <graveyard-kit zip> --page https://kenney.nl/assets/graveyard-kit --author Kenney \
  --license CC0 --type 3d --base "Models/FBX format" --to Assets/Art/Graveyard --take "Models/FBX format/character-keeper.fbx" ...
(the same for five Interface Sounds into Assets/Audio)
python tools/blender/validate_asset.py Assets/Art/Graveyard/<model>.fbx      # every model
```
**Kit gap U2:** every Kenney FBX got a warning for an unapplied scale. FBX files store centimeters, so a uniform 0.01 (or
100) on import is the unit conversion, not a mistake. Fixed: `validate_asset.py` reports a uniform 0.01 or 100 on an FBX
as an info line (exam 24/24). An `AssetPostprocessor` (`Assets/Editor/GraveyardImport.cs`) gives the characters Legacy
animation and no colliders.

## 4. Slice brief and ADRs
`docs/VERTICAL_SLICE.md`: one graveyard, six souls, three ghosts, caught and dawn, a save with a migration; menus and
music out. Three ADRs: **0001** keep the Built-in pipeline, Input Manager and IMGUI (what a headless project gets, and
all drivable from C#), **0002** Unity's AI Navigation package, **0003** a C# state machine for the ghosts.
**Kit gap U3:** the concept planned Unity's Behavior package (SOP-14's Unity row named it). In version 1.0.16 the graph
classes and node constructors are internal: graphs are made in the editor's graph window, and C# can only add nodes.
SOP-14's Unity row and `docs/ENGINE_FLOW.md` now say so. The package was installed to check, then removed (ADR 0003).

## 5. Build (SOP-01, then SOP-14 through `/game-ai`)
- **Engine-free core first, with tests:** ground math, tunables, perception, the ghost FSM (patrol, suspicious, hunt,
  search, return), the night's rules, the save and its migration, the level as data. `Assets/Scripts/Core` uses
  no `UnityEngine` types; 34 EditMode tests cover it.
- **Unity side:** the level built at runtime from data, every prop with a box collider tagged `Cover` (it blocks both
  walking and sight), a NavMesh baked from those colliders, NavMeshAgents for the ghosts, a CharacterController keeper,
  a camera rig, ghosts that glow their state, an IMGUI HUD, five sounds, keyboard and gamepad.
- **Scene and settings from code:** `SceneBuilder.Build` reimports the models, fills the setup asset, writes the scene
  and sets the version (0.2.0) and player settings; `dev.py exec SceneBuilder.Build` reruns it.
**Kit gap U4:** the Unity `dev.py smoke` could only run tests: no markers, no screenshots, no recording, while the web
and C++ overlays had all three. Fixed for parity: `--until`, `--fail-on`, `--graphics`, `--screenshot`, `--record` and
`--record-every`; `Assets/Tests/PlayMode/GameKitCapture.cs` renders the camera into PNGs. The GIF above is a recorded
test night. An IMGUI HUD does not show in camera captures (noted in `docs/ENGINE_FLOW.md`).

## 6. The scenario trio, and how it refuted the pillar
`Assets/Tests/PlayMode/ScenarioTests.cs` plays three bots on the real scene: **careful** (lantern lit only while no ghost
is near), **always lit** and **always dark**. They share one movement brain, so the lantern is the only difference.
| Round | Result | What it showed | Change |
|---|---|---|---|
| 1 | every bot path `PathInvalid`; bots walked into gravestones | `NavMesh.CalculatePath` does not snap its ends to the mesh | sample both ends first (ADR 0002) |
| 2 | careful was always dark and then waited 100 s or more | it treated every ghost as a threat | wait only for ghosts near the way ahead |
| 3 | careful backed into corners and toward a second ghost | hiding spots were scored against one ghost | all ghosts count, corners penalized, paths must stay clear |
| 4 | tuning changes did nothing in the game while tests passed | **kit gap U5** (below) | tests read the asset; `SceneBuilder.ResetTuning` |
| 5 | 4 seeds: careful **5** souls in total, dark 16, lit 16 | a dark keeper that is spotted cannot escape a ghost, and a catch ended the night | **redesign:** hunting ghosts tire after 6 s; a catch costs the last soul and a walk from the gate, not the night |
| 6 | a tired ghost hunted again at once | tired only ended the hunt | tired means return and ignore the keeper for 5 s |
| 7 | 4 seeds swung whole nights on small changes | 4 seeds and one start position per ghost is too few | **8 seeds**: each picks a ghost's starting corner and direction; assertions on totals |
Final, over 8 nights each (progress = souls, an escape counts 7, of 56):
| Bot | Progress | Escapes | Catches |
|---|---|---|---|
| Always lit | 23 | 0/8 | 8 |
| Always dark | 40 | 2/8 | 1 |
| Careful | 44 | 2/8 | 0 |
The test asserts careful ≥ dark, careful beats lit by 10 or more, and lit is caught more than twice as often as the
others together. The honest part: careful beats always-dark by 4 souls over 8 nights. Lighting up is clearly punished
when done always, and only slightly rewarded when done well. That is the first question for a human playtest
(`docs/VERTICAL_SLICE.md`).

## 7. What the kit's checks caught
| Caught by | Problem | Fix |
|---|---|---|
| The scenario trio | Pillar 1 false as built (rounds above) | Ghosts tire, catches cost time, bot fixes |
| EditMode tests reading the asset (after U5) | A perception test hard-coded 10 m | Tests relative to the tuning |
| The boot smoke test | `Bootstrap has no SO_GraveyardSetup` after `SceneBuilder.Build` | Reload the asset after `NewScene` (it unloads unused assets) |
| `dev.py build` | Capture PNGs in the player folder | **kit gap U6:** `build/` and `Build/` are one folder on Windows; captures go to `Logs/` |
| The built player | A replay of seed 6 diverged from the test | `--fixed-fps` (the test fixes frames at 1/60 s); the player now escapes at 65.2 s like the test |
**Kit gap U5:** C# field defaults on a ScriptableObject only seed a **new** asset. Changing a default later reaches nothing:
the game reads the asset, while tests that built `new GameTuning()` saw the new value, so tests and game disagreed
without a sign. The Unity `docs/ENGINE.md` now warns about it.
**Kit gap U7:** Unity 6.6 writes a `.slnx` solution, which the overlay's `.gitignore` did not list (found when copying
the game into the kit). **Kit gap U8:** once, Unity's Package Manager server did not start and `dev.py check` reported
"compile failed"; it now exits 2 and says to run it again (the retry passed).

## 8. Verified
| Check | Result |
|---|---|
| `python tools/dev.py check` / `test` | compiles / 112 EditMode tests in 136 s (2026-10-26, after the review fixes; 101 before, measured at 146 s) (perception, every FSM transition, night rules, saves and their migration, ghost starts, level checks on the hand-made and generated yards, the 250-seed property test, a broken yard for each invariant, pinned yards, measured footprints, audio wiring, music, world sounds, the end sequence, voices) (2026-10-23) |
| `python tools/dev.py smoke` | 20 tests, 80 bot nights, 779 to 1047 s (2026-10-26, after the review fixes; 15 tests in 812 s before; `Smoke_D` failed once at the 104 cap, see "Later: review fixes"). Before that: 15 tests pass (2026-10-23, after the Kimi audit; the trio at Easy, `Smoke_N` at Normal logged): boot, the trio on the hand-made yard (24 nights), the walk grid against the NavMesh on 9 yards, the trio on 8 generated nights, no way out and the gate shutting, every difficulty, the keeper's lantern and legs, a yard from above |
| `python tools/dev.py build` | a Windows player in `Build/` (about 45 s) |
| The built player, `--autoplay careful --seed 6 --fixed-fps` (before the generator; now `--handmade --seed 6`) | escapes at 65.2 s with exit 0, the same as the test; rechecked 2026-10-23 with `--handmade`, and a generated night (`--seed 6258`) escapes at 102.3 s like its test |
| The README steps in a fresh copy inside the kit repo (no `Library/`) | import, `check`, 34 tests, `smoke` 5 tests in 103 s with the same trio numbers |
| `python tools/doctor.py`, `tools/check_links.py`, `tools/publish_check.py` | healthy, no broken references (after expanding short paths the check caught); the only FAIL is the license file, which lives one level up for examples |

### Later: generated sound (ElevenLabs) and a music brief (Suno)
Each kit example gets its audio a different way: Coyote Hop synthesizes it with code, this one generates it with
ElevenLabs through `tools/audio/eleven_audio.py`, and its music comes from Suno's web app.
```
python tools/audio/eleven_audio.py check          # plan free: sound effects yes, music no (HTTP 402)
python tools/audio/eleven_audio.py sfx --text "soft glassy magical chime with a gentle shimmer, a lost soul set free"   --seconds 1.2 --format pcm_32000 --mono --out Assets/Audio/soul_collected.wav --log
(four more effects the same way, prompts in docs/BRIEFS.md)
python tools/audio/eleven_audio.py sfx --text "quiet graveyard at night, soft wind through pine trees, distant crickets, an owl far away, no music"   --seconds 20 --loop --format pcm_32000 --out Assets/Audio/night_ambience.wav --log
python tools/audio/wavfile.py normalize Assets/Audio/night_ambience.wav --peak -3
python tools/dev.py exec SceneBuilder.Build
```
- Cost: about 10 credits per second of sound, 275 credits in all (the tool prints each request's cost).
- `--log` wrote six ASSET_LOG rows and evidence files with the prompt, model, plan and SHA-256. On a free plan the
  output is non-commercial and needs credit, so every row says PLACEHOLDER: `/release-check` will flag them.
- Nobody on the AI side can hear, so the files were measured: the effects peak between 0 and -9 dBFS, but the
  ambience came back at -60 dBFS RMS (inaudible in game), so it was normalized (+39 dB, logged as Modified). Its
  loop seam is clean: the jump from the last sample to the first is smaller than an ordinary step.
- The live run found three bugs in the new tool, fixed before anything was kept: the API's raw PCM is stereo (read as
  mono, a 1 s sound came out 2 s long), "music is not on your plan" was reported as a rate limit, and the
  request ID and cost live in `x-trace-id` and `character-cost`.
- Unity: `GraveyardSetup` gained `ambience`, `music` and their volumes, the game starts them as looping
  `AudioSource`s (a missing clip is skipped), and `SceneBuilder` finds a sound by name in wav, ogg or mp3.
  `AudioSetupTests` checks the wiring.

### Later: sounds that follow the game (more ElevenLabs credits)
Four more generated sounds, 215 free-plan credits, wired by `Assets/Scripts/Game/GraveyardAudio.cs`:
- **Soul whisper** (6 s loop, 3D): every uncollected soul hums where it floats, full volume within 1.5 m, silent past
  11 m, so a soul in the dark can be found by ear. Collecting a soul switches it off, which silences it.
- **Ghost presence** (8 s loop, 3D): each ghost moans, fading between three volumes by state (patrol, wary, hunting),
  so a ghost behind you is heard before it is seen.
- **Footsteps** (3 takes): one per stride of distance walked, 1.4 m lit and loud, 0.9 m dark and soft, each with a
  small random pitch change; a respawn jump is not counted as walking.
- **Lantern flame** (6 s loop): fades in when the lantern is lit, out when it is not.
- The audio listener moved from the high camera to the keeper (with the camera's heading), otherwise "closer to the
  soul" would have meant closer to the camera 13 m up.
- Measured before wiring: three came back too quiet again (footsteps near -38 dBFS peak, the flame at -53 dBFS RMS)
  and the ghost touched full scale; all three were normalized to -3 dBFS (logged as Modified). Positional sounds were
  generated mono, which `AudioSetupTests` now checks along with the state volumes (40 EditMode tests).

### Later: ghost voices (Fish Audio) and the end of the night
- **Whispers:** three "noticed you" lines ("Who's there?", "I see a light...", "Someone's here...") and two "caught" lines,
  made with `tools/audio/fish_tts.py` on the free model in one call per set (`--text` repeated, `--log` wrote one
  ASSET_LOG row each). The voice is "Creepy Whisper" from Fish's library, picked by reading descriptions: "Creepy Tale"
  said it copies a CapCut voice, so it was out. A ghost whispers from where it floats (3D), at most once per 6 s.
- **The ending** (`EndSequence.cs`): at dawn the night's sounds fade, birds sing (ElevenLabs "dawn chorus"), and the
  moon, fog and sky blend to sunrise for 3.5 s; then the screen darkens and the end card shows with the loss sting.
  An escape holds 0.8 s on the gate instead. The timeline is a pure function of time, tested in EditMode (42 tests);
  the Suno win and loss tracks plug in by name (`win_music_a/b`, `loss_sting_a/b`) and stay silent until added.
- The design came from the owner mid-build ("start with the dawn for a few seconds... then fade to the win or loss");
  the dawn chorus had been added before asking, and nearly went: the question "what is it for, if we have the Suno
  music?" was fair, and the answer was to give it a job (showing it is dawn) instead of doubling the sting.

### Later: a voice cast (Fish Audio)
The owner wanted more voice than the ghost whispers, so the night got a cast, 29 lines in all, on the free model:
- **Narrator** ("Warm Storyteller"): an intro over the start screen on the first night of a launch (not on every
  R), and an outro on the end card, one set for escaping and one for dawn, with the end music ducked under the words.
- **The keeper** ("Old man"): barks when a soul is picked up, when the gate opens, when dawn is close, and after
  being caught (right after the ghost's "Gotcha").
- **The ghosts** (same "Creepy Whisper"): lines for losing you ("Where did you go...?") and giving up ("...gone
  again."), next to noticing and catching.
- Voices were picked by reading the library descriptions, not titles alone: the search for "grandpa" turned up a
  game character's voice ("Grandpa for Granny 2"), skipped like the CapCut copy before it.
- The keeper came back about 15 dB quieter than the narrator, and the narrator peaked at -0.4 dBFS: all normalized to
  -3 dBFS so the cast sits together (logged as Modified).
- Keeper and narrator share one voice channel in `GraveyardAudio`: a line waits up to 2.5 s for the one playing,
  then is dropped, so nobody talks over anybody; a set never plays the same take twice in a row. `SceneBuilder`
  loads each numbered set (`keeper_soul_1`, `_2`...) by prefix. 43 EditMode tests.
- The owner's verdict after the voice reel: "voices are no good, but keep them for now". The system (who speaks when,
  queueing, cooldowns) stays; every voice row in `docs/ASSET_LOG.md` is marked PLACEHOLDER so `/release-check` flags
  them. Free-model library voices are a fast way to prove the timing, not the final cast.

### Later: music from Suno (made by a person in a web app)
The third way to get audio in these examples: a person makes it in a web tool from a brief Claude wrote. Suno has no
official API, so the owner pasted the brief from `docs/BRIEFS.md` into Suno's Advanced mode (paid plan, 2:00,
instrumental, weirdness about 25-30%, style influence about 70%) and downloaded the two takes it made. Both were kept.
- The first try came back "not very video gamey": the generic template, `[brackets]` and all, had been pasted. The
  brief is now one block per Suno box, the style starts with "video game background music", and the kit's template
  says it is a template.
- Suno does not make loops. The loop point was found by measurement instead of by ear: the spot late in each track
  whose spectrum best matches the first 8 s (A at 76.95 s; B at 92.17 s, a clear match). The tempo guess (76 to 78
  BPM) was too rough to cut by bar count. Then:
  `python tools/audio/wavfile.py loop "<download>.wav" --end 95.17 --crossfade 3 --out night_music_b_loop.wav`
- 23 MB WAVs became 1.5 and 1.8 MB OGG files (ffmpeg, Vorbis q6, outside the kit). Decoded, each is exactly as long
  as the cut WAV and the seam step is smaller than an ordinary sample step, so the loop has no gap or click.
- Then the human check the numbers cannot do: 30 s MP3s with each wrap point at 0:15, plus both full loops, went to
  the owner's phone through the Claude Code session. Verdict: "I can't even tell there is a loop, it sounds like one
  song", for both takes, including A, the weaker spectral match.
- `GraveyardImport` streams `night_music_*` (no 30 MB of decompressed audio in memory); the game picks the track by
  nights finished (`GraveyardGame.PickMusic`), so a replay sounds different. `AudioSetupTests` checks both tracks,
  streaming and the alternation (38 EditMode tests).

### Later: a new graveyard every night (procedural generation, SOP-17)
The owner asked whether each night was a new graveyard. It was not: the seed only moved the ghosts' starting corners.
Now night 0 is the hand-made yard and every later night is generated, built for the kit's procgen skill (`/procgen`,
SOP-17) and proven here. One session (Claude Opus 5.5), 2026-10-22 and 23, from the brief in `../../PROCGEN_PROMPT.md`;
the game was backed up first, and Unity ran in batch mode only.

**What is generated.** Inside the shared wall, gate and keeper start: a skeleton (the path up from the gate and two side
corridors through every row), crypts and trees off the corridors, gravestone rows that keep those paths open, six
souls picked from ground the keeper can reach, and three ghost loops (down each corridor, and round the middle).
`Assets/Scripts/Core/LevelGenerator.cs`, engine-free; `SeedForNight(n)` gives night n's seed (night 0 gives 0, the
hand-made yard); the HUD shows `SEED n` and `--seed n` replays it; `--handmade` keeps the hand-made yard.

**The invariants** (`LevelCheck.cs`), run on every attempt and by the tests:
| Every yard must | Number |
|---|---|
| have six souls inside the walls, each, and the start and the gate approach, at least 0.6 m from any prop | `SpotClearance` |
| let the keeper reach every soul and the gate on foot (a walk grid of 0.125 m cells, agent radius 0.5 m plus a 0.125 m bake margin) | `KeeperRadius`, `BakeMargin` |
| keep souls 10 m apart and 10 m from the start (7 m on the hand-made yard) | `SoulSpacing`, `GeneratedFromStart`, `SoulFromStart` |
| have cover (not a wall or a post; since the 2026-10-26 review, only props at least as tall as the keeper's chest) within 4 m of every soul, so creeping in the dark can work | `CoverReach`, `Footprint.IsCover` |
| have three ghost loops at least 16 m long, every corner reachable by a ghost (within its 0.8 m arrive radius), none within 8 m of the start (ghosts can start at any corner) | `MinLoop`, `GhostStartSafe` |
| have no prop overlapping another (allowing the 1/8 m that snapping adds) | `OverlapTolerance` |
Generate, check, and on any problem try again from a seed made of the seed and the attempt, at most 25 times, then fall
back to the hand-made yard (logged; a test fails if a tested night ever falls back).

**What the checks caught, in order**
| # | Caught by | Problem | Fix |
|---|---|---|---|
| 1 | `LevelCheck` on the hand-made yard | 8 findings in a yard that had passed every test: pines planted in a gravestone row and in the wall (5 overlaps), a soul 0.45 m from a turned pine's box that the walk grid also calls out of reach, a ghost corner inside a pine's box | Kept as built (the yard is the baseline); written into `HandMadeYard_HasOnlyItsKnownProblems`. The NavMesh, and the bots, reach both spots: the grid is stricter there (the safe direction) |
| 2 | Measuring the meshes in batch mode | The old level test guessed a radius per model; a turned mesh's bounds are the box around its turned box (a pine at 45 degrees blocks 3.6 m, not 2.7 m) | Measured footprints in `Footprint.cs`; `Footprints_MatchTheMeshes` checked 14 models at 7 angles (98 pairs); since the buildings came ("four times the yard" below) it checks 106: 14 props at 7 angles and the two buildings at 4 |
| 3 | The rejection tally | Every rejected attempt was "no room for a tree" | Trees became optional: 9,994 of 10,000 seeds pass on the first attempt |
| 4 | `PinnedYards_OnlyChangeOnPurpose` | The same code and seed built **different yards** in Unity's Mono and in .NET 8. A trace showed the PRNG and `Math.Cos` identical bit for bit, but `min + (max - min) * r` rounded differently, and one borderline comparison changed everything after it. Likely Mono keeping float intermediates at double precision **(verify)** | Every generated coordinate and every constant added to one is a multiple of 1/16 m, so sums are exact; prop boxes are computed in double and snapped outward. Traces then matched line for line, and the pinned prints (made in .NET 8) pass in Unity |
| 5 | `Smoke_E` (walk grid against the real NavMesh) | Yard 55875: a 1.0 m gap between a pine and the wall that the grid passed and the bake closed | A 0.125 m bake margin. Now 17 yards and 323 checks: the grid is never looser than the NavMesh, stricter twice (both in the hand-made yard) |
| 6 | The bot trio | The always-dark bot pushed into a low rock for 104 s: the NavMesh agent climbs 0.75 m (logged from Unity), the keeper's CharacterController 0.3 m, and the "rocks" model is 0.75 m tall | Tried in the game: every blocker marked Not Walkable on the NavMesh. Correct, but it moved the hand-made balance (careful 36 against dark 43, 0 escapes) and failed its test, so it was reverted; the generator no longer uses the low rock. The engine mismatch stays for the owner to decide after a playtest |
| 7 | The bot trio on generated nights | Random rectangle ghost loops: the careful bot was caught 18 times in 8 nights (0 on the hand-made yard) and lost to always-dark | The hand-made yard's skeleton copied into the generator (corridors, loops along them): careful 56, dark 56, lit 24 |
| 8 | The same trio | Now too easy in the dark: always-dark escaped 8 of 8 (2 of 8 on the hand-made yard), so the lantern stopped being a choice | Souls 10 m apart and 10 m from the start: careful 54, dark 48, lit 19 |
| 9 | An independent review (a Sonnet subagent that had not seen the work) | The soul reachability check had been swallowed by a comment during an edit, so it could never fail; good yards never tripped it and every test passed. Also: the 10 m start rule lived only in the generator, magic numbers outside the constants block, a test named "sight" that checked a different distance, the local-retry idea graded B though only one source backs it | Fixed; every invariant now has a test that feeds it a broken yard (`EveryInvariant_CatchesABrokenYard`); the repaired check also flags the hand-made soul above. The generated yards did not change (same pinned prints) |
| 10 | The goal's judge | "The HUD shows the seed" had no proof: batch mode never runs OnGUI, and camera captures leave the IMGUI HUD out | `--shot FILE` saves a real frame (ScreenCapture) in a windowed player, and the HUD logs `SEED_SHOWN` when it first draws the label: `docs/procgen/hud_seed_48947.png` shows "SEED 48947". In batch mode, the HUD keeps the label in `Hud.SeedLabel` every frame and `Smoke_J` reads it from the live scene through `dev.py smoke` |
| 11 | The owner, playing: "if you go out the gate you fall forever" | The gate was a 4 m gap in the wall with nothing behind it but the edge of the ground, and the wall model's off-center pivot left 1.6 m holes in both south corners. `Smoke_K` (written first) pushed the keeper at the gate and all four corners on two yards: 6 of 6 south pushes ended 40 m below the ground. On the hand-made yard too: the bug was there from the first build | Invisible blockers on the wall line (gate and south corners) in `LevelBuilder`, left out of the NavMesh bake; a fall below 3 m puts the keeper back at the start. Baking the blockers into the NavMesh first moved the hand-made trio (careful 39 against dark 40), so they stop bodies only. Now 10 of 10 pushes stay inside |

**Final numbers** (2026-10-23, after the gate fix, `dev.py test` and `smoke` in the scratch copy):
| Over 8 nights (progress: souls, an escape counts 7, of 56) | Progress | Escapes | Catches |
|---|---|---|---|
| Hand-made yard: careful / always dark / always lit | 44 / 40 / 20 | 2 / 2 / 0 | 0 / 1 / 10 |
| Generated nights 1 to 8: careful / always dark / always lit | 54 / 48 / 18 | 7 / 6 / 0 | 11 / 6 / 12 |
Before the gate fix, always-lit made 23 and 19 progress with 8 and 5 catches: a hunted lit keeper could flee through the
holes. Careful's and always-dark's progress and escapes did not change (careful's catches on generated nights went
from 9 to 11).
- 250 night seeds in the EditMode property test: 250 different yards, 0 problems, 0 fallbacks, about 65 ms per yard in
  the editor (about 19 ms in .NET 8); 10,000 seeds in a scratch harness: 6 second attempts, 0 fallbacks.
- Soul tour as the crow flies (nearest soul next, then the gate), 10,000 yards: median 103.5 m, 10% under 90.0 m, 10%
  over 123.6 m; the hand-made yard's is 112.8 m.
- The built player replays both kinds exactly: `--autoplay careful --handmade --seed 6 --fixed-fps` escapes at 65.2 s
  and `--seed 6258` at 102.3 s, the same as the tests.
- Three yards from above: `docs/procgen/yard_seed_6258.png`, `yard_seed_48947.png`, `yard_seed_55875.png` (Smoke_J,
  fog off). `docs/procgen/yards_top_down.png` draws the hand-made yard and nights 1 to 8 as boxes, loops and souls.
- The HUD as a player sees it: `docs/procgen/hud_seed_48947.png`, from `Build/game.exe -screen-fullscreen 0 -- --autoplay
  careful --seed 48947 --fixed-fps --shot <file>` (log: `SEED_SHOWN "SEED 48947"`, then `ESCAPED time=70.5s`).
- The built player was run directly (game.exe from `dev.py build`), as the README's own check does: `dev.py` has no command that
  runs a built player. Unity itself (the editor) ran in batch mode only, through `dev.py`.

**Honest limits**
- The pillar holds on generated nights in its main form (careful escapes 7 of 8, always lit 0; careful beats dark by
  6), but not in every form: always-lit is not caught twice as often as the others there (12 against 11 and 6), because
  it loses mostly by stalling (it waits, lit, for ghosts to pass). `Smoke_I` asserts the catch ratio only for the
  hand-made yard.
- Dark escapes 6 of 8 generated nights against 2 of 8 hand-made: generated nights are easier. A playtest question.
- Some trio totals move between identical runs: before the gate fix, always-dark's catches on generated nights read 6
  or 7, always-lit's progress 17 or 19 and its catches 5 or 6; after it, one full run each. Escapes (7, 6, 0 and 2, 2,
  0) repeated in every run. So the trio is not perfectly repeatable from run to run **(verify the cause)**.
- `SeedForNight` hashes into 1..99,999, so two nights can share a seed: none of the first 250 do, a repeat becomes
  likely after a few hundred nights. Left as is, because changing it reorders every player's nights.
- The player was built with Mono (the project default); IL2CPP was not built or compared **(verify)**.
- The NavMesh says a ghost reaches the hand-made corner (17, -12) at 0.00 m although the footprint box covers it:
  unexplained, and the safe direction **(verify)**.
- Bot-tested, not human-tested: whether generated yards are fun is open.

**Outside the kit:** a scratch .NET 8 console project (Unity's bundled `dotnet`) that compiles the game's Core files ran
thousands of seeds in seconds, printed the rejection tally and the tour metric, and dumped yards for a throwaway Pillow
script that drew `yards_top_down.png`. A temporary editor script measured the meshes and another wrote the cross-runtime
trace; both were deleted (the footprint test and the pinned prints replace them).

### Later: four times the yard, a real gate, and difficulties
The owner, after playing: "graveyard needs to be 4 times the size, it's too easy. Buildings need roofs and doors. The
graveyard should have an actual gate." Then, while it was being built: yards need not be square ("rectangle, or
irregular sections jutting out"); the outside should be grass with trees and bushes, "so it doesn't look like a floating
graveyard"; a title screen with Easy, Normal, Hard and Insane, where Easy is today's light, Normal darker, and Insane
"pitch black except the small area of the lantern"; and two more ghosts each step. Choices made with the owner: 4x the
area (not each side), more ghosts and souls and a night that grows less than the walk, decorative closed doors, and a
new hand-made yard at the new size.

**What changed**
| Piece | Before | Now |
|---|---|---|
| Yard | 40 x 30 m box | A main body plus wings (`Level.Areas`, a union of rectangles on a 2 m grid), 4,000 to 5,200 m2; the hand-made night 0 is about 4,400 m2 with three wings |
| Wall | Segments placed by hand; the model's off-center pivot left holes | One segment on every edge between inside and outside, centered on it, so every corner closes |
| Gate | A gap (and, after the fall, an invisible blocker) | Two iron fence leaves on hinges (`GateSwing`), shut until the last soul, then they swing out |
| Buildings | Roofless crypts | Large and small crypts get their roof and a closed door (`Footprint.Parts`); low tombs (`crypt`, `crypt-a`, `crypt-b`) too |
| Outside | The ground box ended at the wall | Grass to the horizon and about 160 trees, bushes and tufts (Kenney Nature Kit, CC0, A-0027), not in the NavMesh; the trees have no colliders, the grass has one since the first playtest |
| Souls, ghosts, night | 6 souls, 3 ghosts, 150 s | 12 souls, one ghost per patrol loop (about one per 550 m2: 6 to 12, typically 8), 300 s |
| Difficulty | None | Title screen: Easy (the old light, the loops' ghosts), Normal (darker, +2 ghosts), Hard (+4), Insane (+6, no ambient, moon, soul glow or ghost light; souls are found by their whispers). Saved in the save file (v3, with a v2 to v3 migration test); `--difficulty` skips the title |
Extra ghosts walk the longest checked loops from the opposite corner, so difficulty never changes the yard or its checks.
The two narrator lines that said "six souls" were re-voiced with "twelve" (Fish Audio, the same free model and voice).

**What the checks caught**
| # | Caught by | Problem | Fix |
|---|---|---|---|
| 1 | The scratch harness on the new generator | 19 of 200 seeds fell back to the hand-made yard: random outlines were mostly too small; and the new hand-made yard failed its own checks (a soul outside the wall, two crowded souls, 9 ghost corners in trees or rows) | Outlines are redrawn until the area fits, before any props; the hand-made coordinates moved until `LevelCheck` found nothing |
| 2 | `PinnedYards_OnlyChangeOnPurpose` | Two of four pinned yards differed between Unity and .NET 8 again: the new ghost cells used `MinX + i * (width / n)`, a float formula with rounding | Cell widths in whole lattice steps; the prints match again |
| 3 | The 250-seed property test (timeout) | About 1 s per yard in the editor: every candidate soul spot recomputed every prop's box, with trigonometry | Boxes worked out once per check: 6 times faster (42 ms a yard in .NET 8, about 0.45 s in the editor) |
| 4 | `Footprints_MatchTheMeshes` | A crypt with roof and door, turned 15 degrees, has a footprint box 0.13 m bigger than its pieces' boxes together | Buildings only ever stand square to the wall, so they are checked at 0, 90, 180 and 270 degrees |
| 5 | The same test | `crypt-a` was missing from the setup asset: copying the example's Assets over the scratch copy had put the old asset back | The asset is built in the scratch copy and copied back, never the other way |
| 6 | The bot trio | The score still counted an escape as 7 (six souls plus one): a lit keeper with 10 souls outscored a full escape | An escape counts every soul plus one |
| 7 | The bot trio on generated nights | Careful escaped 1 of 8: generated ghost loops were small (7 to 13 m) and everywhere, so a ghost was always near the path; the hand-made loops are big rectangles | Loop cells of 20 m and sides of at least 10 m: careful 4 of 8, then 5 of 8 with (8) |
| 8 | The bot trio | Careful lost to always-dark on both kinds of yard: it waited a minute a night with its lantern lit, giving ghosts near its path an 11 m berth | The careful bot dims when a ghost is near its next few meters too (the shared movement brain is unchanged): careful's lit waiting fell from 20 to 57 s a night to under 8 s |

**Numbers** (2026-10-23, Normal difficulty, `dev.py test` 87 passed, `smoke` 13 passed; after the first playtest's
fixes: 89 and 14, and the trio within one or two points of these)
| Over 8 nights (progress: souls, an escape counts 13, of 104) | Progress | Escapes | Catches |
|---|---|---|---|
| Hand-made yard: careful / always dark / always lit | 104 / 104 / 55 | 8 / 8 / 0 | 9 / 5 / 24 |
| Generated nights 1 to 8: careful / always dark / always lit | 89 / 81 / 38 | 5 / 4 / 0 | 9 / 3 / 27 |
- 250 night seeds: 250 different yards, 0 problems, 0 fallbacks, 24 rejected attempts (at most 4 for one yard); the
  harness: 446 of 500 seeds on the first attempt, 0 fallbacks.
- The walk grid against the real NavMesh on 9 big yards: 405 checks, looser 0 times, stricter 0 times.
- No way out: 30 pushes at the gate and out of every corner of every part of two yards, none got out.
- Difficulty on one yard (8 loops): 8, 10, 12 and 14 ghosts; ambient light 0.20, 0.09, 0.03 and 0 as set, but not as
  seen: the scene lit from the sky and ignored it (the first playtest, below).
- Soul tour as the crow flies: the hand-made yard 256 m, generated median about 275 m (the small yard: 113 m).

**Honest limits**
- Night 0 is the easy night: careful and always-dark both escape 8 of 8 there. Generated nights are the real game.
- On the big yards always-lit loses by never escaping, not by being caught twice as often as the others, so that ratio
  (asserted on the old small yard) is logged now, not asserted.
- The bots see in meters, not pixels: darkness changes nothing for them, so Hard and Insane were not measured by the
  trio, only their ghost counts and light levels. How dark is too dark is a playtest question.
- The GIF at the top of the README and the screenshots in `docs/procgen/` show the old, small yard.
- No human had played the big yards yet: the next section is what the first playtest found.

### Later: the first playtest of the big yards
The owner played the built game and reported, in one message: the title screen's letters were covered and the window
small; "narrator plays before game starts, diff levels dont actually change the global light, they are all the same, all
of them are only 12 ghosts, lantern off the legs are stuck no animation, outside the gate you fall and reset, if you get
caught on the way to an open gate you lose a soul but the gate remains open"; then "the lantern is not in his hands".
Every cause was found before a fix, most of them in the player's own log (`Player.log` keeps the game's markers).

| # | Report | Cause | Fix and proof |
|---|---|---|---|
| 1 | Small window | Not the build: screenshot runs (`-screen-width 1280 -screen-fullscreen 0`) had saved a 1280x720 window in the registry, and Unity reuses the last window over the build's default (borderless, native) | Those saved values deleted; the window is resizable and Alt+Enter switches. Capture scripts now clear what they save |
| 2 | Title letters covered | Insane's line wrapped into a one-line box; and the HUD scaled by width only, so on a 21:9 screen the menu would have run into the help text | The layout scales to fit both sides and widens instead; two-line rows. Captured at 16:9 and 21:9 |
| 3 | Narrator before the game starts | The intro was scheduled when the scene loaded, and the title screen is the same scene | Scheduled only for a real night (`GraveyardAudio.Init(..., intro)`) |
| 4 | Every difficulty looks the same | The scene's ambient mode was Skybox: Unity lit the yard from its default sky and ignored the ambient colors the difficulty set. `Smoke_L` passed because it read back the number the code had just written. Measured from the built player away from the lantern (0 to 255): 60, 51, 48, 46 | Trilight ambient set by the difficulty, sky reflections scaled with it, Easy matched to the old night by eye. Now 55, 25, 8.5, 0.9. `Smoke_L` asserts the ambient mode, not only the numbers |
| 5 | "Only 12 ghosts" | Not a bug: the log shows 8, 10, 12 and 14 on one yard. In that light, though, nobody could tell | Fixed by 4 |
| 6 | Lantern out, legs stuck | The kit's `crouch` clip is a still pose (0.17 s), played whenever he walked dark | The walk cycle at the dark speed. `Smoke_M` measures the leg swing: 120 degrees lit and dark |
| 7 | Lantern not in his hands | It hung off his root at a fixed spot, with the light above it | The `holding-right` pose on his right arm alone (a second animation layer, `CharacterAnimator.Hold`), the lantern on that arm's end, the light in its top (lower, it grazed the ground and lit a smaller pool). `Smoke_M` checks the parenting and captures a close-up |
| 8 | Caught near the open gate: a soul lost, the gate still open | The rules took the soul back but nothing shut the gate | `NightEvent.GateShut` when a catch breaks a full set; the gate swings shut until the soul is collected again. A rules test, and `Smoke_K` opens and shuts the real gate |
| 9 | Outside the gate you fall | Follows from 8: with the gate open and a soul missing, walking through was not an escape, and the grass outside had no floor | Fixed by 8, and the grass has a collider (outside the NavMesh bake) |

The lesson for the kit: a check that reads back what the code set proves the code ran, not what the player sees. The
render was measured from frames of the built player, and that is what caught it.

### Later: a second opinion from another vendor's model (Kimi K3.1 Pro)
The owner asked what Kimi could do; Moonshot had just shipped K3.1. The kit's `tools/second_opinion.py` ran Kimi Code
read-only over this game's code, tests and docs (`--model kimi-code/k3.1-pro`; the bare names in the tool's own help did
not work, which the kit then fixed). Two Sonnet agents reproduced every finding from the code before anything changed:
10 findings, 9 confirmed, 1 partly right, none wrong.

| # | Kimi's finding | Verdict | Fix |
|---|---|---|---|
| 1 | The escape counted 2.2 m from the gate point, so 3 m inside the wall and while the leaves were still swinging | confirmed | The gate must be fully open (`NightRules.Tick(..., gateOpen)`) and the keeper within 1.2 m: in the doorway, not at the start 2 m away |
| 2 | At Normal and up an extra ghost started exactly on a base ghost's corner, (13, -4) on the hand-made yard | confirmed | `Assets/Scripts/Core/GhostPlan.cs`: extras start on the corner opposite their loop's ghost; base ghosts start where they always did. A test checks every difficulty on 9 yards |
| 3 | Saving deleted the old file before moving the new one in: a crash between them lost the save | confirmed | `File.Replace` (one atomic swap); a save left only as `.tmp` still loads. Two tests |
| 4 | A bot night that hit the frame cap counted as a normal 0-soul night (and helped "lit loses" pass) | confirmed | Such a night fails the test |
| 5 | "The gate can be reached" was met by the start itself (2 m from the gate, radius 2.2) | confirmed | Fixed by 1: the check now looks 1.075 m around the gate; a sealed-gate yard fails it |
| 6 | The pinned yard prints skipped models, the outline, the gate and the start | partly (most changes move a hashed number anyway; a model swap did not) | All hashed; the four pins re-made in .NET 8 and matched by Unity's Mono |
| 7 | The broken-yard test reached only half the checks: matching the "routes:" or "reach:" prefix hid eight | confirmed | One broken yard per check (16), each matched on its own message |
| 8 | Insane kept a 4 m gate light under "pitch black outside your lantern" | confirmed | Off on Insane; `Smoke_L` asserts no light but the keeper's |
| 9 | README's "a night replays exactly" was stronger than the evidence | partly | Worded as what was checked (two seeds) |
| 10 | "No human playtest yet" stood below the owner's playtest | confirmed | Updated, with the first `docs/PLAYTEST_LOG.md` entry |

**What the fixes did to the balance.** With the extra ghosts really on the far side of their loops, Normal got harder,
most for the bot that uses the lantern: careful fell behind always-dark (hand-made 101 against 104, generated 89 against
90). The bots see ghosts in the dark, so darkness, most of what Normal adds, costs them nothing. The owner chose: the
trio's lantern tests run at Easy (the loops' ghosts, where the pillar was tuned), careful against always-dark is asserted
on the hand-made yard and only logged on generated nights, and `Smoke_N` logs both bots at Normal.

| Over 8 nights (progress of 104; escapes; catches) | Careful | Always dark | Always lit |
|---|---|---|---|
| Hand-made, Easy (asserted) | 104; 8; 4 | 104; 8; 0 | 81; 0; 19 |
| Generated, Easy (careful vs lit asserted, vs dark logged) | 98; 6; 8 | 101; 7; 0 | 43; 0; 26 |
| Hand-made, Normal (logged) | 102; 7; 11 | 104; 8; 4 | not run |
| Generated, Normal (logged) | 84; 4; 12 | 90; 5; 3 | not run |

So on generated nights a keeper who never lights the lantern does as well as a careful one, as far as bots can tell.
Whether that holds for a person who cannot see in the dark is the next playtest's question.

### Later: review fixes (2026-10-26)
A review by Fable (Claude) proved ten bugs with tests in a scratch copy (`BugHuntEditTests`, `BugHuntPlayTests`, not
shipped). Each fix got a regression test in the game's own assemblies (`CoreRulesTests`, `LevelGeneratorTests`, the new
`Assets/Tests/PlayMode/ReviewFixTests.cs`, `Smoke_K`).

| # | Bug, as proved | Fix | Regression test |
|---|---|---|---|
| 1 | A ghost near the start caught the respawned keeper every frame (35 catches, 35 souls, in a second); a tired ghost caught like any other | `GhostBrain.CanCatch`: tired ghosts never catch; `NightRules` ignores touches for `CatchGraceSeconds` (1.5 s) after a catch | `Caught_ThenGrace_...`, `Tired_NeverCatches`, `Smoke_R1` (1 catch in the second) |
| 2 | After a catch with every soul in hand the gate swung shut over 1.6 s while the keeper woke 3 m inside: holding "down", a lit keeper got out and was locked outside | `GateSwing.Shut()` closes the leaves in the same frame (and syncs the colliders) on `GateShut` | `Smoke_K` pushes through the shutting gate, lit and dark, through the game's own event handling |
| 3 | Cover that hid nothing: the sight line runs from a ghost's eye (1.3 m) to the keeper's chest (1.1 m), yet `crypt-a`, `crypt-b` (1.04 m), `gravestone-bevel` (1.06), `gravestone-broken` (0.68) and `rocks` (0.75) counted; 180 generated souls had nothing that hid them | `Footprint.IsCover` is height-based: measured mesh tops (`Footprint.Height`) at least `ChestHeight` | `Cover_IsOnlyWhatReachesTheKeepersChest`, `Heights_MatchTheMeshes`, `Smoke_R2` (a hugging keeper is hidden from 2, 4 and 7 m by every cover model) |
| 4 | No save file (save.json, written at runtime) and a broken `.tmp`: Load copied the missing save file to `.bad` and threw, a black window on every launch | The file actually read is kept as `.bad`, a broken `.tmp` removed; setting aside never throws | `Load_ABrokenTemporaryFileAndNoSave_...` |
| 5 | `SetDestination` every frame restarted a path that takes more than a frame to compute: a hunting ghost stood still; a search for a spot off the NavMesh never ended | `GhostAgent.Drive` re-paths only when the destination moved 0.25 m or there is no path, never over a pending one; `SearchMaxSeconds` (12 s) ends any search | `Smoke_R4` (old code, measured: 0.0 m in 3 s; now 10.3 m), `Search_GivesUp_...`, `Smoke_R3` (gives up at 12.0 s) |
| 6 | `Area.Contains` was open on both sides: a seam between two areas belonged to neither | Half-open (min edge in) | `Inside_OneMeterFromAnInteriorSeam_IsInside`, `Area_IsHalfOpen_...` |
| 7 | The property test's "0 problems" could not fail (Generate only returns yards that pass) | It now checks the raw attempts: every reject names a real invariant and attempts = rejects + 1 | the property test itself |
| 8 | The extra ghosts' loop order came from a float sum: ties could swap between runtimes | `GhostPlan.LengthKey`: length in whole 1/16 m (summed in double), then index; the Normal plan is in the pinned prints | `GhostPlan_RanksLoopsByAnExactKey_TiesByIndex`, the pins |
| 9 | `--autoplay` runs advanced the player's own save (nights played, so the next yard) | Bot nights never write the save | `Smoke_R5` |
| 10 | README durations and "98 pairs" were stale | Corrected (106 pairs since the buildings) | |
| 11 | Found by the fixes: the new night 3 (seed 55875) had a ghost corner in a sliver between three props that the walk grid kept open and the NavMesh bake closed (no NavMesh within the 0.8 m arrive radius); `Smoke_E` caught it | Loop corners snap only to cells with open ground 0.25 m all round (`LevelGenerator.CornerOpen`, `WalkGrid.ReachableAround`). A first try, 1 m from every prop, failed the hand-made yard and made 295 rejects; it was dropped | `GeneratedGhostCorners_StandInOpenGround`; `Smoke_E`: 405 checks, looser 0, stricter 0 |

**Every generated yard changed** (fixes 3, 6 and 11), on purpose: the four pinned prints were re-made in .NET 8 (a
scratch harness compiling the game's Core files with Unity's bundled SDK, first checked to reproduce the old pins) and
match in Unity's Mono. Property test: 250 yards, 250 different, 0 problems, 0 fallbacks, 26 rejected attempts (all
"room"; 24 before), at most 3 attempts. The hand-made yard is unchanged. The pictures in `docs/procgen/` show yards
from before these fixes (and before the 4x yard).

**The trio** (Easy, 8 nights each; progress of 104; escapes; catches):
| | Careful | Always dark | Always lit |
|---|---|---|---|
| Hand-made, before | 104; 8; 4 | 104; 8; 0 | 81; 0; 19 |
| Hand-made, after (two runs of the same code) | 104; 8; 5 and 103; 7; 8 | 104; 8; 0 | 86; 0; 12 and 86; 0; 14 |
| Generated nights 1 to 8, before | 98; 6; 8 | 101; 7; 0 | 43; 0; 25 |
| Generated nights 1 to 8, after (new yards) | 96; 5; 23 | 103; 7; 6 | 41; 0; 13 |
| Normal, logged, hand-made / generated, after | 102; 7; 11 / 81; 3; 17 | 104; 8; 4 / 88; 3; 13 | not run |

The pillar holds on both kinds of night: careful escapes 8 (or 7) and 5 of 8, always-lit 0, and careful beats lit by 18
and 55 (`Smoke_D` and `Smoke_I` want 10). Always-lit is caught less on the hand-made yard (12 against 19): the catch
grace and tired ghosts end the repeat catches it used to collect. On the new generated nights careful is caught much
more (23) and always-dark edges it (103 against 96, logged, not asserted, as before).

**Honest limits**
- `Smoke_D` asserts careful >= always-dark on the hand-made yard, where both sit at the 104 cap. In one full smoke run
  careful made 103: night 4 ended at dawn with all twelve souls after four catches. The same code then escaped night 4
  at 177.2 s with one catch (as before the fixes) and passed. So `Smoke_D` can fail on run-to-run variance, which
  the procgen section's "Honest limits" already noted for the trio **(verify the cause)**. Not re-tuned: that is the owner's call.
- Careful's 23 catches on the new generated nights were not investigated beyond the totals.
- The built player was not rebuilt or replayed after these fixes, so the "replays a test night" claim (seeds 6 and 6258)
  is from before them **(verify)**.

## 9. Outside the kit (be honest)
- The Behavior package was installed only to read its source (gap U3), then removed.
- `GRAVEYARD_TRACE=1` logs (the bot's position, decision and the nearest ghost twice a second) did the tuning; they
  stayed in the test as an option.
- One human playtest so far, the owner's ("Later: the first playtest of the big yards"); nobody else has played it,
  so pillars 2 and 3 stay open in `docs/VERTICAL_SLICE.md`.

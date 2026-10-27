# How Rune Delve was made

The kit's Unreal Engine 5 example, and its fifth "only what is in the kit" run (after ghost-lantern, courier-dash,
scrap-tanks and graveyard-shift). One Claude Code session (Claude Opus 5.5) on Windows 11 with Unreal Engine 5.8.4 and
Visual Studio 2022 Build Tools, 2026-10-22. The owner picked the concept; Claude did the rest by following the kit's
documents and tools, without opening the Unreal editor's UI, and recorded every place the kit fell short. Each gap was
fixed **in the kit** and pulled in with `new_game.py --upgrade`.

## The rule
Allowed: what a kit user has after scaffolding (docs, SOPs, skills, `tools/`, the Unreal overlay), the sources the kit's
resource lists name, and engine plugins the kit's docs point at. Not allowed: outside scripts or tools. Exceptions are
listed at the end.

## 1. Project, adopt, first build (FIRST_HOUR)
Unreal is adopt-first (`docs/ENGINE.md`). Without the editor UI the project is a hand-written `.uproject` (with the
GameplayAbilities, EnhancedInput and PythonScriptPlugin plugins), two target files, a `Build.cs` and a module file,
at a short path because UnrealBuildTool breaks on long Windows paths. **Kit gap R5:** the generated README called it
"a Unreal Engine 5 game"; the template now reads "a game made with <engine>".
```
python scripts/new_game.py --name "Rune Delve" --engine unreal --dest D:/kt/rd --adopt --git-init
python tools/dev.py doctor && python tools/dev.py check        # compiled in 95 s
```

## 2. Concept, the spike that decided it, and the GDD
Claude offered three Unreal concepts built on parts no example had used; the owner picked "Rune Delve" (the Gameplay
Ability System, AI Perception, the NavMesh, Enhanced Input). Before designing, a 50-second spike answered the one
question that could sink a code-only Unreal game: can a headless editor import FBX and make a map? It could: Interchange
turned a Kenney FBX into a static mesh, an animated one into a skeletal mesh with 34 animations, and a map saved.
**Kit gap R1:** the Unreal `dev.py` had no way to run editor Python. Fixed: `dev.py exec <script.py>` (the
`pythonscript` commandlet; the script's prints are shown and a traceback fails it, exit 1), plus a "Content from scripts"
section in the Unreal flow guide.
The GDD got three pillars: **timing beats spam**, **read the orcs**, **one more delve**.

## 3. Assets
```
python tools/fetch_asset.py --url <mini-dungeon zip> --page https://kenney.nl/assets/mini-dungeon --author Kenney \
  --license CC0 --type 3d --base "Models/FBX format" --take "Models/FBX format/*.fbx" --take "Models/FBX format/Textures/colormap.png" \
  --to assets_src/mini-dungeon
(nine sounds the same way from Sci-fi Sounds, Impact Sounds and RPG Audio into assets_src/audio)
python tools/dev.py exec tools/unreal/build_content.py     # 120 assets in about 15 s, and the map
```
`build_content.py` prints every prop's size, so the C++ layout uses measured numbers: Kenney Mini Dungeon tiles are
100 cm, characters 78 cm tall and facing along Y. Two more probes with `exec` measured the characters and found the
gate imports as a skeletal mesh with its own animation.

## 4. Slice brief and ADRs
`docs/VERTICAL_SLICE.md`: three rooms, three spells, grunts and a warden, gates, no saves or music. ADR **0001** GAS all
in C++ (abilities, effects, attribute set, native tags, numbers as SetByCaller from the ini); **0002** AI Perception
and a runtime NavMesh; **0003** content from a headless script and the level from C++ data.

## 5. Build (SOP-01, then SOP-14 through `/game-ai`)
- **Engine-light core first, with tests:** combat rules, the orc FSM, the level data, the two bots. The first test run
  failed two checks that were wrong, and one taught something: a "ward outlasts the wind-up" rule was the wrong rule
  (the ward must be up when the swing lands, not last longer), so the test now checks that every wind-up is long enough
  to react to. **Kit gap R2:** the Unreal flow guide's test macro used `EAutomationTestFlags::ApplicationContextMask`,
  which no longer compiles (since 5.5 it is the free constant `EAutomationTestFlags_ApplicationContextMask`). Fixed.
- **Tunables in the ini only:** `URDTuning` (a `UDeveloperSettings`) has no C++ defaults, so the game and the tests
  read the same numbers from `Config/DefaultGame.ini`. This is the Unity example's lesson (kit gap U5) applied up front.
- **GAS from code:** the 5.8 API (effect components, `DynamicGrantedTags`, `AddBase`, `InstancedPerActor`) was read
  in the engine source before writing; one timed effect with a dynamic tag serves every cooldown, the ward, the stagger
  and the dash. The whole game compiled on its first full build after two missing includes.
- **Smoke tests in Play In Editor:** the boot test passed at once; the bot pair hung. **Kit gap R3:** `AutomationOpenMap`
  called inside a latent command queues its "start PIE" step behind every later command, so each run waited forever.
  Fixed in the game (request PIE directly) and written up in the Unreal flow guide.
- **Kit gap R4:** the Unreal `smoke` had none of the scenario options the other overlays have. Added `--filter`,
  `--until` and `--fail-on`; capture stays a game option because tests run without a renderer.

## 6. The bot pair, and how it shaped the numbers
`RuneDelve.Smoke.Pair` plays the **weaver** (wards only when a swing will land inside the ward, keeps mana for it) and
the **masher** (casts everything the moment it is ready) over 8 seeds. One movement brain, so the spell policy is the
only difference. Progress per delve: kills (8) plus 2 for a full clear.
| Round | Weaver | Masher | What it showed | Change |
|---|---|---|---|---|
| 1 (1 seed) | 4 kills | 3 kills | the ward (0.9 s) outlasted the wind-up (0.6 s): a ward raised early still blocked | ward 0.45 s inside a 0.7 s wind-up, ward cooldown 2 s |
| 2 | 41 | 23 | the pillar holds, but nobody cleared a delve | grunts weaker, mana regen and room-clear heal up |
| 3 | 62 | 56 | both reach the warden; the warden stops both (weaver 2/8 clears) | warden 180 health, longer recovery |
| 4 | **71** | **55** | full clears 5/8 against 0/8; the masher's wards met no swing in any run | the test asserts a gap of 10 and 3 more clears |
The masher loses for the reason the pillar names: bolting every 0.4 s drains the mana the ward needs.

## 7. What the kit's checks caught
| Caught by | Problem | Fix |
|---|---|---|
| The core tests | A wrong rule (ward must outlast the wind-up) | Test the telegraph length instead |
| The boot smoke test | An assertion that ignored fast time (the room fights at once) | Removed; boot checks spawns and the NavMesh |
| The bot pair | Pillar 1 hollow as tuned (round 1) | Ward window inside the wind-up |
| `-record` frames from the packaged game | Dead orcs standing upright; an opened gate drawn shut | Corpses vanish; open gates are hidden |
| `dev.py check` | Two missing includes | Added |
| Reading the code before compiling (not a tool) | A member function called `Cast` would have hidden Unreal's `Cast<T>` | Renamed `CastSpell` |

## 8. Verified
| Check | Result |
|---|---|
| `python tools/dev.py check` | compiles (95 to 150 s from clean, seconds after) |
| `python tools/dev.py test --filter RuneDelve.Core` | 5 test groups pass |
| `python tools/dev.py smoke` | boot plus 16 bot delves pass in about 2.5 minutes; without content they stop in 20 s with "run build_content.py first" |
| `python tools/dev.py package` | a Windows Development build in about 4 minutes |
| The packaged game, `-autoplay=weaver -seed=4 -fixedfps -quitatend` | `DELVE_COMPLETE`, exit 0, the same delve as the smoke test: 30 bolts, 8 wards, 9 blocks, 54 damage (40.1 s against 40.0 s). A first comparison seemed off; it compared two different builds (`docs/TROUBLESHOOTING.md`) |
| The README steps in a fresh copy inside the kit repo | found three more gaps, all fixed: content before compiling cannot work (**R6**: `dev.py` now says "run check first", exit 2); a space in the path turned the script path's backslashes into escape characters (**R7**: forward slashes); the characters loaded their meshes in C++ constructors, which run before a fresh clone has content, so every editor command logged errors (**R8**: load in `BeginPlay`, Unreal gotcha 12). The smoke tests now stop at once when the map is missing |

### Later: generated sound (ElevenLabs)
The owner asked for API audio in the other example games (2026-10-23), after Graveyard Shift had it. The Kenney sounds
were replaced by sound effects generated with the kit's `tools/audio/eleven_audio.py`, plus an ambience loop the game
never had. Free plan: every file is PLACEHOLDER in `docs/ASSET_LOG.md` (non-commercial, credit in the README); the old
Kenney rows stay, marked removed. Every file was measured before use (peak, loudness, silence at the start, the jump at
a loop's seam, flat-topped samples), then peak-normalized: one-shots to -3 dBFS, loops to -6 (the log says Modified, the
evidence file keeps the shipped file's SHA-256, the `.gen.json` next to it the generated one).

Before, one Kenney file did two jobs (`cloth1` was both the mage's dash and an orc's swing; one punch was both an orc
noticing you and an orc getting hurt). Now every event has its own sound: `bolt-cast`, `ward-raise`, `mage-dash`,
`mage-hurt`, `ward-block`, `orc-alert`, `orc-swing`, `warden-swing`, `orc-hurt`, `orc-die`, `door-open` (mono WAV, played
at a location) and `dungeon-ambience` (a 2D loop the dungeon starts when it builds).
- `build_content.py` now sets the loop flag on `*-ambience` waves and deletes any `/Game/Audio` asset whose file is gone
  from `assets_src/audio` (it removed the nine Kenney assets). Hyphens in names survive the import.
- What the measurements caught: the first orc alert had 4% of its samples flattened at full scale (audible distortion),
  the orc death 1%; both retaken ("not distorted" in the prompt) and clean.
- Cost: 237 credits with the retakes. Verified: the content script logged every sound and the loop, `check`, 7 tests,
  2 smoke tests.

### Later: review fixes (2026-10-26)
A code review (Claude Fable 5.1, with PIE probes in a scratch copy) found eight defects; Claude (Opus 5.5) fixed them
and turned the probes into tests. Each fix was checked by reverting it: on the old code every stage of the new
regression test fails.
| Severity | Defect | Fix | Checked by |
|---|---|---|---|
| High | Being hurt woke an orc only if the mage stood in its room: sleeping orcs (the warden too) could be shot dead through an open gate | A hit always wakes the orc; the room gate stays for sight and hearing | `Smoke.Regressions` (doorway) |
| Medium | The ward blocked every swing in its 0.45 s window, though the GDD says one | A block removes the ward | `Smoke.Regressions` (ward) |
| Medium | The hit landed on the first frame of the attack clip, after a still wind-up pose | The clip starts `ARDOrc::ContactDelay` (0.25 s, measured from its bones with a throwaway `exec` probe) before the hit, so its contact frame meets the damage; hit timing and the bots' ward timing are unchanged | `Smoke.Regressions` (swing: clip at 0.250 s when the hit lands) |
| Low | The warden spawned on a grunt's tile for 24 of seeds 0..199 | Grunts skip its tile; draws keep their order, so other seeds keep their layout | `Core.Level`, now 300 seeds |
| Low | Dash length depended on the frame rate | Step by min(frame, time left); the dodge tag follows the slide | `Smoke.Regressions` (dash: 650.0 cm; old code 638.5) |
| Low | The bolt blocked its caster: a dash behind a fresh bolt hit it | The mage ignores its own bolts when moving | `Smoke.Regressions` (dash behind a bolt) |
| Low | The bots saw orcs by spawn room | By the room or doorway the orc stands in (`FRDLevel::GateOf`) | `Smoke.Pair` |
| Low | README: "Fall and the delve starts over" | It stops; R starts again | |

The bot pair, old code (the reviewer's untouched copy, which reproduced the recorded 71/55) against new:
| Seed | Weaver before | Weaver after | Masher (same before and after) |
|---|---|---|---|
| 0 | clear, 9 wards, 11 blocks, 108 damage | 7 kills, 9 wards, 8 blocks, 198 damage | 7 kills |
| 1 | clear, 10 wards, 11 blocks | clear, 10 wards, 10 blocks | 7 kills |
| 2 | 7 kills, 8 wards, 9 blocks | 7 kills, 9 wards, 9 blocks | 7 kills |
| 3 | 7 kills, 8 wards, 8 blocks | the same | 7 kills |
| 4 | clear, 8 wards, 9 blocks, 54 damage | 7 kills, 6 wards, 6 blocks, 144 damage | 7 kills |
| 5 | clear, 9 wards, 10 blocks | clear, 9 wards, 9 blocks | 6 kills |
| 6 | clear, 10 wards, 10 blocks | clear, 10 wards, 10 blocks | 7 kills |
| 7 | 7 kills, 9 wards, 10 blocks | 7 kills, 9 wards, 9 blocks | 7 kills |
| Total | **71**, clears 5/8 | **65**, clears 3/8 | **55**, clears 0/8 |
Before, the weaver blocked more swings than it raised wards on 6 seeds, the two that lost their clear (0 and 4) among
them, so the multi-block ward is the likely cause (not split out fix by fix). The pillar holds, but the pair test's checks (a gap of 10, 3 more clears) now pass with no margin; nothing was
retuned. The masher never blocks, so its runs did not change at all. Verified: `check`, `test --filter RuneDelve.Core`
(5 groups), `smoke` (boot, regressions, 16 delves, 3.5 minutes), `package`, and the packaged weaver on seed 6
(`DELVE_COMPLETE`, 44.6 s against 44.5 s in the smoke test, the same counts). Found on the way: the packaged replay only
matches with a renderer (`-nullrhi` plays a different delve, `docs/TROUBLESHOOTING.md`).

## 9. Outside the kit (be honest)
- Three throwaway `exec` probes (asset sizes, animation names, the gate) were deleted after use; what they found is
  in `build_content.py` and the code.
- The review fixes used one more throwaway `exec` probe (the swing clip's bone poses, for `ContactDelay`) and ran the
  old-code bot pair in the reviewer's scratch copy outside the repo; neither is kept.
- A first guess (the runtime NavMesh) for a replay mismatch was wrong: the builds differed. Recorded so nobody repeats it.
- No human playtest yet: whether a 0.45 s ward window is fair by eye is the first question (`docs/VERTICAL_SLICE.md`).

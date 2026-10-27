# Field reports (verbatim archive)

> The long "data point" write-ups, moved unchanged from the pre-distill `RESOURCES.md` (2026-10-19). IDs: RemakeBench E19, Viral Echoes E20 and E21, RandomAI E24, Stefan 3D AI 36-hour run E25, Scuppy E26, Brendan Jowett E27. The rules distilled from these are in `docs/EVIDENCE.md` (findings the F rows of `docs/EVIDENCE.md`).

## What AAA-looking output actually costs (claimed, RemakeBench video)
Answers "why does Opus on max look AAA?" Reported results from one tester, one request per run, no human follow-up. Treat every number as his claim, not a promise.
| Scene (static unless noted) | Reported time / cost | What he said |
|---|---|---|
| Off-road truck (interactive) | Opus 5 about $124 (GPT-5.6 Sol about half the time, far cheaper; Kimi K3 3h50m, about $29) | Opus truck had invisible tires and doors, obstructed cockpit camera, tends to catapult. Neither Opus nor Sol was a good one-shot. |
| Space flight stage 2 (interactive) | about 2 h for Claude models; Sol 1h29m, about $21; Kimi about $16 | Opus planet flickered. Fable ship faced down on takeoff. Both fixable if the model had screenshotted the launch sequence. |
| Neo-gothic flooded city | Opus cost more than Fable on max | Matter of taste. Opus had more detailed structures and more realistic water. |
| Infinite cathedral | Opus took about 3x Fable's time | "One of the best results I've seen for this test." Strongest visual round. |
| MacBook Pro | Opus about $27 vs Fable about $75, 6 minutes longer | Opus cheaper here. |
| JRPG boss battle | Opus much cheaper than Fable max | Nice magic animations and cinematic camera, backdrop cut off at the top. |
| Jungle temple | Opus about 4x Fable's cost | "Fantastic", coherent, no major flaws. |
| Oasis outpost | Opus longest of all | More detail, too dynamic a landscape. |
| Shrine exploration (interactive, long horizon) | 7h41m (he stopped it), parent cost "$24+" per caption, 7 sub-agents used 1.89M tokens, parent processed 327M tokens | Judge scored 14/40 after two review and revise rounds. Flaws: animations, character model, collisions. |
Takeaways:
- Static scenes at max effort can look great. The interactive layer (animation, collision, character quality) is where it falls apart.
- His observed trend: best creative output comes from runs of 6+ hours, some people run 24 hours. You pay in time and money.
- The same task can be 4x the cost on one model and cheaper on another. Pick per task, measure cost per good result.
- **RemakeBench** (remakebench.com, per the video): a harness plus assets, tools, skills and prompts under "builder access" so you can replicate runs; frozen prompts per task; an independent LLM judge scores results (the shrine run got 14/40). Not opened by me. Worth a look for prompts and scoring rubrics to copy.

**Second data point: "Opus 5.5 In Unity 6 Is ABSURD" (Viral Echoes, claimed).** Same pattern, bigger hype.
- Recipe he used: (1) ask a cheaper Claude model to write the big prompt ("make X from scratch, I want it to look AAA"); (2) attach several reference screenshots of the target so Claude sees the look; (3) tell Opus to do its own research; (4) Opus at extra-high effort with Unity and Blender both connected; (5) one run per game.
- Reported results: main menus, settings, loading screens and a tutorial boss done "one to one"; a polished Subnautica-style opening room, scanner and fabricator; an Elden Ring-style golden tree, cape cloth, rolls, particles.
- Reported flaws (his list, same shape as the RemakeBench findings): floating tree, goofy character and horse models, bridge does not react to steps, character catching on tile gaps, night water looks wrong, underwater is pitch black, biome blending rough, one fuse box animation weird.
- Pattern to copy: **reference screenshots in the brief**, ask the model for the brief first, and judge the menus/UI/environment separately from the interactive parts.
- Do not copy: cloning a commercial game's name, UI, art and assets for something you plan to release. He removed the "IP rules, non-negotiable" line Claude put in the prompt and said the model otherwise ignored it. Use the look as an exercise, then make original work. See `SOP-04`.

**Third data point: PUBG-style shooter, Sol vs Opus 5 (Viral Echoes, claimed).**
- Fair-test trick worth copying: have a third model write the shared brief (he used Gemini 3.1 Pro), then give the identical prompt to each agent in a fresh session.
- Sol (Codex, about 30 min): menus, weather, map, vehicles and a minimap, but no collision (walked through buildings and a bridge), invisible player model, a hotkey that did nothing, frame rate collapsing to 1 and then 0 FPS.
- Opus 5 (extra high, about 16k lines of TypeScript, hit the session limit partway): much better first impression. Time-of-day and weather options, bot count slider, terrain you can walk on, fall damage, killfeed, vehicles, respawn, inventory. Flaws: held weapon not visible, stuck in a building, heavy fog washed everything out, vehicle exit key did nothing, ran hot on his PC.
- His verdict was "better than most basic Unity games" for Opus. Same split as the other two videos: polish and scenery good, interaction details broken.

**Fourth data point: three one-line-prompt clones (RandomAI, claimed).**
- Prompts were as short as "make a clone of Black Ops 2 and make it very insane". Effort "ultra" for the first, "extra" for the rest because ultra eats rate limits (his words).
- Geometry Dash style runner: about 1h20, fun, three difficulty modes, sound and music working.
- Rocket League style: about 130 minutes, over 100k tokens; looked as good as a viral Fable 5 version but cars flipped constantly, camera poor, garage menu dead, no audio at all. He called it one of his first truly bad Opus 5 results because the core feel was not fun.
- Shooter: firing range and team deathmatch worked (solid gunplay, reload, hit reactions, respawn). The third mode had enemies shooting through walls and bad music. He scored 7/10.
- Same lesson again: menus, visuals and basic loops are easy; **feel** (vehicle handling, camera), audio, and line-of-sight rules are where it breaks. Put those in the vertical-slice tests.

**Fifth data point: 36-hour autonomous MMO run (Stefan 3D AI, sponsored, claimed).**
| Item | Reported |
|---|---|
| Model and effort | Opus 5.5, ultra |
| Wall clock | 36 h billed as running time, about 30 h real because the laptop crashed overnight; the agent resumed from its own notes |
| Tokens | about 7.85 billion, nearly all cache reads |
| API-equivalent cost | about $2,200 (title says $2,175) |
| His real cost | 100% of one weekly limit on his subscription (plan not clearly stated) |
| Asset credits | about 7,000 Higgsfield credits: roughly 300 Tripo 3D models and 600 images including tile textures, plus some music, animation and video |
| Prep by the human | a few hours of research, hundreds of generated reference images (picked down), a design doc, interface sketches, and his own skills (for example, build characters in parts, assemble in Blender) packed in one archive |
| Agent behavior | about 10 parallel agents, gray-box first, played its own game and iterated, screenshotted milestones into a progress journal |
| Output | 6 races, 2 genders each, customization, 4 zones, a city, quests, spell bar, trailer, loading screens, music, debug/god mode |
| Flaws he named | hands holding items, staff through the head, animations, a broken bridge, collider problems, odd targeting, shallow quests and combat, "too perfect" city |
His own conclusion: execution is impressive, but making a game people want to play still takes human taste and effort.

**Sixth data point: Roblox game in about 3 hours (Scuppy, claimed).**
- Setup: Claude Code with Opus 5.5 at extra effort, connected to Roblox Studio through an MCP (open Studio first, then connect). He gave a detailed plain-language description but no reference images.
- What it produced from that: Blender-made models (taxi with interior, props, buildings, night monsters), gameplay scripts, a lobby shop, UI, loading screen, radio stations, a day/night cycle with random events, a Robux store with boosts, a reward system.
- Loop that worked: play, screenshot, give feedback in plain words ("make the interior better and the UI look like a billion dollar company made it"), and send the screenshots back. New ideas typed mid-run were picked up by the agent, which he found surprising.
- What went wrong: after about 1.5 hours he realized the game did not match the vibe in his head (he then asked for a random-highway structure like Dead Rails or A Dusty Trip), so early references would have saved time. Also flaws: odometer on the wrong side, weak grass physics, too many trees in the random map, flat tires from potholes too often.
- Limits and plan: he reported 68% of a weekly limit after 1.5 hours and a hard limit after two, then bought a bigger plan and kept going. Same warning as the 36-hour video.
- Claude could not click through publishing, so he published from Roblox Studio himself. The thumbnail Claude made was bad: use a real image generator for key art, and Claude for the brief (`docs/BRIEFS.md`).
- If you adopt Roblox for real: add an ADR, check Roblox's current rules on monetization and AI content, and build an overlay (`engines/_template/`). **(verify)**

**Seventh data point: Unreal Engine 5 tactical FPS in one prompt (Brendan Jowett, claimed, has affiliate links).**
- Planning that worked: ask for five concepts that suit the engine and visual target, pick one, ask for a deeper design pass (graphics, mechanics, enemies, night vision, destruction), review it, then send the build prompt. He noted he should have named Unreal and Blender in the first message.
- Tell Claude your hardware (he said "4080 Super, push the graphics hard") or ask it to read your PC specs, and it will size the graphics to fit.
- No MCP: he says Claude found the installed Unreal and Blender and drove them from the command line. Unverified here.
- He switched to the "bypass permissions" mode so it would not stop to ask, because he expected an hour or more. It ran about 4 hours and used about 19% of his weekly limit on a Max plan (7% to 26%). Safety note added to `SOP-07`.
- Result: a polished title screen, loadout screen (buttons did nothing), working graphics settings, mission select, one playable mission, ragdolls, bullet holes, dust. Visual effort went into one arena; the surrounding city was cut off or low quality; enemies were too aggressive. His own lesson: next time build one feature first, not the whole game.
- Credits screen listed "Claude / Anthropic" as the developer, a reminder to fix `CREDITS.md` and the legal name before shipping.
- Hardware reality: Unreal at this fidelity needs a strong gaming PC and about 50 GB of install.
- Tip: he dictated prompts by voice in the Claude app, handy for rambling creative briefs.

## Notes moved out of the SOPs during the distill (2026-10-19)
> Kept for the record. The rules they support are in the SOPs now.

### From SOP-11: Blender MCP recipe (E12)
- **Blender MCP recipe (from a short demo, unverified):** open Claude Code and Blender side by side, paste the MCP repo link, ask Claude Code to set it up, then iterate in plain prompts: make the object, remove the default cube, center it, add ground, fix lighting (sun and sky, correct overexposure), scatter variants. A 2D reference screenshot can drive a whole scene. To keep this repeatable, tell Claude to **save every bpy script it runs into `tools/blender/`** and export final assets as glTF. A scene that exists only in a live Blender session cannot be rebuilt.

### From SOP-11: What the agents did well and badly (one creator's comparison, unverified)
Reported from side-by-side runs of two frontier agents building scenes procedurally in Blender (`docs/evidence/video-notes.md`, "Opus 5.5 vs GPT-6 Astra" row, E14).
- **Good:** procedural scenes from primitives and splines, symmetrical hard-surface objects (a galleon), VFX sequences rendered in a browser page with Three.js (magic circle, fireball, leaves), creature rigs with walk and attack cycles, a playable single-file HTML 3D game. Time lapses of the build were requested and were useful for review.
- **Bad:** **UV unwrapping.** Both agents produced tiny islands, wasted texture space, and unusable layouts, even with vision. Do not accept AI UVs without a check.
- **Weak spots to expect:** jump animations (both legs at once, wrong arcs), clipping, details that feel thin, models positioned off-origin.
- **Cost and time are real:** the creator reports runs of 20 to 100 minutes and roughly $10 to $25 each at max effort. Use medium effort for iteration.

### From SOP-11: Self-check views and the static vs interactive gap (RemakeBench video, claimed)
- **Vary the camera when Claude checks its own work.** The tester saw an Opus-built truck with invisible tires and doors because every self-check screenshot came from the rear view. Tell the agent to render front, side, rear, top, three-quarter, and a close-up of any moving part, and to list what it saw in each.
- Same for sequences: screenshot the first frame, middle, and last frame of takeoffs, landings, attacks. A ship that launches pointing down is obvious in one frame.
- **Expect the split.** Models are strong at static environments and weak at the interactive parts: character animation, collision, vehicle physics, character model quality. Spend your human review time there.
- Run animation-heavy assets through the exam in `SOP-09` instead of trusting "looks fine".

### From VERTICAL_SLICE: Answering Claude's clarifying questions fast
In a recorded Ep. 3 run, Claude came back with about eight design questions (weapon, boss, health display, puzzle, death, hero name, controls). The creator's advice, which fits this kit:
- Do not stall on them. It is a prototype, the answers only need to be good enough to test the thesis.
- Say "use your best judgment" wherever you do not care. Only be precise on what the test depends on (for example, controls).
- Keep a literal placeholder interpretation (for example, "a room's puzzle is defeat all enemies, a key drops") and deviate later.
- **Watch the death default.** He answered "reset the whole prototype on death" and then regretted it in play. Prefer "restart the current room/dungeon" unless the death rule is part of what you are testing.
- Controls matter: spell out keys and gamepad mapping, since those are what you will feel immediately.

### From VERTICAL_SLICE: First build review (what to expect)
Reported from the Ep. 3 run (Opus medium, took over 30 minutes, asked permission a few times to run programs locally):
- Claude ran the engine itself, played through, and saved screenshots. It also wrote what is built, how to play start to finish, and a list of what to test first (enemy readability, boss tells, gate payoff, a 10 to 15 minute length target).
- Crude placeholder art and code-made sound effects are normal here.
- Typical first-pass problems seen: enemies too tough or sponge-like, no heart/health drops, a weak puzzle (push block), death sends you too far back, ability to test later (dodge roll with diagonal movement felt good unexpectedly).
- Take notes while you play (pen, notepad, or record your screen). Then turn them into tasks with `/playtest-report`.
- Godot capture quirk (creator's report, **verify**): recording the game window did not work while the project ran in windowed mode. Set Project Settings > Display > Window > Mode to fullscreen to capture. On Windows, Win+G opens the Game Bar recorder.

### From VERTICAL_SLICE: Integrating generated art and audio (Ep. 4 pattern)
1. Make one folder: `assets/art/` (sprites by type: hero, enemies, npcs, tiles, props, ui), `assets/audio/music`, `assets/audio/sfx`.
2. File names must match the prompt pack so Claude can wire them without guessing. Run `tools/art/chroma_key.py` first on magenta-background sprites.
3. Log everything in `ASSET_LOG.md` (tool, plan, date, prompt). Do `/asset-intake` on the batch.
4. Hand Claude the folder, or in a chat-only flow zip it (the series used 77 MB) and re-extract the rebuilt project over the same folder. In Claude Code just drop files into the repo and ask for integration.
5. Expect a 25 to 35 minute rebuild in chat. Read the summary Claude gives: judgment calls and things to check.
6. **Playtest immediately.** Typical post-integration breakage reported: walk animation wrong, roll animation missing, weapon sprite clipping into the tile layer (needs draw order/layers), drab tiles needing a screen-by-screen redesign, flat props with no shadows, push and enter-building animations missing, boss defeat animation firing at the wrong moment, difficulty still too high.
7. Write the notes as a list and send them back. Mechanics notes and art notes can go in separate rounds.

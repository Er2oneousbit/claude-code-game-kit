# Pipelines from creators (worked examples)

Whole workflows other people reported, kept as worked examples. Rules distilled from them live in the SOPs; grades in `docs/EVIDENCE.md`.

## Creature animation pipeline (claimed, E02)
Idea: Mixamo and mocap cover humanoids, so for monsters generate reference motion with a video model, track every joint per frame, and retarget onto the monster's rig.
```
concept image -> 3D model (Tripo) -> skeleton (UniRig) -> motion video (Seedance)
   -> per-frame joint detection (fine-tuned DINOv2) -> retarget in Blender -> export -> engine
```
- The creator reports earlier approaches broke (point tracking, segmentation outlines, depth maps, animal pose models), and that treating it as "find every joint in every frame" worked.
- Reported result: manual frame checking took days, the automated tool takes minutes.
- A test "exam" re-ran after every change to keep the tool honest (see `SOP-09`).
- **Limits stated in the full video (transcript read):** Seedance never makes the same video twice, so separate front and side videos never match. If the two halves of one picture show different moves, the tool can follow only one, so the tool checks the video first and a new generation is faster than fixing it. A hand hidden behind the body is still a guess. A depth model can say which leg is nearer but not exactly how far, so it cannot replace the second camera yet.
- **Methods that failed for him, in order (useful so you do not repeat them):** keyframes written by code (blocky); code walk on a better Tripo model (still not animal-like); matching a filmed AI video by silhouette (legs cross from the side, depth is guessed from a flat video, needed hand fixes per frame); point tracking from Google DeepMind (points slide up onto the body); SAM 2 outlines (far legs vanish in runs, colors swap); a single-image depth model (right only 4 times in 10 on near vs far leg, legs 10 cm apart); painting each leg a different color (worked until Seedance did not keep the paint, and does not scale to wings or six limbs); animal pose detectors (far legs drawn on the belly); MoCapAnything (ran in place, animals only).
- **What worked:** (1) skeleton with UniRig, try several, keep the best by checking against the mesh (every grounded leg needs a bone, left and right match), fold fingers into hands, trim bones outside the body; (2) Seedance with TWO cameras (front and side) in one picture so a joint lies at the crossing of two lines; (3) per-creature joint detector: fine-tune DINO on about 3000 renders of that creature in random legal poses from both cameras, half of them motion-blurred and degraded like Seedance output, about 30 minutes on his GPU; (4) the exam: invent a random legal motion, film it in the same two-camera studio, compare the tool's joint answers to known truth bone by bone, every tool change and every new monster must pass first; (5) triangulate, apply to skeleton, export to Blender and the game.
- **Claimed payoff:** one troll went from about four days of Opus checking every frame, with many tokens, to a few minutes per clip after a one-time per-monster training. Examples shown: lizard, wraith, wolf, troll, with legs, wings, tails, a sword. He also names Mixamo and Kimodo as the humanoid motion options.
- Use for: monsters, creatures, animals. Humanoids: Mixamo-style retargeting is simpler (`SOP-11`).

## Prototype with Claude first, art and audio after (claimed, E07 to E10)
```
Claude one-shots a playable slice with placeholder shapes -> playtest and fix the design
   -> generate art (portraits, sprites, tiles, UI) with an image tool, audio with SFX/music tools
   -> iterate prompts (first sprite sheet failed, about two days of passes)
   -> organize everything into ONE assets folder -> hand to Claude to integrate -> playtest, fix breakage
```
- Matches this kit's rule: prototype first, refine later (`SOP-01`). Art and audio come after the loop is fun.
- Reported asset volume for one pass: portraits with emotions, sprites, tile sets, title screen, NPCs, enemies, a boss, weapons, animals, about 40 SFX, one song per area (about 77 MB).
- Expect the integration step to break things. Run `check`, `test`, `smoke` after dropping assets in, and log everything in `ASSET_LOG.md`.
- What makes the Wingnut screenshots look cohesive (observed, not confirmed): one consistent palette and pixel density, layered parallax backgrounds for depth, a themed HUD frame, readable projectiles. Put those in your style fragments (`docs/BRIEFS.md`).

## AI-agent RTS in one week (claimed, E16)
Seven days, solo, Unity 6 + URP, Git from day one. Order of work, which matches this kit's SOPs:
```
Day 1  write the concept on paper with the agent -> overview doc + concept image iterations (about 4 rounds) -> lock FINAL references
Day 2  engine setup + MCPs (Blender, Unity, asset generator) -> hero + first units + one castle with placeholders
Days 2-3  MECHANICS FIRST, no 3D art: movement, combat, unit stats, balance by playing ~200 times, vision limits in forests
Days 4-5  terrain: learn the terrain tools yourself, MicroSplat for >8 layers, generated seamless textures, decals, grass, shader-animated trees, water, clouds
Day 6  post effects, fog of war, neutral castles
Day 7  modular castles: agent generates PARTS, Blender assembly + manual UV, retexture (Tripo/Meshy or Modddif), team colors via separate flags/banners
End of every day: ask the agent to consolidate what was learned, check project structure, list leftovers and open questions, commit
```
Worth copying into this kit:
- **Mechanics before visuals.** Confirm the game plays the way you imagine before spending time on models (SOP-01, SOP-03). He balanced against his own deaths: enemies must feel hard, kiting required.
- **Do not delegate what you do not understand.** He spent hours learning the terrain tools, asked Claude to teach folder and prefab structure, then decided. Same spirit as the "when stuck, change the angle" rule.
- **Per-theme tuning:** unit roles with different strengths (skeleton count vs human defense), rage-mode AoE on one race that punishes splitting. Put such rules in `docs/GDD.md` and the tuning numbers in data files.
- **Modular asset kits:** generate castle parts, not whole castles. Flags and banners are separate pieces so team color (neutral gray, red, etc.) is a material swap. Two hours of hand assembly per hero asset was considered fine.
- **Color alignment pass:** when generated pieces do not match, run the base color texture through an image-edit model with the environment as reference (the video names Nano Banana Pro), then re-apply. Add this to the `/gen-brief` flow for 3D drafts.
- **Surround decals:** a lone building looks pasted on. Ask for ground decals (walls, road bits) in the same pass.
- **Performance early:** retexture and reduce trees because there will be many. Budgets in SOP-11 and SOP-10.
- **Daily knowledge capture** is the same idea as `/end-session` plus `HANDOFF.md`.
- **Claimed:** AI agents work faster with Unity than Unreal "at least faster for sure" because of the MCP ecosystem. One person's tests, not verified. This kit supports both.
- **Mocap/animation plan for next video:** characters, animations, VFX, with GPT-class models helping with bones. Not shown yet.

## Budget stack and handoff notes (claimed, E07)
- **Budget stack:** Claude ($20 plan, Opus 5.5 on Medium to stretch weekly limits) + Godot (free, open source) + Lovable credits + free Gemini music + ElevenLabs for one month. He hit the weekly limit early and got a free refresh.
- **Handoff loop:** Claude generates the whole project as a zip (code, sprites, music, fonts, scripts), he unzips, opens `project.godot` in Godot, runs. Feedback goes back to Claude, which repackages. He says there are likely more efficient ways. This kit's version: Claude Code edits the repo directly, `python tools/dev.py check|test|smoke` instead of re-zipping.
- **Scope honesty:** big systems (MMO-style, servers) are not something AI delivers scalable and secure yet. Keep the first game small, with a one-sentence hook pitch (Wingnut: "16-bit shooter meets Mega Man X").
- **Vertical slice, never end to end in one prompt:** write the game design doc, build a small slice, test whether it is fun, then scale to art, music, and systems. This matches `SOP-01` and `SOP-08`.
- **Platform target:** pick engine and storefront in the GDD (Godot, Steam PC first), port later.
- **Placeholders first:** code-drawn crude graphics were fine until real art arrived. Code-made SFX sound cheap, so those get replaced early.
- **Audience note:** he flags strong anti-AI sentiment and a likely ceiling on sales for fully AI-made games. Relevant to Steam disclosure and store-page wording in `/release-check`.
- **Blender MCP for 3D** was mentioned as something he had seen but not tried.

## Workspace pattern seen in a screenshot (observed, E18)
What the screenshot shows: a Cursor window with a project folder, a built-in browser tab on `localhost` showing a custom page titled like a game GDD plus concept art, and a PowerShell terminal.
- **Concept board web page (local, apparently custom-built):** tabs for Overview, Mechanics, Characters, Castles, Locations, Ideas, Concepts. The Concepts tab has Direction, a locked "Final" set, and v1 to v4 versions. Each concept card is labeled FINAL with an edit note per version (for example units enlarged, clutter removed, forest densified).
- **Drift tracking:** one card notes that a faction banner drifted to the wrong color and a fix is pending. That is the kind of consistency problem `BRIEFS.md` style fragments are meant to prevent. Worth copying: lock a FINAL image per scene and write down what changed in each version.
- **Folder habits visible in the explorer:** `.claude/skills`, `assets`, `context`, `knowledge`, `inbox` (with a video inbox), `processes` (repeatable workflows such as 3d-ai), `projects/<game>`, `scripts` (image-gen, 3d, video-watch and others). File names like a UE MCP guide suggest he also uses Unreal. Contents were not visible.
- **Other models in the mix (inferred from folder names only):** a Kimi coding tool folder and a "Kimi K3 Tests" project, and a Hermes deploy guide. I do not know what these are in his setup.
- **In this kit:** `docs/CONCEPTS.md` now holds the same idea (FINAL per scene, version log, drift notes), fed back into `docs/BRIEFS.md`.

## Techniques worth stealing (snow survival build, claimed, E03)
- **Deformable ground from a height field:** ask the height at each point every frame near the player only (about 120 m window that slides with the player), not for the whole map. Snow depth slows movement, footprints are painted into ONE fixed-size texture that snow reads, wind erases, and enemies also write to. A thousand tracks cost the same as one.
- **Simple shapes beat "realistic" meshes.** Do not ask AI for realistic models. Boxes, roofs, and good lighting look better than a failed realistic mesh.
- **Concept to mesh:** concept images (image model) -> mesh generator at about 8,000 triangles for a main character -> its own rig and animations -> map colors to the color bible.
- **Lighting presets** (nightfall, deep night, blizzard, sunrise, pale day) from a slider panel change the whole scene cheaply.
- **Decimate downloaded models** (a CC-attribution bear from Sketchfab) in three LOD stages with a Blender script. Keep the attribution in `ASSET_LOG.md`.
- **Interior reveal:** the roof and front wall disappear when the player steps inside. **Occlusion fade:** a ray from the camera to the player fades whatever blocks the view.
- **Fewer, deadlier enemies:** two enemy types, each able to kill you, with telegraphs (warns, then charges).

## Workflow habits from a shipped browser game (claimed, E05)
- **Mockups first, do not skip.** Generate in-game mockups for each device (mobile and desktop) with an image model, pick a mix of styles, then build. This is the alignment step that one-shot videos skip.
- **End the briefing prompt with "Do you understand?"** so the AI pauses and restates the plan before building.
- **Stop one-shotting.** One-shot runs of 12 to 48 hours are great tech demos but give you little creative control over the game in your head.
- **Preview scene for imported models.** A scene that loads each model so size, weight, and animation can be checked (and attachment points like a hose nozzle bound to a hand) caught problems before they hit the game.
- **Background helper agents:** a cheap model captures prompts, takes screenshots or videos, and makes commits so you can review later and make tutorials. One main agent, plus one or two sub-agents only when work is parallel.
- **Ask the AI to teach you.** Have it write a short page explaining how a feature works (his example: the nozzle is a spring chasing the cursor, computed 120 times a second). You learn, and you can steer it better.
- **Polish list:** skybox image (cheap, big atmosphere win), fill the empty world, then first-time user experience.
- **Cost reality (his report):** about 6.5 hours of mostly unattended agent time, about $233 at API prices for the first release, on a high-tier subscription. Your numbers will differ.

Back to the index: `docs/RESOURCES.md`.

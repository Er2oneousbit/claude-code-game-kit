# Generation Briefs: style fragments, prompt patterns, prompt library

> Used by `/gen-brief`. Fill the **Style fragments** once, reuse them in every prompt so assets look and sound like one game.
> Tool features, limits, and pricing change often. Anything marked **(verify)** was written from general knowledge.
> Log accepted outputs with `/asset-intake` (tool, plan or tier, date, prompt). Sources of non-AI assets: `docs/RESOURCES.md`. Where these patterns came from: `docs/EVIDENCE.md`.

## Style fragments (fill these in, then paste into every prompt)
| Fragment | Text |
|---|---|
| **ART_STYLE** | e.g. "16-bit pixel art, 32x32 sprites, limited 16-color palette, hard edges, no anti-aliasing" |
| **PALETTE** | hex list or named palette |
| **CAMERA / VIEW** | e.g. "side view, orthographic, flat lighting, character facing right" |
| **MOOD / TONE** | e.g. "melancholy, neon-noir, quiet menace" |
| **AVOID** | e.g. "no text, no watermark, no gradients, no realistic shading, no real brands or characters" |
| **VOICE_CAST** | per character: age range, accent, energy, pacing, vocal quirks |
| **SFX_CHARACTER** | e.g. "chunky retro, short, dry, no reverb, punchy transients" |
| **MUSIC_BRIEF** | genre, tempo range, instrumentation, loop behavior, mood per area |

## Asset pack request (turn a slice into a prompt list)
```
List every asset needed to level up the vertical slice (world map, dungeon, title screen). Group by tool: [image tool],
[music tool], [SFX tool]. Within art, order: main character first (lock the look), then hero actions, then enemies, then tiles/props, then UI.
Each block must be copy-paste ready, repeat the style fragments, state sprite size and facing, and name the output file.
```
Do the character first so every later prompt can reference the locked look (see `docs/CONCEPTS.md`). Pattern from a creator series (E10).

## Asset hand-off (new art for Claude to integrate)
```
Playtest notes: [what is broken, one line each]. Attached: [sheet name -> what it is, e.g. roll_down.png = roll toward viewer].
First analyze the attachments against the notes and the code. Tell me which problems are code bugs and which need new art,
and list any asset that is missing or not good enough. Do not change code until I confirm.
```
The "do not change code yet" line matters: without it Claude may rebuild before you can add the asset it would have asked for (E35).

## Prompt patterns by category

### Images (ChatGPT, Grok, Midjourney, etc.)
```
[ART_STYLE]. [SUBJECT: what it is, pose, key details]. [CAMERA / VIEW]. [PALETTE]. [MOOD]. Plain flat background. [AVOID].
```
- Ask for **turnarounds** (front, side, back) or sprite sheets in a separate request from the hero image.
- For anything that will become 3D: neutral pose (A or T), flat even lighting, no cast shadows, plain background, orthographic views.
- Generate 4 variants, pick one, then iterate **one change at a time** (color, silhouette, prop) to keep the rest stable.
- Output sizes and transparency support differ by tool **(verify)**. Plan to clean up and downscale by hand for pixel art.
- Pixel art sets (from a series workflow, claimed): do portraits, sprite sheets, tile sets, and UI as separate requests with the SAME style fragment prefix, expect the first sheet to need rework, and budget several passes.
- Ask for consistent sprite sheet layout (grid size, frame count, facing direction) so Claude can wire up animations without guessing.
- Reject if: wrong palette, perspective drift, extra limbs or props, text artifacts, baked-in lighting that fights the engine.

### 2D character and tile pipeline (reported, E10)
Direct sprite-sheet prompts failed for days. What worked, in order:
1. **Portrait first.** Get one approved hero portrait (use an anime-style or reference portrait as the style anchor). Then generate expression portraits by attaching the approved portrait: "using the attached approved portrait, make other portraits for these emotions".
2. **Portrait to sprite.** "Using the attached portraits as an exact character reference, generate a 3/4 view sprite" facing right, forward, and back. Skip left: mirror it in engine.
3. **Then animation frames** (walk, attack per direction, per weapon). This is where models drift: limbs flip, proportions change. Say "do not change the hero's appearance whatsoever", and expect many retries.
4. **Always request a flat MAGENTA background** (FF00FF). It is easy to key out. White backgrounds eat shiny edge pixels. Use `tools/art/chroma_key.py`.
5. **Tiles:** the first jungle and temple tile sets were weak. Fix that worked: once one image hit the target fidelity, say "brand new prompt, same fidelity as this approved image", then ask for dungeon tiles, hub city tiles, NPC walk cycles (3 directions), enemies, and items with only that short instruction. Simple prompts on top of a locked look beat long hex-code prompts.
6. **Test ONE of each first:** one song, one SFX, one sprite sheet. Pivot early if the direction is wrong, before generating everything.
7. **Chat context goes stale.** When the generator keeps making slight variations of a bad result, switch to a different asset type (title screen, logo, HUD) for a while, then come back. Reported to reset the output.
8. **Style references:** you can attach classic sprite sheets as style references (the creator used Mana, Link to the Past, Chrono Trigger). Treat it as inspiration only, never ask for a copy, and do not ship anything that reproduces a known character or sheet. Style reference did not fix his results anyway.
9. **Bosses as parts:** head, body segment, tail, hit state, defeated state, so code can chain segments (the creator calls it a linked list). Cheap to animate and hitbox.
10. **Name files exactly as in the prompt pack** (for example `portrait_<hero>.png`, `tiles_temple.png`). Claude maps assets from names with fewer tokens and fewer mistakes.
11. **Watch a sheet move before integrating it** (E35). Preview each row as a looping GIF. Walk frames that are nearly the same pose do not read as
    walking even when the code cycles them, and a walk cycle must return to its first frame or the character sticks mid-stride.
12. **One direction keeps failing? Start a fresh chat** with only the good sheet attached: "same sprite sheet, do not change the character's
    appearance at all, but rolling away from the viewer". A long chat keeps reproducing its own mistake (E35; compare tip 7).
13. **Correct frame by frame.** List what is wrong in each frame ("frame 1: head faces away but arms and legs face the viewer"). This fixed the
    roll-away sheet after general prompts failed (E35).
14. **Tiles need transitions, not just tiles.** Dark outlines on every tile make a grid ("Lego world"). Ask for edge and corner transition
    pieces, curved path pieces, and cliff faces that show elevation, then use the engine's terrain/autotile feature (E35).
15. **Budget the iterations.** Expect 2 to 10 rounds per animation. For a vertical slice, stop at readable and playable; paid sprite
    animation tools are for after the game proves fun (E35).

### 3D drafts (text or image-to-3D services)
```
Input: one clean front-view concept image (plain background, neutral pose), or: "[SUBJECT], game asset, [ART_STYLE], neutral pose, no base, no background"
```
- Treat output as a **draft**: expect to retopologize, fix UVs, and rebuild materials (`SOP-11`).
- Decide poly target and format before generating. Export glTF/GLB when offered.
- Reject if: baked lighting in textures, non-manifold or messy topology, wrong scale or pivot, fused limbs.
- Kit pieces: generate PARTS (walls, towers, flags, banners as separate pieces) and assemble in Blender, instead of whole buildings. Flags separate so team color is a material swap **(one video, E16)**.
- Color alignment: if a generated piece clashes with the environment, run its base color through an image-edit model with an environment reference, then re-apply. Ask for ground decals (walls, road bits) so buildings do not look pasted on.

**Tripo AI specifics** **(verify, from a mid-2026 third-party review, E29)**
- Image input: single clear image (JPG, PNG, WEBP, reported 5 MB limit). Cluttered backgrounds and busy photos give weaker meshes, so use a clean
  front-view concept with a plain background (make it with the image-generator patterns above).
- Workflow: image prompt (ChatGPT/Grok/etc.) -> Tripo image-to-3D -> optional retopo and auto-rig in Tripo -> export GLB or FBX -> Blender cleanup (`SOP-11`) -> engine.
- Free-plan output is reported as non-commercial. Record the plan in the Prompt Library `Plan/tier` column. Treat free-plan meshes as PLACEHOLDER in `ASSET_LOG.md`.
- Credits are consumed per task. Generate one good candidate, not twenty, then iterate the input image.
- API key: keep it in an environment variable or local secrets file that is git-ignored. Never paste it into prompts, docs, or code.
- Claude Code route: TripoMCP (Blender add-on built on BlenderMCP, MCP server + Tripo API key) lets Claude generate and place models inside Blender.
  Record it in an ADR if adopted. Tool is community/vendor open source, check its repo for current setup.

### Motion reference video (Seedance or similar video generators) **(verify, E02)**
```
ONE picture split into two panels: left panel front view, right panel side view of the same creature (two fixed cameras in a single image). [SUBJECT: creature description matching the 3D model], [MOTION: walk, run, attack, idle], the SAME single move in both panels, static cameras, plain background, full body in frame, consistent lighting, [ART_STYLE]
```
- Purpose: reference motion for a retargeting pipeline (`docs/resources/pipelines.md`, "Creature animation pipeline", E02), not a shippable asset.
- One motion per clip, static camera, whole body visible, no cuts. Joint tracking fails on occlusion and camera moves.
- **Two views in ONE image, not two separate videos:** the same prompt run twice gives two different videos that never match (creator's report). Check that both panels show the same move before spending effort on tracking.
- Painting each leg a different color helped tell legs apart, but Seedance does not always keep the paint. Treat as a trick, not a method.
- Reject if: limbs vanish or merge, camera moves, body leaves frame, proportions drift from the model.
- Record tool, plan, date, and prompt in the Prompt Library. Check output ownership terms **(verify)**.

### Voice (ElevenLabs or similar TTS)
```
Voice design brief: [character name], [age range], [gender presentation if relevant], [accent], [personality and energy], [pacing], [one or two distinctive qualities]. Reference vibe: [describe, do not name a real person].
Line: "[text]"   Direction: [emotion, volume, intent, pauses with punctuation]
```
- Lock the voice once per character, record the voice ID or settings in the Prompt Library, reuse for every line.
- Write lines the way they sound: contractions, punctuation for pauses, spell out numbers and tricky names phonetically if the tool needs it **(verify)**.
- Generate 2 to 3 takes per important line. Same direction text per emotion for consistency.
- Reject if: wrong emotion, robotic rhythm, mispronounced names, inconsistent loudness between takes.
- Rights and plan: record the account tier at generation time. Commercial-use terms can depend on it **(verify)**.

### SFX (ElevenLabs sound effects, jsfxr, or similar)
```
[SOUND SOURCE and material], [ACTION], [ENVIRONMENT/space], [PERSPECTIVE: close, distant], [DURATION], [SFX_CHARACTER]. Dry, no music, no voice.
```
- Examples: "wooden door slamming in a stone hallway, close mic, 1 second, dry" or "retro 8-bit coin pickup, bright, 0.3 seconds".
- Generate **3 to 5 variants** for anything that repeats (footsteps, hits). Randomize pitch ±5 percent in the engine.
- Ask for the **layers** separately for big events (impact, tail, debris) and mix in an editor.
- Duration and looping controls vary by tool **(verify)**.
- Batch plan: list every SFX you need first, generate them all in one burst, then cancel the subscription if you do not need it again **(tip from E07)**. Vague animal or creature prompts can return the wrong thing (a condor cry gave a baby crying), so describe pitch, texture, and context.
- Reject if: reverb baked into a one-shot, clipped start or end, music or voice leaking in, wrong material.

### Music notes from a series episode (Gemini, claimed, E10)
- Each area needs a different identity (jungle, temple, boss, title) or the soundtrack turns to mush. Say so in the brief.
- The generator may ignore "16-bit chip tune" and give modern, well-recorded music. That contrast with retro art can be fine, but decide on purpose.
- Length is not obeyed: a title theme came back at 1:20 with a slow build. Trim in an editor and fade, or ask Claude to cut near the good part. Check the loop in engine: soft start and soft end for seamless looping.
- ElevenLabs gives four takes per prompt, 68 credits each as he said. Remove words like "soft" if the result is inaudible. Be wary of two-part prompts ("body fall, then drum"), the parts came out separated.

### Music (generators or briefs for a human composer)
```
[GENRE], [TEMPO range], [KEY/mood], [INSTRUMENTATION], [STRUCTURE: intro/loop body], seamless loop, no vocals, [MOOD per area]
```
- For commissions, use this as the brief and add: deliverables (stems, loops, one-shots), license scope, revision count.
- Loop check in the engine, not the generator. Loudness-match all tracks to each other.
- AI music: the license and store disclosure are the risk **(verify)**. Log tool, plan, date, prompt.

### Music with Suno (Advanced mode, called Custom in older versions; E33)
Fields: **Style** (sound only, about 1,000 characters, genre and mood first), **Lyrics** (only bracketed section tags for game music),
**Exclude styles** (short list; a hint, not a hard filter, so also name the replacement in Style). Never name artists.
Write one palette line per game and repeat it in every track so the soundtrack sounds like one game. This is a
**template, not a prompt**: fill every `[bracket]` (or ask `/gen-brief`), then paste each field into its own Suno box.
Pasted as is, Suno gets the bracket words as the style and writes random non-game music (it happened). Start the Style
with "video game background music" so it does not drift into a pop or film piece.
```
TEMPLATE (fill the brackets first)
PALETTE: [genre/era], [3-4 core instruments], [production texture]
Style:   [PALETTE], [mood for this area], [tempo] BPM, [energy], instrumental, steady loopable groove, no fade-out
Lyrics:  [Intro] [Main Theme] [Variation] [Main Theme] [Outro] [End]
Exclude: vocals, choir, spoken word, [anything that breaks the palette]
```
Starter set (swap the palette, keep the shape):

| Track | Style (after the palette) | Lyrics tags |
|---|---|---|
| Title / menu | mysterious and inviting, 90 BPM, slow build, memorable main melody | `[Intro] [Main Theme] [Outro] [End]` |
| Exploration | curious calm, 85 BPM, low energy, sparse, no big drops | default |
| Combat | urgent, 140 BPM, high energy, constant intensity, no breakdown | default |
| Boss | menacing, 150 BPM, relentless, big recurring motif | default |
| Town / safe zone | cozy and safe, 80 BPM, gentle | default |
| Dungeon ambience | tense drone, no drums, no melody | `[Ambient] [End]` |
| Victory sting | triumphant, short, 5 seconds, clean ending | `[Short Fanfare] [End]` |
| Game over | sad, 70 BPM, short, clean ending | `[Short Outro] [End]` |

- Suno does not obey length or "seamless loop" (same lesson as E10 above). Cut a clean 8 or 16 bar loop in an editor, or
  `python tools/audio/wavfile.py loop <download>.wav --start <intro s> --end <outro s> --crossfade 2`, and test it in engine.
- Suno has no official public API (2026-10). Third-party "Suno API" sites sell their own credits; output made there is not
  covered by your Suno plan's rights. Use the web app.
- Retro: "chiptune" alone may come back modern. Name the sound ("square wave lead, triangle bass, noise drums") and exclude "orchestral, live drums, reverb".
- Generate 4 to 6 takes, keep the best, then use extend or cover on the winner to make area variations of one theme.
- Rights (E34, **verify** in Suno's current terms before shipping): paid plans grant commercial use for tracks made while subscribed; free-plan
  tracks are non-commercial. Ownership wording changed after Suno's Warner deal. Log the plan in `ASSET_LOG.md`; AI bucket is "pre-generated" (`SOP-04`).

## Prompt Library (accepted results)
| ID | Category | Tool | Plan/tier | Date | Prompt (or voice ID / settings) | Asset ID in ASSET_LOG | Notes |
|---|---|---|---|---|---|---|---|
| P-0001 | | | | {{DATE}} | | | |

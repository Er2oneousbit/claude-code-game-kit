# Dotwork examples

One pack spec per capability. Each one rendered and passed the in-game verify (Godot import, load, smoke) while Dotwork
was built. Run any of them from your game's root:

```
python tools/art/dotwork/dotwork.py pack --spec tools/art/dotwork/examples/<name>.json
```

Copy a spec into your own `assets_src/` (or wherever you keep specs), rename the entries and rewrite the prompts:
prompts describe the subject only, Dotwork adds the pixel-art wording. Seeds are fixed so a re-run gives the same art;
change a seed to get a different take.

| Example | Shows | Model tiers |
|---|---|---|
| `ui.json` | glyph-tool fonts (dialogue, damage numbers, brass and steel titles, symbols), window skins, HUD widgets (gauges, button states, panel, a Theme), emote balloons, hit spark / slash / damage-flash shader | none |
| `status.json` | status-effect loops: poison, sleep, haste, slow, stop, blind, regen, berserk, confuse, silence, doom, burn, freeze, protect, shell, petrify | none |
| `screen.json` | screen transitions (battle swirl, fade, iris, diamond, wipe, blinds, dither, clock, blocks, mosaic) and weather (rain, snow, fog, ash, embers, leaves, sandstorm) | none |
| `town.json` | grass, dirt, raised cobble; brick / timber / stone facades; clay / slate / copper roofs; doors, windows, chimney, sign; one painted street map | sprites |
| `interior.json` | floor, wall tops, north wall face, black void, furniture fixtures | sprites |
| `dungeon.json` | mine floor, rock walls (cliff style), rock tops, rails, props placed by the map | sprites |
| `cliffs.json` | a raised plateau over a cliff face, stairs, hedges | sprites |
| `connectors.json` | fences, iron railings, steam pipes, rail tracks (drawn in code) | sprites |
| `platformer.json` | side-view platformer tiles (grass over dirt, a mine set), one-way ledges, a parallax background | sprites |
| `iso.json` | isometric floors (3 materials) and a wall block, projected from the ground textures | sprites |
| `water.json` | animated shallow / deep water and sludge, sand shore, a prebuilt building | sprites |
| `overworld.json` | world-map terrains and location icons | sprites |
| `props_icons.json` | props with collision scenes, icons at 16 and 32 px, a portrait | sprites |
| `battle.json` | a battle background, a regular enemy, two palette swaps of it and a boss | sprites |
| `scenes.json` | title, game over and cutscene backdrops | sprites |
| `interactables.json` | chest, door, lever, save point; ambient loops (torch, banner, smokestack, gear, fern); an 8-direction airship | sprites, rotate |
| `spells.json` | two spells and a summon blast (additive) | sprites, animate |
| `mount.json` | a rideable walker, idle + walk in 4 directions | sprites, rotate, animate |
| `npcs.json` | two townsfolk (walk clips, code-drawn idles) and three palette variants of them (no render) | sprites, rotate, animate |
| `party_member.json` | a party member: 4-direction idle and walk, attack, the battle pose set, a portrait with five expressions and talking frames | sprites, rotate, animate |
| `tools.json` | instruction edits, an inpaint and a normal map on one of your sprites | sprites |
| `img2px.json` | concept art or a photo to pixel art at a set width | sprites |

Measured per-render costs on an RTX 5060 Ti 16 GB (from dotwork's own logs), to size a pack before you run it:

| Render | Time |
|---|---|
| ComfyUI start (once per run) | 20-25 s |
| a prop, icon, enemy, portrait, battle background or scene (klein) | 10-27 s |
| a character's 4-direction rotation (Qwen) | about 130 s |
| a vehicle's 8-direction rotation | about 210 s |
| one animation clip (Wan 2.2: one action in one direction, or one effect) | 100-120 s |

A party member is one rotation plus one clip per action and direction (8-12 clips) plus the battle poses, so plan on 20-30 minutes; ground packs render one texture per material plus its seamless variants. Re-runs reuse the cached renders. `dotwork.py setup --check` lists which model tiers you have.

`tools.json` edits the duelist's first south idle frame, so run `party_member.json` first (or point its `source` at
any south-facing sprite of yours). `img2px.json` needs your own source image at the path it names. `town.json`,
`interior.json`, `dungeon.json`, `cliffs.json`, `connectors.json`, `water.json` and `overworld.json` include a map:
Dotwork paints it in Godot and writes a preview PNG next to the scene, so you see the tiles in use, not only the atlas.

## Style reference
With no `style_refs` in `dotwork.config.json` (the default) Dotwork renders from the prompt alone. Add 3-4 of your own
finished sprites to `style_refs` and new art follows their palette, outline and shading more closely; set
`"design": {"character": {"style_ref": ""}}` in one spec to switch the reference off for that pack only.

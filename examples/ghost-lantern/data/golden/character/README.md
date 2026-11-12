# Golden rigged character

`character.glb` is the kit's test character: every 3D engine's test loads it, plays `walk` and checks that a bone
moved, and `tools/blender/render_sprites.py` renders it into sprite sheets for the 2D engines. It is a blocky biped
built from boxes by `tools/blender/golden_character.py` (no third-party or AI asset), rigged the way Bozzetto's rig
routes rig a character: Mixamo bone names, one skinned mesh, clips as glTF animations.

| | |
|---|---|
| File | `character.glb`, glTF 2.0 binary, about 62 KB, no textures (flat material colours) |
| Space | metres, +Y up, front +Z (Blender's -Y), feet on the ground at the origin, left is +X |
| Height | 1.80 m |
| Mesh | one mesh, 252 triangles, 4 materials (skin, shirt, trousers, shoes); a nose box shows the front |
| Skin | 22 joints, every box weighted fully to one bone (rigid: seams at the joints) |
| Bones | `mixamorig:Hips` (root), `Spine`, `Spine1`, `Spine2`, `Neck`, `Head`; per side `Shoulder`, `Arm`, `ForeArm`, `Hand`, `UpLeg`, `Leg`, `Foot`, `ToeBase` (all with the `mixamorig:` prefix) |
| Rest pose | A-pose, arms 40 degrees under horizontal (like Bozzetto rigs) |
| Clips | `idle`: 48 frames at 24 fps, 2.0 s (breathing, nod, arm sway, hip bob); `walk`: 24 frames, 1.0 s, two steps in place (no root motion) |
| Keys | every clip starts at 0 s and its last key equals its first: it loops without a seam |
| Moving bone | `mixamorig:LeftUpLeg` swings 56 degrees over `walk` (engine tests watch it) |

`expected.json` holds these numbers for the tests; never copy them into a test. What each engine names
`mixamorig:Hips` after import (its test checks it, `bone_names_in_engines`): Godot and Unreal `mixamorig_Hips`,
three.js `mixamorigHips`, Unity (glTFast) and Bevy keep `mixamorig:Hips`.

## The sprite sheets: `sprites/`
The same character rendered for the 2D engines by `render_sprites.py --manifest`: an assets folder whose
`sprites/dotwork/character.assets.json` is a Dotwork asset manifest (spec 1.0.0, generator `render_sprites`) with one
`animated_sprite`, `character`, and `expected.json`, assetspec's loaded result of it. The 2D engines' Dotwork
importer tests load it beside the Dotwork golden pack.

| | |
|---|---|
| Sheets | `sprites/art/character/character_idle.png` (8 frames) and `character_walk.png` (4 frames): one row per direction (s, w, n, e), 48 px cells |
| Clips | `idle_s` ... `walk_e`, 6 fps (every 6th frame of 24 fps), all looping; the glTF loop's repeated last frame is rendered once |
| Pivot | where the origin (the feet) lands in each direction's cell, about `[24, 37]` |
| Frames | each frame also as its own PNG in `art/character/character_frames/` (the manifest requires them) |

## Rebuild
```
blender -b --factory-startup --python-exit-code 1 -P tools/blender/golden_character.py --
python tools/blender/test_golden_character.py      # the exam: reads the .glb without Blender, rebuilds when it can
# the sheets (delete sprites/ first), then expected.json from assetspec.expected():
blender -b --factory-startup --python-exit-code 1 -P tools/blender/render_sprites.py -- data/golden/character/character.glb --out data/golden/character/sprites/art/character/character.png --actions all --step 6 --directions 4 --size 48 --samples 16 --pixel-art --manifest data/golden/character/sprites/dotwork/character.assets.json
python -c "import json,sys; sys.path.insert(0,'tools/art/dotwork'); import assetspec as a; d='data/golden/character/sprites/'; open(d+'expected.json','w',encoding='utf-8',newline='\n').write(json.dumps(a.expected(a.load(d+'dotwork/character.assets.json')),indent=1)+'\n')"
python tools/blender/test_render_sprites_manifest.py   # validates sprites/ and checks expected.json is current
```
Built and rendered with Blender 5.2.3 (2026-11-11).

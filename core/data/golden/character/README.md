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

`expected.json` holds these numbers for the tests; never copy them into a test. Godot replaces `:` in bone names
with `_` on import (`mixamorig_Hips`).

## Rebuild
```
blender -b --factory-startup --python-exit-code 1 -P tools/blender/golden_character.py --
python tools/blender/test_golden_character.py      # the exam: reads the .glb without Blender, rebuilds when it can
```
Built with Blender 5.2.3 (2026-11-11).

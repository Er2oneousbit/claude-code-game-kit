#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# rebake_uvs.py
# Purpose : Give a textured mesh a fresh, efficient UV layout and bake its own textures onto it. Generated models
#           (Tripo, TRELLIS.2) arrive with the vendor's atlas: thousands of tiny islands covering a third of the
#           texture, which fails the SOP-11 UV coverage floor and wastes texels. The user cannot fix a vendor atlas
#           without a rebake, so this does it: Smart UV Project plus Blender's island packer on a new UV map, then
#           every image the materials read is baked through the two layouts onto a new image of the chosen size
#           (base colour, metallic-roughness(-occlusion), emission, alpha: a pure texture transfer; the normal map is
#           baked as a tangent-space normal, since island rotation changes the tangent frame). The materials keep
#           their node graphs (constants, the glTF settings group, alpha wiring); only the images and the UV map
#           change. The result is checked against the original by rendering both from four sides, as flat colour
#           (the base colour as emission) and lit by a sun (the normal, roughness and metallic maps show there).
# Usage   : Inside Blender (any OS):
#             blender -b --python-exit-code 1 -P tools/blender/rebake_uvs.py -- <in.glb> --out <out.glb> [options]
#           With the bpy module:
#             python tools/blender/rebake_uvs.py <in.glb> --out <out.glb> [--texture 2048] [--json report.json]
#           From another Blender script (tools/bozzetto/cleanup.py --rebake): rebake(bpy, va, obj, texture_px, report)
# Needs   : Blender 4.2+ or the bpy module (Cycles on the CPU for the bakes and the check renders)
# Exit    : 0 written, 1 the bake did not match the original (nothing written) or the mesh could not be read,
#           2 usage or environment (several mesh objects without --join, bpy missing, files in the way)
# Notes   : The source file is never changed. Texture size: --texture, else the largest image the model reads
#           (a 2048 vendor atlas stays 2048), else 1024. The gap between islands is size/1024 pixels (at least 1:
#           padding_px), the bake margin BAKE_MARGIN_PX into free texels. The check renders the base colour as pure emission (no
#           light, no normal map) and the materials under a sun, at 256 px from four sides before and after, and
#           compares the pixels both cover: a mean difference over COLOUR_FAIL or LIT_FAIL (8-bit levels) is a
#           failed bake (exit 1), over COLOUR_WARN or LIT_WARN a warning.
#           Resampling blurs a little (the vendor's texels are not the new ones), so expect a few levels, never zero.
#           Formats (#303): a colour map (sRGB, no alpha) whose source image was JPEG is written as JPEG at
#           prep_export.JPEG_QUALITY (a Tripo character's three 2048 maps had come back as 9.7 MB of PNG, the main
#           file 5.0 MB to 11.5 MB); normal, metallic-roughness(-occlusion) and other data maps stay PNG, since JPEG's
#           blocks show as dents in a normal map and as noise in roughness; a map with alpha stays PNG (JPEG has none).
#           --png writes every map as PNG. Each map's "format" and "quality" go into the report.
#           What is not carried: a second UV map, images read through a Vector input of their own (they keep that
#           input and are left alone, with a warning). Vertex colours stay as they are (nothing to bake).
# Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the island gap is size/1024 px (1 at 1024, #203)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): a JPEG source's colour map stays JPEG, --png (#303)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   import (validate_asset's importer) -> one mesh object (or --join) -> weld split vertices (standalone) ->
#   coverage and islands of the vendor UVs
#   texture size: --texture | largest source image | 1024
#   check render "before": each material's Base Color source as emission, four orthographic views, 256 px
#   new UV layer active: Smart UV Project (angle 66) -> pack_islands (rotate, CONCAVE, margin px/size)
#   every Image Texture reads through a UV Map node for the vendor layer; Normal Map nodes take it as tangent source
#   per material, per image node: transfer rounds (EMIT of the node's Color [and Alpha] into a new image of the
#     texture size, same colour space), normal round (bake NORMAL, tangent space, into a new image) -> swap the
#     node's image for the new one (a JPEG copy for a colour map whose source was JPEG, unless --png), pack it
#   remove the UV Map nodes and the vendor layer -> check render "after" -> mean and max difference -> report
#   standalone: export .glb with the kit's preset, JSON report
import argparse
import json
import math
import sys
import tempfile
import time
from array import array
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DEBUG = False
UV_ANGLE = 66.0            # Smart UV Project angle limit (degrees): Blender's default, coherent islands on a character
TEXTURE_DEFAULT = 1024     # when no source image says otherwise
TEXTURE_SIZES = (256, 512, 1024, 2048, 4096)
SAMPLES = 4                # bake samples: a little anti-aliasing when the vendor atlas is resampled smaller
BAKE_MARGIN_PX = 4         # baked texels extended into the free space around each island (mipmaps, filtering)
RENDER_PX = 256            # the check renders
RENDER_VIEWS = 4           # around the up axis
COLOUR_WARN = 4.0          # mean absolute RGB difference between the flat check renders, in 8-bit levels: a warning
COLOUR_FAIL = 16.0         # and a failed bake (textures lost or misplaced)
LIT_WARN = 8.0             # the same for the lit renders (normal, roughness and metallic maps show there; a sun
LIT_FAIL = 24.0            # at 4 samples with no bounces is a little noisy, so the bar is lower)
LIT_SAMPLES = 4
LIT_SUN = 3.0              # W/m2
GRID = 128                 # UV raster for coverage (validate_asset's default)
WELD_DISTANCE = 0.0001     # standalone: vertices closer than this fraction of the bounds diagonal become one
VENDOR_UV = "UVMap_vendor"
NEW_UV = "UVMap"


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


def padding_px(size):
    """The gap between islands in pixels: 1 up to 1024, 2 at 2048, 4 at 4096, the same share of the texture at
    every size (so the same mip level first blends neighbours). A generated mesh packs into thousands of islands,
    and every pixel of gap costs coverage (8 px at 2048 cost a 51k-triangle character 26 points, K01; 2 px instead
    of 1 at 1024 cost a TRELLIS.2 npc 4 points, 59% to 55%, under the npc floor, #203); TRELLIS.2 bakes its own
    atlas with 1 px. The bake margin (BAKE_MARGIN_PX) extends into the gap and beyond, into free texels only."""
    return max(1, size // 1024)


def free_vector(node):
    """An Image Texture that reads the mesh's own UVs: nothing on its Vector input, or the UV Map node this
    script put there."""
    v = node.inputs["Vector"]
    return not v.is_linked or (v.links[0].from_node.type == "UVMAP" and v.links[0].from_node.uv_map == VENDOR_UV)


def script_argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="rebake_uvs.py",
                                 description="A fresh UV layout for a textured mesh, its textures baked onto it.")
    ap.add_argument("asset", help="source mesh: .glb .gltf .fbx .obj .blend")
    ap.add_argument("--out", required=True, help="the rebaked .glb to write")
    ap.add_argument("--texture", type=int, default=0, choices=(0,) + TEXTURE_SIZES,
                    help="texture size in pixels (default 0: the largest image the model reads, else 1024)")
    ap.add_argument("--join", action="store_true", help="join several mesh objects into one first (one atlas)")
    ap.add_argument("--no-weld", action="store_true",
                    help="keep vertices split at the old atlas's seams (default: weld them, as cleanup.py does, so "
                         "the new islands follow the surface instead of the old seams; custom normals are kept)")
    ap.add_argument("--no-check", action="store_true", help="skip the before/after check renders")
    ap.add_argument("--png", action="store_true",
                    help="write every baked map as PNG (default: a colour map whose source was JPEG stays JPEG, at "
                         "prep_export.JPEG_QUALITY; normal and data maps are always PNG)")
    ap.add_argument("--json", dest="json_out", help="write the report (coverage, maps, settings, the check) here")
    ap.add_argument("--overwrite", action="store_true", help="replace --out if it exists")
    ap.add_argument("--debug", action="store_true", help="verbose output and full tracebacks")
    return ap.parse_args(argv)


def load_modules():
    try:
        import bpy  # noqa: F401
    except ImportError:
        print("[ENV ] bpy not available. Run inside Blender:\n"
              "         blender -b --python-exit-code 1 -P tools/blender/rebake_uvs.py -- <in.glb> --out <out.glb>\n"
              "       or with the bpy module for your Python version (uv run --python 3.13 --with bpy python ...)",
              file=sys.stderr)
        return None, None, None
    import prep_export as pe  # noqa: E402
    import validate_asset as va  # noqa: E402
    return bpy, va, pe


# ---------------------------------------------------------------- UVs
def weld(obj, fraction=WELD_DISTANCE):
    """Merge vertices glTF split at the old atlas's seams (UVs stay per corner, so the texture is unchanged, and
    custom normals are kept): Smart UV Project islands follow shared edges, so a split mesh would give one island
    per old seam patch (11,186 instead of 3,120 on a 51k-triangle character, K01). Returns vertices merged."""
    import bmesh
    mesh = obj.data
    co = [v.co for v in mesh.vertices]
    if not co:
        return 0
    lo = [min(c[i] for c in co) for i in range(3)]
    hi = [max(c[i] for c in co) for i in range(3)]
    diag = math.dist(lo, hi) or 1.0
    normals = [tuple(l.normal) for l in mesh.loops] if getattr(mesh, "has_custom_normals", False) else None
    bm = bmesh.new()
    bm.from_mesh(mesh)
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=fraction * diag)
    merged = before - len(bm.verts)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    if normals is not None and merged and len(normals) == len(mesh.loops):
        mesh.normals_split_custom_set(normals)   # the same corners in the same order: the shading stays
    return merged


def uv_stats(va, mesh, uv_layer):
    """(coverage 0..1, island count) of one UV layer, measured as the validator does."""
    mesh.calc_loop_triangles()
    islands = va.uv_islands(mesh, uv_layer)
    coverage, _, _ = va.raster_uv(mesh, uv_layer, GRID, islands)
    return round(coverage, 3), len(set(islands))


def unwrap(bpy, obj, size):
    """A new UV layer, unwrapped and packed; the old one renamed VENDOR_UV. Returns (old layer, new layer).
    Layer references go stale when a layer is added or edit mode is left, so everything is re-read by name."""
    mesh = obj.data
    (mesh.uv_layers.active or mesh.uv_layers[0]).name = VENDOR_UV
    mesh.uv_layers.new(name=NEW_UV)
    mesh.uv_layers.active = mesh.uv_layers[NEW_UV]
    mesh.uv_layers[NEW_UV].active_render = True
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.context.scene.tool_settings.use_uv_select_sync = True   # the face selection is the UV selection
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(UV_ANGLE), island_margin=0.0, correct_aspect=True,
                             scale_to_bounds=False)
    bpy.ops.uv.pack_islands(rotate=True, scale=True, merge_overlap=False, margin_method="FRACTION",
                            margin=padding_px(size) / size, shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")
    return mesh.uv_layers[VENDOR_UV], mesh.uv_layers[NEW_UV]


# ---------------------------------------------------------------- materials
def materials(obj):
    seen, out = set(), []
    for slot in obj.material_slots:
        m = slot.material
        if m is not None and m.node_tree is not None and m.name not in seen:
            seen.add(m.name)
            out.append(m)
    return out


def image_nodes(mat):
    return [n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image is not None]


def feeds_normal_map(node):
    return any(l.to_node.type == "NORMAL_MAP" for l in node.outputs["Color"].links)


def output_node(tree):
    outs = [n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"]
    return next((n for n in outs if n.is_active_output), outs[0] if outs else None)


def base_colour_source(tree):
    """(socket feeding Base Color, or None, its constant) of the material's Principled BSDF; None when there is none."""
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return None
    sock = bsdf.inputs["Base Color"]
    return (sock.links[0].from_socket if sock.is_linked else None, tuple(sock.default_value))


def emit(tree, from_socket, value=(0.0, 0.0, 0.0, 1.0)):
    """Show one socket (or a constant) as pure emission on the material's output. Returns a restore function."""
    out = output_node(tree)
    if out is None:
        out = tree.nodes.new("ShaderNodeOutputMaterial")
    surface = out.inputs["Surface"]
    prev = surface.links[0].from_socket if surface.is_linked else None
    em = tree.nodes.new("ShaderNodeEmission")
    if from_socket is not None:
        tree.links.new(from_socket, em.inputs["Color"])
    else:
        em.inputs["Color"].default_value = value
    em.inputs["Strength"].default_value = 1.0
    tree.links.new(em.outputs["Emission"], surface)

    def restore():
        tree.nodes.remove(em)
        if prev is not None:
            tree.links.new(prev, surface)
    return restore


def read_through(mats, uv_name):
    """Every Image Texture with a free Vector input reads uv_name through a UV Map node, and every Normal Map node
    without a UV map of its own takes uv_name as its tangent source. Returns a function that undoes it."""
    added, normals, skipped = [], [], []
    for mat in mats:
        tree = mat.node_tree
        uv_node = None
        for n in tree.nodes:
            if n.type == "TEX_IMAGE" and n.image is not None:
                if not free_vector(n):
                    skipped.append(n.image.name)
                    continue
                if uv_node is None:
                    uv_node = tree.nodes.new("ShaderNodeUVMap")
                    uv_node.uv_map = uv_name
                    added.append((tree, uv_node))
                tree.links.new(uv_node.outputs["UV"], n.inputs["Vector"])
            elif n.type == "NORMAL_MAP" and not n.uv_map:
                n.uv_map = uv_name
                normals.append(n)

    def undo():
        for tree, node in added:
            tree.nodes.remove(node)
        for n in normals:
            n.uv_map = ""
    return undo, skipped


def new_image(bpy, name, size, data, alpha):
    img = bpy.data.images.new(name, size, size, alpha=alpha, is_data=data)
    img.colorspace_settings.name = "Non-Color" if data else "sRGB"
    return img


def bake(bpy, obj, kind, px):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    kw = dict(type=kind, margin=px, margin_type="EXTEND", use_clear=True, use_selected_to_active=False,
              target="IMAGE_TEXTURES", save_mode="INTERNAL")
    if kind == "NORMAL":
        kw.update(normal_space="TANGENT")
    bpy.ops.object.bake(**kw)


def pack_image(bpy, img):
    """Keep the baked pixels in the file (the glTF exporter embeds them); a Blender that cannot pack a generated
    image saves it to a temporary PNG first."""
    try:
        img.pack()
        return
    except RuntimeError:
        pass
    with tempfile.TemporaryDirectory(prefix="rebake_img_") as d:
        img.filepath_raw = str(Path(d) / (img.name + ".png"))
        img.file_format = "PNG"
        img.save()
        img.pack()
        img.filepath_raw = ""


def merge_alpha(colour, alpha_img):
    """The R channel of alpha_img becomes the alpha of colour (both the same size)."""
    n = colour.size[0] * colour.size[1] * 4
    cbuf, abuf = array("f", bytes(4 * n)), array("f", bytes(4 * n))
    colour.pixels.foreach_get(cbuf)
    alpha_img.pixels.foreach_get(abuf)
    cbuf[3::4] = abuf[0::4]
    colour.pixels.foreach_set(cbuf)
    colour.update()


def map_format(entry, png):
    """JPEG for a colour map (sRGB transfer, no alpha) whose source image was JPEG, else PNG (#303): JPEG's
    8x8 blocks dent a normal map and add noise to roughness and metallic, and JPEG has no alpha."""
    if png or not entry["source_jpeg"] or entry["kind"] != "transfer" or entry["alpha"]:
        return "PNG"
    return "JPEG" if entry["colorspace"] == "sRGB" else "PNG"


def transfer_maps(bpy, obj, mats, size, report, png=False):
    """Bake every image the materials read onto the new layout, swapping each node's image. Fills report['maps'].
    png: every map as PNG (else a JPEG source's colour map stays JPEG, map_format)."""
    import prep_export as pe   # noqa: E402  (is_jpeg, jpeg_copy, JPEG_QUALITY: the LOD textures share them)
    px = BAKE_MARGIN_PX
    plan = {m.name: [n for n in image_nodes(m) if free_vector(n)] for m in mats}
    transfers = {m.name: [n for n in plan[m.name] if not feeds_normal_map(n)] for m in mats}
    normals = {m.name: [n for n in plan[m.name] if feeds_normal_map(n)] for m in mats}
    rounds = max([len(v) for v in transfers.values()] + [0])
    done = []
    # Transfer rounds: one bake writes into every material's active image node at once, so round r does the r-th
    # image of every material (a material with fewer gets a scratch target, thrown away).
    for r in range(rounds):
        for with_alpha in (False, True):
            restores, targets, scratch = [], [], []
            for mat in mats:
                tree, nodes = mat.node_tree, transfers[mat.name]
                src = nodes[r] if r < len(nodes) else None
                if with_alpha and (src is None or not src.outputs["Alpha"].is_linked):
                    src = None
                if src is None:
                    img = new_image(bpy, "rebake_scratch", 64, True, False)
                    scratch.append(img)
                    restores.append(emit(tree, None))
                else:
                    data = src.image.colorspace_settings.name != "sRGB"
                    if with_alpha:
                        img = new_image(bpy, src.image.name + "_alpha", size, True, False)
                        scratch.append(img)
                    else:
                        img = new_image(bpy, src.image.name + "_rebake", size, data, src.outputs["Alpha"].is_linked)
                    restores.append(emit(tree, src.outputs["Alpha" if with_alpha else "Color"]))
                    targets.append((mat, src, img, with_alpha))
                tgt = tree.nodes.new("ShaderNodeTexImage")
                tgt.image = img
                tree.nodes.active = tgt
                restores.append(lambda tree=tree, tgt=tgt: tree.nodes.remove(tgt))
            if targets:
                bake(bpy, obj, "EMIT", px)
            for restore in restores:
                restore()
            for mat, src, img, is_alpha in targets:
                if is_alpha:
                    colour = next(d for d in done if d["node"] is src)["image"]
                    merge_alpha(colour, img)
                    next(d for d in done if d["node"] is src)["alpha"] = True
                else:
                    done.append({"node": src, "image": img, "material": mat.name, "source": src.image.name,
                                 "source_px": list(src.image.size), "kind": "transfer",
                                 "colorspace": img.colorspace_settings.name, "alpha": False,
                                 "source_jpeg": pe.is_jpeg(src.image)})
            for img in scratch:
                bpy.data.images.remove(img)
    # The normal round: every material at once again; a material without a normal map gets a scratch target.
    if any(normals.values()):
        targets, scratch, cleanup = [], [], []
        for mat in mats:
            tree = mat.node_tree
            src = normals[mat.name][0] if normals[mat.name] else None
            if src is None:
                img = new_image(bpy, "rebake_scratch", 64, True, False)
                scratch.append(img)
            else:
                img = new_image(bpy, src.image.name + "_rebake", size, True, False)
                targets.append((mat, src, img))
            tgt = tree.nodes.new("ShaderNodeTexImage")
            tgt.image = img
            tree.nodes.active = tgt
            cleanup.append((tree, tgt))
        bake(bpy, obj, "NORMAL", px)
        for tree, tgt in cleanup:
            tree.nodes.remove(tgt)
        for mat, src, img in targets:
            done.append({"node": src, "image": img, "material": mat.name, "source": src.image.name,
                         "source_px": list(src.image.size), "kind": "normal", "colorspace": "Non-Color",
                         "alpha": False, "source_jpeg": pe.is_jpeg(src.image)})
        for img in scratch:
            bpy.data.images.remove(img)
        for mat in mats:
            for n in normals[mat.name][1:]:
                print(f"[WARN] {mat.name}: a second normal map ({n.image.name}) is left on the old layout")
    # Swap: the node reads the new image under the old image's name; the old image goes. A colour map whose source
    # was JPEG becomes a packed JPEG first (before the after-check renders, so the check sees what ships).
    for d in done:
        d["format"] = map_format(d, png)
        d["quality"] = pe.JPEG_QUALITY if d["format"] == "JPEG" else None
        if d["format"] == "JPEG":
            baked = d["image"]
            d["image"] = pe.jpeg_copy(bpy, baked, baked.name + "_jpeg")
            bpy.data.images.remove(baked)
        old = d["node"].image
        name = old.name
        d["node"].image = d["image"]
        if old.users == 0:
            bpy.data.images.remove(old)
        d["image"].name = name
        if d["format"] == "PNG":
            pack_image(bpy, d["image"])
        d["image"] = name
        del d["node"]
    report["maps"] = done
    report["bake"] = {"samples": SAMPLES, "margin_px": px, "margin_type": "EXTEND", "normal_space": "TANGENT",
                      "island_gap_px": padding_px(size), "uv_angle_deg": UV_ANGLE,
                      "packer": "smart_project + pack_islands(rotate, CONCAVE)",
                      "formats": "png" if png else "jpeg colour maps from jpeg sources", "jpeg_quality": pe.JPEG_QUALITY}


# ---------------------------------------------------------------- the check renders
def setup_render(bpy, scene):
    scene.render.engine = "CYCLES"
    scene.cycles.samples = SAMPLES
    scene.cycles.device = "CPU"
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = RENDER_PX
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0


def render_views(bpy, scene, obj, mats, folder, tag, lit=False):
    """Four orthographic renders of the object: its base colour as flat emission, or (lit) the materials as they
    are under a sun from the camera's side with no bounces, which shows the normal and roughness maps too.
    Returns the file paths."""
    from mathutils import Vector
    restores = []
    if lit:
        sun_data = bpy.data.lights.new("rebake_check_sun", "SUN")
        sun_data.energy = LIT_SUN
        sun = bpy.data.objects.new("rebake_check_sun", sun_data)
        scene.collection.objects.link(sun)
        scene.cycles.max_bounces = 0
        scene.cycles.samples = LIT_SAMPLES
    else:
        for mat in mats:
            src = base_colour_source(mat.node_tree)
            if src is None:
                continue
            restores.append(emit(mat.node_tree, src[0], src[1]))
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    centre, radius = (lo + hi) / 2, max((hi - lo).length / 2, 1e-3)
    cam_data = bpy.data.cameras.new("rebake_check_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = radius * 2.1
    cam_data.clip_end = radius * 10
    cam = bpy.data.objects.new("rebake_check_cam", cam_data)
    scene.collection.objects.link(cam)
    prev_cam = scene.camera
    scene.camera = cam
    paths = []
    for i in range(RENDER_VIEWS):
        a = 2 * math.pi * i / RENDER_VIEWS
        cam.location = centre + Vector((math.cos(a), math.sin(a), 0.0)) * radius * 3
        cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
        if lit:   # the sun a little above and to the left of the camera, so relief shows
            sun.rotation_euler = (centre - cam.location - Vector((0, 0, radius)) + Vector(
                (-math.sin(a), math.cos(a), 0.0)) * radius).to_track_quat("-Z", "Y").to_euler()
        path = Path(folder) / f"{tag}_{i}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        paths.append(path)
    scene.camera = prev_cam
    bpy.data.objects.remove(cam, do_unlink=True)
    bpy.data.cameras.remove(cam_data)
    if lit:
        bpy.data.objects.remove(sun, do_unlink=True)
        bpy.data.lights.remove(sun_data)
        scene.cycles.samples = SAMPLES
    for restore in restores:
        restore()
    return paths


def compare_renders(bpy, before, after):
    """Mean and max absolute RGB difference (8-bit levels) over the pixels both renders cover."""
    total, count, worst = 0.0, 0, 0.0
    for a, b in zip(before, after):
        ia, ib = bpy.data.images.load(str(a)), bpy.data.images.load(str(b))
        n = ia.size[0] * ia.size[1] * 4
        pa, pb = array("f", bytes(4 * n)), array("f", bytes(4 * n))
        ia.pixels.foreach_get(pa)
        ib.pixels.foreach_get(pb)
        for i in range(0, n, 4):
            if pa[i + 3] > 0.5 and pb[i + 3] > 0.5:
                d = (abs(pa[i] - pb[i]) + abs(pa[i + 1] - pb[i + 1]) + abs(pa[i + 2] - pb[i + 2])) / 3
                total += d
                count += 1
                worst = max(worst, d)
        bpy.data.images.remove(ia)
        bpy.data.images.remove(ib)
    return {"views": len(before), "pixels": count, "mean_levels": round(total / count * 255, 2) if count else None,
            "max_levels": round(worst * 255, 1)}


# ---------------------------------------------------------------- the step
def rebake(bpy, va, obj, texture_px, report, check=True, png=False):
    """Re-unwrap obj and bake its textures onto the new layout. Fills report (a dict); returns True when the
    result passed the check (or no check could run). png: every map as PNG (map_format). Raises RuntimeError on a
    Blender failure."""
    t0 = time.monotonic()
    scene = bpy.context.scene
    mesh = obj.data
    mats = materials(obj)
    sources = [n.image for m in mats for n in image_nodes(m)]
    size = texture_px or max([max(img.size) for img in sources if max(img.size) > 0] + [0]) or TEXTURE_DEFAULT
    size = min(TEXTURE_SIZES, key=lambda s: abs(s - size))
    report.update({"texture_px": size, "source_images": sorted({f"{i.name} {i.size[0]}x{i.size[1]}" for i in sources}),
                   "materials": len(mats)})
    if mesh.uv_layers:
        report["uv_coverage_before"], report["uv_islands_before"] = uv_stats(va, mesh, mesh.uv_layers.active
                                                                             or mesh.uv_layers[0])
    else:
        report["uv_coverage_before"], report["uv_islands_before"] = 0.0, 0
        mesh.uv_layers.new(name=VENDOR_UV)
    folder = tempfile.mkdtemp(prefix="rebake_check_") if check and sources else None
    if folder:
        setup_render(bpy, scene)
        before = render_views(bpy, scene, obj, mats, folder, "before")
        before_lit = render_views(bpy, scene, obj, mats, folder, "before_lit", lit=True)
    unwrap(bpy, obj, size)
    if sources:
        undo, skipped = read_through(mats, VENDOR_UV)
        setup_render(bpy, scene)   # the bake runs in Cycles too
        transfer_maps(bpy, obj, mats, size, report, png=png)
        undo()
        for name in skipped:
            print(f"[WARN] {name} is read through its own Vector input and was left on the old layout")
    else:
        report["maps"] = []
        report["bake"] = None
    mesh.uv_layers.remove(mesh.uv_layers[VENDOR_UV])
    mesh.uv_layers.active = mesh.uv_layers[NEW_UV]
    mesh.uv_layers[NEW_UV].active_render = True
    report["uv_coverage_after"], report["uv_islands_after"] = uv_stats(va, mesh, mesh.uv_layers[NEW_UV])
    ok = True
    if folder:
        after = render_views(bpy, scene, obj, mats, folder, "after")
        after_lit = render_views(bpy, scene, obj, mats, folder, "after_lit", lit=True)
        report["check"] = compare_renders(bpy, before, after)
        report["check_lit"] = compare_renders(bpy, before_lit, after_lit)
        for p in before + after + before_lit + after_lit:
            p.unlink()
        Path(folder).rmdir()
        for what, rep, warn, fail in (("colours", report["check"], COLOUR_WARN, COLOUR_FAIL),
                                      ("lit renders", report["check_lit"], LIT_WARN, LIT_FAIL)):
            mean = rep["mean_levels"]
            if mean is None:
                print(f"[WARN] the {what} check covered no pixels in common: nothing compared")
            elif mean > fail:
                print(f"[FAIL] the rebaked {what} differ from the original by {mean:.1f} levels on average (over "
                      f"{fail:g}): the bake lost or misplaced a texture")
                ok = False
            elif mean > warn:
                print(f"[WARN] the rebaked {what} differ from the original by {mean:.1f} levels on average (over "
                      f"{warn:g}): look at the model before shipping it")
    else:
        report["check"] = report["check_lit"] = None
    report["seconds"] = round(time.monotonic() - t0, 1)
    kinds = ", ".join(f"{m['source']} ({m['kind']}{', alpha' if m['alpha'] else ''}, {m['format']}"
                      f"{' ' + str(m['quality']) if m['quality'] else ''})" for m in report["maps"]) or "no textures"
    print(f"[ OK ] rebake: UV coverage {report['uv_coverage_before']:.0%} ({report['uv_islands_before']} islands) -> "
          f"{report['uv_coverage_after']:.0%} ({report['uv_islands_after']} islands) at {size} px, {kinds}, "
          f"{report['seconds']} s" + (f", check mean {report['check']['mean_levels']} levels flat, "
                                      f"{report['check_lit']['mean_levels']} lit" if report.get("check")
                                      and report["check"]["mean_levels"] is not None else ""))
    return ok


def run(args):
    src, out = Path(args.asset), Path(args.out)
    if not src.is_file():
        print(f"[ENV ] mesh not found: {src}", file=sys.stderr)
        return 2
    if out.suffix.lower() != ".glb":
        print("[ENV ] --out must end in .glb", file=sys.stderr)
        return 2
    if out.exists() and not args.overwrite:
        print(f"[ENV ] {out} exists (use --overwrite)", file=sys.stderr)
        return 2
    bpy, va, pe = load_modules()
    if bpy is None:
        return 2
    try:
        va.import_asset(bpy, src.resolve())
    except ValueError as exc:
        print(f"[ENV ] {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"[FAIL] import failed: {exc}", file=sys.stderr)
        return 1
    scene = bpy.context.scene
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    meshes = [o for o in scene.objects if o.type == "MESH"]
    if not meshes:
        print("[FAIL] no mesh in the file", file=sys.stderr)
        return 1
    if len(meshes) > 1:
        if not args.join:
            print(f"[ENV ] {len(meshes)} mesh objects: one atlas needs one mesh, pass --join", file=sys.stderr)
            return 2
        pe.apply_transforms(bpy, scene)
        pe.join_meshes(bpy, scene)
        meshes = [o for o in scene.objects if o.type == "MESH"]
    obj = meshes[0]
    obj.data.calc_loop_triangles()
    report = {"source": src.name, "tris": len(obj.data.loop_triangles)}
    if not args.no_weld:
        report["welded_vertices"] = weld(obj)
    ok = rebake(bpy, va, obj, args.texture, report, check=not args.no_check, png=args.png)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not ok:
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(out.resolve()), **pe.GLTF_PRESET)
    print(f"[ OK ] {out}")
    return 0


def main():
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        args = parse_args(script_argv())
    except SystemExit as exc:
        return int(exc.code or 0)
    DEBUG = args.debug
    try:
        return run(args)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        if DEBUG:
            raise
        return 1
    except Exception as exc:  # keep the exit-code contract even on surprises
        print(f"[ENV ] rebake crashed: {exc!r}. Re-run with --debug and paste the output.", file=sys.stderr)
        if DEBUG:
            raise
        return 2


if __name__ == "__main__":
    import prep_export   # its end_process: the bpy module crashes while the process ends on Windows
    prep_export.end_process(main())

# ---------------------------------------------------------------------------
# shader_check.py
# Purpose : Compiles every kit shader recipe as an Unreal material and, in render mode, draws each into a 64x64
#           render target and writes <out>/<name>.png for tools/shaders/shader_ref.py compare.
# Usage   : python tools/dev.py check            (compile mode)
#           python tools/dev.py smoke --shaders  (render mode)
#           Both start the full editor off-screen with -ExecCmds="py <this file>" (the pythonscript commandlet runs on
#           the Null RHI, which compiles and draws nothing); GAMEKIT_SHADER_MODE and GAMEKIT_SHADER_OUT steer it.
# Notes   : Prints SHADER_OK <name> / SHADER_FAIL <name> <why> and SHADER_CHECK_DONE <recipes> <failed>.
#           Pseudocode
#             import the check inputs (data/shaders/inputs) as linear point-filtered textures in /Game/KitShaders/Check
#             per recipe: two opaque variants (rgb, alpha) of the recipe's material
#             each editor tick: wait until every variant's pixel shader is compiled (its instruction count is above
#             zero); when none has compiled for STALL_S (or COMPILE_WAIT_S passed), the rest did not compile
#             (the log's LogShaderCompilers / LogMaterial lines say why)
#             render mode: draw both variants into an RGBA16F target (linear), read it back, combine -> 8-bit PNG
#             quit on a later tick (quitting inside the tick that drew crashed UE 5.8 on exit)
#           Nothing is saved: the check's assets live only in this editor session.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os
import struct
import time
import traceback
import zlib

import unreal

from kit_shaders import kit_materials
from kit_shaders.kit_recipes import RECIPES

# ---- Tunables ------------------------------------------------------------------
SIZE = 64                                   # the check canvas (tools/shaders/recipes.json)
DEST = "/Game/KitShaders/Check"
COMPILE_WAIT_S = 600                        # ceiling: first compiles of a fresh project fill the shader cache
STALL_S = 30                                # no further material compiled for this long: the rest failed
INPUT_DIR = "data/shaders/inputs"
MODE = os.environ.get("GAMEKIT_SHADER_MODE", "compile")
OUT = os.environ.get("GAMEKIT_SHADER_OUT", "")


def say(text):
    unreal.log(text)                        # reaches the log as "LogPython: <text>", which dev.py reads


def png(rows):
    """An 8-bit RGBA PNG from rows (top first) of bytes."""
    raw = b"".join(b"\x00" + bytes(row) for row in rows)

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    head = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def byte(v):
    return max(0, min(255, int(round(v * 255.0))))


class Check:
    def __init__(self):
        self.world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        self.started = self.progress_at = time.time()
        self.compiled_count = 0
        self.materials = {}
        self.failed = 0
        self.done = False
        self.quit_in = -1
        project = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
        textures = {}
        for name, recipe in RECIPES.items():
            try:
                for inp in [recipe["main"]] + ([recipe["aux"]] if recipe["aux"] else []):
                    if inp not in textures:
                        file = "sphere_normal" if inp == "sphere" else inp
                        textures[inp] = kit_materials.import_texture(
                            os.path.join(project, INPUT_DIR, f"{file}.png").replace("\\", "/"), DEST, f"T_{file}")
                main = textures[recipe["main"]]
                aux = textures.get(recipe["aux"]) if recipe["aux"] else None
                self.materials[name] = {view: kit_materials.build(name, DEST, view, main, aux, f"M_Check_{name}_{view}")
                                        for view in ("rgb", "a")}
            except Exception as exc:   # an import or a graph that cannot be built: report it, check the rest
                self.failed += 1
                say(f"SHADER_FAIL {name} {exc}")

    def compiled(self, material):
        return unreal.MaterialEditingLibrary.get_statistics(material).num_pixel_shader_instructions > 0

    def draw(self, material):
        rt = unreal.RenderingLibrary.create_render_target2d(self.world, SIZE, SIZE,
                                                            unreal.TextureRenderTargetFormat.RTF_RGBA16F,
                                                            unreal.LinearColor(0, 0, 0, 0), False)
        unreal.RenderingLibrary.clear_render_target2d(self.world, rt, unreal.LinearColor(0, 0, 0, 0))
        unreal.RenderingLibrary.draw_material_to_render_target(self.world, rt, material)
        pixels = unreal.RenderingLibrary.read_render_target_raw(self.world, rt, False)
        if not pixels or len(pixels) != SIZE * SIZE:
            raise RuntimeError("the render target could not be read back")
        return pixels

    def finish(self):
        for name, views in self.materials.items():
            if not all(self.compiled(m) for m in views.values()):
                self.failed += 1
                say(f"SHADER_FAIL {name} the material did not compile (see the LogShaderCompilers / LogMaterial "
                    "lines in this log)")
                continue
            if MODE != "render":
                say(f"SHADER_OK {name}")
                continue
            try:
                rgb, alpha = self.draw(views["rgb"]), self.draw(views["a"])
                rows = []
                for y in range(SIZE):
                    row = []
                    for x in range(SIZE):
                        c, a = rgb[y * SIZE + x], alpha[y * SIZE + x]
                        row += [byte(c.r), byte(c.g), byte(c.b), byte(a.r)]
                    rows.append(row)
                with open(os.path.join(OUT, f"{name}.png"), "wb") as f:
                    f.write(png(rows))
                say(f"SHADER_OK {name}")
            except Exception as exc:
                self.failed += 1
                say(f"SHADER_FAIL {name} {exc}")
        say(f"SHADER_CHECK_DONE {len(RECIPES)} {self.failed}")

    def tick(self, _dt):
        if self.quit_in > 0:
            self.quit_in -= 1
            if self.quit_in == 0:
                unreal.unregister_slate_post_tick_callback(HANDLE)
                unreal.SystemLibrary.quit_editor()
            return
        if self.done:
            return
        every = [m for views in self.materials.values() for m in views.values()]
        count = sum(1 for m in every if self.compiled(m))
        now = time.time()
        if count != self.compiled_count:
            self.compiled_count, self.progress_at = count, now
        stalled = count > 0 and now - self.progress_at > STALL_S
        if count < len(every) and not stalled and now - self.started < COMPILE_WAIT_S:
            return
        self.done = True
        try:
            self.finish()
        except Exception:                     # a slate tick callback drops exceptions silently: say it
            say("SHADER_FAIL * " + " | ".join(traceback.format_exc().splitlines()))
            say(f"SHADER_CHECK_DONE {len(RECIPES)} {len(RECIPES)}")
        finally:
            self.quit_in = 5                  # a few ticks later: quitting inside this tick crashed UE 5.8


if MODE == "render" and not OUT:
    say("SHADER_FAIL * GAMEKIT_SHADER_OUT is not set")
    say(f"SHADER_CHECK_DONE {len(RECIPES)} {len(RECIPES)}")
    unreal.SystemLibrary.quit_editor()
else:
    if OUT:
        os.makedirs(OUT, exist_ok=True)
    CHECK = Check()
    HANDLE = unreal.register_slate_post_tick_callback(CHECK.tick)

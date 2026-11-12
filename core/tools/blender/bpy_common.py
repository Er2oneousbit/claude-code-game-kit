#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# bpy_common.py
# Purpose : Three things every kit script that runs in Blender (or the bpy module) needs and used to get wrong one at
#           a time (#292): the clip names Blender 4.2's glTF importer gives actions, clips keyed at a frame rate other
#           than the scene's (Tripo's 30 fps in a 24 fps scene: the exporter's integer-frame sampling then misses the
#           closing pose, so a loop stops closing), and the bpy module crashing while the process ends on Windows.
# Usage   : from a script inside Blender, after `import bpy`:
#             import bpy_common as bc
#             bc.adopt_clip_names(bpy)                   # actions named "<clip>_<armature>" take their clip's name
#             fps = bc.conform_clip_fps(bpy, scene, bpy.data.actions)   # the scene follows the clips' key rate
#             bc.end_process(bpy, code)                  # the last line of __main__: sys.exit, or TerminateProcess
#           tools/bozzetto/rig_finish.py and rig_chain.py and tools/blender/render_sprites.py import it; a copy of one
#           script without this file beside it loses only these three fixes.
# Needs   : Blender 4.2+ or the bpy module (bpy is passed in, never imported here, so plain Python can import this
#           file and the exam can test clip_fps without Blender)
# Notes   : Clip names: Blender 4.2's glTF importer names each action "<clip>_<object>" (walk_Armature, bob_Cube)
#           while the NLA track it makes keeps the clip's own name; 4.3+ name the action after the clip. The action
#           takes the track's name back, so `--action walk` finds it and an export keeps "walk".
#           Frame rate: glTF stores times, not frames; Blender's importer lays keys on the scene's frame grid
#           (24 fps by default), so a 30 fps clip gets keys every 0.8 frames. The glTF exporter samples clips at
#           whole frames from int(start) to int(end): a clip keyed 0.8 .. 56.8 is written as frames 0 .. 56, and
#           frame 56 is the pose 0.8 frames before the key that closed the loop (Tripo's walk came back with a
#           0.03 quaternion seam that way; its idle crossed rig_chain's loop tolerance and needed --loop). The fix:
#           find the smallest common frame rate (the scene's own first, then 12 .. 60) at which every key of every
#           clip sits on a whole frame, scale the keys to it and set the scene to it. Durations do not change (a key
#           at frame 0.8 of 24 fps and at frame 1 of 30 fps are both 1/30 s). Clips with no common rate up to 60 fps
#           (two rates in one file) are left alone, with a warning. NLA strips are not rescaled: callers remove or
#           mute them (every kit script does) before they play a clip.
#           Exit: the bpy module (no Blender executable) crashes with 0xC0000005 while the process ends on Windows
#           (seen 2026-11-11: bpy 4.2 after any glTF export, bpy 5.3 after a render), which would hide the script's
#           exit code behind the crash's. Everything is written by then, so the process is ended without unloading
#           its libraries (os._exit crashed 5.3 the same way); the handle types matter, an untyped
#           GetCurrentProcess() came back truncated and the call failed. Inside Blender itself this is sys.exit.
# Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   adopt_clip_names: for every object with NLA tracks, for every strip: the action named "<track>_<...>" is renamed
#                     to the track's name when no action has that name yet -> the renamed pairs
#   clip_fps(frames, fps): key frames -> the first rate of (fps, 12, 15, 20, 24, 25, 30, 48, 50, 60) that puts every
#                     key within KEY_TOLERANCE of a whole frame, else None
#   conform_clip_fps: gather every key frame of the actions -> clip_fps -> same rate: nothing; a rate: scale every
#                     key by new / old and snap it to the whole frame (handles shifted along), scale a manual frame
#                     range, set scene fps, print [info]; none: [WARN]
#   end_process: Blender executable -> sys.exit(code); the module on Windows -> flush, TerminateProcess(code)
import sys

RATES = (12, 15, 20, 24, 25, 30, 48, 50, 60)   # common frame rates, the lowest that fits wins
KEY_TOLERANCE = 0.01                           # frames: how far from a whole frame a key may sit and still count


def fcurves_of(act):
    """Every F-curve of an action: the legacy list before Blender 5.0, the layered channel bags after."""
    if hasattr(act, "fcurves"):
        return list(act.fcurves)
    out = []
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for bag in strip.channelbags:
                out += list(bag.fcurves)
    return out


def adopt_clip_names(bpy):
    """Rename actions Blender 4.2's glTF importer called "<clip>_<object>" back to the clip's name (the NLA track's).
    Returns [(old, new)]."""
    renamed = []
    for obj in bpy.data.objects:
        ad = obj.animation_data
        if ad is None:
            continue
        for track in ad.nla_tracks:
            for strip in track.strips:
                act = strip.action
                if act is None or act.name == track.name or track.name in bpy.data.actions:
                    continue
                if not act.name.startswith(track.name + "_"):
                    continue
                renamed.append((act.name, track.name))
                act.name = track.name
    return renamed


def clip_fps(frames, scene_fps):
    """The lowest common frame rate at which every key frame (laid out at scene_fps) sits on a whole frame: the
    scene's own rate first, then RATES in order. None when none fits (or there are no keys)."""
    frames = [float(f) for f in frames]
    if not frames:
        return None
    for rate in (scene_fps,) + tuple(r for r in RATES if r != scene_fps):
        k = rate / scene_fps
        if all(abs(f * k - round(f * k)) <= KEY_TOLERANCE for f in frames):
            return rate
    return None


def conform_clip_fps(bpy, scene, actions, quiet=False):
    """Scale the actions' keys so they sit on whole frames and set the scene's frame rate to match; the clips keep
    their length in seconds. Returns the scene's frame rate afterwards (unchanged when the keys already fit, or when
    no common rate up to 60 fps exists)."""
    old = scene.render.fps / scene.render.fps_base
    frames = [k.co[0] for act in actions for fc in fcurves_of(act) for k in fc.keyframe_points]
    if not frames:               # no clips (a statue, or a rig that gets its clips keyed here): nothing to follow
        return old
    rate = clip_fps(frames, old)
    if rate is None:
        if not quiet:
            print(f"[WARN] the clips' keys fit no common frame rate up to {RATES[-1]} fps (keys at more than one rate?):"
                  f" the scene stays at {old:g} fps and the export samples whole frames, so a loop may not close exactly")
        return old
    if abs(rate - old) < 1e-9:
        return old
    k = rate / old
    for act in actions:
        for fc in fcurves_of(act):
            for kp in fc.keyframe_points:
                # snapped to the whole frame: the imported frame is a float32 time x 24, and scaled back it can land
                # 6e-6 under the frame (a 71-key walk did), where the exporter's int(end) drops the closing key
                snapped = round(kp.co[0] * k)
                shift = snapped - kp.co[0]
                kp.co[0] = snapped
                kp.handle_left[0] += shift
                kp.handle_right[0] += shift
            fc.update()
        if getattr(act, "use_frame_range", False):
            act.frame_end *= k
            act.frame_start *= k
    scene.render.fps, scene.render.fps_base = int(rate), 1.0      # RATES are whole numbers
    if not quiet:
        print(f"[info] clips keyed at {rate:g} fps: the scene follows them (it was {old:g}), so every key is a whole "
              "frame and the export keeps the exact poses, the loop's closing one included")
    return rate


def end_process(bpy, code):
    """The last line of a Blender-side script: exit with `code`. With the bpy module on Windows, end the process
    without unloading its libraries (see Notes), so the exit code is the script's and not the crash's."""
    code = int(code or 0)
    if not getattr(bpy.app, "binary_path", "") and sys.platform == "win32":
        sys.stdout.flush()
        sys.stderr.flush()
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k32.TerminateProcess(k32.GetCurrentProcess(), code)
    sys.exit(code)

"""Python control wrapper for the GNM eye rig: a modular script that sets gaze coordinates and eyelid
opening and closing.

Use it from the command line (Blender runs headless):

    blender -b --factory-startup gnm_rig/out/heads/T02.blend -P eyes.py -- --look 20 5 --eyelids 0.7 --render out.png
    blender -b --factory-startup gnm_rig/out/heads/T02.blend -P eyes.py -- --look -15 -10 --eyelids 0.4 --pupil 0.5 \
            --brows 0.6 --identity ID_00=1.5 ID_03=-1 --tex T05 --render out.png --state

or inside Blender (Scripting tab / Python console) with a GNM head .blend open:

    import sys; sys.path.append(r"<path to repo>")
    import eyes
    eyes.look(15, 5)              # gaze: 15 deg towards screen-right, 5 deg up, target 1 m away
    eyes.eyelids(0.6)             # 1 = fully open ... 0 = closed (continuous); both eyes, or left=/right=
    eyes.blink(frame=30)          # keyframe a natural blink (fast close, slower reopen)
    eyes.key(1); eyes.look(-20, 0); eyes.key(20)   # keyframe a gaze shift on the Timeline
    print(eyes.state())           # gaze target, per-eye rotation angles, lid openings, controls
    eyes.render("still.png")

Gaze coordinates are degrees in the viewer's frame: h > 0 = towards screen-right, v > 0 = up. Both eyes rotate about
their own centres and converge on the same target. The eyelids follow vertical gaze automatically (follow_gaze),
coordinated with any explicit opening you set.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "gnm_rig"))
import materials as _MT  # noqa: E402
import stage as _S  # noqa: E402

DEFAULT_DIST = 1.0
_CONTROLS = ("blink_L", "blink_R", "wide", "squint", "brow_raise", "brow_down", "pupil", "auto_lids")


# ------------------------------------------------------------------------------------------------ gaze
def look(h=0.0, v=0.0, dist=DEFAULT_DIST):
    """Point both eyes at a target `dist` metres away, h deg right(+)/left(-) and v deg up(+)/down(-)."""
    _S.set_gaze(h, v, dist)
    _S.refresh()
    return state()["eyes"]


def look_at(point):
    """Point both eyes at a world-space point (x, y, z) in metres."""
    t = _S.target()
    t.location = t.parent.matrix_world.inverted() @ Vector(point)
    _S.refresh()
    return state()["eyes"]


# ------------------------------------------------------------------------------------------------ eyelids
def eyelids(open=1.0, left=None, right=None):
    """Eyelid opening, continuous: 1 = fully open, 0.5 = half closed, 0 = closed. Per eye with left=/right=."""
    lo = open if left is None else left
    ro = open if right is None else right
    _S.set_ctrl(blink_L=1.0 - _clamp(lo), blink_R=1.0 - _clamp(ro))
    return {"left": lo, "right": ro}


def follow_gaze(amount=1.0):
    """How strongly the lids follow vertical gaze (0 = off, 1 = natural)."""
    _S.set_ctrl(auto_lids=_clamp(amount))


def blink(frame, duration=0.31, amount=1.0, fps=None):
    """Keyframe a natural blink starting at `frame`: ~30% of the time closing, ~10% held, ~60% reopening."""
    fps = fps or bpy.context.scene.render.fps
    n = max(3, int(round(duration * fps)))
    f_close, f_hold = frame + max(1, int(0.3 * n)), frame + max(2, int(0.4 * n))
    for f, val in ((frame - 1, 0.0), (f_close, amount), (f_hold, amount), (frame + n, 0.0)):
        _S.key_ctrl(f, blink_L=val, blink_R=val)


# ------------------------------------------------------------------------------------------------ expression
def pupil(size=0.0):
    """Pupil size: -1 constricted (bright light) .. 0 GNM default .. 2 dilated."""
    _S.set_ctrl(pupil=max(-1.0, min(2.0, size)))


def brows(raise_=0.0, down=0.0):
    _S.set_ctrl(brow_raise=_clamp(raise_), brow_down=_clamp(down))


def expression(wide=0.0, squint=0.0):
    _S.set_ctrl(wide=_clamp(wide), squint=_clamp(squint))


def identity(**sliders):
    """Face shape: GNM identity sliders, e.g. identity(ID_00=1.5, ID_03=-1). Range -3..3. Eyes stay seated."""
    kb = bpy.data.objects["GNM_Head"].data.shape_keys.key_blocks
    for name, val in sliders.items():
        kb[name].value = max(-3.0, min(3.0, float(val)))
    _S.refresh()


def texture(tex_id):
    """Apply a texture set from textures/ (T01..T08)."""
    _staged["tex"] = tex_id
    return _MT.apply(tex_id)


def reset():
    _S.set_ctrl(blink_L=0, blink_R=0, wide=0, squint=0, brow_raise=0, brow_down=0, pupil=-1.0, auto_lids=1)
    look(0, 0)


# ------------------------------------------------------------------------------------------------ timeline
def key(frame):
    """Keyframe the current gaze target and all controls at `frame` (Timeline animation)."""
    _S.target().keyframe_insert("location", frame=frame)
    r = _S.rig()
    for c in _CONTROLS:
        r.keyframe_insert(f'["{c}"]', frame=frame)


# ------------------------------------------------------------------------------------------------ query
def state():
    """Current gaze target, per-eye rotation (deg) and line of sight, lid openings and controls."""
    r = _S.rig()
    out = {"target_world": list(_S.target().matrix_world.translation), "eyes": {}, "controls": {}}
    for side, b in (("left", "eye.L"), ("right", "eye.R")):
        m = r.matrix_world @ r.pose.bones[b].matrix
        d = m.col[1].xyz.normalized()                     # bone +Y = line of sight
        yaw = math.degrees(math.atan2(d.x, -d.y))         # + = towards screen-right
        pitch = math.degrees(math.asin(max(-1, min(1, d.z))))
        out["eyes"][side] = {"center": list(m.translation), "dir": list(d), "yaw_deg": round(yaw, 2),
                             "pitch_deg": round(pitch, 2),
                             "lid_open": round(1.0 - float(r[f"blink_{side[0].upper()}"]), 3)}
    for c in _CONTROLS:
        out["controls"][c] = round(float(r[c]), 3)
    return out


# ------------------------------------------------------------------------------------------------ render
_staged = {"done": False, "tex": None}


def _ensure_texture():
    """A freshly built head has blank materials: apply the matching set (heads/T05.blend -> T05, else T02)."""
    if _staged["tex"]:
        return
    nt = bpy.data.materials["MAT_skin"].node_tree
    if not any(n.bl_idname == "ShaderNodeTexImage" for n in nt.nodes):
        stem = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
        texture(stem if stem[:1] == "T" and stem[1:].isdigit() else "T02")
    _staged["tex"] = True


def render(path, res=(1920, 1080), samples=64, view="eyes"):
    """Render a still of the current state. Sets up the standard stage (lights, world, camera) on first use."""
    sc = bpy.context.scene
    _ensure_texture()
    if not _staged["done"]:
        mid = _S.eye_mid()
        _S.cycles(res, samples)
        _S.world("interior.exr", 0.28, rot=2.4)
        _S.portrait_lights(mid)
        _S.backdrop(mid)
        offs = {"eyes": (Vector((0, -0.36, 0.005)), Vector((0, 0, 0)), 100),
                "face": (Vector((0, -0.66, -0.025)), Vector((0, 0, -0.03)), 85),
                "portrait": (Vector((-0.30, -0.58, 0.02)), Vector((0, 0, -0.045)), 70)}[view]
        _S.camera("CAM_Eyes", mid + offs[0], mid + offs[1], lens=offs[2], fstop=5.6, focus=mid + Vector((0, -0.012, 0)))
        _staged["done"] = True
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.cycles.samples = samples
    sc.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)
    return sc.render.filepath


def _clamp(x):
    return max(0.0, min(1.0, float(x)))


# ------------------------------------------------------------------------------------------------ CLI
def _cli(argv):
    import argparse
    import json
    ap = argparse.ArgumentParser(prog="eyes.py", description="GNM eye control wrapper")
    ap.add_argument("--look", nargs=2, type=float, metavar=("H", "V"), help="gaze in degrees (viewer frame)")
    ap.add_argument("--dist", type=float, default=DEFAULT_DIST)
    ap.add_argument("--eyelids", type=float, help="opening 0..1 (both eyes)")
    ap.add_argument("--left-lid", type=float)
    ap.add_argument("--right-lid", type=float)
    ap.add_argument("--pupil", type=float)
    ap.add_argument("--brows", type=float, help="brow raise 0..1")
    ap.add_argument("--frown", type=float, help="brow down 0..1")
    ap.add_argument("--wide", type=float)
    ap.add_argument("--squint", type=float)
    ap.add_argument("--identity", nargs="*", default=[], metavar="ID_xx=VALUE")
    ap.add_argument("--tex", default=None)
    ap.add_argument("--render", default=None, metavar="PATH")
    ap.add_argument("--view", default="eyes", choices=["eyes", "face", "portrait"])
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--state", action="store_true", help="print the rig state as JSON")
    a = ap.parse_args(argv)
    reset()
    if a.tex:
        texture(a.tex)
    if a.identity:
        identity(**{k: float(v) for k, v in (s.split("=") for s in a.identity)})
    if a.look:
        look(a.look[0], a.look[1], a.dist)
    if a.eyelids is not None or a.left_lid is not None or a.right_lid is not None:
        eyelids(a.eyelids if a.eyelids is not None else 1.0, left=a.left_lid, right=a.right_lid)
    if a.pupil is not None:
        pupil(a.pupil)
    if a.brows is not None or a.frown is not None:
        brows(a.brows or 0.0, a.frown or 0.0)
    if a.wide is not None or a.squint is not None:
        expression(a.wide or 0.0, a.squint or 0.0)
    if a.state or not a.render:
        print(json.dumps(state(), indent=2))
    if a.render:
        print("rendered", render(a.render, samples=a.samples, view=a.view))


if __name__ == "__main__":
    _cli(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

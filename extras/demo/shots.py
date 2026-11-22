"""Blender shots for the GNM demo video (run headless, one shot per call):

    blender -b --factory-startup gnm_expression_timeline.blend -P demo/shots.py -- --shot timeline
    blender -b --factory-startup gnm_rig/out/heads/T05.blend    -P demo/shots.py -- --shot identity
    blender -b --factory-startup gnm_rig/out/heads/T03.blend    -P demo/shots.py -- --shot orbit

timeline : renders the submitted Timeline .blend exactly as delivered (its own keyframes, camera and lights)
identity : GNM identity sliders morph the face while the eyes keep looking around (driven through eyes.py)
orbit    : slow 3/4 camera orbit; the eyes keep eye contact with the moving camera (eyes.look_at)

Frames go to demo/build/<shot>/####.png.  Set XR_CYCLES_DEVICE=CUDA on NVIDIA drivers older than 580.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "gnm_rig"))
import eyes  # noqa: E402
import stage as S  # noqa: E402


def stage_face(view, samples, res):
    eyes._ensure_texture()
    S.cycles(res, samples, 30)
    sc = bpy.context.scene
    sc.render.use_motion_blur = True
    sc.render.motion_blur_shutter = 0.35
    S.world("interior.exr", 0.28, rot=2.4)
    mid = S.eye_mid()
    S.portrait_lights(mid)
    S.backdrop(mid)
    off, look, lens = {"portrait": (Vector((-0.30, -0.58, 0.02)), Vector((0, 0, -0.045)), 70),
                       "face": (Vector((0, -0.66, -0.025)), Vector((0, 0, -0.03)), 85)}[view]
    cam = S.camera("CAM_Demo", mid + off, mid + look, lens=lens, fstop=5.6, focus=mid + Vector((0, -0.012, 0)))
    return mid, cam


def key_gaze(f, h, v, dist=1.0):
    # set the target directly: eyes.look() also refreshes the depsgraph, which would re-evaluate the existing
    # keys and overwrite the new location before it is keyed
    S.set_gaze(h, v, dist)
    S.target().keyframe_insert("location", frame=f)


def key_gaze_point(f, point):
    t = S.target()
    t.location = t.parent.matrix_world.inverted() @ Vector(point)
    t.keyframe_insert("location", frame=f)


def shot_identity(n=210):
    """Face shape changes through GNM identity sliders; eyes glance and blink throughout (eyes stay seated)."""
    eyes.reset()
    kb = bpy.data.objects["GNM_Head"].data.shape_keys.key_blocks
    # (slider, value) keyed at successive beats, then back to the textured identity
    beats = [(1, {}), (35, {"ID_00": 2.6}), (70, {"ID_00": -2.2, "ID_02": 2.4}), (105, {"ID_01": 2.6, "ID_04": -2.0}),
             (140, {"ID_03": -2.6, "ID_05": 2.4}), (175, {"ID_06": 2.6, "ID_01": -2.0}), (n, {})]
    names = sorted({k for _, d in beats for k in d})
    for f, d in beats:
        for k in names:
            kb[k].value = d.get(k, 0.0)
            kb[k].keyframe_insert("value", frame=f)
    gaze = [(1, 0, 0), (20, -14, 3), (55, 12, 2), (90, 4, 9), (125, -10, -6), (160, 15, -2), (195, 0, 1)]
    prev = None
    for f, h, v in gaze:                 # fixation held, then a 3-frame (100 ms) saccade to the next point
        if prev:
            key_gaze(f - 3, *prev)
        key_gaze(f, h, v)
        prev = (h, v)
    for f in (38, 108, 176):
        eyes.blink(f)
    return n


def shot_orbit(cam, mid, n=180):
    """Camera arcs from the subject's right 3/4 to the left 3/4; the eyes hold eye contact with the lens."""
    eyes.reset()
    r = (cam.location - mid).length
    for i in range(n):
        f = i + 1
        k = 0.5 - 0.5 * math.cos(math.pi * i / (n - 1))          # ease in/out
        ang = math.radians(-32 + 64 * k)
        loc = mid + Vector((r * math.sin(ang), -r * math.cos(ang), 0.02))
        cam.location = loc
        S.aim(cam, mid + Vector((0, 0, -0.035)))
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
        if i % 3 == 0:          # smooth pursuit of the moving lens
            key_gaze_point(f, loc)
    for f in (40, 128):
        eyes.blink(f)
    return n


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", required=True, choices=["timeline", "identity", "orbit"])
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--start", type=int, default=None)
    ap.add_argument("--test", default=None, help="comma-separated frames: render these as stills only")
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:])
    res = tuple(int(v) for v in a.res.split("x"))
    sc = bpy.context.scene
    if a.shot == "timeline":
        S.cycles(res, a.samples, sc.render.fps)            # GPU device + quality settings only
        sc.render.use_motion_blur = True
        sc.render.motion_blur_shutter = 0.35
        n = sc.frame_end
    else:
        mid, cam = stage_face("portrait" if a.shot == "orbit" else "face", a.samples, res)
        n = shot_identity() if a.shot == "identity" else shot_orbit(cam, mid)
        sc.frame_start, sc.frame_end = 1, n
    if a.test:
        for f in (int(x) for x in a.test.split(",")):
            sc.frame_set(f)
            sc.render.filepath = os.path.join(ROOT, "demo", "build", f"test_{a.shot}_{f:04d}.png")
            bpy.ops.render.render(write_still=True)
        return
    if a.start:
        sc.frame_start = a.start
    out = os.path.join(ROOT, "demo", "build", a.shot)
    os.makedirs(out, exist_ok=True)
    sc.render.filepath = os.path.join(out, "####")
    sc.render.use_overwrite = False                      # resumable
    bpy.ops.render.render(animation=True)
    print("frames", sc.frame_start, "-", sc.frame_end, "->", out, flush=True)


if __name__ == "__main__":
    main()

"""Look-development shots for the skin and eye upgrades: the deliverable framings plus close framings like the
reference reel, rendered under the project's own studio light (default) so before/after compare like for like.
--light lowkey gives the reference reel's dark single-key look instead (comparison only; it darkens the skin).

blender -b --factory-startup gnm_rig/out/heads/T02.blend -P gnm_rig/lookdev_ref.py -- [--tex T02]
        [--shots portrait,eyes,macro,three_q,wide] [--samples 128] [--res 1920x1080] [--out DIR] [--light studio|lowkey]

Shots (subject's left eye, the eye nearer the camera; Blender: face looks down -Y, +X = subject's left):
  wide     half face at 3/4, eye and nose bridge (reference: wide 3/4 close-up)
  three_q  macro of the eye at about 45 deg, iris toward camera (reference: iris macro)
  profile  grazing side view of the eye along the lid line (reference: profile macro)
  front    front view of both eyes
  portrait, eyes, macro   exactly the render_textures.py deliverable cameras (subject's left eye for macro)
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import materials as MT  # noqa: E402
import stage as S  # noqa: E402

EYE = Vector((-0.031, 0.0, 0.0))      # subject's right eye centre, relative to the eye midpoint (nose on image right)

SHOTS = {
    # name: (camera offset from eye, look-at offset from eye, lens, fstop, gaze (h, v))
    "wide": (Vector((-0.17, -0.38, 0.045)), Vector((0.012, 0.0, -0.012)), 85, 11.0, (-12, 3)),
    "three_q": (Vector((-0.070, -0.140, 0.006)), Vector((0.0, -0.004, 0.0)), 100, 22.0, (-22, 6)),
    "profile": (Vector((-0.165, -0.060, -0.010)), Vector((0.0, -0.008, 0.0)), 100, 22.0, (-4, -4)),
    "front": (Vector((0.031, -0.36, 0.005)), Vector((0.031, 0.0, 0.0)), 100, 4.0, (-6, 3)),
}
# render_textures.py VIEWS, expressed relative to the same eye (eye = mid + EYE)
DELIVERABLE = {
    "portrait": (Vector((-0.30, -0.58, 0.02)), Vector((0.0, 0.0, -0.045)), 70, 5.6),
    "eyes": (Vector((0.0, -0.36, 0.005)), Vector((0.0, 0.0, 0.0)), 100, 4.0),
    "macro": (Vector((0.045, -0.16, 0.012)), Vector((0.031, 0.0, 0.0)), 100, 8.0),
    "back34": (Vector((0.44, 0.40, 0.12)), Vector((0.0, 0.05, 0.02)), 50, 8.0),       # hair / groom check
    "top": (Vector((0.05, -0.12, 0.55)), Vector((0.0, 0.04, 0.03)), 50, 8.0),         # hair coverage from above
    "side": (Vector((0.62, 0.02, 0.03)), Vector((0.0, 0.02, 0.0)), 60, 8.0),          # profile, hairline + nape
    "front": (Vector((0.0, -0.62, -0.01)), Vector((0.0, 0.0, -0.04)), 60, 5.6),      # render_textures 'front'
}


def studio(mid):
    """The project's constant studio light (stage.portrait_lights + interior HDRI), as in every deliverable."""
    clear_lights()
    S.world("interior.exr", 0.28, rot=2.4)
    S.portrait_lights(mid)
    bpy.context.scene.view_settings.exposure = 0.0
    bd = bpy.data.objects.get("SET_Backdrop") or S.backdrop(mid)
    bd.hide_render = False


def clear_lights():
    for o in list(bpy.data.objects):
        if o.type == "LIGHT":
            bpy.data.objects.remove(o, do_unlink=True)


def lowkey(eye, cam_loc, key_low=False):
    """Low-key look of the reference: one hard warm key above and left of the camera, a cool rim from behind on
    the image right (it outlines the nose bridge and lid), near-black world."""
    clear_lights()
    S.world("interior.exr", 0.0, rot=2.4)
    fwd = (eye - cam_loc).normalized()
    right = fwd.cross(Vector((0, 0, 1))).normalized()
    up = right.cross(fwd).normalized()
    kp = (eye - fwd * 0.30 - right * 0.16 + up * 0.07) if key_low else (eye - fwd * 0.26 - right * 0.24 + up * 0.17)
    S.area("KEY", kp, eye, 0.8 if key_low else 1.0, 0.05, (1.0, 0.86, 0.72), shape="DISK")
    S.area("RIM", eye + fwd * 0.25 + right * 0.22 + up * 0.05, eye + right * 0.02, 1.8, 0.04, (0.92, 0.96, 1.0))
    S.area("FILL", eye - fwd * 0.4 + right * 0.3 - up * 0.1, eye, 0.04, 0.6, (1.0, 0.9, 0.85))
    # a window-shaped softbox seen mainly in the cornea and the wet lid line (the reference's big catchlight)
    cl = S.area("CATCH", eye - fwd * 0.34 - right * 0.13 + up * 0.035, eye, 6.0, 0.14, (1.0, 0.97, 0.94), shape="RECTANGLE")
    cl.data.size_y = 0.09
    cl.visible_diffuse = cl.visible_transmission = cl.visible_volume_scatter = False     # reflections only
    bpy.context.scene.view_settings.exposure = -0.3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tex", default="T02")
    ap.add_argument("--shots", default="wide,three_q,profile,front")
    ap.add_argument("--samples", type=int, default=128)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--out", default=os.path.join(HERE, "out", "lookdev"))
    ap.add_argument("--tag", default="")
    ap.add_argument("--light", default="studio", choices=["studio", "lowkey"])
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    a.out = os.path.abspath(a.out)
    os.makedirs(a.out, exist_ok=True)
    w, h = (int(v) for v in a.res.split("x"))
    MT.apply(a.tex)
    S.cycles((w, h), a.samples)
    mid = S.eye_mid()
    eye = mid + EYE
    S.set_ctrl(blink_L=0, blink_R=0, wide=0, squint=0, brow_raise=0, brow_down=0, pupil=-0.6, auto_lids=1)
    for shot in a.shots.split(","):
        if shot in DELIVERABLE:
            off, look, lens, fstop = DELIVERABLE[shot]
            gh, gv = -6, 3                                   # render_textures.py default gaze
            cam_loc, cam_tgt = mid + off, mid + look
            foc = mid + Vector((0.031, -0.013, 0)) if shot == "macro" else mid + Vector((0, -0.012, 0))
        else:
            off, look, lens, fstop, (gh, gv) = SHOTS[shot]
            cam_loc, cam_tgt = eye + off, eye + look
            # focus on the iris plane (~9.5 mm in front of the eyeball centre along the gaze), not the cornea
            # apex: at macro distances the depth of field is only ~1-2 mm
            gaze = Vector((math.tan(math.radians(gh)), -1.0, math.tan(math.radians(gv)))).normalized()
            foc = eye + gaze * 0.0095
        if a.light == "lowkey" and shot not in DELIVERABLE and shot != "front":
            lowkey(eye, cam_loc, key_low=(shot == "three_q"))
            bd = bpy.data.objects.get("SET_Backdrop")
            if bd:
                bd.hide_render = True
        else:
            studio(mid)
        S.set_gaze(gh, gv)
        S.refresh()
        S.camera(f"CAM_{shot}", cam_loc, cam_tgt, lens=lens, fstop=fstop, focus=foc)
        bpy.context.scene.render.filepath = os.path.join(a.out, f"{a.tex}_{shot}{a.tag}.png")
        bpy.ops.render.render(write_still=True)
        print("rendered", shot, flush=True)


if __name__ == "__main__":
    main()

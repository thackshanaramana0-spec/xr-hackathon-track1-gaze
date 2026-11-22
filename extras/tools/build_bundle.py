"""Build scene.blend (repository top level): the Track 1 submission scene from a GNM head.

    blender -b --factory-startup gnm_rig/out/heads/T02.blend -P extras/tools/build_bundle.py -- --tex T02

What it saves:
  * the textured GNM head (UDIM skin/eyes, 3D brows, lashes, tear line, head hair), textures packed in the file
  * the fixed studio lighting used for the project videos (key, fill, rim, catchlight, studio HDRI, backdrop)
  * CAM_Gaze locked 0.40 m forward of the eye midpoint, looking straight at the face, 1024 x 1024 PNG
  * CAM_EyesCloseup at the same position with a longer lens (visual check only, not the evaluated camera)
  * scene["gaze_cfg"]: fixation distance, motion bound, camera distance, calibrated pupil points per eye
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector
from mathutils.geometry import barycentric_transform, intersect_point_tri_2d

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "gnm_rig"))
import materials as MT  # noqa: E402
import stage as S  # noqa: E402

FIX_DIST, CAM_DIST, BOUND = 0.35, 0.40, 0.05
MAIN_LENS, CLOSE_LENS, CLOSE_RES = 70.0, 180.0, (1536, 640)


def pupil_point(side):
    """World position of the pupil centre: the iris texture is painted centred on its UDIM tile
    (eye_tiles.py / iris_hq.py), so the pupil is where UV = tile centre on the eye-interior surface."""
    head = bpy.data.objects["GNM_Head"]
    deps = bpy.context.evaluated_depsgraph_get()
    ev = head.evaluated_get(deps)
    me = ev.to_mesh()
    mi = [i for i, m in enumerate(me.materials) if m and m.name == f"MAT_eye_interior_{side}"][0]
    uv = me.uv_layers.active.data
    me.calc_loop_triangles()
    tris = [t for t in me.loop_triangles if t.material_index == mi]
    u0 = sum(uv[t.loops[0]].uv[0] for t in tris) / len(tris)
    v0 = sum(uv[t.loops[0]].uv[1] for t in tris) / len(tris)
    c = Vector((math.floor(u0) + 0.5, math.floor(v0) + 0.5))
    hits = []
    for t in tris:
        a, b, d = (uv[l].uv.to_3d() for l in t.loops)
        if intersect_point_tri_2d(c, a.xy, b.xy, d.xy):
            pa, pb, pd = (me.vertices[v].co for v in t.vertices)
            hits.append(barycentric_transform(c.to_3d(), a, b, d, pa, pb, pd))
    ev.to_mesh_clear()
    if not hits:
        raise RuntimeError(f"pupil UV centre not found on eye {side}")
    p = hits[0]
    return head.matrix_world @ p, (int(math.floor(u0)) + 1001 + 10 * int(math.floor(v0)))


def reduced_set(tex_id, px):
    """Copy the texture set to _build/ with the skin tiles (1001: albedo, normal, roughness) at px x px, so the packed
    scene.blend and the zip stay under GitHub's 100 MB file limit. The eye tiles keep full 4096 resolution."""
    import glob
    import shutil
    src = MT.set_dir(tex_id)
    dst_root = os.path.join(ROOT, "_build", "textures")
    dst = os.path.join(dst_root, os.path.basename(src))
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    for f in glob.glob(os.path.join(src, "*.png")):
        out = os.path.join(dst, os.path.basename(f))
        if f.endswith(("albedo.1001.png", "normal.1001.png", "roughness.1001.png")) and px < 4096:
            im = bpy.data.images.load(f)
            im.colorspace_settings.name = "Non-Color"
            im.scale(px, px)
            im.filepath_raw = out
            im.file_format = "PNG"
            im.save()
            bpy.data.images.remove(im)
        else:
            shutil.copy2(f, out)
    return dst_root


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tex", default="T02")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(ROOT), "scene.blend"))
    ap.add_argument("--samples", type=int, default=128)
    ap.add_argument("--skin-px", type=int, default=2048, help="skin normal/roughness tile size packed in the bundle")
    a = ap.parse_args(argv)

    sc = bpy.context.scene
    MT.TEX = reduced_set(a.tex, a.skin_px)
    MT.apply(a.tex, heavy_hair=False)
    rig = S.rig()
    # neutral face: open lids, default pupil, lids follow vertical gaze naturally
    S.set_ctrl(blink_L=0, blink_R=0, wide=0, squint=0, brow_raise=0, brow_down=0, pupil=0.0, auto_lids=1)

    # eye midpoint M from the actual pivots (eyeball centres)
    cL = rig.matrix_world @ rig.pose.bones["eye.L"].head
    cR = rig.matrix_world @ rig.pose.bones["eye.R"].head
    mid = (cL + cR) / 2
    rest = bpy.data.objects["GAZE_Rest"]
    rest_err = (rest.matrix_world.translation - mid).length
    tgt = bpy.data.objects["GAZE_Target"]
    tgt.location = (0.0, -FIX_DIST, 0.0)
    S.refresh()

    # constant studio lighting (same rig as the project videos)
    S.cycles((1024, 1024), a.samples)
    sc.cycles.seed = 0
    S.world("interior.exr", 0.28, rot=2.4)
    S.portrait_lights(mid)
    S.backdrop(mid)

    # evaluated camera: 40 cm straight ahead of M, looking back along +Y at the face, no depth of field
    fwd = Vector((0, -1, 0))
    cam = S.camera("CAM_Gaze", mid + fwd * CAM_DIST, mid, lens=MAIN_LENS)
    close = S.camera("CAM_EyesCloseup", mid + fwd * CAM_DIST, mid, lens=CLOSE_LENS)
    for c in (cam, close):
        c.data.sensor_fit = "HORIZONTAL"
        c.lock_location = c.lock_rotation = (True, True, True)
    sc.camera = cam
    sc.render.resolution_x = sc.render.resolution_y = 1024
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.compression = 90           # lossless PNG, smaller files in the zip
    sc.render.film_transparent = False

    # calibrate the pupil point of each eye in its bone frame (moves rigidly with the eye)
    cfg = {"fixation_dist_m": FIX_DIST, "camera_dist_m": CAM_DIST, "motion_bound_m": BOUND,
           "eye_mid": list(mid), "texture_set": a.tex,
           "eyes_camera": {"name": "CAM_EyesCloseup", "res": list(CLOSE_RES)}}
    for side in "LR":
        pb = rig.pose.bones[f"eye.{side}"]
        p, tile = pupil_point(side)
        centre = rig.matrix_world @ pb.head
        R = (rig.matrix_world @ pb.matrix).to_3x3().normalized()
        cfg[f"pupil_offset_local_{side}"] = list(R.inverted() @ (p - centre))
        cfg[f"eye_tile_{side}"] = tile
        print(f"[bundle] eye {side}: tile {tile}, pupil {tuple(round(x, 5) for x in p)}, "
              f"depth {(p - centre).length * 1000:.2f} mm", flush=True)
    sc["gaze_cfg"] = cfg
    print(f"[bundle] eye mid {tuple(round(x, 5) for x in mid)}, GAZE_Rest offset {rest_err * 1000:.3f} mm", flush=True)

    sc.frame_start = sc.frame_end = sc.frame_current = 1
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=a.out, compress=True, relative_remap=True)
    print("[bundle] saved", a.out, round(os.path.getsize(a.out) / 2**20, 1), "MB", flush=True)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

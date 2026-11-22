"""eyes.py - gaze control + rendering for the GNM head in scene.blend (Samsung PRISM Hackathon 2026, Track 1).

Inside Blender, with scene.blend open (Scripting tab or Python console):
    import sys; sys.path.append(r"<folder containing scene.blend>/wrapper")
    import eyes
    eyes.move(h, v)                         # h, v in [-1, +1]; +h = image right, +v = up
    eyes.reset()                            # centre fixation, 35 cm straight ahead
    rec = eyes.render("renders/test.png")   # 1024x1024 PNG + metadata record (dict)

Headless, from the folder containing scene.blend:
    blender -b scene.blend -P wrapper/eyes.py -- --sequence      # 10 clockwise frames -> renders/ + metadata.json
    blender -b scene.blend -P wrapper/eyes.py -- --directions    # centre/left/right/up/down/reset -> checks/
    blender -b scene.blend -P wrapper/eyes.py -- --move 1 0 --out left.png

Geometry (constants stored in scene["gaze_cfg"] when scene.blend was built):
  * M = midpoint of the two eyeball centres.
  * Fixation target T = M + 0.35 m forward + h * 0.05 m right + v * 0.05 m up  (the +-5 cm bound).
  * Each eye bone pivots at its eyeball centre; a Damped Track constraint turns it to look at T,
    so both eyes rotate in 3D and converge on T.
  * Camera CAM_Gaze is locked at M + 0.40 m forward, facing the face; output 1024 x 1024 PNG.
  * Lighting is a fixed studio rig saved in the scene; nothing in this file changes it.

Only Blender is needed (tested on 5.2 LTS). No other Python packages.
"""
import argparse
import json
import math
import os
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

RIG = "GNM_Rig"
TARGET = "GAZE_Target"          # child of GAZE_Rest, which sits at M (local: +X right, -Y forward, +Z up)
CAMERA = "CAM_Gaze"
BONES = {"L": "eye.L", "R": "eye.R"}   # L = the subject's left eye (appears on the image right)
FORWARD = Vector((0.0, -1.0, 0.0))     # the face looks along world -Y

_state = {"h": 0.0, "v": 0.0}


# ------------------------------------------------------------------------------------------------ control
def _cfg():
    return bpy.context.scene["gaze_cfg"]


def _clamp(x):
    """Inputs outside [-1, +1] are clamped (documented behaviour, never an error)."""
    return max(-1.0, min(1.0, float(x)))


def _refresh():
    rig = bpy.data.objects[RIG]
    rig.update_tag()
    sc = bpy.context.scene
    sc.frame_set(sc.frame_current)
    bpy.context.view_layer.update()


def move(h, v):
    """Move both pupils together. h, v normalised to [-1, +1] (+h = image right, +v = up)."""
    h, v = _clamp(h), _clamp(v)
    cfg = _cfg()
    bound, dist = float(cfg["motion_bound_m"]), float(cfg["fixation_dist_m"])
    bpy.data.objects[TARGET].location = (h * bound, -dist, v * bound)
    _state["h"], _state["v"] = h, v
    _refresh()
    return h, v


def reset():
    """Centre fixation: 35 cm straight ahead of the eye midpoint."""
    return move(0.0, 0.0)


# ------------------------------------------------------------------------------------------------ geometry
def _res(scene):
    r = scene.render
    return r.resolution_x * r.resolution_percentage / 100, r.resolution_y * r.resolution_percentage / 100


def _pixel(cam, scene, p):
    co = world_to_camera_view(scene, cam, p)
    w, hgt = _res(scene)
    return [round(co.x * w, 3), round((1.0 - co.y) * hgt, 3)]   # origin top-left, x right, y down


def camera_matrices(scene=None, cam=None):
    """(K 3x3 intrinsics, RT 3x4 world->camera), OpenCV convention."""
    scene = scene or bpy.context.scene
    cam = cam or scene.camera
    w, hgt = _res(scene)
    cd = cam.data
    horiz = cd.sensor_fit == "HORIZONTAL" or (cd.sensor_fit == "AUTO" and w >= hgt)
    f_px = cd.lens / (cd.sensor_width if horiz else cd.sensor_height) * (w if horiz else hgt)
    big = max(w, hgt)
    K = [[f_px, 0.0, w / 2 - cd.shift_x * big], [0.0, f_px, hgt / 2 + cd.shift_y * big], [0.0, 0.0, 1.0]]
    flip = Matrix(((1, 0, 0), (0, -1, 0), (0, 0, -1)))     # Blender camera (-Z fwd, +Y up) -> OpenCV
    R_wc = cam.matrix_world.to_3x3().normalized().transposed()
    t_wc = -(R_wc @ cam.matrix_world.translation)
    R, t = flip @ R_wc, flip @ t_wc
    return K, [list(R[i]) + [t[i]] for i in range(3)]


def _matmul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(len(B))) for j in range(len(B[0]))] for i in range(len(A))]


def _eye_state(side):
    scene = bpy.context.scene
    rig = bpy.data.objects[RIG]
    pb = rig.pose.bones[BONES[side]]
    pose = (rig.matrix_world @ pb.matrix).to_3x3().normalized()
    gaze = (pose @ Vector((0, 1, 0))).normalized()           # bone +Y = line of sight
    centre = rig.matrix_world @ pb.head                       # eyeball centre = rotation pivot
    pupil = centre + pose @ Vector(tuple(_cfg()[f"pupil_offset_local_{side}"]))
    # world-frame rotation that turns the straight-ahead direction (-Y) into this eye's line of sight
    rot = FORWARD.rotation_difference(gaze).to_euler("XYZ")
    yaw = math.degrees(math.atan2(gaze.x, -gaze.y))           # + = towards image right
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, gaze.z))))
    return {"rotation_deg": [round(math.degrees(a), 4) for a in rot], "yaw_deg": round(yaw, 4),
            "pitch_deg": round(pitch, 4), "gaze": [round(x, 6) for x in gaze],
            "centre": [round(x, 6) for x in centre], "pupil_3D": [round(x, 6) for x in pupil],
            "pupil_2D": _pixel(scene.camera, scene, pupil)}


def metadata(frame=None, theta=None):
    scene = bpy.context.scene
    L, R = _eye_state("L"), _eye_state("R")
    K, RT = camera_matrices(scene)
    tgt = bpy.data.objects[TARGET].matrix_world.translation
    mid = (Vector(L["centre"]) + Vector(R["centre"])) / 2
    cam = scene.camera.matrix_world.translation
    return {
        "frame": frame,
        "theta": None if theta is None else round(theta, 6),
        "input": {"h": round(_state["h"], 6), "v": round(_state["v"], 6)},
        "eye_rotation_L": L["rotation_deg"],
        "eye_rotation_R": R["rotation_deg"],
        "pupil_center_2D_L": L["pupil_2D"],
        "pupil_center_2D_R": R["pupil_2D"],
        "camera_matrix": [[round(x, 4) for x in row] for row in K],
        # extras
        "camera_extrinsics_RT": [[round(x, 6) for x in row] for row in RT],
        "camera_projection_P": [[round(x, 4) for x in row] for row in _matmul(K, RT)],
        "eye_yaw_pitch_deg_L": [L["yaw_deg"], L["pitch_deg"]],
        "eye_yaw_pitch_deg_R": [R["yaw_deg"], R["pitch_deg"]],
        "gaze_vector_L": L["gaze"], "gaze_vector_R": R["gaze"],
        "eyeball_center_3D_L": L["centre"], "eyeball_center_3D_R": R["centre"],
        "pupil_center_3D_L": L["pupil_3D"], "pupil_center_3D_R": R["pupil_3D"],
        "fixation_target_3D": [round(x, 6) for x in tgt],
        "fixation_distance_m": round((tgt - mid).dot(FORWARD), 6),
        "camera_distance_m": round((cam - mid).dot(FORWARD), 6),
        "vergence_deg": round(math.degrees(Vector(L["gaze"]).angle(Vector(R["gaze"]))), 4),
        "units": {"eye_rotation": "deg, XYZ Euler, world frame: rotation from straight ahead (-Y) to the line of sight",
                  "yaw_pitch": "deg; yaw + = image right, pitch + = up",
                  "pupil_2D": "px in the 1024x1024 render, origin top-left, x right, y down",
                  "3D": "m, Blender world: Z up, the face looks along -Y, +X = image right",
                  "camera": "OpenCV: [u, v, 1] ~ K [R|t] X_world",
                  "input": "h + = image right (the subject's left), v + = up; clamped to [-1, +1]"},
    }


# ------------------------------------------------------------------------------------------------ render
def setup_device():
    """GPU Cycles if available (XR_CYCLES_DEVICE overrides the order), otherwise CPU. Same image either way."""
    scene = bpy.context.scene
    order = os.environ.get("XR_CYCLES_DEVICE", "OPTIX,CUDA,HIP,ONEAPI,METAL").split(",")
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in order:
            try:
                prefs.compute_device_type = kind
                prefs.get_devices()
            except TypeError:
                continue
            if any(d.type == kind for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type == kind
                scene.cycles.device = "GPU"
                return kind
    except Exception:
        pass
    scene.cycles.device = "CPU"
    return "CPU"


class _UsingCamera:
    def __init__(self, name, res):
        self.name, self.res = name, res

    def __enter__(self):
        sc = bpy.context.scene
        self.old = (sc.camera, sc.render.resolution_x, sc.render.resolution_y)
        sc.camera = bpy.data.objects[self.name]
        sc.render.resolution_x, sc.render.resolution_y = self.res
        return sc.camera

    def __exit__(self, *exc):
        sc = bpy.context.scene
        sc.camera, sc.render.resolution_x, sc.render.resolution_y = self.old


def _write(path):
    scene = bpy.context.scene
    path = os.path.abspath(bpy.path.abspath(path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def render(path=None, frame=None, theta=None, eyes_path=None):
    """Render CAM_Gaze (locked 40 cm, 1024x1024 PNG) and return the metadata record.
    eyes_path: also render the eye close-up camera (same 40 cm position, longer lens) for visual checks."""
    scene = bpy.context.scene
    scene.camera = bpy.data.objects[CAMERA]
    rec = metadata(frame, theta)
    if path:
        rec["image"] = os.path.basename(_write(path))
    ec = _cfg().get("eyes_camera")
    if eyes_path and ec and ec["name"] in bpy.data.objects:
        with _UsingCamera(ec["name"], tuple(ec["res"])) as cam:
            K, RT = camera_matrices(scene, cam)
            sub = {"image": os.path.basename(eyes_path), "resolution": list(ec["res"]),
                   "camera_matrix": [[round(x, 4) for x in row] for row in K],
                   "camera_extrinsics_RT": [[round(x, 6) for x in row] for row in RT]}
            for s in "LR":
                sub[f"pupil_center_2D_{s}"] = _pixel(cam, scene, Vector(rec[f"pupil_center_3D_{s}"]))
            _write(eyes_path)
        rec["eyes_closeup"] = sub
    return rec


# ------------------------------------------------------------------------------------------------ batches
def run_sequence(out_root, n=10, eyes=True):
    """Ten clockwise renders: theta_k = 2*pi*k/10, h = sin(theta_k), v = cos(theta_k); k = 0 is the top."""
    recs = []
    for k in range(n):
        theta = 2 * math.pi * k / n
        move(math.sin(theta), math.cos(theta))
        rec = render(os.path.join(out_root, "renders", f"frame_{k:02d}.png"), frame=k, theta=theta,
                     eyes_path=os.path.join(out_root, "renders_eyes", f"frame_{k:02d}.png") if eyes else None)
        recs.append(rec)
        print(f"[eyes] frame {k} theta={theta:.4f} h={rec['input']['h']:+.4f} v={rec['input']['v']:+.4f} "
              f"L={rec['pupil_center_2D_L']} R={rec['pupil_center_2D_R']}", flush=True)
    reset()
    with open(os.path.join(out_root, "metadata.json"), "w") as f:
        json.dump(recs, f, indent=2)
    return recs


def run_directions(out_root, eyes=True):
    """Centre, Left, Right, Up, Down, then Reset: the five-direction pass/fail check."""
    d = os.path.join(out_root, "checks")
    recs = {}
    for name, h, v in (("center", 0, 0), ("left", -1, 0), ("right", 1, 0), ("up", 0, 1), ("down", 0, -1)):
        move(h, v)
        recs[name] = render(os.path.join(d, f"{name}.png"), eyes_path=os.path.join(d, f"eyes_{name}.png") if eyes else None)
    reset()
    recs["reset"] = render(os.path.join(d, "reset.png"), eyes_path=os.path.join(d, "eyes_reset.png") if eyes else None)
    with open(os.path.join(d, "directions.json"), "w") as f:
        json.dump(recs, f, indent=2)
    return recs


def _main(argv):
    ap = argparse.ArgumentParser(prog="eyes.py")
    ap.add_argument("--sequence", action="store_true", help="10 clockwise renders + metadata.json")
    ap.add_argument("--directions", action="store_true", help="centre/left/right/up/down/reset renders")
    ap.add_argument("--move", nargs=2, type=float, metavar=("H", "V"))
    ap.add_argument("--out", default="move.png", help="PNG path for a single --move render")
    ap.add_argument("--root", default=None, help="output folder (default: the folder of scene.blend)")
    ap.add_argument("--samples", type=int, default=None, help="Cycles samples (default: as saved, 128)")
    ap.add_argument("--no-eyes", action="store_true", help="skip the eye close-up renders")
    a = ap.parse_args(argv)
    root = a.root or os.path.dirname(bpy.data.filepath) or os.getcwd()
    if a.samples:
        bpy.context.scene.cycles.samples = a.samples
    print("[eyes] device:", setup_device(), flush=True)
    if a.sequence:
        run_sequence(root, eyes=not a.no_eyes)
    if a.directions:
        run_directions(root, eyes=not a.no_eyes)
    if a.move:
        move(*a.move)
        print(json.dumps(render(a.out), indent=2))


if __name__ == "__main__":
    _main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

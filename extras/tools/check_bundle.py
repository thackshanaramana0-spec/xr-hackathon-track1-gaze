"""Independent checks of the Track 1 bundle. Reads only the rendered PNGs and the JSON files,
never Blender, so it tests what an evaluator would receive.

    python extras/tools/check_bundle.py .          # writes extras/quality_audit/gate0/report.md + report.json

Checks: 10-record metadata with every required field; clockwise inputs theta_k = 2*pi*k/10, h = sin, v = cos;
1024x1024 PNGs; fixation 35 cm (+-5 cm bound) and camera 40 cm; identical camera and lighting across frames;
convergence of both eyes on the target; metadata pupil centres reproject through K[R|t] and match the pupils
detected in the images; five-direction test with measured pixel shifts; reset returns to centre.
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

REQ = ["frame", "theta", "input", "eye_rotation_L", "eye_rotation_R", "pupil_center_2D_L", "pupil_center_2D_R",
       "camera_matrix"]
MIN_SHIFT_PX = 5.0          # S2-027: every direction must move the pupils at least this far in the 1024 frame
DETECT_TOL_PX = 3.0         # metadata pupil vs detected pupil, 1024 frame
LIGHT_TOL = 1.0             # mean abs difference (0-255) of the background between frames


def lum(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def detect_pupil(img, guess, r_win):
    """Centroid of the darkest blob near guess (hole-filled so the corneal catchlight does not bias it)."""
    h, w = img.shape
    x0, y0 = int(round(guess[0])), int(round(guess[1]))
    xa, xb, ya, yb = max(0, x0 - r_win), min(w, x0 + r_win + 1), max(0, y0 - r_win), min(h, y0 + r_win + 1)
    win = img[ya:yb, xa:xb]
    yy, xx = np.mgrid[ya:yb, xa:xb]
    inside = (xx - x0) ** 2 + (yy - y0) ** 2 <= r_win ** 2
    lo = np.percentile(win[inside], 1)
    iris = np.percentile(win[inside], 50)
    mask = (win < lo + 0.35 * (iris - lo)) & inside
    lab, n = ndimage.label(mask)
    if n == 0:
        return None
    # the component closest to the guess, weighted by size
    best, score = None, -1
    for i in range(1, n + 1):
        m = lab == i
        cy, cx = ndimage.center_of_mass(m)
        s = m.sum() / (1.0 + math.hypot(cx + xa - x0, cy + ya - y0))
        if s > score:
            best, score = m, s
    best = ndimage.binary_fill_holes(best)
    cy, cx = ndimage.center_of_mass(best)
    r = math.sqrt(best.sum() / math.pi)
    # The upper lid covers the top of the pupil whenever the eye looks up or the lid rests low, which pulls a
    # centroid downwards. Fit a circle (least squares) to the visible pupil edge on the lower and side arcs only,
    # where the edge meets the iris rather than the lid.
    edge = best & ~ndimage.binary_erosion(best)
    ey, ex = np.nonzero(edge)
    keep = ey >= cy - 0.35 * r
    if keep.sum() >= 12:
        x, y = ex[keep].astype(float), ey[keep].astype(float)
        A = np.c_[2 * x, 2 * y, np.ones_like(x)]
        (fx, fy, c), *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
        fr = math.sqrt(max(c + fx * fx + fy * fy, 0.0))
        if 0.5 * r < fr < 2.0 * r:
            return [fx + xa, fy + ya], fr
    return [cx + xa, cy + ya], r


def reproject(P, X):
    p = np.asarray(P) @ np.append(np.asarray(X, float), 1.0)
    return [p[0] / p[2], p[1] / p[2]]


def angle(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return math.degrees(math.acos(max(-1, min(1, a.dot(b) / np.linalg.norm(a) / np.linalg.norm(b)))))


def check(root):
    res, rows = {}, []

    def row(name, ok, detail):
        # ok=None means the check could not run because an input is missing: NOT VERIFIED, not PASS.
        status = "NOT VERIFIED" if ok is None else ("PASS" if ok else "FAIL")
        rows.append((name, status, detail))
        return ok

    # ---------------------------------------------------------------- layout
    need = ["scene.blend", "wrapper/eyes.py", "renders", "metadata.json", "README.md"]
    missing = [n for n in need if not os.path.exists(os.path.join(root, n))]
    row("Bundle layout", not missing, "all present" if not missing else f"missing: {missing}")

    meta = json.load(open(os.path.join(root, "metadata.json")))
    row("metadata.json: 10 records", len(meta) == 10, f"{len(meta)} records")
    miss = sorted({k for r in meta for k in REQ if k not in r})
    row("metadata.json: required fields", not miss, "frame, theta, input, eye_rotation_L/R, pupil_center_2D_L/R, "
        "camera_matrix" if not miss else f"missing {miss}")

    # ---------------------------------------------------------------- sequence
    err = 0.0
    for k, r in enumerate(meta):
        th = 2 * math.pi * k / 10
        err = max(err, abs(r["theta"] - th), abs(r["input"]["h"] - math.sin(th)), abs(r["input"]["v"] - math.cos(th)),
                  abs(r["frame"] - k))
    row("Clockwise sequence theta_k = 2*pi*k/10, h = sin, v = cos, k = 0 at the top", err < 1e-5,
        f"max deviation {err:.2e}")
    # clockwise on screen: the target angle atan2(h, v) increases with k
    ang = [math.atan2(r["input"]["h"], r["input"]["v"]) % (2 * math.pi) for r in meta]
    row("Order is clockwise (top, then right, bottom, left)", all(b > a for a, b in zip(ang, ang[1:])),
        "atan2(h, v) increases every frame")

    sizes = {}
    for r in meta:
        im = Image.open(os.path.join(root, "renders", r["image"]))
        sizes[r["image"]] = (im.format, im.size)
    bad = {k: v for k, v in sizes.items() if v != ("PNG", (1024, 1024))}
    row("Renders are 1024 x 1024 PNG", not bad and len(sizes) == 10, f"{len(sizes)} files" if not bad else str(bad))

    # ---------------------------------------------------------------- calibration
    fd = [r["fixation_distance_m"] for r in meta]
    cd = [r["camera_distance_m"] for r in meta]
    row("Fixation target 35 cm forward of the eye midpoint (+-5 cm)", all(abs(x - 0.35) <= 0.05 for x in fd),
        f"forward distance {min(fd):.4f}-{max(fd):.4f} m")
    mids = [(np.add(r["eyeball_center_3D_L"], r["eyeball_center_3D_R"]) / 2) for r in meta]
    offs = [np.asarray(r["fixation_target_3D"]) - m for r, m in zip(meta, mids)]
    lat = max(max(abs(o[0]), abs(o[2])) for o in offs)
    row("Target stays inside the +-5 cm motion bound", lat <= 0.05 + 1e-6, f"max lateral offset {lat * 100:.2f} cm")
    row("Camera locked 40 cm forward", all(abs(x - 0.40) < 1e-4 for x in cd), f"{min(cd):.4f}-{max(cd):.4f} m")
    K0, RT0 = meta[0]["camera_matrix"], meta[0]["camera_extrinsics_RT"]
    same = all(r["camera_matrix"] == K0 and r["camera_extrinsics_RT"] == RT0 for r in meta)
    row("Camera identical in all 10 frames", same, f"f = {K0[0][0]:.1f} px, c = ({K0[0][2]:.1f}, {K0[1][2]:.1f})")
    # camera faces the face: optical axis (row 3 of R) points from the camera towards the eye midpoint
    R = np.asarray(RT0)[:, :3]
    C = -R.T @ np.asarray(RT0)[:, 3]
    a = angle(R[2], mids[0] - C)
    row("Camera faces the face (optical axis through the eye midpoint)", a < 0.5, f"{a:.3f} deg off axis")

    # ---------------------------------------------------------------- convergence (S2-026)
    worst = 0.0
    for r in meta:
        for s in "LR":
            worst = max(worst, angle(r[f"gaze_vector_{s}"], np.subtract(r["fixation_target_3D"], r[f"eyeball_center_3D_{s}"])))
    row("Both eyes converge on the fixation target", worst < 0.05, f"max line-of-sight error {worst:.4f} deg")
    verg = [r["vergence_deg"] for r in meta]
    half = np.linalg.norm(np.subtract(meta[0]["eyeball_center_3D_L"], meta[0]["eyeball_center_3D_R"])) / 2
    expect = 2 * math.degrees(math.atan(half / 0.35))
    res["vergence"] = {"min": min(verg), "max": max(verg), "expected_centre": expect}

    # ---------------------------------------------------------------- pupil ground truth (S2-022)
    rep = max(math.dist(reproject(r["camera_projection_P"], r[f"pupil_center_3D_{s}"]), r[f"pupil_center_2D_{s}"])
              for r in meta for s in "LR")
    row("pupil_center_2D = K[R|t] * pupil_center_3D (to JSON rounding)", rep < 0.1, f"max reprojection error {rep:.4f} px")
    det = []
    for r in meta:
        img = lum(os.path.join(root, "renders", r["image"]))
        for s in "LR":
            got = detect_pupil(img, r[f"pupil_center_2D_{s}"], 26)
            det.append(math.dist(got[0], r[f"pupil_center_2D_{s}"]) if got else float("inf"))
    row(f"Metadata pupils match pupils detected in the 1024 renders (<= {DETECT_TOL_PX} px)", max(det) <= DETECT_TOL_PX,
        f"mean {np.mean(det):.2f} px, max {max(det):.2f} px over 20 pupils")
    res["detect_1024_px"] = det
    ec = [r.get("eyes_closeup") for r in meta]
    if all(ec):
        eye_dir = os.path.join(root, "renders_eyes")
        missing = [e["image"] for e in ec if not os.path.exists(os.path.join(eye_dir, e["image"]))]
        if missing:
            # Metadata references close-up renders that are not in the checkout (renders_eyes/ is gitignored).
            # The check cannot run, so it is reported as NOT VERIFIED rather than PASS or FAIL.
            row("Same check on the eye close-ups (error scaled to 1024-frame px)", None,
                f"NOT VERIFIED: {len(missing)} of {len(ec)} close-up renders missing from {eye_dir}")
        else:
            detc, scale = [], ec[0]["camera_matrix"][0][0] / K0[0][0]
            for e in ec:
                img = lum(os.path.join(eye_dir, e["image"]))
                for s in "LR":
                    got = detect_pupil(img, e[f"pupil_center_2D_{s}"], 120)
                    detc.append(math.dist(got[0], e[f"pupil_center_2D_{s}"]) / scale if got else float("inf"))
            row("Same check on the eye close-ups (error scaled to 1024-frame px)", max(detc) <= DETECT_TOL_PX,
                f"mean {np.mean(detc):.2f} px, max {max(detc):.2f} px")
            res["detect_closeup_px_in_1024"] = detc

    # ---------------------------------------------------------------- constant lighting
    imgs = [lum(os.path.join(root, "renders", r["image"])) * 255 for r in meta]
    bg = np.zeros_like(imgs[0], bool)
    bg[:120, :120] = bg[:120, -120:] = True                       # backdrop corners, away from the face
    dl = max(abs(im[bg] - imgs[0][bg]).mean() for im in imgs[1:])
    row("Constant lighting: backdrop identical across frames", dl < LIGHT_TOL, f"max mean difference {dl:.3f} / 255")

    # ---------------------------------------------------------------- five directions (S2-023, S2-027)
    # the five-direction renders live at the top level (checks/) or in extras/checks/ in the repository layout
    cdir = os.path.join(root, "checks")
    if not os.path.isdir(cdir):
        cdir = os.path.join(root, "extras", "checks")
    dpath = os.path.join(cdir, "directions.json")
    if not os.path.exists(dpath):
        row("Five-direction test", None, f"NOT VERIFIED: directions.json not found in {cdir}")
    else:
        d = json.load(open(dpath))
        c = d["center"]
        expect = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}   # image y grows downwards
        cimg = lum(os.path.join(cdir, "center.png"))
        cdet = {s: detect_pupil(cimg, c[f"pupil_center_2D_{s}"], 26)[0] for s in "LR"}
        passes, shifts = 0, {}
        for name, (sx, sy) in expect.items():
            img = lum(os.path.join(cdir, f"{name}.png"))
            sh = []
            for s in "LR":
                p = detect_pupil(img, d[name][f"pupil_center_2D_{s}"], 26)[0]
                sh.append((p[0] - cdet[s][0], p[1] - cdet[s][1]))
            along = [x * sx + y * sy for x, y in sh]
            across = [abs(x * sy) + abs(y * sx) for x, y in sh]
            ok = min(along) >= MIN_SHIFT_PX and max(across) < min(along)
            passes += ok
            shifts[name] = {"L": [round(v, 2) for v in sh[0]], "R": [round(v, 2) for v in sh[1]]}
            row(f"Direction {name}: both pupils move {name} (detected, >= {MIN_SHIFT_PX:.0f} px)", ok,
                f"L ({sh[0][0]:+.1f}, {sh[0][1]:+.1f}) px, R ({sh[1][0]:+.1f}, {sh[1][1]:+.1f}) px")
        rimg = lum(os.path.join(cdir, "reset.png"))
        rdiff = abs(rimg - cimg).mean() * 255
        rm = max(math.dist(d["reset"][f"pupil_center_2D_{s}"], c[f"pupil_center_2D_{s}"]) for s in "LR")
        ok = rm < 1e-3 and rdiff < LIGHT_TOL
        passes += ok
        row("Reset returns exactly to centre", ok, f"metadata offset {rm:.4f} px, image difference {rdiff:.3f} / 255")
        row("Five-direction test", passes == 5, f"{passes} of 5")
        res["direction_shifts_px"] = shifts

    res["rows"] = rows
    return res


def write_report(res, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    n_pass, n_fail, n_nv = summarize(res["rows"])
    lines = ["# Gate 0 compliance report", "",
             f"Generated by `python extras/tools/check_bundle.py .` from the rendered PNGs and JSON only. "
             f"**{n_pass} of {len(res['rows'])} checks pass, {n_fail} fail, {n_nv} not verified.**", "",
             "| Check | Result | Measured |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in res["rows"]]
    v = res.get("vergence")
    if v:
        lines += ["", f"Vergence at centre {v['min']:.3f}-{v['max']:.3f} deg across the sequence; the geometry "
                  f"(eye separation, 35 cm target) predicts {v['expected_centre']:.3f} deg at centre."]
    open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    json.dump({k: v for k, v in res.items()}, open(os.path.join(out_dir, "report.json"), "w"), indent=2)
    return n_pass, n_fail, n_nv, len(res["rows"])


def summarize(rows):
    """Counts (pass, fail, not verified) over the report rows."""
    statuses = [r[1] for r in rows]
    return statuses.count("PASS"), statuses.count("FAIL"), statuses.count("NOT VERIFIED")


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                                              "quality_audit", "gate0")
    res = check(root)
    for a, b, c in res["rows"]:
        print(f"{b}  {a}  ({c})")
    p, f, nv, n = write_report(res, out)
    print(f"\n{p} of {n} checks pass, {f} fail, {nv} not verified")
    # exit 0 only when every check passes; 2 when nothing fails but some checks could not run; 1 on any failure
    sys.exit(1 if f else (2 if nv else 0))

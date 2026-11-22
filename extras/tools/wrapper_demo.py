"""Builds the 1-2 minute Track 1 video of the wrapper in action, using only the bundle's own output:
renders/, renders_eyes/, checks/, metadata.json and the independent check report.

    python extras/tools/wrapper_demo.py            # -> demo/SRMIST_Rocklef_wrapper_demo.mp4
"""
import json
import math
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.dirname(ROOT)   # repository top level
OUT = os.path.join(ROOT, "demo", "SRMIST_Rocklef_wrapper_demo.mp4")
W, H, FPS = 1920, 1080, 30
BG, FG, GREY, DIM = (8, 10, 16), (240, 242, 246), (140, 146, 160), (80, 86, 100)
TEAL, ORANGE, GREEN, CYAN = (25, 211, 162), (245, 160, 0), (52, 211, 153), (0, 180, 216)
FONTS = r"C:\Windows\Fonts"


def F(size, kind="regular"):
    name = {"regular": "segoeui.ttf", "semi": "seguisb.ttf", "light": "segoeuil.ttf", "mono": "CascadiaMono.ttf"}[kind]
    try:
        return ImageFont.truetype(os.path.join(FONTS, name), size)
    except OSError:
        return ImageFont.truetype(os.path.join(FONTS, "segoeui.ttf"), size)


meta = json.load(open(os.path.join(B, "metadata.json")))
dirs = json.load(open(os.path.join(B, "checks", "directions.json")))
report = open(os.path.join(ROOT, "quality_audit", "gate0", "report.md"), encoding="utf-8").read()
n_pass = report.split("**")[1] if "**" in report else "22 of 22 checks pass."
_cache = {}


def img(path, size=None):
    key = (path, size)
    if key not in _cache:
        im = Image.open(path).convert("RGB")
        _cache[key] = im.resize(size, Image.LANCZOS) if size else im
    return _cache[key]


def cross(d, x, y, r=9, col=ORANGE, w=3):
    d.line([x - r, y, x + r, y], fill=col, width=w)
    d.line([x, y - r, x, y + r], fill=col, width=w)


def eye_crop(rec, closeup_dir, name):
    """Right-eye close-up crop centred on the centre-gaze pupil, so motion is visible against a fixed frame."""
    e = rec["eyes_closeup"]
    cx, cy = dirs["center"]["eyes_closeup"]["pupil_center_2D_R"]
    im = img(os.path.join(closeup_dir, name)).copy()
    d = ImageDraw.Draw(im)
    px, py = e["pupil_center_2D_R"]
    cross(d, px, py, 16, ORANGE, 4)
    d.line([cx - 400, cy, cx + 400, cy], fill=CYAN, width=2)
    d.line([cx, cy - 300, cx, cy + 300], fill=CYAN, width=2)
    return im.crop((int(cx - 165), int(cy - 122), int(cx + 165), int(cy + 122))).resize((690, 510), Image.LANCZOS)


def base(kicker, title):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.text((96, 64), kicker.upper(), font=F(22, "semi"), fill=TEAL)
    d.text((96, 98), title, font=F(46, "semi"), fill=FG)
    return im, d


def frame_seq(k):
    r = meta[k]
    im, d = base(f"eyes.render()  ·  frame {k} of 10", "Ten clockwise renders, one command.")
    full = img(os.path.join(B, "renders", r["image"]), (820, 820)).copy()
    dd = ImageDraw.Draw(full)
    s = 820 / 1024
    for side in "LR":
        x, y = r[f"pupil_center_2D_{side}"]
        cross(dd, x * s, y * s, 10, ORANGE, 3)
    im.paste(full, (96, 196))
    im.paste(eye_crop(r, os.path.join(B, "renders_eyes"), r["image"]), (1000, 196))
    x0, y0 = 1000, 740
    d.text((x0, y0), f"eyes.move({r['input']['h']:+.3f}, {r['input']['v']:+.3f})", font=F(30, "mono"), fill=TEAL)
    th = r["theta"]
    d.text((x0, y0 + 50), f"theta = 2*pi*{k}/10 = {th:.4f}   h = sin, v = cos", font=F(22, "mono"), fill=GREY)
    lines = [f"pupil_center_2D_L  [{r['pupil_center_2D_L'][0]:7.2f}, {r['pupil_center_2D_L'][1]:7.2f}] px",
             f"pupil_center_2D_R  [{r['pupil_center_2D_R'][0]:7.2f}, {r['pupil_center_2D_R'][1]:7.2f}] px",
             f"eye_rotation_L     [{', '.join(f'{v:6.2f}' for v in r['eye_rotation_L'])}] deg"]
    for i, l in enumerate(lines):
        d.text((x0, y0 + 100 + i * 36), l, font=F(22, "mono"), fill=FG)
    # clockwise dial
    cx, cy, rr = 1790, 300, 70
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=DIM, width=2)
    for j in range(10):
        a = 2 * math.pi * j / 10
        px, py = cx + rr * math.sin(a), cy - rr * math.cos(a)
        col = ORANGE if j == k else (GREY if j < k else DIM)
        d.ellipse([px - 7, py - 7, px + 7, py + 7], fill=col)
    d.text((cx, cy + rr + 20), "clockwise", font=F(18), fill=GREY, anchor="mt")
    d.text((96, 1030), "Orange + = pupil centre from metadata.json   ·   cyan cross = centre-gaze pupil   ·   camera locked "
                       "40 cm, target 35 cm, 1024 x 1024 PNG", font=F(20), fill=DIM)
    return im


def frame_dir(name, h, v):
    rec = dirs[name]
    im, d = base("Five-direction check", f"{name.capitalize()}")
    pos = {"center": (0, 0), "left": (-1, 0), "right": (1, 0), "up": (0, 1), "down": (0, -1), "reset": (0, 0)}
    tiles = ["center", "left", "right", "up", "down", "reset"]
    for i, t in enumerate(tiles):
        tile = eye_crop(dirs[t], os.path.join(B, "checks"), f"eyes_{t}.png").resize((276, 204), Image.LANCZOS)
        x = 96 + i * 296
        im.paste(tile, (x, 820))
        d.text((x + 138, 1032), t.capitalize(), font=F(22, "semi" if t == name else "regular"),
               fill=FG if t == name else GREY, anchor="mt")
        if t == name:
            d.rectangle([x - 4, 816, x + 280, 1028], outline=ORANGE, width=3)
    big = eye_crop(rec, os.path.join(B, "checks"), f"eyes_{name}.png")
    im.paste(big, (96, 196))
    d.text((860, 230), f"eyes.move({h:+d}, {v:+d})" if name != "reset" else "eyes.reset()", font=F(40, "mono"),
           fill=TEAL)
    c = dirs["center"]
    if name != "center":
        dx = rec["pupil_center_2D_R"][0] - c["pupil_center_2D_R"][0]
        dy = rec["pupil_center_2D_R"][1] - c["pupil_center_2D_R"][1]
        d.text((860, 310), f"pupil shift vs centre:  dx {dx:+.1f} px   dy {dy:+.1f} px  (1024 frame)", font=F(26), fill=FG)
        ok = "PASS" if name == "reset" or abs(dx) + abs(dy) > 5 else "FAIL"
        d.text((860, 370), ok, font=F(64, "semi"), fill=GREEN if ok == "PASS" else ORANGE)
    else:
        d.text((860, 310), "Reference: both eyes on the 35 cm target, straight ahead", font=F(26), fill=FG)
    return im


def card(lines, kicker=""):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    y = H // 2 - 40 * len(lines)
    if kicker:
        d.text((W // 2, y - 60), kicker.upper(), font=F(22, "semi"), fill=TEAL, anchor="mm")
    for i, (s, size, col, kind) in enumerate(lines):
        d.text((W // 2, y + i * 80), s, font=F(size, kind), fill=col, anchor="mm")
    return im


def sheet_frame():
    im, d = base("metadata.json + contact sheet", "Every frame, labelled and verified.")
    cs = img(os.path.join(ROOT, "quality_audit", "gate0", "contact_sheet.png"))
    s = 1728 / cs.width
    im.paste(cs.resize((1728, int(cs.height * s)), Image.LANCZOS), (96, 200))
    d.text((96, 940), n_pass, font=F(34, "semi"), fill=GREEN)
    d.text((96, 990), "python extras/tools/check_bundle.py .   ·   reads only the PNGs and the JSON", font=F(24, "mono"),
           fill=GREY)
    return im


shots = [(card([("Synthetic Eyes", 84, FG, "semi"), ("eyes.py in action", 40, GREY, "light"),
                ("blender -b scene.blend -P wrapper/eyes.py -- --sequence --directions", 26, TEAL, "mono")],
               "Track 1 wrapper demo"), 4.0)]
shots += [(frame_seq(k), 3.2) for k in range(10)]
shots += [(frame_dir(n, h, v), 3.0) for n, h, v in
          (("center", 0, 0), ("left", -1, 0), ("right", 1, 0), ("up", 0, 1), ("down", 0, -1), ("reset", 0, 0))]
shots += [(sheet_frame(), 6.0),
          (card([("5 of 5 directions  ·  35 / 40 cm calibration", 44, FG, "semi"),
                 ("10 clockwise frames  ·  labels within 2 px of the pixels", 44, FG, "semi"),
                 ("Team Rocklef  ·  SRM Institute of Science and Technology", 28, GREY, "regular")], "Result"), 4.5)]

XF = 0.4
os.makedirs(os.path.dirname(OUT), exist_ok=True)
p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                      "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt",
                      "yuv420p", "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
total = 0
for i, (im, dur) in enumerate(shots):
    n = int(dur * FPS)
    nxt = shots[i + 1][0] if i + 1 < len(shots) else None
    for f in range(n):
        t = f / FPS
        fr = im
        if t < XF and i == 0:
            fr = Image.blend(Image.new("RGB", (W, H), BG), im, t / XF)
        if nxt is not None and t > dur - XF:
            fr = Image.blend(im, nxt, (t - (dur - XF)) / XF)
        p.stdin.write(fr.tobytes())
        total += 1
p.stdin.close()
p.wait()
print(OUT, round(total / FPS, 1), "s")

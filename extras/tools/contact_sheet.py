"""Contact sheet for the submission: the ten clockwise frames (eye crops with the metadata pupil centres) and the
five-direction check.   python extras/tools/contact_sheet.py . extras/quality_audit/gate0/contact_sheet.png"""
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join("quality_audit", "gate0", "contact_sheet.png")
meta = json.load(open(os.path.join(root, "metadata.json")))
dirs = json.load(open(os.path.join(root, "checks", "directions.json")))
try:
    font = ImageFont.truetype("arial.ttf", 22)
    small = ImageFont.truetype("arial.ttf", 17)
except OSError:
    font = small = ImageFont.load_default()

TW, TH, PAD = 420, 170, 14


def tile(path, rec, label):
    im = Image.open(path).convert("RGB")
    L, R = rec["pupil_center_2D_L"], rec["pupil_center_2D_R"]
    cx, cy = (L[0] + R[0]) / 2, (L[1] + R[1]) / 2
    w = abs(L[0] - R[0]) * 1.55
    box = (int(cx - w / 2), int(cy - w * TH / TW / 2), int(cx + w / 2), int(cy + w * TH / TW / 2))
    d = ImageDraw.Draw(im)
    for p in (L, R):
        d.line([(p[0] - 5, p[1]), (p[0] + 5, p[1])], fill=(255, 40, 40), width=1)
        d.line([(p[0], p[1] - 5), (p[0], p[1] + 5)], fill=(255, 40, 40), width=1)
    t = im.crop(box).resize((TW, TH), Image.LANCZOS)
    ImageDraw.Draw(t).text((8, 6), label, fill=(255, 255, 255), font=small, stroke_width=2, stroke_fill=(0, 0, 0))
    return t


cols = 5
rows_seq = 2
W = cols * TW + (cols + 1) * PAD
H = 60 + rows_seq * (TH + PAD) + 50 + 2 * (TH + PAD) + 40
sheet = Image.new("RGB", (W, H), (18, 20, 24))
d = ImageDraw.Draw(sheet)
d.text((PAD, 16), "Ten clockwise renders: theta_k = 2*pi*k/10, h = sin, v = cos (red + = metadata pupil centre)",
       fill=(235, 235, 235), font=font)
for k, r in enumerate(meta):
    t = tile(os.path.join(root, "renders", r["image"]), r,
             f"k={k}  h={r['input']['h']:+.2f}  v={r['input']['v']:+.2f}")
    sheet.paste(t, (PAD + (k % cols) * (TW + PAD), 60 + (k // cols) * (TH + PAD)))
y0 = 60 + rows_seq * (TH + PAD) + 10
d.text((PAD, y0), "Five-direction check (camera and lights unchanged)", fill=(235, 235, 235), font=font)
for i, name in enumerate(["center", "left", "right", "up", "down", "reset"]):
    t = tile(os.path.join(root, "checks", f"{name}.png"), dirs[name], name)
    sheet.paste(t, (PAD + (i % cols) * (TW + PAD), y0 + 40 + (i // cols) * (TH + PAD)))
os.makedirs(os.path.dirname(out), exist_ok=True)
sheet.save(out)
print(out, sheet.size)

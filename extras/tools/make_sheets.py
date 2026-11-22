"""Rebuild the 4 x 2 contact sheets of the eight texture sets from renders_textures/.

    python extras/tools/make_sheets.py
"""
import glob
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RT = os.path.join(ROOT, "renders_textures")
W, H = 960, 540
try:
    FONT = ImageFont.truetype("arial.ttf", 26)
except OSError:
    FONT = ImageFont.load_default()


def sheet(files, out):
    im = Image.new("RGB", (W * 4, H * 2))
    for i, f in enumerate(sorted(files)[:8]):
        t = Image.open(f).convert("RGB").resize((W, H), Image.LANCZOS)
        name = os.path.basename(f).split(".")[0]
        for suf in ("_eyes", "_macro", "_front"):
            name = name.replace(suf, "")
        ImageDraw.Draw(t).text((16, 12), name.replace("_", " "), fill=(255, 255, 255), font=FONT,
                               stroke_width=2, stroke_fill=(0, 0, 0))
        im.paste(t, ((i % 4) * W, (i // 4) * H))
    im.save(out, optimize=True)
    print(out, len(files))


sheet(glob.glob(os.path.join(RT, "T0?_*.png")), os.path.join(RT, "extra", "sheets", "sheet_portrait.png"))
sheet(glob.glob(os.path.join(RT, "extra", "eyes", "T0?_*_eyes.png")), os.path.join(RT, "extra", "eyes", "sheet_eyes.png"))
sheet(glob.glob(os.path.join(RT, "extra", "macro", "T0?_*_macro.png")), os.path.join(RT, "extra", "macro", "sheet_macro.png"))
sheet(glob.glob(os.path.join(RT, "extra", "same_head", "T0?_*_front.png")),
      os.path.join(RT, "extra", "sheets", "sheet_same_head.png"))

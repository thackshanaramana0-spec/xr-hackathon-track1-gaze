"""Fill the organisers' submission template (Submission_Final_forGithub.pptx) -> presentation/SRMIST_Rocklef.pptx.

    python presentation/build_ppt.py [path/to/Submission_Final_forGithub.pptx]
"""
import os
import sys

import numpy as np
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = os.path.dirname(ROOT)            # repository top level (submission files)
def top(*p):
    return os.path.join(TOP, *p)
TPL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.expanduser("~"), "Downloads",
                                                         "Submission_Final_forGithub.pptx")
OUT = os.path.join(ROOT, "presentation", "SRMIST_Rocklef.pptx")
TMP = os.path.join(ROOT, "_build", "ppt")
os.makedirs(TMP, exist_ok=True)

BG_RGB = (0x0A, 0x0E, 0x1A)
BG, PANEL, NAVY = RGBColor(*BG_RGB), RGBColor(0x11, 0x18, 0x2B), RGBColor(0x0D, 0x1B, 0x3E)
CYAN, BLUE, TEAL, ORANGE = RGBColor(0x00, 0xB4, 0xD8), RGBColor(0x3D, 0x8B, 0xFF), RGBColor(0x19, 0xD3, 0xA2), RGBColor(0xF5, 0xA0, 0x00)
WHITE, GREY, LIGHT, DIM = RGBColor(0xF4, 0xF6, 0xFA), RGBColor(0x8A, 0x94, 0xA8), RGBColor(0xC6, 0xCD, 0xDB), RGBColor(0x55, 0x60, 0x75)
GREEN = RGBColor(0x34, 0xD3, 0x99)
LINE = RGBColor(0x23, 0x2D, 0x45)
SANS, SEMI, LITE, MONO = "Segoe UI", "Segoe UI Semibold", "Segoe UI Light", "Cascadia Mono"
REPO = "github.com/rocklef/xr-hackathon-track1-gaze"


def rp(*p):
    return os.path.join(ROOT, *p)


# ------------------------------------------------------------------ image prep
def prep(src, box, name, out_wh, fade=None, fade_frac=0.4):
    """Crop (fractions), resize to out_wh px, optionally fade one edge into the slide background."""
    im = Image.open(src).convert("RGB")
    w, h = im.size
    im = im.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h))).resize(out_wh, Image.LANCZOS)
    if fade:
        a = np.asarray(im, np.float64)
        W, H = out_wh
        n = int((W if fade in ("left", "right") else H) * fade_frac)
        ramp = np.clip(np.linspace(0, 1, n), 0, 1) ** 1.6
        m = np.ones((H, W))
        if fade == "left":
            m[:, :n] = ramp[None, :]
        elif fade == "right":
            m[:, W - n:] = ramp[::-1][None, :]
        elif fade == "bottom":
            m[H - n:, :] = ramp[::-1][:, None]
        a = a * m[..., None] + np.array(BG_RGB)[None, None, :] * (1 - m[..., None])
        im = Image.fromarray(a.clip(0, 255).astype(np.uint8))
    out = os.path.join(TMP, name + ".png")
    im.save(out)
    return out


# ------------------------------------------------------------------ drawing helpers
def tb(slide, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, line_sp=None):
    """runs: list of paragraphs; each paragraph is a list of (text, font, size, color[, spacing]) tuples."""
    t = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = t.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, m, 0)
    for i, para in enumerate(runs):
        after = 0
        if isinstance(para, dict):
            after, para = para.get("after", 0), para["runs"]
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(after)
        if line_sp:
            p.line_spacing = line_sp
        for r_ in para:
            txt, font, size, col = r_[:4]
            r = p.add_run()
            r.text = txt
            r.font.name, r.font.size = font, Pt(size)
            r.font.color.rgb = col
            if len(r_) > 4:
                r.font._element.set("spc", str(r_[4]))
    return t


def P(*runs, after=0):
    return {"after": after, "runs": list(runs)}


def kicker(slide, x, y, s, col=CYAN):
    tb(slide, x, y, 6, 0.25, [[(s.upper(), SEMI, 9.5, col, 250)]])


def rect(slide, x, y, w, h, fill, line=None, round_=0.0):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if round_ else MSO_SHAPE.RECTANGLE,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(1)
    if round_:
        s.adjustments[0] = round_
    s.shadow.inherit = False
    return s


def hline(slide, x, y, w, col=LINE, weight=0.02):
    return rect(slide, x, y, w, weight, col)


def pic(slide, path, x, y, w=None, h=None):
    kw = {}
    if w:
        kw["width"] = Inches(w)
    if h:
        kw["height"] = Inches(h)
    return slide.shapes.add_picture(path, Inches(x), Inches(y), **kw)


def remove(shape):
    shape._element.getparent().remove(shape._element)


def retext(shape, s, size=None, col=None, font=None):
    p = shape.text_frame.paragraphs[0]
    for q in list(shape.text_frame.paragraphs)[1:]:
        q._p.getparent().remove(q._p)
    for r in list(p.runs)[1:]:
        r._r.getparent().remove(r._r)
    r = p.runs[0] if p.runs else p.add_run()
    r.text = s
    if size:
        r.font.size = Pt(size)
    if col:
        r.font.color.rgb = col
    if font:
        r.font.name = font


# ------------------------------------------------------------------ images
img_eye = prep(rp("renders_textures", "extra", "macro", "T03_olive_mediterranean_male_macro.png"),
               (0.25, 0.0, 0.9, 1.0), "eye", (1384, 1200), fade="left", fade_frac=0.42)
img_frame = prep(top("renders", "frame_00.png"), (0.06, 0.17, 0.94, 1.0), "frame", (1258, 1200),
                 fade="left", fade_frac=0.35)
orbit = rp("demo", "build", "orbit", "0089.png")
img_demo = prep(orbit if os.path.exists(orbit) else rp("renders_textures", "T03_olive_mediterranean_male.png"),
                (0.0, 0.0, 1.0, 1.0), "demo", (1600, 900))
img_sheet = rp("quality_audit", "gate0", "contact_sheet.png")
img_faces = prep(rp("renders_textures", "extra", "sheets", "sheet_portrait.png"), (0, 0, 1, 1), "faces", (3200, 900))


def thumb(src, box, name, wh=(640, 400)):
    return prep(src, box, name, wh)


# pipeline thumbnails, one real image per step
TH = {
    "head": thumb(rp("renders_textures", "T03_olive_mediterranean_male.png"), (0.3, 0.05, 0.75, 0.75), "th_head"),
    "look": thumb(rp("textures", "T03_olive_mediterranean_male", "T03_albedo.1002.png"), (0.26, 0.375, 0.74, 0.675),
                  "th_look"),
    "scene": thumb(top("renders", "frame_00.png"), (0.05, 0.2, 0.95, 0.76), "th_scene"),
    "output": thumb(rp("quality_audit", "gate0", "contact_sheet.png"), (0.0, 0.06, 0.6, 0.45), "th_output"),
}


def verifier_thumb():
    """Eye close-up with the pupil detected from the pixels (circle) and the metadata pupil (cross)."""
    import json
    from PIL import ImageDraw
    sys.path.insert(0, rp("tools"))
    import check_bundle as CB
    rec = json.load(open(top("metadata.json")))[2]
    e = rec["eyes_closeup"]
    path = top("renders_eyes", e["image"])
    im = Image.open(path).convert("RGB")
    (cx, cy), r = CB.detect_pupil(CB.lum(path), e["pupil_center_2D_R"], 120)
    mx, my = e["pupil_center_2D_R"]
    d = ImageDraw.Draw(im)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(52, 211, 153), width=4)
    d.line([mx - 22, my, mx + 22, my], fill=(245, 160, 0), width=4)
    d.line([mx, my - 22, mx, my + 22], fill=(245, 160, 0), width=4)
    im = im.crop((int(mx - 200), int(my - 125), int(mx + 200), int(my + 125))).resize((640, 400), Image.LANCZOS)
    out = os.path.join(TMP, "th_verify.png")
    im.save(out)
    return out


TH["verify"] = verifier_thumb()


def direction_tiles():
    """Same fixed crop of one eye for centre/left/right/up/down, with a crosshair at the centre pupil."""
    import json
    from PIL import ImageDraw
    dj = json.load(open(top("checks", "directions.json")))
    cx, cy = dj["center"]["eyes_closeup"]["pupil_center_2D_R"]
    half = 235
    out = {}
    for name in ("center", "left", "right", "up", "down"):
        im = Image.open(top("checks", f"eyes_{name}.png")).convert("RGB")
        im = im.crop((int(cx - half), int(cy - half * 0.8), int(cx + half), int(cy + half * 0.8)))
        im = im.resize((600, 480), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        c = (300, 240)
        d.line([c[0] - 600, c[1], c[0] + 600, c[1]], fill=(0, 180, 216), width=2)
        d.line([c[0], c[1] - 480, c[0], c[1] + 480], fill=(0, 180, 216), width=2)
        p = os.path.join(TMP, f"dir_{name}.png")
        im.save(p)
        out[name] = p
    seq = []
    for k in range(10):
        im = Image.open(top("renders_eyes", f"frame_{k:02d}.png")).convert("RGB")
        im = im.crop((int(cx - half), int(cy - half * 0.8), int(cx + half), int(cy + half * 0.8))).resize((300, 240),
                                                                                                         Image.LANCZOS)
        p = os.path.join(TMP, f"seq_{k}.png")
        im.save(p)
        seq.append(p)
    return out, seq


DIRS, SEQ = direction_tiles()
img_finale = prep(rp("renders_textures", "extra", "macro", "T03_olive_mediterranean_male_macro.png"), (0.1, 0.04, 0.9, 0.79),
                  "finale", (1920, 1080))
_f = np.asarray(Image.open(img_finale), np.float64)
Image.fromarray((_f * 0.28 + np.array(BG_RGB) * 0.72).astype(np.uint8)).save(img_finale)

prs = Presentation(TPL)
S = prs.slides
SH = {i: {s.name: s for s in S[i].shapes} for i in range(len(S))}

# ------------------------------------------------------------------ 1. title
s, sh = S[0], SH[0]
retext(sh["Text 7"], "TRACK 1", size=11)
remove(sh["Text 10"])
remove(sh["Text Box 22"])
tb(s, 0.55, 2.62, 8.7, 0.5, [[("Synthetic Eye Movement & Virtual Camera Rendering", SEMI, 20, CYAN)]])
tb(s, 0.55, 3.17, 8.0, 0.5, [[("Photorealistic eyes with calibrated 3D motion and per-frame ground truth checked against the pixels.", LITE, 13,
                               LIGHT)]])
hline(s, 0.55, 3.95, 8.6)
for x, lab, vals in ((0.55, "TEAM", ["SRMIST_Rocklef"]), (2.75, "COLLEGE", ["SRM Institute of", "Science and Technology"]),
                     (5.6, "MEMBERS", ["Sree Rohith Balaji", "Thackshanaramana"])):
    tb(s, x, 4.15, 2.9, 1.2, [P((lab, SEMI, 9, GREY, 250), after=5)] +
       [P((v, SANS, 14, WHITE), after=1) for v in vals])

# ------------------------------------------------------------------ 2. problem
s = S[1]
pic(s, img_eye, 4.55, 0.9, w=5.45, h=4.725)
kicker(s, 0.55, 1.3, "Why synthetic eyes")
tb(s, 0.55, 1.62, 4.6, 1.3, [[("Gaze models need large sets of labelled eyes.", SEMI, 24, WHITE)]], line_sp=0.95)
tb(s, 0.55, 2.72, 4.1, 0.7, [[("Manual capture is slow and privacy-sensitive, and the true gaze in real footage is not directly known.", LITE, 13, LIGHT)]])
pts = [("Slow and costly", "every angle, every face, recorded by hand", CYAN),
       ("Privacy-sensitive", "eyes and faces can count as biometric data", CYAN),
       ("Hard to label exactly", "the true gaze in real footage is not directly known", CYAN)]
for k, (h, b, c) in enumerate(pts):
    y = 3.55 + k * 0.6
    rect(s, 0.55, y + 0.06, 0.06, 0.38, c)
    tb(s, 0.78, y, 3.9, 0.55, [P((h, SEMI, 12.5, WHITE), after=1), P((b, SANS, 10.5, GREY))])

# ------------------------------------------------------------------ 3. solution
s = S[2]
pic(s, img_frame, 5.05, 0.9, w=4.95, h=4.725)
kicker(s, 0.55, 1.3, "Our approach", TEAL)
tb(s, 0.55, 1.62, 4.7, 1.0, [[("A calibrated, photorealistic eye rig in Blender.", SEMI, 24, WHITE)]], line_sp=0.95)
points = [("Photorealistic, articulated face", "8 skin and iris texture sets, 3D hair and lashes on the GNM head mesh"),
          ("3D eye rotation", "each eyeball rotates about its centre; both converge on one target"),
          ("Verified labels", "rotations, 2D pupils, camera matrix per frame, re-checked from the pixels")]
for k, (h, b) in enumerate(points):
    y = 2.6 + k * 0.52
    rect(s, 0.55, y + 0.05, 0.05, 0.38, TEAL)
    tb(s, 0.75, y, 4.1, 0.5, [P((h, SEMI, 12, WHITE), after=1), P((b, SANS, 9.5, GREY))])
facts = [("3D", "eyeball rotation\nabout each centre"), ("35 cm", "fixation target,\n±5 cm motion"),
         ("40 cm", "locked camera,\n1024 × 1024 PNG")]
for k, (big, small) in enumerate(facts):
    x = 0.55 + k * 1.5
    tb(s, x, 4.32, 1.45, 0.45, [[(big, SEMI, 22, TEAL)]])
    tb(s, x, 4.8, 1.45, 0.6, [P((l, SANS, 9.5, GREY)) for l in small.split("\n")])

# ------------------------------------------------------------------ 4. architecture
s = S[3]
kicker(s, 0.45, 1.15, "Pipeline")
tb(s, 0.45, 1.45, 9.1, 0.5, [[("From a parametric head to verified, labelled renders.", SEMI, 20, WHITE)]])
nodes = [("Head", "open base mesh\nrebuilt in NumPy", CYAN),
         ("Look", "skin, irises, hair\nUDIM, seam-free", CYAN),
         ("Scene", "target 35 cm\ncamera 40 cm", CYAN),
         ("Wrapper", "eyes.py: move,\nreset, render", CYAN),
         ("Output", "1024² PNG + JSON\npupils, rotations", CYAN),
         ("Verifier", "labels re-checked\nfrom the pixels", CYAN)]
nw, gap, y0 = 1.36, 0.19, 2.05
thumbs = ["head", "look", "scene", None, "output", "verify"]
for k, (h, b, c) in enumerate(nodes):
    x = 0.45 + k * (nw + gap)
    rect(s, x, y0, nw, 2.32, PANEL)
    if thumbs[k]:
        pic(s, TH[thumbs[k]], x, y0, w=nw, h=0.85)
    else:                                                       # the wrapper step: its actual API
        rect(s, x, y0, nw, 0.85, RGBColor(0x05, 0x07, 0x0E))
        tb(s, x + 0.1, y0 + 0.14, nw - 0.15, 0.6, [P(("eyes.", MONO, 9, GREY), ("move", MONO, 9, TEAL), ("(h,v)", MONO, 9, WHITE), after=2),
                                                   P(("eyes.", MONO, 9, GREY), ("reset", MONO, 9, TEAL), ("()", MONO, 9, WHITE), after=2),
                                                   P(("eyes.", MONO, 9, GREY), ("render", MONO, 9, TEAL), ("()", MONO, 9, WHITE))])
    rect(s, x, y0 + 0.85, nw, 0.04, c)
    tb(s, x + 0.12, y0 + 1.0, nw - 0.2, 0.25, [[(f"0{k + 1}", SEMI, 9, c, 100)]])
    tb(s, x + 0.12, y0 + 1.2, nw - 0.2, 0.35, [[(h, SEMI, 14, WHITE)]])
    tb(s, x + 0.12, y0 + 1.58, nw - 0.2, 0.65, [P((l, SANS, 9, GREY)) for l in b.split("\n")])
    if k < len(nodes) - 1:
        tb(s, x + nw, y0 + 1.25, gap, 0.4, [[("›", SEMI, 18, DIM)]], align=PP_ALIGN.CENTER)
hline(s, 0.45, 4.6, 9.1)
tb(s, 0.45, 5.3, 6.0, 0.22, [[("Base head mesh: Google GNM v3 (Apache-2.0). Everything else built by Team Rocklef.", SANS, 8, DIM)]])
tb(s, 0.45, 4.72, 1.4, 0.3, [[("BUILT WITH", SEMI, 9, GREY, 250)]])
tb(s, 1.75, 4.68, 7.8, 0.4, [[("Blender 5.2  ·  Cycles  ·  Python + bpy  ·  NumPy  ·  SciPy  ·  ffmpeg  ·  Docker",
                               SANS, 11, LIGHT)]])

# ------------------------------------------------------------------ 5. track final output
s = S[4]
retext(SH[4]["Text 2"], "TRACK FINAL OUTPUT")
kicker(s, 0.45, 1.15, "Track 1 results", ORANGE)
tb(s, 0.45, 1.45, 9.1, 0.5, [[("Track requirements, measured.", SEMI, 20, WHITE)]])
tw, tg = 0.94, (5.0 - 5 * 0.94) / 4
for k, name in enumerate(("center", "left", "right", "up", "down")):
    x = 0.45 + k * (tw + tg)
    pic(s, DIRS[name], x, 2.1, w=tw, h=tw * 0.8)
    tb(s, x, 2.9, tw, 0.25, [[(name.capitalize() + ("" if name == "center" else "  ✓"), SEMI, 9.5,
                               WHITE if name == "center" else GREEN)]], align=PP_ALIGN.CENTER)
sw, sg = 0.46, (5.0 - 10 * 0.46) / 9
tb(s, 0.45, 3.25, 5.0, 0.25, [[("10 CLOCKWISE FRAMES, θk = 2πk/10", SEMI, 8.5, GREY, 200)]])
for k in range(10):
    pic(s, SEQ[k], 0.45 + k * (sw + sg), 3.5, w=sw, h=sw * 0.8)
tb(s, 0.45, 3.97, 5.0, 0.5, [[("Same crop of one eye in every tile; the cyan cross marks the centre pupil.", SANS, 9,
                               GREY)]])
rows = [("40", "Direction pass/fail", "5 / 5"), ("20", "Calibration", "35 / 40 cm"), ("20", "Automation", "1 command"),
        ("20", "Sequence & metadata", "≤ 1.9 px")]
for k, (pts_, lab, res) in enumerate(rows):
    y = 2.1 + k * 0.52
    tb(s, 5.8, y, 0.6, 0.45, [[(pts_, SEMI, 18, ORANGE)]], anchor=MSO_ANCHOR.MIDDLE)
    tb(s, 6.45, y, 1.9, 0.45, [[(lab, SANS, 11.5, WHITE)]], anchor=MSO_ANCHOR.MIDDLE)
    tb(s, 8.0, y, 1.55, 0.45, [[(res, SEMI, 13, GREEN)]], align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
    hline(s, 5.8, y + 0.49, 3.75)
tb(s, 5.8, 4.25, 3.75, 0.4, [[("21 / 22", SEMI, 13, GREEN), ("  independent checks pass, 1 not verified", SANS, 11, LIGHT)]])
hline(s, 0.45, 4.78, 9.1)
tb(s, 0.45, 4.9, 9.1, 0.3, [[("SRMIST_Rocklef.zip   ", SEMI, 10.5, WHITE),
                             ("scene.blend · wrapper/eyes.py · renders/ · metadata.json · README.md", SANS, 10.5, LIGHT)]])
tb(s, 0.45, 5.17, 9.1, 0.3, [[("Limitations: one identity in the evaluated sequence; 2K skin maps in the bundle (4K in "
                               "the repo); not yet tested on Blender 4.2.", SANS, 9, DIM)]])

# ------------------------------------------------------------------ 6. differentiation
s = S[5]
kicker(s, 0.45, 1.15, "Scope", TEAL)
tb(s, 0.45, 1.45, 9.1, 0.5, [[("What this project provides: textured head, 3D eye rotation, checked labels.", SEMI, 20, WHITE)]])
tb(s, 2.15, 2.15, 7.4, 0.3, [[("THIS PROJECT", SEMI, 9, TEAL, 200)]])
cmp_ = [("Face", "full textured GNM head, 8 identities, 3D hair"),
        ("Eye motion", "3D rotation about each eyeball, converging on one target"),
        ("Geometry", "35 cm fixation target, 40 cm locked camera"),
        ("Labels", "pupils re-detected in every frame; max deviation 1.92 px"),
        ("Platform", "Blender + Python, headless, Docker")]
for k, (a, c) in enumerate(cmp_):
    y = 2.5 + k * 0.5
    hline(s, 0.45, y, 9.1)
    tb(s, 0.45, y, 1.6, 0.5, [[(a, SEMI, 12, WHITE)]], anchor=MSO_ANCHOR.MIDDLE)
    tb(s, 2.15, y, 7.4, 0.5, [[(c, SANS, 11.5, WHITE)]], anchor=MSO_ANCHOR.MIDDLE)
hline(s, 0.45, 5.0, 9.1)

# ------------------------------------------------------------------ 7. demo & local setup
s = S[6]
kicker(s, 0.45, 1.15, "Try it", ORANGE)
tb(s, 0.45, 1.45, 4.6, 0.5, [[("One command per task.", SEMI, 20, WHITE)]])
rect(s, 0.45, 2.1, 4.75, 2.55, RGBColor(0x05, 0x07, 0x0E), line=LINE, round_=0.04)
for k, c in enumerate((RGBColor(0xFF, 0x5F, 0x57), RGBColor(0xFE, 0xBC, 0x2E), RGBColor(0x28, 0xC8, 0x40))):
    d = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.65 + k * 0.2), Inches(2.25), Inches(0.11), Inches(0.11))
    d.fill.solid()
    d.fill.fore_color.rgb = c
    d.line.fill.background()
cmd = [("$ ", "git clone " + REPO), ("$ ", "cd xr-hackathon-track1-gaze"), None,
       ("$ ", "blender -b scene.blend -P wrapper/eyes.py \\"), ("  ", "    -- --sequence"),
       ("$ ", "blender -b scene.blend -P wrapper/eyes.py \\"), ("  ", "    -- --directions"), None,
       ("# ", "Linux, no install:  docker build -t rocklef-gaze .")]
paras = []
for c in cmd:
    if c is None:
        paras.append(P(("", MONO, 5, GREY)))
    else:
        paras.append(P((c[0], MONO, 9.5, TEAL if c[0] == "$ " else DIM),
                       (c[1], MONO, 9.5, LIGHT if c[0] != "# " else DIM), after=2))
tb(s, 0.65, 2.5, 4.45, 2.4, paras)
pic(s, img_demo, 5.45, 2.1, w=4.1)
ring = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(5.45 + 2.05 - 0.32), Inches(2.1 + 1.153 - 0.32), Inches(0.64),
                          Inches(0.64))
ring.fill.solid()
ring.fill.fore_color.rgb = RGBColor(0x0A, 0x0E, 0x1A)
ring.line.color.rgb = WHITE
ring.line.width = Pt(1.5)
play = s.shapes.add_shape(MSO_SHAPE.ISOSCELES_TRIANGLE, Inches(5.45 + 2.05 - 0.1), Inches(2.1 + 1.153 - 0.13),
                          Inches(0.27), Inches(0.26))
play.rotation = 90
play.fill.solid()
play.fill.fore_color.rgb = WHITE
play.line.fill.background()
tb(s, 5.45, 4.5, 4.1, 0.3, [[("Demo video  ·  2:43", SEMI, 11.5, WHITE)]])
tb(s, 5.45, 4.78, 4.1, 0.3, [[(REPO, SANS, 10.5, CYAN)]])

# ------------------------------------------------------------------ 8. brownie
s = S[7]
kicker(s, 0.45, 1.15, "Beyond the brief", ORANGE)
tb(s, 0.45, 1.45, 9.1, 0.5, [[("Seam-free textures by construction.", SEMI, 20, WHITE)]])
pic(s, img_faces, 0.45, 2.05, w=9.1)
extras = [("8 identities", "skin + separate L/R irises,\nseam audit passes on all 8"),
          ("3D hair", "head hair, brows, lashes,\nstubble, fine facial hair"),
          ("Natural motion", "saccades, drift, blinks;\nLeft · Right · Generate Motion"),
          ("Timeline .blend", "lids, pupils, brows and gaze\nkeyed on the Timeline")]
for k, (h, b) in enumerate(extras):
    x = 0.45 + k * 2.32
    tb(s, x, 4.75, 2.2, 0.3, [[(h, SEMI, 12, WHITE)]])
    tb(s, x, 5.02, 2.2, 0.5, [P((l, SANS, 9, GREY)) for l in b.split("\n")])

# ------------------------------------------------------------------ 9. thank you
bgp = pic(S[8], img_finale, 0, 0, w=10, h=5.625)
S[8].shapes._spTree.remove(bgp._element)
S[8].shapes._spTree.insert(2, bgp._element)                     # behind the template's text
retext(SH[8]["Text 25"], REPO, size=11, col=WHITE)
SH[8]["Text 25"].text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
tb(S[8], 1.5, 3.3, 7.0, 0.4, [[("SRMIST_Rocklef  ·  Sree Rohith Balaji  ·  Thackshanaramana", SANS, 12, GREY)]],
   align=PP_ALIGN.CENTER)

# ------------------------------------------------------------------ 7 (new). novelty
import copy  # noqa: E402

src = S[5]
s = prs.slides.add_slide(src.slide_layout)
s.background.fill.solid()
s.background.fill.fore_color.rgb = BG
for name in ("Shape 0", "Shape 1", "Text 2"):                    # the template's header band, copied verbatim
    s.shapes._spTree.append(copy.deepcopy(SH[5][name]._element))
retext([x for x in s.shapes if x.name == "Text 2"][0], "NOVELTY")
ids = prs.slides._sldIdLst
new = ids[-1]
ids.remove(new)
ids.insert(6, new)                                               # right after Differentiation

A = TEAL                                                       # one accent colour on this slide
kicker(s, 0.45, 1.15, "Proposed extension · future scope", A)
tb(s, 0.45, 1.48, 3.9, 1.5, [P((l, SEMI, 21, WHITE)) for l in ("Proposed:", "self-verifying", "gaze labels for", "near-field XR.")],
   line_sp=0.92)
tb(s, 0.45, 2.95, 3.6, 0.6, [[("The checker re-measures pupil labels from each frame's pixels. The closed-loop layer "
                               "is proposed, not built.", LITE, 11.5, LIGHT)]])
hline(s, 0.45, 3.72, 3.6)
tb(s, 0.45, 3.85, 3.6, 0.25, [[("BUILT AND MEASURED", SEMI, 8.5, GREY, 200)]])
tb(s, 0.45, 4.08, 3.6, 0.5, [[("0.96 px", SEMI, 26, A), ("   mean label error", SANS, 10.5, LIGHT)]])
tb(s, 0.45, 4.62, 3.6, 0.3, [[("1.92 px max  ·  20 pupils  ·  10 frames", SANS, 9.5, GREY)]])
tb(s, 0.45, 4.92, 3.6, 0.45, [[("Next to measure: gaze-estimator accuracy, trained on raw vs verified labels.", SANS,
                                9, DIM)]])
steps = [("Research gap", "Synthetic gaze data often uses the renderer's geometric pupil [1]; corneal refraction [3] and "
                          "learned realism refiners [2, 4] can shift the pupil the camera sees."),
         ("Proposed layer", "A closed-loop verifier built on the calibrated rig, intended for other Blender scenes."),
         ("Mechanism", "Project the 3D pupil through K[R|t], detect the visible pupil with an occlusion-robust circle "
                       "fit, store both plus a confidence; reject or re-render outliers."),
         ("New applications", "Confidence-weighted XR tracker training, refraction-aware model benchmarks, auditing "
                              "sim-to-real refiners for label drift."),
         ("Expected impact", "Cleaner labels where errors matter most: near-eye views and large vergence. A full "
                             "prior-art review has not yet been done.")]
x0, rw, ry, rh = 4.55, 5.0, 1.42, 0.74
for k, (h, body) in enumerate(steps):
    y = ry + k * rh
    if k:
        hline(s, x0, y - 0.04, rw)
    tb(s, x0, y + 0.05, 0.45, 0.3, [[(f"0{k + 1}", SEMI, 11, A)]])
    tb(s, x0 + 0.5, y + 0.03, rw - 0.5, 0.3, [[(h, SEMI, 12, WHITE)]])
    tb(s, x0 + 0.5, y + 0.3, rw - 0.5, 0.42, [[(body, SANS, 9, GREY)]], line_sp=1.0)
tb(s, 0.45, 5.33, 8.3, 0.25, [[("[1] Wood et al., ETRA 2016   [2] Shrivastava et al., CVPR 2017   [3] Dierkes, Kassner & "
                                "Bulling, ETRA 2019   [4] Ruzzi et al., GazeNeRF, CVPR 2023", SANS, 7.5, DIM)]])

S = prs.slides
n = len(S)
for i in range(1, n - 1):                                      # page numbers on the content slides
    tb(S[i], 8.9, 5.3, 0.65, 0.22, [[(f"{i + 1:02d} / {n:02d}", SANS, 8, DIM, 100)]], align=PP_ALIGN.RIGHT)

prs.save(OUT)
print("saved", OUT)

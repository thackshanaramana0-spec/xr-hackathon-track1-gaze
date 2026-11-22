"""Assemble the GNM demo video (1920x1080, 30 fps, H.264 + AAC, <= 3 min).

    python demo/narration.py                  # voiceover + word timings (edge-tts)
    blender ... -P demo/shots.py -- --shot timeline|identity|orbit   # Blender shots -> demo/build/<shot>/
    python demo/make_demo.py                  # -> demo/SRMIST_Rocklef_demo.mp4 (+ .srt)
    python demo/make_demo.py --preview 6      # every 6th frame, fast check
    python demo/make_demo.py --still apps@3,textures@9   # single frames -> demo/build/stills/

Footage: renders_eyes_cli/<Left|Right|Generate_Motion>/frames (eyes_cli.py), demo/build/<shot>/ (shots.py), and the
application scenes from our earlier character work (legacy/video/build/app_*, tools/render_app_scene.py). Stills: renders_textures/, textures/,
quality_audit/. Overlay data (gaze, blinks, controls) comes from the same motion model the renders were keyed from
(gnm_rig/motion.py), so every on-screen number matches the picture.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "gnm_rig"))
import motion as MO  # noqa: E402

BUILD = os.path.join(ROOT, "demo", "build")
LEGACY = os.path.join(ROOT, "legacy", "video", "build")
OUTDIR = os.path.join(ROOT, "demo")
W, H, FPS = 1920, 1080, 30
XF = 0.6     # crossfade seconds
LEAD = 0.5   # picture before the voice starts in each scene

# ------------------------------------------------------------------ design system
BG = (0, 0, 0)
FG = (245, 245, 247)
GREY = (134, 134, 139)
DIM = (92, 92, 98)
HAIR = (44, 44, 48)
PANEL = (18, 18, 21)
BLUE = (41, 151, 255)
GREEN = (48, 209, 88)
RED = (255, 69, 58)
SOFTRED = (255, 120, 110)
AMBER = (255, 179, 64)
CYAN = (100, 210, 255)
PURPLE = (191, 90, 242)
GRAD = ((100, 210, 255), (94, 120, 255), (191, 90, 242))      # signature gradient
GRAD_G = ((48, 209, 88), (100, 210, 255))
FONTS = r"C:\Windows\Fonts"

TEX = [("T01", "fair_young_female", "Fair · young"), ("T02", "fair_male_stubble", "Fair · stubble"),
       ("T03", "olive_mediterranean_male", "Olive · Mediterranean"), ("T04", "east_asian_female", "East Asian"),
       ("T05", "south_asian_male", "South Asian"), ("T06", "african_female", "African"),
       ("T07", "elderly_caucasian_male", "Elderly · wrinkles"), ("T08", "latina_female", "Latina")]

_fonts = {}
WGT = {"light": 300, "regular": 400, "medium": 500, "semibold": 600, "bold": 700}


def F(size, w="regular"):
    """Segoe UI Variable (Display optical size for large type); Cascadia Mono for code."""
    key = (size, w)
    if key not in _fonts:
        try:
            if w == "mono":
                f = ImageFont.truetype(os.path.join(FONTS, "CascadiaMono.ttf"), size)
            else:
                f = ImageFont.truetype(os.path.join(FONTS, "SegUIVar.ttf"), size)
                f.set_variation_by_axes([WGT[w], 36 if size >= 40 else 10.5])
        except (OSError, ValueError):
            f = ImageFont.truetype(os.path.join(FONTS, "consola.ttf" if w == "mono" else "segoeui.ttf"), size)
        _fonts[key] = f
    return _fonts[key]


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def eio(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def eout(x):
    x = clamp(x)
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def fade(t, st, dur=0.5):
    return ease((t - st) / dur)


def lerp(a, b, k):
    return a + (b - a) * k


# ------------------------------------------------------------------ raster helpers
_lut = {}


def with_alpha(im, a):
    if a >= 0.999:
        return im
    q = int(a * 100)
    if q not in _lut:
        _lut[q] = [int(v * q / 100) for v in range(256)]
    im = im.copy()
    im.putalpha(im.getchannel("A").point(_lut[q]))
    return im


def put(img, im, x, y, a=1.0):
    """Alpha-composite `im` at (x, y) with opacity a, clipped to the canvas."""
    if im is None or a <= 0.003:
        return
    x, y = int(round(x)), int(round(y))
    w, h = im.size
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(w, img.size[0] - x), min(h, img.size[1] - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    if (sx0, sy0, sx1, sy1) != (0, 0, w, h):
        im = im.crop((sx0, sy0, sx1, sy1))
    img.alpha_composite(with_alpha(im, a), (x + sx0, y + sy0))


def canvas():
    return Image.new("RGBA", (W, H), (*BG, 255))


_grad = {}


def grad_img(w, h, stops, vertical=False):
    key = (w, h, stops, vertical)
    if key not in _grad:
        n = h if vertical else w
        xs = np.linspace(0, 1, max(2, n))
        pos = np.linspace(0, 1, len(stops))
        cols = np.stack([np.interp(xs, pos, [s[c] for s in stops]) for c in range(3)], -1).astype(np.uint8)
        arr = np.repeat(cols[:, None], w, 1) if vertical else np.repeat(cols[None], h, 0)
        _grad[key] = Image.fromarray(arr, "RGB")
    return _grad[key]


_timg = {}


def timg(s, font, fill=FG, grad=None, tracking=0):
    """Cached RGBA image of a text line; top edge = ascender line."""
    key = (s, id(font), fill, grad, tracking)
    if key in _timg:
        return _timg[key]
    asc, desc = font.getmetrics()
    if tracking:
        ws = [font.getlength(c) for c in s]
        tw = sum(ws) + tracking * max(0, len(s) - 1)
    else:
        tw = font.getlength(s)
    w, h = int(math.ceil(tw)) + 6, asc + desc + 4
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    if tracking:
        x = 0.0
        for c, cw in zip(s, ws):
            d.text((x, 0), c, font=font, fill=255)
            x += cw + tracking
    else:
        d.text((0, 0), s, font=font, fill=255)
    col = grad_img(w, h, grad) if grad else Image.new("RGB", (w, h), fill)
    im = col.convert("RGBA")
    im.putalpha(m)
    _timg[key] = im
    return im


def _ax(x, w, anchor):
    return x - w / 2 if anchor == "m" else (x - w if anchor == "r" else x)


def text(img, x, y, s, font, fill=FG, a=1.0, anchor="l", grad=None, tracking=0):
    if not s or a <= 0:
        return 0
    im = timg(s, font, fill, grad, tracking)
    put(img, im, _ax(x, im.size[0], anchor), y, a)
    return im.size[0]


def tw(s, font, tracking=0):
    return timg(s, font, FG, None, tracking).size[0]


def reveal(img, x, y, s, font, t, st, fill=FG, a=1.0, anchor="l", grad=None, dur=0.8, out=None, tracking=0):
    """Line rises from behind an invisible mask edge (expo-out), the launch-film text move."""
    if not s or t < st:
        return
    u = (t - st) / dur
    p = eout(u)
    al = clamp(u * 1.7) * a
    if out is not None:
        al *= 1 - clamp((t - out) / 0.4)
    if al <= 0:
        return
    im = timg(s, font, fill, grad, tracking)
    w, h = im.size
    dy = int((1 - p) * h * 0.6)
    if dy >= h:
        return
    put(img, im.crop((0, 0, w, h - dy)) if dy else im, _ax(x, w, anchor), y + dy, al)


def words(img, x, y, s, font, t, st, fill=FG, a=1.0, anchor="l", grad=None, stagger=0.07, dur=0.7):
    """Word-by-word reveal."""
    total = tw(s, font)
    x0 = _ax(x, total, anchor)
    acc = ""
    for k, wd in enumerate(s.split(" ")):
        off = font.getlength(acc + " ") if acc else 0
        reveal(img, x0 + off, y, wd, font, t, st + stagger * k, fill, a, "l", grad, dur)
        acc = (acc + " " + wd) if acc else wd


def eyebrow(img, x, y, s, t=None, st=0.0, col=GREY, a=1.0, anchor="l", size=20):
    f = F(size, "semibold")
    if t is None:
        text(img, x, y, s.upper(), f, col, a, anchor, tracking=3)
    else:
        reveal(img, x, y, s.upper(), f, t, st, col, a, anchor, tracking=3, dur=0.6)


_rr = {}


def rr_mask(w, h, r):
    key = (w, h, r)
    if key not in _rr:
        m = Image.new("L", (w * 2, h * 2), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, w * 2 - 1, h * 2 - 1), r * 2, fill=255)
        _rr[key] = m.resize((w, h), Image.LANCZOS)
    return _rr[key]


def rounded(im, r=24):
    im = im.convert("RGBA")
    if r <= 0:
        return im
    im.putalpha(rr_mask(im.size[0], im.size[1], int(r)))
    return im


_shadow = {}


def card(img, im, x, y, r=24, a=1.0, shadow=True):
    w, h = im.size
    if shadow:
        key = (w, h, r)
        if key not in _shadow:
            pad = 60
            m = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
            ImageDraw.Draw(m).rounded_rectangle((pad, pad + 18, pad + w, pad + h + 18), r, fill=200)
            sh = Image.new("RGBA", m.size, (0, 0, 0, 255))
            sh.putalpha(m.filter(ImageFilter.GaussianBlur(28)))
            _shadow[key] = sh
        put(img, _shadow[key], x - 60, y - 60, a)
    put(img, rounded(im, r), x, y, a)


def outline(img, box, r, col=(255, 255, 255), alpha=34, width=1, a=1.0):
    x0, y0, x1, y1 = [int(v) for v in box]
    lay = Image.new("RGBA", (x1 - x0 + 1, y1 - y0 + 1), (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle((0, 0, x1 - x0, y1 - y0), r, outline=(*col, int(alpha * a)), width=width)
    put(img, lay, x0, y0)


def glass(img, box, a=1.0, r=24, tint=(10, 10, 12), op=0.8, border=True):
    """Frosted-glass panel: blurred backdrop + tint + hairline."""
    if a <= 0:
        return
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    w, h = x1 - x0, y1 - y0
    if w < 4 or h < 4:
        return
    reg = img.crop((x0, y0, x1, y1))
    sm = reg.resize((max(1, w // 6), max(1, h // 6)), Image.BILINEAR).filter(ImageFilter.GaussianBlur(3))
    sm = Image.blend(sm.resize((w, h), Image.BILINEAR), Image.new("RGBA", (w, h), (*tint, 255)), op)
    m = rr_mask(w, h, r)
    if a < 0.999:
        m = m.point([int(v * a) for v in range(256)])
    img.paste(sm, (x0, y0), m)
    if border:
        outline(img, (x0, y0, x1 - 1, y1 - 1), r, alpha=40, a=a)


def panel(img, box, a=1.0, r=24, fill=PANEL, op=235, border=True):
    if a <= 0:
        return
    x0, y0, x1, y1 = [int(v) for v in box]
    lay = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle((0, 0, x1 - x0 - 1, y1 - y0 - 1), r, fill=(*fill, op),
                                          outline=(255, 255, 255, 30) if border else None, width=1)
    put(img, lay, x0, y0, a)


def hline(img, x0, x1, y, a=1.0, col=HAIR, width=1):
    if a <= 0 or x1 <= x0:
        return
    put(img, Image.new("RGBA", (int(x1 - x0), width), (*col, 255)), x0, y, a)


def dot(img, cx, cy, r, col, a=1.0):
    if a <= 0:
        return
    s = int(r * 2 + 4)
    lay = Image.new("RGBA", (s * 2, s * 2), (0, 0, 0, 0))
    ImageDraw.Draw(lay).ellipse((s - 2 * r, s - 2 * r, s + 2 * r, s + 2 * r), fill=(*col, 255))
    put(img, lay.resize((s, s), Image.LANCZOS), cx - s / 2, cy - s / 2, a)


def pill(img, x, y, s, col, a=1.0, size=22, anchor="l", pulse=1.0):
    """Status capsule: coloured dot + label."""
    if a <= 0:
        return
    f = F(size, "semibold")
    h = size + 22
    w = int(tw(s, f, 1)) + h + 22
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle((0, 0, w - 1, h - 1), h // 2, fill=(10, 10, 12, 215), outline=(*col, 150), width=2)
    rr = size * 0.3
    d.ellipse((h / 2 - rr, h / 2 - rr, h / 2 + rr, h / 2 + rr), fill=(*col, int(255 * clamp(pulse))))
    x0 = _ax(x, w, anchor)
    put(img, lay, x0, y, a)
    text(img, x0 + h - 2, y + (h - f.getmetrics()[0] - f.getmetrics()[1]) / 2 - 1, s, f, FG, a, tracking=1)


def check(img, cx, cy, r, kind, a):
    """yes = filled green disc with a check, partly = amber half disc, no = dim ring with a dash."""
    if a <= 0:
        return
    rr = r * (0.75 + 0.25 * eout(a * 1.2))
    s = int(rr * 2 + 6)
    k = 3
    lay = Image.new("RGBA", (s * k, s * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    c = s * k / 2
    R = rr * k
    if kind == "y":
        d.ellipse((c - R, c - R, c + R, c + R), fill=(*GREEN, 255))
        d.line([(c - R * 0.42, c + R * 0.02), (c - R * 0.1, c + R * 0.34), (c + R * 0.45, c - R * 0.32)],
               fill=(0, 0, 0, 255), width=int(R * 0.2), joint="curve")
    elif kind == "p":
        d.ellipse((c - R, c - R, c + R, c + R), outline=(*AMBER, 255), width=int(R * 0.12))
        d.pieslice((c - R * 0.72, c - R * 0.72, c + R * 0.72, c + R * 0.72), 90, 270, fill=(*AMBER, 255))
    else:
        d.ellipse((c - R, c - R, c + R, c + R), outline=(*DIM, 255), width=int(R * 0.1))
        d.line((c - R * 0.36, c, c + R * 0.36, c), fill=(*DIM, 255), width=int(R * 0.12))
    put(img, lay.resize((s, s), Image.LANCZOS), cx - s / 2, cy - s / 2, clamp(a * 2))


_scrim = {}


def scrim(img, x, y, w, h, op=0.75, up=False):
    """Black gradient (transparent at the top -> op at the bottom), for legible type on footage."""
    key = (w, h, op, up)
    if key not in _scrim:
        col = np.linspace(0, 1, h) ** 1.6 * 255 * op
        if up:
            col = col[::-1]
        a = Image.fromarray(np.repeat(col[:, None], w, 1).astype(np.uint8), "L")
        im = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        im.putalpha(a)
        _scrim[key] = im
    put(img, _scrim[key], x, y)


_side = {}


def side_gradient(img, width, right=False):
    key = (width, right)
    if key not in _side:
        g = (1 - np.linspace(0, 1, width)) ** 1.3 * 255
        g = np.clip(g * 1.25, 0, 255)
        if right:
            g = g[::-1]
        im = Image.new("RGBA", (width, H), (*BG, 255))
        im.putalpha(Image.fromarray(np.repeat(g[None], H, 0).astype(np.uint8), "L"))
        _side[key] = im
    put(img, _side[key], W - width if right else 0, 0)


_glow = {}


def glow_disc(size, col, op=0.5):
    key = (size, col, op)
    if key not in _glow:
        yy, xx = np.mgrid[0:size, 0:size]
        r = np.hypot(xx - size / 2, yy - size / 2) / (size / 2)
        a = np.clip(1 - r, 0, 1) ** 2.2 * 255 * op
        im = Image.new("RGBA", (size, size), (*col, 255))
        im.putalpha(Image.fromarray(a.astype(np.uint8), "L"))
        _glow[key] = im
    return _glow[key]


def kenburns(im, k, z0=1.0, z1=1.08, cx=0.5, cy=0.5):
    z = z0 + (z1 - z0) * k
    w, h = im.size
    cw, ch = w / z, h / z
    x0, y0 = (w - cw) * cx, (h - ch) * cy
    return im.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))


def cover(im, w, h, cx=0.5, cy=0.5, fast=False):
    """Scale + crop to fill (w, h)."""
    s = max(w / im.size[0], h / im.size[1])
    nw, nh = max(w, int(im.size[0] * s + 0.5)), max(h, int(im.size[1] * s + 0.5))
    r = im.resize((nw, nh), Image.BILINEAR if fast else Image.LANCZOS)
    x0, y0 = int((nw - w) * cx), int((nh - h) * cy)
    return r.crop((x0, y0, x0 + w, y0 + h))


def full(im, k=0.0, z0=1.0, z1=1.0, cx=0.5, cy=0.5):
    """Full-bleed frame with an optional slow push-in."""
    if z0 == z1 == 1.0 and im.size == (W, H):
        return im
    return kenburns(im, k, z0, z1, cx, cy).resize((W, H), Image.BILINEAR)


# ------------------------------------------------------------------ media
_cache = {}


def load(path):
    if path not in _cache:
        _cache[path] = Image.open(path).convert("RGBA")
    return _cache[path]


CLIPS = {"left": os.path.join(ROOT, "renders_eyes_cli", "Left", "frames"),
         "right": os.path.join(ROOT, "renders_eyes_cli", "Right", "frames"),
         "motion": os.path.join(ROOT, "renders_eyes_cli", "Generate_Motion", "frames"),
         "timeline": os.path.join(BUILD, "timeline"), "identity": os.path.join(BUILD, "identity"),
         "orbit": os.path.join(BUILD, "orbit"),
         # application scenes: our character work in legacy/ (re-rendered with tools/render_app_scene.py)
         "app_vr": os.path.join(LEGACY, "app_vr"), "app_car": os.path.join(LEGACY, "app_car"),
         "app_access": os.path.join(LEGACY, "app_access"), "app_medical": os.path.join(LEGACY, "app_medical")}
_nframes = {}


def nframes(clip):
    if clip not in _nframes:
        d = CLIPS[clip]
        _nframes[clip] = len([f for f in os.listdir(d) if f.endswith(".png")]) if os.path.isdir(d) else 0
    return _nframes[clip]


def clip_frame(clip, t, t0=0.0, speed=1.0, loop=False, pingpong=False):
    """Frame of a rendered clip at scene time t (clip time = t0 + t*speed), holding the last frame."""
    n = nframes(clip)
    if n == 0:
        im = Image.new("RGBA", (W, H), (24, 24, 28, 255))
        text(im, W // 2, H // 2 - 30, f"[{clip} not rendered]", F(40, "semibold"), GREY, anchor="m")
        return im
    i = int(math.floor((t0 + t * speed) * FPS))
    if pingpong:
        p = 2 * (n - 1)
        i = i % p
        i = i if i < n else p - i
    elif loop:
        i = i % n
    i = max(0, min(n - 1, i))
    while i > 0 and not os.path.exists(os.path.join(CLIPS[clip], f"{i + 1:04d}.png")):
        i -= 1
    return Image.open(os.path.join(CLIPS[clip], f"{i + 1:04d}.png")).convert("RGBA")


def rpath(*p):
    return os.path.join(ROOT, *p)


def tex_render(i, kind="main"):
    tid, name, _ = TEX[i]
    if kind == "main":
        return rpath("renders_textures", f"{tid}_{name}.png")
    if kind == "front":
        return rpath("renders_textures", "extra", "same_head", f"{tid}_{name}_front.png")
    return rpath("renders_textures", "extra", kind, f"{tid}_{name}_{kind}.png")


MOTION = {k: MO.synthesize(k) for k in ("left", "right", "motion", "expression")}


def chan(kind, name, t):
    d = MOTION[kind]
    i = max(0, min(len(d["t"]) - 1, int(t * FPS)))
    return float(d[name][i])


def saccades(kind, thresh=6.0):
    """(t_start, amplitude deg, duration s) for each saccade in a motion script, from the gaze channels."""
    d = MOTION[kind]
    gh, gv = d["gaze_h"], d["gaze_v"]
    sp = np.hypot(np.diff(gh), np.diff(gv)) * FPS
    moving = sp > 40
    out, i = [], 0
    while i < len(moving):
        if moving[i]:
            j = i
            while j < len(moving) and moving[j]:
                j += 1
            amp = math.hypot(gh[j] - gh[i], gv[j] - gv[i])
            if amp >= thresh:
                out.append((i / FPS, amp, MO.saccade_duration(amp)))
            i = j
        else:
            i += 1
    return out


# ------------------------------------------------------------------ voice + subtitles
SCENES = ("open", "apps", "problem", "title", "literature", "solution", "textures", "iris", "audit", "motion",
          "timeline", "identity", "architecture", "compare", "novelty", "future", "outro")
VOICE_DIR = os.path.join(BUILD, "voice")
VOICE = {k: json.load(open(os.path.join(VOICE_DIR, f"{k}.json"))) for k in SCENES
         if os.path.exists(os.path.join(VOICE_DIR, f"{k}.json"))}


def vdur(key):
    return VOICE[key]["words"][-1]["t1"] if key in VOICE else 0.0


def wt(key, word, nth=0, default=1.0):
    """Scene-local time at which `word` is spoken (nth occurrence)."""
    hits = [w["t0"] for w in VOICE.get(key, {}).get("words", []) if w["w"].lower().strip(",.:'") == word.lower()]
    return LEAD + hits[min(nth, len(hits) - 1)] if hits else default


def _punctuate(key, ws):
    toks = VOICE.get(key, {}).get("text", "").split()
    ti = 0
    for w in ws:
        for look in range(ti, min(ti + 4, len(toks))):
            core = toks[look].strip(",.:;!?")
            if core.lower() == w["w"].lower():
                w["p"] = toks[look][len(core):] if toks[look].startswith(core) else ""
                ti = look + 1
                break
    return ws


def subtitle_lines(key):
    ws = _punctuate(key, [dict(w) for w in VOICE.get(key, {}).get("words", [])])
    for w in ws:
        w["w"] = w["w"] + w.get("p", "")
    groups, cur = [], []
    for j, w in enumerate(ws):
        if cur and len(" ".join(x["w"] for x in cur + [w])) > 48:
            groups.append(cur)
            cur = []
        cur.append(w)
        gap = ws[j + 1]["t0"] - w["t1"] if j + 1 < len(ws) else 9
        if (gap > 0.3 or w["w"].endswith((".", "?", "!", ":"))) and len(" ".join(x["w"] for x in cur)) >= 14:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    k = 0
    while k < len(groups):
        txt = " ".join(x["w"] for x in groups[k])
        if len(txt) < 12 and len(groups) > 1:
            if k > 0 and len(" ".join(x["w"] for x in groups[k - 1] + groups[k])) <= 56:
                groups[k - 1] += groups.pop(k)
                continue
            if k + 1 < len(groups) and len(" ".join(x["w"] for x in groups[k] + groups[k + 1])) <= 56:
                groups[k] += groups.pop(k + 1)
                continue
        k += 1
    lines = [(g[0]["t0"], g[-1]["t1"], " ".join(x["w"] for x in g).rstrip(",:;")) for g in groups]
    res = []
    for k, (a, b, t) in enumerate(lines):
        nxt = lines[k + 1][0] if k + 1 < len(lines) else b + 0.6
        res.append((LEAD + a, LEAD + min(nxt, b + 0.6), t))
    return res


SUBS = {k: subtitle_lines(k) for k in VOICE}
_subimg = {}


def draw_subtitle(img, key, t):
    for a, b, s in SUBS.get(key, []):
        if a <= t < b:
            al = clamp(min((t - a) / 0.15, (b - t) / 0.15))
            if s not in _subimg:
                im = timg(s, F(36, "semibold"), FG)
                pad = 26
                sh = Image.new("RGBA", (im.size[0] + 2 * pad, im.size[1] + 2 * pad), (0, 0, 0, 255))
                m = Image.new("L", sh.size, 0)
                m.paste(im.getchannel("A"), (pad, pad + 2))
                sh.putalpha(m.filter(ImageFilter.GaussianBlur(9)).point(lambda v: min(255, int(v * 1.6))))
                sh.alpha_composite(im, (pad, pad))
                _subimg[s] = sh
            sh = _subimg[s]
            put(img, sh, W / 2 - sh.size[0] / 2, H - 112, al)
            return


# ------------------------------------------------------------------ shared pieces
SCENE_D = {}     # scene durations, filled in by build()


def gaze_hud(img, t, kind, t0, x, y, s=260, a=1.0, head=False):
    """Live gaze plot (deg) on frosted glass, from the motion model."""
    if a <= 0:
        return
    hh = s + 64 + (64 if head else 0)
    glass(img, (x, y, x + s, y + hh), a, r=26)
    lay = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    cx, cy = s / 2, s / 2
    sc = (s / 2 - 22) / 30.0
    for deg in (10, 20, 30):
        r = deg * sc
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, 22 if deg < 30 else 40), width=1)
    d.line((cx - 30 * sc, cy, cx + 30 * sc, cy), fill=(255, 255, 255, 26))
    d.line((cx, cy - 30 * sc, cx, cy + 30 * sc), fill=(255, 255, 255, 26))
    n = 36
    for k in range(n, 0, -1):
        tt = t0 + t - k / FPS
        if tt < 0:
            continue
        gh, gv = chan(kind, "gaze_h", tt), chan(kind, "gaze_v", tt)
        c = tuple(int(lerp(GRAD[0][i], GRAD[2][i], k / n)) for i in range(3))
        px, py = cx + gh * sc, cy - gv * sc
        rr = 2.6
        d.ellipse((px - rr, py - rr, px + rr, py + rr), fill=(*c, int(230 * (1 - k / (n + 1)))))
    gh, gv = chan(kind, "gaze_h", t0 + t), chan(kind, "gaze_v", t0 + t)
    px, py = cx + gh * sc, cy - gv * sc
    put(lay, glow_disc(44, CYAN, 0.7), px - 22, py - 22)
    d.ellipse((px - 6, py - 6, px + 6, py + 6), fill=(255, 255, 255, 255))
    put(img, lay, x, y + 56, a)
    eyebrow(img, x + 22, y + 22, "Gaze", a=a, col=GREY, size=18)
    text(img, x + s - 22, y + 18, f"{gh:+.1f}°  {gv:+.1f}°", F(22, "medium"), FG, a, anchor="r")
    if head:
        hy, eh = chan(kind, "head_yaw", t0 + t), chan(kind, "eye_h", t0 + t)
        hline(img, x + 22, x + s - 22, y + s + 62, a, (255, 255, 255))
        eyebrow(img, x + 22, y + s + 80, "Head", a=a, size=16)
        text(img, x + 22, y + s + 98, f"{hy:+.1f}°", F(24, "medium"), FG, a)
        eyebrow(img, x + s / 2 + 6, y + s + 80, "Eyes", a=a, size=16)
        text(img, x + s / 2 + 6, y + s + 98, f"{eh:+.1f}°", F(24, "medium"), FG, a)


def headline(img, t, eb, line, st=0.15, x=120, y=78, size=56, grad=None):
    eyebrow(img, x, y, eb, t, st, GREY)
    reveal(img, x, y + 38, line, F(size, "semibold"), t, st + 0.12, grad=grad)


# ------------------------------------------------------------------ applications (earlier characters)
APPS = [dict(clip="app_vr", word=("headset", 0), eb="Virtual reality", head="Sharp only where you look.",
             want=1.0, cy=0.35),
        dict(clip="app_car", word=("car", 0), eb="Driver monitoring", head="Eyes leave the road. It warns.",
             want=1.5, cy=0.4),
        dict(clip="app_access", word=("people", 0), eb="Eye typing", head="A keyboard for the eyes.",
             want=2.5, cy=0.5),
        dict(clip="app_medical", word=("and", 0), eb="Early screening", head="Gaze is studied as an early-screening signal.",
             want=0.6, cy=0.4)]
CW, CH, CG = 800, 450, 24
GX, GY = (W - 2 * CW - CG) // 2, 66
ZOOM = 0.8


def cell(i):
    return (GX + (i % 2) * (CW + CG), GY + (i // 2) * (CH + CG), CW, CH)


def app_times():
    s = [wt("apps", w, n, 2.5 + 2.4 * k) - 0.45 for k, (w, n) in enumerate(a["word"] for a in APPS)]
    return s, LEAD + vdur("apps") + 0.05


def app_clip_t(i, ta):
    s, _ = app_times()
    n = nframes(APPS[i]["clip"]) / FPS or 1.0
    return (ta - s[i] + APPS[i]["want"]) % n


def draw_app(img, i, ta, rect, a, k_full):
    """One application shot at rect (x, y, w, h); k_full 0 = grid cell, 1 = full screen."""
    if a <= 0:
        return
    x, y, w, h = [int(round(v)) for v in rect]
    tc = app_clip_t(i, ta)
    fr = clip_frame(APPS[i]["clip"], tc)
    im = cover(fr, w, h, 0.5, APPS[i]["cy"] * (1 - k_full) + 0.5 * k_full, fast=True)
    r = int(24 * (1 - k_full))
    put(img, rounded(im, r), x, y, a)
    if k_full < 0.5:
        sh = int(h * 0.42)
        lay = Image.new("RGBA", (w, sh), (0, 0, 0, 0))
        scrim(lay, 0, 0, w, sh, 0.7)
        put(img, rounded(lay, 0), x, y + h - sh, a * (1 - 2 * k_full))
        outline(img, (x, y, x + w - 1, y + h - 1), r, alpha=40, a=a)
        eyebrow(img, x + 26, y + h - 48, APPS[i]["eb"], col=FG, a=a * (1 - 2 * k_full), size=18)
    if APPS[i]["clip"] == "app_car":
        off = tc >= 5.0
        sz = int(lerp(18, 24, k_full))
        pill(img, x + lerp(22, 96, k_full), y + lerp(22, 80, k_full), "EYES OFF ROAD" if off else "EYES ON ROAD",
             RED if off else GREEN, a, sz, pulse=(0.35 + 0.65 * (int(tc * 4) % 2)) if off else 1.0)


def apps_layer(img, ta, show_text=True):
    s, t_back = app_times()
    full_r = (0, 0, W, H)

    def lr(r0, r1, k):
        return tuple(lerp(p, q, k) for p, q in zip(r0, r1))

    if ta < s[0]:                                           # opening grid: all four in parallel
        for i in range(4):
            a = eout((ta - 0.12 * i) / 0.7)
            x, y, w, h = cell(i)
            sc = 0.94 + 0.06 * a
            draw_app(img, i, ta, (x + w * (1 - sc) / 2, y + h * (1 - sc) / 2, w * sc, h * sc), a, 0)
        return
    if ta >= t_back:                                        # pull back to the grid
        k = eio((ta - t_back) / ZOOM)
        for i in range(3):
            x, y, w, h = cell(i)
            sc = 0.94 + 0.06 * k
            draw_app(img, i, ta, (x + w * (1 - sc) / 2, y + h * (1 - sc) / 2, w * sc, h * sc), k, 0)
        draw_app(img, 3, ta, lr(full_r, cell(3), k), 1.0, 1 - k)
        return
    f = max(j for j in range(4) if s[j] <= ta)
    if f == 0 and ta < s[0] + ZOOM:                         # dive into the first shot
        k = eio((ta - s[0]) / ZOOM)
        for i in range(1, 4):
            draw_app(img, i, ta, cell(i), 1 - k, 0)
        draw_app(img, 0, ta, lr(cell(0), full_r, k), 1.0, k)
    else:
        if f > 0 and ta < s[f] + 0.4:
            draw_app(img, f - 1, ta, full_r, 1.0, 1)
            draw_app(img, f, ta, full_r, ease((ta - s[f]) / 0.4), 1)
        else:
            draw_app(img, f, ta, full_r, 1.0, 1)
    if show_text:
        st = s[f] + (ZOOM if f == 0 else 0.25)
        end = s[f + 1] if f < 3 else t_back
        scrim(img, 0, H - 470, W, 470, 0.8)
        eyebrow(img, 96, 740, f"0{f + 1}   {APPS[f]['eb']}", t=ta, st=st, col=CYAN)
        reveal(img, 96, 776, APPS[f]["head"], F(64, "semibold"), ta, st + 0.1, out=end - 0.35)


def seg_open(t, d):
    img = canvas()
    put(img, full(clip_frame("motion", t, 0.4), t / d, 1.04, 1.12, 0.5, 0.42), 0, 0)
    gaze_hud(img, t, "motion", 0.4, W - 360, 64, 280, fade(t, 1.2, 0.6))
    return img


def seg_apps(t, d):
    img = canvas()
    apps_layer(img, t)
    return img


def seg_problem(t, d):
    img = canvas()
    t_dead = wt("problem", "many", 0, d * 0.6) - 0.4
    if t < t_dead + 0.6:
        a1 = 1 - fade(t, t_dead, 0.6)
        lay = canvas()
        apps_layer(lay, t + SCENE_D.get("apps", 15.0) - XF, show_text=False)
        kb = eio(t / 1.4)
        if kb > 0:
            bl = lay.resize((W // 6, H // 6), Image.BILINEAR).filter(ImageFilter.GaussianBlur(2.5)).resize((W, H),
                                                                                                           Image.BILINEAR)
            lay = Image.blend(lay, bl, kb)
            lay = Image.blend(lay, Image.new("RGBA", (W, H), (0, 0, 0, 255)), 0.62 * kb)
        put(img, lay, 0, 0, a1)
        reveal(img, W / 2, 250, "They all learn from real faces.", F(84, "semibold"), t, 0.7, a=a1, anchor="m")
        st0 = wt("problem", "filming", 0, 5.0) - 0.15
        reveal(img, W / 2, 420, "Filming real people is", F(38), t, st0, GREY, a1, "m")
        f = F(110, "semibold")
        items = [("slow", "Slow."), ("expensive", "Expensive."), ("private", "Private.")]
        gap = 56
        total = sum(tw(s, f) for _, s in items) + gap * 2
        x = W / 2 - total / 2
        for w_, s in items:
            st = wt("problem", w_, 0, 6.0) - 0.1
            reveal(img, x, 490, s, f, t, st, FG, a1, dur=0.6)
            x += tw(s, f) + gap
    if t >= t_dead:
        a2 = fade(t, t_dead, 0.6)
        reveal(img, W / 2, 96, "Many digital eyes still look static.", F(64, "semibold"), t, t_dead + 0.1, anchor="m", a=a2)
        ba = load(rpath("gnm_rig", "docs", "eye_before_after.png"))
        before = cover(ba.crop((0, 50, 960, 590)), 1180, 560, 0.5, 0.5)
        k = (t - t_dead) / max(1.0, d - t_dead)
        card(img, kenburns(before, k, 1.0, 1.06).resize((1180, 560), Image.BILINEAR), (W - 1180) / 2, 222, 28, a2)
        f = F(48, "semibold")
        items = [("glassy", "Glassy"), ("staring", "Staring"), ("stiff", "Stiff")]
        gap = 90
        total = sum(tw(s, f) for _, s in items) + gap * 2
        x = W / 2 - total / 2
        for w_, s in items:
            st = wt("problem", w_, 0, d - 2) - 0.1
            reveal(img, x, 818, s, f, t, st, SOFTRED, dur=0.5)
            x += tw(s, f) + gap
    return img


def seg_title(t, d, team):
    img = canvas()
    fr = clip_frame("orbit", t, 0.0)
    put(img, cover(fr, 1160, H, 0.5, 0.5, fast=True), W - 1160, 0, fade(t, 0.0, 1.2))
    side_gradient(img, 1060)
    st = wt("title", "synthetic", 0, 0.9) - 0.3
    eyebrow(img, 112, 300, "Samsung PRISM Hackathon 2026 | XR Perception Group | 3D Assets Track", t, st - 0.2)
    reveal(img, 106, 336, "Synthetic Eyes", F(132, "semibold"), t, st, grad=GRAD, dur=1.0)
    reveal(img, 112, 500, "Eye Movement & Virtual Camera Rendering", F(46), t, st + 0.25)
    reveal(img, 112, 586, "Photorealistic eyes and skin  ·  Scripted eye motion  ·  Python control", F(26), t, st + 0.5,
           GREY)
    t_team = wt("title", "team", 0, 3.5) - 0.3
    hline(img, 112, 112 + 520 * eout((t - t_team) / 0.9), 680, 1.0, HAIR)
    reveal(img, 112, 706, team[0], F(40, "semibold"), t, t_team)
    reveal(img, 112, 762, team[1], F(26), t, t_team + 0.12, GREY)
    reveal(img, 112, 802, team[2], F(24), t, t_team + 0.24, GREY)
    return img


LIT = [("3D head models", [("FLAME", "Li et al.  ·  SIGGRAPH Asia 2017"),
                           ("GNM Head", "Ploumpis et al.  ·  Google, 2026"),
                           ("Basel Face Model", "Paysan et al.  ·  AVSS 2009")],
        "Covers face shape and expression", "This project uses the GNM head and rig"),
       ("Eye rendering", [("Eye capture", "Bérard et al.  ·  SIGGRAPH Asia 2014"),
                          ("SynthesEyes", "Wood et al.  ·  ICCV 2015"),
                          ("UnityEyes", "Wood et al.  ·  ETRA 2016")],
        "Covers eye appearance", "This project adds eye motion and eyelid control"),
       ("Eye motion", [("Main sequence", "Bahill et al.  ·  Math. Biosci. 1975"),
                       ("Eyelid kinematics", "Evinger et al.  ·  IOVS 1991"),
                       ("Gaze in virtual agents", "Ruhland et al.  ·  CGF 2015")],
        "Covers eye movement", "This project applies scripted motion to a GNM head")]


def seg_literature(t, d):
    img = canvas()
    headline(img, t, "Related work", "What researchers built.", size=64)
    starts = [wt("literature", "head", 0, 1.0), wt("literature", "eye", 0, 3.0), wt("literature", "eye", 0, 3.0) + 0.6]
    t_gap = wt("literature", "but", 0, d - 4)
    for k, (head, papers, pro, con) in enumerate(LIT):
        x = 120 + k * 580
        st = starts[k] - 0.4
        eyebrow(img, x, 290, head, t, st, CYAN)
        hline(img, x, x + 500 * eout((t - st) / 0.9), 332, 1.0, HAIR)
        for j, (nm, meta) in enumerate(papers):
            sj = st + 0.12 * (j + 1)
            y = 362 + j * 112
            reveal(img, x, y, nm, F(36, "semibold"), t, sj)
            reveal(img, x, y + 50, meta, F(22), t, sj + 0.06, GREY)
        a_p = fade(t, t_gap - 0.3, 0.4)
        dot(img, x + 7, 736, 6, GREEN, a_p)
        text(img, x + 26, 718, pro, F(28), GREY, a_p)
        a_c = fade(t, t_gap + 0.5 + 0.6 * k, 0.4)
        dot(img, x + 7, 790, 6, GREY, a_c)
        reveal(img, x + 26, 772, con, F(28, "semibold"), t, t_gap + 0.5 + 0.6 * k)
    return img


def seg_solution(t, d):
    img = canvas()
    eyebrow(img, W / 2, 70, "Our solution", t, 0.1, anchor="m")
    f = F(64, "semibold")
    items = [("skin", "Photorealistic skin."), ("eyes", "Detailed eyes."), ("motion", "Scripted motion.")]
    gap = 34
    total = sum(tw(s, f) for _, s in items) + gap * 2
    x = W / 2 - total / 2
    for w_, s in items:
        reveal(img, x, 108, s, f, t, wt("solution", w_, 0, 2.0) - 0.2)
        x += tw(s, f) + gap
    cw, ch, g = 340, 460, 22
    strip = 8 * cw + 7 * g
    x0 = lerp(80, W - strip - 80, eio(t / d) * 0.9 + 0.05)
    for i in range(8):
        a = eout((t - 0.15 - 0.08 * i) / 0.8)
        im = cover(load(tex_render(i)), cw, ch, 0.55, 0.42)
        x = x0 + i * (cw + g)
        card(img, im, x, 250 + (1 - a) * 40, 26, a)
        text(img, x + 4, 728, TEX[i][0], F(20, "semibold"), FG, a)
        text(img, x + 56, 728, TEX[i][2], F(20), GREY, a)
    reveal(img, W / 2, 800, "All driven by one Python script.", F(48, "semibold"), t,
           wt("solution", "script", 0, d - 2) - 0.6, grad=GRAD, anchor="m")
    return img


_UVWIRE = {}


def uv_wire(size=620):
    """GNM skin UV layout (tile 1001) drawn over the T03 albedo."""
    if size not in _UVWIRE:
        alb = load(rpath("textures", "T03_olive_mediterranean_male", "T03_albedo.1001.png")).resize((size, size),
                                                                                                    Image.LANCZOS)
        ov = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        try:
            import gnm_model as G
            m = G.GNM()
            uv, reg = m.quad_uvs_udim()
            dd = ImageDraw.Draw(ov)
            for qi in np.where(reg == "skin")[0][::2]:
                pts = [(float(u) * size, (1 - float(v)) * size) for u, v in uv[qi]]
                dd.line(pts + [pts[0]], fill=(100, 210, 255, 80), width=1)
        except Exception as e:  # model file not present: plain albedo
            print("uv wire skipped:", e)
        alb = alb.copy()
        alb.alpha_composite(ov)
        _UVWIRE[size] = alb
    return _UVWIRE[size]


def flow(img, x0, x1, y, t, a):
    """Thin connector with a travelling light pulse."""
    if a <= 0:
        return
    hline(img, x0, x1, y, a, (70, 70, 78), 2)
    for k in range(2):
        p = ((t * 0.7 + k * 0.5) % 1.0)
        put(img, glow_disc(40, CYAN, 0.9), lerp(x0, x1, p) - 20, y - 19, a)
    lay = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    ImageDraw.Draw(lay).polygon([(4, 2), (20, 12), (4, 22)], fill=(200, 200, 210, 255))
    put(img, lay, x1 + 2, y - 11, a)


def seg_textures(t, d):
    img = canvas()
    t_eight = wt("textures", "eight", 0, d * 0.45) - 0.3
    t_pores = wt("textures", "pores", 0, d * 0.7) - 0.3
    if t < t_eight + 0.5:
        a = 1 - fade(t, t_eight, 0.5)
        headline(img, t, "01   Textures", "Painted on the head's own UV map.")
        a1 = eout((t - 0.3) / 0.9) * a
        card(img, uv_wire(620), 220, 236 + (1 - a1) * 30, 26, a1)
        text(img, 220, 880, "T03_albedo.1001.png   ·   4096 × 4096   ·   UDIM 1001", F(20, "mono"), GREY, a1)
        flow(img, 880, 1040, 546, t, fade(t, 1.4, 0.6) * a)
        a2 = eout((t - 1.9) / 0.9) * a
        head = cover(load(tex_render(2, "front")), 620, 620, 0.5, 0.38)
        card(img, head, 1080, 236 + (1 - a2) * 30, 26, a2)
        text(img, 1080, 880, "Wrapped straight onto the head", F(22), GREY, a2)
        st = wt("textures", "seams", 0, 4) - 0.2
        pill(img, 1676, 262, "Seam-free", GREEN, fade(t, st, 0.35) * a, 22, anchor="r")
    if t >= t_eight:
        a = fade(t, t_eight, 0.5) * (1 - fade(t, t_pores, 0.5))
        eyebrow(img, 120, 78, "01   Textures", col=GREY, a=a)
        reveal(img, 120, 116, "Eight faces across ages and backgrounds.", F(56, "semibold"), t, t_eight + 0.1, a=a)
        cw, ch, g = 400, 270, 24
        x0 = (W - 4 * cw - 3 * g) // 2
        for i in range(8):
            r, c = divmod(i, 4)
            x, y = x0 + c * (cw + g), 236 + r * (ch + g)
            ai = a * eout((t - t_eight - 0.06 * i) / 0.7)
            im = cover(load(tex_render(i, "front")), cw, ch, 0.5, 0.4)
            card(img, im, x, y + (1 - ai) * 24, 22, ai, shadow=False)
            if ai > 0.05:
                scrim(img, x, y + ch - 90, cw, 90, 0.6)
            text(img, x + 20, y + ch - 42, TEX[i][0], F(20, "semibold"), FG, ai)
            text(img, x + 72, y + ch - 42, TEX[i][2], F(20), (210, 210, 215), ai)
        text(img, W / 2, 836, "All 8 sets on one identical head: the maps are interchangeable.", F(24), GREY, a,
             anchor="m")
    if t >= t_pores:
        a = fade(t, t_pores, 0.5)
        k = (t - t_pores) / max(0.5, d - t_pores)
        put(img, full(load(tex_render(6, "macro")), k, 1.0, 1.12, 0.45, 0.4), 0, 0, a)
        side_gradient(img, 900)
        glass(img, (60, 236, 700, 830), a, r=30)
        eyebrow(img, 96, 78, "01   Textures", col=GREY, a=a)
        specs = [("pores", "Pores", "~0.4 mm, stronger in the T-zone"),
                 ("freckles", "Freckles", "and age spots"),
                 ("wrinkles", "Wrinkles", "forehead lines, crow's feet"),
                 ("eyebrows", "Eyebrows", "~900 hairs each, grown one by one")]
        for j, (w_, k1, k2) in enumerate(specs):
            st = wt("textures", w_, 0, t_pores + j) - 0.15
            y = 300 + j * 132
            if j:
                hline(img, 96, 96 + 560 * eout((t - st) / 0.8), y - 22, a, (70, 70, 76))
            reveal(img, 96, y, k1, F(48, "semibold"), t, st, a=a)
            reveal(img, 96, y + 62, k2, F(24), t, st + 0.08, (176, 176, 182), a)
    return img


def iris_crop(tid, name, tile, size=480):
    im = load(rpath("textures", f"{tid}_{name}", f"{tid}_albedo.{tile}.png"))
    w = im.size[0]
    r = int(w * 0.192)
    return im.crop((w // 2 - r, w // 2 - r, w // 2 + r, w // 2 + r)).resize((size, size), Image.LANCZOS)


_circ = {}


def circle(im):
    s = im.size[0]
    if s not in _circ:
        m = Image.new("L", (s * 2, s * 2), 0)
        ImageDraw.Draw(m).ellipse((4, 4, s * 2 - 5, s * 2 - 5), fill=255)
        _circ[s] = m.resize((s, s), Image.LANCZOS)
    im = im.copy()
    im.putalpha(_circ[s])
    return im


_iris = {}


def iris_img(i, tile, size):
    key = (i, tile, size)
    if key not in _iris:
        tid, name, _ = TEX[i]
        _iris[key] = circle(iris_crop(tid, name, tile, size))
    return _iris[key]


def seg_iris(t, d):
    img = canvas()
    t_pupil = wt("iris", "pupil", 0, d * 0.65) - 0.3
    a = 1 - fade(t, t_pupil, 0.5)
    if a > 0:
        headline(img, t, "02   Iris", "Every eye gets its own 4K iris.")
        sets = [0, 7, 2]
        L = max(0.8, t_pupil / len(sets))
        idx = min(len(sets) - 1, int(t / L))
        u = t - idx * L
        xf = clamp((u - (L - 0.45)) / 0.45) if idx < len(sets) - 1 else 0.0
        size = 470
        z = 1.0 + 0.04 * clamp(t / t_pupil)
        sz = int(size * z) // 2 * 2
        for k, (tile, side) in enumerate(((1004, "Right eye"), (1002, "Left eye"))):
            cx = 560 + k * 540
            cy = 560
            ak = eout((t - 0.3 - 0.15 * k) / 0.9) * a
            put(img, glow_disc(760, CYAN, 0.16), cx - 380, cy - 380, ak)
            for j, al in ((idx, 1 - xf), (min(len(sets) - 1, idx + 1), xf)):
                if al > 0:
                    put(img, iris_img(sets[j], tile, sz), cx - sz / 2, cy - sz / 2, ak * al)
            eyebrow(img, cx, 830, f"{side}  ·  tile {tile}", col=GREY, a=ak, anchor="m", size=18)
        for j, al in ((idx, 1 - xf), (min(len(sets) - 1, idx + 1), xf)):
            tid, _, lab = TEX[sets[j]]
            text(img, 830, 868, f"{tid}  ·  {lab}", F(22), (200, 200, 205), a * al * fade(t, 0.5), anchor="m")
        specs = [("fibres", "Stroma fibres", "domain-warped, with relief"), ("crypts", "Crypts & furrows",
                                                                                 "crypts of Fuchs, contraction folds"),
                 ("ring", "Collarette ring", "zig-zag ridge, pupillary ruff")]
        for j, (w_, k1, k2) in enumerate(specs):
            st = wt("iris", w_, 0, 1 + j) - 0.15
            y = 360 + j * 130
            hline(img, 1440, 1440 + 380 * eout((t - st) / 0.8), y - 20, a, (60, 60, 66))
            reveal(img, 1440, y, k1, F(36, "semibold"), t, st, a=a)
            reveal(img, 1440, y + 50, k2, F(22), t, st + 0.08, GREY, a)
    if t >= t_pupil:
        a2 = fade(t, t_pupil, 0.5)
        k = (t - t_pupil) / max(0.5, d - t_pupil)
        put(img, full(load(tex_render(0, "macro")), k, 1.0, 1.1, 0.5, 0.45), 0, 0, a2)
        side_gradient(img, 820)
        eyebrow(img, 96, 78, "02   Iris  ·  Cycles render, T01", col=GREY, a=a2)
        glass(img, (60, 580, 960, 850), fade(t, t_pupil + 0.2, 0.5), r=30)
        reveal(img, 96, 610, "The pupil traps light.", F(56, "semibold"), t, t_pupil + 0.3)
        reveal(img, 96, 684, "The cornea refracts it.", F(56, "semibold"), t, t_pupil + 0.5)
        reveal(img, 96, 770, "Tear film on the lid margins, clumped lashes, a soft lid shadow.", F(24), t,
               t_pupil + 0.8, (176, 176, 182))
    return img


def seg_audit(t, d):
    img = canvas()
    headline(img, t, "03   Quality audit", "Every seam, measured.")
    a0 = eout((t - 0.2) / 0.9)
    card(img, load(rpath("quality_audit", "T03_uv_seams_overlay.png")).resize((640, 640), Image.LANCZOS), 120,
         236 + (1 - a0) * 30, 26, a0)
    text(img, 120, 896, "Every UV seam on the skin, in red", F(22), GREY, a0)
    js = json.load(open(rpath("quality_audit", "seam_audit.json")))
    res = js["results"]
    x0 = 880
    reveal(img, x0, 240, f"Colour step across {js['seam_edges']} seam edges vs {js['baseline_edges']} edges of natural "
                         "skin detail", F(22), t, 0.5, GREY)
    st0 = wt("audit", "measured", 0, 2.0) - 0.3
    t_pass = wt("audit", "pass", 0, d - 1.5) - 0.4
    for k, (tid, name, lab) in enumerate(TEX):
        r = res[tid]["albedo"]
        y = 304 + k * 64
        a = fade(t, st0 + 0.1 * k, 0.35)
        text(img, x0, y, tid, F(26, "semibold"), FG, a)
        text(img, x0 + 72, y + 4, lab, F(22), GREY, a)
        bx = 1290
        g = eout((t - st0 - 0.1 * k) / 0.9)
        wb = int(r["base_mean"] * 40 * g)
        ws = int(r["seam_mean"] * 40 * g)
        if wb > 0:
            put(img, rounded(Image.new("RGBA", (max(6, wb), 6), (*DIM, 255)), 3), bx, y + 10, a)
        if ws > 0:
            put(img, rounded(grad_img(max(6, ws), 6, GRAD_G).convert("RGBA"), 3), bx, y + 24, a)
        if res[tid]["pass"]:
            check(img, 1786, y + 18, 16, "y", fade(t, t_pass + 0.08 * k, 0.3))
        hline(img, x0, 1810, y + 50, a * 0.6)
    a_l = fade(t, st0, 0.4)
    put(img, Image.new("RGBA", (22, 6), (*DIM, 255)), x0, 840, a_l)
    text(img, x0 + 32, 828, "natural detail", F(20), GREY, a_l)
    put(img, grad_img(22, 6, GRAD_G).convert("RGBA"), x0 + 200, 840, a_l)
    text(img, x0 + 232, 828, "across the seam", F(20), GREY, a_l)
    reveal(img, 1810, 818, "8 of 8 sets pass.", F(40, "semibold"), t, t_pass + 0.8, GREEN, anchor="r")
    return img


def terminal(img, x, y, w, h, lines, a):
    panel(img, (x, y, x + w, y + h), a, r=22, fill=(16, 16, 19), op=245)
    if a <= 0:
        return
    for k, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        dot(img, x + 30 + k * 24, y + 28, 6, c, a * 0.85)
    text(img, x + w / 2, y + 16, "zsh  ·  xr-track1", F(18), DIM, a, anchor="m")
    for k, (s, col) in enumerate(lines):
        text(img, x + 32, y + 66 + k * 40, s, F(26, "mono"), col, a)


def seg_motion(t, d):
    img = canvas()
    t_eyes = wt("motion", "eyes", 0, 6.0) - 0.4
    if t < t_eyes + 0.6:
        a = 1 - fade(t, t_eyes, 0.6)
        eyebrow(img, 120, 70, "04   Eye motion", col=GREY, a=a)
        reveal(img, 120, 108, "One script. Three inputs.", F(56, "semibold"), t, 0.25, a=a)
        cmds = [("left", "Left", "Left.mp4  ·  6 s"), ("right", "Right", "Right.mp4  ·  6 s"),
                ("motion", "Generate Motion", "Generate_Motion.mp4  ·  12 s")]
        lines = []
        for k, (clip, inp, out) in enumerate(cmds):
            st = wt("motion", inp.split()[0].lower(), 0, 0.8 + k) - 0.3
            cmd = f'python eyes_cli.py --input "{inp}"'
            n = int(len(cmd) * clamp((t - st) / 0.7))
            if t >= st:
                lines.append(("$ " + cmd[:n] + ("▍" if n < len(cmd) and int(t * 4) % 2 else ""), FG))
            if t >= st + 0.8:
                lines.append((f"  ✓ renders_eyes_cli/{out}", GREEN))
            x = 120 + k * 570
            ak = eout((t - st - 0.6) / 0.7) * a
            if ak > 0:
                fr = clip_frame(clip, max(0.0, t - st - 0.6), 0.6)
                im = kenburns(fr, 0.0, 1.55, 1.55, 0.5, 0.4).resize((540, 304), Image.BILINEAR)
                card(img, im, x, 548 + (1 - ak) * 24, 22, ak, shadow=False)
                outline(img, (x, 548, x + 539, 851), 22, alpha=40, a=ak)
                pill(img, x + 18, 566, inp, CYAN, ak, 18)
                text(img, x, 870, out, F(18, "mono"), GREY, ak)
        terminal(img, 120, 196, 1680, 320, lines, a)
    if t >= t_eyes:
        a = fade(t, t_eyes, 0.6)
        tt = t - t_eyes
        c0 = 0.4
        put(img, full(clip_frame("motion", tt, c0)), 0, 0, a)
        scrim(img, 0, 0, W, 260, 0.55, up=True)
        eyebrow(img, 96, 70, "04   Eye motion  ·  Generate_Motion.mp4", col=(200, 200, 205), a=a)
        t_head = wt("motion", "head", 0, 9) - 0.2
        gaze_hud(img, tt, "motion", c0, W - 380, 64, 300, a, head=t >= t_head)
        ct = tt + c0
        for (s0, amp, dur) in saccades("motion"):
            if s0 - 0.05 <= ct < s0 + 1.4:
                al = fade(ct, s0 - 0.05, 0.25) * (1 - fade(ct, s0 + 1.1, 0.3)) * a
                glass(img, (80, 640, 640, 880), al, r=26)
                eyebrow(img, 112, 668, "Saccade", col=CYAN, a=al, size=18)
                wn = text(img, 108, 700, f"{amp:.0f}°", F(96, "semibold"), FG, al, grad=GRAD)
                text(img, 108 + wn + 18, 742, f"in {dur * 1000:.0f} ms", F(40, "medium"), FG, al)
                text(img, 112, 828, "main sequence  ·  21 ms + 2.2 ms per degree", F(18), (176, 176, 182), al)
                break
        b = chan("motion", "blink", ct)
        ab = clamp(b * 4) * a
        if ab > 0:
            glass(img, (80, 160, 640, 290), ab, r=26)
            eyebrow(img, 112, 186, "Blink", col=AMBER, a=ab, size=18)
            text(img, 112, 216, "90 ms close  ·  190 ms open", F(36, "semibold"), FG, ab)
        lt = wt("motion", "eyelids", 0, d - 2) - 0.3
        if t >= lt:
            pill(img, 80, 320, "Eyelids follow the gaze", GREEN, fade(t, lt, 0.4), 22)
    return img


TL_CH = [("blink", "blink_L / blink_R", AMBER), ("brow_raise", "brow_raise", GREEN), ("brow_down", "brow_down", RED),
         ("wide", "wide", CYAN), ("squint", "squint", PURPLE), ("pupil", "pupil", (235, 235, 240)),
         ("gaze_h", "GAZE_Target x", (94, 140, 255)), ("gaze_v", "GAZE_Target z", (102, 212, 207))]
TL_BEATS = [(1.0, "Surprise"), (2.9, "Look left, look right"), (4.5, "Suspicious squint"), (6.6, "Eye roll"),
            (8.3, "Look down. Pupils shrink.")]


def seg_timeline(t, d):
    img = canvas()
    n = nframes("timeline")
    ct = min(t, (n - 1) / FPS if n else t)
    put(img, cover(clip_frame("timeline", t, 0.0), 1260, 1080, 0.5, 0.45, fast=True), 0, 0)
    scrim(img, 0, 0, 1260, 300, 0.6, up=True)
    eyebrow(img, 80, 66, "05   Timeline  ·  gnm_expression_timeline.blend", col=(200, 200, 205))
    for k, (bt, lab) in enumerate(TL_BEATS):
        nxt = TL_BEATS[k + 1][0] if k + 1 < len(TL_BEATS) else 99
        if bt - 0.2 <= ct < nxt - 0.2:
            reveal(img, 80, 104, lab, F(56, "semibold"), ct, bt - 0.2, out=nxt - 0.55)
    x0, y0, pw = 1280, 64, 600
    panel(img, (x0, y0, x0 + pw, 910), 1.0, r=24, fill=(20, 20, 23), op=250)
    eyebrow(img, x0 + 26, y0 + 24, "Timeline  ·  eye rig", size=16)
    text(img, x0 + pw - 26, y0 + 20, "315 frames", F(18), GREY, anchor="r")
    dd = ImageDraw.Draw(img)
    gx0, gx1 = x0 + 220, x0 + pw - 26
    exp = MOTION["expression"]
    T = exp["t"][-1]
    for k, (ch, lab, col) in enumerate(TL_CH):
        y = y0 + 74 + k * 96
        hline(img, x0 + 20, x0 + pw - 20, y + 88, 1.0, (40, 40, 44))
        text(img, x0 + 26, y + 30, lab, F(19, "mono"), col)
        v = np.asarray(exp[ch], dtype=float)
        lo, hi = (-30.0, 30.0) if ch.startswith("gaze") else ((-1.0, 2.0) if ch == "pupil" else (0.0, 1.0))
        xs = gx0 + (gx1 - gx0) * exp["t"] / T
        ys = y + 76 - 62 * np.clip((v - lo) / (hi - lo), 0, 1)
        dd.line(list(zip(xs[::2].tolist(), ys[::2].tolist())), fill=(*col, 255), width=2)
        i = int(ct * FPS)
        if i < len(v):
            dot(img, xs[i], ys[i], 6, col)
    px = gx0 + (gx1 - gx0) * min(1.0, ct / T)
    put(img, Image.new("RGBA", (2, 790), (*BLUE, 255)), px - 1, y0 + 60)
    fl = F(18, "semibold")
    lab = f"{int(ct * FPS) + 1}"
    wl = tw(lab, fl) + 22
    lay = Image.new("RGBA", (wl, 30), (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle((0, 0, wl - 1, 29), 15, fill=(*BLUE, 255))
    put(img, lay, px - wl / 2, 852)
    text(img, px, 855, lab, fl, FG, anchor="m")
    return img


ID_BEATS = [(1, {}), (35, {"ID_00": 2.6}), (70, {"ID_00": -2.2, "ID_02": 2.4}), (105, {"ID_01": 2.6, "ID_04": -2.0}),
            (140, {"ID_03": -2.6, "ID_05": 2.4}), (175, {"ID_06": 2.6, "ID_01": -2.0}), (210, {})]


def id_value(name, f):
    for (f0, a), (f1, b) in zip(ID_BEATS, ID_BEATS[1:]):
        if f0 <= f <= f1:
            k = ease((f - f0) / (f1 - f0))
            return a.get(name, 0.0) * (1 - k) + b.get(name, 0.0) * k
    return 0.0


def seg_identity(t, d):
    img = canvas()
    n = nframes("identity")
    speed = max(min(1.0, (n / FPS) / max(1.0, d - 0.2)), (n / FPS) / max(1.0, d)) if n else 1.0
    put(img, cover(clip_frame("identity", t, 0.0, speed), 1300, 1080, 0.5, 0.4, fast=True), 0, 0)
    scrim(img, 0, 0, 1300, 260, 0.55, up=True)
    scrim(img, 0, 640, 1300, 440, 0.8)
    eyebrow(img, 80, 66, "06   Face shape  ·  identity sliders", col=(200, 200, 205))
    st = wt("identity", "eyes", 0, 3) - 0.3
    reveal(img, 80, 104, "Change the face.", F(56, "semibold"), t, 0.4)
    reveal(img, 80, 770, "The eyes stay seated.", F(56, "semibold"), t, st)
    f = t * speed * FPS + 1
    x0, y0, pw = 1350, 150, 500
    panel(img, (x0, y0, x0 + pw, y0 + 650), 1.0, r=24, fill=(20, 20, 23), op=250)
    eyebrow(img, x0 + 26, y0 + 26, "Shape keys  ·  head", size=16)
    for k in range(7):
        nm = f"ID_{k:02d}"
        v = id_value(nm, f)
        y = y0 + 90 + k * 72
        on = abs(v) > 0.05
        text(img, x0 + 26, y, nm, F(20, "mono"), FG if on else GREY)
        bx0, bx1 = x0 + 130, x0 + 400
        put(img, rounded(Image.new("RGBA", (bx1 - bx0, 4), (52, 52, 58, 255)), 2), bx0, y + 12)
        mid = (bx0 + bx1) / 2
        xe = mid + (bx1 - bx0) / 2 * v / 3
        if on:
            wf = int(abs(xe - mid))
            if wf > 1:
                put(img, grad_img(wf, 4, GRAD).convert("RGBA"), min(mid, xe), y + 12)
        dot(img, xe, y + 14, 9, (255, 255, 255) if on else (120, 120, 126))
        text(img, x0 + pw - 26, y, f"{v:+.2f}", F(20, "medium"), FG if on else GREY, anchor="r")
    hline(img, x0 + 26, x0 + pw - 26, y0 + 590, 1.0, (44, 44, 48))
    text(img, x0 + 26, y0 + 606, "eyes.identity(ID_00=2.6)", F(18, "mono"), CYAN)
    return img


_WIRE = {}


def gnm_wire(size=700, col=(100, 210, 255)):
    key = (size, col)
    if key in _WIRE:
        return _WIRE[key]
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    try:
        import gnm_model as G
        m = G.GNM()
        v, _ = m()
        v = G.to_blender(v)
        ang = math.radians(-28)
        R = np.array([[math.cos(ang), -math.sin(ang), 0], [math.sin(ang), math.cos(ang), 0], [0, 0, 1]])
        p = v @ R.T
        c = p.mean(0)
        sc = size * 0.82 / (p[:, 2].max() - p[:, 2].min())
        X = (p[:, 0] - c[0]) * sc + size / 2
        Y = -(p[:, 2] - c[2]) * sc + size / 2
        dpth = p[:, 1]
        dd = ImageDraw.Draw(im)
        q = m.quads
        a, b, cc = p[q[:, 0]], p[q[:, 1]], p[q[:, 2]]
        nrm = np.cross(b - a, cc - a)
        front = nrm[:, 1] < 0
        dmin, dmax = dpth.min(), dpth.max()
        for qi in np.where(front)[0]:
            pts = [(float(X[i]), float(Y[i])) for i in q[qi]]
            z = (dpth[q[qi]].mean() - dmin) / (dmax - dmin)
            al = int(190 * (1 - z) + 25)
            dd.line(pts + [pts[0]], fill=(*col, al), width=1)
        glow = im.filter(ImageFilter.GaussianBlur(6))
        base = Image.new("RGBA", im.size, (0, 0, 0, 0))
        base.alpha_composite(glow)
        base.alpha_composite(im)
        im = base
    except Exception as e:
        print("wire skipped:", e)
    _WIRE[key] = im
    return im


ARCH = [("head", "Head model in NumPy", "gnm_model.py", "Skinning, correctives, 253 identity components"),
        ("expressions", "Expressions", "expressions.py", "Blink, wide, squint, brows solved in the model's eye space"),
        ("textures", "Textures", "textures.py  ·  iris_hq.py", "Baked in 3D through the head's UVs, 4K iris per eye"),
        ("wrapper", "Control wrapper", "eyes.py  ·  eyes_cli.py", "look()  ·  eyelids()  ·  blink()  ·  render()")]


def seg_architecture(t, d):
    img = canvas()
    headline(img, t, "Architecture", "Under the hood.")
    aw = eout((t - 0.2) / 1.2)
    put(img, gnm_wire(660), 60, 250 + (1 - aw) * 30, aw)
    text(img, 390, 912, "Head topology  ·  17,821 vertices", F(20), GREY, aw, anchor="m")
    # the one credit for the base mesh: a small card in the corner
    ca = aw * 0.9
    card_w, card_h = 330, 54
    lay = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    put(img, rounded(Image.new("RGBA", (card_w, card_h), (22, 22, 26, 235)), 10), W - card_w - 40, H - card_h - 40, ca)
    text(img, W - card_w - 24, H - card_h - 31, "Base head mesh: Google GNM v3", F(17, "medium"), (200, 200, 205), ca)
    text(img, W - card_w - 24, H - card_h - 9, "Apache-2.0  ·  everything else built by us", F(14), GREY, ca)
    times = [wt("architecture", k, 0, 1 + 2 * i) for i, (k, _, _, _) in enumerate(ARCH)]
    active = max([i for i, st in enumerate(times) if t >= st - 0.3] or [-1])
    x, x1 = 820, 1800
    for i, (k, ttl, fn, sub) in enumerate(ARCH):
        y = 262 + i * 168
        st = times[i] - 0.35
        on = i == active
        a = fade(t, st, 0.4)
        hline(img, x, lerp(x, x1, eout((t - st) / 0.9)), y - 24, 1.0, HAIR)
        reveal(img, x, y, f"0{i + 1}", F(30, "semibold"), t, st, grad=GRAD if on else None,
               fill=FG if on else DIM)
        reveal(img, x + 80, y - 6, ttl, F(44, "semibold"), t, st + 0.05, fill=FG if on else (120, 120, 126))
        text(img, x1, y + 6, fn, F(20, "mono"), CYAN if on else DIM, a, anchor="r")
        reveal(img, x + 80, y + 58, sub, F(24), t, st + 0.12, GREY if on else DIM)
    return img


SCORE = [("Whole photorealistic face", "8 identities, 3D hair"),
         ("Separate iris for each eye", "4K texture maps per eye"),
         ("Scripted eye motion", "saccades, drift and blinks"),
         ("Eyelids follow the gaze", "driven by vertical gaze")]
SCORE_WORDS = ("full", "separate", "scripted", "eyelids")


def seg_compare(t, d):
    """Lists what this project provides. It makes no claims about other systems."""
    img = canvas()
    headline(img, t, "This project", "What this project provides.")
    y0 = 300
    for r, (crit, detail) in enumerate(SCORE):
        st = wt("compare", SCORE_WORDS[r], 0, 1.5 + 1.4 * r) - 0.2
        y = y0 + r * 120
        hline(img, 120, lerp(120, 1830, eout((t - st + 0.2) / 0.9)), y + 104, 1.0, HAIR)
        reveal(img, 120, y + 26, crit, F(40, "semibold"), t, st - 0.2)
        reveal(img, 1000, y + 40, detail, F(30), t, st + 0.12, GREY)
    return img


NOV = [("avatars", "app_vr", 1.0, 0.32, "Avatars", "Eye motion for virtual characters"),
       ("cars", "app_car", 4.2, 0.4, "Driver monitoring", "Test in-cabin eye-tracking cameras"),
       ("trackers", "motion", 1.0, 0.42, "Eye-tracker training", "Labelled data for many face shapes"),
       ("medical", "app_medical", 0.6, 0.4, "Medical research", "Simulated eye-movement patterns")]


def seg_novelty(t, d):
    img = canvas()
    eyebrow(img, W / 2, 70, "Novelty & applications", t, 0.1, anchor="m")
    reveal(img, W / 2, 106, "Photorealistic textures. Eye kinematics. Python control.", F(52, "semibold"), t, 0.2,
           anchor="m")
    reveal(img, W / 2, 182, "Built in Blender and Python.", F(52, "semibold"), t, 0.45, anchor="m", grad=GRAD)
    cw, ch, g = 400, 470, 26
    x0 = (W - 4 * cw - 3 * g) // 2
    for k, (w_, clip, c0, cy, lab, sub) in enumerate(NOV):
        st = wt("novelty", w_, 0, 1 + k) - 0.35
        a = eout((t - st) / 0.7)
        if a <= 0:
            continue
        x = x0 + k * (cw + g)
        fr = clip_frame(clip, max(0.0, t - st), c0, loop=True)
        zoom = 1.45 if clip == "motion" else 1.0
        im = cover(kenburns(fr, 0, zoom, zoom, 0.5, 0.42), cw, ch, 0.5, cy, fast=True)
        card(img, im, x, 290 + (1 - a) * 30, 26, a)
        reveal(img, x + 4, 786, lab, F(32, "semibold"), t, st + 0.1)
        reveal(img, x + 4, 830, sub, F(20), t, st + 0.18, GREY)
    return img


_ir = {}


def ir_look(path, w, h):
    key = (path, w, h)
    if key not in _ir:
        g = ImageOps.grayscale(cover(load(path), w, h, 0.5, 0.45))
        g = ImageOps.autocontrast(g, cutoff=1).point(lambda v: int(255 * (v / 255) ** 0.8))
        im = Image.merge("RGB", (g, g, g)).convert("RGBA")
        im.alpha_composite(Image.merge("RGBA", (g, g, g, g.point(lambda v: 40))).filter(ImageFilter.GaussianBlur(8)))
        _ir[key] = im
    return _ir[key]


def seg_future(t, d):
    img = canvas()
    headline(img, t, "What's next", "Next steps.")
    cw, ch, g = 520, 380, 50
    x0 = (W - 3 * cw - 2 * g) // 2
    items = [("FLAME", "Same textures on FLAME", "UV-to-UV transfer"),
             ("infrared", "Infrared headset cameras", "Training data for eye trackers"),
             ("real", "Real time", "EEVEE and game-engine export")]
    for k, (w_, lab, sub) in enumerate(items):
        st = wt("future", w_, 0, 1 + k) - 0.35
        a = eout((t - st) / 0.7)
        if a <= 0:
            continue
        x = x0 + k * (cw + g)
        if k == 0:
            im = Image.new("RGBA", (cw, ch), (12, 14, 20, 255))
            wire = gnm_wire(420, (191, 140, 255))
            im.alpha_composite(wire, ((cw - 420) // 2, (ch - 420) // 2 + 10))
        elif k == 1:
            im = ir_look(tex_render(2, "eyes"), cw, ch).copy()
        else:
            im = cover(clip_frame("orbit", max(0.0, t - st), 2.0, loop=True), cw, ch, 0.5, 0.45, fast=True)
        card(img, im, x, 250 + (1 - a) * 30, 26, a)
        if k == 1:
            pill(img, x + 20, 270, "IR  850 nm", (220, 220, 225), a, 16)
        reveal(img, x, 668, f"0{k + 1}", F(28, "semibold"), t, st + 0.05, grad=GRAD)
        reveal(img, x, 712, lab, F(36, "semibold"), t, st + 0.1)
        reveal(img, x, 766, sub, F(22), t, st + 0.18, GREY)
    return img


def seg_outro(t, d, team, repo, emails):
    img = canvas()
    fr = clip_frame("orbit", t, 3.0, 0.5)
    bl = fr.resize((W // 8, H // 8), Image.BILINEAR).filter(ImageFilter.GaussianBlur(2)).resize((W, H), Image.BILINEAR)
    put(img, bl, 0, 0, 0.35)
    put(img, glow_disc(1400, (60, 90, 200), 0.18), W / 2 - 700, -300)
    reveal(img, W / 2, 150, "Synthetic Eyes", F(120, "semibold"), t, 0.2, grad=GRAD, anchor="m", dur=1.0)
    reveal(img, W / 2, 318, "Eye Movement & Virtual Camera Rendering", F(40), t, 0.45, anchor="m")
    hline(img, W / 2 - 260 * eout((t - 0.9) / 0.9), W / 2 + 260 * eout((t - 0.9) / 0.9), 480, 1.0, HAIR)
    reveal(img, W / 2, 530, team[0], F(52, "semibold"), t, 1.0, anchor="m")
    reveal(img, W / 2, 600, team[1], F(30), t, 1.2, GREY, anchor="m")
    reveal(img, W / 2, 648, team[2], F(26), t, 1.35, GREY, anchor="m")
    t_th = wt("outro", "thank", 0, 1.8)
    reveal(img, W / 2, 770, "Thank you.", F(48, "semibold"), t, max(1.6, t_th), anchor="m")
    return img


# ------------------------------------------------------------------ audio
def _noise_band(n, sr, lo, hi, seed):
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / sr)
    X[(f < lo) | (f > hi)] = 0
    y = np.fft.irfft(X, n)
    return y / (np.abs(y).max() + 1e-9)


def soundtrack(seconds, ticks, whooshes, impacts, sr=48000):
    """Original score: warm pad + soft pulse, with whooshes on section changes, an impact on the title and ticks on
    the PASS checks."""
    n = int(seconds * sr)
    tt = np.arange(n) / sr
    out = np.zeros(n)
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (196.0, 246.94, 293.66), (164.81, 207.65, 246.94)]
    seg = 8.0
    for i in range(int(seconds / seg) + 1):
        a, b = int(i * seg * sr), min(n, int((i + 1) * seg * sr + 2 * sr))
        if a >= n:
            break
        ts = tt[a:b] - i * seg
        env = np.minimum(1, ts / 2.0) * np.minimum(1, np.maximum(0, (seg + 2 - ts) / 2.0))
        root = chords[i % len(chords)][0]
        for f in chords[i % len(chords)]:
            for det in (-0.7, 0.7):
                out[a:b] += 0.045 * env * np.sin(2 * np.pi * (f + det) * ts) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.1 * ts))
        out[a:b] += 0.03 * env * np.sin(2 * np.pi * root / 2 * ts)
        # gentle pulse: eighth-note sub plucks on the root (~100 bpm)
        beat = 0.3
        for j in range(int(seg / beat) + 1):
            p0 = a + int(j * beat * sr)
            m = min(b, p0 + int(0.28 * sr)) - p0
            if m <= 0:
                continue
            tp = np.arange(m) / sr
            amp = 0.05 if j % 2 == 0 else 0.025
            out[p0:p0 + m] += amp * np.exp(-tp * 14) * np.sin(2 * np.pi * root / 4 * tp) * np.minimum(1, ts[0] + 1)
    for et in ticks:
        a = int(et * sr)
        m = min(n - a, int(0.25 * sr))
        if m > 0:
            ts = np.arange(m) / sr
            out[a:a + m] += 0.14 * np.exp(-ts * 26) * np.sin(2 * np.pi * 1318.5 * ts)
    for k, et in enumerate(whooshes):
        L = int(0.9 * sr)
        a = int(et * sr) - int(0.7 * sr)
        if a < 0 or a + L > n:
            continue
        y = _noise_band(L, sr, 300, 5000, k)
        tw_ = np.arange(L) / L
        env = np.where(tw_ < 0.78, (tw_ / 0.78) ** 2.5, np.exp(-(tw_ - 0.78) * 30))
        out[a:a + L] += 0.07 * env * y
    for k, et in enumerate(impacts):
        L = int(2.2 * sr)
        a = int(et * sr)
        if a + L > n:
            continue
        ti = np.arange(L) / sr
        f = 38 + 40 * np.exp(-ti * 6)
        ph = 2 * np.pi * np.cumsum(f) / sr
        out[a:a + L] += 0.32 * np.exp(-ti * 2.2) * np.sin(ph)
        out[a:a + L] += 0.10 * np.exp(-ti * 9) * _noise_band(L, sr, 40, 900, 99 + k)
    out *= np.clip(np.minimum(tt / 1.5, (seconds - tt) / 2.5), 0, 1)
    return np.tanh(out * 1.4) * 0.6


def decode(path, sr=48000):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def mix(path, music, cues, sr=48000):
    """Narration over the music bed; the music ducks under speech."""
    voice = np.zeros_like(music)
    for st, key in cues:
        p = os.path.join(VOICE_DIR, f"{key}.mp3")
        if os.path.exists(p):
            v = decode(p, sr)
            a = int(st * sr)
            m = max(0, min(len(v), len(voice) - a))
            voice[a:a + m] += v[:m]
    k = int(0.3 * sr)
    c = np.concatenate([[0.0], np.cumsum(np.abs(voice))])
    i = np.arange(len(voice))
    env = (c[np.clip(i - k // 2 + k, 0, len(voice))] - c[np.clip(i - k // 2, 0, len(voice))]) / k
    out = music * 0.6 * (1.0 - 0.6 * np.clip(env / 0.03, 0, 1)) + voice
    pcm = (np.clip(out, -0.98, 0.98) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.repeat(pcm[:, None], 2, 1).tobytes())


def write_srt(path, cues):
    def ts(x):
        h, r = divmod(x, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"
    n = 1
    with open(path, "w", encoding="utf-8") as f:
        for st, key in cues:
            for a, b, s in SUBS.get(key, []):
                f.write(f"{n}\n{ts(st + a)} --> {ts(st + b)}\n{s}\n\n")
                n += 1


# ------------------------------------------------------------------ main
def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", default="Team Rocklef")
    ap.add_argument("--members", default="Sree Rohith Balaji  ·  Thackshanaramana")
    ap.add_argument("--college", default="SRM Institute of Science and Technology")
    ap.add_argument("--repo", default="github.com/rocklef/xr-hackathon-track1-gaze")
    ap.add_argument("--emails", default="sb2213@srmist.edu.in,tb2138@srmist.edu.in")
    ap.add_argument("--preview", type=int, default=0, help="render every Nth frame only")
    ap.add_argument("--still", default=None, help="comma-separated times (s) or scene@offset: write PNG stills only")
    ap.add_argument("--workers", type=int, default=max(1, min(12, (os.cpu_count() or 4) - 4)))
    ap.add_argument("--out", default=os.path.join(OUTDIR, "SRMIST_Rocklef_demo.mp4"))
    return ap.parse_args(argv)


TAIL = {"apps": 1.6, "title": 1.2, "outro": 1.4}


def build(a):
    team = (a.team, a.members, a.college)
    base = [("open", seg_open, 5.0),
            ("apps", seg_apps, 6.0),
            ("problem", seg_problem, 6.0),
            ("title", lambda t, d: seg_title(t, d, team), 5.0),
            ("literature", seg_literature, 6.0),
            ("solution", seg_solution, 5.0),
            ("textures", seg_textures, 8.0),
            ("iris", seg_iris, 6.0),
            ("audit", seg_audit, 6.0),
            ("motion", seg_motion, 10.0),
            ("timeline", seg_timeline, 10.8),
            ("identity", seg_identity, 6.0),
            ("architecture", seg_architecture, 6.0),
            ("compare", seg_compare, 6.0),
            ("novelty", seg_novelty, 5.0),
            ("future", seg_future, 5.0),
            ("outro", lambda t, d: seg_outro(t, d, team, a.repo, a.emails.split(",")), 7.0)]

    def with_subs(key, fn):
        def g(t, d):
            im = fn(t, d)
            draw_subtitle(im, key, t)
            return im
        return g

    durs = [max(dmin, LEAD + vdur(k) + TAIL.get(k, 0.8)) for k, _, dmin in base]
    for (k, _, _), dd in zip(base, durs):
        SCENE_D[k] = dd
    segs = [(with_subs(k, fn), dd) for (k, fn, _), dd in zip(base, durs)]
    keys = [k for k, _, _ in base]
    starts, s = [], 0.0
    for _, dur in segs:
        starts.append(s)
        s += dur - XF
    return segs, starts, keys, s + XF


_W = {}


def _init_worker(argv):
    _W["segs"], _W["starts"], _, _ = build(parse_args(argv))


_post = {}


def post(img, fi):
    """Finishing pass: soft vignette + fine film grain."""
    if "vig" not in _post:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2)) / math.sqrt(2)
        _post["vig"] = (1 - 0.32 * np.clip((r - 0.45) / 0.55, 0, 1) ** 1.6)[..., None].astype(np.float32)
        rng = np.random.default_rng(7)
        _post["grain"] = [rng.normal(0, 1.0, (H, W, 1)).astype(np.float32) for _ in range(6)]
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    arr = arr * _post["vig"] + _post["grain"][fi % 6]
    return np.clip(arr, 0, 255).astype(np.uint8)


def frame_at(T, segs, starts):
    out = None
    for (fn, dur), st in zip(segs, starts):
        if st <= T < st + dur:
            im = fn(T - st, dur)
            if out is None:
                out = im
            else:                      # crossfade with a gentle push on the outgoing shot
                k = eio((T - st) / XF)
                z = 1 + 0.03 * k
                o = out.resize((int(W * z), int(H * z)), Image.BILINEAR)
                ox, oy = (o.size[0] - W) // 2, (o.size[1] - H) // 2
                out = Image.blend(o.crop((ox, oy, ox + W, oy + H)), im, k)
    return out if out is not None else canvas()


def paint(fi, segs=None, starts=None):
    segs = segs or _W["segs"]
    starts = starts or _W["starts"]
    return post(frame_at(fi / FPS, segs, starts), fi).tobytes()


def main():
    import multiprocessing as mp
    a = parse_args()
    segs, starts, keys, total = build(a)
    for k, s, (_, dur) in zip(keys, starts, segs):
        print(f"  {k:12s} {s:6.1f}s  +{dur:4.1f}s")
    print(f"total {total:.1f} s")
    if a.still:
        os.makedirs(os.path.join(BUILD, "stills"), exist_ok=True)
        for x in a.still.split(","):
            if "@" in x or x.isalpha():          # scene@offset, e.g. motion@8
                k, off = (x.split("@") + ["1"])[:2]
                T = starts[keys.index(k)] + float(off)
                name = f"{k}@{float(off):04.1f}"
            else:
                T = float(x)
                name = f"{T:06.1f}"
            p = os.path.join(BUILD, "stills", f"still_{name}.png")
            Image.fromarray(post(frame_at(T, segs, starts), int(T * FPS))).save(p)
            print("still", p)
        return
    ai = keys.index("audit")
    ticks = [starts[ai] + wt("audit", "pass", 0, 5) - 0.4 + 0.08 * k for k in range(8)]
    whoosh = [starts[keys.index(k)] for k in ("literature", "solution", "textures", "motion", "architecture",
                                              "novelty", "outro")]
    ti = keys.index("title")
    impacts = [starts[ti] + wt("title", "synthetic", 0, 0.9) - 0.3]
    wav = os.path.join(BUILD, "soundtrack.wav")
    mix(wav, soundtrack(total, ticks, whoosh, impacts), [(starts[i] + LEAD, k) for i, k in enumerate(keys)])
    out = a.out if not a.preview else os.path.join(BUILD, "demo_preview.mp4")
    write_srt(os.path.splitext(a.out)[0] + ".srt", [(starts[i], k) for i, k in enumerate(keys)])
    step = max(1, a.preview)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS / step), "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "slow", "-crf", "19",
           "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    idx = range(0, int(total * FPS), step)
    print(f"painting {len(idx)} frames on {a.workers} cores", flush=True)
    if a.workers > 1:
        with mp.Pool(a.workers, initializer=_init_worker, initargs=(sys.argv[1:],)) as pool:
            for n, buf in enumerate(pool.imap(paint, idx, chunksize=4)):
                p.stdin.write(buf)
                if n % 300 == 0:
                    print(f"  {idx[n] / FPS:6.1f}s / {total:.1f}s", flush=True)
    else:
        for n, fi in enumerate(idx):
            p.stdin.write(paint(fi, segs, starts))
    p.stdin.close()
    p.wait()
    print("wrote", out, f"({total:.1f} s)")


if __name__ == "__main__":
    main()

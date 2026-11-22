"""High-fidelity procedural eye textures for GNM's eye-interior UV tiles (1002 left, 1004 right), with relief.

Anatomy reproduced (in polar coordinates rho = 0 at the pupil margin .. 1 at the limbus):
  * stroma fibres at two scales, domain-warped so they wander, merge and split; brighter raised trabeculae
  * crypts of Fuchs (radially elongated dark lacunae with lighter rims) around the collarette
  * the collarette: a zig-zag raised ridge separating the pupillary zone from the ciliary zone
  * contraction furrows: broken concentric dark arcs in the outer ciliary zone
  * the pupillary ruff: a crenellated dark-brown frill on the pupil margin
  * melanin: palette-specific base, darker gaps, pigment flecks / nevi, central heterochromia for light irises
  * a soft dark limbal ring
Sclera: off-white with a faint blue-grey near the limbus, warmer towards the canthi, and branching conjunctival
vessels concentrated nasally/temporally (where the lids leave the sclera visible).
Outputs albedo (sRGB) and a tangent-space normal map from the relief height.

GNM eye UV: radial around (0.5, 0.5): pupil r < 0.050, iris r < 0.185, sclera 0.191..0.461.
"""
import math

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter, map_coordinates

PUPIL, IRIS, SCL0, SCL1 = 0.050, 0.185, 0.191, 0.461

# (pupillary-zone colour, ciliary stroma colour, fibre highlight, gap/shadow colour, limbal ring) in sRGB
PALETTES = {
    "blue": ((142, 132, 108), (104, 138, 172), (196, 214, 226), (44, 62, 84), (34, 46, 62)),
    "green": ((150, 126, 74), (108, 128, 80), (190, 196, 150), (48, 58, 38), (36, 44, 32)),
    "hazel": ((150, 98, 46), (122, 112, 70), (198, 176, 120), (52, 42, 26), (38, 32, 24)),
    "brown": ((92, 56, 30), (112, 70, 38), (168, 120, 74), (40, 24, 14), (30, 20, 14)),
    "dark_brown": ((62, 38, 22), (78, 48, 28), (128, 88, 56), (26, 16, 10), (20, 14, 10)),
    "very_dark": ((42, 26, 16), (54, 34, 21), (96, 66, 44), (18, 12, 8), (14, 10, 8)),
    "grey_blue": ((138, 134, 120), (128, 142, 156), (204, 212, 218), (58, 66, 76), (46, 52, 60)),
}


def srgb_to_lin(c):
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def sst(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def field(rng, shape, sig, wrap_axis=1):
    """Smooth gaussian random field, normalised to zero mean / unit std; wraps around the angle axis."""
    f = gaussian_filter(rng.standard_normal(shape), sig, mode=("reflect", "wrap") if wrap_axis == 1 else "reflect")
    return (f - f.mean()) / (f.std() + 1e-9)


def polar_layers(rng, R=640, A=6144, light=False):
    """All iris layers on a polar raster (rows: rho 0..1, cols: angle 0..2pi)."""
    rho = np.linspace(0, 1, R)[:, None] * np.ones((1, A))
    # domain warp: fibres wander sideways and the warp varies along the fibre
    warp = field(rng, (R, A), (40, 120)) * 14 + field(rng, (R, A), (16, 30)) * 2.2
    cols = (np.arange(A)[None, :] + warp) % A
    rows = np.arange(R)[:, None] * np.ones((1, A))

    def warped(f):
        return map_coordinates(f, [rows, cols], order=1, mode="grid-wrap")

    fine = warped(field(rng, (R, A), (60, 1.1)))         # thin fibres
    mid = warped(field(rng, (R, A), (40, 3.0)))          # bundles
    trab = warped(field(rng, (R, A), (22, 7.0)))         # broad trabeculae
    ridge = 1 - np.abs(np.tanh(trab * 1.2))              # ridged: thin bright beams along zero-crossings
    # collarette: zig-zag boundary around rho ~ 0.33
    zig = np.clip(0.33 + 0.03 * field(rng, (1, A), (0, 60))[0] + 0.012 * np.sin(np.linspace(0, 2 * np.pi * 14, A)), 0.2, 0.45)
    zig = zig[None, :]
    coll_ridge = np.exp(-((rho - zig) / 0.022) ** 2)
    pupillary = (1 - sst(zig - 0.09, zig + 0.14, rho)) * 0.6
    # crypts: radially elongated lacunae near the collarette
    cr = warped(field(rng, (R, A), (14, 9)))
    crypt = sst(1.35, 1.9, cr) * sst(0.2, 0.3, rho) * (1 - sst(0.62, 0.75, rho))
    crypt_rim = sst(0.95, 1.3, cr) * (1 - sst(1.35, 1.6, cr)) * sst(0.2, 0.3, rho) * (1 - sst(0.62, 0.75, rho))
    # contraction furrows: broken concentric arcs in the outer zone
    fur_phase = rho * 2 * np.pi * 5.5 + field(rng, (R, A), (30, 120)) * 0.9
    furrow = sst(0.82, 0.97, np.cos(fur_phase)) * sst(0.55, 0.7, rho) * (1 - sst(0.9, 0.97, rho))
    furrow *= sst(0.0, 0.8, field(rng, (R, A), (40, 200)))
    # pupillary ruff: crenellated dark frill at the pupil margin
    ruff_w = np.clip(0.035 + 0.012 * field(rng, (1, A), (0, 8))[0][None, :], 0.015, 0.06)
    ruff = 1 - sst(ruff_w * 0.6, ruff_w, rho)
    # pigment flecks / nevi (mostly light irises) and central heterochromia
    fleck_f = field(rng, (R, A), (5, 14))
    flecks = sst(2.6, 3.1, fleck_f) * sst(0.15, 0.3, rho) * (1 - sst(0.85, 0.95, rho))
    limbal = sst(0.86, 0.985, rho)
    return dict(rho=rho, fine=fine, mid=mid, ridge=ridge, coll=coll_ridge, pup=pupillary, crypt=crypt,
                crypt_rim=crypt_rim, furrow=furrow, ruff=ruff, flecks=flecks, limbal=limbal)


def iris_polar(palette, seed):
    rng = np.random.default_rng(seed)
    pz, cz, hi, gap, lim = (srgb_to_lin(c) for c in PALETTES[palette])
    light = palette in ("blue", "green", "grey_blue", "hazel")
    L = polar_layers(rng, light=light)
    pupw = L["pup"][..., None]
    base = pz * pupw + cz * (1 - pupw)
    # fibre structure: highlight on fibres/trabeculae, darker gaps
    fib = 0.55 * np.tanh(L["fine"] * 0.9) + 0.35 * np.tanh(L["mid"] * 0.8)
    t_hi = np.clip(0.62 * L["ridge"] ** 3 + 0.34 * np.clip(fib, 0, 1), 0, 1)[..., None]
    t_gap = np.clip(-fib * 1.45, 0, 1)[..., None] * 0.92
    col = base * (1 - t_hi) + hi * t_hi * (0.55 if not light else 0.75) + base * t_hi * (0.45 if not light else 0.25)
    col = col * (1 - t_gap) + gap * t_gap
    # broad luminance variation (depth / stroma thickness)
    lum = np.tanh(field(np.random.default_rng(seed + 7), col.shape[:2], (50, 260)) * 0.6)
    col = col * (1 + 0.22 * lum[..., None])
    # collarette ridge (lighter), crypts (dark with light rim), furrows (dark)
    col = col * (1 + 0.42 * L["coll"][..., None])
    if light:                                   # central heterochromia: a warm golden ring around the pupil
        gold = srgb_to_lin((176, 128, 52))
        gz = (L["pup"] * 1.3 + 0.5 * L["coll"]).clip(0, 1)[..., None] * 0.36
        col = col * (1 - gz) + gold * gz * (0.6 + 0.4 * np.clip(fib, 0, 1))[..., None]
    col = col * (1 - 0.15 * L["crypt_rim"][..., None]) + hi * 0.15 * L["crypt_rim"][..., None]
    col = col * (1 - 0.75 * L["crypt"][..., None]) + gap * 0.75 * L["crypt"][..., None] * 0.6
    col = col * (1 - 0.22 * L["furrow"][..., None])
    # pigment flecks (brown/orange) — more visible on light irises
    fleck_col = srgb_to_lin((120, 70, 30))
    fk = L["flecks"][..., None] * (0.85 if light else 0.4)
    col = col * (1 - fk) + fleck_col * fk
    # pupillary ruff and limbal ring
    ruff_col = srgb_to_lin((34, 20, 12))
    col = col * (1 - L["ruff"][..., None]) + ruff_col * L["ruff"][..., None]
    lr = L["limbal"][..., None]
    col = col * (1 - 0.9 * lr) + lim * 0.9 * lr
    # relief height (mm-ish, arbitrary units): fibres/trabeculae raised, crypts & furrows recessed, collarette ridge
    h = 0.5 * np.tanh(L["fine"]) * 0.25 + 0.6 * L["ridge"] ** 2 + 0.9 * L["coll"] - 1.4 * L["crypt"] - 0.8 * L["furrow"]
    h = h - 0.6 * L["ruff"]
    return col, h


def to_cartesian(polar, size, r0, r1, cx=0.5, cy=0.5, box=None):
    """Sample a polar raster (rows rho 0..1 between radii r0..r1 in UV, cols angle) onto a UV crop."""
    R, A = polar.shape[:2]
    x0, y0, x1, y1 = box
    yy, xx = np.mgrid[y0:y1, x0:x1]
    u, v = (xx + 0.5) / size, 1 - (yy + 0.5) / size
    dx, dy = u - cx, v - cy
    r = np.hypot(dx, dy)
    th = (np.arctan2(dy, dx) / (2 * np.pi)) % 1.0
    rr = np.clip((r - r0) / (r1 - r0), 0, 1) * (R - 1)
    aa = th * A
    if polar.ndim == 2:
        return map_coordinates(polar, [rr, aa], order=1, mode="grid-wrap"), r, th
    out = np.stack([map_coordinates(polar[..., c], [rr, aa], order=1, mode="grid-wrap") for c in range(polar.shape[2])], -1)
    return out, r, th


def sclera(size, rng):
    yy, xx = np.mgrid[0:size, 0:size]
    u, v = (xx + 0.5) / size, 1 - (yy + 0.5) / size
    dx, dy = u - 0.5, v - 0.5
    r = np.hypot(dx, dy)
    th = np.arctan2(dy, dx)
    s = np.clip((r - SCL0) / (SCL1 - SCL0), 0, 1)
    base = srgb_to_lin((238, 234, 228))
    near = srgb_to_lin((214, 220, 228))                 # thin sclera near the limbus: faint blue-grey
    far = srgb_to_lin((236, 214, 200))                  # warmer / pinker towards the canthi and fornices
    blot = gaussian_filter(rng.standard_normal((size // 8, size // 8)), 6)
    blot = np.array(Image.fromarray(((blot - blot.min()) / np.ptp(blot) * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC)) / 255.0
    col = base * (1 - sst(0.0, 0.25, 1 - s)[..., None] * 0.0)
    col = col * (1 - (1 - sst(0.0, 0.18, s))[..., None] * 0.6) + near * (1 - sst(0.0, 0.18, s))[..., None] * 0.6
    horiz = np.abs(np.cos(th))
    warm = (sst(0.25, 1.0, s) * (0.5 + 0.5 * horiz))[..., None]
    col = col * (1 - warm * 0.32) + far * warm * 0.32
    col = col * (0.955 + 0.08 * blot[..., None])
    # pinguecula: soft yellowish patches beside the limbus on the nasal and temporal sides (sun-exposed conjunctiva)
    yel = srgb_to_lin((226, 206, 160))
    ang = np.minimum(np.abs(th), np.abs(np.pi - np.abs(th)))           # 0 on the horizontal (nasal/temporal)
    pg = sst(0.55, 0.0, ang) * sst(0.02, 0.12, s) * sst(0.75, 0.3, s)
    pg = pg * sst(0.35, 0.8, blot)
    col = col * (1 - pg[..., None] * 0.28) + yel * pg[..., None] * 0.28
    # overall off-white: real sclera is never paper white (slight grey-yellow)
    col = col * srgb_to_lin((250, 248, 242)) / srgb_to_lin((255, 255, 255))
    return col


def draw_vessels(img_lin, size, rng, n=34, ss=2):
    """Two layers: soft deep episcleral vessels, then sharp branching conjunctival vessels on top."""
    img_lin = _vessel_layer(img_lin, size, rng, 12, ss, (168, 70, 78), 3.0, 6.5, 3.5, 0.28, 0, 0.02, 0.12)
    img_lin = _vessel_layer(img_lin, size, rng, 26, ss, (190, 34, 36), 1.6, 3.6, 0.45, 0.88, 2, 0.022, 0.11)
    return img_lin


def _vessel_layer(img_lin, size, rng, n, ss, colour, w0, w1, blur, alpha, max_depth, branch_p, wiggle=0.28):
    """Branching vessels: random walks from the outer sclera inward, mostly nasal/temporal."""
    W = size * ss
    over = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    dr = ImageDraw.Draw(over)

    def walk(x, y, ang, width, length, depth):
        steps = int(length / 4) + 2
        for _ in range(steps):
            ang += rng.normal(0, wiggle)
            nx, ny = x + math.cos(ang) * 4 * ss, y + math.sin(ang) * 4 * ss
            uvr = math.hypot(nx / W - 0.5, ny / W - 0.5)
            if uvr < SCL0 + 0.010:
                break
            a = int(255 * (0.55 + 0.45 * min(1.0, width / 2.0)))
            dr.line([(x, y), (nx, ny)], fill=(255, 255, 255, a), width=max(2, int(round(width * ss))))
            x, y = nx, ny
            width *= 0.982
            if depth < max_depth and rng.random() < branch_p:
                walk(x, y, ang + rng.choice([-1, 1]) * rng.uniform(0.5, 1.1), width * 0.72, length * 0.5, depth + 1)

    for _ in range(n):
        side = rng.choice([0.0, math.pi])                 # temporal / nasal
        a0 = side + rng.normal(0, 0.5)
        r0 = rng.uniform(0.25, 0.40)
        x, y = (0.5 + r0 * math.cos(a0)) * W, (0.5 - r0 * math.sin(a0)) * W
        inward = math.atan2(0.5 * W - y, 0.5 * W - x) + rng.normal(0, 0.4)
        walk(x, y, inward, rng.uniform(w0, w1), rng.uniform(140, 380) * ss, 0)
    over = over.resize((size, size), Image.LANCZOS)
    a = np.asarray(over, dtype=np.float64) / 255.0
    vcol = srgb_to_lin(colour)
    al = gaussian_filter(a[..., 3], blur)[..., None] * alpha
    return img_lin * (1 - al) + vcol * al


def eye_texture(palette, seed, size=4096):
    rng = np.random.default_rng(seed)
    out = sclera(size, rng)
    out = draw_vessels(out, size, rng)
    # iris crop
    c0, c1 = int((0.5 - 0.2) * size), int((0.5 + 0.2) * size)
    box = (c0, c0, c1, c1)
    col_p, h_p = iris_polar(palette, seed)
    col, r, th = to_cartesian(col_p, size, PUPIL, IRIS, box=box)
    h, _, _ = to_cartesian(h_p, size, PUPIL, IRIS, box=box)
    pup = sst(PUPIL + 0.0015, PUPIL - 0.0025, r)[..., None]
    col = col * (1 - pup) + np.array([0.0035, 0.0032, 0.0035]) * pup
    lb = sst(IRIS - 0.003, SCL0 + 0.007, r)[..., None]          # soft limbus into the sclera
    crop = out[c0:c1, c0:c1]
    out[c0:c1, c0:c1] = col * (1 - lb) + crop * lb
    # normal map from relief (only the iris has relief)
    height = np.zeros((size, size))
    height[c0:c1, c0:c1] = h * (1 - lb[..., 0]) * (1 - pup[..., 0])
    # conjunctiva is not mirror-smooth: faint low ripples over the sclera, plus the raised vessels themselves
    r_all = np.hypot((np.arange(size)[None, :] + 0.5) / size - 0.5, (np.arange(size)[:, None] + 0.5) / size - 0.5)
    scl_m = sst(SCL0, SCL0 + 0.02, r_all)
    ripple = gaussian_filter(np.random.default_rng(seed + 5).standard_normal((size // 4, size // 4)), 2.5)
    ripple = np.kron(ripple / (ripple.std() + 1e-9), np.ones((4, 4)))[:size, :size]
    redness = np.clip(1.0 - out[..., 1] / np.maximum(out[..., 0], 1e-4), 0, 1)       # vessels are red
    height = height + scl_m * (0.012 * gaussian_filter(ripple, 10) + 0.10 * gaussian_filter(redness, 1.0))
    height = gaussian_filter(height, 0.8)
    gy, gx = np.gradient(height)
    k = 9.0
    nx, ny = -gx * k, gy * k                       # image y is down; UV v is up
    nz = np.ones_like(nx)
    nrm = np.stack([nx, ny, nz], -1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    albedo = (lin_to_srgb(out) * 255 + 0.5).astype(np.uint8)
    normal = ((nrm * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8)
    return albedo, normal


def save_pair(palette, seed, albedo_l, albedo_r, normal_l, normal_r, size=4096):
    for s, (pa, pn) in ((seed, (albedo_l, normal_l)), (seed + 1000, (albedo_r, normal_r))):
        a, n = eye_texture(palette, s, size)
        Image.fromarray(a).save(pa)
        Image.fromarray(n).save(pn)


if __name__ == "__main__":
    import os
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    tiles = []
    for i, p in enumerate(("blue", "green", "hazel", "brown", "very_dark", "grey_blue")):
        a, n = eye_texture(p, 200 + i, 2048)
        Image.fromarray(a).save(os.path.join(out, f"hq_{p}.png"))
        tiles.append(Image.fromarray(a).crop((614, 614, 1434, 1434)).resize((420, 420), Image.LANCZOS))
        if i == 0:
            Image.fromarray(n).crop((614, 614, 1434, 1434)).save(os.path.join(out, "hq_normal_blue.png"))
    sheet = Image.new("RGB", (420 * 3, 420 * 2))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 3) * 420, (i // 3) * 420))
    sheet.save(os.path.join(out, "hq_sheet.png"))
    print("ok")

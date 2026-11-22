"""Head hair for the GNM heads: real hair curves (Blender Curves object) rendered with the Principled Hair BSDF.

A procedural groom per texture set (style + the set's own hair colour):
  short  natural short cut: hair flows away from the crown whorl, longer on top, short at the sides and back,
         the front swept a little to one side
  bun    long hair pulled back over the scalp into a low bun at the back of the head (face fully visible)
  coily  short natural coily hair (tight helices growing out from the scalp)

How the groom is grown:
  1. Roots are sampled on the scalp region (the same rule as the painted follicles, skin_masks.m_scalp), with a
     soft hairline: density and length fade towards the edge.
  2. ~1500 guide strands grow in steps along the style's flow field, projected onto the head surface and kept
     above it at a "stacking" height that grows with length (hair lies in layers on the head).
  3. Tens of thousands of child strands copy their nearest guide with an offset that clumps towards the tip,
     plus frizz, and are pushed back out of the scalp where needed.
The hair is parented to the rig's head bone, so it follows head motion; the scalp does not deform with the eye
expressions. Deterministic (fixed seeds).

Called by materials.apply(tex_id); can also be run alone:
blender -b --factory-startup gnm_rig/out/heads/T02.blend -P gnm_rig/hair.py -- --tex T02
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
NAME = "GNM_Hair"
BUN = "GNM_HairBun"

STYLES = {
    "T01": dict(kind="bun", guides=1400, children=42000, r0=0.000036, frizz=0.0004, wave=0.0),
    "T02": dict(kind="short", guides=1600, children=60000, r0=0.000040, top=0.048, side=0.018, frizz=0.0006, wave=0.0006),
    "T03": dict(kind="short", guides=1600, children=68000, r0=0.000044, top=0.050, side=0.018, frizz=0.0006, wave=0.0012),
    "T04": dict(kind="bun", guides=1400, children=46000, r0=0.000050, frizz=0.0002, wave=0.0),
    "T05": dict(kind="short", guides=1600, children=62000, r0=0.000046, top=0.048, side=0.016, frizz=0.0005, wave=0.0012),
    "T06": dict(kind="coily", guides=0, children=52000, r0=0.000048, length=0.028, coil=0.0016, pitch=0.0042),
    "T07": dict(kind="short", guides=1400, children=36000, r0=0.000034, top=0.034, side=0.014, frizz=0.0007, wave=0.0,
                salt_pepper=0.35),
    "T08": dict(kind="bun", guides=1400, children=44000, r0=0.000042, frizz=0.0005, wave=0.002),
}


def sst(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


class Surface:
    """Evaluated head skin at rest: BVH for projection, per-vertex scalp weight, handy reference points."""

    def __init__(self, head, kind="short"):
        import fuzz as FZ
        dg = bpy.context.evaluated_depsgraph_get()
        ev = head.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        names = ("R_skin", "R_forehead_region", "R_left_temple_region", "R_right_temple_region", "R_ears",
                 "R_hockey_mask")
        g = FZ._group_weights(head, me, names)
        self.co = np.array([v.co for v in me.vertices])
        self.nr = np.array([v.normal for v in me.vertices])
        self.tris = np.array([lt.vertices[:] for lt in me.loop_triangles if lt.material_index == 0])
        ev.to_mesh_clear()
        x, yb, z = self.co[:, 0], self.co[:, 1], self.co[:, 2]
        fh = g["R_forehead_region"] > 0.5
        fh_top = z[fh].max() if fh.any() else z.max() - 0.05
        scalp = sst(fh_top - 0.012, fh_top + 0.006, z) + sst(0.0, 0.04, yb) * sst(0.24, 0.30, z)
        scalp = scalp + (g["R_left_temple_region"] + g["R_right_temple_region"]) * sst(0.30, 0.33, z)
        face = g["R_hockey_mask"] * sst(0.34, 0.33, z)
        # the hair region reaches down the sides of the head to the top of the ears, plus short sideburns in front
        # of them (the painted follicle region alone stops too high, like an undercut)
        ear = g["R_ears"] > 0.5
        if ear.any():
            ez, ey = z[ear], yb[ear]
            ear_top, ear_mid, ear_front = ez.max(), 0.5 * (ez.max() + ez.min()), ey.min()
            sides = sst(ear_top - 0.012, ear_top + 0.004, z) * sst(ear_front - 0.014, ear_front - 0.002, yb)
            burns = sst(ear_mid - 0.004, ear_mid + 0.008, z) * sst(ear_front - 0.016, ear_front - 0.008, yb)                 * (1 - sst(ear_front - 0.002, ear_front + 0.004, yb)) * (np.abs(x) > 0.05)
            back = sst(ear_mid - 0.03, ear_mid - 0.01, z) * sst(ear_front + 0.02, ear_front + 0.05, yb)
            if kind == "bun":
                # pulled-back hair passes above and behind the ears: no sideburns, sides stop at the ear top
                sides = sst(ear_top - 0.002, ear_top + 0.008, z) * sst(ear_front - 0.014, ear_front - 0.002, yb)
                burns = 0.0 * burns
            scalp = np.maximum(scalp, np.maximum(sides, np.maximum(burns, back)))
            face = face * (1 - sst(ear_front - 0.02, ear_front - 0.005, yb))
        self.w = np.clip(scalp, 0, 1) * (1 - g["R_ears"]) * (1 - face) * (g["R_skin"] > 0.5)
        self.bvh = BVHTree.FromPolygons([Vector(c) for c in self.co], [tuple(t) for t in self.tris])
        sc = self.co[self.w > 0.5]
        self.centre = Vector(((x.max() + x.min()) / 2, yb[self.w > 0.3].mean(), z[self.w > 0.3].mean() - 0.04))
        top = sc[np.argsort(sc[:, 2])[-max(20, len(sc) // 50):]].mean(0)
        self.crown = self.project(Vector(top) + Vector((0.0, 0.035, 0.0)))[0]
        self.top_z, self.front_y = sc[:, 2].max(), sc[:, 1].min()

    def project(self, p):
        loc, n, i, d = self.bvh.find_nearest(p)
        return loc, n

    def sample(self, n, rng, power=1.5):
        a, b, c = (self.co[self.tris[:, k]] for k in range(3))
        area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
        wt = area * (self.w[self.tris].mean(1) ** power)
        pick = rng.choice(len(self.tris), size=n, p=wt / wt.sum())
        r1, r2 = rng.random(n), rng.random(n)
        s = np.sqrt(r1)
        bary = np.stack([1 - s, s * (1 - r2), s * r2], 1)
        T = self.tris[pick]
        pos = (self.co[T] * bary[..., None]).sum(1)
        nrm = (self.nr[T] * bary[..., None]).sum(1)
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
        wroot = (self.w[T] * bary).sum(1)
        return pos, nrm, wroot


def flow_short(S, p, side=1.0):
    """Natural short men's cut: down and back from the crown on the sides and back of the head; on top and at the
    front the hair is combed back and swept to one side, so the forehead and hairline stay visible."""
    radial = p - S.crown
    radial.z -= 0.01
    radial.normalize()
    # 0 at the crown/back .. 1 at the front of the top
    front = float(sst(0.01, -0.06, p.y)) * float(sst(S.top_z - 0.085, S.top_z - 0.03, p.z))
    part_x = -0.022 * side                       # side parting: hair combs away from it on each side
    sgn = 1.0 if p.x >= part_x else -1.0
    big = 1.0 if sgn == side else 0.55           # the wider side sweeps across, the narrow side goes down
    swept = Vector((sgn * 0.85 * big, 0.45, 0.25 * big))
    return radial * (1.0 - front) + swept.normalized() * front * 1.4


def grow(S, root, n, length, flow_fn, rng, lift=0.55, stack=0.006, segs=14, wave=0.0, stop=None):
    """One strand: walk along the surface following the flow, keeping a growing stacking height."""
    pts = [root - n * 0.00025]
    p, nn = root.copy(), n.copy()
    ds = length / segs
    phase = rng.uniform(0, 2 * math.pi)
    for i in range(1, segs + 1):
        t = i / segs
        f = flow_fn(p)
        d = f - nn * f.dot(nn)
        if d.length < 1e-6:
            d = f
        d.normalize()
        la = lift * (1.0 - t) ** 2
        q = p + (d * math.cos(la) + nn * math.sin(la)) * ds
        if wave:
            side = d.cross(nn).normalized()
            q += side * (wave * math.sin(phase + t * 9.0) * t)
        loc, ns = S.project(q)
        hmin = 0.0006 + stack * t
        if (q - loc).dot(ns) < hmin:
            q = loc + ns * hmin
        pts.append(q)
        p, nn = q, ns
        if stop and stop(q):
            break
    return pts


def resample(pts, k):
    """Polyline -> k points evenly spaced along its length."""
    P = np.array([tuple(v) for v in pts])
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    if cum[-1] <= 0:
        return np.repeat(P[:1], k, 0)
    u = np.linspace(0, cum[-1], k)
    return np.stack([np.interp(u, cum, P[:, j]) for j in range(3)], 1)


def build(P, head=None, rig=None):
    st = STYLES.get(P["id"])
    for nm in (NAME, BUN):
        old = bpy.data.objects.get(nm)
        if old:
            data = old.data
            bpy.data.objects.remove(old, do_unlink=True)
            bpy.data.hair_curves.remove(data)
    if st is None:
        return None
    head = head or bpy.data.objects["GNM_Head"]
    rig = rig or bpy.data.objects.get("GNM_Rig")
    rng = np.random.default_rng(100 + int(P["id"][1:]))
    S = Surface(head, st["kind"])
    K = 14
    strands, radii = [], []
    if st["kind"] == "coily":
        pos, nrm, wr = S.sample(st["children"], rng, power=1.2)
        for i in range(len(pos)):
            root, n = Vector(pos[i]), Vector(nrm[i])
            out = (root - S.crown)
            out = (out - n * out.dot(n)).normalized() if out.length > 1e-6 else Vector((0, 0, 1))
            L = st["length"] * rng.uniform(0.7, 1.15) * (0.45 + 0.55 * wr[i])
            axis = (n * 0.75 + out * 0.45).normalized()
            u = axis.cross(Vector((0.0, 0.0, 1.0)))
            if u.length < 1e-6:
                u = Vector((1.0, 0.0, 0.0))
            u.normalize()
            v = axis.cross(u)
            ph = rng.uniform(0, 2 * math.pi)
            cr = st["coil"] * rng.uniform(0.7, 1.3)
            pts = []
            for j in range(K):
                t = j / (K - 1)
                ang = ph + 2 * math.pi * (L * t) / st["pitch"]
                c = root - n * 0.0002 + axis * (L * t) + (u * math.cos(ang) + v * math.sin(ang)) * cr * min(1.0, t * 4)
                loc, ns = S.project(c)
                if (c - loc).dot(ns) < 0.0004:
                    c = loc + ns * 0.0004
                pts.append(tuple(c))
            strands.append(pts)
            radii.append(st["r0"])
    else:
        if st["kind"] == "bun":
            bdir = Vector((0.0, 1.0, -0.18)).normalized()
            bs, bn = S.project(S.centre + bdir * 0.2)
            bun_c = bs + bn * 0.022
            bun_r = 0.026

            def flow(p):
                return (bun_c - p)

            def stop(q):
                return (q - bun_c).length < bun_r * 1.05
            length_fn = lambda p, w: 0.30
        else:
            side = 1.0

            def flow(p):
                return flow_short(S, p, side)
            stop = None
            top_z = S.top_z

            def length_fn(p, w):
                hfac = float(sst(top_z - 0.10, top_z - 0.015, p.z))          # long on top, short at the sides
                nape = float(sst(top_z - 0.17, top_z - 0.11, p.z))          # tapered to very short at the nape
                L = st["side"] + (st["top"] - st["side"]) * hfac
                return L * (0.35 + 0.65 * nape) * (0.55 + 0.45 * w)
        gpos, gnrm, gw = S.sample(st["guides"], rng)
        guides, groots = [], []
        for i in range(len(gpos)):
            root, n = Vector(gpos[i]), Vector(gnrm[i])
            L = length_fn(root, gw[i]) * rng.uniform(0.85, 1.15)
            segs = 40 if st["kind"] == "bun" else 14
            pts = grow(S, root, n, L, flow, rng, lift=0.5 if st["kind"] == "short" else 0.25,
                       stack=0.0055 if st["kind"] == "short" else 0.0035, segs=segs, wave=st.get("wave", 0.0),
                       stop=stop)
            guides.append(resample(pts, K))
            groots.append(root)
        kd = kdtree.KDTree(len(groots))
        for i, r in enumerate(groots):
            kd.insert(r, i)
        kd.balance()
        cpos, cnrm, cw = S.sample(st["children"], rng)
        frizz = st["frizz"]
        uu = np.linspace(0, 1, K)
        for i in range(len(cpos)):
            root = Vector(cpos[i])
            _, gi, _ = kd.find(root)
            # natural length variation between neighbours: each child uses 72-100% of its guide's length
            f = rng.uniform(0.72, 1.0)
            g = np.stack([np.interp(uu * f, uu, guides[gi][:, k]) for k in range(3)], 1)
            off = np.array(tuple(root - groots[gi]))
            clump = rng.uniform(0.25, 0.55) if st["kind"] == "short" else rng.uniform(0.55, 0.85)
            noise = rng.normal(0, 1, (K, 3)) * frizz
            pts = []
            for j in range(K):
                t = j / (K - 1)
                c = Vector(g[j] + off * (1 - clump * t ** 1.3) + noise[j] * t ** 1.5)
                loc, ns = S.project(c)
                if (c - loc).dot(ns) < 0.0005:
                    c = loc + ns * 0.0005
                pts.append(tuple(c))
            strands.append(pts)
            radii.append(st["r0"] * rng.uniform(0.8, 1.2))
    hc = curves_object(NAME, strands, radii, K, head, rig, P)
    if st["kind"] == "bun":
        bun_object(bun_c, bn, bun_r, rng, st, head, rig, P)
    print("hair", P["id"], st["kind"], len(strands), "strands", flush=True)
    return hc


def bun_object(c, n, r, rng, st, head, rig, P, count=9000, K=24):
    """A coiled bun: strands wrap around the bun centre on randomly tilted circles, flattened against the head."""
    u = n.cross(Vector((0.0, 0.0, 1.0)))
    if u.length < 1e-6:
        u = Vector((1.0, 0.0, 0.0))
    u.normalize()
    v = n.cross(u)
    strands, radii = [], []
    for i in range(count):
        rad = r * rng.uniform(0.45, 1.0)
        a1, a2 = rng.normal(0, 1, 3), rng.normal(0, 1, 3)
        e1 = Vector(a1).normalized()
        e2 = Vector(a2)
        e2 = (e2 - e1 * e2.dot(e1)).normalized()
        ph0 = rng.uniform(0, 2 * math.pi)
        span = rng.uniform(1.2, 2.6) * math.pi
        pts = []
        for j in range(K):
            t = j / (K - 1)
            ang = ph0 + span * t
            d = e1 * math.cos(ang) + e2 * math.sin(ang)
            # flatten along the head normal (a bun is wider than it is tall) and keep it off the head
            d = u * d.dot(u) + v * d.dot(v) + n * (0.6 * d.dot(n))
            p = c + d * rad + Vector(rng.normal(0, 1, 3)) * st["frizz"] * 0.5
            pts.append(tuple(p))
        strands.append(pts)
        radii.append(st["r0"])
    return curves_object(BUN, strands, radii, K, head, rig, P)


def curves_object(name, strands, radii, K, head, rig, P):
    hc = bpy.data.hair_curves.new(name)
    hc.add_curves([K] * len(strands))
    flat = np.array(strands, dtype=np.float32).reshape(-1)
    hc.position_data.foreach_set("vector", flat)
    ra = hc.attributes.new("radius", "FLOAT", "POINT")
    t = np.tile(np.linspace(0, 1, K), len(strands))
    r = np.repeat(np.array(radii, np.float32), K) * (1.0 - 0.6 * t ** 1.5)
    ra.data.foreach_set("value", r.astype(np.float32))
    ob = bpy.data.objects.new(name, hc)
    for col in head.users_collection:
        col.objects.link(ob)
    hc.materials.append(material(P))
    if rig and "head" in rig.data.bones:
        ob.parent = rig
        ob.parent_type = "BONE"
        ob.parent_bone = "head"
        bpy.context.view_layer.update()
        ob.matrix_world = head.matrix_world.copy()
    return ob


def material(P):
    m = bpy.data.materials.get("MAT_hair") or bpy.data.materials.new("MAT_hair")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    h = nt.nodes.new("ShaderNodeBsdfHairPrincipled")
    h.model = "CHIANG"
    # melanin model: physically based pigment, far closer to real hair than direct colouring
    h.parametrization = "MELANIN"
    srgb = [float(c) / 255.0 for c in P["hair"]]
    L = 0.2126 * lin(float(P["hair"][0])) + 0.7152 * lin(float(P["hair"][1])) + 0.0722 * lin(float(P["hair"][2]))
    melanin = min(1.0, max(0.0, 1.22 - 1.4 * L ** 0.35))
    redness = min(1.0, max(0.0, (srgb[0] - srgb[2]) / max(srgb[0], 1e-3))) * 0.45
    vals = {"Melanin": melanin, "Melanin Redness": redness, "Roughness": 0.28, "Radial Roughness": 0.32,
            "Coat": 0.0, "Random Color": 0.10, "Random Roughness": 0.12}
    for k, v in vals.items():
        if k in h.inputs:
            h.inputs[k].default_value = v
    sp = STYLES.get(P["id"], {}).get("salt_pepper")
    if sp:
        # greying hair is salt-and-pepper: per strand, either an unpigmented white hair or a pigmented grey-brown one
        info = nt.nodes.new("ShaderNodeHairInfo")
        ramp = nt.nodes.new("ShaderNodeMapRange")
        ramp.interpolation_type = "STEPPED"
        ramp.inputs["Steps"].default_value = 1.0
        ramp.inputs[1].default_value, ramp.inputs[2].default_value = 1.0 - sp, 1.0 - sp + 1e-3
        ramp.inputs[3].default_value, ramp.inputs[4].default_value = 0.02, 0.55
        nt.links.new(info.outputs["Random"], ramp.inputs[0])
        nt.links.new(ramp.outputs[0], h.inputs["Melanin"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(h.outputs[0], out.inputs[0])
    return m


if __name__ == "__main__":
    from presets import BY_ID
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    tex = argv[argv.index("--tex") + 1] if "--tex" in argv else "T02"
    build(BY_ID[tex])

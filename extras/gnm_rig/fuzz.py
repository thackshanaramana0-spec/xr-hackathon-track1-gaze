"""Vellus hair ("peach fuzz"): ~1 mm, very fine, pale hairs over the face. They are nearly invisible head-on and
glow along the silhouette under a rim light, one of the strongest realism cues in close-ups.

Placed on GNM's face regions (vertex groups from the GNM model), away from the lips, eye sockets, lid margins and
brows. Hairs follow a natural flow (down and outward from the face midline) and leave the skin at a shallow angle.
Bound with Surface Deform to the skin-only proxy, like the lashes and brows. Deterministic (fixed seed).

Called by materials.apply(); can also be run alone:
blender -b --factory-startup <head>.blend -P gnm_rig/fuzz.py
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
NAME = "GNM_Fuzz"
REGIONS = ("R_forehead_region", "R_left_cheek_region", "R_right_cheek_region", "R_nose_region",
           "R_left_zygomatic_region", "R_right_zygomatic_region", "R_left_temple_region", "R_right_temple_region",
           "R_chin_region", "R_upper_lip_region", "R_left_infraorbital_region", "R_right_infraorbital_region",
           "R_middle_brow_region", "R_ears")
AVOID = ("R_eye_sockets", "R_mouth_sock", "R_upper_lip", "R_lower_lip", "R_left_brow_region", "R_right_brow_region")


def _surface_samples(head, weight_fn, count, seed):
    """Area- and weight-proportional random points on the evaluated skin: (pos, normal, all_coords)."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = head.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    w_v = weight_fn(head, me)
    co = np.array([v.co for v in me.vertices])
    nr = np.array([v.normal for v in me.vertices])
    tris = np.array([lt.vertices[:] for lt in me.loop_triangles if lt.material_index == 0])
    ev.to_mesh_clear()
    a, b, c = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    wt = area * w_v[tris].mean(1)
    if wt.sum() <= 0:
        return None
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(tris), size=count, p=wt / wt.sum())
    r1, r2 = rng.random(count), rng.random(count)
    s = np.sqrt(r1)
    bary = np.stack([1 - s, s * (1 - r2), s * r2], 1)
    T = tris[pick]
    pos = (co[T] * bary[..., None]).sum(1)
    nrm = (nr[T] * bary[..., None]).sum(1)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    return pos, nrm, co, rng


def _group_weights(head, me, names):
    idx = {head.vertex_groups[n].index: n for n in names if n in head.vertex_groups}
    out = {n: np.zeros(len(me.vertices)) for n in names}
    for v in me.vertices:
        for g in v.groups:
            n = idx.get(g.group)
            if n:
                out[n][v.index] = g.weight
    return out


def _strand_object(name, head, rig, pos, nrm, rng, flow_fn, length, radius, angle_deg, mat, sides=3, segs=4,
                   bend=0.25, shadows=False):
    verts, faces, tv = [], [], []
    for i in range(len(pos)):
        p, n = Vector(pos[i]), Vector(nrm[i])
        flow = flow_fn(p, n, rng)
        flow = (flow - n * flow.dot(n)).normalized()
        ang = math.radians(angle_deg * rng.uniform(0.75, 1.25))
        d0 = (flow * math.cos(ang) + n * math.sin(ang)).normalized()
        L = length * rng.uniform(0.6, 1.4)
        r0 = radius * rng.uniform(0.8, 1.2)
        prev = None
        q, dv = p - n * 0.00003, d0.copy()
        side = dv.cross(n).normalized()
        for j in range(segs + 1):
            t = j / segs
            up = side.cross(dv).normalized()
            ring = []
            for m_ in range(sides):
                a_ = 2 * math.pi * m_ / sides
                ring.append(len(verts))
                verts.append(tuple(q + (side * math.cos(a_) + up * math.sin(a_)) * r0 * (1 - 0.8 * t)))
                tv.append(t)
            if prev:
                for m_ in range(sides):
                    m2 = (m_ + 1) % sides
                    faces.append((prev[m_], prev[m2], ring[m2], ring[m_]))
            prev = ring
            q = q + dv * (L / segs)
            dv = (dv + flow * bend).normalized()
    old = bpy.data.objects.get(name)
    if old:
        mo = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        bpy.data.meshes.remove(mo)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.polygons.foreach_set("use_smooth", np.ones(len(mesh.polygons), dtype=bool))
    at = mesh.attributes.new("hair_t", "FLOAT", "POINT")
    at.data.foreach_set("value", np.asarray(tv, np.float32))
    ob = bpy.data.objects.new(name, mesh)
    for col in head.users_collection:
        col.objects.link(ob)
    ob.matrix_world = head.matrix_world.copy()
    if rig:
        ob.parent = rig
        ob.matrix_parent_inverse = rig.matrix_world.inverted()
    mesh.materials.append(mat)
    ob.visible_shadow = shadows
    import fix_lash_binding as FX
    sd = ob.modifiers.new("SurfaceDeform", "SURFACE_DEFORM")
    sd.target = FX.skin_proxy(head)
    bpy.context.view_layer.update()
    with bpy.context.temp_override(object=ob, active_object=ob):
        bpy.ops.object.surfacedeform_bind(modifier=sd.name)
    # hide in the viewport only AFTER binding (a viewport-hidden object is not evaluated, so the bind would fail);
    # renders still include it, and Timeline playback in the viewport stays fast
    ob.hide_viewport = True
    print(name, len(pos), "hairs,", len(verts), "verts, bound", sd.is_bound, flush=True)
    return ob


def build_stubble(P, head=None, rig=None, seed=23):
    """Short 3D beard stubble (about a day's growth) for the bearded sets, on top of the painted follicle dots."""
    if P.get("beard", 0) < 0.3:
        old = bpy.data.objects.get("GNM_Stubble")
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        return None
    head = head or bpy.data.objects["GNM_Head"]
    rig = rig or bpy.data.objects.get("GNM_Rig")

    def weights(head_, me):
        names = ("R_hockey_mask", "R_chin_region", "R_upper_lip_region", "R_lower_lip_region", "R_left_cheek_region",
                 "R_right_cheek_region", "R_upper_lip", "R_lower_lip", "R_nose_region", "R_mouth_sock", "R_ears")
        g = _group_weights(head_, me, names)
        co = np.array([v.co for v in me.vertices])
        lip = g["R_upper_lip"] > 0.5
        mouth_z = co[lip, 2].mean() if lip.any() else co[:, 2].min() + 0.08

        def sst(a, b, x):
            t = np.clip((x - a) / (b - a), 0, 1)
            return t * t * (3 - 2 * t)
        lower = sst(mouth_z + 0.034, mouth_z + 0.006, co[:, 2])
        front = sst(0.03, -0.03, co[:, 1])
        area = np.clip(g["R_hockey_mask"] + g["R_chin_region"] + g["R_left_cheek_region"] + g["R_right_cheek_region"], 0, 1)
        w = lower * front * area + 0.9 * g["R_upper_lip_region"]
        w = w * (1 - np.clip(g["R_upper_lip"] + g["R_lower_lip"] + g["R_nose_region"] + g["R_mouth_sock"] + g["R_ears"], 0, 1))
        return np.clip(w, 0, 1)

    smp = _surface_samples(head, weights, int(9000 * P["beard"]), seed)
    if smp is None:
        return None
    pos, nrm, co, rng = smp

    def flow(p, n, rng_):                          # beard grows downward, slightly outward on the cheeks
        return Vector((0.2 if p.x > 0 else -0.2, 0.0, -1.0)) + Vector(rng_.normal(0, 0.3, 3))
    return _strand_object("GNM_Stubble", head, rig, pos, nrm, rng, flow, 0.0007, 0.000035, 38,
                          hair_material("MAT_stubble", P["hair"]), sides=3, segs=3, bend=0.08)


def build_scalp(P, head=None, rig=None, seed=31):
    """Buzz-cut scalp hair (~2 mm), matching the painted follicle dots: turns the bald mannequin look into a shaved
    head. Same region rule as skin_masks.m_scalp (above the hairline, back of the head, upper temples)."""
    if P.get("scalp", 0) < 0.3:
        old = bpy.data.objects.get("GNM_Scalp")
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        return None
    head = head or bpy.data.objects["GNM_Head"]
    rig = rig or bpy.data.objects.get("GNM_Rig")

    def sst(a_, b_, x):
        t = np.clip((x - a_) / (b_ - a_), 0, 1)
        return t * t * (3 - 2 * t)

    def weights(head_, me):
        names = ("R_skin", "R_forehead_region", "R_left_temple_region", "R_right_temple_region", "R_ears",
                 "R_hockey_mask")
        g = _group_weights(head_, me, names)
        co = np.array([v.co for v in me.vertices])
        x, yb, z = co[:, 0], co[:, 1], co[:, 2]            # Blender: GNM y -> z (up), GNM z -> -y (front)
        fh = g["R_forehead_region"] > 0.5
        fh_top = z[fh].max() if fh.any() else z.max() - 0.05
        scalp = sst(fh_top - 0.012, fh_top + 0.006, z) + sst(0.0, 0.04, yb) * sst(0.24, 0.30, z)
        scalp = scalp + (g["R_left_temple_region"] + g["R_right_temple_region"]) * sst(0.30, 0.33, z)
        face = g["R_hockey_mask"] * sst(0.34, 0.33, z)
        w = np.clip(scalp, 0, 1) * (1 - g["R_ears"]) * (1 - face) * (g["R_skin"] > 0.5)
        return np.clip(w, 0, 1)

    smp = _surface_samples(head, weights, int(60000 * P["scalp"]), seed)
    if smp is None:
        return None
    pos, nrm, co, rng = smp
    crown = Vector((0.0, 0.03, co[:, 2].max()))

    def flow(p, n, rng_):                          # hair lies away from the crown whorl, downward on the sides
        return (p - crown) + Vector((0, 0, -0.04)) + Vector(rng_.normal(0, 0.012, 3))
    return _strand_object("GNM_Scalp", head, rig, pos, nrm, rng, flow, 0.0018, 0.000032, 24,
                          hair_material("MAT_scalp_hair", P["hair"]), sides=3, segs=4, bend=0.18)


def hair_material(name, colour_srgb):
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (*[lin(float(c)) for c in colour_srgb], 1)
    b.inputs["Roughness"].default_value = 0.35
    b.inputs["Coat Weight"].default_value = 0.3
    b.inputs["Coat Roughness"].default_value = 0.2
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(b.outputs[0], out.inputs[0])
    return m


# extra vellus density around the eyes, between the brows and on the forehead (close-up framing)
DENSE = {"R_left_orbital_region": 1.6, "R_right_orbital_region": 1.6, "R_left_infraorbital_region": 1.8,
         "R_right_infraorbital_region": 1.8, "R_middle_brow_region": 2.0, "R_forehead_region": 1.3,
         "R_left_zygomatic_region": 1.4, "R_right_zygomatic_region": 1.4}


def build(head=None, rig=None, count=52000, seed=11):
    head = head or bpy.data.objects["GNM_Head"]
    rig = rig or bpy.data.objects.get("GNM_Rig")
    dg = bpy.context.evaluated_depsgraph_get()
    ev = head.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    # per-vertex weights from the GNM region groups (vertex groups survive the subdivision modifier)
    gi = {g.name: g.index for g in head.vertex_groups}
    nv = len(me.vertices)
    want = np.zeros(nv)
    avoid = np.zeros(nv)
    for v in me.vertices:
        for g in v.groups:
            nm = head.vertex_groups[g.group].name
            if nm in REGIONS:
                want[v.index] = max(want[v.index], g.weight)
            elif nm in AVOID:
                avoid[v.index] = max(avoid[v.index], g.weight)
    boost = np.ones(nv)
    for v in me.vertices:
        for g in v.groups:
            k = DENSE.get(head.vertex_groups[g.group].name)
            if k:
                boost[v.index] = max(boost[v.index], 1.0 + (k - 1.0) * g.weight)
    w_v = np.clip(want - 2.0 * avoid, 0, 1) * boost
    co = np.array([v.co for v in me.vertices])
    nr = np.array([v.normal for v in me.vertices])
    tris = np.array([lt.vertices[:] for lt in me.loop_triangles if lt.material_index == 0])
    ev.to_mesh_clear()
    a, b, c = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    wt = area * w_v[tris].mean(1)
    if wt.sum() <= 0:
        return None
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(tris), size=count, p=wt / wt.sum())
    r1, r2 = rng.random(count), rng.random(count)
    s = np.sqrt(r1)
    bary = np.stack([1 - s, s * (1 - r2), s * r2], 1)
    T = tris[pick]
    pos = (co[T] * bary[..., None]).sum(1)
    nrm = (nr[T] * bary[..., None]).sum(1)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    midx = 0.5 * (co[:, 0].max() + co[:, 0].min())
    verts, faces, tv = [], [], []
    for i in range(count):
        p, n = Vector(pos[i]), Vector(nrm[i])
        # flow: down and outward from the facial midline, projected onto the skin
        out = 1.0 if p.x >= midx else -1.0
        flow = Vector((0.55 * out, -0.25, -1.0)) + Vector(rng.normal(0, 0.35, 3))
        flow = (flow - n * flow.dot(n)).normalized()
        d0 = (flow * math.cos(math.radians(28)) + n * math.sin(math.radians(28))).normalized()
        L = 0.0011 * rng.uniform(0.6, 1.4)
        r0 = 0.0000075 * rng.uniform(0.8, 1.2)
        k = 4
        prev = None
        q, dv = p - n * 0.00003, d0.copy()
        side = dv.cross(n).normalized()
        for j in range(k + 1):
            t = j / k
            up = side.cross(dv).normalized()
            ring = []
            for m_ in range(3):
                ang = 2 * math.pi * m_ / 3
                ring.append(len(verts))
                verts.append(tuple(q + (side * math.cos(ang) + up * math.sin(ang)) * r0 * (1 - 0.8 * t)))
                tv.append(t)
            if prev:
                for m_ in range(3):
                    m2 = (m_ + 1) % 3
                    faces.append((prev[m_], prev[m2], ring[m2], ring[m_]))
            prev = ring
            q = q + dv * (L / k)
            dv = (dv + flow * 0.25).normalized()            # bends down onto the skin
    old = bpy.data.objects.get(NAME)
    if old:
        mo = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        bpy.data.meshes.remove(mo)
    mesh = bpy.data.meshes.new(NAME)
    mesh.from_pydata(verts, [], faces)
    mesh.polygons.foreach_set("use_smooth", np.ones(len(mesh.polygons), dtype=bool))
    at = mesh.attributes.new("hair_t", "FLOAT", "POINT")
    at.data.foreach_set("value", np.asarray(tv, np.float32))
    ob = bpy.data.objects.new(NAME, mesh)
    for col in head.users_collection:
        col.objects.link(ob)
    ob.matrix_world = head.matrix_world.copy()
    if rig:
        ob.parent = rig
        ob.matrix_parent_inverse = rig.matrix_world.inverted()
    mesh.materials.append(material())
    ob.visible_shadow = False                      # too fine to cast visible shadows; saves render time
    import fix_lash_binding as FX
    sd = ob.modifiers.new("SurfaceDeform", "SURFACE_DEFORM")
    sd.target = FX.skin_proxy(head)
    bpy.context.view_layer.update()
    with bpy.context.temp_override(object=ob, active_object=ob):
        bpy.ops.object.surfacedeform_bind(modifier=sd.name)
    # hide in the viewport only AFTER binding (a viewport-hidden object is not evaluated, so the bind would fail);
    # renders still include it, and Timeline playback in the viewport stays fast
    ob.hide_viewport = True
    print("fuzz", count, "hairs,", len(verts), "verts, bound", sd.is_bound, flush=True)
    return ob


def set_colour(P):
    """Vellus hair is fine and lightly pigmented: a little lighter than the skin on fair skin, dark on dark skin."""
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    skin = [lin(float(v)) for v in P["base"]]
    hair = [lin(float(v)) for v in P["hair"]]
    col = [min(1.0, 0.65 * s_ + 0.35 * h_) * 1.05 for s_, h_ in zip(skin, hair)]
    m = material()
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*col, 1)


def material():
    m = bpy.data.materials.get("MAT_fuzz") or bpy.data.materials.new("MAT_fuzz")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (0.62, 0.52, 0.44, 1)     # pale, unpigmented vellus hair
    b.inputs["Roughness"].default_value = 0.45
    b.inputs["Transmission Weight"].default_value = 0.35            # thin hair lets light through: rim glow
    b.inputs["Sheen Weight"].default_value = 0.4
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(b.outputs[0], out.inputs[0])
    return m


if __name__ == "__main__":
    build()

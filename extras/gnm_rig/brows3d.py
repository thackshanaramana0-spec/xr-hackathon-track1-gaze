"""Real 3D eyebrow hairs on any GNM head, from the strand paths that brow_hairs.py paints into the albedo
(gnm_rig/out/brows/<ID>_brows.npz: UV polylines, thickness, shade, colour).

Each hair point is placed on the head's current surface through GNM's UV layout (shared by every identity), so the
3D hairs sit exactly on top of the painted ones on any face shape. Hairs leave the skin at a shallow angle and lie
along it, as real brow hairs do. The strands are thin tapered tubes, bound with Surface Deform to the skin-only
proxy (fix_lash_binding.py), so they follow brow raises and frowns but never the eyeballs.

Called by materials.apply(tex_id) whenever the strand file exists; can also be run alone:
blender -b --factory-startup <head>.blend -P gnm_rig/brows3d.py -- --tex T02
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
NAME = "GNM_Brows"
SIDES = 4


def strand_file(tex_id):
    p = os.path.join(HERE, "out", "brows", f"{tex_id}_brows.npz")
    return p if os.path.exists(p) else None


def _surface(head):
    """Evaluated skin triangles: UV-space BVH (tile 1001) + 3D positions and normals."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = head.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    uvl = me.uv_layers["UVMap"].data
    co = [v.co.copy() for v in me.vertices]
    nrm = [v.normal.copy() for v in me.vertices]
    uv3, tris, tri_v = [], [], []
    for lt in me.loop_triangles:
        if lt.material_index != 0:
            continue
        uvs = [uvl[li].uv for li in lt.loops]
        if min(u.x for u in uvs) < 0 or max(u.x for u in uvs) > 1:
            continue
        base = len(uv3)
        uv3.extend(Vector((u.x, u.y, 0.0)) for u in uvs)
        tris.append((base, base + 1, base + 2))
        tri_v.append(tuple(lt.vertices))
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(uv3, tris), uv3, tris, tri_v, co, nrm


def build(tex_id, head=None, rig=None):
    path = strand_file(tex_id)
    if path is None:
        return None
    head = head or bpy.data.objects["GNM_Head"]
    rig = rig or bpy.data.objects.get("GNM_Rig")
    d = np.load(path)
    bvh, uv3, tris, tri_v, co, nrm = _surface(head)
    mw = head.matrix_world
    verts, faces, shade_v, t_v = [], [], [], []
    for poly, th, sh in zip(d["uv"], d["thick"], d["shade"]):
        pts, nors = [], []
        for u, v in poly:
            loc, _, fi, dist = bvh.find_nearest(Vector((float(u), float(v), 0.0)))
            if fi is None or dist > 2e-3:
                break
            a, b, c = (uv3[i] for i in tris[fi])
            va, vb, vc = tri_v[fi]
            p = barycentric_transform(loc, a, b, c, co[va], co[vb], co[vc])
            n = barycentric_transform(loc, a, b, c, co[va] + nrm[va], co[vb] + nrm[vb], co[vc] + nrm[vc]) - p
            pts.append(p)
            nors.append(n.normalized())
        if len(pts) < len(poly):
            continue
        k = len(pts)
        # lift: the root starts just under the skin, the hair rises ~0.25 mm and then lies along the surface
        path3 = []
        for i, (p, n) in enumerate(zip(pts, nors)):
            t = i / (k - 1)
            lift = -0.00004 + 0.00034 * math.sin(min(t * 1.6, 1.0) * math.pi / 2) - 0.00008 * t
            path3.append(p + n * lift)
        r0 = 0.000042 * float(th)
        prev = None
        for i in range(k):
            t = i / (k - 1)
            tang = (path3[min(i + 1, k - 1)] - path3[max(i - 1, 0)]).normalized()
            side = tang.cross(nors[i]).normalized()
            up = side.cross(tang).normalized()
            r = r0 * (1.0 - 0.85 * t)
            ring = []
            for j in range(SIDES):
                ang = 2 * math.pi * j / SIDES
                ring.append(len(verts))
                verts.append(tuple(path3[i] + (side * math.cos(ang) + up * math.sin(ang)) * r))
                shade_v.append(float(sh))
                t_v.append(t)
            if prev:
                for j in range(SIDES):
                    j2 = (j + 1) % SIDES
                    faces.append((prev[j], prev[j2], ring[j2], ring[j]))
            prev = ring
    old = bpy.data.objects.get(NAME)
    if old:
        me_old = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        bpy.data.meshes.remove(me_old)
    me = bpy.data.meshes.new(NAME)
    me.from_pydata(verts, [], faces)
    me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), dtype=bool))
    for nm_, vals in (("hair_shade", shade_v), ("hair_t", t_v)):
        a = me.attributes.new(nm_, "FLOAT", "POINT")
        a.data.foreach_set("value", np.asarray(vals, np.float32))
    ob = bpy.data.objects.new(NAME, me)
    for col in head.users_collection:
        col.objects.link(ob)
    ob.matrix_world = mw.copy()
    if rig:
        ob.parent = rig
        ob.matrix_parent_inverse = rig.matrix_world.inverted()
    me.materials.append(material(d["colour"]))
    import fix_lash_binding as FX
    proxy = FX.skin_proxy(head)
    sd = ob.modifiers.new("SurfaceDeform", "SURFACE_DEFORM")
    sd.target = proxy
    bpy.context.view_layer.update()
    with bpy.context.temp_override(object=ob, active_object=ob):
        bpy.ops.object.surfacedeform_bind(modifier=sd.name)
    print("brows3d", tex_id, len(d["uv"]), "hairs,", len(verts), "verts, bound", sd.is_bound, flush=True)
    return ob


def material(colour_srgb):
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    m = bpy.data.materials.get("MAT_brows") or bpy.data.materials.new("MAT_brows")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    base = [lin(float(c)) for c in colour_srgb]
    at = nt.nodes.new("ShaderNodeAttribute")
    at.attribute_name = "hair_shade"
    tt = nt.nodes.new("ShaderNodeAttribute")
    tt.attribute_name = "hair_t"
    # hairs are a little lighter and more translucent towards the tips
    tip = nt.nodes.new("ShaderNodeMapRange")
    tip.inputs[3].default_value, tip.inputs[4].default_value = 0.85, 1.25
    nt.links.new(tt.outputs["Fac"], tip.inputs[0])
    mul = nt.nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY"
    nt.links.new(at.outputs["Fac"], mul.inputs[0]); nt.links.new(tip.outputs[0], mul.inputs[1])
    col = nt.nodes.new("ShaderNodeMix"); col.data_type = "RGBA"; col.blend_type = "MULTIPLY"
    col.inputs[0].default_value = 1.0
    col.inputs[6].default_value = (*base, 1.0)
    nt.links.new(mul.outputs[0], col.inputs[7])
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(col.outputs[2], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.38
    b.inputs["Coat Weight"].default_value = 0.3            # the cuticle's sharp first highlight
    b.inputs["Coat Roughness"].default_value = 0.2
    b.inputs["Subsurface Weight"].default_value = 0.25     # light through thin hair
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.6, 0.4)
    b.inputs["Subsurface Scale"].default_value = 0.0002
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(b.outputs[0], out.inputs[0])
    return m


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    tex = argv[argv.index("--tex") + 1] if "--tex" in argv else "T02"
    build(tex)

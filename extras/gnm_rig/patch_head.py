"""Patch an existing head .blend with the current build_head.py versions of the eye-area extras, without rebuilding
the whole head (mesh, rig, expressions and identity stay exactly as they are).

blender -b --factory-startup <head>.blend -P gnm_rig/patch_head.py -- [--tearline] [--no-save]

--tearline   rebuild the tear meniscus strip (current radius / profile) and bind it to the skin-only proxy
--lashes     rebuild the eyelashes (current count / shape / material) and bind them to the skin-only proxy
Call with the head at rest (the head .blends have no animation).
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def eye_centres(rig):
    return tuple(tuple(rig.matrix_world @ rig.data.bones[b].head_local) for b in ("eye.L", "eye.R"))


def rebuild_tearline():
    import build_head as BH
    import fix_lash_binding as FX
    import gnm_model as G
    head = bpy.data.objects["GNM_Head"]
    rig = bpy.data.objects["GNM_Rig"]
    old = bpy.data.objects.get("GNM_TearLine")
    mats = list(old.data.materials) if old else []
    if old:
        me = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        bpy.data.meshes.remove(me)
    ob = BH.make_tearline(G.GNM(), head, eye_centres(rig))
    if mats and not ob.data.materials:
        ob.data.materials.append(mats[0])
    FX.rebind(FX.skin_proxy(head))
    print("tearline rebuilt", len(ob.data.vertices), flush=True)


def rebuild_lashes():
    import build_head as BH
    import fix_lash_binding as FX
    import gnm_model as G
    head = bpy.data.objects["GNM_Head"]
    rig = bpy.data.objects["GNM_Rig"]
    old = bpy.data.objects.get("GNM_Lashes")
    if old:
        me = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        bpy.data.meshes.remove(me)
    ob = BH.make_lashes(G.GNM(), head, eye_centres(rig))
    FX.rebind(FX.skin_proxy(head))
    print("lashes rebuilt", len(ob.data.vertices), flush=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--tearline" in argv:
        rebuild_tearline()
    if "--lashes" in argv:
        rebuild_lashes()
    if "--no-save" not in argv:
        bpy.ops.wm.save_mainfile()
        print("saved", bpy.data.filepath, flush=True)


if __name__ == "__main__":
    main()

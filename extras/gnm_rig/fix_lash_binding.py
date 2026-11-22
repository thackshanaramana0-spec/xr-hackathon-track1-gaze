"""Re-bind the eyelashes and the tear line to the head SKIN only (not the eyeballs).

Why: GNM's head mesh includes the eyeballs. Surface Deform binds each strand vertex to the nearest target faces, so
lash and tear-line vertices that sit close to the eyeball got bound to eyeball faces and were dragged across the eye
when it rotated (dark lines on the sclera, a notch cut out of the iris during the eye-roll and side glances).

Fix: a hidden proxy that shares GNM_Head's mesh, shape keys and armature, with the eyeball vertices masked out.
The lashes and tear line are bound to that proxy at rest, so they follow the lids, blinks and head, never the eyes.

blender -b --factory-startup <head>.blend -P gnm_rig/fix_lash_binding.py            (fixes and saves the file)
Also imported by build_head.py so new heads are built this way.
"""
import bpy

PROXY = "GNM_HeadSkinProxy"
GROUP = "skin_no_eyeball"


def skin_proxy(head):
    proxy = bpy.data.objects.get(PROXY)
    if proxy is None:
        me = head.data
        ig = [head.vertex_groups[n].index for n in ("eye.L", "eye.R")]
        vg = head.vertex_groups.get(GROUP) or head.vertex_groups.new(name=GROUP)
        keep = [v.index for v in me.vertices if max((g.weight for g in v.groups if g.group in ig), default=0.0) < 0.5]
        vg.add(keep, 1.0, "REPLACE")
        proxy = head.copy()                       # shares mesh data, shape keys (and their drivers) with the head
        proxy.name = PROXY
        for col in head.users_collection:
            col.objects.link(proxy)
        m = proxy.modifiers.new("MaskEyeballs", "MASK")
        m.vertex_group = GROUP
        names = [x.name for x in proxy.modifiers]
        if "Subdivision" in names:                # mask before subdividing
            with bpy.context.temp_override(object=proxy):
                bpy.ops.object.modifier_move_to_index(modifier=m.name, index=names.index("Subdivision"))
        proxy.hide_render = True
        proxy.hide_set(True)
        proxy.visible_camera = proxy.visible_shadow = False
    return proxy


def rebind(proxy):
    for name in ("GNM_Lashes", "GNM_TearLine"):
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        sd = next(m for m in ob.modifiers if m.type == "SURFACE_DEFORM")
        with bpy.context.temp_override(object=ob, active_object=ob):
            if sd.is_bound:
                bpy.ops.object.surfacedeform_bind(modifier=sd.name)      # unbind
        sd.target = proxy
        bpy.context.view_layer.update()
        with bpy.context.temp_override(object=ob, active_object=ob):
            bpy.ops.object.surfacedeform_bind(modifier=sd.name)
        print("rebound", name, "->", proxy.name, sd.is_bound, flush=True)


def fix(head=None):
    """Call with the head at its rest pose (no animation evaluated)."""
    head = head or bpy.data.objects["GNM_Head"]
    rebind(skin_proxy(head))


if __name__ == "__main__":
    fix()
    bpy.ops.wm.save_mainfile()
    print("saved", bpy.data.filepath, flush=True)

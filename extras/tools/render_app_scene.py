"""Re-render one legacy application scene (demo video): fixes texture paths broken when the old video folder moved
under legacy/, then renders the animation to legacy/video/build/<scene>/####.png.

    blender -b --factory-startup legacy/video/build/blend/app_vr.blend -P tools/render_app_scene.py -- [--frames 1-1]
"""
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
STUDIO = os.path.join(os.path.dirname(bpy.app.binary_path), f"{bpy.app.version[0]}.{bpy.app.version[1]}",
                      "datafiles", "studiolights", "world")

fixed = 0
for im in bpy.data.images:
    if im.source not in ("FILE", "TILED", "SEQUENCE") or im.packed_file:
        continue
    p = im.filepath.replace("/", "\\")
    if "AppData" in p:
        new = os.path.join(HOME, p[p.index("AppData"):])
    elif "studiolights" in p:
        new = os.path.join(STUDIO, os.path.basename(p))
    else:
        continue
    if os.path.exists(new):
        im.filepath = new
        fixed += 1
    else:
        print("still missing", new)
missing = [i.filepath for i in bpy.data.images if i.source in ("FILE", "SEQUENCE") and not i.packed_file
           and not os.path.exists(bpy.path.abspath(i.filepath))]
print("fixed", fixed, "missing", missing, flush=True)

sc = bpy.context.scene
name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
out = os.path.join(ROOT, "legacy", "video", "build", name)
os.makedirs(out, exist_ok=True)
sc.render.filepath = os.path.join(out, "####")
sc.render.image_settings.file_format = "PNG"
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if "--frames" in argv:
    a, b = argv[argv.index("--frames") + 1].split("-")
    sc.frame_start, sc.frame_end = int(a), int(b)
prefs = bpy.context.preferences.addons["cycles"].preferences
for dev in os.environ.get("XR_CYCLES_DEVICE", "OPTIX,CUDA").split(","):
    try:
        prefs.compute_device_type = dev
        prefs.get_devices()
        for d in prefs.devices:
            d.use = d.type == dev
        sc.cycles.device = "GPU"
        break
    except TypeError:
        continue
bpy.ops.render.render(animation=True)
print("rendered", name, sc.frame_start, "-", sc.frame_end, flush=True)

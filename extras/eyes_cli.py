"""Kinematic accuracy: one script, three inputs -> rendered frames and video (each at most 15 s).

    python eyes_cli.py --input "Left"              # both eyes move to the left, naturally
    python eyes_cli.py --input "Right"             # both eyes move to the right
    python eyes_cli.py --input "Generate Motion"   # natural sequence: glances, upward eye-roll, reading glances, blinks
    python eyes_cli.py                             # menu

Options: --tex T01..T08, --res 1920x1080, --samples 48, --fps 30, --out DIR, --blender PATH (or env XR_BLENDER).
Implementation: gnm_rig/eyes_cli.py (Blender side: gnm_rig/animate.py, motion model: gnm_rig/motion.py).
"""
import os
import runpy

runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gnm_rig", "eyes_cli.py"), run_name="__main__")

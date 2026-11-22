"""Eye-motion renderer for the GNM head: one script, three inputs, frames and video.

The three inputs, named as specified in the track brief:

    python eyes_cli.py --input "Left"              # both eyes move towards the left, naturally
    python eyes_cli.py --input "Right"             # both eyes move towards the right
    python eyes_cli.py --input "Generate Motion"   # a realistic eye-movement expression: glances left/right,
                                                   # an upward eye-roll with raised brows, reading glances, blinks
    python eyes_cli.py                             # no input: pick 1/2/3 from a menu

Names are case-insensitive. Generate_Motion, generate-motion and motion also work, and so do 1/2/3 and the
short forms L/R/M. The output is frames/ plus <out>/Left.mp4, Right.mp4 or Generate_Motion.mp4 (each <= 15 s).

Options: --tex T01..T08 (texture set), --head PATH, --res 1920x1080, --samples 48, --fps 30, --out DIR,
         --blender PATH (or env XR_BLENDER); set env XR_CYCLES_DEVICE=CUDA if OptiX fails on your NVIDIA driver.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HEAD = os.path.join(HERE, "out", "gnm_head.blend")
MAX_SECONDS = 15.0

# brief's input name -> (motion script key, output name)
INPUTS = {"left": ("left", "Left"), "right": ("right", "Right"), "generatemotion": ("motion", "Generate_Motion")}
ALIASES = {"l": "left", "1": "left", "r": "right", "2": "right", "motion": "generatemotion", "m": "generatemotion",
           "generate": "generatemotion", "3": "generatemotion"}


def normalise(name):
    k = "".join(ch for ch in name.lower() if ch.isalnum())
    k = ALIASES.get(k, k)
    if k not in INPUTS:
        sys.exit(f'Unknown input "{name}". Use one of: "Left", "Right", "Generate Motion".')
    return k


def ask():
    print('Select input:\n  1) Left\n  2) Right\n  3) Generate Motion')
    try:
        return normalise(input("> ").strip() or "3")
    except EOFError:
        sys.exit('No input given. Use --input "Left" | "Right" | "Generate Motion".')


def find_blender(explicit=None):
    if explicit or os.environ.get("XR_BLENDER"):
        return explicit or os.environ["XR_BLENDER"]
    cands = sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe"), reverse=True)
    for c in [shutil.which("blender")] + cands:
        if c and os.path.exists(c):
            return c
    sys.exit("Blender not found: pass --blender PATH (or set XR_BLENDER)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_pos", nargs="*", help='"Left" | "Right" | "Generate Motion" (alternative to --input)')
    ap.add_argument("--input", default=None, help='"Left" | "Right" | "Generate Motion"')
    ap.add_argument("--tex", default="T02")
    ap.add_argument("--head", default=None, help="head .blend (default: out/heads/<tex>.blend if built, else out/gnm_head.blend)")
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out", default=os.path.join(ROOT, "renders_eyes_cli"))
    ap.add_argument("--blender", default=None)
    ap.add_argument("--resume", action="store_true",
                    help="keep already rendered frames and continue from the first missing one (after an interruption)")
    a = ap.parse_args()
    raw = a.input or " ".join(a.input_pos)
    key = normalise(raw) if raw else ask()
    motion_key, out_name = INPUTS[key]
    print(f'Input: {out_name.replace("_", " ")}', flush=True)

    blender = find_blender(a.blender)
    head = a.head or os.path.join(HERE, "out", "heads", f"{a.tex}.blend")
    if not os.path.exists(head):
        head = HEAD
    if not os.path.exists(head):
        subprocess.run([blender, "-b", "--factory-startup", "-P", os.path.join(HERE, "build_head.py")], check=True)
    a.out = os.path.abspath(a.out)
    frames = os.path.join(a.out, out_name, "frames")
    start = 1
    if a.resume and os.path.isdir(frames):
        while os.path.exists(os.path.join(frames, f"{start:04d}.png")):
            start += 1
        print(f"resuming at frame {start}", flush=True)
    else:
        shutil.rmtree(frames, ignore_errors=True)
    os.makedirs(frames, exist_ok=True)
    cmd = [blender, "-b", "--factory-startup", head, "-P", os.path.join(HERE, "animate.py"), "--",
           "--input", motion_key, "--tex", a.tex, "--res", a.res, "--samples", str(a.samples), "--fps", str(a.fps),
           "--frames-dir", frames, "--start", str(start)]
    print("rendering:", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    n = len(glob.glob(os.path.join(frames, "*.png")))
    mp4 = os.path.join(a.out, f"{out_name}.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i", os.path.join(frames, "%04d.png"),
                    "-t", str(MAX_SECONDS), "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", mp4], check=True)
    print(f"{n} frames -> {mp4} ({n / a.fps:.1f} s)")


if __name__ == "__main__":
    main()

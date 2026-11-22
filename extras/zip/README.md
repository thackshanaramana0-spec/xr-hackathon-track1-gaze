# Synthetic Eyes: Track 1 submission (Team Rocklef)

Team Rocklef: Sree Rohith Balaji and Thackshanaramana, SRM Institute of Science and Technology.
Samsung PRISM Hackathon 2026 | XR Perception Group | 3D Assets Track. *(Event name as used by the team; not yet confirmed against an official organiser source.)*

This zip is the submission package. It contains the scene, the wrapper, the ten renders and the per-frame metadata. Nothing else is needed to run the wrapper.

## Contents

| Path | What it is |
|---|---|
| `scene.blend` | Textured GNM head, left and right eye bones, materials, fixed lights and a locked camera. Textures are packed in the file. |
| `wrapper/eyes.py` | The wrapper: `eyes.move(h, v)`, `eyes.reset()`, `eyes.render()`, plus command-line modes. |
| `renders/frame_00.png` … `renders/frame_09.png` | The ten clockwise renders, 1024 × 1024 PNG, θk = 2πk/10 starting at the top. |
| `metadata.json` | One record per frame: inputs, eye rotations, 2D pupil centres, camera matrix and more. |
| `README.md` | This file. |

## Requirements

- **Blender 5.2 LTS.** Tested on Windows 11 with an NVIDIA RTX 4060 Laptop GPU.
- No add-ons and no Python packages for the wrapper.
- No downloads: `scene.blend` packs all its textures.
- A GPU is optional. The wrapper uses OptiX, CUDA, HIP, oneAPI or Metal when present, and the CPU otherwise.

## Setup

1. Unzip the file. **Keep the folder structure as it is**: `wrapper/eyes.py` is found relative to `scene.blend`.
2. Open a terminal in the unzipped folder, the one that contains `scene.blend`.

## Run

Run these from the unzipped folder:

```bash
blender -b scene.blend -P wrapper/eyes.py -- --sequence      # writes renders/frame_00..09.png and metadata.json
blender -b scene.blend -P wrapper/eyes.py -- --directions    # writes checks/: center, left, right, up, down, reset
blender -b scene.blend -P wrapper/eyes.py -- --move 1 0 --out right.png
```

Options:

- `--samples N`: Cycles samples. The default is 128, as saved in the scene.
- `--no-eyes`: skip the eye close-up renders.
- `--root DIR`: write the output to `DIR` instead of the folder that contains `scene.blend`.
- If OptiX fails on an older NVIDIA driver, set `XR_CYCLES_DEVICE=CUDA` before running.

**Warning:** `--sequence` overwrites `renders/` and `metadata.json` in the folder you run it from. Use `--root` to write
somewhere else and keep the submitted files.

Inside Blender, with `scene.blend` open (Scripting tab or Python console):

```python
import sys; sys.path.append(r"<folder containing scene.blend>/wrapper")
import eyes
eyes.move(0.5, -1.0)           # h, v in [-1, +1]
rec = eyes.render("test.png")  # writes the PNG and returns its metadata record (a dict)
eyes.reset()                   # back to centre fixation
```

## Wrapper interface

| Call | Effect |
|---|---|
| `eyes.move(h, v)` | Sets the gaze. `h` and `v` are in [-1, +1]; values outside that range are clamped. `+h` moves the gaze to the image right (the subject's left). `+v` moves it up. |
| `eyes.reset()` | Returns the gaze to centre. |
| `eyes.render(path)` | Renders `CAM_Gaze` to a 1024 × 1024 PNG at `path` and returns the metadata record for that frame. |

## Geometry

- The fixation target is 35 cm in front of the midpoint `M` between the two eyeball centres. It moves by up to ±5 cm: `T = M + 0.35 m forward + h × 0.05 m right + v × 0.05 m up`.
- Each eye bone rotates in 3D about its eyeball centre, with a Damped Track to the target. Both eyes converge on it.
- The camera `CAM_Gaze` is locked 0.40 m in front of `M`, facing the face. It uses a 70 mm lens on a 36 mm sensor.
- The lighting is one fixed studio rig, identical for every render.
- The sampling is θk = 2π·k/10, h = sin θk, v = cos θk, for k = 0…9. Frame 0 is at the top and the frames go clockwise.

## metadata.json

One record per frame. The required fields:

| Field | Meaning |
|---|---|
| `frame`, `theta`, `input {h, v}` | Frame index, angle in radians, normalised inputs. |
| `eye_rotation_L`, `eye_rotation_R` | Degrees, XYZ Euler, world frame: the rotation from straight ahead (−Y) to that eye's line of sight. |
| `pupil_center_2D_L`, `pupil_center_2D_R` | Pixels in the 1024 × 1024 render. Origin top-left, x to the right, y down. |
| `camera_matrix` | Intrinsics K (OpenCV convention). |

Other fields: `camera_extrinsics_RT` (world to camera), `camera_projection_P = K[R|t]`, eye yaw and pitch, gaze vectors,
eyeball and pupil centres in 3D, the fixation target, its forward distance, the camera distance and the vergence angle.
`L` is the subject's left eye, which appears on the image right.

The `eyes_closeup` entries in each record point to eye close-up images in `renders_eyes/`. That folder is produced by the
default run and is **not in this zip**. Running with `--no-eyes` does not write it.

## Checking the output

- `renders/` should contain ten 1024 × 1024 PNG files, `frame_00.png` to `frame_09.png`.
- `metadata.json` should contain ten records, each with the fields listed above.
- After `--directions`, `checks/directions.json` lists the five-direction results. The five-direction renders are in `checks/`.

An independent checker is part of the full project repository. It reads the PNGs and the JSON files and reports PASS,
FAIL or NOT VERIFIED for each check. Run `--directions` before using it, because the five-direction check reads `checks/`.
Without `renders_eyes/` (see above), the eye close-up check is reported as NOT VERIFIED.

## Known limitations

1. The eye close-up renders (`renders_eyes/`) are not in this zip. The `eyes_closeup` entries in `metadata.json` refer to them.
2. The wrapper was tested on Blender 5.2 LTS only. Blender 4.2 LTS has not been tested.

## Licences and credits

- **GNM v3 head model:** Google, Apache-2.0.
- **Studio HDRI:** Blender's bundled `interior.exr`, CC0.
- **Everything else** (textures, eyes, hair, rig, expressions, motion, wrapper and renders) was written by Team Rocklef. The AI tools used are disclosed in `AI_DISCLOSURE.md` in the full repository.

---

**Full project:** this zip contains only the submission files. The full project README, with the demo videos, the source code, the pipeline and the verification tool, is `README.md` in the project repository. It is not in this zip.

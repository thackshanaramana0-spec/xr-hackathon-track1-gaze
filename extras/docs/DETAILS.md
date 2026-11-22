# Technical details

Everything behind the deliverables listed in the main [README](../README.md). Paths are relative to the `extras/` folder. Submission files are at the repository top level.

## 1. Textures (GNM UV, UDIM)

Each set is `textures/<ID>_<name>/<ID>_{albedo,normal,roughness}.<UDIM>.png`:

| Tile | Region | Maps |
|---|---|---|
| 1001 | Skin (face, scalp, ears, neck, lid margins) | albedo, normal, roughness, all 4096² |
| 1002 | Left eye: sclera, iris, pupil | albedo + iris relief normal, 4096² |
| 1004 | Right eye: a **separate** iris (same colour family, different pattern) | albedo + iris relief normal, 4096² |
| 1006, 1007 | Teeth and gums, tongue | albedo |

In Blender, load `<ID>_albedo.<UDIM>.png` as a tiled image on GNM's UV map, and every region gets its texture.

| ID | Set | Iris |
|---|---|---|
| T01 | fair, young female | blue |
| T02 | fair male, stubble | green |
| T03 | olive / Mediterranean male | brown |
| T04 | East Asian female | dark brown |
| T05 | South Asian male | dark brown |
| T06 | African female | very dark |
| T07 | elderly Caucasian male, wrinkles and age spots | grey-blue |
| T08 | Latina female | hazel |

**Skin**
- **Seam-free by construction.** Every skin layer is generated in 3D on the GNM surface and baked through GNM's own
  UVs, so the texels on either side of a UV seam come from the same 3D point.
- **Layers:**
  - melanin tone and mottling, plus haemoglobin redness on the nose, cheeks and ears
  - under-eye shadow and a wet pink waterline
  - vermilion lips with fine lines
  - pores at about 0.4 mm, stronger in the T-zone
  - freckles and age spots
  - stubble and scalp follicles
  - forehead lines and crow's feet that scale with age
- **Region masks** come from GNM's own vertex groups.
- **Eyebrows.** About 900 individual hairs per brow, grown with an anatomical flow field (upward at the inner end,
  herringbone through the body, outward at the tail), painted into the albedo and also built as 3D strands.
- **Fine detail taken from close-up reference footage:**
  - micro-relief (cell pattern, pits and fine noise) with crosshatch furrows
  - capillaries and veins scaled to skin tone
  - colour zones on the forehead and lower face
  - meibomian gland dots on the lid margins, sebaceous dots on the nose, moles
  - an oily coat that follows the roughness map (shinier T-zone)
  - a caruncle and lid margin that follow the skin tone

**Hair (3D, per identity)**
- Head hair as Blender hair curves with the Principled Hair BSDF (physically based melanin colour from the set's
  hair colour): short side-parted cuts, a bun, a coily style, and salt-and-pepper for T07.
- 3D brow strands, stubble on the male sets and fine vellus hair on the face.
- Every strand, lash and the tear line are bound to a skin-only copy of the head with the eyeballs masked out, so
  nothing is dragged across the eye when it rotates ([`gnm_rig/fix_lash_binding.py`](../gnm_rig/fix_lash_binding.py)).

**Eyes** (4K, separate for each eye)
- Domain-warped stroma fibres with raised trabeculae, plus a matching relief normal map
- Crypts of Fuchs, contraction furrows, a zig-zag collarette ridge and a crenellated pupillary ruff
- Pigment flecks and a soft limbal ring
- Sclera with a blue-grey limbus, warm canthi and branching conjunctival vessels

**Rendering**
- Cycles, with refraction through GNM's cornea and a pupil that traps light.
- A soft lid shadow on the eyeball.
- A tear-film strip on the lid margins.
- Clumped, curled eyelashes bound to the lids.

**Faces**
- Each of the 8 main renders uses a matching GNM identity from GNM's official semantic IdentitySampler, which we ported to
  NumPy.
- [`renders_textures/extra/same_head/`](../renders_textures/extra/same_head/) shows all 8 sets on one identical head, proving the
  maps are interchangeable on GNM's UVs.

## 2. Eye motion: `eyes_cli.py`

```bash
python eyes_cli.py --input "Left"              # both eyes move left, naturally       -> renders_eyes_cli/Left.mp4
python eyes_cli.py --input "Right"             # both eyes move right                 -> renders_eyes_cli/Right.mp4
python eyes_cli.py --input "Generate Motion"   # glances, upward eye-roll, blinks     -> renders_eyes_cli/Generate_Motion.mp4
python eyes_cli.py                             # no input: choose 1/2/3 from a menu
```

Input names are case-insensitive; `Generate_Motion`, `motion`, `1/2/3` and `L/R/M` also work.

Options: `--tex T01..T08`, `--res 1920x1080`, `--samples 48`, `--fps 30`, `--blender PATH` (or env `XR_BLENDER`).
Directions are from the viewer's side.

What makes the motion look human ([`gnm_rig/motion.py`](../gnm_rig/motion.py)):
- **Saccades** follow the main sequence (21 ms + 2.2 ms/°) with a minimum-jerk profile.
- **Fixations** have drift and micro-saccades.
- **Blinks** close fast (about 90 ms) and reopen more slowly (about 190 ms); large gaze shifts carry a blink, and
  there are occasional half-blinks.
- **The head follows** large shifts by about 25%, with a lag, while the eyes counter-rotate (vestibulo-ocular
  reflex).
- **Eyelids follow vertical gaze**, and the brows lift during the upward eye-roll.

## Python Control Wrapper: `eyes.py`

```bash
blender -b --factory-startup gnm_rig/out/heads/T02.blend -P eyes.py -- --look 18 6 --eyelids 0.6 --brows 0.5 --render out.png
blender -b --factory-startup gnm_rig/out/heads/T02.blend -P eyes.py -- --look -15 -12 --left-lid 1 --right-lid 0.15 --state
```

You can also use it inside Blender, in the Python console with a head `.blend` open:

```python
import sys; sys.path.append(r"<repo>")
import eyes
eyes.look(15, 5)        # gaze coordinates (deg)
eyes.eyelids(0.6)       # 1 = open, 0 = closed
eyes.blink(30)          # keyframed blink
eyes.key(1)
eyes.render("still.png")
```

`eyes.state()` returns per-eye rotation angles, lines of sight and lid openings. The lids follow vertical gaze
automatically, coordinated with any opening you set.

## 3. Timeline expression: `gnm_expression_timeline.blend`

Open the file in Blender and press **Play**. It is a 10.5 s expression on the Timeline:
1. Surprise: brows up, eyes wide, pupils dilate.
2. Looking left and right with a blink.
3. A suspicious squint with lowered brows.
4. An upward eye-roll.
5. Looking down with the pupils constricting, then a blink.

The rig exposes keyframeable controls on `GNM_Rig`: `blink_L`, `blink_R`, `wide`, `squint`, `brow_raise`,
`brow_down`, `pupil` and `auto_lids`. Gaze is set by moving `GAZE_Target`; both eyes track it and converge.

## Demo video: `demo/SRMIST_Rocklef_demo.mp4`

A narrated walkthrough (2 min 56 s, 1080p): why eyes matter, the problem, related work, our textures,
the seam audit, the three motion inputs, the Timeline expression, face-shape sliders, architecture, comparison,
applications and next steps. Apart from the four application scenes (VR headset, driver monitoring, eye typing, early autism screening),
every result shown is the GNM head from this repository. The application scenes reuse the characters from the
earlier work in `legacy/`; `tools/render_app_scene.py` re-renders them into `legacy/video/build/app_*`, and the
finished scenes are in `demo/clips/`.

```bash
python demo/narration.py                                     # voiceover + word timings
blender -b --factory-startup gnm_expression_timeline.blend -P demo/shots.py -- --shot timeline
blender -b --factory-startup gnm_rig/out/heads/T05.blend    -P demo/shots.py -- --shot identity
blender -b --factory-startup gnm_rig/out/heads/T03.blend    -P demo/shots.py -- --shot orbit
python demo/make_demo.py                                     # -> demo/SRMIST_Rocklef_demo.mp4 + .srt
```

## How it is built

Full details are in [`gnm_rig/README.md`](../gnm_rig/README.md).

- **Model and rig.** A NumPy re-implementation of the GNM forward pass. It uses GNM's 4-joint rig (neck, head,
  eye.L, eye.R) and its skinning weights, with each eye bone at the eyeball centre on GNM's optical axis.
- **Expressions.** Blink, wide, squint, lid-follow and brow shapes are solved by ridge-regularised least squares
  inside GNM's own eye-region expression space (100 PCA components per eye). The whole lid, brow and skin therefore
  deform like the scanned faces GNM was learned from.
- **Rebuild from scratch.** Download `gnm_head.npz` (53 MB, Apache-2.0) from
  [huggingface.co/google/gnm-v3](https://huggingface.co/google/gnm-v3) to `_downloads/gnm/model/`, then follow the
  quick start in `gnm_rig/README.md`.
- **Blender.** Tested with 5.2.4 LTS and 5.3. On NVIDIA drivers older than 580, set `XR_CYCLES_DEVICE=CUDA` so Cycles
  uses the GPU.

`legacy/` holds our earlier exploration: a MakeHuman/MPFB face with a calibrated gaze rig and pupil ground truth, built
before the evaluation criteria were published.

## Track 1 submission: [top-level files](../../README.md)

The track's evaluation criteria score direction (40), calibration (20), automation (20) and sequence and
metadata (20). The repository's top level is the submission package built on the same GNM head (T02, with the textures
packed in), and `python extras/tools/make_zip.py` turns it into `extras/SRMIST_Rocklef.zip`:

```
blender -b scene.blend -P wrapper/eyes.py -- --sequence      # renders/ + metadata.json
blender -b scene.blend -P wrapper/eyes.py -- --directions    # five-direction check
python extras/tools/check_bundle.py .                                        # independent checks (requirements.txt)
```

| Item | Implementation | Measured (`quality_audit/gate0/report.md`) |
|---|---|---|
| Wrapper | `eyes.move(h, v)`, `eyes.reset()`, `eyes.render()`; h, v in [-1, +1], clamped | runs headless from a clean unzip on Blender 5.2.4 and 5.3.0 with identical metadata |
| Calibration | target 35 cm forward of the eye midpoint, +-5 cm; camera locked 40 cm forward | 0.3500 m and 0.4000 m in every frame; camera axis 0.000 deg off the eye midpoint |
| Eyes | 3D rotation about each eyeball centre, both converge on the target | line-of-sight error 0.0001 deg; vergence 10.21 deg at centre (geometry predicts 10.22) |
| Sequence | 10 clockwise frames, theta_k = 2*pi*k/10, h = sin, v = cos, 1024 x 1024 PNG, fixed lights | backdrop difference between frames 0.07 / 255 |
| Metadata | every required field plus K[R\|t], 3D pupils, gaze vectors, vergence | metadata pupils vs pupils detected in the PNGs: mean 0.96 px, max 1.92 px |
| Direction test | left, right, up, down, reset | 5 of 5; each direction moves both pupils 9-10 px in the 1024 frame (about 50-60 px in the eye close-ups) |

`+h` moves the gaze towards the image right (the subject's left). The slides do not say whether "Right" means
the viewer's or the subject's right. This project uses the viewer's (image) right, and the metadata records that convention.

Known limitations: the bundle packs 2048 px skin normal and roughness tiles (the full 4096 px sets are in
`textures/`) to keep `scene.blend` under GitHub's 100 MB file limit; one identity (T02) is used for the evaluated
sequence; tested on Windows with Blender 5.2.4 LTS and 5.3.0 (not yet on 4.2 LTS). `Dockerfile` renders the bundle
headless on Linux with Blender 5.2.4 (not built here, since Docker is not installed on the build machine).

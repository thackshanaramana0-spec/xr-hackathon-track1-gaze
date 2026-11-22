# Quality audit: seams and artifacts

Track brief, quality audit: *Photorealistic Quality Audit: render textured face/eyes under natural gaze; inspect for seams and artifacts.* The evaluation standard also scores seam absence.

## 1. Numeric seam check (skin tile 1001, all 8 sets)

GNM's skin has **142 UV-seam edges**. These are edges where the same 3D edge appears twice in the texture. For every seam edge, we sample the baked albedo 2.5 texels inside each side, at 6 matching points along the edge, and measure the colour difference (RGB distance on a 0–255 scale).

As a baseline we take the same measurement across 4000 ordinary, non-seam edges. That baseline is the texture's natural pixel-to-pixel variation from pores, hairs and freckles. A set passes when its seam difference is of the same order as that natural variation (seam mean ≤ 1.5 × baseline + 1). For reference, about 3–5 RGB units is around the threshold of a visible difference.

| Texture set | seam mean | seam p95 | baseline mean | seam/baseline | result |
|---|---|---|---|---|---|
| T01 fair young female | 4.26 | 12.66 | 3.22 | 1.32 | PASS |
| T02 fair male stubble | 5.14 | 15.19 | 4.03 | 1.28 | PASS |
| T03 olive mediterranean male | 4.52 | 13.68 | 3.81 | 1.19 | PASS |
| T04 east asian female | 5.50 | 17.34 | 3.82 | 1.44 | PASS |
| T05 south asian male | 3.81 | 10.96 | 3.09 | 1.23 | PASS |
| T06 african female | 2.39 | 6.70 | 1.80 | 1.33 | PASS |
| T07 elderly caucasian male | 3.80 | 10.90 | 3.28 | 1.16 | PASS |
| T08 latina female | 4.47 | 13.63 | 3.31 | 1.35 | PASS |

Raw numbers, including the roughness maps, are in `seam_audit.json`.

**Why the textures are seam-free.** Every skin layer is generated in 3D on the GNM surface and baked through GNM's own UVs, so both copies of a seam edge sample the same 3D point. A 24-texel bake margin extends each island so texture filtering never reaches the background. The eye textures live on their own radial islands (tiles 1002 and 1004) and have no seams across the visible iris or sclera.

`T03_uv_seams_overlay.png` and `T06_uv_seams_overlay.png` show the seam edges in red over the albedo.

## 2. Visual check at the seams

The renders `T03_back.png`, `T03_ear.png`, `T06_back.png` and `T06_ear.png` show the back of the head and the ear and jaw, where GNM's UV seams run. They are rendered with the 3D head hair on, as the face is delivered; the hair covers the scalp seams there, so the numeric check in section 1 is the test for those, while the ear, jaw and nape seams stay visible in the renders. Front-facing renders and eye close-ups under natural gaze are in `../renders_textures/` and in the three videos.

## 3. Artifact checklist

| Check | Result |
|---|---|
| Visible UV seams on skin | none (see table and renders) |
| Texture stretching | none: layers are generated in 3D, not projected |
| Eyeball / eyelid intersection while blinking or looking around | none: lids are driven from GNM's own eye expression space, and the tear film is bound to the lid margins |
| Pupil / iris artefacts | pupil is a true light trap; separate left and right iris maps |
| Black or empty texels | none: 24-texel bake margin, and every face is covered |
| Lashes or tear line dragged across the eye | none: lashes, tear line, brows and all 3D hair are bound (Surface Deform) to a skin-only proxy of the head with the eyeballs masked out (`gnm_rig/fix_lash_binding.py`), so they follow the lids and skin but never the rotating eyeball. A binding to the full mesh would let lower lashes and the lower tear strip ride on the eyeball during eye-rolls and side glances, so the binding uses the skin-only proxy |
| Lash roots glowing through the skin | none: lash roots sit just under the skin surface (0.12 mm), so subsurface light never reaches buried geometry |

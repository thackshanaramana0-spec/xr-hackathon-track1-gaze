# AI Disclosure

**Team Rocklef** — Sree Rohith Balaji and Thackshanaramana  
**Samsung PRISM Hackathon 2026** | XR Perception Group | 3D Assets Track

## Use of AI-Assisted Tools

AI-assisted tools were used to support the development, testing, and presentation of this project.

| Tool | Purpose |
|---|---|
| **Claude (Anthropic), via Claude Code** | Used to support development workflows, including debugging, testing, code review, optimization, and technical documentation. |
| **Microsoft Edge Neural Text-to-Speech (`edge-tts`)** | Used to generate the narration audio for the demonstration video. |

## Development and Verification

The project was developed under the team's direction, including defining objectives, selecting technical approaches, integrating components, and evaluating the final results.

The team was responsible for the project's design, implementation oversight, validation, and final evaluation. AI-assisted outputs were reviewed as part of the development process, with the team retaining responsibility for the submitted implementation and its technical claims.

## Asset Generation and Rendering

No generative image or video models were used to produce the project's visual assets.

- **Procedural textures:** Skin, iris, hair, and eyebrow textures were generated using Python-based procedural methods and applied through the GNM UV layout.
- **3D rendering:** Images and videos were rendered using Blender's Cycles path tracer.
- **Eye animation:** Saccades, fixations, and blinks were implemented through scripted motion models rather than generative animation.

## Third-Party Models and Assets

- **GNM v3 (Google, Apache-2.0):** Parametric head model providing the mesh, UV layout, rig, and identity and expression representations.
- **Blender Studio HDRI (`interior.exr`, CC0):** Environment lighting asset used for rendering.
- **MakeHuman/MPFB (CC0):** Assets used during earlier exploratory development under `legacy/`.

Third-party models and assets are acknowledged separately from the team's project-specific development and implementation.

## Responsibility

Team Rocklef retains responsibility for the final submission, including the implementation, technical accuracy, evaluation results, and compliance with the hackathon's submission requirements.

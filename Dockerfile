# Headless renderer for the whole project: Blender 5.2 LTS + Python 3 + ffmpeg on Linux (CPU by default).
#
#   docker build -t rocklef-gaze .
#
# Evaluation deliverables (Track 1 brief):
#   docker run --rm -v "$PWD/out:/out" rocklef-gaze python3 extras/eyes_cli.py --input Left --out /out              # Left / Right / "Generate Motion" -> mp4
#   docker run --rm -v "$PWD/out:/out" rocklef-gaze blender -b --factory-startup extras/gnm_rig/out/heads/T03.blend \
#        -P extras/render_textures.py -- --tex T03 --views portrait,eyes,macro --out /out                           # texture renders
# Track 1 bundle: 10 clockwise frames + metadata.json + direction checks, then the independent checks
#   docker run --rm -v "$PWD/out:/out" rocklef-gaze                                                          # default
# NVIDIA GPU:  add  --gpus all -e XR_CYCLES_DEVICE=CUDA
FROM ubuntu:24.04

ARG BLENDER_VERSION=5.2.4
ARG BLENDER_SERIES=5.2
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates wget xz-utils ffmpeg python3 python3-numpy python3-pil python3-scipy \
        libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 libsm6 libice6 \
        libgl1 libegl1 libglu1-mesa libx11-6 libxext6 libwayland-client0 libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*
RUN wget -q https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz \
    && tar -xf blender-${BLENDER_VERSION}-linux-x64.tar.xz -C /opt \
    && rm blender-${BLENDER_VERSION}-linux-x64.tar.xz \
    && ln -s /opt/blender-${BLENDER_VERSION}-linux-x64/blender /usr/local/bin/blender
ENV XR_BLENDER=/usr/local/bin/blender

WORKDIR /app
COPY . .
# default: re-render the bundle's 10 frames + metadata and the direction checks in place, run the independent
# checks, and copy everything to /out (mount a folder there to keep it)
CMD ["sh", "-c", "blender -b --factory-startup scene.blend -P wrapper/eyes.py -- --sequence --directions --no-eyes && python3 extras/tools/check_bundle.py . /out/gate0; mkdir -p /out && cp -r renders checks metadata.json /out/"]

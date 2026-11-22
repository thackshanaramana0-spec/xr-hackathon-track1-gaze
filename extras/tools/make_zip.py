"""Pack the Track 1 submission zip: SRMIST_Rocklef.zip at the repository top level, containing exactly
scene.blend, wrapper/eyes.py, renders/ (10 frames), metadata.json and README.md at the top level.

The README inside the zip is extras/zip/README.md (written for someone who has only the zip). The repository
README.md is not packed.

    python extras/tools/make_zip.py
"""
import glob
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # extras/
TOP = os.path.dirname(ROOT)                                           # repository top level
OUT = os.path.join(TOP, "SRMIST_Rocklef.zip")                         # team_name.zip (team name = CollegeName_TeamName)
ZIP_README = os.path.join(ROOT, "zip", "README.md")

# (path inside the zip, file on disk)
members = [("scene.blend", os.path.join(TOP, "scene.blend")),
           ("wrapper/eyes.py", os.path.join(TOP, "wrapper", "eyes.py")),
           ("metadata.json", os.path.join(TOP, "metadata.json")),
           ("README.md", ZIP_README)]
for p in sorted(glob.glob(os.path.join(TOP, "renders", "frame_*.png"))):
    members.append((os.path.relpath(p, TOP).replace(os.sep, "/"), p))
assert len(members) == 14, [m[0] for m in members]

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for arcname, path in members:
        z.write(path, arcname)
print(OUT, round(os.path.getsize(OUT) / 2**20, 1), "MB,", len(members), "files")

"""Fail if any frame in a strip touches a cell edge.

ART_SPEC requires a 1-texel transparent border on every side, because the engine
dilates the outline into it. A limb that swings out of the cell loses its outline
and gets visibly clipped. Run after every rig change.

    python pixelanim/checkborder.py examples/skeleton_warrior/out/skeleton_warrior_strip.png 48 48
"""
import sys
from PIL import Image

path = sys.argv[1]
CW = int(sys.argv[2]) if len(sys.argv) > 2 else 48
CH = int(sys.argv[3]) if len(sys.argv) > 3 else 48

im = Image.open(path).convert("RGBA")
px = im.load()
if im.height != CH or im.width % CW:
    sys.exit(f"{path} is {im.width}x{im.height}, not a row of {CW}x{CH} cells")

bad = []
for f in range(im.width // CW):
    x0 = f * CW
    edges = []
    if any(px[x0, y][3] for y in range(CH)):               edges.append("left")
    if any(px[x0 + CW - 1, y][3] for y in range(CH)):      edges.append("right")
    if any(px[x0 + x, 0][3] for x in range(CW)):           edges.append("top")
    if any(px[x0 + x, CH - 1][3] for x in range(CW)):      edges.append("bottom")
    if edges:
        bad.append((f + 1, edges))

n = im.width // CW
if bad:
    for frame, edges in bad:
        print(f"  frame {frame}: touches {', '.join(edges)}")
    sys.exit(f"{len(bad)} of {n} frames have no border left for the outline")
print(f"{n} frames, all clear of the cell border")

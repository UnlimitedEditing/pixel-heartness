"""Render a sprite at zoom with a numbered cell-space grid, so rig pivots and part
rects can be read off instead of guessed.

    python pixelanim/grid.py examples/skeleton_warrior/skeleton_warrior.png 48 48
"""
import sys
from PIL import Image, ImageDraw

src_path = sys.argv[1]
CW = int(sys.argv[2]) if len(sys.argv) > 2 else 48
CH = int(sys.argv[3]) if len(sys.argv) > 3 else 48
S = int(sys.argv[4]) if len(sys.argv) > 4 else 12
out = sys.argv[5] if len(sys.argv) > 5 else "out/grid.png"

src = Image.open(src_path).convert("RGBA")

# same placement mode=slice uses: centred horizontally, bottom-aligned
cell = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
cell.paste(src, ((CW - src.width) // 2, CH - src.height))

M = 30
img = Image.new("RGB", (CW * S + M, CH * S + M), (40, 40, 46))
img.paste(cell.resize((CW * S, CH * S), Image.NEAREST).convert("RGB"), (M, M))
d = ImageDraw.Draw(img)

for x in range(0, CW + 1, 2):
    d.line([(M + x * S, M), (M + x * S, M + CH * S)],
           fill=(255, 80, 80) if x % 8 == 0 else (90, 90, 100))
    if x % 4 == 0:
        d.text((M + x * S - 6, 10), str(x), fill=(230, 230, 230))
for y in range(0, CH + 1, 2):
    d.line([(M, M + y * S), (M + CW * S, M + y * S)],
           fill=(255, 80, 80) if y % 8 == 0 else (90, 90, 100))
    if y % 4 == 0:
        d.text((4, M + y * S - 5), str(y), fill=(230, 230, 230))

import os
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
img.save(out)
print(f"{src_path} {src.width}x{src.height} in a {CW}x{CH} cell -> {out}")

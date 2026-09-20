"""Contact sheet for a walk-turn rig: one row per facing, one column per walk frame."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw
strip, out, ncols = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 4
im = Image.open(strip); CW = 48; h = im.height; n = im.width // CW
boxes = [im.crop((i * CW, 0, (i + 1) * CW, h)).getbbox() or (0, 0, 1, 1) for i in range(n)]
x0 = min(b[0] for b in boxes) - 2; x1 = max(b[2] for b in boxes) + 2; y0 = min(b[1] for b in boxes) - 2; y1 = max(b[3] for b in boxes) + 2
S = 4; w, hh = (x1 - x0) * S, (y1 - y0) * S; rows = n // ncols
sheet = Image.new("RGB", (ncols * w + 8, rows * hh + 8), (40, 40, 48))
for i in range(n):
    f = im.crop((i * CW, 0, (i + 1) * CW, h)).crop((x0, y0, x1, y1))
    c = Image.new("RGBA", f.size, (58, 60, 72, 255)); c.alpha_composite(f)
    sheet.paste(c.convert("RGB").resize((w, hh), Image.NEAREST), (4 + (i % ncols) * w, 4 + (i // ncols) * hh))
sheet.save(out); print(n, "frames", sheet.size)

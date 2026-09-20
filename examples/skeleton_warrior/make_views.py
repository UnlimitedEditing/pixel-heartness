"""SPIKE. Cut a corrected diffusion profile into per-part variant art.

Reads data/diffusion/view_2.png (the profile from pixelize.py, on the source palette and
scale) and writes one source-sized sprite per part, in the layout part variants use: the
same 32x46 size as skeleton_warrior.png, so place_in_cell puts it where the front's part is.

The labelling is by boxes in CELL coordinates, read off the printed profile map (body axis
at column 27, row 3 = top of the skull). It is deliberately crude: rows and columns, not
seeds, because this profile has one visible leg, an edge-on shield and a glove overlapping
the hip, and a flood fill from seeds cannot tell those apart any better than a box can.

    python examples/skeleton_warrior/make_views.py
"""
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
CELL_TO_SRC = (8, 2)                 # rig cell (48x48) -> source sprite (32x46) origin
AXIS = 27                            # body axis, cell column; the profile is centred on it

# part -> (first row, last row, first col, last col), inclusive, cell coordinates.
# Later entries win where boxes overlap.
BOXES = [
    ("torso",      12, 23, 22, 30),
    ("pelvis",     24, 33, 24, 30),
    ("leg_r",      34, 47, 22, 30),
    ("arm_weapon", 24, 31, 25, 29),
    ("head",        3, 11, 22, 32),
    ("shield",     18, 40, 31, 32),
]


def label(profile: np.ndarray):
    """profile: (H, W, 4) placed so its centre column is AXIS and row 0 is cell row 3."""
    H, W = profile.shape[:2]
    x0 = AXIS - W // 2
    lab = np.full((H, W), "", dtype=object)
    for name, r0, r1, c0, c1 in BOXES:
        for j in range(H):
            for i in range(W):
                y, x = 3 + j, x0 + i
                if r0 <= y <= r1 and c0 <= x <= c1:
                    lab[j, i] = name
    return lab, x0


def make_back_head(out_dir):
    """The head's back view, from edit-krea2 run on the front (see EXPERIMENT_DIFFUSION.md).

    The edit result is the raw pixelized image, aligned to the source exactly like the front
    crop (offset 1,1), with the character's lateral layout NOT yet swapped. It is stored raw
    because the `back` view is mirrored about the body axis at render time, which does the
    swap. Only the skull rows are kept: a skeleton's ribcage from behind is close enough to
    the flipped front, and the head is the giveaway.
    """
    f = ROOT / "data/diffusion/back_s0.8.png"
    if not f.exists():
        print("no back_head source (data/diffusion/back_s0.8.png); skipping")
        return
    crop = np.array(Image.open(f).convert("RGBA"))
    img = np.zeros((46, 32, 4), dtype=np.uint8)
    rows = 9                                  # cell rows 3-11 = crop rows 0-8
    img[1:1 + rows, 1:1 + crop.shape[1]] = crop[:rows]
    Image.fromarray(img, "RGBA").save(out_dir / "back_head.png")
    print("back_head    %3d texels (edit-krea2, strength 0.8)" % int((img[:, :, 3] > 127).sum()))


def main():
    src = np.array(Image.open(ROOT / "data/diffusion/view_2.png").convert("RGBA"))
    op = src[:, :, 3] > 127
    lab, x0 = label(src)
    out_dir = HERE / "views"
    out_dir.mkdir(exist_ok=True)
    ox, oy = CELL_TO_SRC
    parts = sorted({p for p in lab.ravel() if p})
    for name in parts + ["leg_l", "arm_shield"]:
        img = np.zeros((46, 32, 4), dtype=np.uint8)
        n = 0
        for j in range(src.shape[0]):
            for i in range(src.shape[1]):
                if op[j, i] and lab[j, i] == name:
                    x, y = x0 + i - ox, 3 + j - oy
                    if 0 <= x < 32 and 0 <= y < 46:
                        img[y, x] = src[j, i]
                        n += 1
        Image.fromarray(img, "RGBA").save(out_dir / ("side_%s.png" % name))
        print("%-11s %3d texels" % (name, n))
    make_back_head(out_dir)
    unlabelled = int((op & (lab == "")).sum())
    print("profile texels not covered by any box:", unlabelled)


if __name__ == "__main__":
    main()

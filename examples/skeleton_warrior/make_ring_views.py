"""SPIKE. Register the generated skeleton views into the rig's cell, ready to be cut into parts.

Each view (already pixel-corrected, see docs/EXPERIMENT_DIFFUSION.md) is placed into a 48x48
cell image so that

  * its body axis (found by symmetry with the handed items excluded, so the shield cannot pull
    it off the body) lands on the front sprite's own axis, and
  * its lowest opaque row is the ground row (46).

Art from different views then lines up, and a part variant made from one of these images is
placed by the renderer with no offset (a variant the size of the cell is placed at 0,0).

The five unique views: front (the source sprite), 45 (3/4), 90 (side), 135 (rear 3/4, with its
shield and glove moved to the right of the body by `flip_handed`: from behind the shield is on the
viewer's right), and 180 (rear).

    python examples/skeleton_warrior/make_ring_views.py
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "pixelanim"))
import mirrorpatch as mp  # noqa: E402

D = ROOT / "data/diffusion/skel"
C = mp.SHIELD_COLOURS
SRC_OFFSET = (8, 2)          # rig cell -> source sprite origin, as in make_views.py
GROUND_ROW = 46


def core_axis(img: Image.Image) -> float:
    a = np.array(img.convert("RGBA"))
    handed = mp.handed_mask(a, C, 1)
    core = (a[:, :, 3] > 127) & ~handed
    return mp.body_axis(core)


def register(img: Image.Image, axis_target: float) -> Image.Image:
    img = img.convert("RGBA")
    box = img.getbbox()
    crop = img.crop(box)
    ax = core_axis(crop)
    x0 = int(round(axis_target - ax))
    y0 = GROUND_ROW + 1 - crop.height
    cell = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    cell.alpha_composite(crop, (x0, y0))
    return cell


def main():
    front = Image.open(ROOT / "examples/skeleton_warrior/skeleton_warrior.png").convert("RGBA")
    fbox = front.getbbox()
    fcrop = front.crop(fbox)
    axis_front = core_axis(fcrop) + fbox[0] + SRC_OFFSET[0]      # in cell coordinates
    print("front body axis at cell column %.1f" % axis_front)

    q34 = Image.open(D / "px_q34.png")
    qside = Image.open(D / "px_qside.png")
    qr34 = mp.flip_handed(Image.open(D / "px_qrear34.png"), C)[0]
    qrear = Image.open(D / "px_qrear.png")

    out = HERE / "views"
    out.mkdir(exist_ok=True)
    views = {"v0": None, "v45": q34, "v90": qside, "v135": qr34, "v180": qrear}
    cell0 = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    cell0.alpha_composite(front, SRC_OFFSET)
    cell0.save(out / "reg_v0.png")
    for name, img in views.items():
        if img is None:
            continue
        reg = register(img, axis_front)
        reg.save(out / ("reg_%s.png" % name))
        a = np.array(reg)[:, :, 3] > 127
        ys, xs = np.where(a)
        print("%-5s opaque texels %4d  cols %2d-%2d  rows %2d-%2d" % (name, a.sum(), xs.min(), xs.max(), ys.min(), ys.max()))


if __name__ == "__main__":
    main()

"""SPIKE. Derive each part's joint (pivot) in each generated view from its segmentation.

The rig's pivots come from the front sprite: the hips sit at x=31 and x=23. In a profile view
both legs sit on the body axis, so rotating a leg about its front-view hip tears it off the
body. A joint is where a part meets its parent, so in each view it is found where the part's
own texels touch the parent's texels:

  * the centroid of the part's texels that are 8-adjacent to the parent's texels;
  * if they never touch (the shield arm hidden behind a shield), the midpoint of the closest
    pair of texels between the two;
  * if the part has no texels in the view (a leg hidden behind the shield), the front pivot.

Writes views/pivots.json: {view: {part: [x, y]}} in cell coordinates, for the unmirrored view art
(a mirrored view is mirrored after FK, so its pivots need no mirroring).

    python examples/skeleton_warrior/derive_pivots.py
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = Path(__file__).parent
VIEWS = ["v45", "v90", "v135", "v180"]


def mask(view, part):
    f = HERE / "views" / ("%s_%s.png" % (view, part))
    return np.array(Image.open(f).convert("RGBA"))[:, :, 3] > 127


def main():
    rig = json.loads((HERE / "rig.json").read_text(encoding="utf-8"))
    parts = {p["name"]: p for p in rig["parts"]}
    out = {}
    for view in VIEWS:
        piv = {}
        for name, p in parts.items():
            m = mask(view, name)
            parent = p.get("parent")
            if not m.any():
                piv[name] = list(p["pivot"])
                note = "front pivot (no texels)"
            elif not parent:
                ys, xs = np.where(m)
                piv[name] = [float(xs.mean()) + 0.5, float(ys.mean()) + 0.5]
                note = "root: centroid"
            else:
                pm = mask(view, parent)
                touch = m & ndimage.binary_dilation(pm, structure=np.ones((3, 3)))
                if touch.any():
                    # the contact can run along a long edge (a leg against the pelvis); the joint
                    # is at the contact point nearest the parent's centre, not the middle of the edge
                    ys, xs = np.where(touch)
                    pcy, pcx = np.where(pm)
                    d = (xs - pcx.mean()) ** 2 + (ys - pcy.mean()) ** 2
                    near = d <= d.min() + 2.0
                    piv[name] = [float(xs[near].mean()) + 0.5, float(ys[near].mean()) + 0.5]
                    note = "touching parent (nearest its centre)"
                elif pm.any():
                    cy, cx = np.where(m)
                    py, px = np.where(pm)
                    d = (cx[:, None] - px[None, :]) ** 2 + (cy[:, None] - py[None, :]) ** 2
                    i, j = np.unravel_index(d.argmin(), d.shape)
                    piv[name] = [(cx[i] + px[j]) / 2.0 + 0.5, (cy[i] + py[j]) / 2.0 + 0.5]
                    note = "closest pair"
                else:
                    piv[name] = list(p["pivot"])
                    note = "front pivot (parent empty)"
            print("%-5s %-11s pivot (%5.1f,%5.1f)  front (%2d,%2d)  %s" % (
                view, name, piv[name][0], piv[name][1], p["pivot"][0], p["pivot"][1], note))
        out[view] = piv
    (HERE / "views" / "pivots.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

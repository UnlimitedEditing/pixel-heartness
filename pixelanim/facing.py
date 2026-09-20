"""How front-on is this image? A cheap classifier for choosing the anchor view of a ring.

Generated entities arrive front-facing, already three-quarter, or in profile, and the
turnaround pipeline needs to know which views it already has. A front or rear view is
close to left-right symmetric; a 3/4 or side view is not. So: take the silhouette,
mirror it about the vertical axis that maximises overlap, and score the overlap.

    python pixelanim/facing.py image.png [image2.png ...]

The score is the mask's intersection-over-union with its own mirror, searched over axis
position. It is silhouette-only on purpose: colour and shading differ between the two
sides of a real subject (a skeleton's shield, a boar's lit side) and would only add noise.

It says *symmetric or not*, which is not the same as *front or back*: a front and a rear
view both score high. Telling those apart needs the interior (a face), not the outline.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from pixelize import background_mask


def silhouette(img: Image.Image) -> np.ndarray:
    if img.mode == "RGBA":
        a = np.array(img)[:, :, 3] > 127
    else:
        a = ~background_mask(np.array(img.convert("RGB")))
    ys, xs = np.where(a)
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def symmetry(mask: np.ndarray) -> tuple[float, float]:
    """Best IoU of the mask with its mirror, and the axis (0..1 across the box) that gave it."""
    H, W = mask.shape
    best = (0.0, 0.5)
    for shift in range(-W // 4, W // 4 + 1):
        pad = W // 2 + abs(shift) + 2
        m = np.pad(mask, ((0, 0), (pad, pad)))
        # mirror about the column at centre + shift/2
        flipped = m[:, ::-1]
        f = np.roll(flipped, shift, axis=1)
        inter = (m & f).sum()
        union = (m | f).sum()
        iou = inter / union if union else 0.0
        if iou > best[0]:
            best = (float(iou), 0.5 + shift / (2.0 * W))
    return best


def classify(score: float) -> str:
    if score >= 0.85:
        return "symmetric (front or rear)"
    if score >= 0.70:
        return "roughly symmetric (front/rear with an asymmetric item, or a slight turn)"
    return "asymmetric (three-quarter or side)"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", type=Path)
    args = ap.parse_args()
    for p in args.images:
        s, axis = symmetry(silhouette(Image.open(p)))
        print("%-46s symmetry %.2f  axis %.2f  -> %s" % (p.name[:46], s, axis, classify(s)))


if __name__ == "__main__":
    main()

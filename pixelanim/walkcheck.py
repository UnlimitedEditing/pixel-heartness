"""Are independently generated frames of one character consistent enough to be a cycle?

A walk cycle only works if its frames look like the same character at the same scale. Frames
that come from separate diffusion generations can each look fine and still not agree, so this
measures the disagreement instead of judging each frame alone.

    python pixelanim/walkcheck.py reference.png frame1.png frame2.png ...

For each frame (all already pixel-corrected on the reference's palette and scale):
  * height and width in texels, and the drift of each from the reference's
  * colour mix: the L1 distance between the frame's palette shares and the reference's (0 =
    the same proportions of every colour, 2 = nothing in common). Identity drift shows up here
    first: a skull that loses its shading, a shield that grows or shrinks
  * shield size: texels in the red-shield family, compared with the reference
  * feet: the lowest opaque row, and whether it is shared by all the frames
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

RED = [(97, 23, 25), (123, 34, 41), (154, 67, 33), (209, 76, 36), (241, 186, 76)]


def stats(img: Image.Image, pal: np.ndarray):
    a = np.array(img.convert("RGBA"))
    op = a[:, :, 3] > 127
    ys, xs = np.where(op)
    rgb = a[:, :, :3][op]
    d = ((rgb[:, None, :].astype(np.int32) - pal[None].astype(np.int32)) ** 2).sum(axis=2)
    share = np.bincount(d.argmin(axis=1), minlength=len(pal)).astype(np.float64)
    share /= max(share.sum(), 1.0)
    red = np.zeros(op.shape, dtype=bool)
    for c in RED:
        red |= (a[:, :, :3] == np.array(c, dtype=np.uint8)).all(axis=2) & op
    return dict(h=int(ys.max() - ys.min() + 1), w=int(xs.max() - xs.min() + 1), n=int(op.sum()),
                share=share, shield=int(red.sum()), foot=int(ys.max()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference", type=Path)
    ap.add_argument("frames", nargs="+", type=Path)
    args = ap.parse_args()
    ref_img = Image.open(args.reference)
    ra = np.array(ref_img.convert("RGBA"))
    pal = np.unique(ra[:, :, :3][ra[:, :, 3] > 127].reshape(-1, 3), axis=0)
    ref = stats(ref_img, pal)
    print("reference: %dx%d texels, %d opaque, shield %d" % (ref["w"], ref["h"], ref["n"], ref["shield"]))
    print("%-22s %7s %7s %7s %9s %9s" % ("frame", "w x h", "dh", "n", "colour L1", "shield"))
    for p in args.frames:
        s = stats(Image.open(p), pal)
        l1 = float(np.abs(s["share"] - ref["share"]).sum())
        print("%-22s %3dx%-3d %+7d %7d %9.2f %5d (%+.0f%%)" % (
            p.name[:22], s["w"], s["h"], s["h"] - ref["h"], s["n"], l1, s["shield"],
            100.0 * (s["shield"] - ref["shield"]) / max(ref["shield"], 1)))


if __name__ == "__main__":
    main()

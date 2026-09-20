"""Mirror a view without swapping its handed items.

A turntable is built from a few generated views plus their mirror images. A plain mirror is
wrong for a subject that carries something on one side: a shield on the left arm ends up on
the right, and the two halves of the ring disagree about which hand holds what. The fix is
the "skim and flip": lift the handed items off, mirror everything else about the body's own
axis, and put the items back where they were, unmirrored.

    python pixelanim/mirrorpatch.py view.png --colours "209,76,36;123,34,41;..." [--out mirrored.png]

  1. skim: pixels of the given colours (the shield, the glove) plus a 1-texel ring around them
     (their outline) are the handed items
  2. axis: the vertical axis that maximises the silhouette's mirror overlap *with the handed
     items removed*, so a large shield cannot drag the axis off the body
  3. mirror the rest about that axis
  4. set the handed items back, unmirrored, at their original positions

The handed items are then in the same place in the mirrored view as in the original, which is
the convention this pipeline's generators already follow (the shield stays on the viewer's
left in every view they produce), so the two halves of the ring agree.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def handed_mask(rgba: np.ndarray, colours, ring: int = 1) -> np.ndarray:
    a = rgba[:, :, 3] > 127
    m = np.zeros(a.shape, dtype=bool)
    for c in colours:
        m |= (rgba[:, :, :3] == np.array(c, dtype=np.uint8)).all(axis=2) & a
    if ring:
        m = ndimage.binary_dilation(m, structure=np.ones((3, 3)), iterations=ring) & a
    return m


def body_axis(core: np.ndarray) -> float:
    """Column coordinate (texel edges, so 0..W) of the mirror axis that best maps `core` onto
    itself. Searched in half-texel steps."""
    H, W = core.shape
    best, axis = -1.0, W / 2.0
    for a2 in range(W // 2, W + W // 2 + 1):          # axis * 2, in half-texels
        ax = a2 / 2.0
        xs = np.arange(W)
        src = np.round(2 * ax - xs - 1).astype(int)   # texel x -> mirrored texel index
        ok = (src >= 0) & (src < W)
        mir = np.zeros_like(core)
        mir[:, xs[ok]] = core[:, src[ok]]
        inter, union = (core & mir).sum(), (core | mir).sum()
        iou = inter / union if union else 0.0
        if iou > best:
            best, axis = iou, ax
    return axis


def mirror_patched(sprite: Image.Image, colours, ring: int = 1, axis: float | None = None,
                   fill_holes: bool = True):
    """Returns (mirrored sprite, the axis used). Canvas is widened so nothing is clipped."""
    a = np.array(sprite.convert("RGBA"))
    H, W = a.shape[:2]
    handed = handed_mask(a, colours, ring)
    core = (a[:, :, 3] > 127) & ~handed
    ax = body_axis(core) if axis is None else axis
    pad = int(np.ceil(abs(W - 2 * ax))) + 2
    left = pad if ax < W / 2 else 0
    canvas = np.zeros((H, W + pad, 4), dtype=np.uint8)
    canvas[:, left:left + W] = a
    ax_c = ax + left
    Wc = canvas.shape[1]
    out = np.zeros_like(canvas)
    xs = np.arange(Wc)
    src = np.round(2 * ax_c - xs - 1).astype(int)
    ok = (src >= 0) & (src < Wc)
    coremask = np.zeros((H, Wc), dtype=bool)
    coremask[:, left:left + W] = core
    for x_dst, x_src in zip(xs[ok], src[ok]):          # mirror the core only
        col = canvas[:, x_src]
        keep = coremask[:, x_src]
        out[keep, x_dst] = col[keep]
    # What was hidden behind a handed item in the original (the far leg behind a shield) does
    # not exist to be mirrored, so the mirrored core has holes there. Fill each hole from the
    # original body at the same position: a leg is a leg, and it is the underlap problem again.
    # Only holes inside the mirrored shadow of a handed item: filling every empty position drew
    # the unmirrored skull over the mirrored one (a two-faced skull).
    if fill_holes:
        hm0 = np.zeros((H, Wc), dtype=bool)
        hm0[:, left:left + W] = handed
        shadow = np.zeros_like(hm0)                    # where the mirrored handed items would fall
        shadow[:, xs[ok]] = hm0[:, src[ok]]
        empty = (out[:, :, 3] == 0) & coremask & shadow
        out[empty] = canvas[empty]
    hm = np.zeros((H, Wc), dtype=bool)
    hm[:, left:left + W] = handed
    out[hm] = canvas[hm]                                # handed items back, unmirrored
    return Image.fromarray(out, "RGBA"), ax


def flip_handed(sprite: Image.Image, colours, ring: int = 1, axis: float | None = None):
    """The inverse of `mirror_patched`: keep the body as it is and move only the handed items
    to the other side of the body axis, mirrored. For a view that is right about its body but
    wrong about which side the shield is on (a rear three-quarter that leaves the shield on the
    viewer's left when, from behind, it belongs on the right). The place the items vacate is
    filled from the mirrored body, the same underlap idea as elsewhere."""
    a = np.array(sprite.convert("RGBA"))
    H, W = a.shape[:2]
    handed = handed_mask(a, colours, ring)
    core = (a[:, :, 3] > 127) & ~handed
    ax = body_axis(core) if axis is None else axis
    pad = int(np.ceil(abs(W - 2 * ax))) + 2
    left = pad if ax < W / 2 else 0
    canvas = np.zeros((H, W + pad, 4), dtype=np.uint8)
    canvas[:, left:left + W] = a
    Wc = canvas.shape[1]
    ax_c = ax + left
    hm = np.zeros((H, Wc), dtype=bool); hm[:, left:left + W] = handed
    cm = np.zeros((H, Wc), dtype=bool); cm[:, left:left + W] = core
    xs = np.arange(Wc)
    src = np.round(2 * ax_c - xs - 1).astype(int)
    ok = (src >= 0) & (src < Wc)
    out = np.zeros_like(canvas)
    out[cm] = canvas[cm]                                     # the body, untouched
    mir_core = np.zeros_like(canvas); mir_core_m = np.zeros_like(cm)
    mir_core[:, xs[ok]] = canvas[:, src[ok]] * cm[:, src[ok], None]
    mir_core_m[:, xs[ok]] = cm[:, src[ok]]
    vacated = hm & ~cm & mir_core_m                          # where the items were: show body
    out[vacated] = mir_core[vacated]
    mh = np.zeros_like(cm); mh[:, xs[ok]] = hm[:, src[ok]]   # where the items land
    mirrored_items = np.zeros_like(canvas); mirrored_items[:, xs[ok]] = canvas[:, src[ok]]
    out[mh] = mirrored_items[mh]
    return Image.fromarray(out, "RGBA"), ax


SHIELD_COLOURS = [(97, 23, 25), (123, 34, 41), (154, 67, 33), (209, 76, 36), (241, 186, 76)]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--colours", default=None, help="R,G,B;R,G,B;... the handed items' colours "
                                                    "(default: the skeleton's shield family)")
    ap.add_argument("--ring", type=int, default=1)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    cols = SHIELD_COLOURS if not args.colours else [tuple(int(v) for v in t.split(",")) for t in args.colours.split(";")]
    img, ax = mirror_patched(Image.open(args.image), cols, args.ring)
    print("body axis at column %.1f; wrote %dx%d" % (ax, img.width, img.height))
    if args.out:
        img.save(args.out)


if __name__ == "__main__":
    main()

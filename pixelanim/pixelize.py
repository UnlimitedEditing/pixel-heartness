"""Turn a diffusion output back into real pixel art on the source sprite's grid.

A diffusion model asked for a turnaround returns a large, soft, uneven-grid image.
Nothing it produces is trustworthy at the texel level, so this step is deterministic
and does all the correcting: it never *adds* detail, it only decides, per texel,
which of the source palette's colours the image is closest to.

    python pixelanim/pixelize.py <output.png> <source_sprite.png> [--texel-from front.png]
                                 [--out out.png] [--report]

  1. background: near-white connected to the border becomes transparent (flood fill,
     so a white highlight inside the figure survives)
  2. scale: texel size in pixels = figure height / source content height. Taken from
     `--texel-from` (the front view of the same run, where the answer is known) so
     every view of one run shares one scale
  3. grid: the offset that minimises colour variance inside cells wins; diffusion
     output is not aligned to any grid
  4. per cell: majority palette colour (colours snapped to the source palette first),
     transparent if most of the cell is background
  5. binary alpha, like every other sprite here

`--report` on a view whose true answer is known (the front) prints how many texels
match it, which is the honest measure of how far the correction can be trusted.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def palette_of(sprite: Image.Image) -> np.ndarray:
    a = np.array(sprite.convert("RGBA"))
    op = a[:, :, 3] > 127
    return np.unique(a[:, :, :3][op].reshape(-1, 3), axis=0)


def background_mask(rgb: np.ndarray, thr: int = 235, speck: int = 150) -> np.ndarray:
    """True where the pixel is background: near-white and connected to the border.

    The near-white test runs on a lightly smoothed image, so noise on the white
    does not read as figure, and foreground specks under `speck` pixels are
    dropped, so a stray artefact cannot stretch the figure's bounding box."""
    sm = ndimage.uniform_filter(rgb.min(axis=2).astype(np.float32), size=5)
    near = sm >= thr - 6
    lab, _ = ndimage.label(near)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(border))
    fg, n = ndimage.label(~bg)
    if n:
        sizes = ndimage.sum(np.ones_like(fg), fg, index=np.arange(1, n + 1))
        for k in np.where(sizes < speck)[0]:
            bg[fg == k + 1] = True
    return bg


def derive_palette(img: Image.Image, bg: np.ndarray, colours: int,
                   far: float = 45.0, min_px: int = 120, extra: int = 4) -> np.ndarray:
    """A palette of `colours` taken from the figure itself, for when there is no source sprite.

    Median cut finds the dominant colours and merges a rare one into its neighbour, which
    is exactly wrong for the accents that matter most in a sprite: a pink snout, an eye
    highlight, a gem. So after the median cut, any group of at least `min_px` pixels sitting
    more than `far` (RGB distance) from every palette colour is clustered and added back,
    up to `extra` more colours. Background pixels are ignored."""
    rgb = np.array(img.convert("RGB"))
    fig = rgb[~bg]
    strip = Image.fromarray(fig.reshape(1, -1, 3).astype(np.uint8), "RGB")
    q = strip.quantize(colors=colours, method=Image.Quantize.MEDIANCUT)
    pal = np.array(q.getpalette()[:colours * 3], dtype=np.uint8).reshape(-1, 3)[np.unique(np.array(q).ravel())]
    d = np.sqrt(((fig[:, None, :].astype(np.float32) - pal[None].astype(np.float32)) ** 2).sum(axis=2)).min(axis=1)
    out = fig[d > far]
    if len(out) >= min_px:
        s2 = Image.fromarray(out.reshape(1, -1, 3).astype(np.uint8), "RGB")
        q2 = s2.quantize(colors=extra, method=Image.Quantize.MEDIANCUT)
        p2 = np.array(q2.getpalette()[:extra * 3], dtype=np.uint8).reshape(-1, 3)
        idx2 = np.array(q2).ravel()
        for k in np.unique(idx2):
            if (idx2 == k).sum() >= min_px:
                pal = np.vstack([pal, p2[k]])
    return pal


def estimate_texel(img: Image.Image, bg: np.ndarray, lo: int = 5, hi: int = 48) -> float:
    """The pixel period of a diffusion 'pixel art' image, from its own edges.

    Pixel blocks change colour only at block boundaries, so the column and row
    gradient profiles are periodic with the texel size. The autocorrelation of the
    profile peaks at that period; the strongest peak within [lo, hi] wins, and the
    two axes are averaged. (Purity of cells cannot pick the size by itself: it is
    trivially best at 1 px, which is why the search elsewhere is only a refinement.)"""
    g = np.array(img.convert("L"), dtype=np.float32)
    ys, xs = np.where(~bg)
    g = g[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    periods = []
    for axis in (0, 1):
        d = np.abs(np.diff(g, axis=axis)).sum(axis=1 - axis)
        d = d - d.mean()
        ac = np.correlate(d, d, mode="full")[len(d) - 1:]
        ac = ac / max(ac[0], 1e-9)
        best = max(range(lo, min(hi, len(ac) - 2)), key=lambda k: ac[k] - 0.5 * (ac[k - 1] + ac[k + 1]) * 0.0 + ac[k])
        # prefer the fundamental over its multiples: the smallest lag within 10% of the peak height
        peak = ac[best]
        for k in range(lo, best):
            if ac[k] >= 0.9 * peak and ac[k] >= ac[k - 1] and ac[k] >= ac[k + 1]:
                best = k
                break
        periods.append(float(best))
    return float(np.mean(periods))


def snap(rgb: np.ndarray, pal: np.ndarray) -> np.ndarray:
    """Index of the nearest palette colour per pixel (plain RGB distance)."""
    flat = rgb.reshape(-1, 3).astype(np.int32)
    d = ((flat[:, None, :] - pal[None, :, :].astype(np.int32)) ** 2).sum(axis=2)
    return d.argmin(axis=1).reshape(rgb.shape[:2])


def figure_box(bg: np.ndarray):
    ys, xs = np.where(~bg)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def texel_size(img: Image.Image, src: Image.Image) -> float:
    rgb = np.array(img.convert("RGB"))
    x0, y0, x1, y1 = figure_box(background_mask(rgb))
    a = np.array(src.convert("RGBA"))[:, :, 3] > 127
    rows = np.where(a.any(axis=1))[0]
    return (y1 - y0) / float(rows.max() - rows.min() + 1)


def _cell_votes(tables, xs, ys):
    """Per-cell colour counts from integral images. tables: (K, H+1, W+1);
    xs, ys: cell boundaries in pixels (ints). Returns counts (K, rows, cols)."""
    Hh, Ww = tables.shape[1] - 1, tables.shape[2] - 1
    xs = np.clip(xs, 0, Ww)
    ys = np.clip(ys, 0, Hh)
    y0, y1 = ys[:-1][:, None], ys[1:][:, None]
    x0, x1 = xs[:-1][None, :], xs[1:][None, :]
    return (tables[:, y1, x1] - tables[:, y0, x1] - tables[:, y1, x0] + tables[:, y0, x0])


def pixelize(img: Image.Image, src, texel: float, refine: float = 0.05, palette=None):
    """Returns an RGBA sprite on the texel grid, with its palette taken from `src`.

    The texel size is a starting point, not an answer: half a pixel of error per
    texel accumulates across a 46-texel figure until the grid no longer lines up
    (a 23 px texel estimated at 22.5 recovered 2% of the sprite). So size and
    offset are searched together for the grid whose cells are purest -- most of
    each cell agreeing on one palette colour -- within `refine` of the estimate."""
    rgb = np.array(img.convert("RGB"))
    bg = background_mask(rgb)
    pal = palette if palette is not None else palette_of(src)
    x0, y0, x1, y1 = figure_box(bg)
    idx = snap(rgb, pal)
    K = len(pal)
    idx[bg] = K                                   # background is its own class
    onehot = np.zeros((K + 1,) + idx.shape, dtype=np.int32)
    for k in range(K + 1):
        onehot[k] = (idx == k)
    tables = np.zeros((K + 1, idx.shape[0] + 1, idx.shape[1] + 1), dtype=np.int64)
    tables[:, 1:, 1:] = onehot.cumsum(axis=1).cumsum(axis=2)

    best = None
    for t in np.linspace(texel * (1 - refine), texel * (1 + refine), 21):
        W = int(round((x1 - x0) / t)) + 1
        H = int(round((y1 - y0) / t)) + 1
        for oy in np.linspace(0, t, max(3, int(t) // 2), endpoint=False):
            ys = np.round(y0 + np.arange(H + 1) * t - oy).astype(int)
            for ox in np.linspace(0, t, max(3, int(t) // 2), endpoint=False):
                xs = np.round(x0 + np.arange(W + 1) * t - ox).astype(int)
                c = _cell_votes(tables, xs, ys)
                tot = c.sum(axis=0)
                top = c.max(axis=0)
                pur = 1.0 - top[tot > 0] / tot[tot > 0]
                score = float(pur.mean())           # mean impurity: comparable across sizes
                if best is None or score < best[0]:
                    best = (score, c.argmax(axis=0), tot, t)
    _, arg, tot, t = best
    out = np.where((tot > 0) & (arg < K), arg, -1)
    H, W = out.shape
    sprite = np.zeros((H, W, 4), dtype=np.uint8)
    solid = out >= 0
    sprite[solid, :3] = pal[out[solid]]
    sprite[solid, 3] = 255
    pixelize.last_texel = float(t)
    return Image.fromarray(sprite, "RGBA")


def compare(a: Image.Image, b: Image.Image):
    """Best whole-texel overlay of two sprites: returns (matching, total, dx, dy)
    where `total` counts texels opaque in either. Slides `a` over `b` by up to 3."""
    A, B = np.array(a.convert("RGBA")), np.array(b.convert("RGBA"))
    H = max(A.shape[0], B.shape[0]) + 8
    W = max(A.shape[1], B.shape[1]) + 8
    def put(X, dx, dy):
        c = np.zeros((H, W, 4), dtype=np.uint8)
        c[4 + dy:4 + dy + X.shape[0], 4 + dx:4 + dx + X.shape[1]] = X
        return c
    Bc = put(B, 0, 0)
    best = None
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            Ac = put(A, dx, dy)
            oa, ob = Ac[:, :, 3] > 127, Bc[:, :, 3] > 127
            same = oa & ob & (Ac[:, :, :3] == Bc[:, :, :3]).all(axis=2)
            tot = int((oa | ob).sum())
            m = int(same.sum())
            if best is None or m > best[0]:
                best = (m, tot, dx, dy)
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("source", type=Path, nargs="?", default=None,
                    help="the original sprite, for its palette and height; omit with --auto")
    ap.add_argument("--height", type=int, default=None, metavar="TEXELS",
                    help="with --auto: force the sprite to this many texels tall, whatever the image's "
                         "own pixel size, so every view of a ring shares one scale")
    ap.add_argument("--palette-from", type=Path, default=None, metavar="IMAGE",
                    help="with --auto: take the palette from this image (the anchor view) so every view "
                         "of a ring shares one palette")
    ap.add_argument("--auto", type=int, default=None, metavar="COLOURS",
                    help="no source sprite: derive a palette of this many colours from the image "
                         "and find the pixel period from its edges")
    ap.add_argument("--texel-from", type=Path, default=None,
                    help="another output of the same run whose height fixes the texel size")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--report", action="store_true",
                    help="compare against the source sprite (only meaningful for the front view)")
    args = ap.parse_args()
    if args.auto:
        img = Image.open(args.image)
        bg = background_mask(np.array(img.convert("RGB")))
        if args.palette_from:
            pimg = Image.open(args.palette_from)
            pal = derive_palette(pimg, background_mask(np.array(pimg.convert("RGB"))), args.auto)
        else:
            pal = derive_palette(img, bg, args.auto)
        if args.height:
            x0, y0, x1, y1 = figure_box(bg)
            t = (y1 - y0) / float(args.height)
            refine = 0.02                 # the size is imposed, not estimated: only fine-tune
            print("auto: %d-colour palette, forced %d texels tall = %.1f px per texel" % (len(pal), args.height, t))
        else:
            t = estimate_texel(img, bg)
            refine = 0.08
            print("auto: %d-colour palette, texel period %.1f px" % (len(pal), t))
        sprite = pixelize(img, None, t, refine=refine, palette=pal)
    else:
        if args.source is None:
            raise SystemExit("pixelize: give the source sprite, or use --auto COLOURS")
        src = Image.open(args.source)
        ref = Image.open(args.texel_from or args.image)
        t = texel_size(ref, src)
        sprite = pixelize(Image.open(args.image), src, t)
    print("texel estimate %.2f px -> refined %.2f px, result %dx%d"
          % (t, pixelize.last_texel, sprite.width, sprite.height))
    if args.out:
        sprite.save(args.out)
        print("wrote", args.out)
    if args.report and not args.auto:
        m, tot, dx, dy = compare(sprite, src)
        print("matches the source sprite on %d of %d texels (%.1f%%) after a shift of (%d,%d)"
              % (m, tot, 100.0 * m / tot, dx, dy))


if __name__ == "__main__":
    main()

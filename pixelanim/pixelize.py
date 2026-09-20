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
    # The anti-aliased fringe of a silhouette is a thin band of near-white that the threshold
    # above just misses. Left in, it snaps to the palette's white and, with rare colours
    # boosted, wins the edge cells as white specks. So near-white pixels touching the
    # background, within 3 px, are background too.
    fringe = ndimage.binary_dilation(bg, iterations=3) & (rgb.min(axis=2) >= 205)
    bg = bg | fringe
    fg, n = ndimage.label(~bg)
    if n:
        sizes = ndimage.sum(np.ones_like(fg), fg, index=np.arange(1, n + 1))
        for k in np.where(sizes < speck)[0]:
            bg[fg == k + 1] = True
    return bg


def derive_palette_multi(paths, colours: int, **kw) -> np.ndarray:
    """One palette from several views at once. A colour that is tiny in one view (the pink
    snout seen from three-quarters) can be large in another (seen head-on), so deriving from
    the union keeps it. Views are stacked side by side and quantised together."""
    tiles, masks = [], []
    for path in paths:
        im = Image.open(path).convert("RGB")
        bg = background_mask(np.array(im))
        tiles.append(np.array(im))
        masks.append(bg)
    H = max(t.shape[0] for t in tiles)
    pad = lambda a, v: np.pad(a, ((0, H - a.shape[0]), (0, 0)) + ((0, 0),) * (a.ndim - 2), constant_values=v)
    big = np.hstack([pad(t, 255) for t in tiles])
    bgm = np.hstack([pad(m, True) for m in masks])
    return derive_palette(Image.fromarray(big, "RGB"), bgm, colours, **kw)


def derive_palette(img: Image.Image, bg: np.ndarray, colours: int, min_share: float = 0.0004,
                   sep: float = 17.0, **_ignored) -> np.ndarray:
    """A palette of up to `colours` flat colours taken from the figure itself.

    Pixel art is made of flat colours, so the palette should be its most common *exact*
    colours, not means. Median cut averages a saturated salmon snout together with the dark
    pixels of the nostrils and outline and returns a dusty blend that is in none of the
    pixels. Here the figure's pixels are histogrammed (4-bit per channel), and modes are
    picked most-common first, skipping any mode within `sep` (RGB distance) of one already
    picked, until `colours` are chosen or a mode falls under `min_share` of the figure. Each
    pick is then refined to the mean of the raw pixels within `sep / 2` of it, which stays on
    the flat colour because the neighbourhood is that colour plus its anti-aliasing."""
    rgb = np.array(img.convert("RGB"))
    fig = rgb[~bg].astype(np.int32)
    q = (fig // 8) * 8 + 4
    keys = (q[:, 0] << 16) | (q[:, 1] << 8) | q[:, 2]
    vals, cnt = np.unique(keys, return_counts=True)
    order = np.argsort(-cnt)
    picked = []
    for i in order:
        if cnt[i] < min_share * len(fig) or len(picked) >= colours:
            break
        c = np.array([(vals[i] >> 16) & 255, (vals[i] >> 8) & 255, vals[i] & 255], dtype=np.float32)
        if all(np.linalg.norm(c - p) > sep for p in picked):
            picked.append(c)
    pal = []
    for c in picked:
        near = fig[np.linalg.norm(fig.astype(np.float32) - c, axis=1) <= sep / 2]
        pal.append(near.mean(axis=0) if len(near) else c)
    return np.round(np.array(pal)).astype(np.uint8)


def merge_close(pal: np.ndarray, fig: np.ndarray, dist: float = 13.0) -> np.ndarray:
    """Drop palette colours that are practically another palette colour. Median cut happily
    keeps three near-blacks (7,0,3), (2,1,2), (10,4,9), which splits an outline between them
    and makes it ragged. Colours are visited most-used first; one is kept only if it is more
    than `dist` (RGB distance) from every colour already kept."""
    d = np.sqrt(((fig[:, None, :].astype(np.float32) - pal[None].astype(np.float32)) ** 2).sum(axis=2))
    counts = np.bincount(d.argmin(axis=1), minlength=len(pal))
    kept = []
    for k in np.argsort(-counts):
        if all(np.linalg.norm(pal[k].astype(np.float32) - pal[j].astype(np.float32)) > dist for j in kept):
            kept.append(k)
    return pal[sorted(kept)]


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


def pixelize(img: Image.Image, src, texel: float, refine: float = 0.05, palette=None,
             preserve: float = 0.0, outline_boost: float = 2.0, restore: float = 0.0,
             restore_colours=None):
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
                    best = (score, c, tot, t, xs.copy(), ys.copy())
    _, c, tot, t, gx, gy = best
    pixelize.last_grid = (gx, gy)
    # Plain majority voting loses whatever is thin or small: a 1-texel outline is often under
    # half of its cell, a specular highlight is outvoted by the pupil round it, a pink snout by
    # the tan beside it. `preserve` boosts rare colours (weight = share ** -preserve) and the
    # darkest colour (the outline) is boosted again, so they win a cell when they cover a
    # fair fraction of it instead of only when they cover most of it.
    w = np.ones(K + 1, dtype=np.float64)
    if preserve > 0:
        share = np.array([(idx == k).sum() for k in range(K)], dtype=np.float64)
        share = np.maximum(share, 1.0) / max(share.sum(), 1.0)
        w[:K] = share ** -preserve
        w[:K] /= w[:K].min()
        dark = int(np.argmin(pal.astype(np.int32).sum(axis=1)))
        w[dark] *= outline_boost
    arg = (c * w[:, None, None]).argmax(axis=0)
    out = np.where((tot > 0) & (arg < K), arg, -1)
    if restore > 0:
        for (i, j, k, f, chosen) in missed_features(idx, K, out, (gx, gy), frac=restore):
            if restore_colours is not None and k not in restore_colours:
                continue
            # a glint or an accent is inside the figure. Next to the background, a light
            # "rare" colour is just the anti-aliased fringe of the silhouette: skip it.
            nb = out[max(j - 1, 0):j + 2, max(i - 1, 0):i + 2]
            edge = (j == 0 or i == 0 or j == out.shape[0] - 1 or i == out.shape[1] - 1
                    or (nb < 0).any() or out[j, i] < 0)
            if not edge:
                out[j, i] = k
    pixelize.last_index = out.copy()
    H, W = out.shape
    sprite = np.zeros((H, W, 4), dtype=np.uint8)
    solid = out >= 0
    sprite[solid, :3] = pal[out[solid]]
    sprite[solid, 3] = 255
    pixelize.last_texel = float(t)
    pixelize.last_raw_idx = (idx, K)
    return Image.fromarray(sprite, "RGBA")


def missed_features(raw_idx: np.ndarray, K: int, out_idx: np.ndarray, grid, rare: float = 0.04,
                    frac: float = 0.18):
    """The comparison sweep: cells where a *rare* colour covered a fair fraction of the cell in
    the raw image but the corrected sprite shows something else. These are the eye glints, the
    pink snout, the chipped outlines. Returns [(col, row, colour_index, fraction, chosen)]."""
    gx, gy = grid
    fig = raw_idx[raw_idx < K]
    share = np.bincount(fig, minlength=K).astype(np.float64) / max(len(fig), 1)
    dark = None
    rows, cols = out_idx.shape
    found = []
    for j in range(min(rows, len(gy) - 1)):
        y0, y1 = max(gy[j], 0), max(gy[j + 1], 0)
        for i in range(min(cols, len(gx) - 1)):
            x0, x1 = max(gx[i], 0), max(gx[i + 1], 0)
            blk = raw_idx[y0:y1, x0:x1].ravel()
            if not blk.size:
                continue
            cnt = np.bincount(blk, minlength=K + 1)
            for k in range(K):
                f = cnt[k] / blk.size
                if f >= frac and share[k] <= rare and out_idx[j, i] != k:
                    found.append((i, j, k, float(f), int(out_idx[j, i])))
    return sorted(found, key=lambda t: -t[3])


def representation(sprite: Image.Image, pal: np.ndarray, raw_idx: np.ndarray, K: int):
    """For each palette colour, how much of the figure it makes up in the corrected sprite
    against in the raw image (ratio of shares). A colour that shrinks a lot was lost by the
    correction: thin outlines, small highlights and rare accents all show up here."""
    a = np.array(sprite)
    op = a[:, :, 3] > 127
    out_share = np.zeros(K)
    for k in range(K):
        out_share[k] = ((a[:, :, :3] == pal[k]).all(axis=2) & op).sum()
    out_share /= max(out_share.sum(), 1.0)
    fig = raw_idx[raw_idx < K]
    raw_share = np.bincount(fig, minlength=K).astype(np.float64) / max(len(fig), 1)
    ratio = np.where(raw_share > 0, out_share / np.maximum(raw_share, 1e-9), 1.0)
    return ratio, raw_share


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
    ap.add_argument("--restore", type=float, default=0.0, metavar="FRAC",
                    help="with --auto: automatically restore any rare colour that covered at least this "
                         "fraction of a cell in the raw image (0.2 is a fair start); blunt, so review it")
    ap.add_argument("--restore-colours", default=None, metavar="R,G,B;R,G,B",
                    help="with --restore: only restore these colours (nearest palette match). Choose the "
                         "accents that matter after reading --sweep: whites, a pink snout, the outline")
    ap.add_argument("--patch", type=Path, default=None,
                    help='JSON list of {"x":, "y":, "colour":[r,g,b] or null} applied last: the '
                         "touch-ups an agent writes after comparing the sprite with the raw image")
    ap.add_argument("--sweep", action="store_true",
                    help="list the cells where a rare colour was present in the raw image but lost")
    ap.add_argument("--palette-also", type=Path, action="append", default=[], metavar="IMAGE",
                    help="with --palette-from: further views to derive the shared palette from")
    ap.add_argument("--preserve", type=float, default=0.0, metavar="GAMMA",
                    help="rarity-weighted voting (0 = plain majority; ~0.4 restores thin "
                         "outlines, small highlights and rare accents)")
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
            pal = derive_palette_multi([args.palette_from] + list(args.palette_also), args.auto)
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
        only = None
        if args.restore_colours:
            only = set()
            for tok in args.restore_colours.split(";"):
                c = np.array([int(v) for v in tok.split(",")], dtype=np.int32)
                only.add(int(((pal.astype(np.int32) - c) ** 2).sum(axis=1).argmin()))
        sprite = pixelize(img, None, t, refine=refine, palette=pal, preserve=args.preserve,
                          restore=args.restore, restore_colours=only)
        idx, K = pixelize.last_raw_idx
        ratio, raw_share = representation(sprite, pal, idx, K)
        lost = [(k, ratio[k], raw_share[k]) for k in range(K) if raw_share[k] >= 0.004 and ratio[k] < 0.7]
        over = [(k, ratio[k], raw_share[k]) for k in range(K) if raw_share[k] >= 0.004 and ratio[k] > 1.5]
        print("representation vs raw: worst under %.2f, worst over %.2f;  %d colours lost, %d inflated"
              % (min([ratio[k] for k in range(K) if raw_share[k] >= 0.004] or [1]),
                 max([ratio[k] for k in range(K) if raw_share[k] >= 0.004] or [1]), len(lost), len(over)))
        if args.sweep:
            for i, j, k, f, chosen in missed_features(idx, K, pixelize.last_index, pixelize.last_grid)[:25]:
                print("    missed:  cell (%2d,%2d) rgb%s is %.0f%% of it, sprite has %s"
                      % (i, j, tuple(int(v) for v in pal[k]), 100 * f,
                         "nothing" if chosen < 0 else "rgb" + str(tuple(int(v) for v in pal[chosen]))))
        if args.patch:
            import json
            arr = np.array(sprite)
            for e in json.loads(args.patch.read_text(encoding="utf-8")):
                x, y, c = int(e["x"]), int(e["y"]), e.get("colour")
                arr[y, x] = [0, 0, 0, 0] if c is None else [c[0], c[1], c[2], 255]
            sprite = Image.fromarray(arr, "RGBA")
        for k, r, s in sorted(lost, key=lambda x: x[1])[:4]:
            print("    lost:    rgb%s kept %.0f%% of its raw share (%.1f%% of the figure)"
                  % (tuple(int(v) for v in pal[k]), 100 * r, 100 * s))
    else:
        if args.source is None:
            raise SystemExit("pixelize: give the source sprite, or use --auto COLOURS")
        src = Image.open(args.source)
        ref = Image.open(args.texel_from or args.image)
        t = texel_size(ref, src)
        if args.height:
            # force the height, whatever the generation drew: a rear 3/4 came out 47 rows tall
            # against a 44-row front, which is invisible until a bob pushes it into the border
            rgb0 = np.array(Image.open(args.image).convert("RGB"))
            bx0, by0, bx1, by1 = figure_box(background_mask(rgb0))
            t = (by1 - by0) / float(args.height)
            print("forced %d texels tall = %.1f px per texel" % (args.height, t))
        # the size is imposed, so only fine-tune it; the default +-5% search re-inflated a forced
        # 44-row sprite back to 47
        sprite = pixelize(Image.open(args.image), src, t, refine=0.01 if args.height else 0.05,
                          preserve=args.preserve)
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

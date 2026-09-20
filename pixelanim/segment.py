"""Cut one flat sprite into parts that can rotate without tearing.

Three stages, each separately inspectable:

  LABEL   every opaque texel is assigned to exactly one part. Colour-weighted
          geodesic growth from rect cores, so a cut follows the colour edge
          between shield and ribs instead of slicing a rectangle through both.

  EXTENT  each part is given a region it is *allowed* to reach into. A part may
          only grow under parts drawn in front of it -- that is what makes the
          growth invisible at rest -- plus, optionally, into the mirror of the
          subject's own silhouette, which is how a body half that was never
          drawn (because a shield covers it) gets reconstructed.

  FILL    the extent minus the label is synthesised from the part's own texels
          by reflection across its boundary, so the palette is closed by
          construction and edge outlines are not smeared outward.

The result is one cell-sized RGBA layer per part plus a `synth` provenance mask,
which render.py transforms in lockstep and checks.py gates.

    python pixelanim/segment.py pixelanim/examples/skeleton_warrior/rig.json --underlap 3
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

import riglib

NEI = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


# ------------------------------------------------------------------ stage 1

def rect_cores(rig, opaque):
    """A part's seed region: the texels its rect claims and no other rect does.

    Falls back progressively, because a rect that is entirely overlapped (the
    torso under a shield) still needs somewhere to start.
    """
    CW, CH = rig.cell
    rects = {}
    for p in rig.parts:
        x, y, w, h = p["rect"]
        m = np.zeros((CH, CW), dtype=bool)
        m[max(0, y):min(CH, y + h), max(0, x):min(CW, x + w)] = True
        rects[p["name"]] = m

    cores, how = {}, {}
    for p in rig.parts:
        n = p["name"]
        if p.get("seeds"):
            m = np.zeros((CH, CW), dtype=bool)
            for sx, sy in p["seeds"]:
                m[sy, sx] = True
            cores[n], how[n] = m & opaque, "seeds"
            continue
        others = np.zeros((CH, CW), dtype=bool)
        for q in rig.parts:
            if q["name"] != n:
                others |= rects[q["name"]]
        exclusive = rects[n] & opaque & ~others
        if exclusive.any():
            cores[n], how[n] = exclusive, "exclusive"
            continue
        infront = np.zeros((CH, CW), dtype=bool)
        for q in rig.parts:
            if rig.z[q["name"]] > rig.z[n]:
                infront |= rects[q["name"]]
        behind_free = rects[n] & opaque & ~infront
        if behind_free.any():
            cores[n], how[n] = behind_free, "not-under-front-rects"
            continue
        if (rects[n] & opaque).any():
            cores[n], how[n] = rects[n] & opaque, "whole-rect"
            continue
        raise SystemExit("segment: part " + n + " rect covers no opaque texel")
    return cores, how


def label_parts(rig, rgba, opaque, colour_lambda):
    """Multi-source Dijkstra over the silhouette. Step cost rises with colour
    difference, so boundaries snap to the colour edges an artist drew."""
    CH, CW = opaque.shape
    names = [p["name"] for p in rig.parts]
    idx = {n: i + 1 for i, n in enumerate(names)}
    cores, how = rect_cores(rig, opaque)

    rgb = rgba[:, :, :3].astype(np.float32)
    lab = np.zeros((CH, CW), dtype=np.int32)
    dist = np.full((CH, CW), np.inf, dtype=np.float64)
    heap = []
    for n in names:
        for y, x in zip(*np.where(cores[n])):
            dist[y, x] = 0.0
            lab[y, x] = idx[n]
            heapq.heappush(heap, (0.0, -rig.z[n], int(y), int(x), idx[n]))

    settled = np.zeros((CH, CW), dtype=bool)
    while heap:
        d, negz, y, x, li = heapq.heappop(heap)
        if settled[y, x]:
            continue
        settled[y, x] = True
        lab[y, x] = li
        for dy, dx in NEI:
            ny, nx = y + dy, x + dx
            if not (0 <= ny < CH and 0 <= nx < CW) or not opaque[ny, nx] or settled[ny, nx]:
                continue
            step = 1.4142135 if dy and dx else 1.0
            cd = float(np.abs(rgb[ny, nx] - rgb[y, x]).max()) / 255.0
            nd = d + step * (1.0 + colour_lambda * cd)
            if nd < dist[ny, nx]:
                dist[ny, nx] = nd
                heapq.heappush(heap, (nd, negz, ny, nx, li))

    # islands the silhouette never connects: fall back to plain nearest part
    orphan = opaque & (lab == 0)
    if orphan.any():
        _, ind = ndimage.distance_transform_edt(lab == 0, return_indices=True)
        lab[orphan] = lab[ind[0][orphan], ind[1][orphan]]

    return lab, idx, how, int(orphan.sum())


# ------------------------------------------------------------------ stage 2

def disc(radius: int) -> np.ndarray:
    r = int(radius)
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (yy * yy + xx * xx) <= (r * r + r)


def required_underlap(rig, lab, idx, part, infront, cap):
    """How far the part behind must reach under each occluding texel.

    The gap that opens at a seam is exactly how far the occluder's material
    drifts away from the material behind it. For an affine rig that is not an
    estimate: at texel t, under pose f, part P sits at `M_P(t)` and the part
    behind sits at `M_Q(t)`, so the cover needed there is
    `max over frames of |M_P(t) - M_Q(t)|`. Computed straight off the rig's own
    pose list, so it needs no tuning and adapts the moment a state is edited.

    This has to be per texel, not per part. A single global radius must satisfy
    the widest gap everywhere, and on `skeleton_warrior` that is self-defeating:
    the radius the sword tip needs is enough for the pelvis to creep six texels
    along that same arm and strand a blob of invented hip texels under the hand.
    """
    CH, CW = lab.shape
    ys, xs = np.mgrid[0:CH, 0:CW]
    ys, xs = ys.astype(np.float64), xs.astype(np.float64)
    need = np.zeros((CH, CW), dtype=np.float64)
    fronts = [q for q in rig.parts if rig.z[q["name"]] > rig.z[part["name"]]]
    for _, _, pose, _, _ in rig.frames():
        cache = {}
        mq = riglib.world_matrix(rig, part["name"], pose, cache)
        for q in fronts:
            m = lab == idx[q["name"]]
            if not m.any():
                continue
            d = riglib.world_matrix(rig, q["name"], pose, cache) - mq
            drift = np.hypot(d[0, 0] * xs + d[0, 1] * ys + d[0, 2],
                             d[1, 0] * xs + d[1, 1] * ys + d[1, 2])
            need[m] = np.maximum(need[m], drift[m])
    need[infront] = np.clip(need[infront] + 1.0, 1.0, cap)  # +1 covers the bare seam
    need[~infront] = 0.0
    return need


def geodesic_grow_to(own: np.ndarray, allowed: np.ndarray, need: np.ndarray,
                     cap: int) -> np.ndarray:
    """Geodesic growth with a per-texel budget: a texel joins the part's extent
    only if it can be reached in at most `need` steps without leaving the body."""
    region = own | allowed
    cur = own.copy()
    got = np.zeros_like(own)
    step = np.ones((3, 3), dtype=bool)
    for k in range(1, int(cap) + 1):
        nxt = ndimage.binary_dilation(cur, structure=step, mask=region)
        new = nxt & ~cur
        if not new.any():
            break
        got |= new & (need >= k)
        cur = nxt
    return got & ~own


def geodesic_grow(own: np.ndarray, allowed: np.ndarray, r: int) -> np.ndarray:
    """Grow `own` by r steps, travelling only through `own | allowed`.

    Plain Euclidean dilation is wrong here and the failure is not subtle: the
    pelvis sits a few texels from the sword arm with bare background between
    them, so a 6-texel disc jumps the gap, lands on the far side, and parks a
    blob of invented hip texels out under the hand. They are hidden at rest, so
    the `rest` gate stays green, and they sit there motionless while the arm
    swings -- exactly the stray-texel artefact this is meant to prevent.

    Growth that has to cross background is never covering a seam, because there
    is no seam there. Constraining propagation to the subject makes the radius
    mean what it is supposed to mean: how far *along the body* a part reaches
    under its neighbour.
    """
    if r <= 0:
        return np.zeros_like(own)
    region = own | allowed
    cur = own.copy()
    step = np.ones((3, 3), dtype=bool)
    for _ in range(int(r)):
        cur = ndimage.binary_dilation(cur, structure=step, mask=region)
    return cur & ~own


def reachable_from(own: np.ndarray, extra: np.ndarray) -> np.ndarray:
    """Keep only the parts of `extra` that connect back to `own`. A mirrored
    limb that lands as a detached island is the same artefact by another route."""
    if not extra.any():
        return extra
    cc, n = ndimage.label(own | extra, structure=np.ones((3, 3), dtype=bool))
    keep = set(np.unique(cc[own])) - {0}
    return extra & np.isin(cc, list(keep))


def mirror_x(mask: np.ndarray, axis_x: float) -> np.ndarray:
    """Reflect a mask about a vertical line at axis_x (cell coords, texel
    centres at x+0.5), nearest-texel."""
    CH, CW = mask.shape
    xs = np.arange(CW)
    src = np.rint(2.0 * axis_x - 1.0 - xs).astype(np.int32)
    ok = (src >= 0) & (src < CW)
    out = np.zeros_like(mask)
    out[:, ok] = mask[:, src[ok]]
    return out


def build_extents(rig, lab, idx, opaque, underlap, policy_default, axis_x):
    """Region each part may synthesise into.

    The load-bearing rule: a part may only grow into territory owned by a part
    drawn *in front* of it. Then the growth is covered at rest by z order alone,
    so the rest pose is bit-identical to the source sprite no matter how far the
    growth goes -- and it is uncovered exactly when the occluder swings away,
    which is the moment the gap would otherwise open. Growing under a part drawn
    *behind* would repaint it and change the sprite, so it is forbidden outright.

    Two sources of growth:
      underlap   dilate the part's own region by a few texels (fixes seams)
      mirror_of  take the whole mirrored region of the part's bilateral twin
                 (rebuilds a limb an occluder hid completely)

    `extend_outside` additionally permits growth into bare background. Nothing
    covers background, so that growth *is* visible at rest -- it is an opt-in
    escape hatch and `checks.py rest` will fail on it.
    """
    extents, mirror_src, notes = {}, {}, {}
    mirror_sil = mirror_x(opaque, axis_x)
    for p in rig.parts:
        n = p["name"]
        own = lab == idx[n]
        r = int(p.get("underlap", underlap))
        policy = p.get("extend_outside", policy_default)

        infront = np.zeros_like(opaque)
        for q in rig.parts:
            if rig.z[q["name"]] > rig.z[n]:
                infront |= lab == idx[q["name"]]

        if policy == "free":
            outside_ok = ~opaque
        elif policy == "mirror":
            outside_ok = (~opaque) & mirror_sil
        elif policy == "none":
            outside_ok = np.zeros_like(opaque)
        else:
            raise SystemExit("segment: part " + n + " has unknown extend_outside " + str(policy))

        allowed = infront | outside_ok
        need = required_underlap(rig, lab, idx, p, infront, r)
        need[outside_ok] = r
        synth = geodesic_grow_to(own, allowed, need, r)

        twin = p.get("mirror_of")
        twin_region = np.zeros_like(opaque)
        if twin:
            if twin not in idx:
                raise SystemExit("segment: part " + n + " mirror_of unknown part " + twin)
            # only under occluders: a mirrored limb poking into bare background
            # would be visible at rest, which is the one thing we never allow
            twin_region = mirror_x(lab == idx[twin], axis_x) & infront & ~own
            twin_region = reachable_from(own | synth, twin_region)
            synth = synth | twin_region

        extents[n] = synth
        mirror_src[n] = twin_region
        notes[n] = dict(radius=r, policy=policy, mirror_of=twin,
                        under_front=int((synth & infront).sum()),
                        from_twin=int(twin_region.sum()),
                        outside=int((synth & ~opaque).sum()))
    return extents, mirror_src, notes


def fill_from_twin(rgba, lab, idx, twin_name, region, axis_x):
    """Colour a mirrored region by reflecting the twin part's own texels across
    the symmetry axis. Palette-exact: every texel is a copy of an authored one."""
    CH, CW = region.shape
    out = np.zeros((CH, CW, 4), dtype=np.uint8)
    got = np.zeros((CH, CW), dtype=bool)
    if not region.any():
        return out, got
    ys, xs = np.where(region)
    sx = np.rint(2.0 * axis_x - 1.0 - xs).astype(np.int32)
    ok = (sx >= 0) & (sx < CW)
    ok &= lab[np.clip(ys, 0, CH - 1), np.clip(sx, 0, CW - 1)] == idx[twin_name]
    out[ys[ok], xs[ok]] = rgba[ys[ok], sx[ok]]
    out[ys[ok], xs[ok], 3] = 255
    got[ys[ok], xs[ok]] = True
    return out, got


# ------------------------------------------------------------------ stage 3

def fill_region(rgba, own, synth, mode, axis_x):
    """Synthesise colours for `synth` using only texels already in `own`.

    mirror  reflect across the part's own boundary -- a texel d outside the edge
            takes the colour d inside it, so an outline is not smeared outward.
    edge    nearest own texel (cheap, smears the outline; useful for flat parts)
    reflect take the bilaterally symmetric texel of the same part, for rebuilding
            a half an occluder hid; falls back to mirror where that is empty.
    """
    CH, CW = own.shape
    out = np.zeros((CH, CW, 4), dtype=np.uint8)
    if not synth.any():
        return out
    _, ind = ndimage.distance_transform_edt(~own, return_indices=True)
    ys, xs = np.where(synth)
    by, bx = ind[0][ys, xs], ind[1][ys, xs]

    if mode == "edge":
        sy, sx = by.copy(), bx.copy()
    elif mode == "mirror":
        sy, sx = 2 * by - ys, 2 * bx - xs
    elif mode == "reflect":
        sx = np.rint(2.0 * axis_x - 1.0 - xs).astype(np.int32)
        sy = ys.copy()
        bad = (sx < 0) | (sx >= CW)
        sx = np.where(bad, bx, sx)
        sy = np.where(bad, by, sy)
        good = ~bad & own[np.clip(sy, 0, CH - 1), np.clip(sx, 0, CW - 1)]
        sy = np.where(good, sy, 2 * by - ys)
        sx = np.where(good, sx, 2 * bx - xs)
    else:
        raise SystemExit("segment: unknown fill mode " + str(mode))

    sy = np.clip(sy, 0, CH - 1)
    sx = np.clip(sx, 0, CW - 1)
    miss = ~own[sy, sx]
    sy[miss], sx[miss] = by[miss], bx[miss]   # last resort: the boundary texel
    out[ys, xs] = rgba[sy, sx]
    out[ys, xs, 3] = 255
    return out


# ---------------------------------------------------------------------- main

def segment(rig, underlap, colour_lambda, fill_mode, policy, axis_x=None, quiet=False):
    src = Image.open(rig.data["source"])
    rgba, (ox, oy) = riglib.place_in_cell(src, rig.cell)
    opaque = riglib.binary_alpha(rgba)

    root = next((p for p in rig.parts if not p.get("parent")), rig.parts[0])
    if axis_x is None:
        axis_x = float(rig.data.get("symmetry_x", root["pivot"][0]))

    lab, idx, how, n_orphan = label_parts(rig, rgba, opaque, colour_lambda)
    extents, mirror_src, notes = build_extents(rig, lab, idx, opaque, underlap, policy, axis_x)

    layers, synths, warnings = {}, {}, []
    for p in rig.parts:
        n = p["name"]
        own = lab == idx[n]
        mode = p.get("fill", fill_mode)
        # mirrored twin texels first, then ordinary underlap over whatever the
        # mirror could not supply
        twin_layer, twin_got = (np.zeros(rgba.shape, np.uint8), np.zeros(own.shape, bool))
        if notes[n]["mirror_of"]:
            twin_layer, twin_got = fill_from_twin(rgba, lab, idx, notes[n]["mirror_of"],
                                                  mirror_src[n], axis_x)
        layer = fill_region(rgba, own, extents[n] & ~twin_got, mode, axis_x)
        layer[twin_got] = twin_layer[twin_got]
        layer[own] = rgba[own]
        layer[own, 3] = 255
        layers[n] = layer
        synths[n] = extents[n].copy()
        # A joint legitimately sits in the parent's territory (a shoulder socket
        # is torso), so the check is not "pivot inside part" but "part reaches
        # its pivot": art that starts several texels away swings as a detached
        # blob. This is the cheapest signal that a cut landed in the wrong place.
        px, py = p["pivot"]
        reach = own | extents[n]
        if reach.any():
            ys_, xs_ = np.where(reach)
            gap = float(np.min(np.hypot(xs_ - px, ys_ - py)))
            if gap > int(p.get("underlap", underlap)) + 1:
                warnings.append("%s: nearest texel is %.1f from pivot (%d,%d) -- it will detach"
                                % (n, gap, px, py))

    if not quiet:
        print("source %dx%d placed at (%d,%d) in %dx%d  |  %d opaque texels  |  symmetry_x=%g"
              % (src.width, src.height, ox, oy, rig.cell[0], rig.cell[1],
                 int(opaque.sum()), axis_x))
        if n_orphan:
            print("  %d disconnected texels assigned by nearest part" % n_orphan)
        print("  %-12s %-22s %5s %6s %6s %5s %5s  fill"
              % ("part", "seed", "own", "synth", "under", "twin", "out"))
        for p in rig.parts:
            n = p["name"]
            nt = notes[n]
            print("  %-12s %-22s %5d %6d %6d %5d %5d  %s/%s@%d"
                  % (n, how[n], int((lab == idx[n]).sum()), int(synths[n].sum()),
                     nt["under_front"], nt["from_twin"], nt["outside"],
                     p.get("fill", fill_mode), nt["policy"], nt["radius"]))
        for w in warnings:
            print("  WARN " + w)
    return dict(rgba=rgba, opaque=opaque, lab=lab, idx=idx, layers=layers,
                synths=synths, axis_x=axis_x, notes=notes, how=how, warnings=warnings)


PALETTE = [(228, 94, 94), (94, 188, 228), (240, 196, 92), (140, 214, 122),
           (196, 128, 232), (232, 150, 96), (120, 232, 204), (232, 120, 170),
           (150, 150, 240), (200, 232, 110)]


def write_out(rig, res, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    CW, CH = rig.cell
    manifest = dict(name=rig.name, cell=[CW, CH], symmetry_x=res["axis_x"], parts=[])
    for p in rig.parts:
        n = p["name"]
        Image.fromarray(res["layers"][n], "RGBA").save(out_dir / (n + ".png"))
        sm = np.zeros((CH, CW, 4), dtype=np.uint8)
        sm[res["synths"][n]] = (255, 255, 255, 255)
        Image.fromarray(sm, "RGBA").save(out_dir / (n + ".synth.png"))
        manifest["parts"].append(dict(
            name=n, parent=p.get("parent"), pivot=list(p["pivot"]),
            layer=n + ".png", synth=n + ".synth.png",
            authored_px=int((res["lab"] == res["idx"][n]).sum()),
            synth_px=int(res["synths"][n].sum()), **res["notes"][n]))
    # identifies this segmentation run, so rig.lua can refuse a stale parts file
    manifest["stamp"] = "|".join("%s:%d:%d" % (e["name"], e["authored_px"], e["synth_px"])
                                 for e in manifest["parts"])
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    lab, idx = res["lab"], res["idx"]
    vis = np.zeros((CH, CW, 4), dtype=np.uint8)
    for p in rig.parts:
        c = PALETTE[rig.z[p["name"]] % len(PALETTE)]
        vis[lab == idx[p["name"]]] = c + (255,)
    Image.fromarray(vis, "RGBA").save(out_dir / "_labels.png")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rig", type=Path)
    ap.add_argument("--underlap", type=int, default=None,
                    help="cap on how far a part may grow under its occluders; the "
                         "radius actually used is derived per texel from how far "
                         "that occluder swings (default: the rig's `underlap`, else 6)")
    ap.add_argument("--colour-lambda", type=float, default=6.0,
                    help="how strongly a cut prefers to follow a colour edge (0 = pure distance)")
    ap.add_argument("--fill", default="mirror", choices=["mirror", "edge", "reflect"])
    ap.add_argument("--extend-outside", default="none", choices=["none", "mirror", "free"])
    ap.add_argument("--symmetry-x", type=float, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rig = riglib.load_rig(args.rig)
    # per-subject tuning belongs in the rig, not in whoever remembers the flag
    underlap = args.underlap if args.underlap is not None else int(rig.data.get("underlap", 6))
    res = segment(rig, underlap, args.colour_lambda, args.fill,
                  args.extend_outside, args.symmetry_x)
    out = args.out or rig.parts_dir()
    write_out(rig, res, out)
    print("wrote %d part layers -> %s" % (len(rig.parts), out))


if __name__ == "__main__":
    main()

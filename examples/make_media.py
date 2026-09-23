"""Render the GIFs and stills the README shows, from the example rigs.

Everything is rendered fresh by `render.py`'s code path (no strip files are read), so the pictures are
exactly what the current pipeline produces. Output goes to docs/media/.

    python examples/make_media.py

Needs the parts on disk first (segment.py for each rig; for the full set, the view pipeline in
examples/skeleton_warrior/, see docs/SPIKE_YAW.md).
"""
from __future__ import annotations

import math
import sys
from functools import reduce
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pixelanim"))
import render   # noqa: E402
import riglib   # noqa: E402

OUT = ROOT / "docs" / "media"
BG = (22, 22, 28)
INK = (225, 225, 232)
DIM = (120, 120, 134)
TICK = 50   # ms; every hold in the example rigs is a multiple of this


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def frames_of(rig_path):
    rig = riglib.load_rig(rig_path)
    frames = render.render_all(rig, render.Parts(rig, rig.parts_dir()))
    by = {}
    for fr in frames:
        by.setdefault(fr["state"], []).append(fr)
    return rig, by


def ticks(seq):
    """A state's frames expanded to one entry per TICK."""
    out = []
    for fr in seq:
        out += [fr["rgba"]] * max(1, round(fr["ms"] / TICK))
    return out


def cell(rgba, z, crop=None):
    im = Image.fromarray(rgba, "RGBA")
    if crop:
        im = im.crop(crop)
    return im.resize((im.width * z, im.height * z), Image.NEAREST)


def panel(tracks, labels, z, n_ticks, cols=None, crop=None, title=None, hold_ms=None):
    """Tracks play side by side, each looping on its own length, for n_ticks."""
    cols = cols or len(tracks)
    rows = math.ceil(len(tracks) / cols)
    sizes = [cell(tr[0], z, crop).size for tr in tracks]
    cw, ch = max(s[0] for s in sizes), max(s[1] for s in sizes)
    pad, lab, top = 8, 20, (26 if title else 4)
    W, H = cols * (cw + pad) + pad, top + rows * (ch + lab + pad)
    f, ft = font(13), font(15)
    ims = []
    for t in range(n_ticks):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        if title:
            d.text((pad, 6), title, fill=INK, font=ft)
        for i, (tr, lb) in enumerate(zip(tracks, labels)):
            x = pad + (i % cols) * (cw + pad)
            y = top + (i // cols) * (ch + lab + pad)
            c = cell(tr[t % len(tr)], z, crop)
            im.paste(c, (x + (cw - c.width) // 2, y + ch - c.height), c)
            tw = d.textlength(lb, font=f)
            d.text((x + (cw - tw) / 2, y + ch + 2), lb, fill=DIM, font=f)
        ims.append(im)
    return ims


def save_gif(ims, name, ms=TICK, tail_ms=0):
    # One shared palette, so colours cannot shift between frames.
    pal = ims[0].quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    ps = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in ims]
    # Collapse runs of identical frames into longer durations.
    out, durs = [], []
    for p in ps:
        if out and np.array_equal(np.asarray(p), np.asarray(out[-1])):
            durs[-1] += ms
        else:
            out.append(p)
            durs.append(ms)
    durs[-1] += tail_ms
    path = OUT / name
    out[0].save(path, save_all=True, append_images=out[1:], duration=durs, loop=0, disposal=1, optimize=False)
    print("wrote %s  (%d frames, %.1f s, %d KB)" % (path.relative_to(ROOT), len(out), sum(durs) / 1000,
                                                    path.stat().st_size // 1024))


def lcm(xs):
    return reduce(lambda a, b: a * b // math.gcd(a, b), xs)


def yaw_label(y):
    return "%d°" % y


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    full = ROOT / "examples/skeleton_warrior/rig_fullset.json"
    _, by = frames_of(full)
    facings = [0, 45, 90, 135, 180, 225, 270, 315]
    crop = (4, 0, 44, 48)   # the skeleton never uses the outer 4 columns

    # 1. Hero: the walk, turning one facing per cycle.
    seq = []
    for y in facings:
        seq += ticks(by["walk_%03d" % y]) * 2
    save_gif(panel([seq], [""], 6, len(seq), crop=crop), "hero_walk_turn.gif")

    # 2. The walk at all eight facings at once.
    tr = [ticks(by["walk_%03d" % y]) for y in facings]
    save_gif(panel(tr, [yaw_label(y) for y in facings], 3, lcm([len(t) for t in tr]), crop=crop),
             "walk_8_facings.gif")

    # 3. The sword attack at all eight facings.
    tr = [ticks(by["attack_a_%03d" % y]) for y in facings]
    save_gif(panel(tr, [yaw_label(y) for y in facings], 3, max(len(t) for t in tr), crop=crop),
             "attack_8_facings.gif", tail_ms=500)

    # 4. Every state, at the front and at 3/4.
    states = ["idle", "idle_b", "walk", "alert", "hostile", "attack_a", "attack_b", "damage"]
    for yaw in (0, 45):
        tr = [ticks(by["%s_%03d" % (s, yaw)]) for s in states]
        n = max(len(t) for t in tr) * 2
        save_gif(panel(tr, states, 3, n, cols=4, crop=crop), "states_%03d.gif" % yaw)

    # 5. The other archetypes: squash/stretch (slime) and chain lag (wisp).
    tracks, labels = [], []
    for name in ("slime", "wisp"):
        rig, sb = frames_of(ROOT / "examples" / name / "rig.json")
        for s, fr in sb.items():
            tracks.append(ticks(fr))
            labels.append("%s / %s" % (name, s))
    n = min(lcm([len(t) for t in tracks]), 120)
    save_gif(panel(tracks, labels, 4, n, cols=len(tracks)), "slime_wisp.gif")

    # 6. The cut: source sprite, part labels, and a posed frame with invented texels marked.
    pipeline_still(ROOT / "examples/skeleton_warrior/rig_2bone.json")


def pipeline_still(rig_path):
    rig = riglib.load_rig(rig_path)
    parts = render.Parts(rig, rig.parts_dir())
    frames = render.render_all(rig, parts)
    rest = frames[0]
    names = [p["name"] for p in rig.parts]
    hues = [(230, 90, 80), (240, 170, 60), (230, 220, 90), (110, 200, 110), (80, 190, 200),
            (90, 130, 230), (170, 110, 220), (220, 110, 180), (160, 160, 160), (200, 140, 100)]
    _, _, owner = render.compose(rig, parts, {})        # the rest pose
    lab = np.zeros(owner.shape + (4,), np.uint8)
    for i, n in enumerate(names):
        m = owner == i + 1
        lab[m, :3] = hues[i % len(hues)]
        lab[m, 3] = 255
    # The frame that moves furthest from rest, with its invented texels tinted cyan.
    pick = max(frames, key=lambda fr: int((fr["owner"] != rest["owner"]).sum()))
    posed = pick["rgba"].copy()
    posed[pick["synth"]] = (90, 230, 255, 255)

    z, pad = 7, 14
    ims = [cell(rest["rgba"], z), cell(lab, z), cell(pick["rgba"], z), cell(posed, z)]
    caps = ["1. authored sprite", "2. cut into parts", "3. posed (%s)" % pick["state"], "4. invented texels"]
    f = font(15)
    W = sum(i.width for i in ims) + pad * (len(ims) + 1)
    H = ims[0].height + 40
    out = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(out)
    x = pad
    for im, c in zip(ims, caps):
        out.paste(im, (x, 8), im)
        d.text((x + (im.width - d.textlength(c, font=f)) / 2, im.height + 14), c, fill=DIM, font=f)
        x += im.width + pad
    path = OUT / "pipeline.png"
    out.save(path)
    print("wrote %s" % path.relative_to(ROOT))


if __name__ == "__main__":
    main()

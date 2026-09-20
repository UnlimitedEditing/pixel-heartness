"""SPIKE. Cut each registered view into the rig's parts and export per-part variant art.

For every view in views/reg_v*.png (see make_ring_views.py) it

  1. proposes seeds from geometry and colour: the shield is the largest red-family component and
     the glove the next; the head is above the neck (the narrowest row under the skull); torso,
     pelvis and the two legs are seeded on the body axis by height;
  2. cuts the view with segment.py's colour-weighted flood (seed validation on, so a seed on a
     transparent texel or on another part's colour is refused);
  3. writes a label picture to check by eye (never trust proposed seeds unseen), and one 48x48
     image per part holding that part's own texels in that view: views/<view>_<part>.png. These
     are the part variants the yaw renderer picks between.

    python examples/skeleton_warrior/segment_views.py [v45 v90 v135 v180]
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "pixelanim"))
import riglib          # noqa: E402
import segment         # noqa: E402
import mirrorpatch as mp   # noqa: E402

RED = mp.SHIELD_COLOURS
PARTS = ["leg_r", "leg_l", "pelvis", "torso", "head", "arm_weapon", "arm_shield", "shield"]
AXIS = 24.5


def nearest(mask, x, y, exclude=()):
    ys, xs = np.where(mask)
    ok = [(xx, yy) for xx, yy in zip(xs, ys) if (int(xx), int(yy)) not in exclude]
    if not ok:
        return None
    d = [(xx - x) ** 2 + (yy - y) ** 2 for xx, yy in ok]
    xx, yy = ok[int(np.argmin(d))]
    return [int(xx), int(yy)]


def propose(rgba):
    a = rgba[:, :, 3] > 127
    red = np.zeros(a.shape, dtype=bool)
    for c in RED:
        red |= (rgba[:, :, :3] == np.array(c, dtype=np.uint8)).all(axis=2) & a
    body = a & ~red
    comp, n = ndimage.label(red, structure=np.ones((3, 3)))
    sizes = ndimage.sum(red, comp, range(1, n + 1)) if n else []
    order = list(np.argsort(sizes)[::-1] + 1) if n else []
    seeds = {p: [] for p in PARTS}
    taken = set()

    def add(part, pt):
        if pt is not None and tuple(pt) not in taken:
            seeds[part].append(pt)
            taken.add(tuple(pt))

    if order:                                             # shield = largest red component
        m = comp == order[0]
        ys, xs = np.where(m)
        cx, cy = xs.mean(), ys.mean()
        for tx, ty in ((cx, cy), (xs.min(), ys.mean()), (xs.max(), ys.mean()), (cx, ys.max()), (cx, ys.min())):
            add("shield", nearest(m, tx, ty, taken))
        sx0, sx1, sy0 = xs.min(), xs.max(), ys.min()
    if len(order) > 1 and sizes[order[1] - 1] >= 5:       # glove = the next one
        m = comp == order[1]
        ys, xs = np.where(m)
        add("arm_weapon", nearest(m, xs.mean(), ys.mean(), taken))
        add("arm_weapon", nearest(body, xs.mean(), ys.min() - 3, taken))   # arm just above the glove
    ys, xs = np.where(a)
    y0, y1 = ys.min(), ys.max()
    H = y1 - y0
    # head: the topmost non-red mass; neck: narrowest row below it
    widths = {y: int(body[y].sum()) for y in range(y0, y0 + int(0.42 * H))}
    top_rows = [y for y in range(y0, y0 + 8) if body[y].any()]
    hx = float(np.mean([np.where(body[y])[0].mean() for y in top_rows]))
    lo, hi = y0 + 7, y0 + int(0.36 * H)
    neck = min(range(lo, hi), key=lambda y: (widths.get(y, 99), y))
    add("head", nearest(body, hx, y0 + 3, taken))
    add("head", nearest(body, hx, y0 + 6, taken))
    for dy in (3, 6):
        row = neck + dy
        tx = float(np.where(body[row])[0].mean()) if body[row].any() else AXIS
        add("torso", nearest(body, tx, row, taken))
    py = y0 + int(0.60 * H)
    add("pelvis", nearest(body, AXIS, py, taken))
    add("pelvis", nearest(body, AXIS, py + 2, taken))
    for frac in (0.78, 0.92):
        ly = y0 + int(frac * H)
        add("leg_r", nearest(body, AXIS + 3, ly, taken))
        add("leg_l", nearest(body, AXIS - 3, ly, taken))
    if order:                                             # the shield arm, hidden: near the shield's top
        add("arm_shield", nearest(body, sx1 if sx1 < AXIS else sx0, sy0 + 1, taken))
    if not seeds["arm_weapon"]:
        add("arm_weapon", nearest(body, AXIS + 6, y0 + int(0.42 * H), taken))
    if not seeds["arm_shield"]:
        add("arm_shield", nearest(body, AXIS - 6, y0 + int(0.42 * H), taken))
    return seeds, dict(neck=int(neck), y0=int(y0), y1=int(y1))


def view_rig(name, seeds):
    base = json.loads((HERE / "rig.json").read_text(encoding="utf-8"))
    rig = {"name": "view_" + name, "source": str((HERE / "views" / ("reg_%s.png" % name)).as_posix()),
           "parts_file": "out/_v.aseprite", "anim_file": "out/_v_anim.aseprite", "strip_file": "out/_v.png",
           "cell": [48, 48], "underlap": 0, "symmetry_x": AXIS, "parts": [], "states": []}
    for p in base["parts"]:
        q = {k: v for k, v in p.items() if k in ("name", "rect", "pivot", "parent")}
        q["seeds"] = seeds[p["name"]]
        rig["parts"].append(q)
    return rig


PALETTE = {"leg_r": (230, 90, 90), "leg_l": (90, 150, 230), "pelvis": (230, 190, 60), "torso": (110, 200, 120),
           "head": (230, 230, 230), "arm_weapon": (230, 120, 200), "arm_shield": (150, 110, 230),
           "shield": (230, 140, 50)}


def main(names):
    (HERE / "views").mkdir(exist_ok=True)
    for name in names:
        rgba = np.array(Image.open(HERE / "views" / ("reg_%s.png" % name)).convert("RGBA"))
        seeds, info = propose(rgba)
        rigd = view_rig(name, seeds)
        path = HERE / "views" / ("_rig_%s.json" % name)
        path.write_text(json.dumps(rigd, indent=1), encoding="utf-8")
        rig = riglib.load_rig(path)
        try:
            res = segment.segment(rig, 0, 6.0, "mirror", "none", None, quiet=True)
            note = "ok"
        except SystemExit as e:
            res = segment.segment(rig, 0, 6.0, "mirror", "none", None, quiet=True, allow_bad_seeds=True)
            note = "SEED PROBLEMS: " + str(e).splitlines()[1] if len(str(e).splitlines()) > 1 else str(e)
        lab, idx = res["lab"], res["idx"]
        counts = {p: int((lab == idx[p]).sum()) for p in PARTS}
        print("%-5s neck row %2d  %s  texels %s" % (name, info["neck"], note, counts))
        # label picture
        S = 9
        img = Image.new("RGB", (48 * S, 48 * S), (58, 60, 72))
        d = ImageDraw.Draw(img)
        for y in range(48):
            for x in range(48):
                if lab[y, x]:
                    pn = PARTS[[idx[p] for p in PARTS].index(lab[y, x])]
                    d.rectangle([x * S, y * S, x * S + S - 1, y * S + S - 1], fill=PALETTE[pn])
        for p in PARTS:
            for sx, sy in seeds[p]:
                d.ellipse([sx * S + 2, sy * S + 2, sx * S + S - 3, sy * S + S - 3], outline=(0, 0, 0), width=2)
        img.save(ROOT / "data/diffusion" / ("skel_labels_%s.png" % name))
        # per-part own-texel art
        for p in PARTS:
            out = np.zeros((48, 48, 4), dtype=np.uint8)
            m = (lab == idx[p]) & (rgba[:, :, 3] > 127)
            out[m] = rgba[m]
            Image.fromarray(out, "RGBA").save(HERE / "views" / ("%s_%s.png" % (name, p)))


if __name__ == "__main__":
    main(sys.argv[1:] or ["v45", "v90", "v135", "v180"])

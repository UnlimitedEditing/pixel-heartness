"""Which rotation angles are clean for a part?

Damage from rotating a small part is not monotonic in the angle: on the wisp head
6 degrees ruins the eyes, 8 leaves them intact, 10-16 half-ruin them, 18 ruins
them. It depends on where the small features land on the texel grid, so no
"stay under N degrees" rule is safe. This measures instead, rotating the part
about its own pivot in isolation, and prints the angles that keep its small
features intact so a pose can be authored from a known-good list.

    python pixelanim/rotscan.py examples/wisp/rig.json head
    python pixelanim/rotscan.py examples/wisp/rig.json head --lo -20 --hi 20 --step 1
"""
from __future__ import annotations

import argparse
from pathlib import Path

import riglib
import render
import checks


def scan(rig, parts, name, lo, hi, step, tol=0.2):
    part = rig.by_name[name]
    layer = parts.layer[name]
    feats = checks._features(layer, int(rig.data.get("feature_min", 4)),
                             int(rig.data.get("feature_max", 16)))
    rows, a = [], float(lo)
    while a <= hi + 1e-9:
        M = riglib.pose_matrix({"rot": a}, part["pivot"])
        new = riglib.sample_nearest(layer, M, rig.cell)
        rows.append((a, len(checks._damaged(layer, new, M, feats, tol)), len(feats)))
        a += step
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rig", type=Path)
    ap.add_argument("part")
    ap.add_argument("--lo", type=float, default=-30)
    ap.add_argument("--hi", type=float, default=30)
    ap.add_argument("--step", type=float, default=1)
    args = ap.parse_args()
    rig = riglib.load_rig(args.rig)
    if args.part not in rig.by_name:
        raise SystemExit("rotscan: no part '%s' (parts: %s)" % (args.part, ", ".join(rig.by_name)))
    parts = render.Parts(rig, rig.parts_dir())
    rows = scan(rig, parts, args.part, args.lo, args.hi, args.step)
    n = rows[0][2]
    if not n:
        print("%s has no small features to protect (%d..%d texels); any angle is clean by this measure"
              % (args.part, int(rig.data.get("feature_min", 4)), int(rig.data.get("feature_max", 16))))
        return
    clean = [a for a, bad, _ in rows if bad == 0]
    print("%s: %d small features tracked" % (args.part, n))
    print("angle : ruined      (# = one ruined feature)")
    for a, bad, _ in rows:
        print("%+6.1f : %-3s %s" % (a, "ok" if bad == 0 else bad, "#" * bad))
    print("clean angles: " + (", ".join("%+g" % a for a in clean) or "none in range"))


if __name__ == "__main__":
    main()

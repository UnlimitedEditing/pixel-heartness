"""SPIKE. rig_walkturn.json: the authored walk (rig.json's `walk`) at all eight facings, using the
per-view part art (make_turn_rig2.py), per-view pivots (derive_pivots.py) and a view-dependent leg
swing (`yaw_gain`: 1x at the front, 2.5x in profile, so the authored +-10 degrees becomes +-25).

    python examples/skeleton_warrior/make_walk_turn.py [--gain 2.5] [--no-pivots]
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).parent
ap = argparse.ArgumentParser()
ap.add_argument("--gain", type=float, default=2.5)
ap.add_argument("--no-pivots", action="store_true", help="keep the front-view pivots everywhere")
ap.add_argument("--out", default="rig_walkturn.json")
args = ap.parse_args()

base = json.loads((HERE / "rig_turn2.json").read_text(encoding="utf-8"))
orig = json.loads((HERE / "rig.json").read_text(encoding="utf-8"))
walk = next(s for s in orig["states"] if s["name"] == "walk")
base["name"] = "skeleton_walkturn"
base["parts_file"] = "out/walkturn_parts.aseprite"
base["anim_file"] = "out/walkturn_anim.aseprite"
base["strip_file"] = "out/walkturn_strip.png"
if not args.no_pivots:
    base["view_pivots"] = "views/pivots.json"
base["states"] = []
for yaw in range(0, 360, 45):
    base["states"].append({
        "name": "walk_%03d" % yaw, "fps": walk["fps"], "loop": True, "min_distinct": 0.2,
        "yaw_gain": {"leg_l": {"rot": [1.0, args.gain]}, "leg_r": {"rot": [1.0, args.gain]}},
        "frames": [{"pose": f.get("pose", {}), "yaw": yaw} for f in walk["frames"]],
    })
(HERE / args.out).write_text(json.dumps(base, indent=2), encoding="utf-8")
print("wrote %s: %d facings x %d frames, gain %.1f, pivots %s" % (
    args.out, len(base["states"]), len(walk["frames"]), args.gain, "front" if args.no_pivots else "per view"))

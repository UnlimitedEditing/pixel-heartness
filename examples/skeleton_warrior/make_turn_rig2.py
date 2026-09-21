"""SPIKE. rig_turn2.json: skeleton_warrior with its parts cut out of five generated views and a
24-frame turn state. Run make_ring_views.py and segment_views.py first.

Views (angle: art): 0 the source sprite, 45 v45, 90 v90, 135 v135, 180 v180, then the other half of
the ring from mirrors: 225 v135 mirrored, 270 v90 mirrored, 315 v45 mirrored. In the mirrored views
the shield and both arms are `handed`: `patch_handed` keeps them on their own side of the body
instead of swapping them with the rest.

    python examples/skeleton_warrior/make_turn_rig2.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
r = json.loads((HERE / "rig_2bone.json").read_text(encoding="utf-8"))
r["name"] = "skeleton_turn2"
r["parts_file"] = "out/turn2_parts.aseprite"
r["anim_file"] = "out/turn2_anim.aseprite"
r["strip_file"] = "out/turn2_strip.png"
r["damage_max"] = 1.0
HANDED = {"shield", "arm_shield", "arm_weapon"}
for p in r["parts"]:
    v = {}
    for name in ("v45", "v90", "v135", "v180"):
        f = HERE / "views" / ("%s_%s.png" % (name, p["name"]))
        if f.exists():
            v[name] = "views/%s_%s.png" % (name, p["name"])
    p["variants"] = v
    if p["name"] in HANDED:
        p["handed"] = True
r["views"] = [
    {"name": "front", "angle": 0, "variant": None, "mirror": False},
    {"name": "v45", "angle": 45, "variant": "v45", "mirror": False},
    {"name": "v90", "angle": 90, "variant": "v90", "mirror": False},
    {"name": "v135", "angle": 135, "variant": "v135", "mirror": False},
    {"name": "v180", "angle": 180, "variant": "v180", "mirror": False},
    {"name": "v135m", "angle": 225, "variant": "v135", "mirror": True, "patch_handed": True},
    {"name": "v90m", "angle": 270, "variant": "v90", "mirror": True},
    {"name": "v45m", "angle": 315, "variant": "v45", "mirror": True, "patch_handed": True},
]
r["states"] = [{"name": "turn", "fps": 8, "loop": True, "min_distinct": 0.3,
                "frames": [{"yaw": a} for a in range(0, 360, 15)]}]
(HERE / "rig_turn2.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
print("wrote rig_turn2.json:", len(r["states"][0]["frames"]), "frames,", len(r["views"]), "views,",
      sum(len(p["variants"]) for p in r["parts"]), "part variants")

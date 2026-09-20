"""SPIKE. Build rig_turn.json: skeleton_warrior plus per-part profile variants and a
24-frame turn state (every 15 degrees). Run make_views.py first.

    python examples/skeleton_warrior/make_turn_rig.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
r = json.loads((HERE / "rig.json").read_text(encoding="utf-8"))
r["name"] = "skeleton_turn"
r["parts_file"] = "out/turn_parts.aseprite"
r["anim_file"] = "out/turn_anim.aseprite"
r["strip_file"] = "out/turn_strip.png"
r["damage_max"] = 1.0
r["yaw_thickness"] = 0.35          # measured: profile is 11 texels against 31 for the front
for p in r["parts"]:
    f = HERE / "views" / ("side_%s.png" % p["name"])
    if f.exists():
        p["variants"] = {"side": "views/side_%s.png" % p["name"]}
r["states"] = [{"name": "turn", "fps": 8, "loop": True, "min_distinct": 0.3,
                "frames": [{"yaw": a} for a in range(0, 360, 15)]}]
(HERE / "rig_turn.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
print("wrote rig_turn.json:", len(r["states"][0]["frames"]), "frames;",
      sum(1 for p in r["parts"] if p.get("variants")), "parts with a side view")

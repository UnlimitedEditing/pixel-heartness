"""Split each leg at the knee: rig_2bone.json.

The one-bone legs cannot bend a knee (open defect #10), which is why a profile walk reads as scissors.
Each leg becomes a thigh (`leg_r`, `leg_l`) and a shin (`leg_r_low`, `leg_l_low`) hinged at the knee,
row 38 in the front sprite. Nothing is redrawn: the shin is the texels of the leg below the knee.
Seeds were placed against the label map (`sheet.py map`): thigh on rows 33-36, shin on rows 40-45.

    python examples/skeleton_warrior/make_2bone_rig.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
r = json.loads((HERE / "rig.json").read_text(encoding="utf-8"))
parts = []
for p in r["parts"]:
    if p["name"] == "leg_r":
        p["seeds"] = [[30, 35], [29, 33]]
        parts.append(p)
        parts.append({"name": "leg_r_low", "rect": [27, 38, 10, 10], "pivot": [30, 38], "parent": "leg_r",
                      "seeds": [[29, 42], [31, 45]]})
    elif p["name"] == "leg_l":
        p["seeds"] = [[21, 36], [22, 35]]
        parts.append(p)
        parts.append({"name": "leg_l_low", "rect": [15, 38, 9, 10], "pivot": [20, 38], "parent": "leg_l",
                      "seeds": [[19, 40], [18, 42], [17, 45]], "mirror_of": "leg_r_low"})
    else:
        parts.append(p)
r["parts"] = parts
r["name"] = "skeleton_2bone"
r["parts_file"] = "out/skeleton_2bone_parts.aseprite"
r["anim_file"] = "out/skeleton_2bone_anim.aseprite"
r["strip_file"] = "out/skeleton_2bone_strip.png"
(HERE / "rig_2bone.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
print("wrote rig_2bone.json:", [p["name"] for p in parts])

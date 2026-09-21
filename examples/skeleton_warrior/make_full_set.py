"""SPIKE. The full animation set for the skeleton, every state at all eight facings, plus a manifest.

States (authored in front-view space; per-view amplitude comes from `yaw_gain`):

  idle, idle_b   breathing; a look-around
  walk           the authored four-frame walk (legs swing 1x at the front, 2.5x in profile)
  alert          noticed something: head turns, weapon arm lifts a little
  hostile        combat stance loop
  attack_a       the sword attack: ready, windup, strike, recover as one state (holds preserve
                 the original timing at a common 20 fps); commit frame = first strike frame
  attack_b       a shield bash
  damage         recoil with a one-frame flash and a squash
  (talk)         NOT here: it needs a jaw part, which the skeleton does not have yet

Each becomes `<state>_<yaw>` (idle_000 ... damage_315). The manifest maps (state, facing) to a frame
range in the strip, with fps, loop, holds and, for attacks, the commit frame.

    python examples/skeleton_warrior/make_full_set.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
orig = json.loads((HERE / "rig.json").read_text(encoding="utf-8"))
base = json.loads((HERE / "rig_turn2.json").read_text(encoding="utf-8"))
S = {s["name"]: s for s in orig["states"]}


def P(**kw):
    return kw


LEG_SWING = {"leg_l": {"rot": [1.0, 2.5]}, "leg_r": {"rot": [1.0, 2.5]}}
ARM_ARC = {"arm_weapon": {"rot": [1.0, 1.3]}}

FLASH = [209, 76, 36]          # a colour the sprite already uses (the shield's orange-red)


def attack_a():
    """ready + windup + strike + recover at a common 20 fps, keeping each frame's duration."""
    frames, commit = [], None
    for name in ("ready", "windup", "strike", "recover"):
        st = S[name]
        for i, f in enumerate(st["frames"]):
            ms = 1000.0 / st["fps"] * f.get("hold", 1)
            if name == "strike" and i == 0:
                commit = len(frames)
            frames.append({"pose": f.get("pose", {}), "hold": max(1, round(ms / 50.0))})
    return frames, commit


aframes, acommit = attack_a()

STATES = [
    dict(name="idle", kind="idle", fps=6, loop=True, frames=S["idle"]["frames"]),
    dict(name="idle_b", kind="idle", fps=4, loop=True, frames=[
        {"pose": {"head": {"rot": -8}}},
        {"pose": {"head": {"rot": -8}, "arm_shield": {"rot": 2}}},
        {"pose": {"head": {"rot": 8}}},
        {"pose": {"head": {"rot": 8}, "arm_shield": {"rot": 2}}}]),
    dict(name="walk", kind="walk", fps=8, loop=True, frames=S["walk"]["frames"], yaw_gain=LEG_SWING),
    dict(name="alert", kind="alert", fps=4, loop=True, frames=[
        {"pose": {"head": {"rot": -6}, "torso": {"rot": -2}, "arm_weapon": {"rot": -8}}},
        {"pose": {"head": {"rot": -6, "dy": -1}, "torso": {"rot": -3}, "arm_weapon": {"rot": -12},
                  "arm_shield": {"rot": -4}}}]),
    dict(name="hostile", kind="hostile", fps=6, loop=True, frames=[
        {"pose": {"arm_weapon": {"rot": -24}, "torso": {"rot": 3}, "arm_shield": {"rot": -6}}},
        {"pose": {"arm_weapon": {"rot": -28}, "torso": {"rot": 3, "dy": -1}, "arm_shield": {"rot": -6}}},
        {"pose": {"arm_weapon": {"rot": -24}, "torso": {"rot": 4}, "arm_shield": {"rot": -8}}},
        {"pose": {"arm_weapon": {"rot": -20}, "torso": {"rot": 3, "dy": -1}, "arm_shield": {"rot": -6}}}]),
    dict(name="attack_a", kind="attack", fps=20, loop=False, frames=aframes, yaw_gain=ARM_ARC,
         commit_frame=acommit),
    dict(name="attack_b", kind="attack", fps=12, loop=False, frames=[
        {"pose": {"arm_shield": {"rot": -20}, "torso": {"rot": -6}, "shield": {"rot": -6}}},
        {"pose": {"arm_shield": {"rot": 22}, "torso": {"rot": 8, "dx": 2}, "shield": {"dx": 2}}},
        {"pose": {"arm_shield": {"rot": 10}, "torso": {"rot": 3}}}], commit_frame=1),
    dict(name="damage", kind="damage", fps=12, loop=False, frames=[
        {"pose": {"torso": {"rot": -8}, "head": {"rot": -8}, "arm_weapon": {"rot": 10}},
         "squash": 0.08, "flash": FLASH},
        {"pose": {"torso": {"rot": -6}, "head": {"rot": -6}}, "squash": -0.04},
        {"pose": {"torso": {"rot": -2}}}]),
]

base["name"] = "skeleton_fullset"
base["parts_file"] = "out/fullset_parts.aseprite"
base["anim_file"] = "out/fullset_anim.aseprite"
base["strip_file"] = "out/fullset_strip.png"
base["view_pivots"] = "views/pivots.json"
base["damage_max"] = 1.0
base["states"] = []
manifest = []
cursor = 0
for yaw in range(0, 360, 45):
    for st in STATES:
        frames = []
        for f in st["frames"]:
            g = {"pose": f.get("pose", {}), "yaw": yaw}
            for k in ("hold", "squash", "flash"):
                if k in f:
                    g[k] = f[k]
            frames.append(g)
        name = "%s_%03d" % (st["name"], yaw)
        entry = {"name": name, "fps": st["fps"], "loop": st["loop"], "min_distinct": 0.1, "frames": frames}
        if st.get("yaw_gain"):
            entry["yaw_gain"] = st["yaw_gain"]
        base["states"].append(entry)
        manifest.append({"state": st["name"], "kind": st["kind"], "facing": yaw, "tag": name,
                         "first": cursor, "count": len(frames), "fps": st["fps"], "loop": st["loop"],
                         "holds": [f.get("hold", 1) for f in st["frames"]],
                         **({"commit_frame": st["commit_frame"]} if "commit_frame" in st else {})})
        cursor += len(frames)

# The poses underlap must cover. Each view's underlap is derived from the rig's pose list, so it has to
# see the worst-case poses actually used: every state's poses with the largest view gain applied.
under = []
for st in STATES:
    gains = st.get("yaw_gain") or {}
    fr = []
    for f in st["frames"]:
        pose = {k: dict(v) for k, v in f.get("pose", {}).items()}
        for part, keys in gains.items():
            for key, (mf, ms) in keys.items():
                if part in pose and key in pose[part]:
                    pose[part][key] = pose[part][key] * max(mf, ms)
        fr.append({"pose": pose})
    under.append({"name": st["name"], "fps": st["fps"], "loop": st["loop"], "frames": fr})
    # In a patched-mirror view the torso texels that sat under the shield end up under the sword arm
    # (and the other way round), so the underlap under each arm must be sized for the *other* arm's
    # motion too. Add a copy of every pose with the two arms' motions swapped.
    sw = []
    for f in fr:
        p2 = {k: dict(v) for k, v in f["pose"].items()}
        a, b = p2.pop("arm_weapon", None), p2.pop("arm_shield", None)
        if a is not None:
            p2["arm_shield"] = a
        if b is not None:
            p2["arm_weapon"] = b
        sw.append({"pose": p2})
    under.append({"name": st["name"] + "_swapped", "fps": st["fps"], "loop": st["loop"], "frames": sw})
(HERE / "views" / "underlap_states.json").write_text(json.dumps(under), encoding="utf-8")
(HERE / "rig_fullset.json").write_text(json.dumps(base, indent=2), encoding="utf-8")
(HERE / "fullset_manifest.json").write_text(json.dumps({
    "cell": [48, 48], "facings": list(range(0, 360, 45)), "frames": cursor,
    "mirrors": "225, 270 and 315 are baked here; an engine with a shader mirror needs only 0-180",
    "kinds": {k: sorted({m["state"] for m in manifest if m["kind"] == k}) for k in sorted({m["kind"] for m in manifest})},
    "entries": manifest}, indent=1), encoding="utf-8")
per = sum(len(s["frames"]) for s in STATES)
print("wrote rig_fullset.json + fullset_manifest.json: %d states x 8 facings = %d frames (%d per facing)"
      % (len(STATES), cursor, per))

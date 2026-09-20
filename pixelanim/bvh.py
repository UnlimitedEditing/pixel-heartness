"""BVH mocap -> a 2D keypoint clip for retarget.py.

Mocap supplies the *curve*; no texel comes from it. This reads a BVH, runs FK,
projects the 3D skeleton to a chosen camera, and expresses each mapped bone as
motion relative to a reference frame, laid onto the rig's own rest pose.

    python pixelanim/bvh.py scan  clip.bvh --joint RightHand
    python pixelanim/bvh.py clip  clip.bvh <rig> <map.json> --start 300 --end 420 \\
                                   --step 5 --azimuth auto --mirror --out clip.json

A map file names, per rig part, the BVH joints its bone runs between:

    {"pelvis": ["Hips", "Spine"], "torso": ["Spine", "Neck"], ...}

A joint written "A+B" means A extended by (A - B), for a bone with no end joint
(a shield hand, a head top).

Projection is a plain orthographic camera at `--azimuth` degrees about the
vertical axis, 0 = looking at the performer from the front. A billboard sprite
is front-facing, so motion toward or away from that camera foreshortens a bone;
that is kept, not corrected, because it is exactly the information the
retarget classifier needs ("this motion needs new art"). `--azimuth auto`
picks the angle where bones change length least.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

import riglib


# ------------------------------------------------------------------ parse

class Bvh:
    def __init__(self, path):
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        head, _, motion = text.partition("MOTION")
        self.joints = []                     # dicts in file order
        stack = []
        toks = head.replace("{", " { ").replace("}", " } ").split()
        i = 0
        cur = None
        while i < len(toks):
            t = toks[i]
            if t in ("ROOT", "JOINT"):
                cur = dict(name=toks[i + 1], parent=stack[-1] if stack else None,
                           offset=None, channels=[], end=None)
                self.joints.append(cur)
                i += 2
            elif t == "End":                 # End Site
                # "End Site { OFFSET x y z }": the whole block is consumed here,
                # braces included, so it never touches the joint stack
                j = toks.index("OFFSET", i)
                self.joints[-1]["end"] = np.array([float(x) for x in toks[j + 1:j + 4]])
                i = j + 5
                continue
            elif t == "{":
                stack.append(self.joints[-1]["name"] if self.joints else None)
                i += 1
            elif t == "}":
                stack.pop()
                i += 1
            elif t == "OFFSET":
                self.joints[-1]["offset"] = np.array([float(x) for x in toks[i + 1:i + 4]])
                i += 4
            elif t == "CHANNELS":
                n = int(toks[i + 1])
                self.joints[-1]["channels"] = toks[i + 2:i + 2 + n]
                i += 2 + n
            else:
                i += 1
        lines = [l for l in motion.strip().splitlines() if l.strip()]
        self.nframes = int(lines[0].split()[1])
        self.dt = float(lines[1].split()[2])
        self.data = np.array([[float(x) for x in l.split()] for l in lines[2:2 + self.nframes]])
        self.index = {j["name"]: k for k, j in enumerate(self.joints)}
        col = 0
        for j in self.joints:
            j["col"] = col
            col += len(j["channels"])

    @property
    def fps(self):
        return 1.0 / self.dt


def _rot(axis, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == "X":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "Y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def joint_positions(bvh: Bvh, frame: int):
    """World position of every joint at `frame`. Returns {name: (3,)}."""
    row = bvh.data[frame]
    world, pos = {}, {}
    for j in bvh.joints:
        loc = np.eye(4)
        loc[:3, 3] = j["offset"]
        R = np.eye(3)
        t = np.zeros(3)
        for ch, v in zip(j["channels"], row[j["col"]:j["col"] + len(j["channels"])]):
            if ch.endswith("position"):
                t["XYZ".index(ch[0])] = v
            else:
                R = R @ _rot(ch[0], v)          # channels are listed outermost first
        loc[:3, :3] = R
        loc[:3, 3] += t
        M = world[j["parent"]] @ loc if j["parent"] else loc
        world[j["name"]] = M
        pos[j["name"]] = M[:3, 3].copy()
    for j in bvh.joints:                        # end sites, as "<joint>.end"
        if j["end"] is not None:
            pos[j["name"] + ".end"] = (world[j["name"]] @ np.append(j["end"], 1.0))[:3]
    return pos


def all_positions(bvh, frames):
    return [joint_positions(bvh, f) for f in frames]


# ------------------------------------------------------------------ camera

def camera_axes(P0, azimuth_deg, mirror):
    """Screen right vector `s` and up vector `u` from a reference frame's pose."""
    u = np.array([0.0, 1.0, 0.0])
    a = P0["RightUpLeg"] - P0["LeftUpLeg"]
    a = a - u * (a @ u)
    a /= np.linalg.norm(a)                      # performer's right, horizontal
    f = np.cross(u, a)                          # performer's forward
    phi = math.radians(azimuth_deg)
    s = -(math.cos(phi) * a + math.sin(phi) * f)  # front view: viewer's right = performer's left
    if mirror:
        s = -s
    return s, u


def project(P, name, s, u):
    p = P[name]
    return np.array([p @ s, -(p @ u)])


def joint2(P, spec):
    """Position of a joint spec ('A' or 'A+B' meaning A extended by A-B)."""
    if "+" in spec:
        a, b = spec.split("+")
        return P[a] + (P[a] - P[b])
    return P[spec]


def proj(P, spec, s, u):
    p = joint2(P, spec)
    return np.array([p @ s, -(p @ u)])


# ------------------------------------------------------------------ scan

def scan(bvh, joint, ref="Head", top=6, min_gap=60):
    """Frames where `joint` is highest relative to `ref` -- the top of a swing --
    with the frames either side where it crosses back below shoulder height."""
    h = np.array([joint_positions(bvh, f)[joint][1] - joint_positions(bvh, f)[ref][1]
                  for f in range(bvh.nframes)])
    order = np.argsort(-h)
    peaks = []
    for k in order:
        if all(abs(int(k) - p) >= min_gap for p in peaks):
            peaks.append(int(k))
        if len(peaks) >= top:
            break
    return h, sorted(peaks)


# ------------------------------------------------------------------ clip

def bone_lengths_over_time(P_list, mapping, s, u):
    L = {n: [] for n in mapping}
    for P in P_list:
        for n, (a, b) in mapping.items():
            L[n].append(float(np.hypot(*(proj(P, b, s, u) - proj(P, a, s, u)))))
    return {n: np.array(v) for n, v in L.items()}


def auto_azimuth(P_list, mapping, s_fn, refidx=0, step=15):
    best = None
    for az in range(0, 360, step):
        s, u = s_fn(az)
        L = bone_lengths_over_time(P_list, mapping, s, u)
        score = float(np.mean([np.abs(L[n] / max(L[n][refidx], 1e-6) - 1).mean() for n in L]))
        if best is None or score < best[0]:
            best = (score, az)
    return best[1], best[0]


def to_clip(rig, parts, bvh, mapping, frames, ref_frame, azimuth, mirror, fps, root_motion=False):
    """Lay the performer's motion onto the rig's rest pose.

    Per part: the bone's world-angle change from the reference frame (2D, in the
    camera) becomes a rotation of the rig's own rest bone; the bone's projected
    length ratio scales it (foreshortening survives); the root translates by the
    hips' motion scaled to the rig. Children sit where FK puts them."""
    Pref = joint_positions(bvh, ref_frame)
    P_list = [joint_positions(bvh, f) for f in frames]
    if azimuth == "auto":
        azimuth, score = auto_azimuth(P_list, mapping,
                                      lambda az: camera_axes(Pref, az, mirror), refidx=0)
        print("auto azimuth: %d deg (mean bone-length change %.1f%%)" % (azimuth, 100 * score))
    s, u = camera_axes(Pref, float(azimuth), mirror)

    # rig rest bones: pivot from the rig, tip = farthest authored texel
    rest_tip, rest_len, rest_ang = {}, {}, {}
    for p in rig.parts:
        n = p["name"]
        ys, xs = np.where(parts.layer[n][:, :, 3] > riglib.ALPHA_CUT)
        px, py = p["pivot"]
        far = int(np.argmax(np.hypot(xs + 0.5 - px, ys + 0.5 - py)))
        rest_tip[n] = np.array([xs[far] + 0.5, ys[far] + 0.5, 1.0])
        v = rest_tip[n][:2] - np.array(p["pivot"], dtype=float)
        rest_len[n] = float(np.hypot(*v))
        rest_ang[n] = math.degrees(math.atan2(v[1], v[0]))

    ref2 = {n: (proj(Pref, a, s, u), proj(Pref, b, s, u)) for n, (a, b) in mapping.items()}
    ref_ang = {n: math.degrees(math.atan2(*(b - a)[::-1])) for n, (a, b) in ref2.items()}
    ref_len = {n: float(np.hypot(*(b - a))) for n, (a, b) in ref2.items()}

    # root scale: the rig's torso length over the performer's, in the camera
    root = next(p["name"] for p in rig.parts if not p.get("parent"))
    scale = rest_len["torso"] / max(ref_len["torso"], 1e-6) if "torso" in ref_len else 1.0

    def wrap(d):
        return (d + 180.0) % 360.0 - 180.0

    order, seen = [], set()

    def visit(n):
        if n in seen:
            return
        seen.add(n)
        if rig.by_name[n].get("parent"):
            visit(rig.by_name[n]["parent"])
        order.append(n)
    for p in rig.parts:
        visit(p["name"])

    hips_ref = proj(Pref, mapping[root][0], s, u)
    frames_out = []
    for P in [Pref] + P_list:                    # frame 0 is the rest pose
        dw, rat = {}, {}
        for n in mapping:
            a2, b2 = proj(P, mapping[n][0], s, u), proj(P, mapping[n][1], s, u)
            v = b2 - a2
            dw[n] = wrap(math.degrees(math.atan2(v[1], v[0])) - ref_ang[n])
            rat[n] = float(np.hypot(*v)) / max(ref_len[n], 1e-6)
        pose = {}
        for n in order:
            par = rig.by_name[n].get("parent")
            local = dw.get(n, 0.0) - (dw.get(par, 0.0) if par else 0.0) if n in dw else 0.0
            pz = {"rot": local} if abs(local) > 1e-9 else {}
            if not par and n in mapping and root_motion:
                d = (proj(P, mapping[n][0], s, u) - hips_ref) * scale
                pz["dx"], pz["dy"] = float(d[0]), float(d[1])
            if pz:
                pose[n] = pz
        cache, fr = {}, {}
        for p in rig.parts:
            n = p["name"]
            M = riglib.world_matrix(rig, n, pose, cache)
            pv = (M @ np.array([*p["pivot"], 1.0]))[:2]
            tip = M @ rest_tip[n]
            tp = pv + (tip[:2] - pv) * rat.get(n, 1.0)       # foreshortening survives
            fr[n] = dict(pivot=[float(pv[0]), float(pv[1])], tip=[float(tp[0]), float(tp[1])])
        frames_out.append(fr)
    return dict(fps=fps, frames=frames_out, azimuth=float(azimuth))


# ------------------------------------------------------------------ cli

def load_map(path):
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: tuple(v) for k, v in m.items() if not k.startswith("_")}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("bvh", type=Path)
    s.add_argument("--joint", default="RightHand")
    s.add_argument("--top", type=int, default=6)
    c = sub.add_parser("clip")
    c.add_argument("bvh", type=Path)
    c.add_argument("rig", type=Path)
    c.add_argument("map", type=Path)
    c.add_argument("--start", type=int, required=True)
    c.add_argument("--end", type=int, required=True)
    c.add_argument("--step", type=int, default=5)
    c.add_argument("--ref-frame", type=int, default=0)
    c.add_argument("--azimuth", default="auto")
    c.add_argument("--mirror", action="store_true")
    c.add_argument("--root-motion", action="store_true", help="carry the hips' travel into pelvis dx/dy")
    c.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    bvh = Bvh(args.bvh)
    if args.cmd == "scan":
        h, peaks = scan(bvh, args.joint, top=args.top)
        print("%s: %d frames at %.0f fps (%.1f s)" % (args.bvh.name, bvh.nframes, bvh.fps, bvh.nframes / bvh.fps))
        print("%s height above Head, top peaks (frame: height):" % args.joint)
        for k in peaks:
            print("  %5d: %+.1f   (%.2f s)" % (k, h[k], k / bvh.fps))
        return
    import render
    rig = riglib.load_rig(args.rig)
    parts = render.Parts(rig, rig.parts_dir())
    mapping = load_map(args.map)
    frames = list(range(args.start, args.end + 1, args.step))
    az = args.azimuth if args.azimuth == "auto" else float(args.azimuth)
    clip = to_clip(rig, parts, bvh, mapping, frames, args.ref_frame, az, args.mirror,
                   fps=bvh.fps / args.step, root_motion=args.root_motion)
    args.out.write_text(json.dumps(clip), encoding="utf-8")
    print("wrote %s: %d frames (+ rest) at %.1f fps, azimuth %.0f" % (
        args.out, len(frames), clip["fps"], clip["azimuth"]))


if __name__ == "__main__":
    main()

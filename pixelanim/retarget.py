"""Fit a rig's poses to a 2D keypoint clip, reduce them to keys, and say whether the
rig could express the motion at all.

Diffusion or mocap may supply a *curve*; it never supplies a texel. The output
here is rig JSON -- a state you can diff, hand-edit and gate -- and nothing
downstream changes.

A clip is per-part 2D keypoints in cell space, y down, frame 0 being the rest
pose the rig was cut from:

    {"fps": 14, "frames": [{"<part>": {"pivot": [x, y], "tip": [x, y]}, ...}, ...]}

`pivot` is the joint the part rotates about, `tip` the far end of the bone. Mapping
a skeleton from BVH or a pose estimator onto part names is a separate, thin step
and deliberately not in here.

    python pixelanim/retarget.py fit      <rig> <clip.json> [--max-keys 4] [--out state.json]
    python pixelanim/retarget.py selftest <rig> --state strike [--noise 0.3]

Per frame, in FK order:
  * rot  = the bone's world angle change from frame 0, minus what the parent chain
           already contributes, so it is the rig's *local* rot
  * dx,dy = the pivot's offset from where the parent chain puts it, in the
           parent's frame, rounded to whole texels
  * residuals: how much the bone's length changed (foreshortening) and how far the
    pivot sits from where FK puts it after rounding (a limb tearing off its joint)

The residuals are the deformable / needs-new-information classifier. A motion the
rig can express fits tightly; a head turning to profile or a limb pointing at the
camera shows up as a bone that shortens and cannot be rotated back to full length.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

import riglib

FORESHORTEN_TOL = 0.15     # bone length change beyond this is not an in-plane rotation
PIVOT_TOL = 1.0            # texels a pivot may sit from where FK puts it
TEXEL_DEG = 3.0            # one texel of travel reads about as much as this many degrees


# ------------------------------------------------------------------ FK order

def fk_order(rig):
    order, seen = [], set()

    def visit(n):
        if n in seen:
            return
        seen.add(n)
        par = rig.by_name[n].get("parent")
        if par:
            visit(par)
        order.append(n)
    for p in rig.parts:
        visit(p["name"])
    return order


def _ang(v):
    return math.degrees(math.atan2(v[1], v[0]))


def _wrap(d):
    return (d + 180.0) % 360.0 - 180.0


# ------------------------------------------------------------------ fit

def smooth_clip(clip, window):
    """Moving average of every keypoint over `window` frames (odd), clamped at the
    ends. Frame 0 is the rest pose and is left alone. Cuts jitter by ~sqrt(window)
    but rounds off sharp extremes, so use it on dense clips, not on a clip that
    already has only a handful of frames."""
    if window <= 1:
        return clip
    h = window // 2
    fr = clip["frames"]
    out = [fr[0]]
    for i in range(1, len(fr)):
        idx = [min(len(fr) - 1, max(1, j)) for j in range(i - h, i + h + 1)]
        f = {}
        for part in fr[0]:
            f[part] = {k: [float(np.mean([fr[j][part][k][a] for j in idx])) for a in (0, 1)]
                       for k in ("pivot", "tip")}
        out.append(f)
    return dict(clip, frames=out)



def fit_clip(rig, clip, deadband=3.0):
    """Returns per-frame dicts: pose, and residuals (foreshorten, pivot_gap).

    A rotation smaller than `deadband` degrees, or than half a texel of movement
    at the bone's tip if that is larger, is dropped: it is tracker jitter, not
    motion, and on a short bone a fraction of a texel of noise is several
    degrees. Left in, that jitter invents movement on parts the animator held
    still, and once one tore a hole in a frame. Dropping it is self-correcting:
    children are fitted against the parent's *fitted* pose, so they absorb it."""
    frames = clip["frames"]
    rest = frames[0]
    order = fk_order(rig)
    for n in order:
        if n not in rest:
            raise SystemExit("retarget: clip frame 0 has no keypoints for part %s" % n)
    ang0 = {n: _ang(np.subtract(rest[n]["tip"], rest[n]["pivot"])) for n in order}
    len0 = {n: float(np.hypot(*np.subtract(rest[n]["tip"], rest[n]["pivot"]))) for n in order}

    out = []
    for f, fr in enumerate(frames):
        pose, world, fore, gap = {}, {}, {}, {}
        for n in order:
            part = rig.by_name[n]
            par = part.get("parent")
            Mp = world[par] if par else np.eye(3)
            obs_p = np.array([*fr[n]["pivot"], 1.0])
            local = np.linalg.inv(Mp) @ obs_p
            d = local[:2] - np.array(part["pivot"], dtype=float)
            dx, dy = int(round(d[0])), int(round(d[1]))
            v = np.subtract(fr[n]["tip"], fr[n]["pivot"])
            parent_rot = math.degrees(math.atan2(Mp[1, 0], Mp[0, 0]))
            rot = _wrap((_ang(v) - ang0[n]) - parent_rot)
            pz = {}
            floor = max(deadband, math.degrees(math.atan2(0.5, len0[n])) if len0[n] else deadband)
            if abs(rot) >= floor:
                pz["rot"] = round(rot)      # whole degrees
            if dx:
                pz["dx"] = dx
            if dy:
                pz["dy"] = dy
            if pz:
                pose[n] = pz
            world[n] = Mp @ riglib.pose_matrix(pz, part["pivot"])
            fk_pivot = world[n] @ np.array([*part["pivot"], 1.0])
            gap[n] = float(np.hypot(*(fk_pivot[:2] - np.array(fr[n]["pivot"]))))
            fore[n] = float(np.hypot(*v)) / len0[n] - 1.0 if len0[n] else 0.0
        out.append(dict(pose=pose, foreshorten=fore, pivot_gap=gap))
    return out


def classify(fit, frames_from=1):
    """Deformable or needs new information, per frame, with the parts to blame."""
    verdicts = []
    for i, r in enumerate(fit):
        if i < frames_from:
            continue
        bad = sorted(n for n, v in r["foreshorten"].items() if abs(v) > FORESHORTEN_TOL)
        tear = sorted(n for n, v in r["pivot_gap"].items() if v > PIVOT_TOL and n not in bad)
        verdicts.append((i, bad, tear))
    return verdicts


# ------------------------------------------------------------------ keys

def pose_vector(fit):
    """One row per frame: every part's rot, and dx/dy scaled so a texel counts as
    `TEXEL_DEG` degrees of read. Distances between rows are then comparable."""
    names = sorted({k for r in fit for k in r["pose"]})
    cols = []
    for part in names:
        for key, w in (("rot", 1.0), ("dx", TEXEL_DEG), ("dy", TEXEL_DEG)):
            cols.append([w * float(r["pose"].get(part, {}).get(key, 0.0)) for r in fit])
    return np.array(cols).T if cols else np.zeros((len(fit), 0))


def reduce_to_keys(fit, max_keys=4, tolerance=2.0):
    """Reduce a dense curve to the fewest keys that reproduce it.

    Greedy piecewise-linear simplification (Douglas-Peucker, capped): start with
    the rest frame and the last frame, then keep adding the frame the current
    interpolation misses by most, until the worst miss is under `tolerance`
    degrees or there are `max_keys`. That finds extrema *and* slope corners -- a
    monotone ramp with a change of speed has no extremum but does have a key --
    and it stops on error instead of an arbitrary threshold. It is the "key
    poses first, breakdowns second" rule stated as an algorithm. Frame 0 is the
    rest pose and is never returned; the last frame always is.
    """
    n = len(fit)
    V = pose_vector(fit)
    chosen = [0, n - 1]
    while len(chosen) - 1 < max_keys:
        chosen.sort()
        worst, at = 0.0, None
        for lo, hi in zip(chosen[:-1], chosen[1:]):
            for i in range(lo + 1, hi):
                t = (i - lo) / (hi - lo)
                dev = float(np.abs(V[i] - (V[lo] + (V[hi] - V[lo]) * t)).max()) if V.shape[1] else 0.0
                if dev > worst:
                    worst, at = dev, i
        if at is None or worst < tolerance:
            break
        chosen.append(at)
    return sorted(k for k in chosen if k != 0)


def state_from_fit(fit, keys, name, fps, loop=False):
    return dict(name=name, fps=fps, loop=loop,
                frames=[dict(pose=fit[k]["pose"]) for k in keys])


# ------------------------------------------------------------------ synth

def densify(poses, n):
    """Linearly interpolate whole poses n-fold: the smooth 24 fps curve a tracker
    would see between the keys an animator drew. Returns (poses, key_indices)."""
    out, keys = [], []
    for a, b in zip(poses[:-1], poses[1:]):
        for s in range(n):
            t = s / n
            fr = {}
            for part in {*a, *b}:
                pz = {}
                for k in ("rot", "dx", "dy"):
                    va, vb = float(a.get(part, {}).get(k, 0.0)), float(b.get(part, {}).get(k, 0.0))
                    if va or vb:
                        pz[k] = va + (vb - va) * t
                if pz:
                    fr[part] = pz
            out.append(fr)
    out.append(poses[-1])
    keys = [i * n for i in range(len(poses))]
    return out, keys


def synthesize(rig, parts, state_name, noise=0.0, seed=0, dens=1):
    """A ground-truth keypoint clip made from the rig's own state, with frame 0 as
    the rest pose. What a perfect tracker would return, plus optional noise."""
    import render
    st = next(s for s in rig.states if s["name"] == state_name)
    res = riglib.resolve_state(rig, st)
    rng = np.random.default_rng(seed)
    tip = {}
    for p in rig.parts:
        ys, xs = np.where(parts.layer[p["name"]][:, :, 3] > riglib.ALPHA_CUT)
        px, py = p["pivot"]
        far = int(np.argmax(np.hypot(xs + 0.5 - px, ys + 0.5 - py)))
        tip[p["name"]] = np.array([xs[far] + 0.5, ys[far] + 0.5, 1.0])
    poses = [{}] + [r["pose"] for r in res]
    key_idx = list(range(len(poses)))
    if dens > 1:
        poses, key_idx = densify(poses, dens)
    frames = []
    for pose in poses:
        cache, fr = {}, {}
        for p in rig.parts:
            M = riglib.world_matrix(rig, p["name"], pose, cache)
            pv = (M @ np.array([*p["pivot"], 1.0]))[:2]
            tp = (M @ tip[p["name"]])[:2]
            if noise:
                pv = pv + rng.normal(0, noise, 2)
                tp = tp + rng.normal(0, noise, 2)
            fr[p["name"]] = dict(pivot=[float(pv[0]), float(pv[1])], tip=[float(tp[0]), float(tp[1])])
        frames.append(fr)
    return dict(fps=float(st.get("fps", 8)) * dens, frames=frames), res, key_idx


def selftest(rig, state_name, noise, seed, dens=1, foreshorten=None, deadband=3.0, smooth=1):
    import render
    parts = render.Parts(rig, rig.parts_dir())
    clip, truth, key_idx = synthesize(rig, parts, state_name, noise, seed, dens)
    if foreshorten:
        # what a head turning to profile does to a 2D bone: same rotation, shorter
        # projection. Applied to the second half of the clip.
        half = len(clip["frames"]) // 2
        for fr in clip["frames"][half:]:
            k = fr[foreshorten]
            k["tip"] = [k["pivot"][0] + 0.55 * (k["tip"][0] - k["pivot"][0]),
                        k["pivot"][1] + 0.55 * (k["tip"][1] - k["pivot"][1])]
    fit = fit_clip(rig, smooth_clip(clip, smooth), deadband)
    if dens > 1:
        # keys are what matters when the clip is dense: does reduction find the
        # frames the animator drew? (Whole-degree rounding makes pose error moot.)
        want = key_idx[1:]
        keys = reduce_to_keys(fit, max_keys=len(want))
        hit = [k for k in want if any(abs(k - c) <= dens // 2 for c in keys)]
        print("selftest %s.%s dense x%d noise=%.2f texel: %d frames from %d authored keys"
              % (rig.name, state_name, dens, noise, len(fit) - 1, len(want)))
        print("  authored key frames %s" % want)
        print("  reduction chose     %s  -> %d/%d authored keys recovered (within %d frames)"
              % (keys, len(hit), len(want), dens // 2))
        flagged = [v for v in classify(fit) if v[1] or v[2]]
        print("  classifier: %d/%d frames flagged%s" % (
            len(flagged), len(fit) - 1,
            (" -- parts: " + ", ".join(sorted({p for v in flagged for p in v[1] + v[2]}))) if flagged else ""))
        return len(hit), len(want)
    err, worst = [], (0.0, "")
    for i, r in enumerate(fit[1:]):
        for n in {*r["pose"], *truth[i]["pose"]}:
            for key in ("rot", "dx", "dy"):
                a = float(r["pose"].get(n, {}).get(key, 0.0))
                b = float(truth[i]["pose"].get(n, {}).get(key, 0.0))
                err.append(abs(a - b))
                if abs(a - b) > worst[0]:
                    worst = (abs(a - b), "%s.%s frame %d: fitted %.1f, truth %.1f" % (n, key, i, a, b))
    verdicts = classify(fit)
    keys = reduce_to_keys(fit, max_keys=len(truth))
    print("selftest %s.%s noise=%.2f texel  frames=%d" % (rig.name, state_name, noise, len(truth)))
    print("  pose error vs truth: mean %.2f, worst %.2f  (%s)" % (float(np.mean(err)), worst[0], worst[1] or "exact"))
    flagged = [v for v in verdicts if v[1] or v[2]]
    print("  classifier: %d/%d frames flagged as needing new information" % (len(flagged), len(verdicts)))
    print("  keys chosen from %d frames: %s (authored state has %d keys, frames 1..%d)"
          % (len(fit) - 1, [k for k in keys], len(truth), len(truth)))
    return float(np.mean(err)), worst[0], len(flagged), keys


# ------------------------------------------------------------------ cli

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("rig", type=Path)
    f.add_argument("clip", type=Path)
    f.add_argument("--max-keys", type=int, default=4)
    f.add_argument("--tolerance", type=float, default=2.0, help="degrees the key curve may miss by")
    f.add_argument("--name", default="retargeted")
    f.add_argument("--smooth", type=int, default=1, help="moving-average window over keypoints (odd)")
    f.add_argument("--deadband", type=float, default=3.0, help="degrees below which a rotation is jitter")
    f.add_argument("--out", type=Path, default=None)
    s = sub.add_parser("selftest")
    s.add_argument("rig", type=Path)
    s.add_argument("--state", required=True)
    s.add_argument("--noise", type=float, default=0.0, help="keypoint noise, texels (sigma)")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--deadband", type=float, default=3.0)
    s.add_argument("--smooth", type=int, default=1)
    s.add_argument("--foreshorten", default=None, metavar="PART",
                   help="shorten this part's bone by 45%% in the back half, as a turn out of plane would")
    s.add_argument("--densify", type=int, default=1, help="interpolate the authored keys n-fold first")
    args = ap.parse_args()

    rig = riglib.load_rig(args.rig)
    if args.cmd == "selftest":
        selftest(rig, args.state, args.noise, args.seed, args.densify, args.foreshorten, args.deadband, args.smooth)
        return
    clip = json.loads(args.clip.read_text(encoding="utf-8"))
    fit = fit_clip(rig, smooth_clip(clip, args.smooth), args.deadband)
    for i, bad, tear in classify(fit):
        if bad:
            print("frame %d needs new information: %s changed length by more than %d%%"
                  % (i, ", ".join(bad), FORESHORTEN_TOL * 100))
        if tear:
            print("frame %d: %s cannot be reached by rotation and whole-texel translation"
                  % (i, ", ".join(tear)))
    keys = reduce_to_keys(fit, args.max_keys, args.tolerance)
    state = state_from_fit(fit, keys, args.name, float(clip.get("fps", 8)))
    print("keys: frames %s of %d" % (keys, len(fit) - 1))
    text = json.dumps(state, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print("wrote", args.out)
    else:
        print(text)


if __name__ == "__main__":
    main()

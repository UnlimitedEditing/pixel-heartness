"""Mechanical gates. Run after every rig change.

A harness without cheap mechanical gates is a slot machine: every real defect in
this pipeline so far was found by counting, not by looking. Each check below is
a number with a threshold, not a judgement.

    python pixelanim/checks.py pixelanim/examples/skeleton_warrior/rig.json
    python pixelanim/checks.py examples/skeleton_warrior/rig.json --only rest,holes -v

Exit status is the number of failing gates.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

import render
import riglib

CONN8 = np.ones((3, 3), dtype=bool)


def alpha(fr):
    return fr["rgba"][:, :, 3] > riglib.ALPHA_CUT


def enclosed_holes(mask: np.ndarray) -> np.ndarray:
    """Background texels the silhouette completely encloses. This is the direct
    measure of the thing underlap exists to prevent: a part rotating away from
    its neighbour and leaving a window through the body."""
    return ndimage.binary_fill_holes(mask) & ~mask


# ------------------------------------------------------------------- gates

def gate_rest(rig, parts, frames, args):
    """The rest pose must be the source sprite, texel for texel.

    This is the load-bearing invariant of the whole extend-and-hide scheme: if
    every synthesised texel really is covered by a part in front of it, then
    adding underlap cannot change how the character looks standing still. Any
    drift here means growth escaped into open background.
    """
    src, _ = riglib.place_in_cell(Image.open(rig.data["source"]), rig.cell)
    got, _, _ = render.compose(rig, parts, {})
    sa, ga = src[:, :, 3] > riglib.ALPHA_CUT, got[:, :, 3] > riglib.ALPHA_CUT
    shape_diff = int((sa ^ ga).sum())
    both = sa & ga
    colour_diff = int((src[:, :, :3][both] != got[:, :, :3][both]).any(axis=-1).sum())
    lines = []
    if shape_diff:
        extra = ga & ~sa
        lines.append("%d texels differ in silhouette (%d invented, %d lost)"
                     % (shape_diff, int(extra.sum()), int((sa & ~ga).sum())))
        for y, x in list(zip(*np.where(ga ^ sa)))[:8]:
            lines.append("  (%d,%d)" % (x, y))
    if colour_diff:
        lines.append("%d texels differ in colour" % colour_diff)
    return (shape_diff + colour_diff) == 0, lines or ["rest pose is bit-identical to the source"]


def gate_palette(rig, parts, frames, args):
    """A deformation must not invent colours. Nearest-neighbour sampling
    guarantees it today; the gate is here so that any future primitive that
    blends breaks loudly instead of silently."""
    src, _ = riglib.place_in_cell(Image.open(rig.data["source"]), rig.cell)
    ok_cols = set(map(tuple, src[:, :, :3][src[:, :, 3] > riglib.ALPHA_CUT].reshape(-1, 3)))
    bad = {}
    for i, fr in enumerate(frames):
        a = alpha(fr)
        for c in set(map(tuple, fr["rgba"][:, :, :3][a].reshape(-1, 3))) - ok_cols:
            bad.setdefault(c, []).append(i)
    lines = ["%s in frames %s" % (c, f[:6]) for c, f in list(bad.items())[:8]]
    return not bad, lines or ["%d frames use only the source's %d colours" % (len(frames), len(ok_cols))]


def gate_holes(rig, parts, frames, args):
    """No frame may tear a window through the body.

    Two different things both read as "a hole" when you just count enclosed
    background, and only one of them is a bug:

      tear        a texel that was *body* in the rest pose and is now an
                  enclosed window. A part rotated off its neighbour and nothing
                  was underneath. This is what underlap exists to prevent, and
                  it is what this gate fails on.

      negative    a texel that was already background at rest -- the notch
                  between a hanging arm and the ribs -- which a swinging part
                  merely sealed at both ends. The art always looked like that;
                  only its connection to the outside changed. Reported, not failed.
    """
    rest, _, _ = render.compose(rig, parts, {})
    rest_a = rest[:, :, 3] > riglib.ALPHA_CUT
    worst, tears_total, neg_total = [], 0, 0
    for i, fr in enumerate(frames):
        h = enclosed_holes(alpha(fr))
        # ground_lock may have slid the frame, so compare against a rest pose
        # slid the same way, or the shift alone would look like torn body
        ref = np.roll(rest_a, fr.get("offset", (0, 0))[1], axis=0)
        # Classify each hole as a region, not texel by texel. A notch that was
        # always there usually swallows a texel or two that happened to be body
        # at rest as it seals; calling those an independent tear is noise, and
        # it is the *region* the viewer reads as one window either way.
        cc, k = ndimage.label(h, structure=CONN8)
        tear = np.zeros_like(h)
        for c in range(1, k + 1):
            comp = cc == c
            if int((comp & ref).sum()) * 2 > int(comp.sum()):
                tear |= comp
        neg = h & ~tear
        tears_total += int(tear.sum())
        neg_total += int(neg.sum())
        if int(tear.sum()) > args.max_holes:
            ys, xs = np.where(tear)
            worst.append("frame %2d %-8s tore %d texels, first at (%d,%d)"
                         % (i, fr["state"], int(tear.sum()), xs[0], ys[0]))
    if worst:
        return False, worst[:12] + (["..."] if len(worst) > 12 else [])
    return True, ["%d frames, 0 torn texels (limit %d/frame); %d enclosed texels were "
                  "already background at rest" % (len(frames), args.max_holes, neg_total)]


def gate_floaters(rig, parts, frames, args):
    """No frame may show a detached island of invented texels.

    Found by eye before it was found by counting, which is the failure this gate
    exists to stop repeating. Underlap used to dilate the pelvis across the bare
    background between the ribs and the sword arm, landing a blob of invented hip
    texels out under the hand. Hidden at rest, so `rest` stayed green -- but the
    pelvis is the unposed root, so the blob sat there motionless while the arm
    swung past it.

    The signature is exact: a connected component of one part's *visible* texels
    that contains no authored texel of that part. Real underlap is always
    anchored to art the viewer can see.
    """
    names = [p["name"] for p in rig.parts]
    bad = []
    for i, fr in enumerate(frames):
        owner, synth = fr["owner"], fr["synth"]
        for pi, name in enumerate(names, start=1):
            vis = owner == pi
            if not vis.any():
                continue
            cc, n = ndimage.label(vis, structure=CONN8)
            for c in range(1, n + 1):
                comp = cc == c
                if int(comp.sum()) > args.max_floater and not (comp & ~synth).any():
                    ys, xs = np.where(comp)
                    bad.append("frame %2d %-8s %d invented %s texels detached at (%d,%d)"
                               % (i, fr["state"], int(comp.sum()), name, xs[0], ys[0]))
    return not bad, bad[:12] or ["no detached islands of invented texels in %d frames" % len(frames)]


def gate_border(rig, parts, frames, args):
    """ART_SPEC needs a clear texel on every side: the engine dilates the
    outline into it, so a limb touching the cell edge loses its outline."""
    bad = []
    for i, fr in enumerate(frames):
        a = alpha(fr)
        edges = [n for n, hit in (("left", a[:, 0].any()), ("right", a[:, -1].any()),
                                  ("top", a[0, :].any()), ("bottom", a[-1, :].any())) if hit]
        if edges:
            bad.append("frame %2d %-8s touches %s" % (i, fr["state"], ", ".join(edges)))
    return not bad, bad or ["%d frames all clear of the cell border" % len(frames)]


def gate_wholetexel(rig, parts, frames, args):
    """Motion must land on whole texels. Sub-texel drift makes edge texels
    toggle under the engine's post pass and reads as flicker, not motion."""
    bad = []
    for state in rig.states:
        for j, f in enumerate(state["frames"]):
            for part, pose in f.get("pose", {}).items():
                for k in ("dx", "dy"):
                    v = pose.get(k)
                    if v is not None and float(v) != round(float(v)):
                        bad.append("%s frame %d: %s.%s = %s" % (state["name"], j, part, k, v))
    return not bad, bad or ["every translation in the rig is a whole number of texels"]


def gate_ground(rig, parts, frames, args):
    """Feet stay on the floor unless the state is deliberately airborne.
    Rotating a limb about a joint above it swings the far end down by
    r*(1-cos t), which is how the first walk cycle sank through the ground."""
    floor = rig.cell[1] - 2
    airborne = set(rig.data.get("airborne_states", []))
    bad = []
    for i, fr in enumerate(frames):
        if fr["state"] in airborne:
            continue
        a = alpha(fr)
        rows = np.where(a.any(axis=1))[0]
        if len(rows) and int(rows[-1]) != floor:
            bad.append("frame %2d %-8s lowest texel on row %d, floor is %d"
                       % (i, fr["state"], int(rows[-1]), floor))
    return not bad, bad or ["every frame's lowest texel is on row %d" % floor]


def gate_distinct(rig, parts, frames, args):
    """Silhouette is the whole game at this size, and interruptibility needs
    pose-distinct states: consecutive keys that read the same as a black shape
    are a failed pose, not a subtle one."""
    soft, worst = [], []
    i = 0
    for state in rig.states:
        n = len(state["frames"])
        # per-state, because the requirement is not one number: an idle is
        # deliberately low-amplitude, an attack has to show its commit point
        bar = float(state.get("min_distinct", args.min_distinct))
        lo = 1e9
        # a looping state wraps, so last->first is a key-to-key transition too:
        # two near-identical keys either side of the loop point read as a stall
        pairs = [(j, j + 1) for j in range(i, i + n - 1)]
        if state.get("loop", True) and n > 1:
            pairs.append((i + n - 1, i))
        for j, k in pairs:
            a, b = alpha(frames[j]), alpha(frames[k])
            pct = int((a ^ b).sum()) * 100.0 / max(1, int(a.sum()))
            lo = min(lo, pct)
            if pct < bar:
                soft.append("frames %d-%d %-8s differ by %.1f%% of the silhouette, bar is %.1f%%"
                            % (j, k, state["name"], pct, bar))
        if n > 1:
            worst.append("%s %.1f%%/%.1f" % (state["name"], lo, bar))
        i += n
    return not soft, soft or ["closest consecutive keys per state (actual/bar): " + "  ".join(worst)]


def gate_synth(rig, parts, frames, args):
    """Report how much of each frame the viewer actually sees that was invented
    rather than authored. Not a pass/fail -- a number to watch. A frame that is
    mostly synthesised is a frame to look at."""
    lines, worst = [], 0.0
    for i, fr in enumerate(frames):
        a = alpha(fr)
        n, tot = int(fr["synth"].sum()), max(1, int(a.sum()))
        pct = n * 100.0 / tot
        worst = max(worst, pct)
        if pct >= args.warn_synth:
            lines.append("frame %2d %-8s %d of %d visible texels invented (%.1f%%)"
                         % (i, fr["state"], n, tot, pct))
    return True, lines or ["worst frame is %.1f%% invented texels" % worst]


def gate_agree(rig, parts, frames, args):
    """Python render.py and Aseprite rig.lua must produce the same frames. They
    implement the same maths twice; this is the only thing keeping them honest.

    Compares the frames just rendered in memory against rig.lua's own strip
    (`ase_strip_path`), alpha and colour. Those are different files by
    construction: when both renderers wrote `strip_file` this gate compared a
    file with itself and passed whatever rig.lua did. A strip older than the rig
    file or the parts manifest is stale and fails, since it cannot say anything
    about the current rig.
    """
    strip = rig.ase_strip_path()
    if not strip.is_file():
        return True, ["SKIPPED: no Aseprite strip at %s (run rig.lua mode=build)" % strip]
    newest = max(rig.path.stat().st_mtime, (rig.parts_dir() / "manifest.json").stat().st_mtime)
    if strip.stat().st_mtime < newest:
        return False, ["Aseprite strip %s is older than the rig or parts -- rebuild it" % strip.name]
    CW, CH = rig.cell
    im = np.array(Image.open(strip).convert("RGBA"))
    if im.shape[0] != CH or im.shape[1] != CW * len(frames):
        return False, ["Aseprite strip is %dx%d, expected %dx%d"
                       % (im.shape[1], im.shape[0], CW * len(frames), CH)]
    bad = []
    for i, fr in enumerate(frames):
        cell = im[:, i * CW:(i + 1) * CW]
        a_ase, a_py = cell[:, :, 3] > riglib.ALPHA_CUT, alpha(fr)
        shape = int((a_ase ^ a_py).sum())
        both = a_ase & a_py
        colour = int((cell[:, :, :3][both] != fr["rgba"][:, :, :3][both]).any(axis=1).sum())
        if shape or colour:
            bad.append("frame %2d: %d texels differ in shape, %d in colour" % (i, shape, colour))
    return not bad, bad[:10] or ["%d frames match the Aseprite build, shape and colour" % len(frames)]


GATES = [("rest", gate_rest), ("palette", gate_palette), ("holes", gate_holes),
         ("floaters", gate_floaters), ("border", gate_border), ("wholetexel", gate_wholetexel), ("ground", gate_ground),
         ("distinct", gate_distinct), ("synth", gate_synth), ("agree", gate_agree)]


def run(rig_path, args):
    rig = riglib.load_rig(rig_path)
    parts = render.Parts(rig, args.parts or rig.parts_dir())
    frames = render.render_all(rig, parts)
    wanted = set(args.only.split(",")) if args.only else None
    fails = 0
    for name, fn in GATES:
        if wanted and name not in wanted:
            continue
        ok, lines = fn(rig, parts, frames, args)
        fails += 0 if ok else 1
        print("%s %-11s %s" % ("PASS" if ok else "FAIL", name, lines[0]))
        if args.verbose or not ok:
            for extra in lines[1:]:
                print("                 " + extra)
    return fails


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rig", type=Path)
    ap.add_argument("--parts", type=Path, default=None)
    ap.add_argument("--only", default=None, help="comma-separated gate names")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--max-holes", type=int, default=0)
    ap.add_argument("--max-floater", type=int, default=0,
                    help="largest detached island of invented texels to tolerate")
    ap.add_argument("--min-distinct", type=float, default=2.0, help="percent of silhouette")
    ap.add_argument("--warn-synth", type=float, default=15.0)
    args = ap.parse_args()
    raise SystemExit(run(args.rig, args))


if __name__ == "__main__":
    main()

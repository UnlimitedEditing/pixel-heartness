"""Pose the parts and composite a frame strip, in Python.

`rig.lua` is still the Aseprite authoring path; this is the same maths in a form
the gates and the agent loop can call directly, so a rig change can be built,
measured and looked at without launching Aseprite. The two must agree texel for
texel -- `checks.py agree` compares them.

Every part carries a `synth` provenance mask through the same transform as its
pixels, so a gate can ask "which visible texels were invented?" of any frame.

    python pixelanim/render.py pixelanim/examples/skeleton_warrior/rig.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

import riglib

CONN8 = np.ones((3, 3), dtype=bool)


class Parts:
    """Part layers produced by segment.py, plus their provenance masks."""

    def __init__(self, rig: riglib.Rig, parts_dir: Path):
        self.dir = Path(parts_dir)
        man_path = self.dir / "manifest.json"
        if not man_path.is_file():
            raise SystemExit("render: no parts at %s -- run segment.py first" % self.dir)
        self.manifest = json.loads(man_path.read_text(encoding="utf-8"))
        self.cell = tuple(self.manifest["cell"])
        if self.cell != tuple(rig.cell):
            raise SystemExit("render: parts are %s but rig cell is %s -- re-run segment.py"
                             % (self.cell, tuple(rig.cell)))
        self.layer, self.synth = {}, {}
        for entry in self.manifest["parts"]:
            n = entry["name"]
            self.layer[n] = np.array(Image.open(self.dir / entry["layer"]).convert("RGBA"))
            self.synth[n] = np.array(Image.open(self.dir / entry["synth"]).convert("RGBA"))[:, :, 3] > 127
        # Part variants: authored alternate art for a part, swapped in per frame
        # with `pose[part].variant`. Drawn as a full-size sprite the same size as
        # the source, so it lines up by the same placement rule. Nothing in it is
        # invented, so its synth mask is empty.
        self.variant_layer = {}
        for p in rig.parts:
            for v, f in p.get("variants", {}).items():
                arr, _ = riglib.place_in_cell(Image.open(f), rig.cell)
                self.variant_layer[(p["name"], v)] = arr
        missing = [p["name"] for p in rig.parts if p["name"] not in self.layer]
        if missing:
            raise SystemExit("render: parts dir has no layer for %s" % ", ".join(missing))


def compose(rig: riglib.Rig, parts: Parts, pose: dict, offset=(0, 0), cull=True, squash=0.0, yaw=0.0):
    """One frame. Returns (rgba, synth_visible, owner): `synth_visible` is True
    where the winning texel came from synthesised fill rather than authored art,
    and `owner` is the 1-based index into rig.parts of whichever part won.

    `offset` post-translates every part by whole texels; ground_lock uses it.
    `squash` scales the whole frame about the rig's squash base, volume-preserving.

    `cull` drops any visible component of a part that consists solely of
    synthesised texels. Underlap is meant to be revealed *attached* to the art it
    extends; a patch that surfaces with no authored texel of its own part beside
    it is a stray, and it reads as one -- it does not move with anything, because
    the part it belongs to is somewhere else entirely. This enforces at render
    time exactly what `checks.py floaters` asserts.
    """
    CW, CH = rig.cell
    shift = np.array([[1.0, 0.0, float(offset[0])],
                      [0.0, 1.0, float(offset[1])],
                      [0.0, 0.0, 1.0]])
    if squash:
        shift = shift @ riglib.squash_matrix(squash, rig.squash_base())
    order = list(range(len(rig.parts)))
    if yaw:
        ym, order = riglib.yaw_matrix(rig, parts, yaw)
        shift = shift @ ym
    cache = {}
    layers = []
    for p in rig.parts:                      # layers stay in rig order; `order` sorts them below
        n = p["name"]
        m = shift @ riglib.world_matrix(rig, n, pose, cache)
        v = pose.get(n, {}).get("variant")
        if v:
            if (n, v) not in parts.variant_layer:
                raise SystemExit("render: part %s has no variant '%s'" % (n, v))
            layer = parts.variant_layer[(n, v)]
            synth = np.zeros((CH, CW), dtype=bool)
        else:
            layer, synth = parts.layer[n], parts.synth[n]
        layers.append((riglib.sample_nearest(layer, m, rig.cell),
                       riglib.sample_mask_nearest(synth, m, rig.cell)))

    drop = [np.zeros((CH, CW), dtype=bool) for _ in layers]
    for _ in range(4):                       # converges in one or two passes
        out = np.zeros((CH, CW, 4), dtype=np.uint8)
        synth_vis = np.zeros((CH, CW), dtype=bool)
        owner = np.zeros((CH, CW), dtype=np.int32)   # 1-based index into rig.parts
        for i in order:                      # backmost first; later parts win
            px, sm = layers[i]
            hit = (px[:, :, 3] > riglib.ALPHA_CUT) & ~drop[i]
            out[hit] = px[hit]
            synth_vis[hit] = sm[hit]
            owner[hit] = i + 1
        if not cull:
            break
        again = False
        for i in range(len(layers)):
            vis = owner == i + 1
            if not vis.any():
                continue
            cc, k = ndimage.label(vis, structure=CONN8)
            for c in range(1, k + 1):
                comp = cc == c
                if not (comp & ~synth_vis).any():   # no authored texel anchors it
                    drop[i] |= comp
                    again = True
        if not again:
            break
    return out, synth_vis, owner


def ground_lock(rig: riglib.Rig, parts: Parts, pose: dict, squash=0.0):
    """Slide the whole frame vertically, in whole texels, so the lowest texel
    lands on the floor row.

    Rotating a limb about a joint above it moves its far end vertically by
    `x*sin(t) + y*(cos(t)-1)` -- and for a foot that sits sideways of the hip the
    first term dominates, so the "pair any leg rot with dy:-1" rule of thumb is
    both necessary and wrong by a texel depending on which way the leg swings.
    That is a mechanical constraint no prompt would reliably supply, so it is
    enforced here by construction instead of being written down as advice.
    """
    if not rig.data.get("ground_lock", True):
        return (0, 0)
    floor = rig.cell[1] - 2
    rgba, _, _ = compose(rig, parts, pose, squash=squash)
    rows = np.where((rgba[:, :, 3] > riglib.ALPHA_CUT).any(axis=1))[0]
    if not len(rows):
        return (0, 0)
    return (0, int(floor - rows[-1]))


def render_all(rig: riglib.Rig, parts: Parts):
    """Flatten every state into frames. Mirrors rig.lua: `hold` lengthens a
    frame's duration rather than duplicating it."""
    airborne = set(rig.data.get("airborne_states", []))
    frames = []
    for state in rig.states:
        fps = float(state.get("fps", 8))
        first = len(frames)
        resolved = riglib.resolve_state(rig, state)
        for fr, rs in zip(state["frames"], resolved):
            pose, sq, yw = rs["pose"], rs["squash"], rs.get("yaw", 0.0)
            off = (0, 0) if state["name"] in airborne else ground_lock(rig, parts, pose, sq)
            rgba, synth, owner = compose(rig, parts, pose, off, squash=sq, yaw=yw)
            frames.append(dict(rgba=rgba, synth=synth, owner=owner, state=state["name"],
                               pose=pose, squash=sq, offset=off,
                               ms=int(1000.0 / fps * int(fr.get("hold", 1)))))
        frames[first]["tag_from"] = first
        frames[-1]["tag_to"] = len(frames) - 1
    return frames


def tags_of(rig: riglib.Rig, frames):
    tags, i = [], 0
    for state in rig.states:
        n = len(state["frames"])
        tags.append(dict(name=state["name"], from_=i, to=i + n - 1,
                         loop=state.get("loop", True)))
        i += n
    return tags


def write_strip(rig: riglib.Rig, frames, strip_path: Path):
    CW, CH = rig.cell
    strip = Image.new("RGBA", (CW * len(frames), CH), (0, 0, 0, 0))
    for i, fr in enumerate(frames):
        strip.paste(Image.fromarray(fr["rgba"], "RGBA"), (i * CW, 0))
    strip_path.parent.mkdir(parents=True, exist_ok=True)
    strip.save(strip_path)

    # Aseprite JSON_ARRAY shape, so the existing packer reads this unchanged
    data = dict(
        frames=[dict(filename="%s %d" % (rig.name, i),
                     frame=dict(x=i * CW, y=0, w=CW, h=CH),
                     rotated=False, trimmed=False,
                     spriteSourceSize=dict(x=0, y=0, w=CW, h=CH),
                     sourceSize=dict(w=CW, h=CH), duration=fr["ms"])
                for i, fr in enumerate(frames)],
        meta=dict(app="pixelanim/render.py", version="1",
                  image=strip_path.name, format="RGBA8888",
                  size=dict(w=CW * len(frames), h=CH), scale="1",
                  frameTags=[dict(name=t["name"], **{"from": t["from_"]}, to=t["to"],
                                  direction="forward", color="#000000ff")
                             for t in tags_of(rig, frames)]))
    strip_path.with_suffix(".json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    return strip


def build(rig_path, parts_dir=None, strip_path=None, quiet=False):
    rig = riglib.load_rig(rig_path)
    parts = Parts(rig, parts_dir or rig.parts_dir())
    frames = render_all(rig, parts)
    out = Path(strip_path) if strip_path else rig.path_of("strip_file")
    write_strip(rig, frames, out)
    if not quiet:
        print("built %d frames across %d states -> %s" % (len(frames), len(rig.states), out))
        for t in tags_of(rig, frames):
            print("  %-10s frames %d-%d" % (t["name"], t["from_"], t["to"]))
    return rig, parts, frames


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rig", type=Path)
    ap.add_argument("--parts", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None, help="strip png (default: rig strip_file)")
    args = ap.parse_args()
    build(args.rig, args.parts, args.out)


if __name__ == "__main__":
    main()

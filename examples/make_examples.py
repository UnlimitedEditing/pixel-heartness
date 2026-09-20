"""Generate the two synthetic example subjects: a slime (squash/stretch) and a
wisp with a chained tail (lag). Synthetic on purpose -- the geometry is known, so
seeds and pivots are exact instead of read off a grid.

    python examples/make_examples.py
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent


def save(path, a):
    Image.fromarray(a, "RGBA").save(path)


def blank(w, h):
    return np.zeros((h, w, 4), np.uint8)


def paint(a, mask, rgb):
    a[mask] = (*rgb, 255)


def disc_mask(w, h, cx, cy, rx, ry):
    yy, xx = np.mgrid[0:h, 0:w]
    return ((xx + 0.5 - cx) / rx) ** 2 + ((yy + 0.5 - cy) / ry) ** 2 <= 1.0


def outline(a):
    """1-texel dark outline around every opaque texel, inside the sprite."""
    op = a[:, :, 3] > 127
    pad = np.pad(op, 1)
    inner = pad[1:-1, 1:-1] & pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:]
    edge = op & ~inner
    a[edge] = (18, 30, 22, 255)


def place(a, cell):
    CW, CH = cell
    h, w = a.shape[:2]
    return (CW - w) // 2, CH - h


# ------------------------------------------------------------------ slime
def slime():
    d = HERE / "slime"
    d.mkdir(exist_ok=True)
    W, H, cell = 20, 15, (32, 32)          # last sprite row is clear: floor is CH-2
    a = blank(W, H)
    body = disc_mask(W, H - 1, 10, 7.6, 9.6, 6.6)
    body[:, :] &= np.arange(H - 1)[:, None] >= 1
    m = np.zeros((H, W), bool); m[:H - 1] = body
    paint(a, m, (96, 204, 104))
    paint(a, m & (np.arange(H)[:, None] >= 10), (56, 152, 84))
    hl = np.zeros((H, W), bool); hl[3:5, 5:8] = True
    paint(a, hl & m, (176, 244, 160))
    outline(a)
    eyes = np.zeros((H, W), bool); eyes[6:8, 6:8] = True; eyes[6:8, 12:14] = True
    paint(a, eyes, (250, 250, 240))
    for x in (7, 13):
        a[7, x] = (20, 20, 30, 255)
    save(d / "slime.png", a)
    # blink variant: same texels as the eyes, redrawn closed -- body green above,
    # the outline colour as the lid line. Colours come from the source palette.
    bl = blank(W, H)
    for x in (6, 7, 12, 13):
        bl[6, x] = (96, 204, 104, 255)
        bl[7, x] = (18, 30, 22, 255)
    save(d / "slime_eyes_blink.png", bl)
    ox, oy = place(a, cell)
    ex = np.zeros((H, W), bool); ex[6:8, 6:8] = True; ex[6:8, 12:14] = True
    rig = {
        "name": "slime", "source": "slime.png",
        "parts_file": "out/slime_parts.aseprite", "anim_file": "out/slime_anim.aseprite",
        "strip_file": "out/slime_strip.png",
        "cell": list(cell), "underlap": 4, "symmetry_x": ox + 10,
        "airborne_states": ["air"],
        "_note": "squash/stretch demo. `squash` is per frame: >0 flattens, <0 stretches, area conserved about the floor line under the root.",
        "parts": [
            {"name": "body", "rect": [ox, oy, W, H], "pivot": [ox + 10, oy + H - 1],
             "seeds": [[ox + 10, oy + 11], [ox + 4, oy + 8], [ox + 15, oy + 8], [ox + 10, oy + 6], [ox + 10, oy + 4]]},
            {"name": "eyes", "rect": [ox + 6, oy + 6, 8, 2], "pivot": [ox + 10, oy + 7],
             "parent": "body", "seeds": [[ox + 6, oy + 6], [ox + 12, oy + 6]],
             "variants": {"blink": "slime_eyes_blink.png"}},
        ],
        "states": [
            {"name": "idle", "fps": 4, "loop": True, "min_distinct": 0.5, "frames": [
                {"squash": 0.0}, {"squash": 0.08},
                {"squash": 0.0, "pose": {"eyes": {"variant": "blink"}}}, {"squash": -0.05}]},
            {"name": "windup", "fps": 10, "loop": False, "frames": [
                {"squash": 0.12}, {"squash": 0.30, "hold": 2}]},
            {"name": "air", "fps": 8, "loop": False, "frames": [
                {"squash": -0.30, "pose": {"body": {"dy": -6}}},
                {"squash": -0.12, "pose": {"body": {"dy": -10}}},
                {"squash": 0.0, "pose": {"body": {"dy": -8}}}]},
            {"name": "land", "fps": 10, "loop": False, "frames": [
                {"squash": 0.34, "pose": {"eyes": {"variant": "blink"}}}, {"squash": -0.12}, {"squash": 0.10}, {"squash": 0.0}]},
        ],
    }
    (d / "rig.json").write_text(json.dumps(rig, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ wisp
def wisp():
    d = HERE / "wisp"
    d.mkdir(exist_ok=True)
    W, H, cell = 12, 35, (40, 44)
    a = blank(W, H)
    # (name, y0, y1, half-width, colour): head then three tapering tail segments
    segs = [("head", 0, 11, 5.5, (150, 190, 255)),
            ("t1", 11, 18, 4.0, (110, 160, 240)),
            ("t2", 18, 25, 3.0, (80, 130, 220)),
            ("t3", 25, 34, 2.0, (60, 100, 200))]
    for name, y0, y1, hw, col in segs:
        if name == "head":
            m = disc_mask(W, H, 6, 5.5, 5.5, 5.5)
        else:
            m = np.zeros((H, W), bool)
            for y in range(y0, y1):
                f = 1 - (y - y0) / (y1 - y0) * 0.35
                w = hw * f
                m[y, int(round(6 - w)):int(round(6 + w))] = True
        paint(a, m & (a[:, :, 3] == 0), col)
    outline(a)
    eyes = np.zeros((H, W), bool); eyes[5:7, 3:5] = True; eyes[5:7, 7:9] = True
    paint(a, eyes, (255, 255, 255))
    save(d / "wisp.png", a)
    ox, oy = place(a, cell)
    ax = ox + 6
    rig = {
        "name": "wisp", "source": "wisp.png",
        "parts_file": "out/wisp_parts.aseprite", "anim_file": "out/wisp_anim.aseprite",
        "strip_file": "out/wisp_strip.png",
        "cell": list(cell), "underlap": 4, "symmetry_x": ax,
        "ground_lock": False, "airborne_states": ["sway", "flick"], "lag_max_deg": 30,
        "_note": "chain-lag demo. Only the head is animated; each tail segment has `lag` and trails its parent, cascading down the chain.",
        "parts": [
            {"name": "t3", "rect": [ox + 4, oy + 25, 4, 9], "pivot": [ax, oy + 25], "parent": "t2", "lag": 0.75,
             "seeds": [[ax, oy + 29]]},
            {"name": "t2", "rect": [ox + 3, oy + 18, 6, 7], "pivot": [ax, oy + 18], "parent": "t1",
             "lag": 0.75, "seeds": [[ax, oy + 21]]},
            {"name": "t1", "rect": [ox + 2, oy + 11, 8, 7], "pivot": [ax, oy + 11], "parent": "head",
             "lag": 0.75, "seeds": [[ax, oy + 14]]},
            {"name": "head", "rect": [ox, oy, 12, 11], "pivot": [ax, oy + 11],
             "seeds": [[ax, oy + 3], [ax - 3, oy + 5], [ax + 3, oy + 5]]},
        ],
        "states": [
            {"name": "sway", "fps": 6, "loop": True, "frames": [
                {"pose": {"head": {"rot": -8}}}, {"pose": {"head": {"rot": 0}}},
                {"pose": {"head": {"rot": 8}}}, {"pose": {"head": {"rot": 0}}}]},
            {"name": "flick", "fps": 10, "loop": True, "frames": [
                {"pose": {"head": {"rot": 0}}}, {"pose": {"head": {"rot": -8}}},
                {"pose": {"head": {"rot": 0}}}, {"pose": {"head": {"rot": 8}}}]},
        ],
    }
    (d / "rig.json").write_text(json.dumps(rig, indent=2), encoding="utf-8")


if __name__ == "__main__":
    slime()
    wisp()
    print("wrote examples/slime and examples/wisp")

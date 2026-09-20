"""Shared rig primitives: loading, cell placement, and the one affine convention.

Both renderers (this package and `rig.lua`) must agree texel-for-texel, so the
matrix convention lives here and is mirrored in the Lua by hand:

    pose -> T(pivot + d) . R(rot) . S(sx, sy) . T(-pivot)

applied to cell-space coordinates, y down, positive `rot` clockwise on screen.
Sampling is always inverse-mapped nearest-neighbour from the part's authored
pixels, one pass, never chained -- resampling twice at 46 texels tall destroys
the art.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

ALPHA_CUT = 127  # ART_SPEC binary alpha: a source texel is kept only above this


# ------------------------------------------------------------------ rig file

class Rig:
    def __init__(self, data: dict, path: Path):
        self.path = path
        self.data = data
        for key in ("source", "parts_file", "anim_file", "strip_file", "parts_dir"):
            if key in data and not Path(data[key]).is_absolute():
                data[key] = (path.resolve().parent / data[key]).as_posix()
        self.cell = (int(data["cell"][0]), int(data["cell"][1]))
        self.parts = list(data["parts"])          # backmost first == z order
        self.states = list(data.get("states", []))
        self.by_name = {p["name"]: p for p in self.parts}
        self.z = {p["name"]: i for i, p in enumerate(self.parts)}
        for p in self.parts:
            par = p.get("parent")
            if par and par not in self.by_name:
                raise SystemExit(f"rig: part {p['name']} has unknown parent {par}")

    @property
    def name(self) -> str:
        return self.data.get("name") or self.path.stem

    def path_of(self, key: str) -> Path:
        return Path(self.data[key])

    def parts_dir(self) -> Path:
        """Where segment.py writes its output. Defaults beside the parts file."""
        if "parts_dir" in self.data:
            return Path(self.data["parts_dir"])
        return self.path_of("parts_file").with_suffix("")

    def ancestors(self, name: str):
        seen = set()
        cur = self.by_name[name].get("parent")
        while cur:
            if cur in seen:
                raise SystemExit(f"rig: parent cycle at {cur}")
            seen.add(cur)
            yield cur
            cur = self.by_name[cur].get("parent")

    def frames(self):
        """Flatten states into (state_name, frame_index_in_state, pose, hold, fps)."""
        for st in self.states:
            for i, fr in enumerate(st["frames"]):
                yield st["name"], i, fr.get("pose", {}), int(fr.get("hold", 1)), float(st.get("fps", 8))


def load_rig(path) -> Rig:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as fh:
        return Rig(json.load(fh), path)


# ------------------------------------------------------------- cell placement

def place_in_cell(src: Image.Image, cell) -> tuple[np.ndarray, tuple[int, int]]:
    """Centre horizontally, bottom-align. Identical to rig.lua mode=slice and
    grid.py, so cell coordinates read off the grid render are the real thing.

    Returns (H, W, 4) uint8 and the (ox, oy) the sprite was pasted at.
    """
    CW, CH = cell
    ox, oy = (CW - src.width) // 2, CH - src.height
    canvas = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    canvas.paste(src.convert("RGBA"), (ox, oy))
    return np.array(canvas), (ox, oy)


def binary_alpha(rgba: np.ndarray) -> np.ndarray:
    return rgba[:, :, 3] > ALPHA_CUT


# -------------------------------------------------------------------- affine

def pose_matrix(pose: dict, pivot) -> np.ndarray:
    """2x3 affine as a 3x3 with the bottom row implied. Matches rig.lua."""
    rot = math.radians(float(pose.get("rot", 0.0)))
    sx, sy = float(pose.get("sx", 1.0)), float(pose.get("sy", 1.0))
    co, si = math.cos(rot), math.sin(rot)
    px, py = float(pivot[0]), float(pivot[1])
    dx, dy = float(pose.get("dx", 0.0)), float(pose.get("dy", 0.0))
    r = np.array([[co * sx, -si * sy, 0.0],
                  [si * sx,  co * sy, 0.0],
                  [0.0,      0.0,     1.0]])
    t1 = np.array([[1.0, 0.0, -px], [0.0, 1.0, -py], [0.0, 0.0, 1.0]])
    t2 = np.array([[1.0, 0.0, px + dx], [0.0, 1.0, py + dy], [0.0, 0.0, 1.0]])
    return t2 @ r @ t1


def world_matrix(rig: Rig, part_name: str, pose: dict, cache: dict | None = None) -> np.ndarray:
    """FK: a part's matrix is its parent's composed with its own local pose."""
    cache = {} if cache is None else cache
    if part_name in cache:
        return cache[part_name]
    part = rig.by_name[part_name]
    m = pose_matrix(pose.get(part_name, {}), part["pivot"])
    parent = part.get("parent")
    if parent:
        m = world_matrix(rig, parent, pose, cache) @ m
    cache[part_name] = m
    return m


def sample_nearest(layer: np.ndarray, m: np.ndarray, cell) -> np.ndarray:
    """Inverse-map `layer` (cell-sized RGBA) through `m` into a new cell-sized
    RGBA. Nearest-neighbour, one pass, no new colours by construction."""
    CW, CH = cell
    inv = np.linalg.inv(m)
    ys, xs = np.mgrid[0:CH, 0:CW]
    hx = xs + 0.5
    hy = ys + 0.5
    u = inv[0, 0] * hx + inv[0, 1] * hy + inv[0, 2]
    v = inv[1, 0] * hx + inv[1, 1] * hy + inv[1, 2]
    su = np.floor(u).astype(np.int32)
    sv = np.floor(v).astype(np.int32)
    inside = (su >= 0) & (su < CW) & (sv >= 0) & (sv < CH)
    out = np.zeros((CH, CW, 4), dtype=np.uint8)
    su = np.clip(su, 0, CW - 1)
    sv = np.clip(sv, 0, CH - 1)
    picked = layer[sv, su]
    keep = inside & (picked[:, :, 3] > ALPHA_CUT)
    out[keep] = picked[keep]
    out[~keep, 3] = 0
    return out


def sample_mask_nearest(mask: np.ndarray, m: np.ndarray, cell) -> np.ndarray:
    """Same transform applied to a boolean mask, so a part's provenance and its
    pixels stay in lockstep."""
    CW, CH = cell
    inv = np.linalg.inv(m)
    ys, xs = np.mgrid[0:CH, 0:CW]
    u = inv[0, 0] * (xs + 0.5) + inv[0, 1] * (ys + 0.5) + inv[0, 2]
    v = inv[1, 0] * (xs + 0.5) + inv[1, 1] * (ys + 0.5) + inv[1, 2]
    su = np.floor(u).astype(np.int32)
    sv = np.floor(v).astype(np.int32)
    inside = (su >= 0) & (su < CW) & (sv >= 0) & (sv < CH)
    out = np.zeros((CH, CW), dtype=bool)
    out[inside] = mask[np.clip(sv, 0, CH - 1), np.clip(su, 0, CW - 1)][inside]
    return out

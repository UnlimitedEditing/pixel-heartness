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
        for key in ("source", "parts_file", "anim_file", "strip_file", "ase_strip_file", "parts_dir"):
            if key in data and not Path(data[key]).is_absolute():
                data[key] = (path.resolve().parent / data[key]).as_posix()
        self.cell = (int(data["cell"][0]), int(data["cell"][1]))
        self.parts = list(data["parts"])          # backmost first == z order
        self.view_pivots = {}
        if data.get("view_pivots"):
            vp = Path(data["view_pivots"])
            vp = vp if vp.is_absolute() else path.resolve().parent / vp
            self.view_pivots = json.loads(vp.read_text(encoding="utf-8"))
        for p in self.parts:                      # variant art, relative to the rig file
            for v, f in list(p.get("variants", {}).items()):
                if not Path(f).is_absolute():
                    p["variants"][v] = (path.resolve().parent / f).as_posix()
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

    def ase_strip_path(self) -> Path:
        """Where rig.lua writes its strip. Deliberately not `strip_file`: that is
        render.py's output, and if both wrote it the `agree` gate would compare a
        file with itself."""
        if "ase_strip_file" in self.data:
            return Path(self.data["ase_strip_file"])
        s = self.path_of("strip_file")
        return s.with_name(s.stem + "_ase" + s.suffix)

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
        """Flatten states into (state_name, frame_index_in_state, pose, hold, fps).

        `pose` is the *resolved* pose -- authored values plus whatever `lag`
        adds -- because that is what actually moves, and what segment.py must
        size its underlap against."""
        for st in self.states:
            res = resolve_state(self, st)
            for i, fr in enumerate(st["frames"]):
                yield st["name"], i, res[i]["pose"], int(fr.get("hold", 1)), float(st.get("fps", 8))

    def squash_base(self):
        """Where squash/stretch pivots: the floor line under the root, by default."""
        if "squash_base" in self.data:
            b = self.data["squash_base"]
            return float(b[0]), float(b[1])
        root = next((p for p in self.parts if not p.get("parent")), self.parts[0])
        return float(self.data.get("symmetry_x", root["pivot"][0])), float(self.cell[1] - 1)


MAX_LAG = 0.95


def resolve_state(rig: Rig, state: dict) -> list[dict]:
    """Turn a state's authored frames into what is rendered: a list of
    `{"pose": {part: {...}}, "squash": float}`.

    **Lag** (`parts[].lag`, 0..0.95) is follow-through. A lagged part's angle in
    the world trails its parent's: with `pw` the parent's world rotation and `L`
    the lagged copy of it, each frame does `L <- pw - lag*(pw - L_prev)` and the
    part gets an extra local `rot` of `L - pw`, so a driver that swings out
    leaves the part behind and it catches up on the frames after. `lag` 0 is
    rigid FK, which is what a part without the field gets. One step per key
    frame regardless of `hold`: a held frame renders the pose at the *start* of
    the hold, and the catch-up happens during it. Only `rot` is lagged; scale
    and translation are not, and the parent's rotation is summed along the chain
    rather than composed, which is exact for the small angles this is for.

    A looping state is run round three times so its first frame starts from the
    steady-state lag instead of from rest. A non-looping state starts unlagged,
    since nothing is known about what came before it.

    **Squash** is passed through untouched; it is applied as one global matrix
    in `render.py` / `rig.lua`, not resolved per part.
    """
    frames = state["frames"]
    lagged = {p["name"]: min(MAX_LAG, max(0.0, float(p.get("lag", 0.0))))
              for p in rig.parts if p.get("lag")}

    def parent_world_rot(name, eff):
        total, cur = 0.0, rig.by_name[name].get("parent")
        while cur:
            total += eff[cur]
            cur = rig.by_name[cur].get("parent")
        return total

    fk, seen = [], set()
    def visit(n):
        if n in seen:
            return
        seen.add(n)
        if rig.by_name[n].get("parent"):
            visit(rig.by_name[n]["parent"])
        fk.append(n)
    for p in rig.parts:
        visit(p["name"])

    passes = 3 if (state.get("loop", True) and lagged) else 1
    L = {n: None for n in lagged}
    resolved = []
    for _ in range(passes):
        resolved = []
        for fr in frames:
            pose = {n: dict(v) for n, v in fr.get("pose", {}).items()}
            eff = {}
            for n in fk:                      # parents before children
                own = float(pose.get(n, {}).get("rot", 0.0))
                if n in lagged:
                    pw = parent_world_rot(n, eff)
                    if L[n] is None:
                        L[n] = pw             # unlagged on the very first frame
                    L[n] = pw - lagged[n] * (pw - L[n])
                    extra = L[n] - pw
                    if extra:
                        pose.setdefault(n, {})["rot"] = own + extra
                    own += extra
                eff[n] = own
            resolved.append(dict(pose=pose, squash=float(fr.get("squash", 0.0)),
                                 yaw=float(fr.get("yaw", 0.0))))
    return resolved


def squash_matrix(amount: float, base) -> np.ndarray:
    """Volume-preserving squash (amount > 0) or stretch (amount < 0) about the
    point `base`: y scales by `1 - amount`, x by its reciprocal, so the area a
    shape covers is unchanged. Applied to every part after FK."""
    sy = 1.0 - float(amount)
    sx = 1.0 / sy
    bx, by = float(base[0]), float(base[1])
    return np.array([[sx, 0.0, bx - sx * bx],
                     [0.0, sy, by - sy * by],
                     [0.0, 0.0, 1.0]])


DEFAULT_VIEWS = [
    {"name": "front", "angle": 0, "variant": None, "mirror": False},
    {"name": "side", "angle": 90, "variant": "side", "mirror": False},
    {"name": "back_art", "angle": 180, "variant": "back", "mirror": True},   # authored/edited, if the part has it
    {"name": "back", "angle": 180, "variant": None, "mirror": True},         # else the flipped front
    {"name": "side_l", "angle": 270, "variant": "side", "mirror": True},
]


def _wrap(d):
    return (d + 180.0) % 360.0 - 180.0


def yaw_plan(rig: Rig, parts, yaw_deg: float):
    """SPIKE. Per-part view selection for a turn about the vertical axis.

    The rig lists views (`views`, default front 0 / side 90 / back 180 / side_l 270);
    a view either reuses the part's front art or names a variant (`side`), and may
    mirror it. For each part the nearest *available* view wins, and the card is
    scaled horizontally by cos(residual angle) about the body axis, negated for a
    mirrored view. With views every 90 degrees the residual is at most 45, so a card
    is never squashed below ~0.7. A part with no art for any near view falls back to
    the flipped front, clamped at `yaw_thickness` so it never vanishes.

    Returns (plan, order): plan[name] = dict(variant, matrix), and the draw order,
    backmost first. Front and back cards sort by depth (`base * cos + offset * sin`);
    profile art sorts by the rig's own z order, because its horizontal axis is the
    body's depth axis and a lateral offset means something else there.
    """
    views = rig.data.get("views") or DEFAULT_VIEWS
    ax = float(rig.data["symmetry_x"]) if "symmetry_x" in rig.data else         float(next(p for p in rig.parts if not p.get("parent"))["pivot"][0])
    thick = float(rig.data.get("yaw_thickness", 0.4))
    step = float(rig.data.get("depth_step", 2.0))
    t = math.radians(yaw_deg)
    c, sn = math.cos(t), math.sin(t)
    n = len(rig.parts)
    plan, depth = {}, []
    for i, p in enumerate(rig.parts):
        name = p["name"]
        avail = [v for v in views if v.get("variant") is None or (name, v["variant"]) in parts.variant_layer]
        v = min(avail, key=lambda v: abs(_wrap(yaw_deg - v["angle"])))
        r = math.radians(_wrap(yaw_deg - v["angle"]))
        scale = max(math.cos(r), thick)
        sgn = -1.0 if v.get("mirror") else 1.0
        if v.get("patch_handed") and p.get("handed"):
            sgn = 1.0      # a handed part (the shield and its arms) keeps its side in a mirrored view
        m = np.array([[sgn * scale, 0.0, ax - sgn * scale * ax], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        vp = rig.view_pivots.get(v.get("variant") or "", {})
        plan[name] = dict(variant=v.get("variant"), matrix=m, view=v["name"], pivot=vp.get(name))
        base = (i - (n - 1) / 2.0) * step
        if v.get("variant"):
            depth.append(i * 1e-3)                  # profile art: rig z order
        else:
            a = parts.layer[name][:, :, 3] > ALPHA_CUT
            xs = np.where(a.any(axis=0))[0]
            xc = float(xs.mean()) + 0.5 if len(xs) else ax
            depth.append(base * c + (xc - ax) * sn)
    order = sorted(range(n), key=lambda i: (depth[i], i))
    return plan, order


def yaw_gain(pose: dict, yaw_deg: float, gains: dict | None) -> dict:
    """View-dependent amplitude. A limb swing authored in the picture plane is only right at one
    facing: a walk's leg swing is depth motion from the front (the rig fakes it with a small
    in-plane rotation) and true in-plane motion in profile. `gains` maps part -> key -> [m_front,
    m_side]; the value is multiplied by lerp(m_front, m_side, |sin yaw|). The sign is not touched:
    a mirrored view mirrors the swing by itself."""
    if not gains:
        return pose
    g = abs(math.sin(math.radians(yaw_deg)))
    out = {k: dict(v) for k, v in pose.items()}
    for part, keys in gains.items():
        for key, (mf, ms) in keys.items():
            if part in out and key in out[part]:
                out[part][key] = out[part][key] * (mf * (1.0 - g) + ms * g)
    return out


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


def world_matrix(rig: Rig, part_name: str, pose: dict, cache: dict | None = None,
                 pivots: dict | None = None) -> np.ndarray:
    """FK: a part's matrix is its parent's composed with its own local pose. `pivots` overrides
    the rig's pivots part by part (a generated view has its own joints)."""
    cache = {} if cache is None else cache
    if part_name in cache:
        return cache[part_name]
    part = rig.by_name[part_name]
    pv = pivots[part_name] if pivots and part_name in pivots else part["pivot"]
    m = pose_matrix(pose.get(part_name, {}), pv)
    parent = part.get("parent")
    if parent:
        m = world_matrix(rig, parent, pose, cache, pivots) @ m
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

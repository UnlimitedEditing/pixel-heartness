"""Look at what the rig actually produced.

The harness must never ask for a coordinate without supplying a labeled
reference, so every view here is numbered in cell coordinates.

    python pixelanim/sheet.py grid    examples/skeleton_warrior/rig.json   # seed/pivot authoring view
    python pixelanim/sheet.py parts   examples/skeleton_warrior/rig.json   # authored vs synthesised
    python pixelanim/sheet.py contact examples/skeleton_warrior/rig.json   # every frame, labelled
    python pixelanim/sheet.py gif     examples/skeleton_warrior/rig.json --state walk
    python pixelanim/sheet.py map     examples/skeleton_warrior/rig.json --what colours
    python pixelanim/sheet.py map     examples/skeleton_warrior/rig.json --frame 13 --x0 26
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

import render
import riglib
import segment

BG = (26, 26, 32)
INK = (232, 232, 238)
DIM = (120, 120, 132)
OUT_DIR = Path("out")


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def checker(w, h, s=8):
    """Transparency backdrop, so a hole in the art is unmistakable."""
    im = Image.new("RGB", (w, h), (46, 46, 54))
    d = ImageDraw.Draw(im)
    for y in range(0, h, s):
        for x in range(0, w, s):
            if (x // s + y // s) % 2:
                d.rectangle([x, y, x + s - 1, y + s - 1], fill=(38, 38, 45))
    return im


def zoom(rgba: np.ndarray, s: int) -> Image.Image:
    im = Image.fromarray(rgba, "RGBA").resize((rgba.shape[1] * s, rgba.shape[0] * s), Image.NEAREST)
    base = checker(im.width, im.height, max(4, s))
    base.paste(im, (0, 0), im)
    return base


def outline_of(mask: np.ndarray) -> np.ndarray:
    """Texels on the inside edge of a mask -- drawn as the boundary of a part."""
    return mask & ~ndimage.binary_erosion(mask, structure=np.ones((3, 3), bool))


# ----------------------------------------------------------------- grid view

def view_grid(rig, args):
    res = segment.segment(rig, args.underlap, args.colour_lambda, args.fill,
                          args.extend_outside, args.symmetry_x, quiet=True, allow_bad_seeds=True)
    CW, CH = rig.cell
    S, M = args.zoom, 34
    img = Image.new("RGB", (CW * S + M, CH * S + M), BG)
    img.paste(zoom(res["rgba"], S), (M, M))
    d = ImageDraw.Draw(img)
    f = font(13)

    for x in range(CW + 1):
        c = (210, 70, 70) if x % 8 == 0 else ((110, 110, 124) if x % 4 == 0 else (58, 58, 68))
        d.line([(M + x * S, M), (M + x * S, M + CH * S)], fill=c)
        if x % 4 == 0:
            d.text((M + x * S - 6, 12), str(x), fill=INK, font=f)
    for y in range(CH + 1):
        c = (210, 70, 70) if y % 8 == 0 else ((110, 110, 124) if y % 4 == 0 else (58, 58, 68))
        d.line([(M, M + y * S), (M + CW * S, M + y * S)], fill=c)
        if y % 4 == 0:
            d.text((4, M + y * S - 6), str(y), fill=INK, font=f)

    # part boundaries in their label colour, then pivots
    for p in rig.parts:
        col = segment.PALETTE[rig.z[p["name"]] % len(segment.PALETTE)]
        edge = outline_of(res["lab"] == res["idx"][p["name"]])
        for yy, xx in zip(*np.where(edge)):
            d.rectangle([M + xx * S, M + yy * S, M + xx * S + S - 1, M + yy * S + S - 1],
                        outline=col, width=max(1, S // 6))
    for p in rig.parts:
        px, py = p["pivot"]
        cx, cy = M + px * S + S // 2, M + py * S + S // 2
        d.line([(cx - S, cy), (cx + S, cy)], fill=(255, 255, 255), width=2)
        d.line([(cx, cy - S), (cx, cy + S)], fill=(255, 255, 255), width=2)
        d.text((cx + S + 2, cy - 7), "%s (%d,%d)" % (p["name"], px, py), fill=(255, 255, 255), font=f)

    ax = res["axis_x"]
    d.line([(M + ax * S, M), (M + ax * S, M + CH * S)], fill=(90, 200, 255), width=2)
    d.text((M + ax * S + 3, M + 3), "symmetry_x=%g" % ax, fill=(90, 200, 255), font=f)
    return img


# ---------------------------------------------------------------- parts view

def view_parts(rig, parts_dir, args):
    CW, CH = rig.cell
    S = args.zoom
    cols = min(len(rig.parts), 4)
    rows = (len(rig.parts) + cols - 1) // cols
    cw, ch = CW * S + 14, CH * S + 30
    img = Image.new("RGB", (cw * cols, ch * rows), BG)
    d = ImageDraw.Draw(img)
    f = font(13)
    man = {e["name"]: e for e in json.loads((parts_dir / "manifest.json").read_text())["parts"]}

    for i, p in enumerate(rig.parts):
        n = p["name"]
        layer = np.array(Image.open(parts_dir / (n + ".png")).convert("RGBA"))
        synth = np.array(Image.open(parts_dir / (n + ".synth.png")).convert("RGBA"))[:, :, 3] > 127
        x0, y0 = (i % cols) * cw, (i // cols) * ch
        img.paste(zoom(layer, S), (x0 + 7, y0 + 24))
        if args.mark_synth:                       # ring the invented texels
            for yy, xx in zip(*np.where(outline_of(synth))):
                d.rectangle([x0 + 7 + xx * S, y0 + 24 + yy * S,
                             x0 + 7 + xx * S + S - 1, y0 + 24 + yy * S + S - 1],
                            outline=(90, 230, 255), width=1)
        e = man[n]
        d.text((x0 + 7, y0 + 5), "%s  %d px + %d synth" % (n, e["authored_px"], e["synth_px"]),
               fill=INK, font=f)
        d.text((x0 + 7, y0 + ch - 16), "under %d / outside %d / %s@%d"
               % (e["under_front"], e["outside"], e["policy"], e["radius"]), fill=DIM, font=f)
    return img


# -------------------------------------------------------------- contact view

def view_contact(rig, frames, args):
    CW, CH = rig.cell
    S = args.zoom
    cols = args.cols
    rows = (len(frames) + cols - 1) // cols
    cw, ch = CW * S + 10, CH * S + 34
    img = Image.new("RGB", (cw * cols, ch * rows), BG)
    d = ImageDraw.Draw(img)
    f = font(13)
    for i, fr in enumerate(frames):
        x0, y0 = (i % cols) * cw, (i // cols) * ch
        img.paste(zoom(fr["rgba"], S), (x0 + 5, y0 + 20))
        if args.mark_synth:
            for yy, xx in zip(*np.where(fr["synth"])):
                d.rectangle([x0 + 5 + xx * S, y0 + 20 + yy * S,
                             x0 + 5 + xx * S + S - 1, y0 + 20 + yy * S + S - 1],
                            outline=(90, 230, 255), width=1)
        n_synth = int(fr["synth"].sum())
        d.text((x0 + 5, y0 + 4), "%d  %s" % (i, fr["state"]), fill=INK, font=f)
        d.text((x0 + 5, y0 + ch - 15), "%d ms%s" % (fr["ms"], ("  +%d synth" % n_synth) if n_synth else ""),
               fill=DIM, font=f)
    return img


# ------------------------------------------------------------------ map view

CHARS = "0123456789abcdefghijklmnopqrstuvwxyz"


def view_map(rig, args, parts_dir):
    """Print the cell as text. Not a fallback for the image views -- it answers a
    different question, and it answered the one that mattered.

    The grid render shows *where* a texel is, which is what pivots and seeds need.
    It does not show *what colour family* a texel belongs to, and at 15 px a zoom
    the shield's dark red edge and the skeleton's brown bone are indistinguishable
    on screen. Two seeds were placed on shield texels that way, and `leg_l` quietly
    took a strip of the shield with it. The colour map makes that a typo you can
    see. Rendering both is cheap; guessing is not.
    """
    res = segment.segment(rig, int(rig.data.get("underlap", 6)), args.colour_lambda,
                          args.fill, args.extend_outside, args.symmetry_x, quiet=True, allow_bad_seeds=True)
    CW, CH = rig.cell
    rgba, opaque = res["rgba"], res["opaque"]
    lines = []

    if args.what == "colours":
        rgb = rgba[:, :, :3]
        cols, counts = np.unique(rgb[opaque].reshape(-1, 3), axis=0, return_counts=True)
        order = np.argsort(-counts)
        key = {tuple(cols[j]): CHARS[i] for i, j in enumerate(order)}
        lines.append("palette, most used first:")
        for i, j in enumerate(order):
            c = tuple(int(v) for v in cols[j])
            lines.append("  %s  rgb%-18s %4d texels" % (CHARS[i], str(c), counts[j]))
        grid = lambda y, x: key[tuple(rgb[y, x])] if opaque[y, x] else "."
    elif args.frame is not None:
        frames = render.render_all(rig, render.Parts(rig, parts_dir))
        fr = frames[args.frame]
        names = [p["name"] for p in rig.parts]
        ch = _part_chars(names)
        lines.append("frame %d (%s) -- lowercase means the texel was invented, not authored"
                     % (args.frame, fr["state"]))
        lines.append("  " + "  ".join("%s=%s" % (ch[n], n) for n in names))
        own, syn = fr["owner"], fr["synth"]
        grid = lambda y, x: ("." if not own[y, x] else
                             (ch[names[own[y, x] - 1]].lower() if syn[y, x]
                              else ch[names[own[y, x] - 1]]))
    else:
        names = [p["name"] for p in rig.parts]
        ch = _part_chars(names)
        lab, idx = res["lab"], res["idx"]
        lines.append("rest pose part labels")
        lines.append("  " + "  ".join("%s=%s" % (ch[n], n) for n in names))
        grid = lambda y, x: ch[names[lab[y, x] - 1]] if lab[y, x] else "."

    x0, x1 = args.x0, min(CW, args.x1 if args.x1 else CW)
    lines.append("")
    lines.append("    " + "".join(str(x % 10) for x in range(x0, x1)))
    for y in range(CH):
        row = "".join(grid(y, x) for x in range(x0, x1))
        if row.strip("."):
            lines.append("%3d %s" % (y, row))
    return "\n".join(lines)


def _part_chars(names):
    """One distinct character per part, chosen to read as the part's name.

    The qualifier carries the meaning in this naming scheme, so `leg_r` wants R
    and `arm_weapon` wants W -- taking plain initials gives L and A and makes the
    map unreadable, which defeats the point of printing it.
    """
    used, out = set(), {}
    for n in names:
        bits = n.upper().split("_")
        prefer = [bits[-1][0]] + [b[0] for b in bits] + list(n.upper()) + list(CHARS.upper())
        c = next((k for k in prefer if k.isalnum() and k not in used), "?")
        used.add(c)
        out[n] = c
    return out


def write_gif(rig, frames, out: Path, state, scale):
    sel = [f for f in frames if state is None or f["state"] == state]
    if not sel:
        raise SystemExit("sheet: no frames in state " + str(state))
    ims = []
    for fr in sel:
        im = Image.fromarray(fr["rgba"], "RGBA")
        bg = Image.new("RGBA", im.size, (26, 26, 32, 255))
        bg.paste(im, (0, 0), im)
        ims.append(bg.convert("P", palette=Image.ADAPTIVE)
                   .resize((im.width * scale, im.height * scale), Image.NEAREST))
    out.parent.mkdir(parents=True, exist_ok=True)
    ims[0].save(out, save_all=True, append_images=ims[1:],
                duration=[f["ms"] for f in sel], loop=0, disposal=2)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("view", choices=["grid", "parts", "contact", "gif", "map"])
    ap.add_argument("rig", type=Path)
    ap.add_argument("--zoom", type=int, default=10)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--state", default=None)
    ap.add_argument("--mark-synth", action="store_true", help="ring texels that were invented")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--underlap", type=int, default=3)
    ap.add_argument("--colour-lambda", type=float, default=6.0)
    ap.add_argument("--fill", default="mirror")
    ap.add_argument("--extend-outside", default="none")
    ap.add_argument("--symmetry-x", type=float, default=None)
    ap.add_argument("--what", default="labels", choices=["labels", "colours"],
                    help="map view: part labels, or which palette entry each texel uses")
    ap.add_argument("--frame", type=int, default=None,
                    help="map view: a posed frame's owner map instead of the rest labels")
    ap.add_argument("--x0", type=int, default=0)
    ap.add_argument("--x1", type=int, default=0, help="map view: crop to a column range")
    args = ap.parse_args()

    rig = riglib.load_rig(args.rig)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or OUT_DIR / ("%s_%s.%s" % (rig.name, args.view, "gif" if args.view == "gif" else "png"))

    if args.view == "map":
        print(view_map(rig, args, rig.parts_dir()))
        return
    if args.view == "grid":
        view_grid(rig, args).save(out)
    elif args.view == "parts":
        view_parts(rig, rig.parts_dir(), args).save(out)
    else:
        parts = render.Parts(rig, rig.parts_dir())
        frames = render.render_all(rig, parts)
        if args.view == "contact":
            view_contact(rig, frames, args).save(out)
        else:
            write_gif(rig, frames, out, args.state, max(2, args.zoom // 2))
    print("wrote %s" % out)


if __name__ == "__main__":
    main()

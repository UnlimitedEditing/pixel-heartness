"""PixelAnim Studio: Bridge between Graydient CLI and pixelanim.

Orchestrates:
1. Base pixel art generation via Graydient krea2 (high pixel accuracy & crisp silhouette)
2. Native RGBA transparency cleanup via Graydient edit-qwen / edit-qwen21
3. Deterministic quantization, grid fitting, and palette cleanup via pixelize.py
4. View turnaround & state synthesis using Graydient edit-qwen / edit-qwen21
5. Symmetry & handedness preservation via mirrorpatch.py
6. Scaffolding archetype rigs (biped, slime, wisp) for the animation loop
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

from PIL import Image
import numpy as np

# Resolve local pixelanim modules
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pixelize
import mirrorpatch

# Keep the isolation prompt SHORT and subject-free. Long prompts that describe the subject and talk about
# "RGBA / alpha channel / transparent background" make qwen draw a literal checkerboard "transparency grid"
# (observed on every sprite, 2026-10-01). This wording on edit-qwen21-turbo returns clean alpha and also
# straightens non-square texels.
ISOLATE_PROMPT = (
    "remove white background from subject and replace with alpha transparent layer. "
    "correct non square subtexel pixels"
)
DEFAULT_EDIT_WORKFLOW = "edit-qwen21-turbo"

KREA2_STYLE_TEMPLATE = (
    "16-bit retro pixel art, SNES RPG style, crisp pixel-perfect rendering, clean black outlines, "
    "vibrant color palette, flat lighting, front view, eye level, 2D sprite, isolated on solid white background, "
    "featuring {prompt}"
)


def run_graydient(
    prompt: str,
    workflow: str,
    out_path: Path,
    init_image: Path | str | None = None,
    steps: int = 30,
    seed: int | None = None,
    timeout_mins: int = 15,
) -> tuple[Path, str | None]:
    """Invokes graydient render and returns the downloaded file path."""
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["graydient", "render"]
    
    # Prompt construction with inline flags
    full_prompt = prompt
    if not any(f"/run:{workflow}" in full_prompt or f"--workflow" in str(cmd) for _ in [1]):
        full_prompt += f" /run:{workflow}"
    if seed is not None:
        full_prompt += f" /seed:{seed}"
    if steps:
        full_prompt += f" /steps:{steps}"

    cmd.append(full_prompt)

    if init_image:
        init_str = str(init_image)
        if init_str.startswith("http://") or init_str.startswith("https://"):
            cmd.extend(["--init-image", init_str])
        else:
            cmd.extend(["--init-image", str(Path(init_image).resolve())])

    cmd.extend(["--out", str(out_path)])
    cmd.extend(["--timeout", str(timeout_mins)])

    print(f"[studio] Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)

    if result.returncode != 0:
        print(f"[studio] Error from graydient CLI (code {result.returncode}):")
        print(result.stderr or result.stdout)
        raise RuntimeError(f"Graydient render failed: {result.stderr or result.stdout}")

    print(f"[studio] Graydient output:\n{result.stdout.strip()}")

    # Extract remote URL from stdout if available
    remote_url = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("http://") or line.startswith("https://"):
            remote_url = line
            break

    # Find the resulting file
    final_path = None
    if out_path.is_file():
        final_path = out_path
    elif out_path.is_dir():
        candidates = list(out_path.glob("*.png")) + list(out_path.glob("*.webp"))
        if not candidates:
            raise FileNotFoundError(f"No image found in {out_path} after render.")
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        final_path = candidates[0]
    else:
        for ext in [".png", ".webp", ".jpg"]:
            cand = out_path.with_suffix(ext)
            if cand.exists():
                final_path = cand
                break

    if not final_path:
        raise FileNotFoundError(f"Render output target {out_path} not found.")

    return final_path, remote_url


def isolate_transparency(
    init_image: Path | str,
    subject: str,
    out_path: Path,
    edit_workflow: str = DEFAULT_EDIT_WORKFLOW,
    steps: int = 0,
    seed: int | None = None,
) -> tuple[Path, str | None]:
    """Takes a source concept/sprite image or URL and uses edit-qwen to produce an image with native RGBA transparency.

    `subject` is accepted for compatibility but deliberately NOT put in the prompt (see ISOLATE_PROMPT).
    `steps=0` leaves the workflow's own step count alone (the turbo workflow is tuned for it)."""
    if not (str(init_image).startswith("http://") or str(init_image).startswith("https://")):
        init_image = Path(init_image).resolve()
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rgba_prompt = ISOLATE_PROMPT

    print(f"\n=== Transparency Isolation via Graydient {edit_workflow} ===")
    print(f"[studio] Source Image: {init_image}")
    return run_graydient(
        prompt=rgba_prompt,
        workflow=edit_workflow,
        init_image=init_image,
        out_path=out_path,
        steps=steps,
        seed=seed,
    )


def pixelize_image(
    source_img_path: Path,
    out_path: Path,
    height: int = 48,
    colours: int = 16,
    preserve: float = 0.5,
) -> Path:
    """Locally and deterministically cleans up an RGBA image onto an exact texel grid and closed palette."""
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n=== Deterministic Local Quantization & Grid Fitting (pixelanim) ===")
    img = Image.open(source_img_path)
    bg = pixelize.background_mask(img)
    pal = pixelize.derive_palette(img, bg, colours=colours)
    
    x0, y0, x1, y1 = pixelize.figure_box(bg)
    t = (y1 - y0) / float(height)
    print(f"[studio] Discovered {len(pal)} palette colors. Scale: {t:.2f} px per texel (target height: {height} texels)")

    clean_sprite = pixelize.pixelize(
        img,
        src=None,
        texel=t,
        refine=0.02,
        palette=pal,
        preserve=preserve,
    )

    clean_sprite.save(out_path)
    print(f"[studio] Wrote crisp, on-grid pixel sprite: {out_path} ({clean_sprite.width}x{clean_sprite.height})")
    return out_path


def generate_sprite(
    prompt: str,
    out: Path,
    height: int = 48,
    colours: int = 16,
    base_workflow: str = "krea2",
    edit_workflow: str = DEFAULT_EDIT_WORKFLOW,
    steps_base: int = 30,
    steps_edit: int = 0,
    seed: int | None = None,
    preserve: float = 0.5,
    raw_dir: Path | None = None,
    skip_transparency: bool = False,
) -> Path:
    """Generates a new sprite using the 3-stage pipeline:
    1. Base Art: krea2 (pixel-accurate style, crisp outlines)
    2. Transparency: edit-qwen (native RGBA isolation)
    3. Cleanup: pixelanim pixelize.py (deterministic quantization & palette closure)
    """
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    raw_dir = raw_dir or (out.parent / "raw")
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 1. Base Art with krea2
    krea_file = raw_dir / f"{out.stem}_krea2.png"
    print(f"\n=== Step 1: Generating Base Pixel Art via Graydient {base_workflow} ===")
    krea_prompt = KREA2_STYLE_TEMPLATE.format(prompt=prompt)
    rendered_krea_path, krea_remote_url = run_graydient(
        prompt=krea_prompt,
        workflow=base_workflow,
        out_path=krea_file,
        steps=steps_base,
        seed=seed,
    )

    # 2. Transparency Cleanup with edit-qwen (prefer direct S3 URL to avoid upload relay)
    if skip_transparency:
        transparent_img_path = rendered_krea_path
    else:
        init_target = krea_remote_url if krea_remote_url else rendered_krea_path
        trans_file = raw_dir / f"{out.stem}_trans.png"
        print(f"\n=== Step 2: Transparency Isolation via Graydient {edit_workflow} ===")
        transparent_img_path, trans_remote_url = isolate_transparency(
            init_image=init_target,
            subject=prompt,
            out_path=trans_file,
            edit_workflow=edit_workflow,
            steps=steps_edit,
            seed=seed,
        )

    # 3. Deterministic Local Quantization
    print(f"\n=== Step 3: Local Pixel Correction via pixelanim ===")
    return pixelize_image(
        source_img_path=transparent_img_path,
        out_path=out,
        height=height,
        colours=colours,
        preserve=preserve,
    )


def prepare_input_x10(src_path: Path, out_path: Path) -> Path:
    """Scales a source pixel art sprite 10x using nearest-neighbor for edit-qwen21."""
    im = Image.open(src_path).convert("RGBA")
    w, h = im.size
    big = im.resize((w * 10, h * 10), Image.NEAREST)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    big.save(out_path)
    return out_path


def generate_turnaround(
    front_sprite: Path,
    out_dir: Path,
    subject_desc: str,
    height: int | None = None,
    workflow: str = "edit-qwen",
    steps: int = 35,
    base_seed: int = 1100,
    preserve: float = 0.5,
) -> dict[str, Path]:
    """Generates an 8-facing turnaround set from a front-facing sprite."""
    front_sprite = Path(front_sprite).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 1. Scale front sprite 10x
    in_x10 = raw_dir / f"{front_sprite.stem}_x10.png"
    prepare_input_x10(front_sprite, in_x10)

    # Views definition: (name, angle_deg, prompt_addon, seed_offset)
    views_to_render = [
        ("q34", 45, "three-quarter view, turned 45 degrees toward the left of the image", 1),
        ("qside", 90, "profile side view facing left", 2),
        ("qrear34", 135, "three-quarter rear view from behind, facing away and slightly left", 3),
        ("qrear", 180, "directly from behind, showing the back of the character", 4),
    ]

    results = {"front": front_sprite}
    front_im = Image.open(front_sprite)
    pal = pixelize.palette_of(front_im)
    fig_h = height or front_im.height

    print(f"\n=== Generating Turnaround Views for {front_sprite.name} ===")

    for name, angle, desc, s_offset in views_to_render:
        view_raw = raw_dir / f"{name}_raw.png"
        prompt = (
            f"Rotate the {subject_desc} to a {desc}. "
            f"Keep the same pixel art style, exact colours and proportions."
        )
        rgba_prompt = prompt + " Replace the white background with an alpha transparent layer."
        
        print(f"\n--- Rendering {name} ({angle}Â°) ---")
        run_graydient(
            prompt=rgba_prompt,
            workflow=workflow,
            init_image=in_x10,
            out_path=view_raw,
            steps=steps,
            seed=base_seed + s_offset,
        )

        # Clean with pixelize
        view_clean = out_dir / f"{name}.png"
        raw_im = Image.open(view_raw)
        bg = pixelize.background_mask(raw_im)
        bx0, by0, bx1, by1 = pixelize.figure_box(bg)
        t = (by1 - by0) / float(fig_h)

        clean = pixelize.pixelize(
            raw_im,
            src=None,
            texel=t,
            refine=0.02,
            palette=pal,
            preserve=preserve,
        )
        clean.save(view_clean)
        results[name] = view_clean
        print(f"[studio] Cleaned {name}: {view_clean} ({clean.width}x{clean.height})")

    # Mirror opposite views
    print("\n--- Constructing Bilateral Opposite Views ---")
    # 225 is mirror of 135 (qrear34)
    if "qrear34" in results:
        r225 = out_dir / "qrear34_m.png"
        im135 = Image.open(results["qrear34"]).transpose(Image.FLIP_LEFT_RIGHT)
        im135.save(r225)
        results["qrear34_m"] = r225

    # 270 is mirror of 90 (qside)
    if "qside" in results:
        r270 = out_dir / "qside_m.png"
        im90 = Image.open(results["qside"]).transpose(Image.FLIP_LEFT_RIGHT)
        im90.save(r270)
        results["qside_m"] = r270

    # 315 is mirror of 45 (q34)
    if "q34" in results:
        r315 = out_dir / "q34_m.png"
        im45 = Image.open(results["q34"]).transpose(Image.FLIP_LEFT_RIGHT)
        im45.save(r315)
        results["q34_m"] = r315

    print(f"\n[studio] Turnaround set complete in {out_dir}")
    return results


def scaffold_rig(
    archetype: str,
    name: str,
    source_sprite: Path,
    out_rig: Path,
    cell: tuple[int, int] = (48, 48),
) -> Path:
    """Generates an initial rig.json template for biped, slime, or wisp."""
    out_rig = Path(out_rig).resolve()
    out_rig.parent.mkdir(parents=True, exist_ok=True)
    source_sprite = Path(source_sprite).resolve()

    try:
        rel_source = os.path.relpath(source_sprite, out_rig.parent)
    except ValueError:
        rel_source = str(source_sprite)

    templates = {
        "slime": {
            "name": name,
            "source": rel_source,
            "parts_file": f"out/{name}_parts.aseprite",
            "anim_file": f"out/{name}_anim.aseprite",
            "strip_file": f"out/{name}_strip.png",
            "cell": list(cell),
            "underlap": 4,
            "airborne_states": ["air"],
            "_note": "Generated by pixelanim studio. Adjust part seeds and pivots using 'sheet.py grid'.",
            "parts": [
                {
                    "name": "body",
                    "pivot": [cell[0] // 2, cell[1] - 2],
                    "seeds": [[cell[0] // 2, cell[1] - 5]],
                },
                {
                    "name": "eyes",
                    "parent": "body",
                    "pivot": [cell[0] // 2, cell[1] - 10],
                    "seeds": [[cell[0] // 2, cell[1] - 10]],
                }
            ],
            "states": [
                {
                    "name": "idle",
                    "fps": 4,
                    "loop": True,
                    "min_distinct": 0.5,
                    "frames": [
                        {"squash": 0.0},
                        {"squash": 0.08},
                        {"squash": 0.0},
                        {"squash": -0.05}
                    ]
                },
                {
                    "name": "windup",
                    "fps": 10,
                    "loop": False,
                    "frames": [
                        {"squash": 0.15},
                        {"squash": 0.3, "hold": 2}
                    ]
                },
                {
                    "name": "air",
                    "fps": 8,
                    "loop": False,
                    "frames": [
                        {"squash": -0.3, "pose": {"body": {"dy": -6}}},
                        {"squash": -0.1, "pose": {"body": {"dy": -10}}},
                        {"squash": 0.0, "pose": {"body": {"dy": -6}}}
                    ]
                },
                {
                    "name": "land",
                    "fps": 10,
                    "loop": False,
                    "frames": [
                        {"squash": 0.35},
                        {"squash": -0.1},
                        {"squash": 0.05},
                        {"squash": 0.0}
                    ]
                }
            ]
        },
        "wisp": {
            "name": name,
            "source": rel_source,
            "parts_file": f"out/{name}_parts.aseprite",
            "anim_file": f"out/{name}_anim.aseprite",
            "strip_file": f"out/{name}_strip.png",
            "cell": list(cell),
            "underlap": 4,
            "ground_lock": False,
            "airborne_states": ["sway", "flick"],
            "lag_max_deg": 30,
            "_note": "Generated by pixelanim studio. Chain-lag demo rig.",
            "parts": [
                {"name": "t2", "pivot": [cell[0] // 2, cell[1] - 6], "parent": "t1", "lag": 0.75, "seeds": [[cell[0] // 2, cell[1] - 4]]},
                {"name": "t1", "pivot": [cell[0] // 2, cell[1] - 14], "parent": "head", "lag": 0.75, "seeds": [[cell[0] // 2, cell[1] - 10]]},
                {"name": "head", "pivot": [cell[0] // 2, cell[1] - 20], "seeds": [[cell[0] // 2, cell[1] - 22]]}
            ],
            "states": [
                {
                    "name": "sway",
                    "fps": 6,
                    "loop": True,
                    "frames": [
                        {"pose": {"head": {"rot": -8}}},
                        {"pose": {"head": {"rot": 0}}},
                        {"pose": {"head": {"rot": 8}}},
                        {"pose": {"head": {"rot": 0}}}
                    ]
                }
            ]
        },
        "biped": {
            "name": name,
            "source": rel_source,
            "parts_file": f"out/{name}_parts.aseprite",
            "anim_file": f"out/{name}_anim.aseprite",
            "strip_file": f"out/{name}_strip.png",
            "cell": list(cell),
            "underlap": 4,
            "_note": "Generated by pixelanim studio. Biped rig template.",
            "parts": [
                {"name": "leg_r", "parent": "pelvis", "pivot": [cell[0] // 2 + 5, cell[1] - 18], "seeds": [[cell[0] // 2 + 5, cell[1] - 12]]},
                {"name": "leg_l", "parent": "pelvis", "pivot": [cell[0] // 2 - 5, cell[1] - 18], "mirror_of": "leg_r", "seeds": [[cell[0] // 2 - 5, cell[1] - 12]]},
                {"name": "pelvis", "pivot": [cell[0] // 2, cell[1] - 20], "seeds": [[cell[0] // 2, cell[1] - 20]]},
                {"name": "torso", "parent": "pelvis", "pivot": [cell[0] // 2, cell[1] - 24], "seeds": [[cell[0] // 2, cell[1] - 26]]},
                {"name": "head", "parent": "torso", "pivot": [cell[0] // 2, cell[1] - 32], "seeds": [[cell[0] // 2, cell[1] - 36]]},
                {"name": "arm_r", "parent": "torso", "pivot": [cell[0] // 2 + 8, cell[1] - 28], "seeds": [[cell[0] // 2 + 8, cell[1] - 24]]},
                {"name": "arm_l", "parent": "torso", "pivot": [cell[0] // 2 - 8, cell[1] - 28], "mirror_of": "arm_r", "seeds": [[cell[0] // 2 - 8, cell[1] - 24]]}
            ],
            "states": [
                {
                    "name": "idle",
                    "fps": 4,
                    "loop": True,
                    "min_distinct": 0.5,
                    "frames": [
                        {"pose": {"torso": {"dy": 0}}},
                        {"pose": {"torso": {"dy": 1}}},
                        {"pose": {"torso": {"dy": 0}}},
                        {"pose": {"torso": {"dy": -1}}}
                    ]
                }
            ]
        }
    }

    if archetype not in templates:
        raise ValueError(f"Unknown archetype '{archetype}'. Choose from: {list(templates.keys())}")

    out_rig.write_text(json.dumps(templates[archetype], indent=2), encoding="utf-8")
    print(f"[studio] Wrote rig template: {out_rig}")
    return out_rig


def main():
    ap = argparse.ArgumentParser(description="PixelAnim Studio Graydient Bridge")
    sub = ap.add_subparsers(dest="command", required=True)

    # generate: 3-stage toolchain (krea2 -> edit-qwen -> pixelanim)
    gen_p = sub.add_parser("generate", help="3-stage generation: krea2 base art -> edit-qwen transparency -> pixelanim local cleanup")
    gen_p.add_argument("prompt", help="Visual subject description")
    gen_p.add_argument("--out", type=Path, required=True, help="Destination clean sprite PNG")
    gen_p.add_argument("--height", type=int, default=48, help="Target sprite texel height")
    gen_p.add_argument("--colours", type=int, default=16, help="Target palette size")
    gen_p.add_argument("--base-workflow", default="krea2", help="Base art workflow (default: krea2)")
    gen_p.add_argument("--edit-workflow", default=DEFAULT_EDIT_WORKFLOW, help="Transparency cleanup workflow (default: edit-qwen)")
    gen_p.add_argument("--steps-base", type=int, default=30, help="Base generation steps")
    gen_p.add_argument("--steps-edit", type=int, default=0, help="Transparency edit steps")
    gen_p.add_argument("--seed", type=int, default=None, help="Generation seed")
    gen_p.add_argument("--preserve", type=float, default=0.5, help="Rarity boost for thin outlines/glints")
    gen_p.add_argument("--skip-transparency", action="store_true", help="Skip edit-qwen transparency stage")

    # isolate: take an existing image, isolate transparency via edit-qwen, and pixelize
    iso_p = sub.add_parser("isolate", help="Clean existing image: edit-qwen transparency -> pixelanim cleanup")
    iso_p.add_argument("image", type=Path, help="Source concept/raw sprite image")
    iso_p.add_argument("--subject", required=True, help="Subject description for transparency isolation prompt")
    iso_p.add_argument("--out", type=Path, required=True, help="Destination clean sprite PNG")
    iso_p.add_argument("--height", type=int, default=48, help="Target sprite texel height")
    iso_p.add_argument("--colours", type=int, default=16, help="Target palette size")
    iso_p.add_argument("--edit-workflow", default=DEFAULT_EDIT_WORKFLOW, help="Transparency cleanup workflow (default: edit-qwen)")
    iso_p.add_argument("--steps", type=int, default=25, help="Transparency edit steps")
    iso_p.add_argument("--seed", type=int, default=None, help="Generation seed")
    iso_p.add_argument("--preserve", type=float, default=0.5, help="Rarity boost for thin outlines/glints")

    # pixelize: standalone local quantization of an already transparent or isolated image
    pix_p = sub.add_parser("pixelize", help="Deterministic local quantization of an RGBA image")
    pix_p.add_argument("image", type=Path, help="Source RGBA image")
    pix_p.add_argument("--out", type=Path, required=True, help="Destination clean sprite PNG")
    pix_p.add_argument("--height", type=int, default=48, help="Target sprite texel height")
    pix_p.add_argument("--colours", type=int, default=16, help="Target palette size")
    pix_p.add_argument("--preserve", type=float, default=0.5, help="Rarity boost for thin outlines/glints")

    # turnaround
    turn_p = sub.add_parser("turnaround", help="8-facing turnaround via edit-qwen / edit-qwen21")
    turn_p.add_argument("front", type=Path, help="Source front-facing sprite PNG")
    turn_p.add_argument("--out-dir", type=Path, required=True, help="Directory to store turn views")
    turn_p.add_argument("--subject", type=str, required=True, help="Short subject description (e.g. 'skeleton warrior')")
    turn_p.add_argument("--height", type=int, default=None, help="Force height in texels")
    turn_p.add_argument("--workflow", default="edit-qwen21", help="Turnaround edit workflow (default: edit-qwen)")
    turn_p.add_argument("--steps", type=int, default=35, help="Sampling steps")
    turn_p.add_argument("--seed", type=int, default=1100, help="Base seed")
    turn_p.add_argument("--preserve", type=float, default=0.5, help="Rarity boost")

    # scaffold
    scaf_p = sub.add_parser("scaffold", help="Scaffold rig.json for an archetype")
    scaf_p.add_argument("archetype", choices=["biped", "slime", "wisp"])
    scaf_p.add_argument("name", help="Rig name")
    scaf_p.add_argument("source", type=Path, help="Source sprite PNG")
    scaf_p.add_argument("--out", type=Path, required=True, help="Destination rig.json path")
    scaf_p.add_argument("--cell", type=int, nargs=2, default=[48, 48], help="Cell size [W, H]")

    args = ap.parse_args()

    if args.command == "generate":
        generate_sprite(
            prompt=args.prompt,
            out=args.out,
            height=args.height,
            colours=args.colours,
            base_workflow=args.base_workflow,
            edit_workflow=args.edit_workflow,
            steps_base=args.steps_base,
            steps_edit=args.steps_edit,
            seed=args.seed,
            preserve=args.preserve,
            skip_transparency=args.skip_transparency,
        )
    elif args.command == "isolate":
        raw_trans = args.out.parent / "raw" / f"{args.out.stem}_trans.png"
        trans_path = isolate_transparency(
            init_image=args.image,
            subject=args.subject,
            out_path=raw_trans,
            edit_workflow=args.edit_workflow,
            steps=args.steps,
            seed=args.seed,
        )
        pixelize_image(
            source_img_path=trans_path,
            out_path=args.out,
            height=args.height,
            colours=args.colours,
            preserve=args.preserve,
        )
    elif args.command == "pixelize":
        pixelize_image(
            source_img_path=args.image,
            out_path=args.out,
            height=args.height,
            colours=args.colours,
            preserve=args.preserve,
        )
    elif args.command == "turnaround":
        generate_turnaround(
            front_sprite=args.front,
            out_dir=args.out_dir,
            subject_desc=args.subject,
            height=args.height,
            workflow=args.workflow,
            steps=args.steps,
            base_seed=args.seed,
            preserve=args.preserve,
        )
    elif args.command == "scaffold":
        scaffold_rig(
            archetype=args.archetype,
            name=args.name,
            source_sprite=args.source,
            out_rig=args.out,
            cell=tuple(args.cell),
        )


if __name__ == "__main__":
    main()

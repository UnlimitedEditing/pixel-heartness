# Getting started: animate your own sprite

This walks one new character from a single PNG to a gated frame strip. Every step is a command
plus a JSON edit, so you can do it by hand or hand it to an agent along with [AGENTS.md](../AGENTS.md).
Paths below assume you run from the repo root, with your character in `chars/hero/`.

## 0. Install

```bash
pip install -r requirements.txt
```

## 1. Prepare the sprite

`chars/hero/hero.png`, front-facing, drawn at final size:

- **Transparent background, hard alpha** (every texel fully opaque or fully clear).
- **One transparent row under the feet.** The sprite is centred horizontally and bottom-aligned in the
  cell, and the floor is the cell's second-to-last row.
- **A limited palette.** The pipeline never adds colours, so the palette you draw is the palette
  every frame will use.
- **Limbs drawn apart where possible.** Anything hidden (a far arm behind a shield) can be rebuilt
  from its mirror twin, but art the pipeline can see always beats art it has to infer.

Pick a **cell** larger than the sprite, with room for the widest swing. The examples use 48x48 for a
32x46 biped, which leaves 8 texels of swing room each side.

## 2. Write a first rig

`chars/hero/rig.json`. The part list goes **backmost first** (list order is the z-order). Start with
no seeds; you'll read them off the grid next.

```json
{
  "name": "hero",
  "source": "hero.png",
  "cell": [48, 48],
  "parts_file": "out/hero_parts.aseprite",
  "anim_file": "out/hero_anim.aseprite",
  "strip_file": "out/hero_strip.png",
  "symmetry_x": 24,
  "underlap": 6,
  "parts": [
    {"name": "arm_back", "parent": "torso", "pivot": [0, 0], "seeds": []},
    {"name": "leg_l",    "parent": "pelvis", "pivot": [0, 0], "seeds": [], "mirror_of": "leg_r"},
    {"name": "leg_r",    "parent": "pelvis", "pivot": [0, 0], "seeds": []},
    {"name": "pelvis",   "pivot": [0, 0], "seeds": []},
    {"name": "torso",    "parent": "pelvis", "pivot": [0, 0], "seeds": []},
    {"name": "head",     "parent": "torso",  "pivot": [0, 0], "seeds": []},
    {"name": "arm_front","parent": "torso",  "pivot": [0, 0], "seeds": []}
  ],
  "states": []
}
```

The `[0, 0]` pivots are placeholders. Relative paths resolve against the rig file's own directory.
The three `*_file` paths are required; `out/` is gitignored. Children inherit their parent's motion
(the head moves with the torso), so a pose only needs to name the part that drives the motion.

## 3. Read coordinates off the grid

```bash
python pixelanim/sheet.py grid chars/hero/rig.json --zoom 15     # -> out/hero_grid.png
python pixelanim/sheet.py map  chars/hero/rig.json --what colours
```

The grid numbers every texel in cell coordinates (x right, y down). The colour map prints which palette
entry each texel uses. For each part:

- **seeds**: 2 to 4 texels well inside the part, on its own colour family. Check each one against the
  colour map; dark outline colours are shared by every part and make poor seeds.
- **pivot**: the joint the part rotates about (hip, shoulder, neck), at the point where it meets its
  parent.
- **symmetry_x**: the body's vertical axis, used to rebuild `mirror_of` parts.

## 4. Cut it

```bash
python pixelanim/segment.py chars/hero/rig.json
python pixelanim/sheet.py map   chars/hero/rig.json          # part labels as text
python pixelanim/sheet.py parts chars/hero/rig.json --mark-synth
```

`segment.py` refuses seeds that sit on background or on another part's colour, and says which ones.
Read the label map. If a part has taken texels that belong to another (a leg eating the edge of a
shield), move or add seeds and cut again. In the parts view, cyan rings mark texels the pipeline
invented under other parts. They only show when an occluding part moves.

## 5. Author states

Each frame's pose is relative to rest, per part: `rot` (degrees, positive clockwise), `dx`/`dy`
(whole texels), `sx`/`sy`. Author extreme keys and use `hold` for timing:

```json
"states": [
  {"name": "idle", "fps": 4, "loop": true, "min_distinct": 1.5, "frames": [
    {"pose": {}},
    {"pose": {"torso": {"dy": 1}}, "hold": 2}
  ]},
  {"name": "walk", "fps": 8, "loop": true, "frames": [
    {"pose": {"leg_l": {"rot": -10}, "leg_r": {"rot": 10}}},
    {"pose": {"torso": {"dy": -1}}},
    {"pose": {"leg_l": {"rot": 10}, "leg_r": {"rot": -10}}},
    {"pose": {"torso": {"dy": -1}}}
  ]}
]
```

Ground lock keeps the lowest texel on the floor row, so don't compensate leg swings with `dy`, and
bob the `torso`, not the root. Other primitives (squash, chain lag, part variants, flash) are in
[REFERENCE.md](REFERENCE.md#primitives-beyond-rigid-fk); `examples/slime` and `examples/wisp` use them.

## 6. Build, gate, look

```bash
python pixelanim/segment.py chars/hero/rig.json        # re-derive underlap for the new poses
python pixelanim/render.py  chars/hero/rig.json
python pixelanim/checks.py  chars/hero/rig.json        # exit status = number of failed gates
python pixelanim/sheet.py contact chars/hero/rig.json --mark-synth
python pixelanim/sheet.py gif     chars/hero/rig.json --state walk
```

Iterate until `checks.py` exits 0 and the contact sheet reads well. [AGENTS.md](../AGENTS.md#reading-gate-output)
explains what each failure means and what usually fixes it.

## 7. Use the output

`chars/hero/out/hero_strip.png` is one row of cells. `hero_strip.json` is in Aseprite's export format
(a frame rect and duration per frame, plus a tag per state), which most engines and packers read.
For a per-state, per-facing atlas with a manifest, see `examples/skeleton_warrior/make_game_atlas.py`.

## Optional: Aseprite

`pixelanim/rig.lua` runs the same maths inside Aseprite, for onion skin and hand-painted overlays
(layers named `+...` survive rebuilds). The `agree` gate checks that both renderers produce the same
frames. Commands are in [REFERENCE.md](REFERENCE.md#hand-touch-ups-survive-rebuilds) and at the top
of `rig.lua`.

## Experimental: more facings

Turning a character needs side and back art per part. The skeleton gets it from generated turnaround
views that are corrected onto its grid and palette, cut with the same segmenter, and chosen per part
by `yaw`. That pipeline is in `examples/skeleton_warrior/make_*.py` and documented, with its open
defects, in [SPIKE_YAW.md](SPIKE_YAW.md) and [EXPERIMENT_DIFFUSION.md](EXPERIMENT_DIFFUSION.md).

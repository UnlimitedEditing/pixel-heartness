# AGENTS.md: operating manual for coding agents

This file is for any coding agent (Claude Code, Codex, Cursor, Aider, and so on) asked to animate a
sprite with Pixel Heartness. Human-facing docs: [README.md](README.md),
[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md), [docs/REFERENCE.md](docs/REFERENCE.md).

## What you need

- A shell, file read/write, and Python 3 with `pip install -r requirements.txt` (numpy, Pillow, SciPy).
- Image input is **useful but optional**. Every tool has a text mode, and every gate reports in text.
- Aseprite is **optional**: it's only needed for the `rig.lua` hand-touch-up path and the `agree` gate.

## The contract

You write **rig JSON**: part seeds, pivots, the hierarchy, and states made of poses. The tools make
**every texel**. Never paint, recolour or edit a sprite's pixels to make a gate pass. If a gate can
only be passed by drawing, stop and tell the human that the motion needs new art (a part variant).

## Hard rules

1. **Never type a coordinate you haven't seen.** Render `sheet.py grid` (numbered cell coordinates,
   y down) before choosing a seed or pivot. Without vision, use `sheet.py map`.
2. **Check colours as text, not by eye.** `sheet.py map <rig> --what colours` prints the palette
   index of every texel. On screen, dark shield red and brown bone look the same; in text they don't.
   `segment.py` refuses a seed that sits off the subject or on another part's colour. Don't override
   that with `--allow-bad-seeds` unless you have read the map and can say why the seed is right.
3. **Run the gates after every change.** `checks.py` exits with the number of failed gates. Anything
   above zero means you aren't done. Some gates are per-state (`states[].min_distinct`) or capped by a
   rig field (`damage_max`, `underlap`). Only lower a threshold to admit known debt, record why in the
   rig's `_debt` field, and never raise it silently.
4. **Translations are whole texels.** `dx`/`dy` must be integers (the `wholetexel` gate enforces it).
5. **Body bob comes from `torso`, not the root.** Ground lock pins the lowest texel to the floor row,
   so moving the root (usually `pelvis`) is cancelled out exactly.
6. **Parts are listed backmost first.** List order is z-order. Underlap only grows under parts drawn
   in front, so a wrong order shows up as tears.
7. **Re-run `segment.py` whenever parts, pivots or poses change.** Underlap is derived from the pose
   list, so a new state can need more cover than the old cut provides.
8. **Numbers rank, eyes choose.** Gates catch the defects someone has already named. When a frame
   looks wrong and every gate is green, report it; a new gate may be needed. Leave taste calls (does
   this idle read as breathing?) to a human, or show them the candidates.

## The loop

```bash
RIG=path/to/rig.json
python pixelanim/sheet.py grid  $RIG --zoom 15            # 1. see coordinates    -> out/<name>_grid.png
python pixelanim/sheet.py map   $RIG --what colours       # 2. see colour families (text)
python pixelanim/segment.py $RIG                          # 3. cut; read any seed refusals
python pixelanim/sheet.py map   $RIG                      # 4. check the part label map (text)
python pixelanim/sheet.py parts $RIG --mark-synth         #    or as an image
#    5. write or edit states[] in the rig
python pixelanim/segment.py $RIG                          # 6. re-derive underlap for the new poses
python pixelanim/render.py  $RIG                          # 7. strip + tag table
python pixelanim/checks.py  $RIG; echo "failures: $?"     # 8. gates
python pixelanim/sheet.py contact $RIG --mark-synth       # 9. every frame, labelled; cyan = invented
python pixelanim/sheet.py gif     $RIG --state <state>    #    one state, animated
python pixelanim/sheet.py map     $RIG --frame N --x0 A --x1 B   # text view of posed frame N; invented texels lowercase
```

Everything is written to `out/`, relative to where you run the command: grids, contact sheets and
GIFs to `./out/`, and parts and strips to `out/` beside the rig.

## Reading gate output

Each gate prints one line: `PASS`/`FAIL`, its name, and a measurement. A failure is followed by
indented lines naming the frame, the state and the first texel involved, e.g.
`frame 76 walk_090 tore 14 texels, first at (27,29)`. To follow one up:

- `holes`: a part rotated off its neighbour with nothing under it. Look with `sheet.py map --frame N`.
  Fix it by reducing the rotation, moving the pivot to the actual joint, raising the `underlap` cap,
  or adding `mirror_of` for a limb that was never drawn.
- `floaters`: invented texels showing with nothing authored beside them. The derived underlap usually
  prevents this; if it doesn't, cap `underlap` or use `under_only` on the part.
- `rotation`: small features (eyes, knuckles) destroyed by nearest-neighbour rotation. Run
  `python pixelanim/rotscan.py $RIG <part>` for the clean angles and author from that list. Damage
  isn't monotonic in angle, so no rule of thumb works.
- `distinct`: two consecutive keys have near-identical silhouettes. Push the pose further or drop a key.
- `border`: a swing leaves the cell. Reduce it, or ask for a larger `cell`.
- `rest`/`palette`: never "fix" these by editing art. Something in the cut or a primitive is wrong.

The full list and what each gate asserts: [docs/REFERENCE.md](docs/REFERENCE.md#gates--checkspy).

## Authoring motion

- Author **keys, not in-betweens**. At about 46 texels tall, three or four extreme keys with holds
  (`hold` on a frame) read better than a smooth eight-frame arc. Typical counts: idle 2 to 4, walk 4,
  attack 3 to 5, damage 2 to 3.
- Anticipation goes opposite the action at roughly a third of its size. An attack's extreme overshoots
  past rest and then settles.
- A pose is relative to rest: `{"rot": deg, "dx": int, "dy": int, "sx": 1.0, "sy": 1.0}`. Positive
  `rot` is clockwise.
- Primitives: `squash` on a frame (positive flattens, area preserved), `lag` on a part (it trails its
  parent; the parent must *rotate*), `variant` in a pose (authored alternate art for a part), `flash`
  on a frame (a colour the sprite already uses), `yaw` on a frame (facing; experimental, see below).
- Airborne states (jumps) go in `airborne_states`, or ground lock pulls them back to the floor.
- To start from real motion, `pixelanim/retarget.py fit` turns a 2D keypoint clip into a state.
  Always run the gates on the result.

## Motions a rig cannot do

A cutout rig moves texels that already exist. It **cannot** show a head turning to profile, a limb
foreshortening toward the camera, a mouth opening, or the far side of an object. Say so instead of
approximating. The fix is a **part variant** (new art for that part, supplied by a human or a
generation pipeline, then corrected with `pixelize.py`), or a stylised stand-in the human agrees to.

## Experimental: facings

The eight-facing work (`yaw`, per-view part art, `examples/skeleton_warrior/make_*.py`) is Python-only
and has open defects (shoulder-seam cracks in some facings; see `docs/DEFECTS.md`). Use it when asked,
report the `holes` numbers honestly, and read `docs/SPIKE_YAW.md` first.

## Repository conventions

- Generated output (`out/`, `data/`) is gitignored. `docs/media/` is committed and regenerated with
  `python examples/make_media.py`.
- Relative paths inside a rig file resolve against the rig file's own directory.
- When you find a new defect class, add it to `docs/DEFECTS.md` with what found it (a gate or an
  eye) and which gate covers it now.

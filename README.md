# pixelanim

An agent-drivable harness for animating pixel art. It turns **one authored character sprite** into a tagged frame strip by cutting it into parts and posing them per frame, then **mechanically checks** the result.

The premise: an agent can animate pixel art well, and the lever is method, not model. Animation craft is turned into executable procedure plus gates, so the bar at ~46 texels tall ("does it read") is checkable rather than a matter of taste.

The hard part is the **cut**, not the transform. A part rotated away from its neighbour reveals texels nobody drew, so the pipeline segments along colour edges and extends each part *underneath* the parts drawn in front of it. That growth is invisible at rest (z order covers it) and is uncovered exactly when a gap would open. Details in [docs/REFERENCE.md](docs/REFERENCE.md).

## Pipeline

```
<rig dir>/<name>.png          one authored front-facing sprite
   | segment.py               cut into parts, extend each under its occluders
out/<name>_parts/             RGBA layer + provenance mask per part
   | render.py                pose + composite (fast path)
   | rig.lua (Aseprite)       same maths, for hand touch-ups (optional)
out/<name>_strip.png + .json  frame strip + Aseprite-style tag table
   | checks.py                fourteen mechanical gates
   | sheet.py                 look at it (grid, parts, contact sheet, gif, text maps)
```

## Quick start

```bash
pip install -r requirements.txt
RIG=examples/skeleton_warrior/rig.json
python pixelanim/segment.py $RIG
python pixelanim/render.py  $RIG
python pixelanim/checks.py  $RIG        # exit status = number of failed gates
python pixelanim/sheet.py contact $RIG --mark-synth
python pixelanim/sheet.py gif $RIG --state walk
```

Views land in `./out/`. `segment.py` refuses seeds that sit off the subject or on a patch of colour another part owns (`--allow-bad-seeds` overrides; `sheet.py map <rig> --what colours` is the text dump to check against). Author a new rig by rendering `sheet.py grid` first and reading seed/pivot coordinates off it — never type a coordinate you haven't seen.

### Aseprite path (optional)

```bash
ASE="path/to/Aseprite.exe"; RIG=$PWD/examples/skeleton_warrior/rig.json
"$ASE" -b --script-param rig=$RIG --script-param mode=import --script pixelanim/rig.lua
"$ASE" -b --script-param rig=$RIG --script-param mode=build  --script pixelanim/rig.lua
python pixelanim/checks.py $RIG --only agree
```

Re-run `import` after every `segment.py`. Layers named `+...` survive rebuilds.
`rig.lua` writes its own `<name>_strip_ase.png` (override with `ase_strip_file`); `strip_file` is `render.py`'s output, which is what an engine packer should read. `agree` compares a fresh in-memory render against the Aseprite strip, shape and colour. It reports SKIPPED when there is no Aseprite strip and fails if that strip is older than the rig or parts.

## Rig files

JSON; relative paths (`source`, `parts_file`, `anim_file`, `strip_file`) resolve against the rig file's own directory, in both Python and Lua. See [docs/REFERENCE.md](docs/REFERENCE.md#rig-file).

## Layout

| path | what |
|---|---|
| `pixelanim/` | segment, render, checks, sheet, riglib, rig.lua, retarget, rotscan, bvh, pixelize (incl. --auto for diffusion output), facing (symmetry hint) |
| `examples/skeleton_warrior/` | rig + source sprite: biped FK |
| `examples/slime/`, `examples/wisp/` | squash/stretch and chain-lag subjects; `python examples/make_examples.py` regenerates them |
| `docs/REFERENCE.md` | how the cut, gates, ground lock work |
| `docs/DEFECTS.md` | **open defects, the deferred-work backlog**, and the log of every defect class |
| `docs/EXPERIMENT_CMU.md` | the real-mocap experiment: method, numbers, verdict |
| `docs/EXPERIMENT_DIFFUSION.md` | diffusion turnaround plus deterministic pixel correction: method, numbers, caveats |
| `docs/HANDOFF.md` | history, evidence for the thesis, roadmap |

## Origin

Built inside a UE5 game project, where the strip feeds a sprite packer and `M_Sprite`. That engine wiring stays in that project; this repo is engine-agnostic. No license chosen yet.

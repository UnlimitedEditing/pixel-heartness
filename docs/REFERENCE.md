# Reference: cutout rig internals

> Paths in the "Wired up" section describe the original Unreal project; the repo-local flow is in the top-level README.

Turns one authored character sprite into a tagged frame strip, by cutting it into parts
and transforming them per frame. Written 2026-09-20. Companion to `Docs/ART_SPEC.md`.

The hard part is not the transform, it is the **cut**. A part rotated away from its
neighbour reveals texels nobody ever drew, and a rectangle-cut part tears at every joint.
So the pipeline segments along colour edges, then **extends each part underneath the parts
drawn in front of it** — growth that is invisible at rest because z order covers it, and
uncovered exactly when the occluder swings away and the gap would otherwise open.

## The loop

```
<rig dir>/<name>.png       one authored front-facing sprite
      |  segment.py        cut into parts, extend each one under its occluders
<rig dir>/out/<name>_parts/             one RGBA layer + provenance mask per part
      |  render.py         pose and composite                 (fast path)
      |  rig.lua mode=import + mode=build (Aseprite path, for hand touch-ups)
<rig dir>/out/<name>_strip.png + .json  frame strip + tag table -> the packer
      |  checks.py         ten mechanical gates
      |  sheet.py          look at it
```

From the repo root:

```bash
python pixelanim/segment.py examples/skeleton_warrior/rig.json
python pixelanim/render.py  examples/skeleton_warrior/rig.json
python pixelanim/checks.py  examples/skeleton_warrior/rig.json
```

`render.py` and `rig.lua` implement the same maths twice and must agree texel for texel;
the `agree` gate is the only thing keeping them honest. Use Python for the build loop and
Aseprite when you want onion skin, layer painting, or a `+fx` overlay.

## segment.py — the three stages

**LABEL.** Every opaque texel is assigned to exactly one part by a colour-weighted
geodesic flood from seed texels (multi-source Dijkstra; step cost rises with colour
difference). Boundaries therefore snap to the edges the artist drew instead of slicing a
rectangle through shield and ribs alike.

Seeds come from `parts[].seeds` — a few cell coordinates per part, read off the numbered
grid that `sheet.py grid` renders. **Never type a coordinate without rendering that view
first.** `parts[].rect` is only a fallback for parts with no seeds, and it fails badly when
rects overlap: on `skeleton_warrior` the shield's rect swallowed both legs' rects, so the
pelvis seeded from its whole box and grew until it owned both thighs.

**EXTENT.** Where a part is *allowed* to invent texels. The load-bearing rule:

> A part may only grow into territory owned by a part drawn **in front** of it.

Then z order covers the growth at rest no matter how far it goes, so the rest pose stays
bit-identical to the source sprite — which the `rest` gate asserts. Growing under a part
drawn *behind* would repaint it and change the sprite, so it is forbidden outright.

Two sources of growth:

| field | what it does |
|---|---|
| `underlap` (rig-level, per-part override) | **cap** on how far a part may reach under its occluders. The radius actually used is derived per texel — see below. |
| `mirror_of: "<part>"` | take the whole mirrored region of a bilateral twin, clipped to what an occluder covers. Rebuilds a limb that was never drawn. |

Growth is **geodesic**: it travels only through the subject, never across bare
background. Plain Euclidean dilation looks equivalent and is not. The pelvis sits a
few texels from the sword arm with background between them, so a disc of radius 6
jumps the gap, lands on the far side, and parks a blob of invented hip texels out
under the hand — hidden at rest, so `rest` stays green, and motionless while the arm
swings past, because the pelvis is the unposed root. Growth that has to cross
background is never covering a seam, because there is no seam there.

The radius is **derived per texel, not tuned**. The gap that opens at a seam is
exactly how far the occluder's material drifts from the material behind it, and for
an affine rig that is not an estimate: at texel `t` under pose `f`, the cover needed
is `max over frames of |M_P(t) − M_Q(t)|`. That is read straight off the rig's own
pose list, so it re-derives itself the moment a state is edited, and it is wide at
the sword tip and nearly nothing at the shoulder. A single global radius cannot do
that — the radius the sword tip needs is precisely the radius that lets the pelvis
creep along the arm. `underlap` only caps it.

`mirror_of` is what makes `skeleton_warrior` work at all: the shield hides the left leg and
left arm almost completely, so they are reconstructed from the right ones across
`symmetry_x`. Both are clipped to what the shield actually covers, never into bare
background — background is covered by nothing, so growth there *would* be visible standing
still. `extend_outside` permits it anyway as an escape hatch, and `rest` will fail on it.

**FILL.** Synthesised texels are copies of authored ones, so the palette is closed by
construction. `mirror` (default) reflects across the part's own boundary — a texel *d*
outside the edge takes the colour *d* inside it, which avoids smearing the black outline
outward the way a plain nearest-neighbour fill does. `edge` is that plain fill. `reflect`
takes the bilaterally symmetric texel.

## Two artefacts, and how they pull against each other

**Tears** are the gap underlap exists to close. **Floaters** are invented texels
revealed with no authored texel of their own part beside them — they read as strays
stuck to nothing, because the part they belong to is somewhere else. With a single
global radius the two trade off directly and there is no good setting:

| global underlap | torn texels | floater texels |
|---|---|---|
| 0 | 74 | 13 |
| 2 | 5 | 5 |
| 4 | 1 | 59 |
| 6 | 0 | 202 |

The derived per-texel radius plus render-time culling gets **0 and 0** together, with
the worst frame at 7.6% invented texels rather than 12%. `underlap` stays in the rig
as the cap, because a cap is still per-subject.

Two different things read as "a hole" and only one is a bug. A **tear** is a texel that was
body at rest and is now an enclosed window — a part rotated off its neighbour with nothing
underneath. **Negative space** is a texel that was already background at rest, like the
notch between a hanging arm and the ribs, which a swinging part merely sealed at both ends;
the art always looked like that. The gate fails on tears and only reports negative space,
and it classifies each hole as a **region** rather than texel by texel — a notch that was
always there usually swallows a texel or two of former body as it seals, and the viewer
reads the whole window as one thing either way.
Note that fixing a tear *increases* negative space, because the arm now stays attached and
so closes the notch — which is why the raw count plateaus while tears go to zero.

Against the old rectangle-cut build of the same rig: **15 torn texels → 0**.

## Gates — `checks.py`

Exit status is the number of failures. Run after every rig change.

| gate | asserts |
|---|---|
| `rest` | the rest pose is bit-identical to the source sprite |
| `palette` | no frame invents a colour |
| `holes` | no frame tears a window through the body |
| `floaters` | no frame shows a detached island of invented texels |
| `border` | no frame touches the cell edge (the engine dilates the outline into it) |
| `wholetexel` | every `dx`/`dy` in the rig is a whole number of texels |
| `ground` | every frame's lowest texel is on row `CH-2` |
| `distinct` | consecutive keys differ enough as a black shape, **including the loop wrap** |
| `synth` | reports how much of each frame the viewer sees that was invented |
| `volume` | a squashed frame covers within `volume_tol` (default 15%) of the same pose unsquashed |
| `lag` | each lagged part's tip sits at least ~0.75 texel from rigid FK, and its joint never gets more than `lag_max_deg` (default 25) of extra rotation |
| `variant` | every variant is declared, used, and aligned with the part it replaces |
| `agree` | a fresh `render.py` render matches `rig.lua`'s separate strip (`*_strip_ase.png`) in shape and colour; SKIPPED if absent, fails if stale |

`distinct` takes its bar per state (`states[].min_distinct`, default 2%), because the
requirement is not one number: an idle is deliberately low-amplitude, while an attack must
show a readable commit point. `skeleton_warrior`'s idle sits at 1.6% against a 1.5% bar and
every other state has 9% or more of margin.

## Primitives beyond rigid FK

**Squash / stretch.** `states[].frames[].squash`: positive flattens, negative stretches. One
global matrix applied after FK to every part: y scales by `1 - s`, x by `1/(1 - s)`, so area is
conserved, about `squash_base` (default: the floor line under the root's x). Ground lock runs
after it, so a squashed frame still lands on the floor row. Airborne states are exempt as usual.
Segmentation does not see squash when sizing underlap; it is a uniform scale about the floor
and the drift it adds at a seam is small. `examples/slime` is the subject.

**Chain lag.** `parts[].lag` (0..0.95) makes a part's world angle trail its parent's:
`L <- pw - lag*(pw - L_prev)`, extra local `rot = L - pw`. It **cascades**, since each link
trails an already-smoothed parent, so local extra rotation shrinks down the chain while the tip
offset from rigid FK grows; the `lag` gate therefore measures at the tip. Only `rot` lags. One
step per key frame regardless of `hold`. Looping states are settled over three passes;
non-looping states start unlagged. Deep links need a high `lag` (~0.75 in the wisp) because each
one only sees the previous link's damped motion. `examples/wisp` is the subject. **The driver must
rotate a parent**: a `dx` swing of the root does not lag.

**Small parts and rotation.** At ~12 texels, a head rotated 18-26 degrees comes out scrambled
under nearest-neighbour sampling (eyes split, edge texels detach) and no gate says so. Keep
rotation of small parts to about 8 degrees and let lag carry the motion elsewhere.

**Part variants.** `parts[].variants: {"blink": "slime_eyes_blink.png"}`, used per frame as
`pose: {"eyes": {"variant": "blink"}}`. A variant is *authored* alternate art for one part: a
sprite the same size as the source, placed by the same centre/bottom rule, containing only that
part's replacement texels. It inherits the part's pivot and FK chain, so it rotates and squashes
like the part it replaces, and none of it counts as invented. This is what moves a head turn or
a blink from "needs new information" into reach. The `palette` gate accepts variant colours, and
the `variant` gate fails on an unknown variant name, on art that overlaps the part's own texels
by under `variant_min_iou` (default 0.3, i.e. misaligned), and on a declared variant no state
uses. Variants get no underlap, so a variant much smaller than the part exposes what was beneath
it (defect #3 in DEFECTS.md); a variant that is a different silhouette needs the neighbours to
cover the seam. `examples/slime` blinks this way.

## Retargeting a motion curve - `retarget.py`

Takes a 2D keypoint clip (per part: `pivot` and `tip`, cell space, frame 0 = rest) and produces
an ordinary rig state. Mocap or a video model may supply the *curve*; no texel ever comes from
it. Mapping a BVH or pose-estimator skeleton onto part names is a separate thin step, not built.

```bash
python pixelanim/retarget.py fit <rig> clip.json --max-keys 4 --tolerance 2 --out state.json
python pixelanim/retarget.py selftest <rig> --state strike --noise 0.2 --densify 6
python pixelanim/retarget.py selftest <rig> --state strike --densify 6 --foreshorten head
```

- **Fit**: per frame in FK order, `rot` is the bone's world angle change minus what the parent
  chain already contributes; `dx,dy` is the pivot's offset from where the parent puts it, in the
  parent's frame, rounded to whole texels. Rotations under `--deadband` degrees (or half a texel
  of tip travel on a short bone, if larger) are dropped as jitter.
- **Keys**: greedy piecewise-linear simplification of the whole pose curve, stopped by
  `--tolerance` degrees or `--max-keys`. It finds extrema *and* slope corners. My first version
  scored extrema only and missed the strike's middle key, because a monotone ramp that changes
  speed has a corner and no extremum.
- **Classifier**: a bone whose length changes by more than 15% between frames cannot be an
  in-plane rotation - that is the "needs new information" column of the handoff's section 2, and
  the frame report names the part. A pivot the rig cannot reach with rotation and whole-texel
  translation is reported separately.

**Measured** (round trip on `skeleton_warrior`: rig -> ground-truth keypoints -> fit):
exact at zero noise; authored keys recovered strike 3/3, windup 2/2, walk 4/4 (3/4 at 0.2 texel
noise); clean clips flag 0 frames, a bone shortened 45% flags exactly that part. At 0.2 texel
noise the mean rotation error is 1.9 degrees, and short bones are the weak point - a fraction
of a texel on a 4-texel bone is several degrees. A fit from a noisy clip once tore a hole in a
frame (the `holes` gate caught it), so **always run the gates on a retargeted state**.
`--smooth 3` cuts invented motion (0.85 -> 0.53 moved parts per key) but costs rotation error
(1.9 -> 2.1 degrees) by blunting peaks; it is off by default.

**Not yet done**: the real experiment - a genuine clip (BVH or estimated keypoints) retargeted
onto `skeleton_warrior` and compared against the hand-written strike. Everything above validates
the machinery against ground truth it generated itself, which proves the fit is correct and says
nothing about whether real motion beats a hand-written three-key strike.

## Ground lock

Rotating a limb about a joint above it moves its far end vertically by
`x·sin t + y·(cos t − 1)`. For a foot that sits sideways of the hip the **first term
dominates**, so the old "pair any leg `rot` with `dy: -1`" rule of thumb is both necessary
and wrong by a texel depending on which way the leg swings.

That is a mechanical constraint no prompt would reliably supply, so it is enforced by
construction rather than written down as advice: each frame is rendered once to find its
lowest texel, then re-rendered shifted by whole texels so it lands on the floor row. Both
renderers do it; `agree` keeps them in step. Set `ground_lock: false` to disable, or list
states in `airborne_states` to exempt them.

One consequence worth knowing: **a body bob must come from `torso`, not `pelvis`.** Moving
the root moves the feet, and ground lock cancels it exactly.

## Looking at it — `sheet.py`

The harness must never ask for a coordinate without supplying a labelled reference.

```bash
python pixelanim/sheet.py grid    <rig> --zoom 15   # numbered grid, part boundaries, pivots
python pixelanim/sheet.py parts   <rig> --mark-synth
python pixelanim/sheet.py contact <rig> --mark-synth
python pixelanim/sheet.py gif     <rig> --state walk
python pixelanim/sheet.py map     <rig> --what colours     # palette index per texel
python pixelanim/sheet.py map     <rig> --frame 13 --x0 26 # a posed frame's owner map
```

The `map` view prints the cell as text and answers a question the image views cannot.
The grid render shows *where* a texel is, which is what seeds and pivots need; it does
not show *what colour family* a texel belongs to, and on screen the shield's dark red
edge and the skeleton's brown bone are indistinguishable at any zoom. Two seeds were
placed on shield texels that way. `--what colours` makes that a typo you can see, and
`--frame N` lowercases every invented texel so a stray is obvious in the terminal.

`--mark-synth` rings every invented texel in cyan, which is how you tell a reconstruction
that reads as bone from one that reads as a smear. Output lands in `out/`.

## Floater culling

Both renderers drop any visible component of a part that consists solely of invented
texels. Underlap is meant to be revealed *attached* to the art it extends; a patch
that surfaces with nothing authored beside it is a stray. This enforces at render time
exactly what `checks.py floaters` asserts, so the gate can never be satisfied by
something the renderer would not actually produce.

## Rig file

`rigs/<name>.json`. Coordinates are cell-space texels, y down, positive `rot` clockwise.

- top level: `cell`, `underlap`, `symmetry_x`, `ground_lock`, `airborne_states`
- `parts` — **listed backmost first; that order is the z order.** `seeds` cut it, `pivot` is
  the joint it rotates about, `parent` builds the FK chain, `mirror_of` names its bilateral
  twin, `underlap`/`fill`/`extend_outside` override the defaults. `rect` is legacy.
- `states[].frames[].pose` — per part `{rot, dx, dy, sx, sy}`, all optional, all relative to
  rest. `hold` lengthens a frame's duration rather than duplicating it.

## Cell size

ART_SPEC class C (32 × 48) fits a character standing still but not one whose shield swings.
Animated humanoids use a **48 × 48** cell: same 46-texel content height, so the world scale
in ART_SPEC is unchanged, with 8 texels of swing room each side.

## Hand touch-ups survive rebuilds

`rig.lua mode=build` regenerates every part layer, so hand edits on those layers are lost.
**Any layer whose name starts with `+` is copied across untouched.** Put motion smears,
impact sparks or a hand-fixed silhouette on a `+fx` layer and keep iterating underneath it.
Edits to `<name>_parts.aseprite` itself do survive — `mode=import` writes that file, and
`mode=build` reads it rather than the PNGs.

**Re-run `mode=import` after every `segment.py` run.** `build` reads part pixels from
the `.aseprite` but provenance masks from the parts dir, so a stale parts file mixes
old pixels with new masks — that drifted 43 texels in one frame and was invisible
until `agree` caught it. `segment.py` now stamps the manifest, `import` copies the
stamp beside the parts file, and `build` refuses to run on a mismatch.

## Wired up

```bash
ASE="<path to Aseprite>"
RIG=<game project root>/examples/skeleton_warrior/rig.json
python pixelanim/segment.py $RIG && python pixelanim/render.py $RIG && python pixelanim/checks.py $RIG
python Tools/make_placeholder_sprites.py --pack-only
"<UE engine root>/Engine/Build/BatchFiles/Build.bat" MyGameEditor Win64 Development -Project=<game project root>/MyGame.uproject
"<UE engine root>/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" <game project root>/MyGame.uproject -run=pythonscript -script=<game project root>/Tools/make_sprite_material.py
```

The build is needed because the rect table is C++, and the editor must be closed for the
import. Every Aseprite tag becomes its own sprite, so `skeleton_warrior_idle` and
`skeleton_warrior_walk` are separate entries over one shared strip; frames/256 and fps/256
ride in the fraction of UV2, whose whole part is the atlas origin, and `M_Sprite` recovers
them and steps the origin by whole cell widths, phased per instance from the pivot hash so
a crowd does not breathe in unison.

## Still missing: choosing a state

Playback is time-driven, so a sprite loops whatever state it was placed with. Switching
idle → ready → windup → strike needs per-instance state, which a baked chunk mesh cannot
carry — that wants a real enemy actor owning its own sprite component, which is also what
the interruptible attack chain needs. The frames and the material are ready for it: the
actor only has to pick which `FSpriteRect` to draw.

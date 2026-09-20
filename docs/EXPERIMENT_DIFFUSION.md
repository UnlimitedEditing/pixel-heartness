# Experiment: diffusion turnaround + deterministic correction

Run 2026-09-20. Question: can the missing views of a sprite come from a diffusion workflow,
with the harness doing all the correcting? One subject (`skeleton_warrior`), one run.

## Setup

- Workflow `stage-3d` on Graydient (public, built on Qwen Image Edit 2509; ~110 s per run).
  Input: one front-facing image on a clear white background. Output: four 1024x1024 views.
- Input prepared as suggested: the 32x46 source sprite scaled 10x nearest-neighbour,
  centred on a 512x512 white canvas (`data/diffusion/skeleton_front_x10.png`).
- `graydient render "..." /run:stage-3d --init-image <file> --out <dir>`. The CLI uploads a local
  init image to a **temporary public host (litter.catbox.moe)** first; the sprite was reachable at
  that URL for its lifetime.
- Raw outputs and corrected views live in `data/` (git-ignored).

## What the workflow returned

| output | content | verdict |
|---|---|---|
| 3 | front, the input at exactly 20 px per texel | faithful, trivial |
| 2 | profile (skull and ribs in side view, shield edge-on) | **usable** after correction |
| 0 | the other profile | usable but muddier: brownish skull, smeared torso |
| 1 | the front, mirrored (shield on the other side, face visible) | **not a back view**: a skull from behind shows no eye sockets |

The two profiles are independent generations, not mirrors of each other: silhouette overlap with
the mirrored other is 68%.

## The correction step: `pixelanim/pixelize.py`

Deterministic; never adds detail. Removes the white background (flood fill from the border, on a
smoothed image, ignoring specks), searches texel size and grid offset together for the grid whose
cells are purest, majority-votes each cell after snapping every pixel to the source palette, and
makes alpha binary.

**Measured on known data** (the source sprite degraded the way diffusion output looks, then
recovered; texel match against the original):

| degradation | texel found vs true | match |
|---|---|---|
| exact 20 px grid | 19.99 / 20 | 100% |
| blur 2, off-grid shift | 20.01 / 20 | 99% |
| blur 3, noise 8, jpeg 60 | 19.88 / 20 | 81% |
| 17 px texel, blur 3, jpeg 50 | 17.01 / 17 | 76% |
| 23 px texel, blur 4, noise 12, jpeg 40 | 22.90 / 23 | 76% |
| 21 px texel, blur 5, noise 15, jpeg 35 | 21.00 / 21 | 67% |

The match falls with blur because blur mixes colours, which is real information loss, not a bug.
Texel size is recovered within 0.5% throughout. The real outputs have clean white backgrounds, so
they sit at the mild end of this table.

Two bugs found on the way, both mine: a height-based scale estimate that drifted half a pixel
per texel (fixed by searching size and offset together), and a test that pasted a 1058 px
sprite onto a 1024 px canvas and cropped the feet.

## Result on the real outputs

After correction all four views are on the source palette and scale (31x45 front, 11x45-47
profiles). Profile B reads as a clean side view.

**Measured, not assumed:** the profile is 11 texels wide against 31 for the front, a ratio of
**0.35**. That is the true thickness for this thin skeleton, and almost exactly the 0.4 the
front-only card spike guessed (`spike-yaw`). The Might & Magic reference (armoured, weapons out)
kept roughly its width through a turn. So thickness is a per-subject number, and a profile view
is how to measure it.

## Caveats

- One subject, one run. Variance between runs is unknown; the two profiles differ noticeably
  within a single run.
- "Usable" is my reading of a contact sheet at 8x. Nothing here measures whether a profile is
  *anatomically right*, only that it is clean palette pixel art at the right scale.
- The shield is drawn edge-on in both profiles; whether that matches how the sprite should turn
  is a design call.
- 3/4 views were not produced and not attempted.

## Next

1. A second and third run of `stage-3d` on the same input, to see how much profile quality varies
   and whether the back can ever be a back (a prompt hint, or a different slug such as
   `stage-8view`, which advertises multiviews).
2. Feed a corrected profile in as a part **variant** and drive it from `yaw`. Requires per-part
   segmentation of the profile, which is the same problem as segmenting the front.
3. Infer 3/4 from front + profile: not started.

## Follow-up: `edit-krea2` to rotate the subject 180 degrees

Run 2026-09-20. `edit-krea2` (Krea2 with an unofficial instruction-editing patch, ~34 s per run,
`/strength` 0.01-1.0: lower follows the instruction harder, higher keeps identity). Same 10x input.
Prompt: rotate the character 180 degrees to show the skeleton from directly behind, back of the
skull and spine and shield strapped to the back, same pixel art style, white background.
Strengths 0.3, 0.55 and 0.8, one run each.

| strength | what it did |
|---|---|
| 0.3 | blank cranium; a red strap across the ribs; the shield's dark interior with a grip; noisiest pixels, a few off-palette colours before snapping |
| 0.55 | blank cranium with a stray black band left over from the eye sockets; shield face still shown |
| 0.8 | cleanest blank cranium and neck; shield and ribs still front-facing |

**What it fixed:** the head. Every strength gives a cranium with no eye sockets, which is what
`stage-3d`'s "back" (a mirrored front, face showing) failed to do.

**What it did not do:** swap the lateral layout (the shield stays on the viewer's left where a back
view needs it on the right; a horizontal flip fixes that deterministically), or redraw the torso
as a spine (the ribcage stays a front ribcage). A skeleton's ribcage from behind is close to the
front, so that matters less than it would for another subject.

**How it was used:** per part. Only the head takes edit-krea2's result; every other part keeps the
flipped front, via the `back_art` view in the yaw spike (`docs/SPIKE_YAW.md`, branch
`spike-yaw`). One run per strength, so run-to-run variance is again unknown.

## Follow-up 2: the boar, and `edit-qwen21`

Run 2026-09-20. Two more findings, one about the workflow and one about the inputs.

**Inputs are not always front views.** Generated entities arrive front-on (the skeleton, a crab) or
already three-quarter (a boar). The pipeline therefore has to classify the facing first and work out
which views of the ring it already has (the *anchor*) and which it must produce. The ring has only
five unique views (0, 45, 90, 135, 180 degrees); the other three are mirrors. A silhouette-symmetry
score would separate a front view (high) from a 3/4 view (low); not yet built or measured.

**`edit-qwen21` rotates well; `edit-krea2` barely does.** Qwen-Image 2.1 image-to-image edit, ~65 s,
one run per prompt, from the 3/4 boar:

| prompt | result |
|---|---|
| rotate to face the camera | clean, symmetric front, same mane, ears, tusks, palette |
| rotate to a perfect side profile facing left | on-model side view: tusks, striped flank, curled tail kept |
| rotate to show it from directly behind | plausible rear: ears from behind, mane ridge, central tail, hooves |

By contrast `edit-krea2` at strength 0.65, asked for a 3/4 of the skeleton, returned the front view
with the shield enlarged and the torso narrowed, head still frontal. `stage-8view` returned no images
at all on the skeleton (cause not investigated). One run each throughout: variance is unknown.

**Making the views a ring: `pixelize.py --auto`.** The views come back at different pixel scales
(native texel 12.6, 11.1 and 14.7 px; 45 to 62 texels tall) and each would get its own palette. New
options, no source sprite needed:
- `--auto N`: palette of N colours from the image itself (median cut, plus a step that adds back any
  sizeable colour far from the palette, because median cut merges accents such as a pink snout or a
  tusk white into their neighbours) and the pixel period from the autocorrelation of the image's
  edges (exact on degraded synthetic data at 10, 14, 17, 20 and 23 px);
- `--height T`: force the sprite to T texels tall, so every view shares one scale;
- `--palette-from IMAGE`: take the palette from the anchor view, so every view shares one palette.

Result on the boar (anchor = the 3/4 input, height 46): front 33x47, 3/4 58x46, side 72x48, rear
35x48, one shared 24-colour palette. The snout is still paler than the original pink.

**Not yet done:** the 135-degree rear three-quarter (one more edit), the asymmetry patch for mirrored
views (matters for the skeleton's shield and weapon hand, likely little for the boar), a facing
classifier, and driving any of this from `yaw`.

## Follow-up 3: the boar's five unique views

Run 2026-09-21. The 135-degree rear three-quarter, two independent generations (`edit-qwen21`,
seeds 4101 and 7202, same prompt, from the 3/4 boar), pixelized with `--auto 20 --height 46
--palette-from <3/4 anchor>`.

| view | size (texels) | source |
|---|---|---|
| front | 33x47 | edit-qwen21 |
| 3/4 | 58x46 | the input, pixelized |
| side | 72x48 | edit-qwen21 |
| rear 3/4 (a) | 48x48 | edit-qwen21, seed 4101 |
| rear 3/4 (b) | 50x48 | edit-qwen21, seed 7202 |
| rear | 35x48 | edit-qwen21 |

Both rear-three-quarters read as the same boar seen mostly from behind: head turned away with the
tusk at far left, rump and curled tail nearest the camera, striped back. They differ in leg
positions and stripe detail, so two samples agree on the view and differ in detail. That is the
first (small) evidence on run-to-run variance for this subject. All six share a scale and a
24-colour palette. With the mirror images this is a complete eight-view ring for the boar, which is
close to symmetric so the mirrors need little patching.

Mistake on the way: the first two attempts submitted an invalid seed (a number with a letter
appended), so nothing was generated and the folders were empty; the second attempt broke on a shell
syntax error of mine. Both cost time, neither cost quota.

**Facing classifier (`pixelanim/facing.py`).** Silhouette mirror symmetry: boar front 0.97, rear
0.96, 3/4 0.73, side 0.67, and the skeleton front only 0.62, because its shield makes the outline
lopsided. It separates a symmetric subject from an asymmetric one but misreads a front-facing subject
carrying an asymmetric item. Treat it as a hint (open defect 16).

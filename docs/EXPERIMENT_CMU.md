# Experiment: retarget real mocap onto `skeleton_warrior`

Run 2026-09-20. This is the falsifiable experiment from HANDOFF section 9: can a real motion
clip, retargeted through `bvh.py` + `retarget.py`, beat the hand-written three-key `strike`?

**Verdict: no, and the tooling says why before you look at a frame.** Raw retargeted mocap is
worse than the hand-written strike on a front-facing billboard. It is still useful as a source of
*timing and extremes for the upper body*, and the classifier is the most valuable output.

## Data

CMU Graphics Lab Motion Capture Database, BVH conversion by B. Hahne, mirrored at
`github.com/una-dinosauria/cmu-mocap`. Free for research and commercial use, as long as the
animations themselves are not resold. Subject 2, trials 7-9 are "swordplay".

| file | bytes | frames |
|---|---|---|
| `02_09.bvh` | 790,078 | 1034 at 120 fps (8.6 s) |
| `02_08.bvh` | 1,137,312 | 1501 at 120 fps |

Not committed (`data/` is git-ignored). Re-fetch:

```bash
mkdir -p data/cmu && cd data/cmu
B=https://raw.githubusercontent.com/una-dinosauria/cmu-mocap/master
for f in data/002/02_09.bvh data/002/02_08.bvh READMEFIRST.txt; do curl -sSfLO "$B/$f"; done
```

Only `02_09` was used. Its right hand rises above the head at frames 555 and 819; frames
760-900 are one clean raise (760 to 820) and strike down (820 to 890). Window 761-900 at
every 5th frame (24 fps), reference frame 760.

## Method

`python pixelanim/bvh.py clip` reads the BVH, runs FK, projects to an orthographic camera,
and lays each mapped bone's world-angle change (from the reference frame) onto the rig's own rest
bone. Projected bone-length ratio survives, so foreshortening is preserved. `retarget.py fit`
then fits rig poses, reduces to 5 keys, and classifies. Part-to-joint map:
`examples/skeleton_warrior/cmu_map.json`, used with `--mirror` because the sprite's weapon is on
the viewer's right.

## Results

**Classifier (does the rig's in-plane articulation express this motion?)**

| camera | frames needing new information | parts flagged |
|---|---|---|
| front (azimuth 0), what the sprite is | 22 / 28 | legs, head, torso, weapon arm, shield |
| side (90) | 21 / 28 | legs, weapon arm |
| auto-chosen (285) | 18 / 28 | legs, weapon arm, shield |

No camera makes the swing in-plane: the auto search bottomed out at a 19% mean bone-length
change. An overhead strike travels in depth.

Two distinct reasons, and only one is fixable:
1. **Depth motion** (weapon arm, torso, head): needs a 3/4 view or authored variants.
2. **Legs**: a one-piece hip-to-foot bone cannot bend a knee, so it foreshortens every time the
   performer lunges. This is a rig limitation (needs a two-bone leg), not a camera choice.

**Gates on the retargeted states** (each in a scratch rig, re-segmented so underlap is sized
for the new poses):

| state | result |
|---|---|
| raw, root motion on | fails `holes`, `border`, `ground`: the performer travels 9-12 texels sideways |
| raw, root motion off, front camera | 1 torn texel; shield swing of 16-37 degrees uncovers ~77 invented texels |
| raw, root motion off, auto camera | 3 torn texels, border and ground fail; final key leans the torso 31 degrees and the head comes apart |
| upper body only (arms, torso, head) | front: passes every gate; auto: 3 torn texels in frame 25 |

**Against the hand-written strike.** Hand-written weapon arm: -20, +34, +44 degrees, a sweep
*across* the sprite plane. Mocap weapon arm: -72 to -110 for the raise, then back to -28, and it
never reaches +34/+44, because the real downswing goes toward the camera. The hand-written strike
is a stylised in-plane substitute, not an approximation of the mocap. That is the answer to the
question: fidelity to real motion was never what made it read.

## What it is good for

- **Timing and extremes for the upper body.** The raise (about 0.5 s) and the strike (about 0.6 s)
  give a believable ratio of anticipation to action, and the raise reaching well past the
  hand-written windup's -71 degrees suggests the hand-written one could be bigger.
- **The classifier.** "22 of 28 frames need new art, here are the parts" is exactly the
  deformable / needs-new-information split of HANDOFF section 2, measured rather than guessed.
- **Motions with no mocap library**, where the point was always to supply a curve.

## Caveats

- One clip, one performer, one rig. It says nothing about walks, which are largely in-plane
  from the side and may retarget well.
- The retargeted keys were reduced to 5; the hand-written strike has 3 plus separate windup,
  ready and recover states. Not a like-for-like frame budget.
- The fit still invents small motions from keypoint jitter (OPEN #7). Two of the four upper-body
  states show it.

## What would change the verdict

1. A **3/4-view rig** (or a camera the game actually uses), where a strike is nearer to in-plane.
2. **Two-bone limbs** so legs can bend.
3. A **walk or run clip**, where the front/side view is in-plane.
4. Part variants for the foreshortened arm, which is what the classifier is asking for.

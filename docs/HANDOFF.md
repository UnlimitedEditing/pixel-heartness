# Pixel-art harness — engineering history and roadmap (written inside a UE5 game project; paths below predate the split into this repo, see README.md)


Written 2026-09-20, at the end of the session that built `Tools/anim` (the cutout rig) and wired animated
sprites through the packer and `M_Sprite`. Read `pixelanim/README.md` first — it is the current state of the
art here, and this file is the argument for going much further.

The premise being tested: **an agent can animate pixel art well, and the lever is method, not model.** There
is a century of animation craft and a large pixel-art-specific literature, all free. If that knowledge is
turned into executable procedure with mechanical checks, an ordinary model should clear the bar, because the
bar at 46 texels tall is "does it read", not "is it beautiful".

This session produced evidence for that and also found the real ceiling. Both are below.

---

## 0. 2026-09-20, second session: the cut is solved, and it moved the ceiling

`Tools/anim` gained `segment.py`, `render.py`, `checks.py`, `sheet.py` and `riglib.py`.
`pixelanim/README.md` is the reference; this section is only what changed about the argument.

**The cut was the real problem, not the transform.** §6 listed "parts were cut with plain
rectangles" as ten minutes of hand work. It was not. Rectangles overlap, and on
`skeleton_warrior` the shield's rect swallowed both legs' rects entirely, so the pelvis
seeded from its whole box and grew until it owned both thighs. The legs then rotated about
hips whose art belonged to another part. That is not a touch-up, it is a broken rig that
happened to look plausible.

What replaced it, in three stages:

1. **Label** by colour-weighted geodesic flood from a handful of seed texels per part
   (multi-source Dijkstra, step cost rising with colour difference). Cuts snap to the edges
   the artist drew. The agent supplies two to four coordinates per part; the tool does the
   cut.
2. **Extent** — the load-bearing idea. *A part may only grow into territory owned by a part
   drawn in front of it.* Then z order hides the growth at rest however far it goes, and
   uncovers it exactly when the occluder swings away and the gap would otherwise open.
   Growing under a part drawn behind is forbidden, because it would repaint it.
3. **Fill** by reflecting across the part's own boundary, so synthesised texels are copies
   of authored ones and the palette is closed by construction.

**`mirror_of` turned out to matter more than underlap.** The shield hides the skeleton's
left arm and left leg almost completely — dilation has nothing to dilate. Naming a
bilateral twin and reflecting its whole region across `symmetry_x` rebuilds the limb, and
clipping that to what the occluder actually covers keeps the rest pose exact. This is the
cheapest answer yet to a whole block of §2's right-hand column.

**Result, measured against the old rectangle build of the same rig: 15 torn texels → 0.**

**A gate got sharper by being wrong first.** Counting enclosed background conflates two
things. A *tear* was body at rest and is now a window — the bug. *Negative space* was
already background, like the notch between a hanging arm and the ribs, which a swinging
part merely sealed at both ends. Fixing tears *raises* negative space, because the arm now
stays attached and closes the notch, so the raw count plateaus at 44 while tears go to
zero. A gate that had only counted would have read that as a regression.

**One rule of thumb in §4 and the old README was simply wrong.** "Rotating a limb about a
joint above it swings the far end down by `r(1−cos t)`, so pair any leg `rot` with
`dy: -1`." The real displacement is `x·sin t + y·(cos t − 1)`, and for a foot sitting
sideways of the hip the first term dominates — about 1.5 texels at 10°, not 0.2, and it
changes sign with the direction of swing. Removing the `dy` on the strength of the stated
formula put a foot through the floor within one build. It is now solved rather than
advised: `ground_lock` renders each frame, finds its lowest texel, and re-renders shifted
by whole texels onto the floor row. **This is the pattern §1 predicted — there will be
dozens of these, and each one belongs in the tool.**

**`agree` is the gate that matters most.** `render.py` (Python, the fast loop) and
`rig.lua` (Aseprite, for onion skin and `+fx` hand painting) implement the same maths twice
and are asserted identical every run. Without it the two would have silently drifted the
first time ground lock landed in only one of them.

### Open questions from §7, as far as this session got

- **Can an agent do the part segmentation?** Yes, with the tool carrying the geometry. What
  it could not do was place seeds from an image: two of eight seeds landed on shield-red
  texels rather than bone, and `leg_l` quietly stole a strip of the shield's edge. What
  caught it was not looking at the render — it was dumping the palette as text and reading
  which colour family each candidate texel belonged to. **The grid render tells you where
  things are; only a text dump tells you what colour they are.** `segment.py` should
  validate a seed against its part's dominant colour and refuse an outlier. Not yet done.
- **Does the agent need vision in the loop?** Every *structural* defect this session was
  found by counting. Vision was decisive exactly once, for taste: four candidate idles were
  scored numerically, the highest-scoring one looked like a gesture rather than breathing,
  and the one that actually reads sits near the bottom of the range at 1.6%. **Numbers
  rank, eyes choose.**
- **Where does per-subject tuning live?** Top-level rig fields: `underlap`, `symmetry_x`,
  `ground_lock`, `airborne_states`, and `states[].min_distinct`. The last exists because a
  single distinctness bar is wrong in principle — an idle is deliberately low-amplitude
  while an attack must show a readable commit point.
- **Is there prior art?** Still not searched. Worth doing: underlap is standard practice in
  Spine and DragonBones, where artists draw each part complete and let z order hide the
  overlap. What is new here is only deriving it automatically from a flat sprite.

### Addendum: the artefact the gates missed

A stray patch of texels was spotted by eye under the skeleton's sword hand, sitting
still while the arm swung past it. Every gate was green at the time. Three separate
mistakes had to line up, and each one generalises:

**Euclidean growth jumps gaps.** The pelvis sits a few texels from the sword arm with
bare background between them, so dilating it by a disc of radius 6 leapt the gap,
landed on the arm, and left a blob of invented hip texels out at the hand. It passed
`rest` because the arm covered it standing still, and the pelvis is the unposed root,
so the blob never moved. Growth now travels **geodesically**, only through the
subject: growth that has to cross background is never covering a seam, because there
is no seam there.

**A single global radius is unachievable, not just untuned.** Sweeping it showed tears
and floaters pulling in opposite directions — 74 torn / 13 floater texels at radius 0,
and 0 torn / 202 floater at radius 6, with nothing good in between. The radius the
sword tip needs *is* the radius that lets the pelvis creep along that arm. The fix was
to stop picking a number: the cover needed at a texel is exactly how far the
occluder's material drifts from the material behind it, `max over frames of
|M_P(t) − M_Q(t)|`, which for an affine rig is computed from the rig's own pose list.
It re-derives itself when a state is edited. `underlap` survives only as a cap.
**Where a constant appears in this harness, check first whether the rig already
contains the quantity it is standing in for.**

**The renderer should enforce what the gate asserts.** The remaining floaters are now
dropped at composite time — any visible component of a part made only of invented
texels is removed, because underlap is meant to be revealed *attached* to the art it
extends. `checks.py floaters` asserts the same property, so the gate cannot be
satisfied by something the renderer would not produce. Both renderers do it and
`agree` keeps them in step.

Two smaller results fell out of the same investigation:

- `holes` now classifies each hole as a **region**, not texel by texel. A notch that
  was always there swallows a texel or two of former body as it seals; calling those
  an independent tear was noise, and the viewer reads the window as one thing anyway.
  Scored under the new rule, the pipeline is 0 torn against 69 for no extension — the
  signal is unchanged.
- `build` now refuses a parts file stamped by a different `segment.py` run. It reads
  part pixels from the `.aseprite` and provenance masks from the parts dir, so a
  stale import silently mixed old pixels with new masks and drifted 43 texels in one
  frame. `agree` caught it; nothing else would have.

**The lesson for §7's vision question.** The earlier answer — "numbers rank, eyes
choose" — was too generous to the numbers. Every gate was green while a visible
artefact sat in the frame, because no gate had been written for that artefact yet.
Gates catch regressions of defects someone already characterised; they do not
enumerate defect classes. Looking is what finds the *first* instance, and the job then
is to turn it into a gate the same day. The floaters gate took twenty minutes to write
once the artefact had a name.

### What to do next, in order

1. **Seed validation** in `segment.py` (above). Cheap, and it closes the one failure mode
   that still needed a human. Pair it with a colour dump in `sheet.py`, since that is
   what actually caught the bad seeds.
2. **The two missing primitives from §3** — squash/stretch about a base line, and lag down a
   chain. Both are small, both unlock whole archetypes, and neither needs anything from the
   segmentation work.
3. **Part variants** (§2's first deliverable) — cheaper now, because `segment.py` already
   emits one file per part and the manifest can carry alternates.
4. Only then the motion-reference work in §9.

---

## 1. What the last session actually established

`skeleton_warrior` went from one static frame to 17 frames across 6 states, playing in game, with no pixel
ever authored by a model. The frames came from a JSON pose list: per part, per frame, `{rot, dx, dy, sx, sy}`
over an FK hierarchy. An agent wrote that JSON from the animation literature alone — anticipation on the
windup, a two-frame contact on the strike, a passing pose in the walk — and it reads correctly.

That is the existence proof, and it is narrower than it looks. Three findings matter more than the frames:

**Every real defect was found by measurement, not by looking.** The 32x48 cell was too small — not because a
render looked wrong, but because a script counted 8 of 17 frames touching the cell border. The walk's feet
sank through the floor for the same reason. In game, "it looks animated" was worthless at 40 m where a texel
is sub-pixel; what settled it was 4253 changed pixels on sprites against 0 in a ground control band. **A
harness without cheap mechanical gates is not a harness, it is a slot machine.**

**The model could not place a pivot from an image.** Reading joint coordinates off a 32x46 sprite failed until
a numbered grid was rendered over it (`pixelanim/grid.py`). This is a tooling fix, not a model limitation to
be trained around: the harness must never ask for a coordinate without supplying a labeled reference, and
should prefer letting the agent name a joint semantically over having it type numbers at all.

**A mechanical constraint was discovered that no prompt would have supplied.** Rotating a limb about a joint
above it swings the far end downward by `r * (1 - cos θ)`, which pushes feet through the bottom border. Every
leg rotation needs a paired lift. There will be dozens of these. **They belong in the tool's validation, not
in a prompt**, because a prompt is advice and a gate is a guarantee.

---

## 2. The crux: does the motion need new information?

This is the axis the whole harness should be organized around, and it is the honest ceiling on the rig.

A cutout rig moves existing texels. It can never produce a pose that requires texels that were never drawn:

| Deformable (rig can do it) | Needs new information (rig cannot) |
|---|---|
| Limb swing, lean, bob, squash/stretch | Head turning to profile |
| Weapon arc in the sprite plane | A limb foreshortening toward camera |
| Recoil, stagger, knockback | The far side of a shield coming into view |
| Cape/cloth follow-through | A mouth opening, an eye blink |
| Whole-body translate and tilt | Anything rotating out of the picture plane |

Most game animation for a front-facing billboard is in the left column, which is why this approach works at
all. But **the harness must be able to classify a requested motion into these columns and say so**, because
silently approximating a right-column motion with a left-column tool is exactly how you get the mush we were
trying to avoid. When a motion lands right, the options are: author a second part variant by hand (a profile
skull as an alternate `head` layer), or accept a stylized substitute (pixel art routinely fakes a head turn
with a 1-texel shift and a squint, and it reads).

**First real deliverable for the new session: make the rig support part variants,** so a state can swap
`head` for `head_profile` on specific frames. That single feature moves a large block of the right column
into reach, and it is a small change to `rig.lua`.

---

## 3. Why "unique methods per subject and motion" is right, and what it implies

Agreed, and it implies more than a prompt library. A rig is a *claim about how a subject articulates*, and
`rig.lua` currently supports exactly one claim: rigid parts under affine transforms in an FK tree. That is
correct for a skeleton and wrong for most other things:

| Archetype | Articulation | Primitive needed | Have it? |
|---|---|---|---|
| Biped (skeleton, wizard, knight) | FK chain of rigid parts | per-part affine | yes |
| Slime, ooze, blob | no skeleton; volume conservation | per-column or per-row scale, squash/stretch about a base | no |
| Bat, bird, insect | wings; 2-3 frame ping-pong, no FK | mirrored part pairs, phase offset | partly |
| Floating (crystal, wisp, eye) | rigid body, no joints | whole-sprite translate + bob + rotate | yes (trivially) |
| Quadruped | two FK chains, phase-offset gait | same as biped + gait phase table | yes, needs a method |
| Cloth, cape, tail, chain | follow-through; each segment lags its parent | FK chain with a lag/damping term per frame | **no, and it is cheap** |
| Projectile, effect, explosion | no subject persistence; redrawn per frame | not a rig problem at all | n/a |

So the harness is a **primitive library** as much as a method library. Two primitives are conspicuously
missing and both are small: **squash/stretch about a base line** (unlocks every blob and every impact) and
**lag/damping down a chain** (unlocks capes, tails, and the follow-through that makes strikes feel heavy).

Method, then, is a triple: *archetype → primitive set → motion recipe*. The recipe is where the literature
lives, and it is mostly numbers: how many frames, which are keys, where the holds go, how spacing eases.

---

## 4. What the literature actually gives us, concretely

Worth stating precisely, because "use the 12 principles" is not executable and the pixel-specific rules are
the ones that bite.

**From general animation, as parameters:**
- Key poses first, breakdowns second, never inbetween-then-fix. Our states already read because they are
  keys-only. A 2-frame windup with a hold beats a smooth 8-frame arc.
- Anticipation is opposite the action and roughly a third of its magnitude.
- Contact/overshoot/settle: the strike's extreme is *past* the rest pose, then settles back. Our `strike`
  does this (`rot 34 → 44` then `recover 22 → 8`) and it is why it reads.
- Spacing carries weight: even spacing reads mechanical, tight-then-wide reads snappy. This is pure numbers
  in the `hold` and rotation deltas.
- Follow-through lags the driver by one frame. Needs the damping primitive above.

**From pixel art specifically, as hard constraints the gates should enforce:**
- Motion must be in **whole texels**. Sub-texel drift makes edge texels toggle under the post pass and reads
  as flicker, not motion. `M_Sprite`'s wind sway already rounds to whole texels for exactly this reason; the
  rig's nearest-neighbour sampling does it implicitly, but nothing currently *checks* it.
- Silhouette is the whole game at this size. A pose that is unreadable as a solid black shape is a failed
  pose. **This is a cheap mechanical gate nobody has written: flatten the frame to alpha and check the
  silhouette differs enough between consecutive key poses.**
- Low frame counts are a style, not a compromise. ART_SPEC's defaults (idle 2-4, walk 4, attack 3-4) are
  correct and should be treated as ceilings.
- Limited palette: a deformation must not invent colours. Nearest-neighbour sampling guarantees this; a gate
  should assert it anyway, because any future primitive that blends will break it silently.
- Interruptibility (the design goal): states must be *pose-distinct*, so a player can read the commit point.
  This argues for fewer, more extreme keys — and it means "does frame N of windup look clearly different
  from frame N of strike" is a **design** gate, not just an art one.

---

## 5. Proposed shape of the harness

Not a monolith. Four layers, each independently testable:

1. **Primitives** (`rig.lua` and successors). Pure, deterministic, no agent involvement. Affine-per-part
   today; add part variants, squash/stretch, chain lag. Every primitive guarantees the pixel-art invariants
   (binary alpha, whole-texel, no new colours) by construction.
2. **Gates** (`pixelanim/check*.py`). Cheap, mechanical, run after every build. Have: border. Need:
   whole-texel motion, silhouette distinctness between keys, palette conservation, ground-contact (feet on
   row H-2 except when deliberately airborne), state distinctness.
3. **Methods** (new: `pixelanim/methods/`). Per archetype-and-motion recipes, in a form an agent executes
   rather than reads — which parts move, in what order, how many keys, where the holds are, what the gates
   should show. Written as markdown with worked numbers, one file per recipe.
4. **The agent loop.** Read subject → classify archetype → pick method → emit rig JSON → build → run gates →
   read the contact sheet → revise. **The loop is only as good as layer 2**, which is why gates come before
   any agent work.

The ordering claim: **build gates before building the agent loop.** An agent iterating without gates will
confidently produce mush, and we will not know.

---

## 6. The case study: `skeleton_warrior`

Everything needed is on disk.

| Thing | Where |
|---|---|
| Source sprite, 30x44 content | `Art/Source/Sprites/parts/skeleton_warrior.png` |
| Parts, one layer per body part | `Art/Source/Anim/skeleton_warrior_parts.aseprite` |
| Rig: 8 parts, 6 states, 17 frames | `examples/skeleton_warrior/rig.json` |
| Built animation, layered and tagged | `Art/Source/Anim/skeleton_warrior_anim.aseprite` |
| Frame strip + tag table | `Art/Source/Anim/skeleton_warrior_strip.png` / `.json` |
| In game | `EDecor::Skeleton`, sparse in Sunken Shore and Ashen Badlands |

**Known defects, deliberately left unfixed so the new session has a real subject:**
- Parts were cut with plain rectangles, so the arms carry stray rib pixels and there is a seam under the
  skull. The intended fix is ten minutes of hand work in the parts file — **but the new session should first
  ask whether an agent can do this cut**, since "segment a 30x44 sprite into named body parts" is a crisp,
  checkable sub-problem and a perfect first test of the harness thesis.
- Shield and weapon arm swing wide; poses are unpolished.
- `idle` is barely perceptible at distance. Possibly correct, possibly too timid — needs a judgement call.

**Suggested first experiment,** because it is small and falsifiable: have an agent re-author the `strike`
state from scratch, given only the parts file, the rig schema, and a method file for "biped, one-handed
overhead strike, interruptible". Compare against the hand-written version in git. If it matches or beats it,
the thesis holds for the easiest case and the question becomes how far it scales. If it fails, the failure
will be specific and will name the missing gate or primitive.

---

## 7. Open questions for the new session to settle

- **Does the agent need vision in the loop at all, or only for final judgement?** Layers 1-3 are parameter
  space. My suspicion is vision is needed only to catch silhouette failures the gates miss, and that a
  contact sheet at 6-8x with frame labels is the right and only visual input.
- **Can an agent do the part segmentation?** See above. If yes, the whole pipeline is agent-drivable from one
  static sprite. If no, every character costs ten human minutes, which is still fine.
- **How is a method file written so it is executed rather than paraphrased?** Worked numbers and explicit
  gates, probably. This is the core authoring question of the whole project.
- **Where does per-subject tuning live** so it is not re-derived per character — a per-archetype defaults file
  that a rig inherits from?
- **Is there prior art to steal?** Nothing was found matching "agent drives cutout rig with animation
  principles". Worth a proper search before building; DragonBones, Spine, and the Aseprite scripting
  community are the places to look for primitives, and the pixel-art tutorial corpus for method content.

---

## 8. Not part of this, but blocking the payoff

Playback is time-driven: a sprite loops whatever state it was placed with. Switching idle → ready → windup →
strike needs per-instance state, which a baked chunk mesh cannot carry. That wants a real enemy actor owning
its own sprite component — the same thing the interruptible attack chain needs. The frames and material are
ready; the actor only has to pick which `FSpriteRect` to draw. **The harness can be developed and judged
entirely without it**, via contact sheets and GIFs, so it should not block this work — but the design goal
(interruptible states, readable commit points) cannot be truly evaluated in game until it exists.

---

## 9. Diffusion as a motion reference: use it for the curve, never for the texels

Raised as "procedural agentic mocap". It is a good idea with one line that must not be
crossed, and a by-product that is better than the idea itself.

**The line.** Every guarantee this pipeline has — palette closure, whole-texel motion, a
rest pose identical to the source, no invented art outside an occluder — exists because no
generative model ever touches a texel. Nearest-neighbour sampling of authored pixels is
what makes "the same fabric rustle looking like a different character next frame" a
non-problem, and §1 of the session notes chose the cutout rig for exactly that reason. So:
**diffusion may produce a motion curve; it may never produce a pixel.** The output of the
whole path is rig JSON — a text file you can diff, review and hand-edit — and nothing
downstream changes.

**The pipeline, if built.** Reference clip → per-part 2D tracking (a keypoint estimator for
anything humanoid, optical flow otherwise) → solve each frame for the `{rot, dx, dy}` that
best matches the tracked bone angles → reduce 24 fps of smooth motion to the 3–4 keys
ART_SPEC wants → quantise translations to whole texels → run the gates.

The reduction step is where the animation literature already lives, and it is mechanical:
**the keys are the local extrema of each joint's angle curve.** "Key poses first,
breakdowns second, never inbetween-then-fix" and "pick the extrema" are the same operation.

**The by-product, which is the best part.** Fitting an in-plane affine per part produces a
*residual*. A motion the rig can express fits tightly; a head turning to profile, a limb
foreshortening toward camera, or the far side of a shield rotating into view will not fit
at any parameter. **That residual is the deformable / needs-new-information classifier §2
asks for, and it comes free.** §2 says the harness "must be able to classify a requested
motion into these columns and say so"; nothing else proposed so far actually measures it.
That alone might justify building the tracking half.

**Sequence the risk.** The weak link is not tracking or fitting — it is that a 32×46 sprite
is far outside any img2vid model's distribution, and de-stylising it first is the same
problem that sank the TripoSG idea in the session notes. So do not start with diffusion:

> **First experiment: retarget a humanoid motion from clean 2D keypoints — a stock clip or
> a free BVH of an overhead strike — onto `skeleton_warrior`'s existing rig, and compare
> against the hand-written `strike` in git.**

That isolates retargeting from generation entirely, needs no model, and is falsifiable in
an afternoon. If clean keypoints cannot beat a hand-written three-key strike, a diffusion
clip will not rescue it, and the whole path dies cheaply. If they can, the real question
becomes worth asking — and it is narrower and more interesting than "use img2vid":

**Diffusion earns its place precisely where no motion library exists.** There is mocap for
bipeds and none for a slime, a wisp, a floating eye or a bat — which is exactly §3's table
of archetypes the rig cannot yet serve. A generated clip of "a blob of slime hopping" is a
plausible source for a squash/stretch curve in a way it is simply not needed for a walk.

**What not to do:** use the generated video as a per-pixel target and let the harness redraw
texels to match it. That reintroduces the temporal inconsistency the cutout rig was chosen
to avoid, breaks palette closure, and still needs amodal completion for anything occluded.
The rig already knows how to move texels correctly. It only lacks a curve. Supply the curve.

---

## 10. Two design conclusions from the end of the second session

Discussion, not code. Both change what should be built next, so they are here rather than lost.

### How much looking this actually needs, long term

The claim worth holding: **eyes scale with the number of primitives, not the number of
assets.**

Of the ten gates, seven — `rest`, `palette`, `border`, `wholetexel`, `ground`, `floaters`,
`agree` — assert properties of the *representation*, not of skeletons. They transfer to
every future subject for free; only their thresholds are per-subject. Every gate that had
to be *discovered* was discovered because a mechanism was new: underlap created the tear
class, dilation across background created the floater class, ground lock created the
offset-alignment class.

So the curve that decides whether this scales is not "defects per asset". It is **new gate
classes per new primitive**, and the roadmap has maybe six primitives left in it. If each
costs two or three gates, that is a bounded one-time tax against unlimited content.

That is measurable and worth measuring from now rather than reconstructing later: a
`pixelanim/DEFECTS.md` recording, per defect, what found it (a gate or an eye) and which
gate covers it now. If the eye-found column thins as subjects accumulate but reappears with
each new primitive, the thesis is confirmed with a shape rather than a feeling. **Not
started — start it with the next primitive, or it is worthless.**

What gates will not take over is taste. The idle is the clean example: the gate correctly
said "these two keys are too similar" and could not say "this one reads as a gesture, not
breathing". But it still did the expensive part, narrowing four candidates to a ranked list.
That is the realistic end state — eyes as a final one-bit judgement, not as the search.

### The label map as a compile target, and where SAM fits

Raised as: rather than diffusing pixels, have a model author a *map* of the kind
`sheet.py map` prints, and compile that to texels deterministically — with something like
SAM3 classifying parts off the source image first.

The architecture is right, and it is the same move this harness already makes. Rig JSON is
an IR: the model emits parameters, deterministic code emits texels. A label map is simply a
more expressive IR. It buys palette closure by construction, errors that are local and
legible (a wrong label is a recolour, not mush), and gates that get *easier* — silhouette,
connectivity, outline continuity and part counts are all trivial on labels.

Two refinements before anyone builds it:

**Part labels alone cannot produce pixel art.** "This texel is arm" does not say which of
the five arm colours, and at 46 texels the shading *is* the read. The IR needs part plus a
**shade role** — outline / core / shadow / highlight / rim — which is the pixel artist's
real working vocabulary and a small alphabet. Shade role is *derivable* rather than
guessable given a light direction and a surface-normal proxy, which makes the compiler a
shader. The world geometry is already shaded into pixel art by a dither pass; the sprite
path and the world path converging on the same abstraction is a good sign it is real.

**SAM3 at 32x46 is the same out-of-distribution bet as img2vid.** It is trained on
photographs; a 14-colour sprite with 1px black outlines gives it very little to grip. You
would upscale first, at which point it segments by flat colour region — approximately what
`segment.py`'s colour-weighted geodesic flood already does, deterministically, at zero cost,
with exact texel boundaries and no resample round trip. SAM also returns masks, not names,
so the real chain is SAM + a VLM to name them. That replaces eight hand-typed seed
coordinates, and the failure actually hit this session is fixed by ten lines of seed
validation.

The calculus flips at scale — for a hundred enemies, seed-free segmentation is the
difference between a pipeline and a chore. And it is **cheaply falsifiable right now**,
because there is ground truth: run SAM on the upscaled `skeleton_warrior` and score its
masks against the current label map. If it cannot match a free method on the one sprite
where the answer is known, that settles it before any ComfyUI work.

**The strongest version of the idea** is not re-deriving an existing sprite. It is authoring
label maps for poses the rig *cannot reach* — the head turn, the foreshortened limb, §2's
right-hand column. A label map is a plausible generation target precisely because it is
low-entropy and heavily constrained, and the harness already manufactures the training data:
every posed frame has an `owner` map, so (pose parameters -> label map) pairs come free from
any rigged subject.

The cheap version still comes first. A head turn does not need generation, it needs a **part
variant** — one alternate `head` layer swapped on specific frames, already §2's first
deliverable. Generation earns its place at forty subjects, not at one.

### Noted, not decided

Productising this as a hosted tool was raised and deliberately deferred until the local
pipeline is settled. Nothing in the current design blocks it: the IR is JSON, the compiler
is deterministic, and the gates are the product's quality floor. Worth keeping the
Aseprite dependency optional for that reason — `render.py` already has no need of it.

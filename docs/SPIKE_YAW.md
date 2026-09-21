# Spike: `yaw`, front-only cards as a turntable (branch `spike-yaw`)

Python-only, deliberately not merged. No Lua mirror, so `agree` would fail on any rig that uses it.

## What it does

`frame.yaw` (degrees) turns the whole figure about its vertical axis as flat cards: one x-scale by
cos(yaw) about the body axis, |cos| clamped at `yaw_thickness` (0.4) so it never vanishes, mirrored
past 90 degrees, with parts re-sorted by depth (`base_depth * cos + lateral_offset * sin`).
See `riglib.yaw_matrix`.

## Result: it is a filler, not a turntable

Twelve facings on `skeleton_warrior` (`turn` state, every 30 degrees). All existing gates pass
(rest, palette, holes, floaters, border, ground, distinct, synth, rotation), which only says it is
structurally sound.

- **0 to ~45 degrees reads as a turn.** The shield crosses correctly and the figure narrows.
- **60 to 120 degrees degenerates.** The body becomes a thin tall sliver and the skull a narrow bar.
  It reads as a squeezed sprite, not a turned one. There is no profile art to show.
- **"Back" is the front flipped.** At 180 the face is still visible, mirrored. Wrong.
- **Depth sorting works** (shield in front at 60, behind the ribs by 120-150), which is the one
  part of the model that is right and cheap.

## Against the Might & Magic sheet (a reference only, not committed)

The width column of my own turn matched the model exactly; that is circular and proves nothing.
The real comparison is the reference: in each of its 26 pose columns, silhouette width across the
five rows barely changes (row 1, 2, 3 over row 0: means 1.09, 1.12, 1.02; minimum 0.71-0.80). A
real turn keeps roughly its width, because a body has depth and arms and weapons stick out. My cards
collapse to 0.4. Caveats: the rows may not be evenly spaced facings (row 4's widths almost equal
row 0's, so they are not a simple 0 to 180 degree ring), and armed poses vary.

## Conclusion

Cards are only good between authored key views. The 90-degree profile and the back cannot come from
a front sprite and need real art, which means part variants per view. Next, if pursued: per-part
views (front, side, back) chosen by yaw using the existing variant machinery; mirror for the other
half; keep card scaling and depth sorting for in-betweens; a gate that adjacent facings differ by a
bounded amount; the Lua mirror.

Not done, and needed first: authored side and back art. That is the real cost, and it is the one
place generation might earn its keep.

## Update: per-part views from a diffusion profile

Second spike, same branch. `stage-3d` supplied a profile (`docs/EXPERIMENT_DIFFUSION.md`);
`pixelize.py` put it on the sprite's grid and palette; `examples/skeleton_warrior/make_views.py`
cut it into per-part variant art by boxes read off the printed map (crude on purpose: one visible
leg, an edge-on shield and a glove overlapping the hip defeat seed-based flood). `riglib.yaw_plan`
picks, per part, the nearest available view (front 0, side 90, back 180 via the flipped front,
side_l 270 via the mirrored profile) and scales the card by cos of the leftover angle, so no card is
squashed below ~0.7. `make_turn_rig.py` builds `rig_turn.json`: 24 frames, every 15 degrees.

**Reads well:** 0-45 (narrowing front), 60-135 (a real profile: skull, ribs, glove, edge-on shield),
240-300 (the mirrored profile), 315-345 (front again).

**Reads badly:** 150-225, the back. It is the flipped front with the face still showing, the chest
becomes a black mass, and up to 200 texels per frame are invented (frame 10: 164 of 573). No real
back exists; a diffusion "back" was a mirrored front. Also a visible pop at 45-60 degrees, where
the front card (~0.7 wide) hands over to the profile (~0.87): there is no 3/4 view.

**Gates on it:** rest, palette, floaters, border, ground, synth (reported), rotation pass. `holes`
tears one texel at the foot in frames 4-8. `distinct` fails between consecutive frames that pick the
same profile (yaw 75, 90, 105 render identically, which is correct). `variant` fails for a
reason that is a gate bug, not an art bug: it assumes a variant overlaps the silhouette of the
part it replaces and is used by a pose, and a *view* variant does neither. Merging needs the gate
taught the difference, the Lua mirror for `agree`, and a `yaw` state that doesn't rely on `distinct`.

**Measured input:** profile 11 texels wide against 31 for the front (0.35), used as `yaw_thickness`.

**Open before it can merge:** a real back (or an honest decision to only ever show the flipped front
where the back is not seen); a 3/4 view (infer from front + profile, or accept the pop); the second
leg (the profile shows one, so `leg_l` has no art at 90 degrees); rotation of profile parts under
animation has not been tried; run-to-run variance of the diffusion profile is unknown.

## Update: the back view, head only, from edit-krea2

`riglib.DEFAULT_VIEWS` now lists a `back_art` view (variant `back`, mirrored) ahead of the plain
`back` (the flipped front), so a part with back art uses it and every other part keeps the flipped
front. `make_views.py` builds `views/back_head.png` from the edit-krea2 result at strength 0.8.
The variant is stored raw (lateral layout unswapped) because the mirrored `back` view swaps it.

**Result (yaw 135-225):** the skull is a blank cranium, no face. The body is unchanged and still
weak: the chest is a dark mass and the shield is drawn over the torso with a smeared emblem
(underlap fill; up to ~29% of a frame's visible texels are invented). One of the three tells of
a fake back is fixed.

## Update: per-part segmentation of five generated views (skeleton)

Third spike step, same branch. The five unique views of the skeleton (front, 3/4, side, rear 3/4 with its
shield moved across, rear; see `docs/EXPERIMENT_DIFFUSION.md`) are now cut into the rig's eight parts and
driven by `yaw`, so each part chooses its own view art and the character turns as one body.

**Pipeline (`examples/skeleton_warrior/`):**
1. `make_ring_views.py` registers each view into the 48x48 cell: body axis (found with the handed items
   excluded) on the front's axis (cell column 24.5), lowest texel on the ground row 46. A variant image the
   size of the cell is placed at 0,0, so registered art lines up across views.
2. `segment_views.py` proposes seeds per view from geometry and colour (shield = largest red-family
   component, glove = the next, head above the narrowest row under the skull, torso/pelvis/legs on the axis
   by height), cuts with `segment.py`'s flood (seed validation on: passed on all four views), writes a label
   picture (`skel_labels_*.png`) to check by eye, and exports each part's own texels per view.
3. `make_turn_rig2.py` builds `rig_turn2.json`: 32 part variants, eight views (0, 45, 90, 135, 180, and 225 /
   270 / 315 as mirrors), a 24-frame turn state, and `handed: true` on the shield and both arms.

**In the renderer** (`riglib.yaw_plan`): a view can set `patch_handed`; in that mirrored view a `handed`
part is not flipped, so the shield stays on its own side of the body. This is `mirror_patched` applied
per part instead of per colour.

**Reads well:** every frame is the same character; the shield travels left -> centre -> right -> centre ->
left; parts never disagree about the view because they all come from the same registered image.

**Gates:** palette, floaters, border, ground, synth (0.0% invented) pass. `holes` fails on the 3/4, rear and
mirrored frames (5-22 enclosed texels): it counts enclosed background absent from the *front* pose, and a
real 3/4 view legitimately has gaps between arm and body. It needs to compare a yaw frame against its own
view, not the front. Defect logged.

**Still rough:** frames change art at the 22.5-degree boundaries (a visible step between views, inherent to
five drawn views); the rear 3/4 and its mirror have fragmentary legs and a floating foot from the generated
art; the far leg hidden behind the shield in a 3/4 view is missing in that view; nothing here has a Lua
mirror, so `agree` does not apply.


## Update: the walk at eight facings (G1, G2, G7)

`rig_walkturn.json` (from `make_walk_turn.py`): the authored four-frame walk at facings 0, 45, ..., 315,
32 frames, using the per-view part art.

- **G1, per-view pivots** (`derive_pivots.py` -> `views/pivots.json`, `world_matrix(..., pivots=)`, the
  `pivot` in `yaw_plan`): a joint is where a part's texels meet its parent's, at the contact point nearest
  the parent's centre (the centroid of a long contact put the profile hip 5 rows too low). Compared with
  the front-view pivots on the profile walk, legs stay attached at the hip. Counting detached pieces, the
  improvement is real but small (a profile frame goes 2 pieces -> 1, another 4 -> 3) and the number of
  small floating fragments barely moves (9 -> 8): most of those come from the generated leg art, not the
  joints.
- **G2, view-dependent swing** (`yaw_gain` on a state, `riglib.yaw_gain`): the leg swing is multiplied by
  lerp(1.0, 2.5, |sin yaw|), so the authored +-10 degrees becomes +-25 in profile. A mirrored view mirrors
  the swing by itself, so the sign is left alone. Scissors, as predicted, without a knee bend.
- **G7, facing-aware gates:** `holes` compares each frame against the rest silhouette of its own view
  (fixes open defect #17), `palette` allows a declared flash colour, and a new `facings` gate compares
  frame k across the facings of one animation (`<kind>_<yaw>` states).

**Three findings that only showed up by rendering:**
1. The rear 3/4 art was 46 rows tall against 44 for the rest. Invisible until the torso bob pushed it into
   the top border; `facings` now catches it. Fixed at source: `pixelize.py --height`, and the default +-5%
   texel search had to be tightened when a height is forced (it re-inflated 44 rows back to 47).
2. **View art had no underlap.** The front sprite has extra texels tucked under neighbouring parts, derived
   from the rig's pose list; the views were exported as own-texels-only, so any relative motion between
   parts (a torso bob) opened a gap at every non-front facing (up to 7 texels in the profile).
   `segment_views.py` now runs each view through the same derivation and exports the extended layer plus a
   synth mask (`<view>_<part>.synth.png`), which `Parts` loads so stray patches can still be culled.
   Gates went from 12 failing frames to 4.
3. Rendering both pivot variants into the same strip file silently overwrote the first.

**Left:** 4 one-texel tears at the neck seam of the mirrored views; stray foot fragments in the profile
(generated art, defect G9); no knee bend (G3).


## Update: the full set (G4, G5, G6)

`examples/skeleton_warrior/make_full_set.py` builds `rig_fullset.json` and `fullset_manifest.json`: eight states at
eight facings, 33 frames per facing, 264 in all. See `docs/ANIMATION_SET.md` for the status table and numbers.

New in the renderer: `flash` (a frame's colour override), view variants may carry a synth mask, `yaw_gain`, per-view
pivots. New in the gates: `facings`, thickness-based `holes`, yaw-aware `volume`/`variant`.
`segment_views.py` now cuts each view twice (once to find the joints, again with underlap sized for those joints and for
the worst-case poses of every state, written by `make_full_set.py`).

Not merged to `main`: this is a spike branch with no Lua mirror.

## Update: the shoulder-seam cracks (defect #18), what worked and what did not

Diagnosis by looking, not theory: at 225 and 315 degrees the cracks are *inside the ribcage*, beside the glove and below
the shield's inner edge, appearing in frames whose pose is tiny (`idle`: arms 3-6 degrees). In a patched-mirror view the
torso half that the shield hid in the original is missing, and it lands under the (unmirrored) sword arm; at rest the arm
covers it, and any arm motion uncovers texels that were never drawn.

| attempt | frames with a crack / crack texels |
|---|---|
| baseline (underlap sized for the old poses) | 67 / 209 |
| underlap sized for the worst-case poses of every state | 65 -> 63 |
| underlap derived with the view's own pivots | 67 |
| `mirror_of` restored in the view rigs (the front rig has it; my copy dropped it) | 70 / 209 |
| underlap also sized for the *other* arm's motion (poses with the arms swapped) | 67 / 183 |
| underlap cap 4 -> 8 | 59 / 149 |
| cap 8 -> 14 | 60 / 151, and a floater appears |
| conjugated FK for handed parts (arm follows the *mirrored* torso) | 59 / 149 vs 54 / 125 without it: **worse, reverted** |
| final (plain FK, `mirror_of`, swapped-arm poses, cap 8) | 54 / 125 |

A theory I liked (a 16 degree disagreement between the mirrored torso and the unmirrored arm) was measured and was wrong.
What remains is concentrated at 225 and 315 (12 and 13 frames). The honest fix is art: author the mirrored views' torso
half, or accept a small tolerance for those facings.


## Update: two-bone legs (G3) and the underlap trade-off

`make_2bone_rig.py` splits each leg at the knee into a thigh and a shin. The views get shin seeds; the walk gets a knee bend
(`WALK_2BONE` in `make_full_set.py`). New `segment.py` option `under_only` (a list of the parts a part may tuck under).

Two things tried and rejected while doing it: restricting each thigh's underlap to the pelvis (cracks 53 -> 113 frames, the
hip lost its cover) and to "everything but arms and shield" (113 -> 113: the shield is what hides the far leg in profile).
Excluding only the sword arm gives 77 frames and no visible stray strip beside the glove.

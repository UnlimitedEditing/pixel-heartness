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

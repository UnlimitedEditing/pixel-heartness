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

# Defect log

One row per defect class: what found it, and what covers it now. The thesis this tests is that *eyes scale with the number of primitives, not the number of assets* — if the "found by" column shows eyes mostly when a new primitive lands, it holds. Add a row the day a defect is characterised, and add the gate the same day.

| defect | mechanism that made it possible | found by | covered by |
|---|---|---|---|
| Frames touch the cell edge (32x48 too small) | cell size | script count | `border` |
| Feet sink through the floor | limb rotation about a joint | measurement | `ground` + ground lock |
| Rectangle cut tears at joints, pelvis owns thighs | rect segmentation | eye | `segment.py` flood + `holes` |
| Hole count read as regression when a tear was fixed | gate counted texels not regions | reasoning about a plateau | `holes` classifies tears vs negative space |
| Invented texels jump across background (blob under sword hand) | Euclidean underlap | **eye** (all gates green) | geodesic growth, `floaters` |
| Single global underlap radius: tears vs floaters trade off | constant standing in for a derivable quantity | sweep | per-texel derived radius |
| Stale parts file mixed with new masks (43 texels drift) | Aseprite import/build split | `agree` | stamp check in `rig.lua` |
| Seed lands on another part's colour; `leg_l` steals shield edge | hand-typed seed coords | text colour dump | `segment.py validate_seeds` (patch-based) |
| Seed on a transparent texel silently ignored | `m & opaque` in `rect_cores` | reading code | `segment.py validate_seeds` |
| `agree` vacuous when the strip on disk came from `render.py` | both writers share `strip_file` | reading code | `ase_strip_file` split; `agree` compares colour too and fails on a stale strip |
| Small part rotated ~20 degrees scrambles: eye splits, edge texels detach (wisp head, 12 texels) | nearest-neighbour rotation of a tiny part | **eye** (all gates green) | **open** -- convention only (keep small-part rotation to ~8 degrees); no gate yet |
| Lag configured but tip barely moves; and first version of the gate measured local rotation, which shrinks down a cascade | lag primitive | gate, then reasoning about the cascade | `lag` gate, measured at the tip |
| Squash drops or duplicates rows under nearest-neighbour | squash primitive | anticipated | `volume` |
| Single synthetic texel beside head in frames 2 and 7 of the wisp | rotation reveals an underlap texel attached at one corner | eye | **open** -- passes `floaters` (attached); a `synth` texel-count bar per frame would flag it |

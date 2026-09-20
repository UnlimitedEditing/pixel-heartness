# Defect log and trail

Two things live here so nothing has to be remembered: what is **open** right now, and the **log** of every defect class ever found. Update this file in the same commit as the change that finds, fixes or defers something. `grep -n "OPEN #" docs/DEFECTS.md` lists the open rows in the log.

The thesis this tests: *eyes scale with the number of primitives, not the number of assets.* If the "found by" column shows eyes mostly when a new primitive lands, it holds. Add a row the day a defect is characterised, and add the gate the same day.

## Open defects (no gate covers them, or only partly)

| # | defect | why it is open | what would close it |
|---|---|---|---|
| 1 | ~~A small part rotated more than ~8 degrees scrambles~~ **CLOSED** by the `rotation` gate and `rotscan.py`. The "~8 degrees" rule of thumb was wrong: damage is not monotonic in angle | | |
| 2 | A single synthetic texel sits beside the wisp head in frames 2 and 7 | attached at one corner, so it passes `floaters` | per-frame cap on visible synth texels, or a rule that visible synth texels must be adjacent to at least two authored ones |
| 3 | Swapping a part variant can expose body texels the part had claimed, or underlap fill | segmentation assigns a part whatever the flood reaches; a variant redraws only part of that | `variant` gate warning when the variant does not cover the part's authored footprint and the uncovered texels have no authored body beneath |
| 4 | Squash is not seen when segmentation sizes underlap | squash is a global matrix applied after the rig's pose list is read | include the squash matrix in `required_underlap`; low priority, drift is small |
| 5 | `agree` can only run where Aseprite is installed; otherwise it reports SKIPPED and everything is green | the second implementation lives in Aseprite Lua | a Python-only second renderer, or CI on a machine with Aseprite |
| 6 | Lag: looping settles over 3 passes, non-looping starts unlagged; a state entered mid-motion is not modelled | no notion of the previous state | carry lag state across state transitions once the engine side can switch states |
| 7 | A retargeted state can contain invented small motions and still tear a hole | tracker jitter on short bones becomes rotation | `holes` catches it after the fact; the deadband and `--smooth` reduce it. A retarget-time check that renders the candidate and refuses on any gate failure would close it |
| 8 | Retarget error is dominated by short bones (a fraction of a texel is several degrees) | 2D keypoints at 46 texels | fit against the mean of several nearby frames, or weight by bone length; not tried |
| 9 | The skeleton's own sword arm (18-52 deg) and shield (14-21 deg) ruin up to 80% of their small features in windup, ready and strike: ragged hand, stair-stepped shield edge | found when the `rotation` gate was calibrated; visible in the contact sheet, never recorded before | rework those poses using clean angles from `rotscan.py`, or give the parts variants; then lower `damage_max` in the rig (currently 0.85, budgeted with a `_debt` note) |

## Backlog (deliberately not done, from the handoff)

Ordered as the handoff ordered them; item numbers are its section numbers.

1. **Method files** (section 5, layer 3): per-archetype, per-motion recipes as executable markdown with worked numbers. `pixelanim/methods/` does not exist yet.
2. **The agent loop** (section 5, layer 4). Build only after the gates, which is where things stand now.
3. **First falsifiable experiment** (section 6): an agent re-authors `skeleton_warrior`'s `strike` from the rig schema and a method file; compare with the hand-written one in git.
4. **Motion reference, real-clip half** (section 9). The fitter, key reduction and foreshortening classifier are built and validated against synthetic ground truth (`pixelanim/retarget.py`). Still to do: obtain a real clip (a stock BVH or estimated keypoints; downloading needs the user's go-ahead), write the thin BVH-to-part-names mapping, retarget onto `skeleton_warrior`, and compare against the hand-written `strike`. That comparison is the falsifiable experiment; nothing so far speaks to it. Diffusion is for the *curve* only, never for texels.
5. **SAM falsification** (section 10): score SAM masks on the upscaled `skeleton_warrior` against the current label map before any ComfyUI work.
6. **Prior-art search** (sections 0 and 7): Spine, DragonBones, the Aseprite scripting community, the pixel-art tutorial corpus. Not searched.
7. **Per-archetype defaults file** a rig inherits from (section 7).
8. **Shade-role IR** (section 10): part plus outline/core/shadow/highlight/rim, compiled to texels. Only worth building at forty subjects.
9. **Left-column vs right-column classifier** (section 2): say when a requested motion needs new art. Variants are the first answer to it.
10. **Engine side, not this repo** (section 8): per-instance sprite state so idle/ready/windup/strike can be switched in the game's UE project.
11. **Hosted productisation**: raised, deliberately deferred. Keep the Aseprite dependency optional.

## Log

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
| Small part rotated ~20 degrees scrambles: eye splits, edge texels detach (wisp head, 12 texels) | nearest-neighbour rotation of a tiny part | **eye** (all gates green) | **OPEN #1** -- convention only (keep small-part rotation to ~8 degrees); no gate yet |
| Lag configured but tip barely moves; and first version of the gate measured local rotation, which shrinks down a cascade | lag primitive | gate, then reasoning about the cascade | `lag` gate, measured at the tip |
| Squash drops or duplicates rows under nearest-neighbour | squash primitive | anticipated | `volume` |
| Single synthetic texel beside head in frames 2 and 7 of the wisp | rotation reveals an underlap texel attached at one corner | eye | **OPEN #2** -- passes `floaters` (attached); a `synth` texel-count bar per frame would flag it |
| Key reduction by extrema missed a slope corner (strike middle key), 1/3 recovered | keys are corners as well as extrema | round-trip selftest | greedy piecewise-linear simplification in `retarget.py` |
| Fit invented small rotations on parts the animator held still, and one tore a hole | tracker jitter on short bones | gate (`holes`), then eye on the fitted numbers | deadband scaled by bone length; still **OPEN #7** |
| Small-part rotation scramble (wisp head, then found again on the skeleton sword arm and shield) | nearest-neighbour rotation loses small features; non-monotonic in angle | **eye** twice, then a probe that measured it | `rotation` gate (per-feature damage) + `rotscan.py`; skeleton debt is **OPEN #9** |
| Two calibration mistakes on the way: region-count change (36/54 skeleton part-frames flagged, mostly 1-px outline) and supersampled-mismatch (measured sub-texel phase, not scramble) | wrong metric | probing on known-good and known-bad rigs | per-feature tracking, outline excluded, features of 4+ texels |
| Variant swap exposed body texels the `eyes` part had grabbed during segmentation (synth 0% -> 4%) | a part's flood claimed texels its variant does not redraw | `synth` gate delta, then eye | fixed in the example by seeding the body there; **OPEN #3** for the general case |

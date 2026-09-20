# The animation set, and the gaps to it

Written 2026-09-21. The target: every character gets **walk, idle, alert, hostile, attack, take
damage**, each at **every facing**. Some characters have more than one attack, two idles, or (NPCs) a
talking animation.

## What that costs

| | frames |
|---|---|
| base set per facing (idle 4, walk 4, alert 2, hostile 4, attack 5, damage 3) | 22 |
| unique-art frames per character, 5 facings (0/45/90/135/180; the rest are mirrors) | 110 |
| same with mirrors baked into the strip, 8 facings | 176 |
| a richer character (3 attacks, 2 idles, talk = 40 per facing) | 200 unique / 320 baked |
| sprites (one Aseprite tag each) at 6 states x 5 facings | 30 |
| skeleton today | 17 frames, front only, 6 states (idle walk ready windup strike recover) |

Nobody should hand-author 110-320 frames per character. The plan this repo has arrived at: **the rig
is the animation engine; generation supplies still art per part per view**. That works for stills
(turnarounds are consistent) and does not work for pose sequences (frames generated independently
drift in identity; see `EXPERIMENT_DIFFUSION.md`, follow-up 6).

## The gaps

Ordered by what blocks what. G1-G3 are the three named while asking "can we turn around our own walk?".

### Rig side (this repo)

| # | gap | why it matters | shape of the fix |
|---|---|---|---|
| G1 | **Pivots are front-view only.** Hips at x=31 and x=23 are wrong in profile, where both legs sit on the axis; rotating about them tears the leg off. | Blocks every state at every non-front facing. | Derive per-view pivots from the segmentation: a joint is where a part's texels touch its parent's texels in that view. Per-view pivot table used by FK. |
| G2 | **Motion is authored in the picture plane, so it is only right at one facing.** The front walk's +-10 degree leg rot fakes depth motion; in profile the swing is in-plane and should be ~+-25 and flip when facing right. The same is true of an attack's arc. | Every limb motion, every state. | A view-dependent gain per limb per state (sin(yaw) for a walk swing, signed so it reverses at 270), or authored per-facing overrides where a formula fails. |
| G3 | **One-bone limbs cannot do what the new states need**: knee bend (walk contact/passing), jaw open (talk), a pain face (damage), a head turn (alert). | Walk and damage read badly without them; talk is impossible. | Part variants (built) but each variant needs art in each of the 5 views, so variants x 5 is the real cost. Two-bone legs (open defect #10) would remove the knee case. |
| G4 | **Most of the states do not exist.** alert, hostile, damage, talk, extra attacks and a second idle are unauthored; `ready/windup/strike/recover` is the only attack. | The content itself. | Data, plus method files (backlog item 1). Alert and hostile are mostly held postures with small motion, which suits the rig; damage and talk need G3 and G5. |
| G5 | **No flash/tint primitive** for taking damage (a one-frame white or red flash). | Damage. | New primitive; the `palette` gate must allow a declared flash colour (or use the palette's lightest). |
| G6 | **State schema is a flat list.** No "attack_a / attack_b", no "idle_a / idle_b", no per-facing playback, no manifest of (state x facing) -> strip range, no interruption data (commit-point frame). | Everything downstream, including the engine. | Group states by kind; emit a manifest; carry a commit frame per attack. |
| G7 | **Gates are front-view.** `holes` fails on legitimate 3/4 gaps (open #17); `distinct` fails between frames that select the same view; `agree` has no Lua mirror for yaw/views/handed. | Nothing can be trusted at other facings. | Per-view baselines; a runner over (state x facing); decide whether the Aseprite path keeps up or is dropped for turnarounds. |
| G8 | **Segmentation and mirroring rely on subject-specific shortcuts**: seed proposal uses the red-family colour rule and a biped's height fractions; handed-item detection is by colour. | The boar (four legs, no red family) and the next character. | Generalise seed proposal (per-subject seed templates), use an explicit mask for handed items. |

### Generation side

| # | gap | notes |
|---|---|---|
| G9 | Stills are consistent across views; **pose sequences are not** (drift in shield size, torso bulk, facing). Front prompts barely changed the pose. | So generation is for per-part view art and a few key variants, not for animation frames. Untried: chaining, per-frame seeds, pose references. |
| G10 | Silent failures (roughly 1 in 4 requests returned nothing, some when the queue was stalled) and a cleanup pass by eye for glints and outlines. | Retry logic; the sweep tool exists (`pixelize.py --sweep`). |

### Engine side (the game project, not this repo)

| # | gap | notes |
|---|---|---|
| G11 | No per-instance state, so a baked chunk mesh loops whatever it was placed with (HANDOFF section 8). Also no facing selection from the camera-relative angle, and no shader mirror, so the strip would need 8 facings baked (176 frames) instead of 5 unique (110). | Blocks judging any of this in game. |

## Suggested order

1. **G1 + G2 together, on the walk**, since everything else stands on them. First check: does a walk at
   profile look like scissors (expected), and does per-view pivoting fix the tearing.
2. **G3 for the legs** (knee variants from the generated side frames), then jaw for talk.
3. **G7** before adding states, so new states are gated at every facing from the start.
4. **G4/G5/G6** as content: alert, hostile, damage (with flash), the manifest.
5. **G8** when the next non-biped is attempted; **G11** whenever the engine work is scheduled.

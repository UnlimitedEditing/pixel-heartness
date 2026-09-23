<h1 align="center">Pixel Heartness</h1>

<p align="center">
  <b>An early build of a pixel art animation suite, powered by Claude.</b><br>
  One hand-drawn sprite in, a gated, game-ready animation set out.
</p>

<p align="center">
  <img src="docs/media/hero_walk_turn.gif" alt="A pixel-art skeleton warrior walking while turning through eight facings" width="256">
</p>

> **Early build.** The core pipeline (cut, pose, gate) is solid and passes every gate on three subjects. The
> eight-facing turnaround is experimental: it works, and it has known defects, listed [below](#status).

Pixel Heartness is a harness that lets a coding agent animate pixel art without ever painting a pixel.
The agent writes **poses as JSON**. Deterministic code **moves the texels the artist already drew**.
**Fifteen mechanical gates** then check the result. It was built with Claude, which drives it day to
day. Nothing in it is specific to Claude, though. Every step is a CLI command that reads and writes
JSON, PNG and plain text, and reports through exit codes. Any agent that can run a shell, edit files
and (ideally) look at an image can drive it. [AGENTS.md](AGENTS.md) is the manual for agents.

## What it makes

<p align="center">
  <img src="docs/media/states_045.gif" alt="Eight animation states at the three-quarter facing" width="520"><br>
  <sub>Eight states for one character (idle, idle_b, walk, alert, hostile, sword attack, shield bash,
  damage), shown at the 3/4 facing. The poses were authored by an agent, and every frame is made of the
  artist's own texels.</sub>
</p>

<p align="center">
  <img src="docs/media/walk_8_facings.gif" alt="The walk cycle at eight facings" width="780"><br>
  <img src="docs/media/attack_8_facings.gif" alt="The sword attack at eight facings" width="780"><br>
  <sub>The walk and the sword attack at all eight facings: 264 frames across the full set, packed into a game
  atlas with a manifest (frame ranges, timing, loop flags, the attack's commit frame).</sub>
</p>

<p align="center">
  <img src="docs/media/slime_wisp.gif" alt="A slime squashing and a wisp with a lagging tail" width="620"><br>
  <sub>Other body types need other motion primitives. The slime uses volume-preserving squash and
  stretch; the wisp's tail trails its head through a lag chain.</sub>
</p>

## How it works

<p align="center">
  <img src="docs/media/pipeline.png" alt="Source sprite, part labels, a posed frame, and the invented texels highlighted" width="820">
</p>

1. **Cut.** `segment.py` splits the sprite into parts with a colour-weighted flood from a few seed
   texels per part, so the cuts follow the edges the artist drew. The agent supplies coordinates it
   has read off a numbered grid. It never guesses them.
2. **Underlap.** A part that rotates away from its neighbour exposes texels nobody drew. Each part is
   therefore extended *underneath* the parts in front of it. At rest this growth is hidden by z-order,
   and it shows exactly where a gap would otherwise open. How far each part extends is worked out from
   the rig's own poses; it is not a tuned constant. Limbs hidden behind a shield are rebuilt from their
   mirror-image twin. In panel 4 above, the cyan texels are the ones the pipeline invented, and they are
   copies of authored texels, so the palette never grows.
3. **Pose.** A state is a list of frames. Each frame gives `{rot, dx, dy, sx, sy}` per part over an FK
   hierarchy, plus optional squash, chain lag, part variants, a colour flash and a facing (`yaw`).
4. **Gate.** `checks.py` runs the gates and exits with the number that failed. The rest pose must be
   bit-identical to the source. No frame may introduce a colour or tear a hole in the body. Feet stay
   on the floor row, and consecutive keys must read as different silhouettes. Other gates catch
   floating strays, sub-texel drift and small features destroyed by rotation. The full list is in
   [docs/REFERENCE.md](docs/REFERENCE.md#gates--checkspy).
5. **Look.** `sheet.py` renders numbered grids, contact sheets and GIFs. It also prints **text maps**
   of part labels and palette indices, because a render shows *where* a texel is but not *which colour
   family* it belongs to.

The main idea: **a generative model may supply a motion curve or reference art, but it never places
a texel in a frame.** That is why palette closure, whole-texel motion and a pixel-exact rest pose are
guaranteed by construction rather than hoped for.

## Quick start

Needs Python 3 with numpy, Pillow and SciPy (developed on 3.14).

```bash
pip install -r requirements.txt

RIG=examples/skeleton_warrior/rig_2bone.json
python pixelanim/segment.py $RIG                  # cut into parts
python pixelanim/render.py  $RIG                  # pose + composite -> strip + tag table
python pixelanim/checks.py  $RIG                  # the gates; exit status = failures
python pixelanim/sheet.py contact $RIG --mark-synth
python pixelanim/sheet.py gif     $RIG --state walk
```

Output goes to `out/` next to the rig: `<name>_strip.png` plus an Aseprite-style `<name>_strip.json`
(frame rects, durations, tags), which any sprite packer can read.

The eight-facing set shown above:

```bash
RIG=examples/skeleton_warrior/rig_fullset.json
python pixelanim/segment.py $RIG && python pixelanim/render.py $RIG && python pixelanim/checks.py $RIG
python examples/skeleton_warrior/make_game_atlas.py   # atlas + JSON manifest + a C++ include
python examples/make_media.py                         # regenerate every GIF in this README
```

To animate your own sprite, follow [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md).

## Driving it with an agent

Hand your agent this repository and [AGENTS.md](AGENTS.md). (Claude Code picks it up automatically
through [CLAUDE.md](CLAUDE.md).) The loop is:

```
read the sprite -> render the grid -> place seeds -> segment -> check the text map
-> write states -> render -> run gates -> read the contact sheet -> revise
```

The agent needs a shell, file editing, and Python with numpy, Pillow and SciPy. Image input makes it
better, but it isn't strictly required: every structural defect found so far was caught by a gate or
a text dump, not by eye. What vision adds is **taste**. The gates can rank four candidate idles, but
only a look can tell you which one reads as breathing and not a gesture.

## Status

| | |
|---|---|
| **Solid** | Segmentation with seed validation, derived underlap, mirror rebuild, FK render, ground lock, squash/stretch, chain lag, part variants, colour flash, 15 gates, text/grid/contact/GIF views, retargeting a 2D keypoint clip into a state. The front-facing rigs pass 15/15. |
| **Experimental** | Eight facings (`yaw`). Side and back art for each part comes from generated turnaround views, corrected onto the sprite's grid and palette (`pixelize.py`). The full skeleton set is 264 frames and passes 14/15 gates. |
| **Known defects** | At some facings, thin one-texel cracks open at the shoulder seam when an arm swings (the `holes` gate fails on those frames). The rear views read as a dark mass. There is no jaw or face variant yet, so no talk state. The eight-facing code has no Aseprite (Lua) mirror, so `agree` is skipped there. See [docs/DEFECTS.md](docs/DEFECTS.md). |
| **Not yet** | Seed proposal that generalises past bipeds, transitions and interruption rules between states, and a license (see below). |

## Layout

| path | what |
|---|---|
| `pixelanim/segment.py` | cut a sprite into parts, derive underlap, rebuild hidden limbs |
| `pixelanim/render.py`, `riglib.py` | FK, primitives, ground lock, compositing, strip + tag table |
| `pixelanim/checks.py` | the gates |
| `pixelanim/sheet.py` | grid, parts, contact sheet, GIF, text maps |
| `pixelanim/rig.lua` | the same maths inside Aseprite, for hand touch-ups (optional) |
| `pixelanim/retarget.py`, `bvh.py` | fit a keypoint or mocap clip to a rig state |
| `pixelanim/rotscan.py` | list the rotation angles a small part survives cleanly |
| `pixelanim/pixelize.py`, `facing.py`, `mirrorpatch.py`, `walkcheck.py` | turning generated view art into on-grid, on-palette sprites |
| `examples/skeleton_warrior/` | the biped: front rig, two-bone legs, eight-facing views and the full set |
| `examples/slime/`, `examples/wisp/` | squash/stretch and chain lag (`make_examples.py` regenerates them) |
| `examples/make_media.py` | renders every picture in this README |

## Documentation

| doc | read it for |
|---|---|
| [AGENTS.md](AGENTS.md) | the operating manual for an agent: rules, loop, commands, how to read gate output |
| [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) | animating your own sprite, step by step |
| [docs/REFERENCE.md](docs/REFERENCE.md) | how the cut, underlap, gates, primitives and ground lock work; the rig file |
| [docs/ANIMATION_SET.md](docs/ANIMATION_SET.md) | the target animation set per character, the gaps to it, and status |
| [docs/DEFECTS.md](docs/DEFECTS.md) | open defects, the backlog, and how each defect class was found |
| [docs/SPIKE_YAW.md](docs/SPIKE_YAW.md) | the eight-facing work: what was tried, with numbers |
| [docs/EXPERIMENT_CMU.md](docs/EXPERIMENT_CMU.md), [docs/EXPERIMENT_DIFFUSION.md](docs/EXPERIMENT_DIFFUSION.md) | real mocap retargeting; diffusion turnarounds plus deterministic pixel correction |
| [docs/HANDOFF.md](docs/HANDOFF.md) | the original argument and engineering history |

## Origin

Pixel Heartness started inside a UE5 dungeon-crawler project, where its strips feed a sprite packer
and a billboard material. That engine wiring stays in the game; this repo is engine-agnostic. The
Python package is still called `pixelanim`, its original working name.

## License

None chosen yet. Until one is, all rights are reserved by the author.

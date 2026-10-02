---
name: pixelanim
description: On-call pixel art studio for generating, editing, rigging, and animating pixel-perfect game sprites. Bridges Graydient CLI (krea2 for base pixel accuracy, edit-qwen / edit-qwen21 for native RGBA transparency) with pixelanim's deterministic quantization, ambient rigging (squash/stretch, chain lag), orthogonal slot stamping (Spine/Saint11 standard), and 15 mathematical zero-defect quality gates.
---

# PixelAnim Studio & Graydient Pixel Engine

Use this skill whenever asked to:
- Generate new pixel art characters, tiles, props, or monsters from scratch.
- Clean and isolate transparency on existing concept art or tile sheets (`krea2` -> `edit-qwen` -> `pixelanim`).
- Create 8-facing turnaround sheets from a front-facing sprite.
- Rig and animate 2D pixel sprites (idles, breathing, squash/stretch jumps, floating wisps, walks).
- Animate expressive facial features, lip-sync speech, and blinks using the Saint11 6-viseme standard and orthogonal slot stamping.
- Author high-resolution battle busts (e.g. Pokémon DS / Fire Emblem GBA style) with protected hair bangs and precise facial anatomy.
- Perform pixel-perfect edits, part variations (blinks, weapon swaps, open jaws), or action keyframes.
- Ensure strict palette closure, integer texel alignment, and zero-defect quality gates (15/15 gates).

---

## 1. The Core Contract

1. **The 3-Stage Generative Pipeline (`krea2` -> `edit-qwen` -> `pixelanim`):**
   - **Stage 1 (Base Art with `krea2`):** Always use `krea2` for base pixel art generation. Diffusion models like `qwen21` have loose, blurry pixel boundaries. `krea2` possesses vastly superior priors for authentic retro pixel-art silhouettes, consistent texel grids, and sharp contours.
   - **Stage 2 (Transparency Cleanup with `edit-qwen`):** Base `krea2` outputs sit on solid backgrounds. We pass the candidate image into `edit-qwen` (or `edit-qwen21`) with the native RGBA transparency prompt contract to produce true alpha channels without fuzzy edge eating.
   - **Stage 3 (Deterministic Local Correction with `pixelanim`):** `pixelanim` (`pixelize.py`) performs all quantization, texel grid snapping, palette closure, and outline preservation deterministically on the local machine. No diffusion noise or off-palette texels ever reach production.
2. **Transparency: short prompt, `edit-qwen21-turbo` (verified 2026-10-01):**
   - Never describe the subject or talk about "RGBA / alpha channel / transparent background" in the edit prompt. Long prompts make qwen draw a literal checkerboard "transparency grid" into the pixels (it happened on every sprite).
   - Use exactly this, with the base render (solid white background) as `--init-image`:
     > `remove white background from subject and replace with alpha transparent layer. correct non square subtexel pixels /run:edit-qwen21-turbo`
   - It returns a real RGBA image and also straightens non-square texels. Leave `/steps` unset for the turbo workflow.
   - Never use post-hoc colour thresholding, rembg, or SAM. `Tools/cleanbg.py` in BumFightManager is only a fallback for old checkerboard renders.
   - `pixelize.py` detects the native alpha (`alpha < 128`), preserving 1-pixel outlines.
3. **The Orthogonal Slot Invariant (Spine / Saint11 Standard):**
   - **Never apply 2D continuous affine rotation to sub-16px facial features** (eyes, mouth, nose, jaw).
   - Inverse nearest-neighbor sampling on low-resolution facial clusters destroys cluster morphology, causes phase cancellation, and ruins the T-zone.
   - Use `"mode": "orthogonal_stamp"` on facial slots, hands, or held items. The attachment anchor follows parent bone kinematics in whole integer texels, but stamps its bitmap with zero rotation ($m = [[1, 0, tx-px], [0, 1, ty-py], [0, 0, 1]]$).
4. **Hard Rules for Agents:**
   - **Never type a coordinate you haven't seen.** Render `sheet.py grid <rig>` before picking seeds or pivots.
   - **Translations are whole texels.** No sub-texel floating drift ($dx, dy \in \mathbb{Z}$).
   - **Parts are listed backmost first.** In `rig.parts`, list order is z-render order. (Kinematic hierarchy follows `parent` pointers).
   - **Run the gates after every change.** `checks.py <rig>` exits with the number of failed gates. Anything above 0 means you are not done.

---

## 2. Directory & Tool Locations

- **Harness Root:** `D:\pixelanim`
- **Core Package:** `D:\pixelanim\pixelanim`
- **Studio Bridge:** `D:\pixelanim\pixelanim\studio.py`
- **Verification Gates:** `D:\pixelanim\pixelanim\checks.py`
- **Visualizer / Sheets:** `D:\pixelanim\pixelanim\sheet.py`
- **Quantization Refiner:** `D:\pixelanim\pixelanim\pixelize.py`
- **Kinematic Engine (Python):** `D:\pixelanim\pixelanim\riglib.py`
- **Kinematic Engine (Lua / Aseprite):** `D:\pixelanim\pixelanim\rig.lua`
- **Method Runbooks:** `D:\pixelanim\pixelanim\methods/`
  - Speech Visemes: `D:\pixelanim\pixelanim\methods\speech_viseme_6f.md`
- **Reference Examples:**
  - Hobo Brawler (48x48): `D:\pixelanim\examples\hobo/`
  - Pokémon Trainer Battle Bust (64x92): `D:\pixelanim\examples\trainer/`
- **Graydient CLI:** `graydient` (available globally in PATH)

---

## 3. Workflow Runbooks

### Workflow A: Generate New Character Sprite or Tile (`krea2` -> `edit-qwen` -> `pixelanim`)

Use this workflow to create a brand-new, on-grid pixel sprite or tile with crisp native alpha.

#### Step 1: Run Full 3-Stage Generation
```bash
python D:\pixelanim\pixelanim\studio.py generate \
  "a scruffy alley brawler in ragged leather jacket with taped fists" \
  --out ./out/brawler/front.png \
  --height 48 \
  --colours 16 \
  --base-workflow krea2 \
  --edit-workflow edit-qwen21-turbo \
  --preserve 0.5
```
This automatically executes:
1. `krea2` diffusion generating pixel-accurate base concept art.
2. `edit-qwen` image-to-image isolating the subject with a true native RGBA transparent alpha channel.
3. `pixelize.py` locally quantizing onto an exact 48-texel integer grid with a 16-color closed palette.

#### Step 2: Inspect Palette & Texture Map
Verify the palette indices and texel structure:
```bash
python D:\pixelanim\pixelanim\sheet.py map ./out/brawler/front.png --what colours
```

---

### Workflow A.2: Isolate Transparency on Existing Art / Tiles (`isolate`)

If you already have a concept art sheet, tile, or prop generated via `krea2` or another tool:
```bash
python D:\pixelanim\pixelanim\studio.py isolate \
  ./path/to/krea2_asset.png \
  --subject "cracked concrete sidewalk tiles" \
  --out ./out/tiles/sidewalk.png \
  --height 32 \
  --colours 16 \
  --edit-workflow edit-qwen
```

---

### Workflow B: Generate 8-Facing Turnaround Set (`edit-qwen`)

Use this when you have a front-facing sprite and need profile, 3/4, and rear views for game engines.

#### Step 1: Synthesize Turnaround Ring
```bash
python D:\pixelanim\pixelanim\studio.py turnaround \
  ./out/brawler/front.png \
  --out-dir ./out/brawler/views/ \
  --subject "brawler in ragged jacket" \
  --height 48 \
  --workflow edit-qwen \
  --steps 35
```
This automatically:
1. Upscales the front sprite 10x with nearest-neighbor interpolation.
2. Prompts `edit-qwen` for $45^\circ$ (q34), $90^\circ$ (qside), $135^\circ$ (qrear34), and $180^\circ$ (qrear) with native RGBA transparency.
3. Quantizes each raw view with `pixelize.py` against the front sprite's scale and exact palette.
4. Generates bilateral opposite views ($225^\circ, 270^\circ, 315^\circ$) via `mirrorpatch.py`, protecting handed items (weapons, bags, wraps).

---

### Workflow C: Rigging & Ambient Animation (Pure `pixelanim`)

Use this for continuous ambient loops: breathing idles, slime bounces, wisp sways, and character gestures.

#### Step 1: Scaffold Initial Rig
```bash
python D:\pixelanim\pixelanim\studio.py scaffold \
  <biped|slime|wisp> \
  <rig_name> \
  path/to/sprite.png \
  --out path/to/rig.json \
  --cell 48 48
```

#### Step 2: Render Coordinate Grid
```bash
python D:\pixelanim\pixelanim\sheet.py grid path/to/rig.json --zoom 15
```
Inspect `./out/<rig_name>_grid.png` to find exact $(x, y)$ texel coordinates for part seeds and pivots.

#### Step 3: Segment Parts & Validate Seeds
```bash
python D:\pixelanim\pixelanim\segment.py path/to/rig.json
python D:\pixelanim\pixelanim\sheet.py map path/to/rig.json
```
Read the text map to confirm parts follow natural anatomical seams.

#### Step 4: Author States & Motion Primitives
Edit `states` in `rig.json`:
- **FK Rotation & Translation:** `{"pose": {"torso": {"rot": -4, "dy": 1}}}`
- **Squash & Stretch (Slimes/Landings):** `{"squash": 0.15}` (positive flattens, negative stretches; area preserved).
- **Chain Lag (Tails, Capes, Hair):** Add `"lag": 0.75` on child parts; they will trail parent rotation.
- **Part Variants (Blinks, Hurt):** Swap variants: `{"pose": {"eyes": {"variant": "blink"}}}`.
- **Ground Lock:** Keep `ground_lock: true` so the lowest texel stays pinned to the floor row.

#### Step 5: Render and Verify Gates
```bash
python D:\pixelanim\pixelanim\render.py path/to/rig.json
python D:\pixelanim\pixelanim\checks.py path/to/rig.json
```
If `checks.py` returns code 0 (`PASS` on all 15 gates), proceed to render preview GIF or sprite sheets.

---

### Workflow D: Orthogonal Slot Stamping & Speech Lip-Sync (Saint11 Standard)

Use this method whenever animating speech, lip-sync, or facial expressions on pixel sprites. Reference: `pixelanim/methods/speech_viseme_6f.md`.

#### Step 1: Declare Slots with `"mode": "orthogonal_stamp"`
In `rig.json`:
```json
{
  "name": "mouth",
  "parent": "head",
  "pivot": [30, 49],
  "mode": "orthogonal_stamp",
  "variants": {
    "open": "trainer_mouth_open.png",
    "round": "trainer_mouth_round.png",
    "wide": "trainer_mouth_wide.png"
  }
},
{
  "name": "eyes",
  "parent": "head",
  "pivot": [30, 40],
  "mode": "orthogonal_stamp",
  "variants": {
    "blink": "trainer_eyes_blink.png",
    "squint": "trainer_eyes_squint.png"
  }
}
```

#### Step 2: The 5 Canonical Viseme Shapes (Pedro Medeiros / Saint11)
| Viseme Key | Phonemes Covered | Visual Geometry | Co-Articulation Rule |
|---|---|---|---|
| **`rest`** (default) | M, B, P, silence | 1-pixel horizontal dark line with lower lip/chin shadow | Chin at resting row |
| **`open`** | A, I, H, soft vowels | Vertical opening, dark core cavity, light teeth/tongue line | Chin drops 1 texel ($dy: +1$) |
| **`round`** | O, U, W, Q | Compact circular cavity, dark border, tongue center | Chin drops 1 texel ($dy: +1$) |
| **`wide`** | E, Y, S, Z, stressed yells | Wide aperture, visible upper teeth line and tongue | Chin drops 1 texel, eyes squint |
| **`fricative`** | F, V, TH | Flat upper lip line, 1 light pixel indicating upper teeth | Chin neutral |

#### Step 3: Whole-Face Co-Articulation & Cadence (12 FPS)
- **Anticipation (1-2 frames before onset):** Torso slight bob ($dy: -1$), mouth remains at `rest`.
- **Vowel Hits (Hold 1-2 frames max):** Match primary vowel stress with `wide`, `open`, or `round`.
- **Consonants & Stops:** Return to `rest` or neutral shape.
- **Blinks on Pauses:** Insert `{"eyes": {"variant": "blink"}}` on natural pauses or bilabial consonant stops ('M', 'P').

---

### Workflow E: High-Resolution Battle Busts & Facial Slicing

For high-resolution characters ($64 \times 64$ to $96 \times 96$ battle busts, e.g. Pokémon DS or Fire Emblem GBA style):

1. **Protect Hair Bangs (Eye Sockets Masking):**
   - Never use broad bounding boxes for eyes that include hair bangs or bridge skin.
   - Broad eye boxes fill underlying skin in `underlap`, carving ugly skin notches into overlapping hair bangs.
   - Always slice eye sockets into **tight per-eye masks** (e.g. Left: $x=22..27$, Right: $x=33..38$), leaving hair bangs permanently in `head`.
2. **Anatomical Proportions:**
   - In anime/chibi sprites, place mouth **1 texel below the nose dot and 2 texels above the chin line**. Placing mouth on lower chin ($y+3$) places it unnaturally on the neck/collar.
3. **Z-Order vs. Kinematic Hierarchy:**
   - In `rig.json`, rendering order follows `rig.parts` list order, while kinematic hierarchy follows `parent` pointers.
   - List `head` *before* `torso` in `rig.parts` so neck underlap renders behind the front jacket collar, even while `head` has `"parent": "torso"` to follow breathing motion.

---

### Workflow F: Complex Action Keyframes (`edit-qwen` + Cleanup)

For extreme actions (e.g. leap strikes, spell casting, death collapses) where 2D cutout rotation alone cannot foreshorten limbs:

1. **Synthesize Action Pose:**
   Prompt `edit-qwen` with 10x front sprite as `--init-image`:
   ```bash
   graydient render "Redraw the character raising weapon high with two hands. Keep the same pixel art style, exact colours and proportions. Replace the white background with an alpha transparent layer. /run:edit-qwen21-turbo /seed:4012" --init-image ./raw/front_x10.png --out ./raw/action_raw.png
   ```
2. **Clean onto Source Grid:**
   ```bash
   python D:\pixelanim\pixelanim\pixelize.py ./raw/action_raw.png ./out/character/front.png --out ./out/character/action.png --preserve 0.5
   ```
3. **Integrate into Rig as Part Variant:**
   Cut specific limbs/weapons from the cleaned frame and register them under `variants` in `rig.json`.

---

## 4. Export & Compilation Pipeline (Zero Dither Buzz / Artifacts)

### Two-Pass FFmpeg Palettegen (GIF Standard)
Never use PIL default `Image.save(format='GIF')` for final production exports. PIL uses lossy Octree color reduction that creates temporal dither buzzing and transparent smearing trails across frames.

Always compile animated GIFs using FFmpeg's two-pass exact palette generator:
```bash
ffmpeg -y -framerate 12 -i up_%03d.png \
  -filter_complex "[0:v]split[a][b];[a]palettegen=max_colors=16:reserve_transparent=on[p];[b][p]paletteuse=dither=none" \
  out.gif
```

### Audio-Synchronized MP4 Video
```bash
ffmpeg -y -framerate 12 -i up_%03d.png -i voice.mp3 \
  -c:v libx264 -pix_fmt yuv420p -tune stillimage -c:a aac -b:a 192k -shortest \
  out.mp4
```

---

## 5. Reading Gate Failures (`checks.py`)

| Gate | Why It Failed | How to Fix |
|---|---|---|
| `holes` | A part rotated off its neighbor, exposing empty background. | Reduce rotation angle, move pivot closer to joint seam, or increase `underlap` in `rig.json`. |
| `floaters` | Invented texels showing with no authored pixels nearby. | Restrict `underlap` or specify `"under_only"` on the offending part. |
| `rotation` | Small features (eyes, teeth, knuckles) scrambled by nearest-neighbor rotation. | Use `"mode": "orthogonal_stamp"` for facial features, or run `rotscan.py` to identify clean angles. |
| `distinct` | Two consecutive keyframes have nearly identical silhouettes. | Push the pose further (larger $dx/dy/rot$) or delete the redundant frame. |
| `border` | An arm or weapon swing crossed outside the cell boundary. | Reduce rotation/translation, or expand `"cell": [W, H]` in `rig.json`. |
| `ground` | Lowest texel lifted off the floor row. | Ensure `ground_lock: true`, or add the state to `airborne_states` if it is a genuine jump. |
| `wholetexel` | Float translation provided. | Ensure all $dx$ and $dy$ values in poses are integers ($dx, dy \in \mathbb{Z}$). |
| `rest` / `palette` | Off-palette color or rest pose drift. | Never edit pixels to pass these gates; fix the source sprite or segmentation seeds. |

---

## 6. Output Deliverables

When complete, every asset outputs:
1. `<name>_strip.png`: Full sprite strip with all animated states laid out horizontally.
2. `<name>_strip.json`: Aseprite-compatible frame tags, frame rects, and durations (ready for Unreal Engine Paper2D or custom sprite materials).
3. `<name>_anim.gif`: Ultra-clean two-pass palettegen animated preview.
4. `<name>_lipsync.mp4`: (For speaking characters) Audio-synchronized dialogue render.

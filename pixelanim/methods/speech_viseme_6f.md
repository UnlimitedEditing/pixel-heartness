# Method: 6-Viseme Orthogonal Speech Animation (Saint11 / Spine Standard)

*Executable recipe for animating facial speech and lip-sync on low-resolution pixel art sprites (sub-64px).*

---

## 1. Core Principle & The Orthogonal Invariant

> **Rule**: Never rotate facial features (eyes, mouth, nose, jaw) using 2D continuous affine transforms.
> Inverse nearest-neighbor sampling on features <16 texels destroys cluster morphology and breaks the T-Zone.

In `pixelanim`, facial features must be declared as **orthogonal slot attachments**:
```json
{
  "name": "jaw",
  "parent": "head",
  "pivot": [24, 17],
  "mode": "orthogonal_stamp",
  "variants": {
    "open": "hobo_jaw_open.png",
    "wide": "hobo_jaw_wide.png",
    "round": "hobo_jaw_round.png"
  }
}
```

### The Mechanism
1. The parent bone (`head` / `torso`) provides translation $(dx, dy)$ and macro-tilt.
2. The attachment anchor $(px, py)$ transforms with the parent matrix and rounds to the nearest **integer whole texel**:
   $$tx = \text{round}(wx) + \text{round}(dx)$$
   $$ty = \text{round}(wy) + \text{round}(dy)$$
3. The attachment bitmap is stamped **orthogonally** (zero rotation, zero shear) onto $(tx, ty)$.
4. Every single authored pixel lands 1:1 on the pixel grid.

---

## 2. The 5 Canonical Viseme Shapes (Pedro Medeiros / Saint11)

For low-resolution faces ($8 \times 8$ to $16 \times 16$ texel head size), do not attempt muscular kinematics. Use this 5-state discrete viseme library:

| Viseme Key | Phonemes Covered | Visual Geometry | Co-Articulation Rule |
|---|---|---|---|
| **`rest`** (default) | M, B, P, silence | 1-pixel horizontal dark line with lower lip/chin shadow | Chin at resting row |
| **`open`** | A, I, H, soft vowels | $3 \times 2$ vertical opening, dark core, 1-pixel teeth/tongue highlight | Chin drops 1 texel ($dy: +1$) |
| **`round`** | O, U, W, Q | $2 \times 2$ compact circular cavity, dark border, tongue center | Chin drops 1 texel ($dy: +1$) |
| **`wide`** | E, Y, S, Z, stressed yells | $4 \times 2$ wide opening, visible upper teeth line and tongue | Chin drops 1 texel, eyes squint |
| **`fricative`** | F, V, TH | Flat upper lip line, 1 light pixel indicating upper teeth contacting lower lip | Chin neutral |

---

## 3. Whole-Face Co-Articulation Rules

A mouth never moves in isolation. When authoring frames:
1. **The T-Zone Anchor**: Pupils and nose bridge must maintain a constant relative offset.
2. **Chin & Beard Drop**: When switching to `open`, `round`, or `wide`, the jaw/beard artwork drops by 1 integer texel to provide anatomical clearance for the opening cavity.
3. **Eyebrows & Eye Accents**:
   - On stressed syllables, trigger `"eyes": {"variant": "squint"}` or `"eyes": {"variant": "wide"}`.
   - Insert an `"eyes": {"variant": "blink"}` frame during natural pauses or consonant stops (e.g. on bilabial 'P' or 'M').

---

## 4. Audio-to-Frame Cadence Mapping

Given an audio sample at $12\text{ FPS}$ (1 frame $\approx 83.3\text{ms}$):
1. **Anticipation (1–2 frames before vocal onset)**: Torso slightly bobs ($dy: -1$), mouth remains at `rest`.
2. **Vowel Hits (Hold 1–2 frames max)**: Match primary vowel stress with `wide`, `open`, or `round`.
3. **Consonants & Stops**: Brief 1-frame return to `rest` or neutral shape.
4. **Settle (2–3 frames post-speech)**: Return to idle stance with natural follow-through.

---

## 5. Mathematical Gate Compliance
*   `checks.py rest`: Bit-identical because rest pose uses default un-offset variant.
*   `checks.py wholetexel`: Integer rounding ensures zero fractional coordinates.
*   `checks.py rotation`: Orthogonal stamping guarantees $0\%$ ruined small features on facial slots.
*   `checks.py palette`: Uses only pre-quantized colors from the character source palette.

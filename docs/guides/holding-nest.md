# A holding nest for your part

A holding nest is a tray that holds a part while you sand it, glue it, or mark it. You give it a part as a STEP model. It builds a
**floor** under the part, and a **wall** round the part's shadow, with **finger notches** cut through the wall so the part lifts out by hand.

```bash
zcad-validation nest template --part bracket.step --output my-nest.json
# say what the part is, then:
zcad-validation nest check my-nest.json
zcad-validation nest build --nest-file my-nest.json --output-directory exports/my-nest
```

`nest template --part` writes a nest file that names your STEP model and its SHA-256. `nest check` reads the part and exits 1 if the nest
cannot be built, listing every problem at once. `nest build` exports the nest as STEP and STL, checks it against the printer profile, and writes
`nest.json`, a record of what was built from what, which says the nest is **unverified**.

A drill guide with no bores also holds a part, from above; this is a tray with a floor, for working on the part while it stands in it.

## The nest file

| Field | What it is |
| --- | --- |
| `part.step`, `part.sha256` | The STEP file and its hash. A part that has changed since is refused. |
| `part.solid_index` | Which solid is the part (from 1), if the model holds several. |
| `nest.depth_mm` | How far up the part's side the wall climbs. Left out, half the part's height, at least 3 mm. It cannot be more than the part's height. |
| `nest.wall_mm` | The wall round the pocket (2.0). It cannot be under the printer's minimum wall. |
| `nest.floor_mm` | The floor under the part (2.0). It cannot be under the printer's minimum floor. |
| `nest.flange_mm` | How far the floor reaches past the wall (8.0), all round. Zero leaves no flange. |
| `features.finger_notches` | 0 to 4 notches (2). |

The part's frame is its own: centred on its bounding box in X and Y, with +X right and +Y up the page seen from above, and its **top face at z = 0**. The
model must have **+Z up**. Everything is in millimetres.

## How the nest fits

The pocket follows the part's **shadow**, its outline seen from above (undercuts and overhangs included), widened by the printer's sliding clearance
(0.2 mm on the A1 mini profile, which is provisional). A pocket cut to the shadow lets the part lift straight out whatever its shape beneath: a part
with a wide head on a narrow stem still releases. The price is a looser fit where the part narrows below its widest point. The shadow is found by drawing
the part's triangles onto a grid, so it is never smaller than the part and can be a pixel or so larger. A part whose shadow is several separate pieces is refused.

## Finger notches

A notch is 12 mm wide, cut through the wall from the floor's top up, at the middle of a straight stretch of the shadow's outline. It needs a stretch at least
18 mm long (12 mm and 3 mm of margin past each end), and the nest takes the longest stretches first. A part whose outline has fewer long stretches than the notches
asked for is refused, with the number it has: a round part, whose outline is many short segments, takes none. The width and the margin are the engine's own
choices.

## What is checked

The nest is **one solid**. The part is put in its pocket and shares no volume with it, and is lifted straight up through the wall's height in 2 mm steps and
meets nothing on the way. Every notch is open at its middle, at the wall's top and just above the floor. The nest must fit the printer's bed.

**The engine says nothing about how well the nest holds a part.** It says the part fits the pocket and lifts straight out. A nest is unverified until a printed
trial has passed.

# A nest for your part

A drill guide holds a drill where you want a hole. This release builds its
lower half: a **nest**, a pocket that fits a part you give it as a STEP model,
with a **plate** on top that rests on the part. On its own that is a holding
nest for sanding, gluing, or marking. The bores that make it a drill guide
come in the next release.

```bash
zcad-validation guide template --part bracket.step --output my-guide.json
# edit the nest depth, then:
zcad-validation guide check my-guide.json
zcad-validation guide build --guide-file my-guide.json --output-directory exports/my-guide
```

`guide template --part` writes a guide file that names your STEP model and its
SHA-256. `guide check` reads the part, refuses what cannot be nested, and
exits 1 if the guide cannot be built. `guide build` exports the guide as STEP
and STL, checks it against the printer profile, and writes `guide.json`, a
record of what was built from what.

## The guide file

| Field | What it is |
| --- | --- |
| `part.step` | The part's STEP file, relative to the guide file or absolute. |
| `part.sha256` | The STEP file's hash. A part that has changed since is refused. |
| `part.solid_index` | Which solid is the part (from 1), if the model holds several. Left out, the nest is built around all of them together, and the check says so. |
| `nest.depth_mm` | How far down the part the pocket goes. It cannot be deeper than the part. |
| `nest.wall_mm` | The wall round the pocket (2.0 by default). It cannot be under the printer's minimum wall. |
| `nest.bearing` | `top`: the plate rests on the part's top face. The only choice for now. |
| `plate.thickness_mm` | The plate over the part (6.0 by default). |

The part's frame is its own. It is centred on its bounding box in X and Y, with
+X right and +Y up the page seen from above, and its **top face at z = 0**. The
model must have **+Z up**: that is the direction the guide lifts off. Everything
is in millimetres.

## How the nest fits

The nest follows the part's **shadow**: its outline seen from above, undercuts
and overhangs included, widened by the printer's sliding clearance (0.2 mm on the
A1 mini profile, which is provisional). A pocket cut to the shadow lets the part
lift straight out whatever its shape underneath, so a part with a wide head on
a narrow stem still releases. The price is a looser fit where the part narrows
below its widest point.

The shadow is found by drawing the part's triangles onto a grid and tracing the
outline, so it is never smaller than the part and can be a pixel or so larger
(at most 0.05 mm on a small part, a little more on a large one). A hole in the
shadow is filled, since a pocket has no island, and a part whose shadow is
several separate pieces is refused: name the one solid that is the part.

On a model of a whole board, `guide check` takes several seconds, because it
reads thousands of parts. It skips any part that lies inside the shadow already
drawn.

## What the check refuses

- A part that has changed since the file was written, or a STEP file that is
  missing, or a `solid_index` the model does not have.
- A nest deeper than the part.
- A part with **no flat top**: at least 10% of its shadow must be flat material
  at the top, for the plate to bear on. A ledge for a part with no flat top
  comes in a later release.
- A shadow that is more than one piece.

and warns of a nest under 3 mm deep (it barely locates the part) and of a model
with several solids and no `solid_index`.

`guide build` also refuses a wall or plate under the printer's minimum, a guide
too big for the bed, and one that fails its own checks: the part must fit the
pocket, and lift out in 2 mm steps without touching it.

## The build record

`guide.json` names the guide file and the part by hash, the nest and plate
numbers, the printer profile and its tolerances (all provisional), and the
exported files with their STL hashes. It says `verified: false` and states **no
accuracy**. A printed guide's fit is something a trial measures, and trials
come in a later release; until then, check the print against your part before
you trust it.

The guide prints plate down, so its flat face is on the bed and the nest opens
upward.

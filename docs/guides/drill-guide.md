# A drill guide for your part

A drill guide holds a drill where you want a hole. You give it a part as a STEP
model and say where the holes go. It builds a **nest**, a pocket that fits the
part, and a **plate** on top that rests on the part and carries a **bore** for
each hole: a printed hole, or a pocket for a steel drill bushing. With no bores
it is a holding nest for sanding, gluing, or marking.

```bash
zcad-validation guide template --part bracket.step --output my-guide.json
# edit the drill, the bores, and the nest depth, then:
zcad-validation guide check my-guide.json
zcad-validation guide build --guide-file my-guide.json --output-directory exports/my-guide
```

`guide template --part` writes a guide file that names your STEP model and its
SHA-256, with a drill and one example bore. `guide check` reads the part,
places every bore, and exits 1 if the guide cannot be built, listing every
problem at once. `guide build` exports the guide as STEP and STL, checks it
against the printer profile, and writes `guide.json`, a record of what was built
from what. Both take `--printer-profile`, which the bores are checked against.

## The guide file

| Field | What it is |
| --- | --- |
| `part.step` | The part's STEP file, relative to the guide file or absolute. |
| `part.sha256` | The STEP file's hash. A part that has changed since is refused. |
| `part.solid_index` | Which solid is the part (from 1), if the model holds several. Left out, the nest is built around all of them together, and the check says so. |
| `nest.depth_mm` | How far down the part the pocket goes. It cannot be deeper than the part. |
| `nest.wall_mm` | The wall round the pocket (2.0 by default). It cannot be under the printer's minimum wall. |
| `nest.bearing` | `top`: the plate rests on the part's top face. The only choice for now. |
| `plate.thickness_mm` | The plate over the part. Leave it out and the plate is sized to the bores (6.0 with none). Give one and it must be enough for them. |
| `drill` | The tool, from you: `diameter_mm`, `chuck_diameter_mm`, `depth_mm`, and optionally `stickout_mm`. |
| `bushing` | A steel bushing, if any bore uses one; see below. |
| `bores` | The holes: each has an `identifier`, `x_mm` and `y_mm`, and optionally `kind`, `diameter_mm`, `depth_mm`, a tilt, and `allow_exit`. |

The part's frame is its own. It is centred on its bounding box in X and Y, with
+X right and +Y up the page seen from above, and its **top face at z = 0**. The
model must have **+Z up**: that is the direction the guide lifts off. A bore's
`x_mm` and `y_mm` are where its axis crosses that top plane. Everything is in
millimetres.

## How the nest fits

The nest follows the part's **shadow**: its outline seen from above, undercuts
and overhangs included, widened by the printer's sliding clearance (0.2 mm on the
A1 mini profile, which is provisional). A pocket cut to the shadow lets the part
lift straight out whatever its shape underneath, so a part with a wide head on a
narrow stem still releases. The price is a looser fit where the part narrows
below its widest point.

The shadow is found by drawing the part's triangles onto a grid and tracing the
outline, so it is never smaller than the part and can be a pixel or so larger.
A hole in the shadow is filled, since a pocket has no island, and a part whose
shadow is several separate pieces is refused: name the one solid that is the
part. On a model of a whole board, `guide check` takes several seconds.

## Bores

```json
"drill": {"diameter_mm": 4.0, "chuck_diameter_mm": 14.0, "depth_mm": 6.0, "stickout_mm": 60.0},
"bores": [
  {"identifier": "B1", "x_mm": 10.0, "y_mm": -5.0},
  {"identifier": "B2", "x_mm": -10.0, "y_mm": 5.0, "tilt_about": "y", "tilt_deg": 15.0}
]
```

`diameter_mm` and `depth_mm` on a bore default to the drill's. `depth_mm` is
measured **along the drill's axis from where it meets the part's top face**.

**A printed bore** (`"kind": "printed"`, the default) is a hole the printer
makes. Its modelled diameter is the drill's, plus the printer's sliding
clearance each side, plus its `hole_oversize` (printers print holes small, so
the model is larger than the hole you get). A 4 mm drill gets a 4.6 mm hole on
the A1 mini profile. It is as long as 1.5 drill diameters (at least 3 mm); that
is a default and not a measured figure. **A printed bore wears** as the bit cuts
it, so it is for a few holes.

**A bushing bore** (`"kind": "bushing"`) is a pocket for a steel drill bushing
with a hole through it for the drill, so it lasts. Give the bushing's figures:

```json
"bushing": {"inner_diameter_mm": 4.2, "outer_diameter_mm": 8.0, "length_mm": 12.0,
            "flange_diameter_mm": 11.0, "flange_thickness_mm": 3.0,
            "source": "measured with calipers on the bushings I bought"}
```

The figures are **yours**. The engine's catalog holds no bushing until a maker's
datasheet has been read, so `source` is required, and the build record says the
figures came from your file. The drill must fit through the bushing. The pocket
is the outer diameter plus the press-fit clearance each side (and the
`hole_oversize`). A flange sits on the plate's top face.

**A tilt** leans the drill. `tilt_about` is `x` or `y` and `tilt_deg` is up to 45
either way. Tilting about X for a positive angle leans the drill's **lower end
toward +Y**; about Y, toward +X. So up through the plate the bore sits the other
way, and a tilted bore needs less plate straight up (its length is along the
axis). A flanged bushing needs a flat seat, so it cannot tilt: use a printed
bore or a bushing without a flange. A bore tilted past 20 degrees prints across
its layers and comes out roughest, and the build says so.

## What the check refuses

- A part that has changed, a missing STEP file, a solid the model does not have,
  a nest deeper than the part, a part with no flat top (under 10% of its shadow
  flat at the top), or a shadow of several pieces.
- A **plate too thin** for the bores, if you set one.
- A bore too close to the part's edge: its foot must stand inside the shadow by
  its radius and a printed wall, and its head, up through the plate, must stand
  inside the plate's outline the same way (a flange only needs to rest fully on
  it). A steep tilt near an edge can run the head off the plate.
- A drill that would **come out of the part's underside** with nothing to take
  the bit (within 1 mm of it). Set `allow_exit` on a bore if you will support the
  part.
- A drill that would **break out of the part's side** at its depth.
- Two bores whose walls, or a flange and a neighbour, leave less than the
  printer's minimum wall between them.
- A drill wider than its bushing, a chuck narrower than its bit, and a bushing
  with no source.

`guide build` then slides the **chuck** up each bore's axis until it clears the
plate, any bushing flange (including a neighbour's), and finds how far the drill
reaches. For a vertical printed bore the chuck stands on the plate. A tilt lifts
it by about its radius times the tangent of the tilt, and a flange by its
thickness. The build reports `bit_needed_beyond_chuck_mm`: how much bit must
stand out of the chuck to cut to depth. If you gave `stickout_mm` and it is not
enough, the build refuses; if you did not, it reports the figure and you check
your drill against it.

## The build record and the play

`guide.json` names the guide file and the part by hash, the numbers and
provisional tolerances used, the drill and bushing figures (marked as yours),
each bore as placed (entry, head, axis, hole and pocket diameters, chuck
standoff, bit needed), and the exported files with their STL hashes. It says
`verified: false`.

For each bore it gives `worst_case_entry_play_mm` and `worst_case_tip_play_mm`:
how far the drill can sit off the bore's axis from the clearances alone, at the
part's surface and at the bottom of the hole (where the drill's tilt in the bore
adds to it). This is a **bound from the printer profile's provisional
tolerances. It is not an accuracy.** A printed guide's accuracy is something a
trial measures, and trials come in a later release; until then, check the first
holes on scrap.

The guide prints plate down, so its flat face is on the bed and the nest opens
upward.

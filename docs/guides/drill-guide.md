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
| `nest.bearing` | `top` (the default): the plate rests on the part's top face. `ledge`: for a part with no flat top; see below. |
| `nest.gap_mm` | With `ledge` only: how far the plate stands above the part's highest point (1.0 by default). |
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

## A part with no flat top

A plate cannot rest on a dome, a cylinder's curved end, or a sloped top. For
such a part set `"bearing": "ledge"`:

```json
"nest": {"depth_mm": 12.0, "wall_mm": 2.0, "bearing": "ledge", "gap_mm": 1.0}
```

The nest then follows the shadow of only the part's **top `depth_mm`**, and the
guide rests where the part **widens below that**: the part's own shoulder is the
ledge, under the nest's rim. Choose `depth_mm` to put the rim at a shoulder, a
step where the part grows wider. The plate stands `gap_mm` above the part's
highest point instead of touching it, and a drill must cross that gap too.

The check refuses a ledge nest that has nothing to rest on: a `depth_mm` within
half a millimetre of the part's height, or a part that widens under the rim by
less than 25 mm² (a part with no shoulder at that depth, like a straight pipe).
It reports `bearing_area_mm2`, how much of the part the rim lands on. A bore is
measured from the plane through the part's highest point, and the bit needed
beyond the chuck includes the gap.

A ledge nest follows the top slab's shadow and not the whole part's, so it is
cut by slicing the model: on a very large assembly that is slow.

## Copying holes from a master part

If another part already has the holes you want (a mating plate, a cover, a
gasket), read them instead of measuring:

```bash
zcad-validation guide import --holes-from master.step --part target.step \
  --output my-guide.json
```

Each round through-hole of the master becomes a bore at the same place. The
master must have **+Z up**, and a hole must run its whole height; holes under
1.6 mm are left out (`--minimum-hole-mm` changes that). Leave out `--part` to
build the guide around the master itself, to re-drill or enlarge its own holes.

Both parts are in the guide's frame, **centred on their own bounding box** in X
and Y, so a pattern copies across when the two parts share a centre. If they
do not (the master has a tab the target lacks, say), give `--offset X,Y` to
move every hole. The report lists the holes that fall outside the target. The
commonest hole size becomes the drill; a hole of another size gets its own
`diameter_mm`. A target with no flat top is given a ledge nest.

The chuck and the depth cannot be guessed, so the file is written with
`needs_review`, and `guide check` and `guide build` refuse it until you set the
drill's `chuck_diameter_mm` and `depth_mm` and remove `needs_review`. Check the
holes against the real part first: a model is often wrong.

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

The figures are **yours**, so `source` is required, and the build record says they came
from your file. Or name a **catalogued bushing**, `"bushing": {"catalog": "DIN179A-4X12"}`, which takes
no figures of its own and no flange. The drill must fit through the bushing.

**The catalog** has the headless press-fit bushings of DIN 179 type A, named
`DIN179A-<bore>X<length>` in millimetres: bores 2 to 8 mm (2, 3, 4, 5, 6, 7, 8) in the lengths
the manufacturer lists, 18 in all, such as `DIN179A-4X12` (4 mm bore, 7 mm outside, 12 mm long). They are read from a
manufacturer's part table (JW Winco's DIN 179), which gives the outer diameters in inches, converted
here (0.276 in is 7.0 mm); the bore is its nominal size, and DIN 179's F7 fit leaves a drill of that
size room. Headed bushings (DIN 172) are not catalogued, so a flange takes your own figures.
The build record's `figures_from` says the figures came from the catalogue, and its `source` names the
entry. The pocket
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
  a nest deeper than the part, a part with no flat top under a `top` bearing
  (under 10% of its shadow flat at the top; use `ledge`), a ledge nest with
  nothing to rest on, or a shadow of several pieces.
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
trial measures: see [Trying a guide](#trying-a-guide). Until you have trials,
check the first holes on scrap.

The guide prints plate down, so its flat face is on the bed and the nest opens
upward.

## Trying a guide

A printed guide is unverified until a trial has measured it. A trial records one
print of exactly the part `guide build` exported, drilled into the real thing.

```bash
zcad-validation guide trial start --build-record exports/my-guide/guide.json
# print it, fit it, drill, measure; fill in the two files it names
zcad-validation guide trial complete --trial-directory exports/my-guide/trials/trial-001 \
  --disposition pass
```

`trial start` writes `trials/trial-001/` beside the build record with two files:

- **`observations.json`**: a pass or fail for each check that applies to your
  guide. Does the guide seat on the part without rocking? Does it lift off
  without catching? Does the drill pass every bore? Does each bushing press in
  and stay? Does each hole reach its depth with the chuck seated? (The bushing
  and depth checks appear only if the guide has bushing bores or bores.) The
  guidance for each is in the file.
- **`measurements.json`**: for each bore, where the drilled hole's centre
  actually is. Positions are in the part's frame, and the file says how to turn
  a distance from the part's left and bottom edges into it. Optionally give the
  printed bore's diameter (`measured_bore_mm`, from a pin gauge: the largest that
  enters) or a bushing pocket's (`measured_seat_mm`), to see how far the printer
  was off the model.

`trial complete` checks that the printed STL still matches the build record,
that every check is answered, and that the measurements belong to this guide's
bores, then writes `guide-trial.json` with each bore's offset (dx, dy, and
radial) from where it was meant to be. A passing trial cannot have a failed check
and measures **every** bore's position. A failed or inconclusive trial may
leave bores unmeasured. A completed trial is never overwritten; record the next
print as the next trial.

**A guide is verified by two passing trials of the same build record.**

```bash
zcad-validation guide status --build-record exports/my-guide/guide.json
```

exits 0 if it is verified and 1 if not, and lists the trials. A rebuilt guide has
a new record, so it starts again with none: change the guide file or the part and
the old trials no longer count.

### A measured error for the next build

The offsets from passing trials pool into a **guide accuracy profile** for one
printer and one material:

```bash
zcad-validation guide derive --evidence-root evidence \
  --printer-profile-id bambu-lab-a1-mini --material-profile petg
```

It needs at least two passing trials, and writes
`profiles/guides/bambu-lab-a1-mini-petg.json`, for printed and bushing bores
separately: the mean, spread, and largest radial offset, the sample count, and
the mean offset in X and Y (a bias: holes all landing the same way mean the frame
or the print is off, not the guide's play). It also pools how far printed bores
and bushing pockets came out against the model. Deriving again writes the next
version and keeps the old figures.

Give it to a build with `guide build --accuracy-profile PATH`, with the same
printer and `--material-profile`. The build reports the measured figures with
their sample sizes next to its own clearance bound for each bore, says when the
measured offsets are **bigger** than that bound (the profile's clearances are
tighter than the print), and records the profile's id, version and hash. A
profile for another printer or material is refused. It is evidence about those
prints and how they were measured, and the engine does not turn it into a
promise for a new guide.

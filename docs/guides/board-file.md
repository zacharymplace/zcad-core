# Your own board

The catalog holds a handful of boards. For any other rectangular board, describe
it in a JSON file and build an enclosure from that:

```bash
zcad-validation board template --output my-board.json
# edit every number, then:
zcad-validation board check my-board.json
zcad-validation enclosure build --board-file my-board.json \
  --output-directory exports/my-board --review
```

`board template` writes a valid example (every number in it is an example, and
its sources say so). `board check` refuses what cannot be right, lists what
probably is not, and exits 1 if the file cannot be used. `enclosure build`
takes exactly one of `--board` (the catalog) and `--board-file`.

The engine does not trust a board file. It checks it, builds from it, and says
in the build summary and in `enclosure.json` that the board came from a file,
with the file's path and SHA-256, and that it is **unverified**. A printed trial
is what tells you the numbers were right.

## From a STEP model

If the maker publishes a 3D model, read the board from it instead of measuring:

```bash
zcad-validation board import --step board.step --output my-board.json
```

The model must have its **+Z up**. The import finds the PCB (the solid with the
largest footprint that is 0.4 to 3.2 mm thick; the report says which, and
`--pcb-solid-index N` names another), takes the outline and thickness from it,
reads its round through-holes, and turns every other part into a box, merging
neighbours of a similar height. It prints a report: the model's SHA-256, the PCB
it chose, the holes found (the commonest size is taken as the mounting holes;
other sizes are listed), a note if the PCB is not a plain rectangle, and the
**cable connector candidates**, the parts that overhang an edge.

The connector cannot be guessed. The file is written with `needs_review`, which
`board check` and `enclosure build` refuse, until you name the part the cable
plugs into, from the candidates:

```bash
zcad-validation board import --step board.step --output my-board.json \
  --cable-connector top-03
```

(Delete the first file, or write to another: an import never overwrites.) That
part becomes `cable_connector`, clipped to the outline, and leaves the
components. Then read the file against the real board, since a model is often
wrong, and trial it like any board from a file. A model with no mounting holes
gives a board for the snap-in cradle.

## From a KiCad board

If you have the board's KiCad design (KiCad 6 or later), read the outline, thickness and holes from it:

```bash
zcad-validation board import --kicad board.kicad_pcb --output my-board.json \
  --default-height 6 --default-height-source "tallest part, measured"
```

The import reads the board's `Edge.Cuts` outline (a rectangle, a rounded rectangle, or a polygon, following any arc KiCad 7 or later writes among a polygon's points and refusing anything else there), the thickness the file gives, and the mounting holes (round non-plated drills and `MountingHole`
footprints; the commonest size is taken and others are listed). It does not read the parts yet, so two things stay open and the file is written with `needs_review`: the **cable connector**, which you set by hand,
and the **heights**, which a KiCad file does not hold. `--default-height` with `--default-height-source` gives one height for every part, which is written as the board's `envelope` with where it came from;
give both or neither. A file with no thickness gets a placeholder you must replace.

This reader has been tested on boards written by hand, **not on a file exported from KiCad**, so check the outline and holes against the board. A hole whose place depends on how KiCad turns or
mirrors a footprint is flagged `footprint_transforms` for you to check. See [Importing a KiCad board](../roadmaps/kicad-import.md).

## Measuring a board

Look at the board from above, with its centre as the origin: **+X to the right,
+Y up the page**. The edge at +Y is `positive_y`. Width runs along X, length
along Y. Everything is in millimetres. The board is never rotated.

| Field | What to measure |
| --- | --- |
| `board.width_mm`, `length_mm`, `thickness_mm` | The PCB's outline and its thickness, with calipers. Typical thickness is 1.6 mm. |
| `mounting_holes.diameter_mm` | The hole diameter. |
| `mounting_holes.positions_mm` | Each hole's `[x, y]` from the board's centre, **or** `spacing_mm`, `[dx, dy]` between a rectangle of four holes. Give one, not both. Leave the section out and the board sits in a snap-in cradle held by its edges. |
| `standoff` | Optional `height_mm` (under the board) and `clearance_mm` (round it). |
| `cable_connector` | The connector the cable plugs into, which the wall is opened for. Its `edge`, `width_mm`, `height_mm`, `depth_mm`, `center_offset_mm` along the edge from the middle, and `bottom_offset_from_board_top_mm`. It sits inside the outline against its edge. Required. |
| `wall_openings` | Anything else the wall must be opened for, such as a barrel jack: `edge`, `width_mm`, `height_mm`, offsets. |

### Two levels of detail

- **Envelope.** Measure the height of the tallest part above the PCB and write
  `"envelope": {"top_mm": 12.0}`. The loader turns that into one box covering
  the whole board, so the enclosure is taller than it must be but never too
  short. Only the top is offered: a box under the whole board would cut the
  standoffs away, so list parts under the board as components.
- **Components.** A list of boxes: `identifier`, `center_x_mm` and
  `center_y_mm` (from the board's centre), `width_mm` (along X), `depth_mm`
  (along Y), `height_mm`, and `bottom_offset_from_board_top_mm` (0 for a part
  standing on the board, negative for one under it), with optional
  `access_edge` and `lid_vent`. A part lies wholly above or wholly below the
  board. If it reaches past an edge, mark `access_edge` so the wall is opened
  for it.

Give an envelope **or** components, not both.

## The outline

A board is a rectangle unless the file says otherwise, and the enclosure's cavity
always encloses its bounding rectangle. Say the shape when it matters, so the
PCB solid and a snap-in cradle follow it:

```json
"outline": {"type": "rounded_rectangle", "radius_mm": 3.0}
```

```json
"outline": {"type": "polygon", "points_mm": [[-15, -22.5], [15, -22.5], [15, 18], [11, 22.5], [-15, 22.5]]}
```

A polygon's points are in the board's frame (centre at the origin, +X right, +Y
up) and must fill exactly the `board` width and length about the origin, as one
loop that does not cross itself. Holes and the cable connector are checked
against the outline, not the rectangle, so a hole off a rounded corner is
refused. `board import` writes a polygon for a model whose PCB is not a plain
rectangle, thinned to within 0.02 mm; check it against the board.

What follows the outline:

- the **PCB solid** in the review and the interference checks;
- a **cradle** (a board with no holes): its ledge and stop wall follow the
  outline, and each clip stands outside the outermost edge across its width, so
  a castellated or notched edge does not put a clip inside the board. The
  outline must be roughly straight where the clips stand, or the build says so;
- **standoffs** stand under the holes as ever, since a hole is a point.

A board with no holes and an `envelope` is held in a cradle, so the envelope
stands in from its edges: 1 mm for a rectangle, and for another outline as far
as keeps its rectangle inside it (up to 8 mm). A notch too deep for that is
refused: list the parts as components.

## Test points

Optional pads a test fixture's probes land on:

```json
"test_points": [
  {"identifier": "TP1", "x_mm": -8.0, "y_mm": 12.5, "pad_diameter_mm": 3.0,
   "side": "top", "net": "3V3"}
]
```

Positions are in the board's frame, as for holes. `side` is `top` (the default)
or `bottom`; `net` is your own label, carried to the fixture's report. The check
refuses a pad that hangs off the board (judged by its outline, so a rounded
corner counts), a pad under 0.5 mm, two pads on the same side that overlap, and a
name used twice. `board check` counts the points by side. `board import` cannot
find test points, since a STEP model carries no copper: they come from your
design. See [A test fixture for your board](pcb-test-fixture.md).

## Power

```json
"power": {"typical_w": 0.5, "peak_w": 1.0, "source": "meter reading, 5 V, idle"}
```

feeds the [temperature estimate](enclosure-builder.md#temperature-estimate) as
a figure from you. A `source` is required: power with no source is not used.
Without a power figure the estimate says the board's power is unknown.

## What the check refuses and warns about

Refused (errors): wrong `schema_version` or `units`, an outline that is not
one of the forms below or whose polygon crosses or touches itself (a vertex
repeated, a vertex on another edge, an edge folding back, or two lobes joined at
one point) or does not fill the board's stated size, unknown fields, holes
outside the board's outline or given two ways, holes closer than a standoff is
wide, a connector running off its edge or hanging off a rounded corner, a part through the board, an envelope with a
bottom, power without a source, and any file still carrying a `needs_review`
note. All problems are listed at once.

Warned of: a board over 150 mm or a thickness outside 0.4 to 3.2 mm (usually
the wrong unit), a hole near the edge, no holes, a part overhanging an edge that is not marked `access_edge`, and a file
with no `source`.

## Adding a board to the catalog

A board file is unverified until a printed trial has fitted the real board. A
board that has passed two trials joins the catalog, so anyone can build with
`--board NAME`, as a file and a pull request, with no code:

```bash
zcad-validation board promote my-board.json \
  --trial-record builds/my-board/trials/trial-001/enclosure-trial.json \
  --trial-record builds/my-board/trials/trial-002/enclosure-trial.json
```

It refuses a file with errors **or warnings**, an identifier the catalog already
holds, fewer than two distinct passing trials (a trial record copied to another
folder, with the same build record, trial id and completion time, counts once),
and any trial of another version
of the file: each trial's build record carries the file's SHA-256, so a file
edited since its trials needs new trials. It writes
`src/zcad_core/hardware/data/boards/<identifier, lower case, dashes>.json`, the
same file with one field added, `verified_by`, naming the trials. Commit it and
open a pull request.

A catalogued board builds as `kind: catalog` with `verified: true` and the
trials in `verified_by`; the build record keeps the data file's SHA-256, and
`enclosure revise` refuses if that file has changed since. A `verified_by` in
your own file, built with `--board-file`, is only a claim: that board stays
unverified.

## Revising

`enclosure revise` rebuilds from the same file. It refuses if the file is
missing or has changed since the build: a revision changes the design, not the
board. To change the board, build again from the changed file.

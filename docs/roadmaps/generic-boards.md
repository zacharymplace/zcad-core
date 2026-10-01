# Generic boards

## Purpose

An enclosure can only be built around a board the catalog knows. There are five:
the Pico 2, the Feather RP2040, the XIAO ESP32-S3, the UNO R4 WiFi, and the Pi 5.
Anyone else's board, a custom PCB, a breakout, or a board the catalog has not
got to, cannot be enclosed without writing Python and extracting its parts from
a vendor model by hand.

The engine already treats a board as data. This is the design for letting a
user supply that data, and for making it from a STEP model, without any new
code per board.

This is a design, not built work. Nothing below exists in the code yet.

## What the engine needs from a board

A board is anything with this shape (`BoardSpec`, plus the mounting-hole fields
`pcb_mounts` reads):

| Field | What reads it |
| --- | --- |
| `identifier` | Names the parts and the build record |
| `board_width_mm`, `board_length_mm`, `board_thickness_mm` | The PCB box, the cavity, the cradle |
| `mounting_hole_diameter_mm` and the hole positions (or an X and Y spacing) | The standoffs; with no holes, a snap-in cradle instead |
| `recommended_standoff_height_mm`, `recommended_clearance_mm` | Standoff height and hole clearance |
| `usb_connector` (a rectangular connector on one edge) | The cable opening, the one place a plug must reach |
| `components`: boxes, each wholly above or wholly below the PCB, with an optional `access_edge` and `lid_vent` | Clearances, wall openings for parts that overhang an edge, lid slots over a fan |
| `wall_openings` | Openings for plugs or cards the components do not show |

The board is a rectangle, centred on the origin, width along X and length along
Y, seen from above, and it is never rotated: the enclosure is rotated instead.

## Decision: a board file, not a new class per board

A board is a JSON file with exactly those fields, loaded into an object that
satisfies the same protocols, so nothing in the builder changes:

```
zcad-validation enclosure build --board-file my-board.json --output-directory out
```

and `load_board(path)` from Python. The file also records, optionally, where its
numbers came from (`source`: a datasheet, calipers, a model) and the board's
power, which feeds the thermal estimate as a figure from the user, with the
source it states, instead of "unknown". The engine does not trust a board file.
It checks it, and says it is unchecked.

### Two levels of detail in one file

- **Envelope.** The board's outline, thickness, holes, its cable connector, and
  the height of its tallest part above the PCB (and, if there is one, the
  lowest below it). The loader turns those into one box above and one below, so
  a board measured with calipers needs nothing else. It is conservative: the
  box covers the whole board, so the enclosure is taller than it must be, and a
  part that needs a wall opening, such as a barrel jack, needs `wall_openings`
  by hand.
- **Components.** The same list the catalog boards carry: boxes with positions,
  sizes, and access edges. Hand-written for a small board, or imported.

### The outline is a rectangle, until the file says otherwise

A board's outline is its bounding rectangle, and the enclosure's cavity always
encloses that rectangle: the clearances are right, and a rounded or notched
board is enclosed whole. A file may give a rounded rectangle or a polygon
(phase 4), which the PCB solid, the checks, and the cradle then follow.

### The cable connector is required

The builder always cuts one cable opening. A board file names that connector,
its edge, its size, and its offset along the edge. Other parts that a plug must
reach are components with an `access_edge`, or `wall_openings`. A board with no
cable at all is a different feature and is not covered.

## Decision: a board is checked before it is built

`zcad-validation board check my-board.json` refuses a file that cannot be right
and warns about one that probably is not. It checks:

- **Schema and units.** Numbers are millimetres. A board over 400 mm or under 5
  mm on a side is refused as a likely unit mistake, and one over 150 mm is
  warned about.
- **Geometry.** Holes lie inside the outline with room for a standoff round
  them; a hole pattern with holes closer than a standoff's diameter is refused;
  the cable connector lies on its edge and within its length; each component is
  wholly above or wholly below the PCB, as the catalog requires; a component
  overhangs an edge by no more than 20 mm; identifiers are unique.
- **Plausibility.** A thickness outside 0.4 to 3.2 mm, no components and no
  envelope, no holes (a cradle is used), and a part reaching past the outline
  with no `access_edge` are warnings.

`board template` writes a filled-in example to edit. JSON has no comments, so a
`notes` field in it describes the axes. The guide gets a page on measuring a
board: where the origin is, which edge is `positive_y`, and what to measure with
calipers.

## Decision: an unverified board says so, and a trial verifies it

A board from a file is hardware the engine has never seen. The build prints
`board_source: file`, the file's SHA-256, and `verified: false`, and records
them in `enclosure.json`. The existing trial already asks whether the board
seats, is retained, and plugs in; those checks are what verify a board file. A
board that has passed two trials is a candidate to join the catalog.

## Decision: import from a STEP model with the extraction the catalog uses

The catalog's components come from a script that reads a vendor STEP model, drops
parts under 0.5 mm, splits parts through the board, merges neighbours of a
similar height but never across a hole, and marks a part overhanging an edge as
needing access. It works on five boards because each has a hand-set quarter turn
and a known USB connector. The import generalises it:

```
zcad-validation board import --step model.step --output my-board.json
```

- **The PCB solid** is found as the solid with the largest area whose thinnest
  side is 0.4 to 3.2 mm, and named in the output so it can be overridden with
  `--pcb-solid-index`.
- **The outline and thickness** are that solid's bounding box.
- **The holes** are its circular through-holes: cylindrical faces about the
  vertical axis that span the thickness.
- **The components** are the script's own, with its merge and tier rules.
- **The cable connector** cannot be guessed, so the import lists the parts that
  overhang an edge, with their sizes and edges, and the file is written with
  `needs_review: ["cable_connector"]`. The loader refuses such a file until the
  user has named one, so no board is built on a guess.
- **The frame** is the model's, centred, so no quarter turn is needed: the
  cable edge is wherever the connector is, and the enclosure is rotated.

The existing script is refactored to use the same code, so the catalog and the
import cannot drift apart. STEP files are large and often wrong; the import
records the model's hash and says when the PCB it found is not rectangular.

## Phases

1. **Board file, check, and template. Built.** The schema, the loader and its
   object, `--board-file` on `enclosure build`, `board check`,
   `board template`, the envelope form, the provenance in the build record, the
   user power figure, and the guide's page on measuring a board
   ([Your own board](../guides/board-file.md)). Deviations from the design as
   written: the envelope has a top only, because a box under the whole board
   would cut the standoffs away; a file gives an envelope or components, not
   both; an unverified board is warned of and recorded, with no
   acceptance flag; and a revision refuses a board file that has changed since
   the build.
2. **STEP import. Built.** `board import`, the generalised extraction
   (`hardware/electronics/board_import.py`), the PCB-solid guess, hole
   detection, the connector review gate, and the catalog script moved onto it;
   the five catalog models regenerate byte-identical component files through it,
   and its PCB guess picks the catalog's solid on all five. Deviations: the
   model must be +Z up (the import reports why when no solid is a PCB); holes
   within 0.1 mm of one another count as one size, the commonest size is the
   mounting holes and a tie goes to the smaller; and a second import with
   `--cable-connector PART` names the connector from the candidates the first
   listed, clips it to the outline and drops it from the components, rather than
   the user editing the file by hand.
3. **Data-driven catalog. Built.** Board files placed in
   `hardware/data/boards/` join the catalog without code, so promoting a board
   that passed its trials is a file and a pull request. Beyond the design:
   `board promote` writes the file only on two passing trials of its exact
   SHA-256 (a `verified_by` field names them), refuses a file with warnings, and
   the loader refuses a file that is invalid, unreviewed, or not named for its
   board. A catalogued board is `kind: catalog` and `verified: true` in a
   build; a user's own `verified_by` is a claim and changes nothing. No board
   has been promoted yet: none has passed trials, so the directory ships empty
   and the mechanism is tested with files made in the tests.
4. **Outlines. Built.** `outline` is `"rectangle"`, a rounded rectangle, or a
   polygon (`hardware/electronics/board_outline.py`); the PCB solid, the
   hole and connector checks, and the cradle follow it, and `board import`
   writes a polygon for a PCB that is not a plain rectangle (its top face's
   outer loop, simplified to 0.02 mm). Decisions on the way:
   standoffs needed nothing, since a hole is a point; the cavity still
   encloses the bounding rectangle; a polygon cradle keeps the rectangular
   one unchanged for a rectangular board, puts its clips outside the outermost
   edge across their width (a castellated edge), and stops its wall at three
   quarters of the board's thickness so a part overhanging a rounded corner
   does not touch it. Found and fixed with it, from phase 1: a board with no
   holes and an envelope was refused (the clip lips touched the envelope), so
   the envelope now stands in from the edges of a cradle; and the check judged
   a connector's and an opening's edge by the wrong board dimension. The five
   catalogued boards stay rectangles: their polygon outlines would change them.

Each phase is one PR. Phases 1 and 2 add a way in and change no existing board.

## Not covered

- **KiCad and other EDA files.** A `.kicad_pcb` gives the outline, the holes,
  and footprint positions, but not part heights, which live in 3D models. A later
  import could read the first three and ask for the heights.
- **Displays.** A display is its own spec with its own fields. The same file
  and import would suit it, as a follow-up.
- **Boards with no cable connector, flexible boards, and boards that stack.** A
  HAT is a board whose envelope is the whole stack.
- **Group enclosures.** The Pi 5 group is built for the Pi 5; boards of other
  kinds in bays are the modular-bays work.

## Open questions

- **JSON or something easier to write by hand.** The catalog's data are JSON
  and JSON is proposed, with a `notes` field standing in for comments. TOML is
  kinder to hand editing and would be a second format to load.
- **Whether an unverified board should need a flag.** Proposed: a warning in
  the build output and the record, not a refusal, with the trial as the control.
  A flag such as `--accept-unverified-board` would be one more thing to type on
  every build.

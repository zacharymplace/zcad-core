# Importing a KiCad board

## Purpose

[Generic boards](generic-boards.md) lets anyone supply a board as a JSON file, and made one way to fill it in from a STEP model (`board import`). Its design left the other obvious source for later: a
**KiCad PCB** (`.kicad_pcb`). A KiCad file is the board's own design, not a vendor's model of it. It has the **outline** exactly, every **mounting hole** at its true place and size, every
**footprint's position, side and courtyard**, and the **test pads**, which a STEP model cannot carry because it has no copper. It does not have what a STEP model has: **heights**. They live in
3D models the PCB file only names.

This is the design for reading a KiCad board into a board file, so that the engine's enclosures, [PCB test fixtures](pcb-test-fixtures.md), nests and guides can be built from a design the user already has.

**Status (2026-10-05): phases 1 and 2 are built; phases 3 and 4 are design only.** Phase 1 reads the outline, the thickness and the mounting holes, and phase 2 the parts, their heights from a heights file or a
default, and the cable connector (`zcad-validation board import --kicad`). Both are tested only against boards written by hand to the format's documented tokens, not against a file exported from KiCad: **no real board has
been read yet**. What the reader assumes, and what a real board must check, is under [Phase 1, as built](#phase-1-as-built) and [Phase 2, as built](#phase-2-as-built).

## What the engine does not claim

The stance of the other imports carries over, and a KiCad file adds its own:

- **No height it was not given.** A KiCad PCB has no part heights, so the engine states none. A height comes from the user, with a source, or from a 3D model the user supplies and the engine reads. A board
  with parts and no height is written with `needs_review: ["heights"]` and refused by `board check` and `enclosure build` until someone gives one, as a STEP import's cable connector is.
- **No guess at the cable connector.** As in the STEP import, the parts that sit on an edge are listed, and the user names one.
- **The courtyard is not the part.** A footprint's courtyard is a keep-out the library author drew round the part with a margin. A box made from it is conservative: the enclosure is a little bigger than it must be, never smaller.
- **An unverified board.** A board from a file is unverified, whatever tool made the file. A printed trial is what verifies it.
- **Nothing about the design.** The engine does not check the board's electrical correctness, its stack-up, or its copper. It reads geometry.

## What a KiCad PCB gives, and what it does not

The format is the s-expression one documented at <https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/> and <https://dev-docs.kicad.org/en/file-formats/sexpr-intro/>, **from KiCad 6.0** (the `footprint`
token; before 6.0 it was `module`). The header carries `(version YYYYMMDD)` and `(generator ...)`. All values are millimetres.

| What | Where in the file | Notes |
| --- | --- | --- |
| **The outline** | Items on the `Edge.Cuts` layer: `gr_line` (start, end), `gr_arc` (start, **mid**, end), `gr_rect` (start, end), `gr_circle` (center, end), `gr_poly` (pts of xy), a cubic Bezier (`pts` of four xy); also `fp_*` items on `Edge.Cuts` inside a footprint | Joined end to end into closed loops |
| **Mounting holes** | A footprint's `pad` of type `np_thru_hole`, shape `circle`, with `(drill D)`; or a `thru_hole` pad of a `MountingHole*` footprint; or a circle on `Edge.Cuts` | A drill with `oval` is a slot, not a hole |
| **Footprint position and side** | `(at X Y [ANGLE])`, the footprint's `(layer "F.Cu")` or `"B.Cu"` | Angle in degrees |
| **A footprint's footprint** | `fp_line`, `fp_rect`, `fp_circle` and `fp_arc` on `F.CrtYd` or `B.CrtYd`, in the footprint's own frame | The courtyard; its bounding box is the part's plan |
| **Pads** | `pad` with number, type (`smd`, `thru_hole`, `np_thru_hole`, `connect`), shape (`circle`, `rect`, `oval`, `roundrect`, `trapezoid`, `custom`), `(at)`, `(size X Y)`, `(layers)`, `(net N "NAME")` | Test pads and their nets |
| **3D models** | `(model "FILE" (at (xyz ...)) (scale (xyz ...)) (rotate (xyz ...)))` in a footprint | A path, and an offset, a scale and a rotation. The model itself is a separate STEP or VRML file |
| **Heights** | **Not in the file** | |

The format documents the tokens, not two conventions the import depends on: which way **Y** points and what **sign a footprint's angle** has, and how a footprint on the **bottom** side is mirrored. KiCad draws with Y increasing
downward, and the engine's board frame has +Y up, so the import flips Y. The rotation sign and the bottom-side mirror are the things most likely to be silently wrong, so the design does not rely on memory for them:
phase 1 reads a real board whose footprints are rotated and on both sides, and the import's tests check a footprint whose pad positions are known against what the board looks like, before any number is trusted.

## Decision: a small reader of its own

The reader is a short s-expression parser in the engine, with no new dependency, that returns nested lists, and a layer of typed accessors over the tokens above. It reads KiCad 6 and later, and **refuses a file
with an older version, or a `module`**, saying what to do (open it in KiCad 6 or later and save). An unknown token is skipped, since a KiCad file has many the engine does not need. The file's SHA-256, version and generator are recorded in the
board file's `source`.

## Decision: the outline from `Edge.Cuts`

1. Collect the `Edge.Cuts` items, in the board and in footprints, with their transforms.
2. Join them end to end, where ends meet within 0.01 mm, into closed loops. Arcs and Beziers are sampled to a 0.02 mm chord error, the tolerance the STEP import simplifies its outline to.
3. **One outer loop** is the board. More than one is a panel and is refused, with the count. A loop inside the outer one is a cutout: a circle of mounting-hole size is a hole; any other is **listed and not modelled**,
   since the board file has an outline and holes but not slots or windows, and the report says where each is.
4. Flip Y, centre the outline's bounding box on the origin, and write it the way the STEP import does: a plain rectangle as `"rectangle"`, four equal arcs and four lines as `"rounded_rectangle"`, anything else
   as `"polygon"`. The width and length are the bounding box.
5. An open outline (a gap, or a line that does not meet the next) is refused with the two ends and the gap between them.

The thickness is not on `Edge.Cuts`. KiCad keeps it in the board's `setup`/stack-up (`(general (thickness T))` in the files the format documents), which the import reads; where it is missing the board is written with
`needs_review: ["thickness"]`. The default is not 1.6 mm: a figure the file did not give is not a figure.

## Decision: holes from the pads

A mounting hole is a round, non-plated drill, `np_thru_hole` with shape `circle`, or a plated `thru_hole` pad of a footprint named `MountingHole*` (KiCad's own library names them so), or a circle on
`Edge.Cuts`. Each is at its pad's `(at)` through its footprint's position and angle. The commonest diameter is the mounting-hole size, and a tie goes to the smaller, as in the STEP import; other sizes are listed, with
their positions, for the user to move into `mounting_holes` if they are mounting holes. Oval drills are slots and are listed, not used. Through-hole component pads are not holes for standoffs and are not read as such.

## Decision: components from courtyards, heights from the user

Each footprint that is a part (not a mounting hole, a fiducial, a test point or a logo) becomes a box:

- **Plan.** The bounding box of its courtyard, taken through the footprint's angle and mirrored for the bottom side. A footprint with no courtyard gets the bounding box of its pads, grown by nothing, with a warning that it is
  smaller than a part's courtyard would be.
- **Side.** `F.Cu` is above the board, `B.Cu` is below.
- **Height.** From the first of these that gives one:
  1. a `--heights FILE`: a JSON object mapping a reference (`J1`), a library name (`Connector_USB:USB_C_...`) or a pattern to `{"height_mm": H, "source": "datasheet, p. 4"}`, which is the user's figure and says where it is from;
  2. a **3D model** in the footprint's `model` token, if `--models DIR` finds the file and the engine can read it (STEP), where the height is the model's extent through the model's `rotate`, `scale` and `at`, marked `from model`
     (phase 4);
  3. a `--default-height MM --default-height-source TEXT`, the user's one figure for every part left, marked as a default.
  A part with none of these leaves the board with `needs_review: ["heights"]`.
- **Merging.** Neighbouring boxes of a similar height are merged by the same rule the STEP import uses (`merge_boxes`), so a board with three hundred resistors is a handful of boxes.
- **Overhang and the cable connector.** A box that reaches past the outline gets an `access_edge`, as the STEP import marks one, and the parts that overhang or sit at an edge are listed as **cable connector candidates**; the
  user names one with `--cable-connector REF` and the file is written without `needs_review: ["cable_connector"]`.

The result is conservative in three ways, all stated in the report: courtyards are bigger than their parts, a box covers a part's whole plan at its full height, and a merged box takes its tallest member's height.

## Decision: test points, which a STEP model cannot give

A footprint is a **test point** if its library name starts with `TestPoint` or its reference starts with `TP`, or if the user lists it with `--test-points TP1,TP7`. Its pad's centre, through the footprint, is the
point's place in the board frame; its **side** is the footprint's layer; its diameter is a circular pad's size, or the smaller side of a rectangular one, with a warning, since a probe lands in the pad's middle; and its **net** is the
pad's `(net N "NAME")` name. They are written to `test_points` in the board file, where [the PCB test fixtures](pcb-test-fixtures.md) read them, so a fixture can be built from a KiCad file in two commands. Pads under 0.5 mm, two
on a side that overlap, and a pad hanging off the outline are refused by the board file's own check, as for a file written by hand.

## Decision: the command and the report

```
zcad-validation board import --kicad my-board.kicad_pcb --output my-board.json \\
  --heights heights.json --default-height 3.0 --default-height-source "tallest part, measured" \\
  --cable-connector J1 --test-points TP1,TP2
```

The report names the file's SHA-256, KiCad version and generator, the outline's kind and size, the holes found and the size taken as mounting, the cutouts it did not model, the parts and how many boxes they made, the
heights and where each came from, the cable connector candidates, the test points by side, and every warning. An import never overwrites, and the board file records `needs_review` for what is open, which the loader refuses until it
is settled. A second import with the same options writes the same file.

## Checks

| Check | What it refuses |
| --- | --- |
| Version | A file older than KiCad 6, or with `module` |
| Outline | No `Edge.Cuts`, an open loop (with the gap), more than one outer loop (a panel, with the count) |
| Holes | A hole outside the outline, two closer than a standoff is wide, no mounting size (a cradle is used, and says so) |
| Heights | A part with no height from any source: `needs_review`, refused until given |
| Cable connector | Not named: `needs_review`, refused until named |
| Test points | A pad under 0.5 mm, two that overlap, a pad off the outline, a name used twice |
| The board file | Everything `board check` already refuses, on the file the import writes |

## Phases

1. **The reader, the outline and the holes.** The s-expression reader, `Edge.Cuts` into an outline (rectangle, rounded rectangle, polygon), the thickness, the mounting holes, the report, and `--default-height` for an
   envelope-only board, so an enclosure can be built from a KiCad file at once.
2. **Components.** Courtyards through footprint angle and side, the heights file, merging, overhang, and the cable connector.
3. **Test points.** `TestPoint*` and `TP*` footprints and `--test-points`, with side and net, written to the board file for the fixtures.
4. **Heights from 3D models.** `--models DIR`, reading a footprint's STEP model through its `at`, `scale` and `rotate`, marked as from a model.

Each phase is one PR, and no existing board or import changes.

### Phase 1, as built

`zcad-validation board import --kicad FILE --output OUT [--default-height MM --default-height-source TEXT]`, in `hardware/electronics/kicad_sexp.py` (the reader) and `kicad_import.py`.

- **Reads** KiCad 6 and later (file version 20211014 or newer; an older file or a `module` is refused with what to do). The outline is `Edge.Cuts` lines, arcs, circles, rectangles, polygons and curves, in the
  board and in footprints, joined within 0.01 mm and sampled to 0.02 mm. A plain rectangle is written as `rectangle`, a rectangle with four equal quarter-round corners as `rounded_rectangle`, anything else as a
  `polygon` (at most 500 points). A panel (more than one outer loop) and an open outline are refused, the second with the two ends and the gap.
- **Holes**: round non-plated drills, plated drills of a `MountingHole*` footprint, and `Edge.Cuts` circles of 0.8 to 8 mm. The commonest diameter of 1.6 mm or more is the mounting size, a tie going to the smaller;
  other sizes and oval slots are listed with positions, and so is any other cut-out, none of them modelled.
- **Thickness** from `(general (thickness T))`. A file without one gets 1.6 mm as a placeholder **and** `needs_review: thickness`: the figure is not read, so it is not trusted.
- **Heights** are open (`needs_review: heights`) unless `--default-height` is given with `--default-height-source`; the two go together, the default is written as `envelope.top_mm`, and the board file's `source`
  says it is one default and where it came from.
- **The cable connector** could not be read until phase 2 read parts, so the file was written with `needs_review: cable_connector` and a placeholder connector. Phase 2 names it from the parts; a file with
  no parts still gets the placeholder.

**Unverified, and written as such.** Three conventions are assumed and have not been checked against KiCad: Y points down (so Y is flipped); a footprint's angle is counter-clockwise on screen; and a bottom-side
footprint is mirrored in X before it is turned. The first is how KiCad draws and affects every board; the other two only matter for a point that is *not at its footprint's origin*. A mounting hole at the centre
of a `MountingHole` footprint, the usual case, does not depend on them. Where one does (an offset drill in a turned or bottom-side footprint, or `Edge.Cuts` drawn inside one), the import lists it under
`unverified_transforms` and writes `needs_review: footprint_transforms`, which the loader refuses until the positions are checked against the board. The tests pin these assumptions as assumptions; a real
board with a rotated footprint and one on the bottom side is what settles them.

The file-version floor, 20211014 for KiCad 6, is from memory of KiCad's source and has not been checked against an exported file.

### Phase 2, as built

`--heights FILE` and `--cable-connector REF` join phase 1's options, in `kicad_import.py` and `kicad_heights.py`.

- **Parts** are every footprint but a mounting hole, a fiducial (`Fiducial*`), a test point (`TestPoint*`, or a reference `TP` and digits), a logo (the `Symbol` library, or `Logo` in the name) or a board-only one
  (`(attr ... board_only)`), each listed in the report with why. A part's plan is the bounding box of its courtyard (`fp_line`, `fp_rect`, `fp_circle`, `fp_arc` and `fp_poly` on `F.CrtYd` or `B.CrtYd`), taken through
  the footprint's place as phase 1 takes a drill. With no courtyard it is the extent of its pads, each taken as the square round its circumscribing circle so a pad's own angle does not matter, and the report warns.
  A front-side part sits on the board's top face; a back-side one hangs from its bottom face.
- **Heights** come from the heights file (a reference, then a library name, then the patterns in the file's order), then from `--default-height`. Every entry needs a height of 0.05 to 200 mm, the board
  file's own bounds, and a source. A part with neither is left out of `components` and named under `needs_review: heights`. The board file's `source` counts the heights from each, and the report lists each
  part's height, where it came from, and the heights file's keys that matched nothing. When the file has parts, the default is a part height and no `envelope` is written; with no parts it is the
  envelope, as in phase 1, and a heights file is refused as having nothing to size.
- **Merging** is the STEP import's `merge_boxes`, the front by height tier and the back as one, and never across a mounting hole none of the parts covers. A box is named by its parts: one to three
  references joined, or the first and a count (`R1_and_12_more`).
- **The cable connector**: the parts past an edge or within 1 mm of one are the candidates, largest plan first, with the edge and how far past it each reaches. `--cable-connector REF` must name one with a height;
  it is written as the connector through the STEP import's `connector_record` and taken out of the components.

**Unverified, and written as such.** A part on the back, or turned, is placed through the two conventions phase 1 assumed and has not checked, so every such part is listed under `unverified_transforms`
and the file carries `needs_review: footprint_transforms`. On a real board that will be most of them; checking a few parts of each angle and side against the board settles all of them, and the first
real board settles the conventions for good.

## Not covered

- **KiCad 5 and earlier, EasyEDA, Eagle, Altium, Gerber and ODB++.** Another reader each, and the same board file behind them.
- **Slots, cutouts and windows in the outline.** Listed, not modelled: the board file has no way to say them.
- **Copper, zones and the stack-up.** The engine reads geometry; thickness is the one stack-up figure it takes.
- **A panel of several boards,** and a board with a flex part.
- **A schematic.** The PCB is the geometry; a schematic has none.
- **Heights from a footprint's name.** A part's name does not say how tall it is, and the engine will not guess from one.
- **The KiCad 3D viewer's own bounding boxes,** which live in KiCad and not in the file.

## Open questions

- **Whether the courtyard is the right box.** It is conservative and always present for a library footprint. The alternative is the pads' extent grown by a margin, which is tighter and misses a part's body. The proposal is
  the courtyard, with the pads' box as the fallback and the choice a flag (`--plan courtyard|pads`) if a trial finds the enclosures too big.
- **Whether `--default-height` should be allowed at all.** One figure for every part is the quickest way to an enclosure, and the conservative thing is to set it to the tallest part. The proposal is to allow it and mark the
  board file's components `height_source: default`, so a build summary says the heights were a default.
- **Which KiCad versions to test against.** The format has changed between 6, 7 and 8 (strokes replace `width` from 7). The proposal is to read all three and to test each against a board exported from that version, which
  the engine's author cannot make without KiCad: phase 1 needs a real board file from the user, one with a rotated footprint and one on the bottom side, before the rotation and mirror conventions are trusted.

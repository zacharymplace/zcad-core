# Stackable items

## Purpose

Everything the engine builds so far stands alone. Units join along a row (the group's
standard joint), and an enclosure hangs on a wall (a mount), but nothing sits on
anything else. A workshop, a rack of boards and a drawer of parts all stack: bins on a
baseplate, trays under a lid, a Pi box over another, a board over a board.

This is the design for one **stack interface**, a record that says how an item's top
and bottom faces meet, and four kinds of item that adopt it: **bins** on a grid,
**trays and drawers** in a frame, the **enclosures the engine already builds**, and
**electronics layers** that stack like a hat on a board. One interface means any item
can sit on any other that shares its profile, and one check, `check-stack`, answers
whether two will.

## What the engine does not claim

The wearable housings roadmap's stance carries over, and stacking adds its own:

- **No load rating, and no stable height.** The engine does not say how much a stack
  holds, how tall it can go before it tips, or that a printed lip will not creep. A trial
  measures a wobble and a force and counts stackings; the engine has no sourced figure
  to compare any of them with.
- **No pull force for a magnet and no holding force for a latch.** A magnet's size comes
  from the catalog or the user and the engine builds its pocket. How hard it holds is
  a measurement.
- **No compatibility with any other maker's parts** until a trial shows it. A profile
  can be built to a published specification, and the record says which and by what
  source; whether a printed bin sits on a bought baseplate is a reading.
- **No electrical connection.** A layer is mechanical. A header that joins two boards,
  its alignment, and what it carries are the user's.
- **No figure it was not given.** A pitch, a lip's section, a magnet's pocket position,
  a spacer's height: each comes from a profile file with its `source`, and a figure sourced
  as an example is refused, as a screw's and a pogo pin's are.

## What the engine already has

| Need | Where it is today |
| --- | --- |
| A mount interface on an enclosure's underside, with pads and insert pockets, recorded as `mount_pad_positions` | `features/mounts.py`, `features/mount_rack.py`, `mount_pads` in `features/enclosure.py`; see [Mounting systems](mounting-systems.md) |
| A standard joint face with bolt points, a pass-through, and `check-join` for two units or two records | `features/enclosure_group_join.py`; see [Modular bays](modular-bays.md) |
| Heat-set inserts and screws by size, with pocket diameter and depth | `hardware/fasteners.py` |
| Round magnets with a pocket diameter and depth, and no use in any build yet | `hardware/magnets.py` (`D6X2`, `D8X3`, `D10X3` …) |
| A flexure whose strain is checked against a provisional limit | `mounts.flexure_for`, `FLEXURE_STRAIN_LIMIT` (1.5 per cent), used by the DIN clip, the lid catch, the slide detent, the cradle's tabs |
| A sliding lid on grooves with a detent | `features/lid_slide.py` |
| A board from a file: outline, mounting holes, parts and their heights | the board file; see [A board file](../guides/board-file.md) |
| A build record that names its inputs by hash, and trials with readings and a disposition | `enclosure_trial`, `guide_trial`, `pcb_fixture_trial`, `enclosure_group_trial`, `housing_trial` |
| Rounded outer corners, a lid that snaps on, dividers and labels | `features/housing.py`, `features/enclosure_group_dividers.py`, `features/labels.py` |

The enclosure builder has nothing on its top face, and the group's modular-bays design
listed *stacking units in Z* as not covered. A profile, a grid and a stack check are new.

## Decision: one stack interface

A **stack profile file** is the interface. It holds:

- **a pitch**, the cell's width and depth in mm, and **a height unit**, the step a
  height comes in;
- **a section for the top and the bottom face**: a short list of `(inset, height)`
  points, measured from a cell's outer wall, that draws the lip on top and the foot
  underneath. The foot of one item sits in the lip of the one below; the build checks
  that the two sections nest with the clearance the profile gives, rather than taking
  that on trust;
- **a corner radius** for a cell's outline;
- **holding points**, each a position in a cell with a kind: `bolt` (a heat-set insert
  pocket and a clearance hole), `magnet` (a pocket for a catalogued magnet), or `latch`
  (a printed flexure hook and its keeper); and
- **a source** for every figure above, and a **name**.

A profile file is checked like a board file: a missing source, an example source, a
non-nesting section, or a holding point that falls outside the cell is an error, named.
The template shows a pitch of 42 mm and a height unit of 7 mm, the published figures of
the open Gridfinity specification, with an example source the user must replace.

Why a file and not constants: the same reason as the wearable file. A bin that fits one
baseplate and not another is a profile that differs by a tenth of a millimetre, and the
only honest place for that figure is somewhere it carries its source. The engine ships no
profile of its own.

### Compatibility

The design's grid is the open Gridfinity one, so the template carries its pitch and height
unit. **The lip and foot section, the corner radius and the magnet and screw positions are
read from the published specification in phase 1, and cited in the profile's source.** Until
that is done, no number from memory goes into a template. Once it is, the engine's claim is
only that a part was built to the profile in the file named by its hash. Whether it sits on
a bought baseplate is a trial reading.

## Decision: four kinds of item

| Kind | For | Builds |
| --- | --- | --- |
| `bin` | Parts, tools, loose hardware | A bin of `cells` across and `units` high on the profile's foot, with the lip on top, with optional dividers, a label tab and a scoop |
| `baseplate` | Holding bins | A grid of cells with the profile's receiving section, for a drawer, a shelf or a desk |
| `tray` and `drawer` | Boards, sensors, small parts | A shallow tray that stacks and takes a snap lid on the top one; and a stack frame with sliding drawers, on the slide lid's grooves |
| `layer` | Boards | A board-sized plate or frame for a board file's mounting holes, with spacers whose height clears the tallest part below |
| `plate` | An enclosure | A mount plate for the enclosure's pads (a new `--mount stack`) whose underside has the profile's foot, in cells rounded up from the enclosure's footprint |

Each is built from a **stack file**, which names a profile by hash and lists its items,
as the housing file names a wearable file. `stack template`, `stack check` and `stack
build` follow `housing`'s commands, and a unit is refused with the reason if it cannot
stack: a footprint that is not whole cells, a height that is not whole units, a divider that
meets a magnet pocket.

## Decision: how a stack holds together

The profile lists the holding points and the stack file chooses which a unit uses. All four
were asked for, and each is its own check:

| Holding | What it is | Check |
| --- | --- | --- |
| Lip | The foot sits in the lip, and gravity does the rest | The sections nest with the profile's clearance; always on |
| Bolts | A heat-set insert in the lower unit and a clearance hole through the upper, at the corners | Positions line up, the insert pocket does not break through, the screw reaches the insert's depth |
| Magnets | A pocket in each facing surface for a catalogued round magnet | Pockets are the magnet's size and depth plus the catalog's allowance, face the same way on both sides, and leave the wall the printer needs |
| Latches | A printed hook on the upper unit and a keeper on the lower | A flexure's strain, by the cantilever formula, is under the provisional limit; refused with the length it would need if not |

`check-stack` takes two items, or two build records, and says whether they stack: the
footprints are whole cells, the faces nest, and **the holding points they both carry line
up and agree on kind**. A unit that has a magnet pocket where the one below has a bolt
insert is a mismatch, named, as `check-join` names a joint mismatch.

## Decision: enclosures stack by their mount, not by a new lid

The enclosures already have a mount interface underneath and nothing on top, and changing
the lid of every existing build is not a small thing. So an enclosure stacks the way it
mounts: a **stack plate** is a mount that bolts to the pads and carries the profile's
foot below it, in whole cells. A Pi 5 box, a Pico box and a housing's case can then sit on
a baseplate, on a bin, or on one another's plate. Existing builds are unchanged unless
`--mount stack` is asked for.

Putting something on top of an enclosure needs a profile on its lid. That is an open
question, below.

## Decision: layers follow the board

A **layer** is built from a board file: its outline and mounting holes give the plate's
size and the bolt points; its tallest part, and the part's access edge, give the spacer
height and the openings. It refuses a spacer shorter than the tallest part under it plus
the layer's clearance, a hole pattern that two boards do not share, and a plate that
covers a connector the file says is reached from above. A layer's electrical connection
is the user's; the engine only places the plate and the spacers.

## Checks

- **Whole cells and units.** A footprint and a height that are not whole multiples of the
  profile's pitch and unit are refused, with the nearest ones named.
- **The sections nest.** A foot's section lies inside the lip's by at least the profile's
  clearance, everywhere along it; a section that does not is refused.
- **One solid per part,** as every builder has.
- **Holding points.** As the table above, per kind, and positions agree between items.
- **Printing.** A foot's overhang angle, a lip that is too thin for the printer's minimum
  wall, and a bin too large for the bed are each refused; the bed check reports a baseplate
  as the tiles it would take.
- **`check-stack`** over any two items or records.
- **A stack's total.** The stack file may list a stack, and the build reports its height and
  its mass if the user gave a density with a source. It states no limit.

## Phases

1. **The profile and the grid (built).** The profile file with `template` and `check`; `bin` and
   `baseplate`, with dividers, a label tab and a scoop; the lip-and-foot nesting check;
   the profile's figures read from the published specification and cited.
2. **Holding (built, without latches).** Bolts, magnets and latches in the profile, built into any item, and
   `check-stack` for two items.
3. **Trays and drawers (built).** The stacking tray with a snap lid, and the stack frame with
   sliding drawers.
4. **Enclosures on the grid (built).** `--mount stack` on the single-board enclosure and the Pi 5
   group, and `check-stack` over their build records.
5. **Electronics layers (built).** The layer from a board file, with its spacers and checks.
6. **The record and stack trials.** A stack's build record, and trials in the housing
   trials' style with stack readings: whether it stacks square, a wobble in mm by feeler gauge,
   a separation force by spring scale, a count of stackings with whether anything wore, and
   whether it sits on a named other maker's baseplate. The engine states no limit for any.

Each phase is one PR. The profile is a new file and the stack plate is a new mount, so no
existing build changes unless a design asks for the new thing.

## Not covered

- **Load, tipping and creep.** See above; a stack is as tall as the user stacks it.
- **Anything but a rectangular grid.** Hex grids, round bins and non-rectangular cells
  are not in the design.
- **A bin that is not on the profile.** A bin of any other shape is not a stackable.
- **A baseplate that is screwed to a surface or magnetised to a steel one,** beyond the
  profile's holding points.
- **Electrical connection between layers.**
- **A catalogue of bins.** The engine builds the bin a file describes, not a library.

## Open questions

- **Whether an enclosure's lid gets a profile.** A stack plate lets a box sit on a grid,
  and not carry anything on its lid. The proposal is a `--stack-top` option that adds the lip
  to the lid, off by default, so no lid changes unless asked.
- **How a bin's height and a tray's height share a unit.** A tray is shallow, a few mm, and a
  bin's unit is 7 mm. The proposal is that a tray's height is a whole number of a finer unit
  the profile may give, and is a whole unit when it stacks with a bin.
- **Whether the layer's spacer is part of the layer or a separate printed part.** One part
  prints taller and one needs a separate print for each height. The proposal is a separate
  spacer, built to a record, since a spacer's height is the one thing a board changes.
- **Where a latch's keeper goes on a bin.** The lip is on the outside, where a latch would
  catch. The proposal is a keeper recess in the lip, refused where a divider or a label tab
  meets it.

### What phase 1 changed

See [Stackable items](../guides/stackable-items.md).

- **The figures are the Gridfinity Rebuilt library's, as an example to cite.** The design said the
  figures would be read from the published specification. The specification page at
  <https://gridfinity.xyz/specification/> carries a magnet size (6 mm by 2 mm) and an M3 screw, and none of the profile's
  numbers in a form that could be read. The OpenSCAD library that says it follows the page (`src/core/standard.scad`,
  commit `910e22d`) has them, so the template carries those and its source says so; the file is refused until the user
  replaces that source. The engine still ships no profile.
- **What the library gives for the foot and the lip.** Pitch 42 mm and a height unit of 7 mm; a cell's top 41.5 mm, a
  corner radius of 3.75 mm; a foot of a 0.8 mm chamfer, 1.8 mm straight and a 2.15 mm chamfer, 4.75 mm in all, drawn in
  2.95 mm at its bottom; a lip of 0.7 mm chamfer, 1.8 mm straight and 1.9 mm chamfer, 4.4 mm high, reaching 2.6 mm in.
  Laid together they leave 0.25 mm across the wall at their tightest, which is what the check computes.
- **Figures for phase 2, found now.** Magnet holes 6.5 mm across and 2.4 mm deep, screw holes 3 mm, 8 mm in from the side
  of the cell (so 26 mm apart across it). Nothing is built from them yet.
- **The lip is cut off where it comes to a point.** The section ends at a zero-width tip, which cannot print. The build cuts it
  where its reach falls to 0.4 mm, a nozzle's width, so a bin is 0.4 mm lower in its lip than the section says. The nest check
  uses the whole section, which is the more careful of the two.
- **A baseplate's pocket is the foot grown by the clearance.** The design said "the profile's receiving section", meaning the
  lip. A baseplate takes a foot, not a lip, so its pocket is the foot's own section grown by `min_nest_clearance_mm`, and
  stops where the ridge between two pockets is 0.8 mm wide (4.35 mm up the foot, with the example figures). That ridge is under the
  printer's 1.2 mm minimum wall; it is the engine's choice and the guide says so.
- **A plate has a rim.** Pockets at the edge would leave no wall at the plate's outline, so a baseplate is a rim wider
  than its cells, 1.2 mm by default. A rim is the engine's choice, not the profile's.
- **Two files, one check.** `stack check` reads a profile or a stack file and says which; both carry `file_kind`.
- **The build names its inputs by hash and writes no record.** The stack's build record and trials are phase 6, as the
  design lists.
- **The label tab and the scoop are the engine's own sizes** (a 12 mm ledge with a 45 degree gusset, a 10 mm quarter-round),
  refused where a bin is too low or narrow for them, and not figures from a source.

### What phase 2 changed

See *How an item holds* and *Does it stack* in [Stackable items](../guides/stackable-items.md).

- **Latches are not built.** The design asked for a printed hook on the upper unit and a keeper on the lower. On
  this grid there is nowhere for one: bins stand 0.5 mm apart, so a hook outside the outline strikes the next bin,
  and the lip's inside is taken by the foot. A latch needs its own design, starting with the open question of where
  a keeper goes. Magnets and bolts are built and `check-stack` knows `lip`, `magnet` and `bolt`; `latch` joins when it
  has a design.
- **Pockets meet at the foot and the baseplate, not between two bins.** A magnet or a bolt at a holding point is in
  the bottom of a foot and in a baseplate's floor. Between two bins nothing lies under a foot's holding point, because
  it stands over the cavity, so a bin on a bin is held by the lip alone and `check-stack` says so.
- **An item holds one way.** `holding` is one of `lip`, `magnet`, `bolt`, since a magnet pocket and a screw hole
  would share a point. The library the figures came from puts a screw through the magnet hole; here that is two
  choices, not one point.
- **The profile gives the points; the catalogues give the sizes.** A holding point is a position in the profile; a
  magnet's pocket comes from the magnet catalogue (6.3 mm by 2.1 mm for a D6X2, which is under the 6.5 mm by 2.4 mm the
  library lists for a magnet of 6 mm by 2 mm), and an insert's from the fastener catalogue. The pocket the library draws is
  a design choice of its own, and this is the catalogue's.
- **The baseplate floor grows to take a magnet.** A baseplate's 1.2 mm floor cannot hold a 2.1 mm pocket, so a magnet
  baseplate is refused until `floor_mm` is at least 3.3 mm. M3 inserts cannot go in a 4.75 mm foot, and M2 can. These
  refusals are the printer's minimums at work, not a limit the engine chose.
- **`check-stack` takes two items, not two records.** The build record is phase 6, so the check reads stack files
  (`FILE:NAME`). Checking two records joins it then.
- **The check lays real solids.** As well as comparing what holds them, it places the upper on the lower and
  measures any overlap, as the build does for one item against its own baseplate and itself.

### What phase 3 changed

See *Caps, frames and drawers* in [Stackable items](../guides/stackable-items.md).

- **A tray is a bin, and the new kinds are `cap`, `frame` and `drawer`.** The design listed a tray with a snap lid.
  A shallow tray is a bin of two units, so no kind is needed for it; what it lacked was the lid, and the drawers.
- **The finer unit for a tray's height is dropped.** The open question proposed a unit finer than the profile's so a
  tray could be shallow. A bin's foot is 4.75 mm of a 7 mm unit, so the least bin has about 1 mm inside, and a tray of
  two units has 8. Whole units stack with every bin, which a finer unit would not, so trays stay whole units.
- **The lid is a cap, not a snap lid.** A snap needs the latch that phase 2 deferred. A cap sits in the lip and is held
  by it, and nothing stacks on a cap. A snapping lid joins when latches do.
- **A drawer rides on ledges, not in grooves.** The design said "the slide lid's grooves". The frame's walls are 1.2 mm
  thick, too thin to groove, and a groove in a ledge 3 mm deep leaves no room for a drawer of any width beside it. A
  drawer sits on a pair of ledges that stand in from the side walls, like a tray on shelves, and slides out along them.
- **A drawer is held by nothing.** There is no stop, so it comes out when pulled. A stop would be a latch of its own,
  and the engine states no retention.
- **A drawer is checked by sweeping it.** As the hinges and slides did, the build puts the drawer in every slot and
  pulls it out, and refuses one that touches the frame. The check found no clash for a drawer sized from the frame,
  and does find one for a drawer from a taller slot.
- **A frame's front wall comes out with its inside corners.** Taking out only the wall leaves a wedge of the rounded
  corner that a drawer's corners would strike, so the cut takes the wedge too, and a drawer's corners carry the inside
  corner's radius less the clearance.

### What phase 4 changed

See *Enclosures on the grid* in [Stackable items](../guides/stackable-items.md).

- **The stack plate is a cap that screws on.** The design said a mount plate whose underside has the foot. It is built as the
  cap is, a plate on the foot, with the screw holes of a mount plate through it; the screws are M3 (or the enclosure's fastener) from
  below, so each goes through a foot, which a recess in the foot's bottom lets it do.
- **The cells are searched, not just rounded.** The design said "rounded up from the enclosure's footprint". A pad can land on a
  foot's edge in the least plate, so the build tries up to two more cells each way, smallest area first, and refuses if no plate puts all
  four pads inside a foot. A Pico 2 takes 1 x 2 and a one-bay Pi 5 group 3 x 3 with the example profile.
- **A plate bigger than the bed is refused with its cells.** The Pi 5 pair would need 5 x 3 cells, 210 mm, on a 180 mm bed. The design
  had no answer to a footprint wider than the bed; this one is refused clearly, and a wider enclosure is built as units that bolt together.
- **The record names the plate and `check-stack` reads it.** Both build records carry a `stack` entry, and `check-stack --upper` takes the
  record. Phase 6 adds the stack's own record; this is the enclosures'.
- **The enclosure's top is unchanged.** Nothing stacks on an enclosure's lid, as the design left open. That is `--stack-top`, off by
  default, and not built.
- **Existing builds are unchanged.** `stack` is another value of `--mount`, and the design and record fields default to none.

### What phase 5 changed

See *Electronics layers* in [Stackable items](../guides/stackable-items.md).

- **A layer is not on the grid.** The design had layers adopt the stack interface, with a profile and whole cells. A board is
  not whole cells, so a layer adopts the board's own mounting holes: it has its own file (`file_kind: layer`), commands
  (`stack layer template | build`) and check (`check-layers`), and `stack check` reads it. Grid items and layers do not stack on each
  other through `check-stack`; an enclosure's stack plate, or a bin, is how a board goes on the grid.
- **The spacer is a separate printed part.** The open question proposed it, since a spacer's height is what a board changes.
  A layer builds a plate and one spacer to print for each hole.
- **The cable connector counts.** The plate is opened from a connector to its edge, as it is for a marked part, and its top counts
  towards the spacer's height. A board file with an `envelope` gives that as its only part; one with `components` gives them.
- **A header's height is the user's.** The design asked for a header-height rule between layers. The board file has no header,
  and the engine does not model one: the clearance is the air over the tallest part, a setting, and `check-layers` compares holes.
- **The check lays real solids.** The spacers and the plate are put against the board's parts, as the stack items are, and the
  build fails on any overlap. The air, the opening margin and the spacer's wall are the engine's own sizes.

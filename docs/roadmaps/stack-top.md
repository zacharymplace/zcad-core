# Stacking on an enclosure's lid

## Purpose

An enclosure stacks the way it mounts. `--mount stack` bolts a **stack plate** to the pads under its floor, so it stands on a baseplate, a bin or another
box. Nothing stands **on** it: its lid is flat plastic of whatever size the board needed, with screws, vents and sometimes a fan, and no lip. The
[stackable items](stackable-items.md) design left this open as `--stack-top`, with the proposal "adds the lip to the lid, off by default, so no lid changes
unless asked".

That proposal does not survive a look at the geometry, and this design replaces it. A lip is a cell-sized ring: a foot stands in it only if the ring is
whole cells, and a lid is the size of the board plus its walls. So the top interface cannot be cut into the lid. It is a **top plate**: a baseplate, in whole
cells, that sits on the lid and is held by the lid's own screws.

**Status (2026-10-08): all three phases are built**, the last on 2026-10-03: `--stack-top` on `enclosure` and
`enclosure-group`; see [Phases](#phases).

## What the engine does not claim

The stance of the other stackable designs carries over:

- **No load rating.** The engine does not say what a lid carries, whether the plate flexes under a bin, or whether the screws hold a stack. The lid is
  2 mm of printed plastic and the plate is on top of it.
- **No compatibility with any other maker's parts** until a trial shows it.
- **No figure it was not given.** The plate's sizes are the profile's (pocket and foot) and the engine's own choices (the recess, the floor); the screws are the
  lid's.

## What the engine already has

| Need | Where it is today |
| --- | --- |
| A plate with a pocket for each cell, with the profile's foot and the nest clearance, and holding by magnets, bolts and latches | `baseplate_solid`, `cut_plate_holding`, `cut_plate_keepers` in `stack_solids.py`, `stack_latch.py` |
| A plate in whole cells found by searching for cells that put every screw inside a foot, with the screw recesses and the bed check | `mount_stack.py` (`_cell_options`, `recess_depth_mm`, `require_plate_fits_bed`) |
| The screws of a screwed lid, where they go and how long they are | `enclosure.py`, `enclosure_lid.py`, `mounts.standard_screw_length` |
| A build record that names the stack plate for `check-stack` | the `stack` entry of an enclosure's record, `stack_check._from_record` |

## Decision: a top plate is a baseplate on the lid

A **top plate** is the baseplate the profile already builds, in whole cells that cover the lid, with its underside flat on the lid's top face. Anything that
stands on a baseplate stands on it: bins, frames, another enclosure's stack plate. Holding by magnets, bolts and latches comes with it, because it is a baseplate, and so does
`check-stack`, which already reads a baseplate.

**The cells.** The least cells that cover the lid's outline, as the stack plate takes the least that cover its pads, found the same way: a screw's recess must lie in a
pocket's floor with the wall round it, so the build tries up to two more cells each way, smallest area first, and refuses if none puts every screw in a floor. The plate is
centred on the lid. It overhangs the enclosure where the cells are bigger, and nothing under the overhang is the lid's.

**How it is held: the lid's own screws, made longer.** A screwed lid is held by screws through clearance holes at its corners into heat-set inserts in the base's bosses.
The plate has a hole at each, in a recess sunk in its pocket floor, and the same screw goes down through the plate, the lid and into its insert, so lifting the plate needs the same
screwdriver as opening the box. The build prints the screw's new length: the lid screw's, plus the plate's floor under the head. The recess is the head's diameter and a little more, and
as deep as the screw's head plus 0.5 mm, as the stack plate's is; **the plate's floor must be thick enough to leave 1.0 mm under it**, which with an M3 head is 4.5 mm, so the floor is
at least that and a plate is 8.85 mm tall with the example profile (a floor of 4.5 and a pocket 4.35 deep).

**What it refuses.**

- **A lid that is not screwed.** A snap lid has no screws to share, a hinged lid must swing, and a sliding lid slides out from under a plate. A plate over any of them would fix the
  lid shut or leave itself unheld, so `--stack-top` needs `--lid screws` and says so.
- **A lid with a fan on it.** Its frame stands above the lid. (A lid with outlets is not refused: the plate leaves a window over each; see *Vent windows*, below.)
- **Screws that cannot reach.** If the plate's floor and the lid together are more than the screw's catalogued lengths or the boss's insert can take, the build refuses and names the longest that does.
- **A plate bigger than the bed,** with the cells it would take, as the stack plate is.

## Checks

| Check | What it refuses |
| --- | --- |
| Cells | A footprint of whole cells that covers the lid, with every screw's recess in a pocket floor |
| Floor | A floor too thin to sink the screw's head with 1.0 mm under it |
| Screws | A screw length the catalogue and the boss do not allow, or a lid that is not screwed |
| Openings | A lid with vents, outlets or a fan under the plate |
| One solid | The plate |
| Seats | The plate laid on the lid's top face with no overlap, and a bin laid on the plate, as the baseplate check does |
| Bed | A plate bigger than the printer's bed |

## Phases

1. **The top plate on a single-board enclosure (built).** `--stack-top` with `--stack-profile`, the cells search, the recesses, the screw length, the refusals, `check-stack` reading the
   record's `stack_top` entry as a baseplate, and the build record.
2. **The Pi 5 group (built).** The same for a group enclosure's lid, which is larger and has its own screws and outlets.
3. **Trials (built).** The record names the plate and the longer screws; a trial reads whether the plate sits flat, whether the screws reach the inserts, and a stack's wobble and count, as the
   stack plate's does. The engine states no limit.

Each phase is one PR, and no existing build changes unless `--stack-top` is asked for.

## Not covered

- **A lid with its own lip.** A lip cut into the lid is not possible unless the lid is whole cells, which a board's enclosure is not.
- **A top plate over a lid that opens.** Hinge, slide and snap lids, as above.
- **A bolt.** A bolt would pass through the lid, which is closed.
- **Load, flex and creep.** See above.

## Open questions

- **Whether a top plate may carry its own vents.** The plate could leave the lid's vent area open, with a window in its floor over each outlet and no pocket there. That costs
  cells, since a pocket cannot sit over a window, and the build would need to place them. The proposal is to refuse first and add it if a trial finds a box that needs it.
- **Whether the plate should be two parts.** A plate that is only the pockets, laid on a thin plate screwed to the lid, would let the screws stay short. The proposal is one part, since a second
  part is a second print and a second thing to lose.

### What phase 1 changed

See *A stack top: things stacked on the box* in [Stackable items](../guides/stackable-items.md).

- **It is `build_stack_top` in `mount_stack.py`, on the baseplate the profile already builds.** The plate is `baseplate_solid` with a floor of the head's recess and a millimetre, translated onto the
  lid's top face, with a hole and a recess cut at each lid screw. The cells are searched with the stack plate's own `_cell_options` and `_inside_a_foot`, so a screw's recess lies inside a foot's bottom area,
  which is inside the pocket floor.
- **The floor is 4.5 mm and the plate 8.85 mm** with an M3 head on the example profile, as the design said. The screw reach is 8 mm: a millimetre of floor under the head, the 2 mm lid and the insert's
  5 mm, so the build prints an 8 mm screw where the lid's own is 6.
- **Cells.** A Pico 2 box takes 1 x 2, 44.4 x 86.4 mm. The design's rule, the least cells that cover the lid with every recess in a floor, found a 1 x 2 plate that does, so the search added nothing here.
- **Refusals are all listed.** `_require_stack_top_possible` runs before the enclosure is built and names every reason together: a lid that is not `screws`, the display's window, `vent_area_mm2` outlets, a fan in
  the lid, and board parts that draw air through lid slots. The design also named a lid whose screws the catalogue cannot lengthen; with the lengths listed that cannot happen for an M3, so it is not checked.
- **`stack_top` is its own flag beside `mount`.** An enclosure can have a stack plate under it and a stack top over it. `stack_profile` goes with either, and a profile with neither is refused.
- **`check-stack` reads `RECORD:top`.** The enclosure's record carries `stack_top` (profile by hash, cells, floor, rim, screws), and `check-stack` takes the top as a baseplate of those cells and floor, as the
  *lower* item. A record with none says how to build one.
- **Not built in this phase:** the Pi 5 group, and the trial readings, built in phases 2 and 3. Holding by magnets, bolts or latches on a top is not asked for in this phase.

### What phase 2 changed

See *A stack top: things stacked on the box* in [Stackable items](../guides/stackable-items.md).

- **The same plate, the group's numbers.** `enclosure-group build --stack-top` calls `build_stack_top` with the group's lid screws (`lid_boss_positions`), its outer size and its lid, which is a plain box from the
  origin to the row's outer size, 3 mm thick and not 2. The screw reach is a millimetre of floor, the 3 mm lid and the insert's 5 mm, 9 mm, so an M3 is 8 mm.
- **Vents are the usual blocker.** `GroupDesign.vents` is on by default and cuts slots in the lid over each Pi's fan, so a default Pi 5 row is refused with "build with --no-vents". That is the design's
  refusal of a lid with openings, and the build says how to lift it; it does not say whether the Pi runs cool with its fan slots closed, which the thermal estimate and a trial answer.
- **The refusals are listed together** by `_require_stack_top_possible` in the group builder: a hinged or sliding lid, lid slots, outlets, a fan in the lid. The check runs after the lid is cut, because the fans
  and the slots are known only then, and before the plate is built.
- **`stack_top` joins `GroupDesign` and `GroupEnclosure`**, and the group's build record carries `stack_top`, so `check-stack RECORD:top` reads it as it does an enclosure's. The record's `design` holds `stack_top`.
- **A row too wide for the bed is refused with its cells,** by the same bed check as the plate. The two-bay Pi 5 row, 176 mm wide, is refused by the row's own bed check first.
- **Not built in this phase:** the trials, built in phase 3.

### What phase 3 changed

See *Trying a print* in [Stackable items](../guides/stackable-items.md#a-stack-top-things-stacked-on-the-box). All three phases are built.

- **The readings are `stack_top.json` beside the enclosure's other trial files.** It is written only when the build has a stack top, as `lid.json` is for a hinged lid, and a blank one is left out of the record. Both the
  enclosure trial and the group trial read it, through the same functions.
- **Two checks and six sizes.** `stack_top_sits_flat` and `stack_top_screws_reach` join the enclosure checks; the plate's width, depth, thickness and floor and the recess's depth and diameter join the sizes to measure.
  The record's stack figures gain `recess_diameter_mm` for that. The design asked the trial to read "whether the plate sits flat, whether the screws reach the inserts, and a stack's wobble and count"; the wobble
  and the count are of a bin stacked on the plate, and the force of lifting it off is added.
- **The screw length used is a reading,** kept beside the recommended one, so a trial that used a 6 mm screw says so.
- **No limits, no load rating.** The readings are set beside what was designed and nothing is compared with a figure.
- **Records are schema 1.1.0** for the enclosure's and the group's build and trial.
- **Not covered:** a rig for the force, a count to wear-out, and vent windows in the plate over a lid's outlets, which stays open until a trial finds a box that needs them.

### What the extras changed

See *Holding a bin on a top* in [Stackable items](../guides/stackable-items.md#a-stack-top-things-stacked-on-the-box).

- **Holding is the baseplate's own.** A top can carry magnet pockets in its pocket floors and latch keepers in its pocket walls, built with the functions a baseplate uses (`cut_plate_keepers`, the magnet's catalogued pocket) and
  recorded in the stack figures, so `check-stack RECORD:top` holds a bin to them with the rules a baseplate already has. A bolt is refused: it would go through the closed lid.
- **A screw and a magnet meet.** The design did not foresee it. The Pico 2 box's lid screws sit at (10.9, 32.9) from the plate's centre and the example profile's holding points at 13 mm out in each cell: 2.4 mm apart
  at the nearest. A recess and a pocket cannot share a floor, and no cell count separates them (the search found none from 1 x 2 to 3 x 4), so a pocket is **left out of each holding point within a wall of a recess**
  and the record says which. The alternative, refusing, would have made a magnet top impossible on the commonest box.
- **A top holds with fewer magnets than the bin carries.** A bin has all four; a Pico top has two per cell. How well that holds is a reading, not a figure, and the trial's `stack_top_holds` and its lifting force are where it shows.
- **Latches had no such trouble:** a keeper is in the pocket wall above the floor, and a recess is below its surface.
- **The latch's clearance is the design's `slide_clearance_mm`,** the printer's sliding clearance the enclosure is already built to (0.2 mm), since an enclosure build has no printer profile to read it from.
- **A holding top asks one check more,** `stack_top_holds`, and the trial's template carries the holding it was designed to.

### Vent windows

The open question asked whether a top could leave a lid's outlets open. It needs three decisions, and the proposal is to settle them before building.

1. **Finding the opening.** An enclosure's lid has its outlets from three builders (`vent_area_mm2` fields of slots or a hex grid, a fan's guard, slots over a board part), and the display's window. The plate needs the
   union of their footprints. The proposal is to take it from the built lid, the through-cuts the lid has beyond its screw holes, grown by a margin, and to refuse a lid whose openings are not one or a few
   rectangles' worth.
2. **What stands over a window.** A pocket cannot sit over a window: a foot's bottom would hang over the void. The proposal is that every cell a window touches is a **vent cell** with no pocket, a flat floor with
   the window cut through it, and that the plate's usable cells are the others. A bin of a vent cell's footprint is refused by `check-stack`, naming the cell. This costs cells: on a Pico 2 box's 1 x 2 plate a lid outlet
   would take one of the two.
3. **What it claims.** The plate leaving the outlet open is a statement about geometry, not air: the engine does not say the box runs cool with a top on it, and the thermal estimate does not model one. The proposal is
   to state it that way and leave the temperature to a trial.

The alternative is to refuse, as now. A top over a lid with outlets is a box that is built to be hot or has a fan; the proposal is to build windows only once a trial shows a box that needs both.

### What the vent windows changed

See *Vent windows* in [Stackable items](../guides/stackable-items.md#a-stack-top-things-stacked-on-the-box). The three decisions above were taken as proposed, with these results.

- **The openings come from the built lid.** `lid_openings` cuts the built lid from a plain lid of the same size and screw holes (`plain_lid`) and takes the footprint of each piece that goes right through the
  lid's thickness; a countersink or a pocket does not, so is not an opening. Pieces within 4 mm are one. The same code serves the enclosure and the group, which build their lids differently.
- **A vent cell is solid, not an empty cell.** `baseplate_solid` takes a `skip` set of cells and leaves them without a pocket; the window is cut through the plate over them. A vent cell keeps the plate's full
  height, since the ridges stay and a removed cell would leave the plate in pieces.
- **The screws decide.** The design said the plate would lose cells; it did not say it would lose the plate. A lid screw's head recess is cut down into a pocket floor, which a vent cell lacks, so every screw must be
  in a cell with no window, and the cell search runs again with that. The result is a split decided by the lid: the one-bay Pi 5 row (screws at its ends, fan slots in its middle) gets a 3 x 3 top with a window over
  two cells, and a Pico 2 box with an outlet is refused, because with the example profile its screws sit in every cell a window could take.
- **The lid's other blockers are gone except two.** A display's window, outlets, slots over a part and the group's fan slots no longer refuse a top. A lid that is not screwed and a lid with a fan on it still do.
  The fan is refused for a reason the design missed: the fan's frame stands above the lid, where the plate goes.
- **`check-stack` knows the vent cells.** The top's record carries them, the baseplate built from it has no pockets there, and a bin laid over one is refused with a message that names them.
- **A top with windows asks one more check,** `stack_top_vents_open`, and its template names the cells and windows.
- **Not covered:** airflow through a window, which is a temperature for a trial.

### What shifting the plate changed

See *Vent windows* in [Stackable items](../guides/stackable-items.md#a-stack-top-things-stacked-on-the-box).

- **The search has a shift.** `_place` tries, for each number of cells, no shift and then every whole millimetre each way that leaves the lid covered (the plate's slack, `(cells x pitch + 2 x rim - lid) / 2`), the least first,
  and takes the first plate whose screws are all in cells with no window. It is tried only when the lid has windows, so a top without them is placed as before, centred.
- **The case it was for.** A window off the middle of the lid, over a cell at one end that holds a screw: lid 60 x 40 mm, screws at 34 mm, a window 8 x 10 mm 20 mm left of centre. Centred, the left cell is a vent cell with a
  screw in it, and no number of cells fixes that; shifted 5 mm left, the window is in the middle cell and the screws are in the end cells. The test builds exactly this.
- **It does not rescue the Pico 2 with a large outlet.** The earlier note said a shift would let a small box have windows. On the Pico 2 box with `--vent-area-mm2 300` the outlet is 20 x 50 mm on a 33 x 77 mm lid, wider than
  the space between the screws and nearly as tall as the lid, so a window touches every row that could hold the screws, wherever the plate is. The refusal stays and now says the shift was tried. With a small outlet the
  centred search already finds a plate, so a shift is not needed.
- **The record names the shift** as `offset_mm`, `[0, 0]` when there is none, and the plate is built at that centre.

# Stacking on an enclosure's lid

## Purpose

An enclosure stacks the way it mounts. `--mount stack` bolts a **stack plate** to the pads under its floor, so it stands on a baseplate, a bin or another
box. Nothing stands **on** it: its lid is flat plastic of whatever size the board needed, with screws, vents and sometimes a fan, and no lip. The
[stackable items](stackable-items.md) design left this open as `--stack-top`, with the proposal "adds the lip to the lid, off by default, so no lid changes
unless asked".

That proposal does not survive a look at the geometry, and this design replaces it. A lip is a cell-sized ring: a foot stands in it only if the ring is
whole cells, and a lid is the size of the board plus its walls. So the top interface cannot be cut into the lid. It is a **top plate**: a baseplate, in whole
cells, that sits on the lid and is held by the lid's own screws.

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
- **A lid with openings.** Vent slots, a fan or any lid outlet is under the plate where the air cannot leave. The build refuses it, naming what the lid has; a plate with its own matching
  openings is an open question, not part of this.
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
2. **The Pi 5 group.** The same for a group enclosure's lid, which is larger and has its own screws and outlets.
3. **Trials.** The record names the plate and the longer screws; a trial reads whether the plate sits flat, whether the screws reach the inserts, and a stack's wobble and count, as the
   stack plate's does. The engine states no limit.

Each phase is one PR, and no existing build changes unless `--stack-top` is asked for.

## Not covered

- **A lid with its own lip.** A lip cut into the lid is not possible unless the lid is whole cells, which a board's enclosure is not.
- **A top plate over a lid that opens.** Hinge, slide and snap lids, as above.
- **A plate with openings that match the lid's vents.** See the open questions.
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
- **Not built yet:** the Pi 5 group, and the trial readings, as phases 2 and 3. Holding by magnets, bolts or latches on a top is not asked for in this phase.

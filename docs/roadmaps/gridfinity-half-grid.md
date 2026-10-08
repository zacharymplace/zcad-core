# Half-grid Gridfinity bins

## Purpose

[Gridfinity bins](gridfinity-bins.md) are built on the standard's 42 mm grid. The finest a drawer divides is a whole cell, which is coarse for small
parts: a bin for a few resistors takes a 42 mm square whether it needs one or not. The most used way round it is the **half grid**: bins whose bases are on
a 21 mm pitch, four to a cell, so a bin can be 21 or 63 mm across and still drop into an ordinary baseplate.

This is the design for half-grid **bins**. It adds nothing to baseplates, for the reason given under [Not covered](#not-covered).

**Status (2026-10-07): phases 1 and 2 are built.** `zcad-validation gridfinity bin --half-grid` and `gridfinity fitted --half-grid`; see
[Phase 1, as built](#phase-1-as-built), [Phase 2, as built](#phase-2-as-built) and [Half-grid bins](../guides/gridfinity.md#half-grid-bins).

## Where the figures come from

The half grid is **not in the standard**. The unofficial specification (<https://github.com/gridfinity-unofficial/specification>, README at
`ea7b4f8`) defines only the 42 x 42 x 7 mm grid, and never mentions half units or 21 mm. The half grid is **Gridfinity Rebuilt's** own feature
(<https://github.com/kennetek/gridfinity-rebuilt-openscad>, MIT licence, at commit `910e22d`, the commit the full-grid figures come from, and still the head
of its main branch), and its README and docs do not describe it. So every figure below is Rebuilt's, named by file and line, and a half-grid bin is
registered as keeping to Rebuilt, not to the standard.

What Rebuilt does, read from its source:

- **The same base on half the pitch.** `half_grid` divides the grid by two (`gridfinity-rebuilt-bins.scad:117`, from `GRID_DIMENSIONS_MM = [42, 42]` in
  `src/core/standard.scad:15`). Each base's top is the pitch less `BASE_GAP_MM`, the 0.5 mm the full grid leaves (`src/core/base.scad:34`,
  `standard.scad:205`), so a half base is **20.5 mm** square with 0.25 mm each side. Its comment says why the gap stays: it "must be kept constant, even at
  half/quarter grid sizes. Otherwise, they won't fit in normal grids" (`standard.scad:201-203`).
- **The profile does not shrink.** The 0.8, 1.8 and 2.15 mm steps (4.75 mm), the 7 mm base height and the 3.75 mm top corner radius are the full grid's,
  independent of the pitch (`standard.scad:175-229`). Rebuilt asserts a base top larger than 7.5 mm (`base.scad:234-236`), which 20.5 mm is.
- **Counts are in half units.** With `half_grid` on, `gridx` and `gridy` count 21 mm units (`gridfinity-rebuilt-bins.scad:44-46, 71`): a 2 x 2 half-grid
  bin has the outside of a full 1 x 1, with four bases under it.
- **Walls and lip are the full bin's.** The outline is the total pitch less the perimeter gap (`src/core/bin.scad:79-84`), and the wall and stacking lip
  depend only on that size and the corner radius (`src/core/wall.scad:25-45`). One bridge joins all the bases (`base.scad:44`).
- **Magnet and screw holes at the bin's outer corners only.** `half_grid` implies `only_corners` (`gridfinity-rebuilt-bins.scad:50, 115`): four holes in the
  whole footprint, 4.8 mm in from its bottom edge (`base.scad:46-61, 273-276`, `standard.scad:35`). This departs from the specification's "holes in all four
  corners of every unit", which a 20.5 mm base could not hold: two 6.5 mm holes 8 mm in from each side of a 21 mm unit would overlap.
- **No half-cell baseplate.** Rebuilt's baseplate takes a fixed 42 mm grid (`gridfinity-rebuilt-baseplate.scad:73`, `src/core/gridfinity-baseplate.scad:19`).
  A half-grid bin sits in the ordinary baseplate: each cell is an open socket with no ridge in its middle, and four half bases put their outer faces where
  one full base's would be.

Neither source says anything about a half-grid bin with an **odd** count, one that covers half a cell; the next section is the engine's reading of the
geometry, which the build checks and a trial settles.

## What the engine does not claim

- **Not that a half-grid bin keeps to the standard.** It keeps to Rebuilt's half grid; the record says so, and names the figures' source as Rebuilt, not the
  specification.
- **Not that a bin covering half a cell stays put on its own.** See below.
- Everything the full grid does not claim: fit with every generator's parts, load, and any printer correction to the interface.

## Decision: `--half-grid` counts in 21 mm units

`zcad-validation gridfinity bin --half-grid --units 3x2 --height 3` builds a bin 3 by 2 half units (63 by 42 mm outside, less the gap), as Rebuilt counts.
Counting in half units keeps one meaning per number and matches what Rebuilt users type; a half-grid bin's record states its pitch, 21 mm, beside its counts,
so a 2 x 2 half-grid bin and a full 1 x 1 bin are never mistaken for each other. Height stays in 7 mm units, since the half grid halves the pitch, not the
height.

Everything else about a bin is unchanged: walls, the optional stacking lip, dividers and label tabs (which depend on the inside, not the pitch), the base
height, the bridge. Only the bases and the holes change:

- a **base** under every half unit, the full profile on a 20.5 mm top with 3.75 mm corners;
- **magnet and screw holes** at the bin's four outer corners only, as Rebuilt places them, and refused when the bin is one half unit across in either
  direction: a half base's bottom is 14.6 mm across (20.5 mm less the profile's 2.95 mm each side), so holes 4.8 mm in from its edges would sit 2.5 mm
  from its centre, and two 6.5 mm holes there overlap.

## Decision: a bin covering half a cell is warned of, not refused

A bin whose count is odd in a direction covers half a cell there. Along that direction, one side of its bases rests on a cell's slope and the other faces
the open middle of the cell, so nothing but a neighbour stops it sliding up to 21 mm. A bin 3 half units across is still held, by the whole cell under its
other two units; a bin **1 half unit** across in a direction is not held in that direction at all.

The engine's seat check (clear when raised 0.05 mm, meeting the baseplate when pushed 0.2 mm lower) cannot see this, since a bin resting on one slope passes
it. So phase 1 adds a **located** check: in each direction, some cell under the bin must meet its bases on both sides. A bin 1 half unit across in a
direction fails it, and the build **warns** that the bin can slide half a cell unless a neighbour holds it, rather than refusing: packing half bins
together is what the half grid is for, and Rebuilt builds them. Whether a lone half bin moves enough to matter is a trial's to say.

## Checks

| Check | What it refuses or warns |
| --- | --- |
| The standard's profile | A half base whose top is not 20.5 mm with 3.75 mm corners, or whose profile is not 4.75 mm tall (checked on the solid, against Rebuilt's lines) |
| Seats | A half-grid bin, set in the engine's own baseplate at each place it can go, sharing volume with it or not resting on a socket's profile |
| Located | Warns of a bin that some direction holds on one side only |
| Stacks | A half-grid bin's bases set in a full bin's lip, and a full base in a half-grid bin's lip, sharing volume with the lip |
| Holes | Magnet or screw holes asked for on a bin 1 half unit across in either direction |

The full grid's walls, printability and one-solid checks apply unchanged.

## Trials

The [Gridfinity trial](gridfinity-bins.md#phase-4-as-built) needs nothing new: a half-grid bin is a bin, its record names its pitch, and its trial names
the baseplate it was tried in. A trial in a baseplate from another generator says the most, and one of a bin 1 half unit across, alone in its cell, says
whether the located warning matters.

## Phases

1. **Half-grid bins (built).** `--half-grid` on `gridfinity bin`; the bases on a 21 mm pitch; the outer-corner holes and their refusal; the located check and
   warning; the stacking checks both ways; the figures registered against Rebuilt's lines; the record's pitch.
2. **Fitted bins on the half grid (built).** `--half-grid` on `gridfinity fitted`, so a measured object takes the fewest half units: a 50 mm tool in a bin 63 mm across
   instead of 84 mm.

Each phase is one PR, and no full-grid bin changes.

### Phase 1, as built

`BinSpec(half_grid=True)` in `features/gridfinity.py`, with `HALF_GRID_MM` and `HALF_GRID_HOLE_INSET_MM` in `features/gridfinity_standard.py`, each
registered against Rebuilt's lines.

- **Counts.** 1 to 16 half units each way, twice the full grid's 8, as far as the bed allows.
- **Seating.** The bin is set at a cell's corner in a baseplate of the whole cells it covers. A bin within one cell rests on the cell's slopes; one that
  covers more than a cell rests on the ridge between cells, 0.25 mm higher, as a full bin of more than one unit does. A test shows the check tells the
  two apart: a 2 x 2 half-grid bin is held at the slopes and not at the ridges.
- **Located.** As designed, a count rule: a bin one half unit across in either direction is warned of. A bin of two or more half units always has a whole
  cell under it in that direction.
- **Stacking both ways.** A half base set in the corner of the bin's lip (`stacks`) is a half-grid bin stacked on any bin, since a lip depends only on the
  outline; a full base in the lip (`takes_a_full_base`) is a full bin stacked on a half-grid one, checked where the bin is two or more half units each way.
- **The record** gives the pitch and `half_grid` in its settings, adds Rebuilt's half grid to its sources, and the build is named `gridfinity-bin-half-…`.

### Phase 2, as built

`FittedSpec(half_grid=True)` in `features/gridfinity_fitted.py`. The fewest units are counted at the half grid's pitch, so a 50 x 30 mm tool takes 3 x 2
half units (62.5 x 41.5 mm) where it took 2 x 1 full ones (83.5 x 41.5 mm).

- **Shared checks.** The seat, the stacking checks, the hole refusal and the located warning moved into `features/gridfinity.py` as
  `seats_in_baseplate`, `stacking_checks`, `refuse_overlapping_holes` and `located_warnings`, which the plain and fitted bins both call; a full-grid
  fitted bin's checks are what they were.
- **Stacking on a fitted bin.** As on the full grid, a stacked base rests on the solid top inside the lip; a half-grid fitted bin two or more half units
  each way also takes a full base there.
- **Names.** The build is named `gridfinity-fitted-<object>-half-<x>x<y>`.

## Not covered

- **Half-cell baseplates.** Neither source has one; a baseplate with 21 mm cells would be the engine's own interface, fitting only the engine's bins. The
  half grid works because its bins fit the ordinary baseplate.
- **Quarter grids and other pitches.** Rebuilt's comment mentions quarter grids, but its code divides only by two.
- **A mix of pitches in one bin.** A bin is all full or all half.

## Open questions

- **Whether `--units` should accept halves (`1.5x1`) instead of a flag.** It would let one number mean the outside in full units, but `1.5` is a count of
  nothing Rebuilt users type. The proposal is the flag, with the record's pitch beside the counts.
- **Whether a bin 1 half unit across should be refused rather than warned.** The proposal is to warn, and let a trial of a lone half bin decide.
- **Whether holes should follow Rebuilt or be refused on every half-grid bin.** The specification's every-unit holes cannot fit; Rebuilt's outer corners are
  the only placement either source gives. The proposal is Rebuilt's, registered as Rebuilt's.

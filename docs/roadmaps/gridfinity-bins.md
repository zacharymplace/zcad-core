# Gridfinity bins

## Purpose

Everything the engine builds so far is one of a kind: a cup for this remote, a nest for this part. Storage is the opposite. People keep things in systems,
and the most widely printed one is **Gridfinity**: bins on a 42 mm grid that drop into baseplates and stack on each other, made by thousands of people with
dozens of generators, all fitting together because they keep to the same few dimensions.

That is the reason to build it: a part that keeps to a published interface fits things the engine has never seen. It is also the test. A Gridfinity bin is
judged by whether it seats in someone else's baseplate, so the engine's figures must be the standard's, not its own.

This is the design for building Gridfinity **bins** and **baseplates**, and for the thing the engine can add that a generic generator cannot: a bin with a
pocket cut to a **measured object**, from the captures and models the holders already read.

**Status (2026-10-06): design only.** Nothing here is built.

## Where the figures come from

Gridfinity is a community standard, not an official one; the community's own specification page calls itself a work in progress. Its figures are taken from
two sources, and the engine says which each figure comes from:

1. **The unofficial specification** (<https://github.com/gridfinity-unofficial/specification>, the README and its two profile drawings): the 42 x 42 x 7 mm
   grid; a bin 41.5 mm square (0.5 mm tolerance) with 3.75 mm corners and a 4.75 mm base profile; a baseplate cell 42 mm square with 8.0 mm corners, 5 mm
   tall; magnets 6 mm across and 2 mm thick, in all four corners of every unit.
2. **Gridfinity Rebuilt** (<https://github.com/kennetek/gridfinity-rebuilt-openscad>, MIT licence, `src/core/standard.scad` at commit `910e22d`), a widely
   used generator whose constants mark what follows the specification. It gives the steps the drawings do not:
   - the **base profile**, from the bottom up: 0.8 mm out at 45 degrees, 1.8 mm straight up, 2.15 mm out at 45 degrees (4.75 mm in all, which is the
     drawing's figure), with a 3.75 mm corner radius at its top;
   - the **base height**, 7 mm, the profile plus the bridge tying a bin's units together;
   - the **stacking lip**, from its inner tip up: 0.7 mm out at 45 degrees, 1.8 mm straight up, 1.9 mm out at 45 degrees;
   - the **magnet hole**, 6.5 mm across and 2.4 mm deep (a 2 mm magnet and two 0.2 mm layers), 8 mm in from each side of a unit; and the **screw hole**, 3 mm.

Figures Rebuilt marks as its own choices (a 0.95 mm wall, a 1.2 mm support under the lip, crush ribs, the label tab's 36 degrees) are the engine's to choose
again and are registered as design values, not as the standard. Where the two sources agree (the 4.75 mm profile, the 41.5 mm top, the corner radii), the
tests check the engine's solids against both.

**Height.** A bin of `u` units is `7u` mm from its bottom to the top of its wall, the base included, with the stacking lip above that, as Gridfinity Rebuilt
counts it by default. A 3-unit bin's wall is 21 mm tall; stacked, it carries the next bin's base in its lip.

## What the engine does not claim

- **Not that it fits every Gridfinity part.** Generators differ in small ways (a lip's support, a baseplate's floor, magnet press fits). The engine keeps to
  the figures above and claims those; whether a bin seats in a baseplate printed from another generator is what a trial says.
- **Nothing about load.** A bin's strength, a magnet's hold, and what a stack bears are not modelled.
- **No printer correction to the interface.** The 0.25 mm each side between a bin and its cell is the standard's, so a bin is never widened or narrowed by
  the coupon's measured fit. The coupon's side-gap shortfall is reported beside the build: a printer that closes a gap by more than 0.25 mm will print bins
  that bind, and the build says so rather than quietly changing the interface.

## Decision: a bin is units, height and a lip

A bin is `x` by `y` units (1 to 8 each, as far as the bed allows) and `u` units tall (2 or more: a 1-unit bin is all base). It has:

- a **base** on every unit: the base profile swept round the unit's 41.5 mm square, its corners 3.75 mm, joined above by the 7 mm base's bridge, so a 2 x 3
  bin seats on six cells;
- **walls** round the whole footprint, at the engine's wall thickness (1.2 mm, the A1 mini profile's minimum, or more);
- an optional **stacking lip** (on by default), the profile above, with a 45-degree support beneath it so it prints;
- optional **magnet holes** in the four corners of every unit's base, opening on the bin's underside, which prints on the bed; and optional **screw holes**.

The bin's inside is a single cavity in phase 1. Dividers, compartments and a label tab are phase 2.

## Decision: a baseplate is cells

A baseplate is `x` by `y` cells (as far as the bed allows), each a 42 mm square socket with 8.0 mm corners, the base profile's inverse grown by the 0.25 mm
gap, 5 mm tall (the drawing's figure). It prints flat. Magnet and screw holes in a baseplate are phase 2; a plain baseplate is phase 1. A baseplate larger
than the bed is built in pieces that butt together, each piece whole cells, the way the modular bays split a row: phase 2.

## Decision: a bin for a measured object

This is the engine's own contribution. A **fitted bin** takes a caliper capture or a STEP model, as a holder does, and cuts a pocket for it into a solid
bin's top, the object lying flat with its face up:

- the bin's footprint is the fewest units that hold the object's footprint with a wall round it, and its height the fewest units that bury it to the depth
  asked;
- the pocket is the object's shadow from above grown by the clearance (the coupon's measured one under `--compensation-profile`; inside the bin, the fit is
  the engine's, unlike the interface), open at the top, with the holders' finger notch; a capture's face features stay uncovered since nothing is above them;
- the space under the pocket is solid to the base, or hollowed with a wall when the user asks, to save plastic.

So a caliper, the engine and a Gridfinity drawer make a tool tray that fits the tool. Phase 3.

## Checks

| Check | What it refuses |
| --- | --- |
| The standard | A unit's base whose top is not 41.5 mm square with 3.75 mm corners, or whose profile is not 4.75 mm tall; a baseplate cell not 42 mm with 8.0 mm corners |
| Seats | A bin's base, set in the engine's own baseplate, sharing volume with it, or not resting on the socket's profile |
| Stacks | A 1 x 1 base set in a bin's lip sharing volume with the lip |
| Walls | A wall or a floor under the printer's minimum |
| Printable | A bin or a baseplate larger than the bed; an overhang past 45 degrees |
| One solid | A bin in pieces |
| A fitted bin | The object not fitting its pocket, or not lifting straight out |

The figures in the first row are checked on the built solid, against the two sources, so a change that drifts from the standard fails the gate.

## Trials

A Gridfinity trial records a printed bin against a real baseplate: which baseplate (the engine's, or another generator's, named), whether it drops in and
seats flat, whether it lifts out, how it feels in the cell (loose, right, tight), whether a bin stacks on it, and whether the magnets, if any, hold it. The
engine states no pass mark. A bin is verified on two passing trials, as a holder is; a trial in a baseplate from another generator is what says it keeps to
the standard in practice. Phase 4.

## The command and the files

```
zcad-validation gridfinity bin --units 2x3 --height 6 --output-directory exports/bin-2x3x6
zcad-validation gridfinity baseplate --units 4x4 --output-directory exports/plate-4x4
zcad-validation gridfinity fitted --capture caliper.json --depth 15 --output-directory exports/caliper-bin
```

A plain bin or baseplate needs no file: its units and options are the whole of it. A fitted bin names its object as a holder does, by path and hash. Each
build writes a record that names the sources its figures come from, and says the part is unverified.

## Phases

1. **Plain bins and baseplates.** The standard's figures in one module with their sources; a bin of `x` by `y` by `u` with its bases, walls, stacking lip and
   magnet and screw holes; a plain baseplate; the standard, seats, stacks, walls, printable and one-solid checks; `gridfinity bin` and `gridfinity baseplate`.
2. **Inside and under.** Dividers and compartments, a label tab; magnet and screw holes in baseplates; a baseplate in pieces when it outgrows the bed.
3. **Fitted bins.** A bin with a pocket for a captured or modelled object.
4. **Trials.** `gridfinity trial`, with a baseplate from another generator named, and verification on two passing trials.

Each phase is one PR, and nothing that exists changes.

## Not covered

- **Half-grid and other grids.** Gridfinity has variants (half units, "lite" thin-walled bins, weighted baseplates, other generators' refinements). The
  engine builds the standard's full units first.
- **Spiral-vase bins.** A print mode, not a shape; the slicer's.
- **A drawer or a cabinet.** The engine's stackable items already make drawers; a drawer sized to a Gridfinity grid is a later design.

## Open questions

- **Whether the lip should be on by default.** Most bins have one; a bin at the top of a drawer that nothing stacks on does not need it. The proposal is on.
- **Whether a fitted bin's pocket should be cut to the object's shadow or to its outline.** The shadow lifts straight out, which is what a tray needs. The
  proposal is the shadow, as the nest and the holder do.

# Gridfinity bins and baseplates

[Gridfinity](https://gridfinity.xyz/) is a storage system on a 42 mm grid: bins that drop into baseplates and stack on each other. The engine builds bins and
baseplates that keep to its published figures, so they fit the system you already have.

```bash
zcad-validation gridfinity bin --units 2x3 --height 6 --output-directory exports/bin-2x3x6
zcad-validation gridfinity baseplate --units 4x4 --output-directory exports/plate-4x4
```

Each exports STEP and STL, checks them against the printer profile, and writes `gridfinity.json`, a record of what was built, which figures it was built
to and where they come from, and that the part is **unverified**.

## Bins

| Option | What it is |
| --- | --- |
| `--units 2x3` | Units across and front to back, 1 to 8 each, as far as the bed allows. A 4 x 4 bin is 167.5 mm and fits the A1 mini's 180 mm bed. |
| `--height 6` | Height in 7 mm units, 2 or more. A bin of `u` units is `7u` mm from its bottom to the top of its wall, its base included. |
| `--no-lip` | Leaves off the stacking lip, which otherwise stands 4.4 mm above the wall so another bin can sit on it. |
| `--magnets` | Magnet holes for 6 x 2 mm magnets, 6.5 mm across and 2.4 mm deep, in the four corners of every unit, 8 mm in from each side. They open on the underside. |
| `--screws` | M3 screw holes, 3 mm across, in the same corners, up through the base to leave the printer's floor (1.2 mm) under the cavity. |
| `--divisions 3x1` | Compartments across and front to back. Dividers are 1.2 mm (or the printer's minimum wall), split the inside evenly, and stand from the floor to half a millimetre under where a stacked bin's base comes down, so the bin still stacks. A compartment narrower than 10 mm is refused. |
| `--label-tabs` | A label shelf along the back wall of each compartment in the back row, 12 mm deep, its top level with the dividers', on a 45-degree underside so it prints. A back compartment shallower than 24 mm is refused. |
| `--wall-mm` | The wall, 1.2 mm unless you give more; never under the printer's minimum. |
| `--compensation-profile` | A coupon's measured fit: it does not change the bin (see below), but a printer that closes gaps too much is warned. |

Every unit has the standard's base: 41.5 mm square with 3.75 mm corners at its top, stepping in by 2.15 mm at 45 degrees, straight for 1.8 mm, and in by
0.8 mm at 45 degrees to its bottom, 4.75 mm in all. A bridge joins the units above the bases to the 7 mm floor. The stacking lip steps out from its inner
tip, 2.6 mm in from the outside, by 0.7 mm at 45 degrees, up 1.8 mm, and out 1.9 mm at 45 degrees to the outside edge; a 45-degree shoulder under its tip
carries it, so the bin prints standing on its base with nothing overhanging.

## Baseplates

`--units 4x4` makes a plate of 42 mm cells, 5 mm tall with 8 mm corners outside. Each cell's socket is the baseplate profile (0.7 mm at 45 degrees, 1.8 mm
straight, 2.15 mm at 45 degrees) over a 0.35 mm straight clearance, open through the plate.

- `--magnets` and `--screws` put the plate on a solid floor under its cells, as Gridfinity Rebuilt's are: 1 mm, with 2.4 mm added for magnet pockets and
  2.5 mm for countersinks. A magnet pocket, 6.5 mm across, opens up from the floor's top under each of a bin's magnets; a screw hole, 3 mm, goes through the
  floor below it, with a 45-degree countersink 8 mm across so an M3 screw's head sits under the magnet. With both the plate is 10.9 mm tall. The sockets
  start on the floor, where a bin then rests. The floor is solid, not cut away to save plastic as some generators do.
- **A plate larger than the bed** is built in pieces of whole cells that butt together: as few as the bed allows, as even as the cells allow (five cells
  on a 180 mm bed are three and two). The plate is built whole and cut at the cells' edges, so the pieces are exactly the plate; each is exported as
  `baseplate-1`, `baseplate-2` and so on, and only the plate's outer corners are rounded. Nothing joins the pieces: lay them side by side.

## How a bin sits

A one-unit bin rests on its cell's slopes, its bottom level with the plate's. A bin of more than one unit rests on the ridges between cells: they peak at
the plate's 5 mm, above the 4.75 mm where the bridge joins the bin's units, so it stands 0.25 mm higher. That is what the figures give, not a choice of the
engine's; the record says which. Stacked, a bin's base sits in the lip below it 0.35 mm under the lip's foot, where their slopes meet.

## The fit is the standard's

A bin is 0.25 mm smaller than its cell on every side, by the standard. The engine never changes that for your printer, since a bin widened or narrowed for
one printer no longer fits the system. If a calibration coupon says your printer closes a side gap by more than 0.25 mm, `--compensation-profile` makes the
build warn that its bins may bind, and builds the bin to the standard anyway.

## Where the figures come from

Gridfinity is a community standard. Every figure the engine builds to comes from one of two sources, named in the record:

- the **unofficial specification**, <https://github.com/gridfinity-unofficial/specification>: its README and its two profile drawings;
- **Gridfinity Rebuilt**, <https://github.com/kennetek/gridfinity-rebuilt-openscad> (MIT licence), `src/core/standard.scad` and
  `src/core/gridfinity-baseplate.scad` at commit `910e22d`, whose constants mark what follows the specification.

The tests check the built solids against them: the base's 41.5 mm top and its bottom, the baseplate's 42 mm cells and 5 mm height, a bin seated in the
engine's baseplate and a base stacked in a lip, each clear when raised 0.05 mm and meeting what holds it when pushed 0.2 mm lower. The figures are listed,
with their sources, in [Figures taken on trust](../reference/figures.md).

## What is checked, and what is not

A bin is **one solid**, its base keeps to the standard, it **seats** in the engine's own baseplate and, with a lip, a base **stacks** in it. A baseplate is
one solid, its cells keep to the standard, and it holds a bin. Both must fit the printer's bed.

**The engine says nothing about whether a part fits a baseplate or a bin from another generator, what a bin or a stack bears, or how well a magnet holds.**
Generators differ in small ways; a printed trial in a baseplate made elsewhere is what says a bin keeps to the standard in practice. See
[the design](../roadmaps/gridfinity-bins.md).

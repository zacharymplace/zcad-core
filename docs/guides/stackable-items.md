# Stackable items

A **stack profile** says how an item's top and bottom faces meet another's. Bins and
baseplates built on one profile sit on each other, and a bin stacks on a bin like it. This
release builds the bins and baseplates, holds them with magnets or bolts, and checks whether two
items stack; latches, trays, enclosures and layers come in later releases (see the
[stackable items design](../roadmaps/stackable-items.md)).

```bash
zcad-validation stack template --kind stack-profile --output my-profile.json
# check the figures against a source you trust, cite it in "source", then:
zcad-validation stack check my-profile.json
zcad-validation stack template --kind stack --profile-file my-profile.json \
  --output my-stack.json
# edit the items, then:
zcad-validation stack check my-stack.json
zcad-validation stack build --stack-file my-stack.json --output-directory exports/my-stack
```

## The stack profile

The engine ships **no profile of its own**. The template holds the figures of the Gridfinity
Rebuilt OpenSCAD library (`src/core/standard.scad`, commit `910e22d`), which says it follows
the open specification at <https://gridfinity.xyz/specification/>. That page does not carry the
profile's numbers in a form the engine's author could read, so the figures are the library's, as
an **example**: the template's `source` begins `EXAMPLE`, and a file that leaves it is refused. Check
the figures against a source you trust and say where they came from.

| Field | Meaning |
| --- | --- |
| `pitch_mm`, `height_unit_mm` | A cell's width and depth (42), and the step a height comes in (7). |
| `gap_mm` | What a cell's top outline is short of the pitch (0.5), so two bins side by side leave a gap. |
| `corner_radius_mm` | The radius of a cell's outline where the foot is widest (3.75). |
| `foot` | The section a bin stands on: `[inset, height]` points from the bottom, ending at inset 0. |
| `lip` | The section a bin takes the foot above in: from its base, ending at inset 0. |
| `min_nest_clearance_mm` | The least gap the file claims between a foot laid in a lip (0.25). |
| `holding_points` | Where a magnet or a bolt goes in a cell, each `[x, y]` from its centre (the template has the four corners, 13 mm out). Up to 16, 5 mm or more apart, inside the cell. |

An **inset** is how far in from the item's outer wall, at that height. The check refuses a
section that does not start at height 0, does not end at the wall, moves back in as it rises, or
leans more than 45 degrees (it would print with support).

**The check does not take the sections on trust.** It lays the foot in the lip, finds the least gap
across the wall at each height either turns, and refuses a profile whose foot stands outside the lip
or leaves less gap than the file says. With the example figures that gap is 0.25 mm.

## The stack file

A stack file names a profile by its hash and lists items. If the profile has changed since, the stack
is refused.

```json
{
  "kind": "bin", "name": "parts-bin", "cells": [2, 1], "units": 3,
  "dividers": {"x": 1, "y": 0}, "label_tab": false, "scoop": true
}
```

| Item | Fields |
| --- | --- |
| `bin` | `cells` (across, deep), `units` high, optional `wall_mm`, `floor_mm` (1.2), `dividers` (counts along `x` and `y`), `label_tab`, `scoop`, `holding`. |
| `baseplate` | `cells` (across, deep), optional `floor_mm` (1.2), `rim_mm` (1.2), `holding`. |

A footprint is whole cells and a height is whole units, because they are counts. A bin is refused if its wall
or floor is under the printer's minimum, if its wall is thicker than the lip reaches in from the wall (2.6 mm
with the example figures), if dividers leave a compartment under 5 mm, or if it is too low for a label tab (a bin
needs 12.5 mm of height inside) or a scoop (10 mm). A baseplate too big for the bed is refused with the number of
cells the bed takes.

## What is built

- **A bin** stands on one foot per cell, with walls on the cell outline, a floor, and the lip on top. The lip is
  cut off where it comes to a point, leaving a flat 0.4 mm wide, and a support under its base holds it up where
  the wall is thinner than the lip reaches. Walls end at `units` of the height unit from the bottom of the feet.
  Dividers are 1.2 mm thick; a label tab is a 12 mm ledge on the back wall's inside with a 45 degree gusset; a
  scoop is a 10 mm quarter-round at the front of the floor.
- **A baseplate** is a plate with a pocket for each cell: the foot's section, grown by the clearance. The pocket
  stops where the ridge between two pockets is 0.8 mm wide at its mouth, narrower than the printer's minimum
  wall; a ridge is not a wall, but it is a place to look when you print one.

These dimensions (the lip's flat, the ridge's width, the divider, the tab, the scoop) are the engine's own
design choices, not figures from the profile's source.

## How an item holds

An item's `holding` is `lip` (the default), `magnet` or `bolt`. The profile's `holding_points` say where.

| Holding | Needs | Builds |
| --- | --- | --- |
| `lip` | nothing | Nothing at the points: the foot sits in the lip and gravity does the rest. |
| `magnet` | `"magnet": "D6X2"` (any catalogued magnet) | A pocket for the magnet in the bottom of each cell's foot, and one in each baseplate pocket's floor, sunk into it from above. The pocket is the magnet's size plus the catalogue's allowance: 6.3 mm across and 2.1 deep for a D6X2. |
| `bolt` | `"fastener": "M2"` (any catalogued fastener) | A heat-set insert pocket in the bottom of each foot, and a clearance hole through a baseplate's floor under it. The build reports the least length of screw that passes the floor and reaches the insert's depth. |

A holding is refused, with the figures, when it would break through or leave too little: a pocket deeper than the
foot leaves the printer's minimum floor above it (an M3 insert is 5 mm deep in a 4.75 mm foot; an M2.5's 4 mm
leaves 0.75), a magnet pocket in a baseplate whose floor is under the pocket's depth plus the minimum floor (a
D6X2 needs a floor of 3.3 mm), or a pocket that comes within the minimum wall of the edge of the foot's bottom.

**The engine states no pull force and no holding force**, and which way a magnet faces is yours: it builds both
pockets the same size at the same place.

## Does it stack: `check-stack`

```bash
zcad-validation stack check-stack --upper my-stack.json:parts-bin --lower my-stack.json:base
```

It reads two items, from the same stack file or two, and says whether the upper stacks on the lower, or why not,
with every reason at once:

- they are built to **the same profile**, by its hash;
- a **bin** goes on a **baseplate** whose cells cover its own, or on a bin with **the same cells**; a baseplate goes
  on nothing;
- on a baseplate they **agree on what holds them**: the same magnet, the same fastener, or both the lip alone. A
  bin that holds by magnet on a plain baseplate is refused, and so is a magnet bin on a bolt baseplate; and
- laid together as real solids, with the upper's first cell over the lower's, they **do not overlap**.

A bin on a bin is held by the lip alone. If either has pockets in its foot they meet nothing there, and the check
says so as a warning. It also reports the height of the stack.

## What is checked

Each item is one solid. **A bin is laid against real solids**: it sits in a baseplate of its own size with no
overlap, and a second bin like it stacks on its walls' tops with no overlap. Both are measured, not assumed, so a
profile whose sections nest on paper but not in solid fails the build.

**The engine states no load rating, no stable height for a stack, and no compatibility with any other maker's
parts.** It says a part was built to the profile in the file named by its hash. Whether it sits on a bought
baseplate is a reading for a trial, which comes with the build record in a later release.

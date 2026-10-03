# Stackable items

A **stack profile** says how an item's top and bottom faces meet another's. Bins and
baseplates built on one profile sit on each other, and a bin stacks on a bin like it. This
release builds bins, baseplates, caps, and drawer frames with their drawers, holds them with magnets
or bolts, puts the enclosures on the grid, stacks plates and spacers over boards, checks whether
two items stack, and keeps a record and trials of a print. Bins, frames, baseplates and caps can also snap together with
printed latches, and a drawer can click shut (see the [stackable items design](../roadmaps/stackable-items.md) and the
[latch design](../roadmaps/stackable-latches.md)).

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
| `cap` | `cells`, optional `floor_mm` (1.2), the thickness of its flat top. |
| `frame` | `cells`, `units` high, `drawers` (1 to 8), optional `wall_mm`, `floor_mm`, `holding`. |
| `drawer` | `frame`, the name of a frame in the same file; optional `wall_mm`, `floor_mm`, `pull` (true). |

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

## Caps, frames and drawers

A **tray** is a bin that is not very tall, and a bin does not need another kind for that: a two-unit bin has 8 mm
inside. What a tray adds is a lid, and a drawer is what a frame adds.

- **A cap** is a flat lid on the profile's foot. It sits in the lip of a bin or a frame of the same cells, the way a
  bin does, and nothing stacks on it. It is held by the lip alone unless it has a latch (see *Latches*): then it snaps into keepers cut in the lip below.
- **A frame** is a bin with its front wall taken out, a roof, and a pair of ledges up the inside of its side walls
  for each of its `drawers`. It has the foot and the lip, so it stands on a baseplate and takes a bin or a cap on top.
  It can hold by magnet or bolt in its foot, like a bin.
- **A drawer** is a tray that slides along a slot's ledges, its front flush with the frame's front, with a half-round
  finger pull in its front wall. The drawer is as wide as the frame inside less the printer's sliding clearance each
  side (0.2 mm on the A1 mini), and stops short of the back wall by the same. **It is held by nothing, unless it has a detent (see *A drawer that clicks shut*): it comes out
  when pulled.**

A frame is refused, with the figures, if its drawers would be too shallow to hold anything (under 3 mm inside), or if
it is too narrow for ledges and a drawer. The ledge (3 mm in, 1.6 mm thick), the roof (1.6 mm), the air above a
drawer (0.6 mm) and the pull (a 6 mm radius at most) are the engine's own design choices, not figures from the
profile.

**The build lays real solids.** A frame and a cap are one solid each. A cap sits on a bin of its cells with no
overlap. And a drawer is put in every slot of its frame, shut and pulled out by half and nine tenths of its length, and
must touch the frame nowhere, so a drawer that is too tall for its slot fails the build.

## Enclosures on the grid

```bash
zcad-validation enclosure build --board raspberry_pi_pico_2 --mount stack \
  --stack-profile my-profile.json --output-directory exports/pico-on-grid
zcad-validation enclosure-group build --bays pi5 --mount stack \
  --stack-profile my-profile.json --output-directory exports/pi5-on-grid
```

`--mount stack` is one more mount, with the four pads under the floor that the others use. The plate is a **stack
plate**: a flat plate on the profile's foot, in whole cells, that bolts to the pads and stands on a baseplate, or on a bin
or frame of the same cells, like any item on the profile. An enclosure built without it is unchanged.

- **The cells** are the least that cover the pads, rounded up (a Pico 2 takes 1 x 2, a Pi 5 group of one bay 3 x 3), and the
  plate is centred on the pads.
- **The screws come from below,** up through a foot. A recess in the foot's bottom sinks each head (the screw's diameter plus
  0.5 mm deep), and the foot above it, the plate and the insert's depth are the screw's reach, so the build prints a screw
  length. The recess must lie inside a foot's bottom with a millimetre round it: if a pad would land on a foot's edge the build
  tries one more cell across or deep, up to two, and refuses if none works.
- **The plate must fit the bed.** A stack plate bigger than the printer's bed is refused, saying how many cells it is and
  what the bed is: a Pi 5 pair is 176 mm wide and needs 5 cells, 210 mm, on a 180 mm bed. Build shorter units and bolt them together.

The build record names the plate under `stack`: the profile by path and hash, the cells, the plate's thickness and the screw's
reach. `check-stack` takes that record in place of `FILE:NAME`:

```bash
zcad-validation stack check-stack --upper exports/pico-on-grid/enclosure.json --lower my-stack.json:base
```

It checks it as it checks a bin: the profile by hash (a profile that has changed since the build is not trusted), the cells, the
holding (a stack plate holds by the lip alone) and the overlap of real solids. Nothing stacks on a stack plate.

### A stack top: things stacked on the box

A stack plate puts an enclosure on the grid. A **stack top** puts the grid on the enclosure: a baseplate, in whole cells that cover the lid, that sits on the lid and is held by the
lid's own screws. A lip cannot be cut into a lid, because a lip is whole cells and a lid is the size of the board.

```bash
zcad-validation enclosure build --board raspberry_pi_pico_2 --stack-top \
  --stack-profile my-profile.json --output-directory exports/pico-with-top
zcad-validation stack check-stack --upper my-stack.json:tub --lower exports/pico-with-top/enclosure.json:top
```

- **It is a baseplate.** Bins, frames and another enclosure's stack plate stand in its pockets as on any baseplate, and `check-stack` reads it as one: `RECORD:top` names it. It holds by the lip
  alone unless you ask for more (below).
- **The cells** are the least that cover the lid, and the build tries up to two more cells each way, smallest area first, until every lid screw's head recess lies inside a pocket's floor. A
  Pico 2 box takes 1 x 2 cells, 44.4 x 86.4 mm. The plate is centred on the lid and overhangs it where the cells are bigger, and it is refused, with its cells, if it is bigger than the printer's bed.
- **It is held by the lid's own screws, made longer.** Each goes down through a recess sunk in a pocket's floor, through the plate and the lid, into its insert. The recess is the head's diameter and a little
  more, and as deep as the head plus 0.5 mm; the plate's **floor is that and a millimetre under it**, 4.5 mm with an M3 head, so the plate is 8.85 mm tall on the example profile. The build prints the screw
  length: the millimetre, the lid and the insert's depth, 8 mm for an M3 on a 2 mm lid, where the lid's own are 6.
- **It needs a lid that is screwed shut and has no fan on it.** A snap, hinged or sliding lid is refused, as is a lid with a fan on it, whose frame stands above the lid. The plate would fix a lid that must
  open or stand on the fan, and the build names each reason it finds. A lid's openings are not a reason: the plate leaves a window over each (below).
- **A group enclosure takes one too:** `enclosure-group build --stack-top --stack-profile my-profile.json`, on a screwed lid, with the same refusals. The group's lid is 3 mm, so its screws reach 9 mm and an M3 is
  8 mm. A one-bay Pi 5 row takes 3 x 3 cells, with a window over its fan slots; a row wider than the bed is refused, with its cells.
- **The engine states no load rating:** it does not say what the lid carries or whether the plate flexes under a bin. The record's `stack_top` names the plate, its profile by hash, its cells, its floor
  and the screws.

**Vent windows.** A lid's openings (the outlets from `--vent-area-mm2`, the slots over a Pi's fan or a board part, a display's window) are found from the built lid: what it has cut away from a plain lid,
right through its thickness, joined where the pieces are within 4 mm. The plate leaves a **window** over each, the opening and 2 mm more each way, cut through it.

- **A vent cell has no pocket.** A pocket cannot sit over a window, so each cell a window touches is a **vent cell**: solid, with the window through it and no pocket for a foot. The record names them
  (`vent_cells`, `vent_windows_mm`) and the cells that are left (`cells_usable`). A bin that would stand over one is refused by `check-stack`, which names the vent cells.
- **A lid screw cannot be in a vent cell,** since its head's recess is cut down into a pocket floor and a vent cell has none. The cells are searched as before, up to two more each way, for a plate whose screws are
  all in cells with no window, and **with windows the plate may be shifted off the lid's centre**, by whole millimetres, as far as it still covers the lid, least first. A window off the middle of the lid is met by a
  shift (a window 20 mm left of centre and screws 34 mm out take a plate shifted 5 mm); `offset_mm` in the record says how far. It is refused if no cells and no shift put every screw in a cell with no window.
  **A small box often fails this:** a Pico 2 box with a 300 mm2 outlet has an outlet that nearly fills its lid, 20 x 50 mm, and every cell a window could take has a screw in it, so the build refuses and says it tried
  shifting. A smaller outlet needs no shift there. The one-bay Pi 5 row has screws at the ends and its fan slots in the middle, and gets a window over two of nine cells.
- **Several windows:** the lid's openings may make up to four windows, and more is refused as too scattered for a plate to leave open. A lid with a fan on it is still refused.
- **The engine says nothing about air.** The window leaves the outlet open as geometry. It does not say the box runs cool under a top, and the thermal estimate does not model one: a trial's temperature is where
  that shows. A top with windows asks one more check, `stack_top_vents_open`.

**Holding a bin on a top.** Two options, on `enclosure build` and `enclosure-group build`:

```bash
zcad-validation enclosure build --board raspberry_pi_pico_2 --stack-top --stack-profile my-profile.json \
  --stack-top-holding magnet --stack-top-magnet D6X2 --stack-top-latch front,back \
  --output-directory exports/pico-with-held-top
```

- **Magnets** (`--stack-top-holding magnet --stack-top-magnet NAME`): a pocket sunk into each cell's pocket floor at the profile's holding points, for a bin built with the same magnet. The floor is
  4.5 mm, so a pocket leaves a minimum floor under it. **A bolt is not offered:** it would go through the lid, which is closed.
- **Latches** (`--stack-top-latch front,back`, with `--stack-top-engagement-mm` if you want one): a keeper in each cell's pocket wall on the named sides, for a latched bin or frame, built as a baseplate's are.
- **Where a screw meets a magnet.** The lid's screws sit in the corners, as the grid's holding points do, and a screw's head recess and a magnet pocket cannot share a floor. **A pocket is left out of any
  holding point within a wall of a recess**, and the record names the points kept (`magnet_points`) and those left out (`magnet_points_left_out`). On the Pico 2 box's 1 x 2 plate four of the eight points are left out,
  so each cell keeps its two inner magnets; the build refuses only if no point is left. A bin has all four magnets, so a top holds with fewer than the bin carries.
- `check-stack` holds a bin to what the top carries: it must agree on the magnet and have a latch on every side the top has keepers for, or the hooks would strike the pocket wall.

**Trying a print.** A build with a stack top adds two checks to the enclosure's or the group's trial, `stack_top_sits_flat` and `stack_top_screws_reach`, and six sizes to measure (the plate's width,
depth and thickness, its floor, and the screw recess's depth and diameter). `trial start` also writes `stack_top.json`, with what was designed beside blanks:

- **`gap_under_plate_mm`:** the gap a feeler gauge finds between the plate and the lid at the worst corner with the screws in.
- **`screws_pass_all_holes`** and **`screw_length_mm`:** whether a screw goes through plate, lid and insert at every corner, and the length you used, kept beside the recommended one.
- **A bin stacked on it:** its **`bin_wobble_mm`** by feeler gauge, the **`separation_force_n`** a spring scale reads lifting it off, and a **count of stackings** with whether anything wore. Wear needs the count.

Each is left blank if not taken, and any one reading is enough to complete a trial. **The engine states no limit and no load rating for any reading.** A blank `stack_top.json` is left out of the record.
A top that holds by magnets or latches also asks `stack_top_holds`, and the template names what it was designed to hold by.

## Electronics layers

A **layer** stacks over a board, as a hat does. It adopts the board's own mounting holes, not the grid's, so
it lives in its own file and has its own commands.

```bash
zcad-validation stack layer template --board-file my-board.json --output my-layer.json
# say what it is for, then:
zcad-validation stack check my-layer.json
zcad-validation stack layer build --layer-file my-layer.json --output-directory exports/my-layer
zcad-validation stack check-layers --upper hat-layer.json --lower my-layer.json
```

A layer file names a [board file](board-file.md) by hash, as a housing does, and sets `fastener` (a catalogued one, such as
M2.5), `clearance_mm` (the air over the board's tallest part, 1.0), `spacer_mm` (optional: the least is worked out),
`plate_mm` (2.0) and `wall_mm` (the spacer's wall, 1.2).

`layer build` makes two parts:

- **A spacer**, a tube round the fastener. Its height is the board's tallest top above its face (a part, the cable
  connector, or the board file's `envelope`) plus the air, rounded up to 0.5 mm. Print one for each mounting hole.
- **A plate** the shape of the board's outline, over the spacers, with a hole at each mounting hole. It is opened over each
  part the board file marks `access_edge`, and over the cable connector, from the part out to its edge, and has a window
  over a part marked `lid_vent`.

The layer is refused, with the figures, when the spacer is under the height needed (say how tall the part is), when the
fastener will not pass the board's holes, when a spacer would stand on a part (it is under 0.3 mm from it), when an
opening would come within the printer's minimum wall of a hole, or when the wall or plate is under the printer's
minimums. The build also lays the spacers and the plate against the board's parts as solids and fails if they touch.

`layer build` also writes `layer-build.json`: the layer file and the board by hash, the settings as built, the spacer's height and the
holes, each part's STL hash, and the checks and dimensions a trial asks. `check-layers` takes a record in place of a layer file, and does not trust
one whose board has changed since the build.

`check-layers` says whether two layers stack: **their holes must be the same pattern** to within 0.1 mm, since one bolt
passes through both boards, and they must use the same fastener. It reports the worst offset and the height of the lower layer.

A layer's trial records one print fitted to a real board:

```bash
zcad-validation stack layer trial start --build-record exports/my-layer/layer-build.json
# print it, fit it to the board; fill in observations.json, measurements.json and fitting.json
zcad-validation stack layer trial complete --trial-directory exports/my-layer/trials/trial-001 \
  --disposition pass
```

The checks are that it printed cleanly, the spacers stand flat, the plate seats with a screw through every hole, the openings line up, and the
plate clears the tallest part. `fitting.json` takes the **air** a feeler gauge finds over the tallest part (set beside the air designed), whether
the **bolts pass** every hole, and a **count of assemblies** with whether anything wore. The engine states no limit for any of them, and nothing about
a board's function. A completed trial checks the parts by hash and is never overwritten.

**The engine places a plate and spacers.** It makes no electrical connection, and states nothing about a header's alignment
or what it carries. The air over a part, the margin round an opening and the spacer's wall are the engine's own choices.

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
- a **bin** or **frame** goes on a **baseplate** whose cells cover its own, or on a bin or frame with **the same
  cells**; a **cap** goes on a bin or frame with the same cells; a baseplate goes on nothing, nothing goes on a cap or a
  drawer, and a drawer slides into a frame instead;
- on a baseplate they **agree on what holds them**: the same magnet, the same fastener, or both the lip alone. A
  bin that holds by magnet on a plain baseplate is refused, and so is a magnet bin on a bolt baseplate; and
- laid together as real solids, with the upper's first cell over the lower's, they **do not overlap**.

A bin on a bin is held by the lip alone. If either has pockets in its foot they meet nothing there, and the check
says so as a warning. It also reports the height of the stack.

## The build record and stacking trials

`stack build` writes `stack-build.json` beside the parts: the stack file and the profile by hash, with the profile's
identifier and pitch, each item as built (its settings, what the build said of it, and its part's STL hash), the checks a trial
asks, the dimensions it measures, and what the engine does not claim. It refuses to replace one.

```bash
zcad-validation stack trial start --build-record exports/my-stack/stack-build.json
# print, stack and try it; fill in observations.json, measurements.json and stacking.json
zcad-validation stack trial complete --trial-directory exports/my-stack/trials/trial-001 \
  --disposition pass
```

The checks follow each item's kind: every item is printed cleanly; a bin or frame sits flat and stacks square; a baseplate's pockets are
clean; a cap sits on its bin; a drawer slides free (and a frame's drawers slide); a magnet seats; a screw reaches its insert.
Measurements are each item's width, depth and height as built.

`stacking.json` holds four kinds of reading, each left blank if not taken:

- **Wobble:** the gap a feeler gauge finds at a corner when the item is pressed down at the opposite side.
- **Separation force:** the highest force a spring scale reads pulling it off what it sits on.
- **A count of stackings,** and whether anything wore or cracked. Wear needs the count.
- **Other makers' parts:** a baseplate or bin of another maker you tried it on, and whether it sat.

**Latches and detents** add a file, `latch.json`, when an item has them, and checks for each: `latch_clicks` for an item with hooks (a bin, frame or cap), `keepers_clean` for one with
keepers (a baseplate, bin or frame), `detent_clicks` for a drawer's bumps and `dimples_clean` for a frame's dimples. The build record's sizes to measure grow too: each hook's
and bump's stand-out, and each keeper's and dimple's depth, from the solids as built. `latch.json` has an entry for each item that carries hooks and each drawer with a detent,
with the designed figures beside the blanks:

- **A hooked item:** whether it **clicked on** and **clicked off**, the **separation force** by spring scale pulling it off, and a **count of snaps** with whether anything wore.
- **A drawer:** whether it **clicked shut** and **clicked open**, the **pull force** to take it out of its dimples, and the same count.
- **A drawer with a stop** has four readings more: whether it **stopped** when pulled out, the **stop force** a spring scale reads pulling against the stop before you squeeze, whether squeezing both
  bumps in through the windows **released** it, and whether it then **went back** in past the windows and clicked shut. Its checks are `stop_holds` and `stop_releases`, and its frame's is
  `windows_clean`. The sizes to measure add how far the drawer stops out (`<drawer>_stop_travel_mm`) and each window's length and height (`<frame>_window_length_mm`, `<frame>_window_height_mm`).

**The engine states no limit for any reading, and states no holding force.** It records the force and the count and sets each beside what was designed.

**The engine states no limit for any reading, and claims no compatibility from one.** A trial that records a part sitting on another maker's
baseplate is a reading, nothing more. A completed trial checks the printed parts still match the record by hash, is never overwritten, and a
passing one cannot have a failed check.

`check-stack` reads a build record too: `--upper stack-build.json:tub --lower stack-build.json:base`, with the profile the record names, checked
against its hash.

## What is checked

Each item is one solid. **A bin is laid against real solids**: it sits in a baseplate of its own size with no
overlap, and a second bin like it stacks on its walls' tops with no overlap. Both are measured, not assumed, so a
profile whose sections nest on paper but not in solid fails the build.

**The engine states no load rating, no stable height for a stack, and no compatibility with any other maker's
parts.** It says a part was built to the profile in the file named by its hash. Whether it sits on a bought
baseplate is a reading for a trial, which comes with the build record in a later release.

## Latches

A **latch** is a printed snap between a foot and a lip: a hook on the side of the upper item's foot, caught in a recess, the **keeper**, cut
into the lip of the item below. It is a detent, not a lock: it resists being pulled apart and lets go to a pull. **The engine states no holding
force**, and a stack that must not come apart is bolted.

```json
{"kind": "bin", "name": "box", "cells": [2, 1], "units": 3, "latch": {"sides": ["front", "back"]}},
{"kind": "baseplate", "name": "plate", "cells": [2, 1], "latch": {"sides": ["front", "back"]}}
```

`latch` goes on a bin, a frame, a baseplate or a cap, and takes `sides` from `front` (-Y), `back` (+Y), `left` (-X) and `right` (+X), defaulting to front and back, and an optional `engagement_mm`. It is
a field of its own, so an item can hold by magnets and latch too.

| Item | What `latch` builds |
| --- | --- |
| `bin`, `frame` | On each cell's foot along each named side, a hook on a tongue, and in its own lip a keeper at the same place, so it takes the item above and holds to the one below. |
| `baseplate` | A keeper in the pocket wall of every cell on each named side. |
| `cap` | A tongue and hook on each cell's foot along each named side, and no keeper, because nothing stacks on a cap. A cap snaps into the keepers of the bin or frame below. |

**A hook that meets no keeper strikes the lip or the pocket wall.** A latched bin or frame stacks only on an item with keepers on the same sides and the same
engagement, and `check-stack` says which side is missing. An item with keepers and nothing hooked to them only warns.

**The tongue** is a strip of the foot's skin, 1.2 mm thick (the printer's minimum wall), freed by a relief pocket cut up into the solid foot from its bottom, and
bending outward along the side as the slide lid's detent does. Its reach is the least, to the next half millimetre, that keeps its strain under the provisional
1.5 per cent limit: 7 mm for the default 0.4 mm engagement. The build reports the strain, and refuses a cell side too short for the reach it needs. A tongue is refused
near a magnet or bolt pocket.

**The hook** is 6 mm wide and stands out of the foot by the gap across the wall (0.25 mm on the example profile) plus the engagement, with a 45 degree ramp each side. **The
keeper** is the hook's shape grown by the printer's sliding clearance, cut into the lip's face. These sizes, the slit (0.8 mm) and the flat on a hook's tip (0.4 mm)
are the engine's own choices, provisional until a trial.

**What the profile allows.** The engine finds a vertical run of the foot's face and of the lip's face that overlap in height (0.8 to 2.5 mm on the example profile), and
refuses a profile with under 1.5 mm. The engagement is held by two limits from the profile:

- the hook's ramps take twice its protrusion from the vertical run, leaving a flat of at least 0.4 mm: **at most 0.4 mm** on the example profile;
- the lip behind a keeper stays at least the printer's minimum wall: at most 0.5 mm on the example profile.

The default engagement is 0.4 mm. A profile can state its own, with a source, once a trial has settled it:

```json
"latch": {"engagement_mm": 0.35, "source": "trial of 12 snaps on the A1 mini, PETG"}
```

A source is needed and an `EXAMPLE` one is refused. A profile with a thicker lip or a taller vertical run, an edit to its sections, allows more.

**The build lays real solids.** Each latched bin or frame gets four checks on top of the stack's own: each tongue's skin is solid and its relief void; each keeper's mouth
is void with the lip solid behind it; a hook seated in the lip overlaps what a plain lip would be, so it does engage; and a hook deflected by its tongue's travel passes
the plain lip at every height from the lip's top down, so it goes on and comes off. The item laid on itself, and on a baseplate with keepers, has no overlap. The record
carries each item's latch figures.

## A drawer that clicks shut

A drawer is held by nothing: it comes out when pulled. A **detent** gives it a closed position. Near the back of each side wall of the drawer a **tongue** is cut free of the
wall with a **bump** on its outer face, and the frame's side wall has a **dimple** where the bump sits when the drawer is shut. Pushed shut, the drawer clicks into the dimple;
pulled, it clicks out. **It does not stop the drawer coming out the front, and the engine states no holding force.**

```json
{"kind": "frame", "name": "chest", "cells": [1, 1], "units": 4, "drawers": 2, "wall_mm": 1.8, "detent": {}},
{"kind": "drawer", "name": "tray", "frame": "chest", "detent": {}}
```

`detent` goes on a frame and on the drawers that click into it, and takes an optional `engagement_mm` (0.4 by default, 0.3 to 1.5). The frame has dimples in every slot, and a drawer with
bumps is refused if its frame has none or is cut for another engagement. A frame with a detent and a drawer without one is fine: the drawer just slides.

- **The tongue** is a strip of the drawer's side wall along its length, 4.5 mm tall down from the rim, freed by a 0.8 mm slit under it and a 0.8 mm slit at its free end, and fixed at the
  back. It bends in the wall's thickness, so its thickness is the drawer's `wall_mm`, and its reach is the least, to the next half millimetre, that keeps the strain under the provisional
  1.5 per cent limit with the bump pushed in by the engagement: 7 mm for a 1.2 mm wall and 0.4 mm. The drawer must be at least 5.3 mm deep inside for it, and the inside face of the
  tongue must be left clear.
- **The bump** is 3 mm tall and 1.6 mm along the wall at its base, with a 45 degree ramp each way, and stands out of the drawer by the sliding clearance plus the engagement. **The dimple** is the bump's
  shape grown by the sliding clearance, cut into the frame's wall past its face.
- **The frame's wall** must stay the printer's minimum wall behind a dimple: the dimple is the engagement plus the clearance deep, 0.6 mm by default, so **`wall_mm` must be at least 1.8 mm**
  with a 1.2 mm minimum, and the build says so. This is why the example sets `wall_mm`.
- **Where.** The bump is 14 mm from the back of the drawer and 2 mm below its rim, laid out from the frame's own sizes, so a frame and the drawers that go in it agree on the dimple whatever
  the drawer's own wall and floor. A drawer wall over 4 mm, whose tongue would end against the back wall, is refused.

**The build lays real solids.** Each frame gets `detent_dimples_open`: every dimple's mouth is void with the wall solid behind it, at every slot. Each drawer gets `detent_tongues_freed` (the
tongue's wall is solid and both slits are void), `detent_clicks_in` (a bump in its dimple overlaps what the frame's plain wall would be, so it does engage) and `detent_passes` (a bump pushed in by
the engagement passes the plain wall along nine tenths of the drawer's length). `slides_in_<frame>` still holds the drawer clear of the frame shut and at half and nine tenths out, with the
bumps pushed in once it is out of the dimple. These sizes are the engine's own choices, provisional until a trial.

### A stop that keeps the drawer in

```json
{"kind": "frame", "name": "chest", "cells": [1, 1], "units": 4, "drawers": 2, "wall_mm": 1.8, "detent": {}, "stop": {}},
{"kind": "drawer", "name": "tray", "frame": "chest", "detent": {}, "stop": {}}
```

`stop` on a frame and on a drawer, each with its `detent`, keeps the drawer in the frame when it is pulled out. The bump's front face is vertical, and the frame has a **window** through each
side wall at every slot, where the bump sits when the drawer is pulled out; the window's front edge is a vertical wall, so the bump catches on it. **To take the drawer out, squeeze:** push both
bumps in through the windows, with a pin or a fingernail, on both sides at once, and pull. **To put it back,** push the rear in: the bump's rear face is a 45 degree ramp, so it rides over the frame's
front edge and drops into the window, and a push shuts the drawer, clicking into its dimple. The dimple has a ramped front wall for a stop, so the drawer still clicks out of its closed position.

- **The stop lets the drawer out 21.5 mm of its 40 mm, 54 per cent,** with the example profile: the window's front edge is 3 mm back from the frame's front. A stop must let it out between a fifth and
  two thirds of its length, and is refused outside that. A drawer stopped there still has more than half of its length inside the frame.
- **The window** is 5.6 mm along the wall and 4.2 mm tall, so a pin 2 mm across reaches the bump. Slots must leave the printer's minimum wall between windows.
- **A drawer with a stop needs a frame with one,** at the same engagement. A frame with windows and a drawer with only a detent is fine: the drawer comes out as it did.
- **Checks on the real solids:** `stop_holds` (pulled the stop's travel, the bump sits in its window, and a millimetre more strikes the window's front wall), `stop_releases` (a bump pushed in by the
  engagement passes the whole travel of the frame with its dimples and windows), and the frame's `stop_windows_open`. The engine states no holding force: it stops a pull and a squeeze lets it go.

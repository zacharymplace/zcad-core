# Modular bays

## Purpose

The Pi 5 group enclosure is one base and one lid around a row of bays, with a lid
that screws, hinges or slides, dividers, vents, mounts, and units that bolt
together. Everything but the bay itself is generic over the row. The bay is
hard-wired to one board: the slot is a Pi 5's width, the service gap is the 25 mm
a Pi's USB-C and micro-HDMI plugs need to its right, the ports face the back and
front walls, and the standoffs, the fit envelope and the lid's fan slots are all
a Pi's. The only alternatives are `reserved`, a Pi bay with no Pi fitted, and
`open`, a flat shelf whose openings you place by hand.

A modular bay makes the bay a module described by data, so a row can mix a Pi 5,
any board from a board file, a fan, and a shelf, in one box under one lid; and it
makes a unit (a box of one or more bays) something that bolts to another unit of
a different size and can be swapped without reprinting its neighbours. This is
the design for both.

This is a design, not built work. Nothing below exists in the code yet.

## What the engine already has

| Need | Where it is today |
| --- | --- |
| A board that is not a Raspberry Pi: outline, mounting holes, components with the edge they are reached from, a power figure | The board file (`hardware/electronics/board_file.py`), its checks, the catalog loader and `needs_review`; see [A board file](../guides/board-file.md) |
| A pocket that follows a polygon, for a board with no mounting holes | `board_cradle`, with polygon outlines |
| A row of bays with heights, openings, dividers and vents per bay | `enclosure_group_layout`, `enclosure_group_dividers`, `enclosure_group_openings` |
| A hinged or sliding lid over the row, swept against the hardware | `enclosure_group._attach_lid`, `lid_hinge`, `lid_slide` |
| Units that bolt together through their end walls | `enclosure_group._add_join_features`: two heat-set bosses on a left wall, two clearance holes on a right wall, `--no-join-bolts` |
| A temperature estimate from each board's draw | `enclosure_thermal.estimate_thermal`, which takes catalog identifiers, and a board file's `power` section |
| A build record and trials | `enclosure_trial` and `guide_trial`, for the single-board enclosure and the guide; the group has neither |

## Decision: a bay is a module, described by data

What the group builder reads from a Pi, it should read from a module record, with
the Pi 5 as the first one. A module is:

- a **footprint**: the slot's width and depth, and the service space on each side
  along the row;
- the **supports**: standoff positions and the screw they take, or a cradle;
- the **parts**: the board's envelope and each part's box, for the fit checks;
- the **openings** it needs through the front and back walls, each with the plug it
  takes;
- its **heat**: a power figure with its source, or none;
- its **headroom** above the board, as today.

`pi5` and `reserved` stay as bay kinds and build exactly what they build now; this
is a refactor of their code onto the module record, checked by their existing
tests and by comparing the volumes and bounding boxes of today's builds with the
refactored ones. `open` stays. New kinds are:

| Bay | Builds |
| --- | --- |
| `board:FILE` | Any board a board file describes: its slot, its standoffs or a cradle, its openings from its connectors, its envelope. Refused if the file is `needs_review`. |
| `fan` | A bay for a fan from the fan catalog: its frame, its guarded opening, and a duct to the board beside it, with the figures marked as provisional as they are today. |

A board bay's file is named in the bay token, `board:path/to/board.json`, with the
same per-bay settings a Pi bay has (`standoff=`, `headroom=`, `divider=`), and in
Python `Bay("board", board=load_board(path))`.

## Decision: how a board fits the row

The row runs along X and is one box deep in Y. A Pi sits portrait with its ports
at the back and the front and its header toward the previous bay. A general board
needs three rules to sit in that frame, and each can fail, so each is a check:

1. **Orientation.** A board is turned in 90 degree steps so that its longer side
   runs along Y, as a Pi's does, unless the bay says `rotate=0|90|180|270`. The
   board's connectors then fall on four faces: the front and back walls, and the
   left and right sides, which face the neighbouring bays.
2. **The service space.** A connector facing a neighbour needs the room a plug
   needs, and its cable leaves the box through an opening at the end of that space
   on the front wall, as a Pi's USB-C and micro-HDMI do. The space is sized from
   the connector's plug allowance (`cable_plug_*` in the design, the same figures
   the single-board enclosure uses), not from a Pi. A board with connectors on
   both sides takes a space on each; the first bay's left space is the end margin
   and the last bay's right space runs to the end wall.
3. **Depth.** The row is as deep as its deepest bay needs. A shallower board sits
   against the back wall by default (`align=front|center|back`), because the back
   wall is where most ports are. A connector on a wall whose board edge is more
   than a stated reach from it (4 mm) cannot be opened through that wall and is
   refused, with the board's own edge distance in the message: the opening would
   show an empty cavity. The answer is `align=` the other way, a deeper row, or a
   cable.

The ends of the row stay the join walls, so a connector facing an end wall of a
unit is refused too: put the board in the middle, or turn it.

## Decision: units that join, and that swap

Today a row too wide for the bed is built as two units, each a copy of the same
box, whose left wall's two bosses meet the next unit's right wall's two holes at
fixed fractions of the depth. That works only for equal depths. Making units
swappable means a **standard joint face**:

- the bolt positions are measured from the front wall's outer face and the floor's
  underside, not as fractions of the depth, so two units of different depth meet
  on the range they share;
- the bolts, bosses and holes are the same screw and the same positions in every
  unit, so any unit's left wall meets any other's right;
- an optional **pass-through**, one rectangular opening in the join walls at a set
  height and offset, lets a cable run from one unit to the next; and
- a unit's height is its own: the lids are separate, so units of different height
  need no match.

`enclosure-group check-join A B` builds both, puts B against A's right wall, and
checks that each boss is coaxial with a hole, the walls meet without gap or
overlap over the shared depth, and a pass-through, if both have one, lines up. It
exits 1 if the pair cannot bolt. A unit built before this change keeps its
fraction-based bolts and is reported as not on the standard face, since a
unit's old and new joint cannot be told to mate by looking.

## Decision: heat per module, from the board's own figure

The temperature estimate counts each fitted Pi from a catalog. A board bay takes
its draw from the board file's `power` section, which already carries typical and
peak watts and where they came from, and the estimate adds them. A board file with
no `power` section contributes nothing and the estimate says so, as it does for an
unknown board in a single-board enclosure: it states a figure only for what it was
given. The fan bay's effect on the estimate is the single-board fan's, with the fan
catalog's provisional status carried through.

## Checks

- **Module checks, as for a Pi.** Every board's envelope clears the base and the lid;
  every extracted part clears them; no standoff meets a part under the board; the
  lid meets no board.
- **Row rules.** Orientation, service space, depth, and wall reach, each refusing
  with the numbers.
- **Lid motion over a mixed row.** The hinge and the slide sweep against every
  module's envelope, as they sweep a Pi's. A fan bay's frame is part of the sweep.
- **Joint face.** `check-join`, as above, and a build that reports whether its
  unit is on the standard face.
- **Bed.** A unit that does not fit the bed is refused, naming where to cut the row.

## Phases

1. **Bay modules and board bays.** The module record, `pi5`, `reserved` and `open`
   moved onto it with their builds unchanged, and `board:FILE` bays: slot,
   standoffs or cradle, openings and envelope from the board file, with orientation
   and alignment. A row of a Pi and a board file builds and passes its checks.
2. **Row rules for mixed boards.** Service spaces from connectors on the side
   faces, the depth and wall-reach checks, and what the lid's bosses, dividers,
   vents and fan slots do round modules of different size.
3. **Heat and fans.** The per-board power figure in the estimate and the `fan`
   bay, with the fan's figures still provisional.
4. **Joinable units.** The standard joint face, the pass-through, and
   `check-join`.
5. **The group's build record and trials.** `enclosure-group.json`, with each bay's
   kind, the board file's hash, the module's placement, and the printed parts'
   hashes; `enclosure-group trial start|complete` in the enclosure trials' style,
   with per-bay checks and, for a pair of units, a reading of the gap measured at
   the joint; and the lid readings the single-board enclosure's hinged and sliding
   lids take. This also gives the Pi 5 group the build record its trials have
   been waiting for.

Each phase is one PR. Phases 1 and 4 add bay kinds and a joint face, so every
existing group build keeps its output unless a design asks for the new ones.

## Not covered

- **Stepped floors.** A row has one floor and one lid height; a low bay beside a
  tall one wastes the room above it. A stepped floor needs a stepped lid and is
  its own design.
- **Hot-swapping electrically.** A unit swaps mechanically; its wiring is the
  user's.
- **Stacking units in Z.** Units join along the row, not on top of one another.
- **A board with no board file.** The STEP import and `board promote` make a board
  file from a model; a bay does not read a model directly.
- **Catalogued modules other than boards and fans.** A shelf with openings stays
  the answer for an SSD or a switch until one is worth a module of its own.

## Open questions

- **How a board's connectors give their plug allowance.** The single-board
  enclosure derives it from a connector's type; the board file gives a part's size
  and its access edge but not what plugs into it. The proposal is a default per
  connector kind with the design's `plug_margin_mm`, and a per-part override in the
  board file's component, marked as the user's.
- **Where a cradle bay's clips go.** The cradle's clips hold a board by its edges,
  which sit against the neighbouring bay's divider or service space. The proposal
  is to refuse a cradle bay whose clip would meet a divider, and tell the user to
  move the divider or use standoffs.
- **Whether a unit's joint face can retrofit.** A unit built before the standard
  face has fraction-based bolts. The proposal is not to retrofit: rebuild the unit,
  since a build is one command.

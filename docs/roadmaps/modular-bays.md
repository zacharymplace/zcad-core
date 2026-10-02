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

All five phases are built; each section of *Phases* and the *What phase N
changed* notes below say where the build departed from the design.

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

1. **Bay modules and board bays (built).** The module record, `pi5`, `reserved` and `open`
   moved onto it with their builds unchanged, and `board:FILE` bays: slot,
   standoffs or cradle, openings and envelope from the board file, with orientation
   and alignment. A row of a Pi and a board file builds and passes its checks.
2. **Row rules for mixed boards (built).** Service spaces from connectors on the
   side faces, the cradle bay, the lid vents over a board's parts, and what the
   lid's bosses and dividers do round modules of different size. (The depth and
   wall-reach checks came with phase 1.)
3. **Heat and fans (built).** The per-board power figure in the estimate and the
   `fan` bay, with the fan's figures still provisional.
4. **Joinable units (built).** The standard joint face, the pass-through, and
   `check-join`.
5. **The group's build record and trials (built).** `enclosure-group.json`, with each bay's
   kind, the board file's hash, the module's placement, and the printed parts'
   hashes; `enclosure-group trial start|complete` in the enclosure trials' style,
   with per-bay checks and, for a pair of units, a reading of the gap measured at
   the joint; and the lid readings the single-board enclosure's hinged and sliding
   lids take. This also gives the Pi 5 group the build record its trials have
   been waiting for.

### What phase 1 changed

- **The Pi's builds are unchanged, and that was measured.** `pi5`, `reserved` and
  `open` now read their slot, standoffs, envelope and parts from a module record.
  Ten builds (a pair, a lone Pi, reserved and open, per-bay heights, a divider, an
  open bay's openings, a hinged lid, a slide lid, a vent pattern, rack ears) were
  built before and after, and their base, lid and envelope volumes and bounding
  boxes, their checks, bay layouts and Pi centre agree exactly.
- **The Pi's openings, service gap and fan slots stay Pi code.** The design had the
  module carry its openings. A Pi's are its ports merged, its microSD card, and the
  cable exit along its gap, tied to the boss that closes the gap, and its fan slots
  are in the lid over its fan; making those generic would have changed a Pi bay's
  build for no gain here. The module record carries a board bay's openings, and
  the Pi's stay in `enclosure_group_openings` and `_lid`, to be generalised only
  when a second board needs the same.
- **Every opening source counts.** A board file names its connectors three ways: the
  cable connector every board has, `wall_openings`, and parts marked `access_edge`.
  All three become openings, and ones that overlap merge by the web rule.
- **Cradle bays are not built.** The design said "standoffs or a cradle". A board
  with no mounting holes is refused, saying so. The cradle's clips sit at the
  board's edges, against the neighbouring bay's divider or service space (an open
  question in the design), and the single-board cradle is built round one board in
  a box of its own; that interplay needs the row rules first.
- **A board's connector on a side is refused, not given a gap.** The service space
  that a connector facing a neighbour needs is the next phase's. Refusing it with
  the way round (`rotate=`) means no board is built with an opening that cannot
  reach.
- **Alignment is back by default for every bay.** For the deepest board, which is a
  Pi in every row there was before, back, front and centre are the same place.
- **The standoff height is the board's own.** A board bay takes the board file's
  recommended standoff, not the design's 4 mm, since the board file knows what is
  under it. It is still checked against the parts under the board.
- **Two design fields, `board_gap_mm` and `board_reach_mm`,** hold the gap right of
  a board bay and how far from a wall a connector can still be opened to it.
- **Heat is not counted yet.** The build's temperature estimate counts only the Pi
  bays, and says so when a board bay is present; that is phase 3.
- **`board_assembly` moved to `board_solids`,** a neutral module, so the group and
  the test fixture share it.

### What phase 2 changed

- **A side connector takes the design's service gap.** The design sized the space
  from the connector's plug allowance. The board file gives a connector's size and
  edge, not what plugs into it, and the open question on the plug allowance has no
  answer yet, so a connector facing a side takes `service_gap_mm`, the 25 mm a Pi's
  plugs take. A bay with a right-facing connector has that gap in place of
  `board_gap_mm`; a left-facing one has a space of that width before its slot. The
  cable leaves through a front-wall opening along the space, the pattern a Pi's
  gap has, and is refused if less than 6 mm is left.
- **The left space is the bay's own.** It is added before the slot rather than shared
  with the previous bay's gap, so a row with a Pi and a left-facing board has both
  spaces. That widens the row more than strictly needed, and is the simpler rule: a
  bay carries what it needs, whoever its neighbour is.
- **The cradle bay is built here.** The board's cable connector's wall is the edge
  the cradle leaves open; the board's outline, turned, is the cradle's. A cradle's
  clips stand outside the side edges where a divider stands, so the open question
  on clips and dividers is settled as proposed: a cradle bay takes none, and the
  error says to move the divider to the neighbouring bay. A cradle takes no screw.
- **Bosses and dividers needed nothing.** The lid's bosses sit in the corners and at
  the gap ends, and dividers stand at the end of a gap, so a bay of any size, a
  left space, or a board's depth leaves them where they were; tests build rows of
  mixed boards with dividers to show it.
- **Lid vents follow the part, not the Pi.** A part the board file marks `lid_vent`
  gets the five slots a Pi's fan does. The Pi's slots are cut as before.
- **A board with no parts listed crashed the build.** Probing a board file with no
  components (allowed, with a warning) raised a void bounding box from the part
  collision check. It is fixed: a bay with no parts has nothing to collide.
- **Pi builds are unchanged, measured again.** The ten builds of phase 1 compare
  equal after this change.

### What phase 3 changed

- **Boards, fans and Pis all count in the estimate, by what each is given.** A board
  bay's `power` section is the user's figure with the source they state; a fan's draw
  is the catalog's; a Pi is the catalog's idle figure as before. A board file with no
  `power` section is counted as unknown and listed under `missing`, so the estimate
  is a lower bound and says so. The phase 1 warning that board bays add no heat is
  gone, since they do now.
- **A fan bay is a fan in the lid, with no duct.** The design had the bay carry the
  fan's frame, its guarded opening, and a duct to the board beside it. The fan is
  built with the single-board fan bay's own planning and cutting (the frame flat
  against the lid's inside, a guarded round opening, four screw holes), on the
  group's cavity. A duct has to lead air from somewhere to somewhere, and a row has
  no air path to draw one along, so none is built; the guide says to add vents.
- **Fans are in the lid only.** The single-board fan can also stand in a long wall.
  A group's long walls carry the ports of every board, so a wall fan is left out
  until a row has a wall free for it.
- **The lid carries the fan.** A hinged lid sweeps it with the lid, a sliding lid
  refuses it by name (the slide's existing rule), and the review model moves it
  with the lid. `GroupEnclosure` gains `fans` and `lid_carried` for this.
- **The fan's figures stay provisional, and the build says so.** The catalog's three
  fans were read from search excerpts, not the makers' pages; the fan report and a
  build warning carry that. Verifying them was its own follow-on, which the thermal features roadmap records.
- **A closed box is one with nothing to move air.** Slots over a Pi's fan or a
  board's `lid_vent` part, a vent pattern, or a fan open the box, so the estimate's
  `closed` follows them.
- **Pi builds are unchanged, measured again.** The ten builds of phase 1 compare equal.

### What phase 4 changed

- **The standard face is opt-in, so nothing printed or built changes.** `GroupDesign`
  has `joint_face` (`fractions`, the default, or `standard`); the ten builds that
  phases 1 to 3 compared still compare equal.
- **The bolts are at 20 and 38 mm from the front, 10 mm up.** The design said fixed
  distances without choosing them. They are chosen so the bolts clear the lid's
  corner bosses and a pass-through fits between and above them, which makes the least
  unit 44.1 mm deep (52.8 mm with a screwed lid). A shallower unit is refused with
  the number; it can use the original face, which fits it. The design did not name
  this limit.
- **The pass-through is one size for both walls, and it goes through the ends too.**
  The design said one opening in the join walls. It is cut at 29 mm from the front
  and 16 mm up, above the bolts' bosses, in the left wall, the right, or both; the
  two ends of a row are join walls as well, so a pass-through there is open to the
  outside. A 6 mm tall one fits the lowest unit; a taller unit takes a taller one.
- **`check-join` reads geometry, not records.** The group has no build record until
  phase 5, so it takes the two units as `--left-bays` and `--right-bays`, builds them,
  and checks the pair: same screw, walls meeting, a screw passing each hole into each
  boss, a pass-through lining up. Reading geometry means it can tell that two
  original-face units of the same depth mate and that mixed depths do not, where the
  design said an old unit is reported as off the standard face and left at that;
  that note is still given.
- **Only the joint's own settings are shared.** `check-join` takes the wall, floor,
  fastener and lid as shared flags, and the joint face and pass-through per unit;
  heights and bays are the units' own, and no other design setting moves the joint.

### What phase 5 changed

- **A record, trials, and a check from records.** `enclosure-group build` writes
  `enclosure-group.json`; `enclosure-group trial start|complete` and
  `enclosure-group-trial.json` follow the single-board enclosure's trials, reusing its
  readers for the observations, measurements, temperature and lid. `check-join` takes
  `--left-record` and `--right-record` as well as bays.
- **The record check does not rebuild, so it checks less.** Only the bolts' positions,
  the screw, the joint face and the pass-through are in a record. The walls meeting
  and the screw's path need the geometry, so the record check says it did not check
  them; `check-join` from bays still does.
- **Checks are per bay, named by index.** The design said per-bay checks. Each is
  `bay-<n>-<check>` with its guidance by the bay's kind, so a row of mixed bays
  lists what each asks and nothing else: no seating check for a fan, no fan check for a
  board.
- **The joint is a reading, not a check.** A pair of units needs both printed and
  bolted for the gap to be read, so a trial of one unit cannot make it a pass or fail
  check. `joint_gap_mm` is an optional measurement, nominally zero.
- **Group trials are not pooled.** The enclosure's thermal and fit profiles pool its
  own trial records; the group's are a separate file and are not read by them. A
  group is almost never a closed box, which is what the thermal pooling requires.
- **The hinge and slide trials' open question is closed.** The lid readings of the
  hinges and slides roadmap's phase 4 now apply to the group too.

Each phase is one PR. Phases 1 and 4 add bay kinds and a joint face, so every
existing group build keeps its output unless a design asks for the new ones.

## Not covered

- **Stepped floors.** A row has one floor and one lid height; a low bay beside a
  tall one wastes the room above it. A stepped floor needs a stepped lid and is
  its own design.
- **Hot-swapping electrically.** A unit swaps mechanically; its wiring is the
  user's.
- **Stacking units in Z.** Units join along the row, not on top of one another; see
  [Stackable items](stackable-items.md).
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

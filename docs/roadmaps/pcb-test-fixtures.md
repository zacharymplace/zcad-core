# PCB test fixtures

## Purpose

A board you have built has to be tested: every test point reached, a program
loaded, a signal read. Doing it with probes held by hand is slow and loses a
point in every few. A test fixture holds the board by its outline, and presses
spring-loaded pins (pogo pins) onto its test points from a plate above, all at
once and in the same place every time.

The engine already holds a board as data: its outline as a polygon, its
mounting holes, its parts as boxes. This is the design for a fixture built from
that data, and for the one thing a fixture must get right that an enclosure never
had to: whether a pin lands on its pad.

It builds on the base set out in [Drill guides and fixtures](drill-guides.md): a
nest that follows a silhouette, a plate that carries bores, the release and
sweep checks, and a fixture that is unverified until a trial measures it. This
document covers only what a board adds.

This is a design, not built work. Nothing below exists in the code yet.

## What the engine already has

| Need | Where it is today |
| --- | --- |
| A board's outline, thickness, holes, and parts | board files (`load_board`), with polygon outlines |
| A nest that follows the outline, with a ledge and clips | `board_cradle._local_outline_cradle` |
| Locating by the board's mounting holes | `mounting_hole_positions_mm` and the standoff diameters |
| Part boxes above and below the board, for clearance | `components` on a board file, and `board import` from a STEP model |
| Hinge and catch, with a swept-swing check | `lid_hinge`, which the fixture's lid can reuse |
| A part with sourced figures, each marked read or unread | `hardware/fans.py` |
| Trials, and a pooled measured value that replaces an assumed one | `enclosure trial`, the thermal trials |

## Decision: test points are data on the board file

A board file gains an optional `test_points` list. It is the board's own
property, so it belongs in the file and not in a fixture's:

```json
"test_points": [
  {"identifier": "TP1", "x_mm": -8.0, "y_mm": 12.5, "pad_diameter_mm": 1.5, "side": "top", "net": "3V3"}
]
```

Positions are in the board's frame, as for holes. `side` is `top` or `bottom`.
`net` is the user's own label and is only carried through to the fixture's
report. The check refuses a point outside the outline, a pad diameter under
0.5 mm, and two points whose pads overlap.

`board import` cannot guess a test point, as it cannot guess a connector, so a
STEP import leaves `test_points` empty. Nothing is inferred from a model's
copper, which a STEP does not carry.

## Decision: a pin is a catalogued part, each figure with its source

A spring pin is a part with figures the engine must not invent. A `PogoSpec`
carries, like a fan, its maker, model, barrel and tip diameters, free length,
travel, the preload force at a stated travel, and the source of each with a
`read` flag. The catalog starts empty. A pin is added when a maker's datasheet
has been read, and the build says when a figure is from a search excerpt.

Until one is, a fixture can take the user's own pin figures in its file, labelled
as the user's, in the way a board's power is.

## Decision: the build computes a worst-case misalignment, and refuses a pin that can miss

This is the check that matters. Every clearance in the chain from the board to
the pin shifts the pin's tip off its pad. A fixture's misalignment is the sum of
those clearances, taken at their worst:

| Link | Its worst-case shift |
| --- | --- |
| Board in the nest | the nest's clearance, a side to a side |
| Locating pins in the board's mounting holes, when used | the hole's diameter less the pin's, per side |
| The pin plate on the nest | the sliding clearance at its dowels, per side |
| The pin in its bore | the bore's clearance, per side |
| The pin's tip off its axis | the tilt allowed by that clearance over the pin's length |

All the figures are the printer profile's provisional tolerances and the pin's
own. The result is one number, `misalignment_mm`, which the build prints. The
build then refuses a fixture where, for any test point,

```
misalignment_mm + tip_radius_mm > pad_radius_mm
```

A pad of 1.5 mm and a tip of 0.5 mm leave 0.25 mm of slack on each side; a
fixture whose chain adds up to more cannot be trusted to land, and the engine
says which link to tighten, or that the fixture needs locating pins. It does not
claim the number is accurate, only that the design cannot meet its own pads if
the number is exceeded. A trial's measured offsets replace the assumed
tolerances in this sum, so the figure improves as evidence comes in.

## Decision: the pins press from above, through a plate

Phase one probes the top side. The board sits in the nest, parts up, and a plate
above it carries a bore over each test point. A pin sits in the bore, its tip
down on the pad, its tail held by the plate, and the spring taking up the
travel as the plate closes.

- **The pin plate** stands off the board by the pin's free length less the
  working travel, with a boss at each corner against the nest so the plate never
  rests on the board.
- **Clearance over parts.** A pin's barrel and the plate's bore are a
  cylinder. Each is checked against the board's component boxes above the
  board's top: a barrel that falls on a part is refused, and the plate's
  underside stands above the tallest part by a clearance.
- **Locating.** The plate registers to the nest by two dowels (a printed pin or
  a catalogued fastener), or by pins down through the board's mounting holes
  when it has two or more.
- **The closure.** The plate is held down against the pins' combined preload.
  It is either screwed to the nest, or hinged on the nest's back wall and closed
  with the catch, with `lid_hinge` as the pattern. The build computes the
  preload as pins times force at the working travel, and refuses a catch whose
  strain at that load is over the material limit. A screwed closure is checked
  against the fastener's tensile figure from the catalog.

A fixture that probes the bottom side, a bed of nails with the board parts-up
on top of the pins, is later: it needs a nest that holds the board by its edge
over an open window, and the standoffs and cradle are not built for it.

## The fixture file

```
zcad-validation fixture template --board-file my-board.json --output my-fixture.json
zcad-validation fixture check my-fixture.json
zcad-validation fixture build --fixture-file my-fixture.json --output-directory out
```

The fixture file names the board file (by path and hash), the pin (a catalogued
one, or the user's figures), the working travel, the locating method, and the
closure. It never repeats the board's data. `fixture check` lists every problem
at once and says whether the board file's test points are enough.

## Checks

| Check | What it refuses |
| --- | --- |
| The board is where it says | The board file's hash differs from the fixture's |
| Test points present | The board has none on the side being probed |
| Pin reaches | A test point is off the plate's span, or the plate's bore walls are thinner than the printer's minimum |
| Pin lands | `misalignment_mm + tip_radius_mm` exceeds a pad's radius |
| Pin clear of parts | A barrel footprint overlaps a part box, or the plate meets the tallest part |
| Pin pitch | Two bores' walls are under the printer's minimum wall |
| Release | The board, lifted out with the plate off, meets the nest |
| Closure | The preload exceeds what the screws or the catch can take |
| Bed | The nest and the plate fit the bed |

## Decision: verified by trials that probe, with the misalignment measured

A trial of a test fixture records what a person observes: per test point,
whether the pin made contact (a continuity or a program loaded), and its
measured offset from the pad's centre if it was off. A fixture that has passed
two trials, each with every point in contact, is verified. The offsets pool into
a measured misalignment with a sample size, which the build then uses in place
of the assumed sum, as the pooled thermal coefficient replaced the default.

The engine does not test a board. It builds a fixture and records whether the
fixture worked.

## Phases

1. **Test points and the pin (built).** `test_points` in the board schema and its
   checks, the `PogoSpec` type and its sourcing, `board check` reporting them,
   and the fixture file's schema with `fixture template` and `fixture check`.
   See *What phase 1 changed* below, and the guide
   [A test fixture for your board](../guides/pcb-test-fixture.md).
2. **Nest and plate.** The outline-following nest, the pin plate, the bores, the
   locating dowels, the part-clearance checks, the worst-case misalignment and
   the check on it, and `fixture build`.
3. **Closure.** The screwed closure and the hinged one, with the preload and the
   catch or fastener check.
4. **Trials.** Fixture trials in the Validation Lab with per-point contact and
   offset, the pooled measured misalignment, verification, and the page on
   building and trying a fixture.

A later phase adds the bottom-side bed of nails, and a programming fixture for
pads that carry a header footprint (a row of pins at a fixed pitch) as one
named group.

### What phase 1 changed

- **Test points are checked against the outline.** A pad must lie wholly on the
  board, judged by its polygon or rounded outline when it has one, not by the
  bounding rectangle. Two pads on the same side that overlap are refused; pads on
  opposite sides may share a place. The board template now carries two example
  points. The schema version stays 1.0.0, since the field is optional.
- **The pin catalog is empty, and cannot be a `HardwareCatalog`.** That class
  refuses an empty registry, so pins have their own small one
  (`hardware/pogo.py`) with `get_pogo_pin` and `list_pogo_pins`. A fixture's
  `pin` is either `{"catalog": ID}`, refused today with the empty list named, or
  the user's own figures with a required `source`. The check, and later the build
  record, say the figures are the user's.
- **The pitch check is built here, not in phase 2.** It needs only the pin and
  the profile, so `fixture check` takes `--printer-profile` and refuses pins
  whose bores (barrel, sliding clearance each side, `hole_oversize`) leave less
  than the printer's minimum wall between them.
- **Slack is reported per point.** The pad's radius less the tip's: how far the
  tip may sit off the centre and still touch. Phase 2's misalignment sum is
  compared with it; phase 1 only reports it, and warns when a tip covers more
  than half its pad.
- **The commands join the existing `fixture` group.** `fixture export` is the
  Validation Lab's print fixture; `fixture template` and `fixture check` sit
  beside it. They share a name and nothing else.
- **Not built: bottom-side probing, the nest, the plate, the closure,** and the
  catalogued pins. `side` other than `top` is refused with a message saying so.

Each phase is one PR. Phase 1 adds an optional field to the board file, so no
existing board file changes.

## Not covered

- **Testing itself.** No test sequence, no instrument control, no pass or fail
  of the board. The engine builds the fixture.
- **Bottom-side probing, double-sided boards, and bed-of-nails production
  fixtures.** One side, parts up, a bench fixture.
- **Test-point positions from a design file.** A KiCad or Gerber file carries
  them; reading one is the later EDA import named in [Generic boards](generic-boards.md).
- **Fine pitch.** The printer's minimum wall and its hole accuracy set how close
  two pins can stand, and a very fine pitch is beyond a printed plate. The check
  refuses it by the profile's own minimum wall, and no pitch is promised here.
- **High-current and high-frequency contacts.** A pin's current rating is a
  maker's figure; the engine carries it and does not use it.

## Open questions

- **Where the pin's tilt allowance comes from.** The shift from a pin tilting in
  its bore needs the bore's clearance and the pin's length. It is geometry, but a
  real pin also rocks on its tail. The proposal is to include the geometric
  tilt and say the rest is for a trial to measure.
- **Whether locating by the mounting holes is the default.** It is tighter than
  the outline, but a board's holes are the least precise feature it has. The
  proposal is the outline by default, and the holes when the user asks.
- **Whether a fixture takes a board that is not a file.** The catalogued boards
  have no test points, so a fixture for the Pico 2 needs them added to its entry.
  The proposal is to add `test_points` to the catalogued boards only when someone
  has a measured list, and until then a fixture takes a board file.

# A test fixture for your board

A test fixture holds a board by its outline and presses spring-loaded pins
(pogo pins) onto its test points from a plate above, so every point is reached
in the same place every time. This release describes the fixture and checks it:
which points, which pin, and whether the pins can reach the pads. It does not
build the nest and plate yet.

```bash
zcad-validation fixture template --board-file my-board.json --output my-fixture.json
# edit the pin's figures and the points, then:
zcad-validation fixture check my-fixture.json
```

`fixture check` reads the fixture file and the board file it names, lists every
problem at once, and exits 1 if the fixture cannot be built. It takes
`--printer-profile`, which the pins' pitch is checked against.

## Test points are in the board file

A fixture never repeats the board's data. The pads to probe are the board's own
property, so they go in its [board file](board-file.md#test-points). Without
test points on the side being probed, the fixture is refused.

## The fixture file

| Field | What it is |
| --- | --- |
| `board.file`, `board.sha256` | The board file, relative to the fixture file or absolute, and its hash. A board that has changed since is refused. |
| `side` | `top`, the only side probed for now. |
| `points` | The test points to probe, by name. Left out, all of the side's. |
| `pin` | The spring pin; see below. |
| `working_travel_mm` | How far the pins are pressed in. It cannot exceed the pin's travel. |
| `locating` | `outline` (the board's edge, the default) or `holes` (its mounting holes, which needs at least two). |
| `closure` | `screws` or `hinge`: how the plate holds down. Recorded now, built later. |

## The pin

A pogo pin's figures are a maker's datasheet: barrel and tip diameter, free
length, travel, and the force it pushes back with at a stated travel. The engine
**does not catalogue any pin yet**, because no datasheet has been read, so a
fixture gives its pin's own figures:

```json
"pin": {"maker": "...", "model": "...", "barrel_diameter_mm": 1.0, "tip_diameter_mm": 0.6,
        "free_length_mm": 8.0, "travel_mm": 2.0, "force_n": 1.0, "force_at_travel_mm": 1.5,
        "source": "the maker's datasheet, page 2"}
```

`source` is required, and the check says the figures are **yours**. When a pin
is catalogued, `"pin": {"catalog": "ID"}` will name it; today that is refused
with the list of catalogued pins, which is empty.

## What the check refuses and reports

Refused:

- A board that has changed, is missing, or is not itself a valid board file.
- No test points on the probed side, or a point named in `points` that the board
  does not have (the error lists the ones it has).
- A pin whose **tip is wider than a pad** it must land on.
- A working travel beyond the pin's.
- `locating: holes` on a board with fewer than two mounting holes.
- Pins too close together: each pin sits in a bore of its barrel plus the
  printer's sliding clearance on each side plus `hole_oversize`, and the plate
  between two bores must be at least the printer's minimum wall. Two pads 2.5 mm
  apart with a 1 mm pin leave 0.9 mm and are refused.

Warned of: a tip wider than half its pad, which leaves little slack for
everything that can move it.

The report gives, for each point, its position and its **slack**: how far the
pin's tip may sit off the pad's centre and still touch it (the pad's radius less
the tip's). The fixture build, in a later release, will add up the clearances
that can move the tip and refuse a fixture whose total exceeds that slack.

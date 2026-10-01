# A test fixture for your board

A test fixture holds a board by its outline and presses spring-loaded pins
(pogo pins) onto its test points from a plate above, so every point is reached
in the same place every time. The engine builds the **nest** that holds the board
and the **plate** that carries the pins, checks that the pins can land on their
pads, and writes a record of what it assumed. The closure that holds the plate
down against the pins is not built yet: you hold the plate by hand.

```bash
zcad-validation fixture template --board-file my-board.json --output my-fixture.json
# edit the pin's figures and the points, then:
zcad-validation fixture check my-fixture.json
zcad-validation fixture build --fixture-file my-fixture.json --output-directory exports/my-fixture
```

`fixture check` reads the fixture file and the board file it names, lists every
problem at once, and exits 1 if the fixture cannot be built. `fixture build`
exports `<name>-nest` and `<name>-plate` as STEP and STL, checks them against the
printer profile, and writes `fixture.json`, a record of what was built from what.
Both take `--printer-profile`.

## Test points are in the board file

A fixture never repeats the board's data. The pads to probe are the board's own
property, so they go in its [board file](board-file.md#test-points). Without
test points on the side being probed, the fixture is refused. List the board's
parts as components, not an envelope, if you want the check to say which pins
would land on a part.

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
| `nest.wall_mm` | The nest's wall (2.4 by default). |
| `plate.thickness_mm` | The plate's thickness. Left out, it is two barrel diameters, or as much as the room allows. |

## The pin

A pogo pin's figures are a maker's datasheet: barrel and tip diameter, free
length, travel, and the force it pushes back with at a stated travel. The engine
**does not catalogue any pin yet**, because no datasheet has been read, so a
fixture gives its pin's own figures:

```json
"pin": {"maker": "...", "model": "...", "barrel_diameter_mm": 1.0, "tip_diameter_mm": 0.6,
        "free_length_mm": 14.0, "travel_mm": 4.0, "force_n": 1.0, "force_at_travel_mm": 2.0,
        "source": "the maker's datasheet, page 2"}
```

`source` is required, and the check says the figures are **yours**. When a pin
is catalogued, `"pin": {"catalog": "ID"}` will name it; today that is refused
with the list of catalogued pins, which is empty.

## What it builds

All heights are above the board's top face.

- **The pin sits in a bore through the plate** with its tail flush with the plate's
  top, so with the pins pressed in by the working travel the tip is on the pad:
  the plate's top stands **the free length less the working travel** above the
  board (12 mm for a 14 mm pin pressed in 2 mm). The bore is the barrel plus the
  printer's press-fit clearance each side plus `hole_oversize`: the barrel is
  pressed in.
- **The plate** is as thick as two barrel diameters allow (at least 1.5 mm), and
  its underside must stand 0.5 mm above the tallest part. A pin too short for
  that is refused, with how much room there is.
- **The nest** is a tray that follows the board's outline. The board rests on a
  1.2 mm ledge round its edge over a hollow for the parts under it, with a prop
  under each test point unless a part sits there (the check warns of the ones
  with none, where the pins may flex the board). The walls rise to a **rim** at the
  plate's underside, so the plate rests on the rim and never touches the board.
  A window is cut, open to the rim, wherever a part overhangs the board's edge, so
  the part lifts out with the board, and two finger notches help lift it.
- **Locating.** With `outline`, two 3 mm dowels stand on ears outside the nest at
  the ends of the board's longer side, and the plate has sockets for them. With
  `holes`, two posts rise from the nest's floor through the two mounting holes
  farthest apart, locating the board and the plate together.

The build then checks that the board drops into the nest and lifts straight out,
that the plate clears the board and rests on the nest without touching it, and
that every pin's barrel clears the plate and the parts. It also refuses a part
that will not lie on the printer's bed.

## Will the pins land?

Every clearance in the chain from the board to the pin can move a tip off its
pad. The check adds them up **at their worst**, from the printer profile's
provisional tolerances:

| Link | What it is |
| --- | --- |
| The board in its nest | The sliding clearance each side, or the post in its hole. |
| The plate on its dowels | A clearance at each dowel, which can also turn the plate: a pad far from the line between the dowels swings more. |
| The pin in its bore | The press-fit clearance. |
| The pin tilting in its bore | The pin turning by two clearances over the bore's length, with the tip a long way below: the thicker the plate, the less. |

A pin **can miss** if the total is more than its pad's **slack**, the pad's radius
less the tip's. The check then refuses the fixture and names the largest link,
and what to do: a larger pad or a finer tip, a thicker plate or a longer pin, or
locating by the mounting holes. For a 3 mm pad and a 0.6 mm tip the slack is
1.2 mm; the example fixture's worst point totals 1.06 mm, mostly the pin tilting
in its bore. With 1.5 mm pads it would total the same against 0.45 mm of slack,
and be refused.

This is a bound from tolerances the printer profile marks provisional. If it fits,
**nothing is proved**: a printed fixture is not verified until a trial has
measured it. If it does not fit, the fixture cannot be trusted to land.

## What the check also refuses

- A board that has changed, is missing, or is not itself a valid board file.
- No test points on the probed side, or a point named in `points` that the board
  does not have (the error lists the ones it has).
- A pin whose **tip is wider than a pad** it must land on.
- A working travel beyond the pin's.
- `locating: holes` on a board with fewer than two mounting holes, holes too small
  for a 1.6 mm post, or a post that would meet a part under the board.
- A pin whose barrel would land on a part beside its pad.
- Pins too close together: the plate between two bores must be at least the
  printer's minimum wall. Two small pads 2.3 mm apart with a 1 mm pin leave 1.0 mm
  and are refused.

It warns of a tip wider than half its pad, of a board with no prop under a point,
and of a board whose parts are one envelope.

## The build record

`fixture.json` names the fixture file and the board by hash, the pin and whose
figures they are, each point with its slack and its worst-case misalignment, the
plate's heights, the dowels or posts, and the budget's links. It says
`verified: false` and `closure_built: false`.

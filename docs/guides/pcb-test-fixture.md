# A test fixture for your board

A test fixture holds a board by its outline and presses spring-loaded pins
(pogo pins) onto its test points from a plate above, so every point is reached
in the same place every time. The engine builds the **nest** that holds the board
and the **plate** that carries the pins, checks that the pins can land on their
pads, and writes a record of what it assumed. Two screws hold the plate down
against the pins; see *The closure* below.

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

## Probing the bottom side

Set `"side": "bottom"` and the fixture probes the test points the board file lists on its bottom side.

The pins still press down from above, so the fixture holds the board **turned over**, bottom face up, with its top
side hanging in the nest's cavity: the nest already holds a board by its edge over a cavity for the parts under it,
and the parts that were on top are now the ones hanging there. Everything the fixture checks (the pins' reach and pitch,
their clearance over parts, the plate, the release, the closure) is checked on the turned board, so a pin is refused if its
barrel would land on a part on the bottom side, and a tall part on the top side only deepens the cavity.

The board is turned **left to right**, about its Y axis, as a page is turned. So a bottom point at `(x, y)` is at `(-x, y)`
in the fixture, and a part standing 8.5 mm on the top face hangs 8.5 mm below it. The plate, the nest and the record are in the
fixture's frame; the record says `board_turned_over: true` and gives each point's `position_mm` (in the fixture) beside its
`position_in_board_mm` (in the board file). A trial's offsets are in the fixture's frame too, as you look down on a pad in
the nest, and the trial's note says so.

A board file with test points on both sides gives two fixtures, one for each side: the engine does not probe both at once.

## Test points are in the board file

A fixture never repeats the board's data. The pads to probe are the board's own
property, so they go in its [board file](board-file.md#test-points), written by
hand or read from a KiCad design by `board import --kicad`. Without
test points on the side being probed, the fixture is refused. List the board's
parts as components, not an envelope, if you want the check to say which pins
would land on a part.

## The fixture file

| Field | What it is |
| --- | --- |
| `board.file`, `board.sha256` | The board file, relative to the fixture file or absolute, and its hash. A board that has changed since is refused. |
| `side` | `top` (the default) or `bottom`: the side of the board the pins land on. A bottom-side fixture holds the board turned over; see below. |
| `points` | The test points to probe, by name. Left out, all of the side's. |
| `pin` | The spring pin; see below. |
| `working_travel_mm` | How far the pins are pressed in. It cannot exceed the pin's travel. |
| `locating` | `outline` (the board's edge, the default) or `holes` (its mounting holes, which needs at least two). |
| `closure` | `screws` (the default) or `hinge`: how the plate holds down. `hinge` needs a plain rectangular board. |
| `screw` | Optional: `size` (a catalog fastener with a heat-set insert, `M3` by default) and `tensile_limit_n` with its `source`. See *The closure*. |
| `hinge` | Optional, for `closure: hinge`: `pin` (a catalog fastener, `M3` by default) and `catch_load_limit_n` with its `source`. See *The hinged closure*. |
| `nest.wall_mm` | The nest's wall (2.4 by default). |
| `plate.thickness_mm` | The plate's thickness. Left out, it is two barrel diameters, or as much as the room allows. |

## The pin

A pogo pin's figures are a maker's datasheet: barrel and tip diameter, free
length, travel, and the force it pushes back with at a stated travel. The engine
catalogues a pin only when its datasheet has been read, and a fixture either names a
catalogued pin or gives its own figures:

```json
"pin": {"maker": "...", "model": "...", "barrel_diameter_mm": 1.0, "tip_diameter_mm": 0.6,
        "free_length_mm": 14.0, "travel_mm": 4.0, "force_n": 1.0, "force_at_travel_mm": 2.0,
        "source": "the maker's datasheet, page 2"}
```

`source` is required, and the check says the figures are **yours**.

**Catalogued pins.** `"pin": {"catalog": "MILLMAX-0906-1-15-20-75-14-11-0"}` names one, and an
unknown name is refused with the list. Two are catalogued, both Mill-Max 0906 spring-loaded
pins read from the maker's data sheets (`0906-0-15-20-76-14-11-0`, 3.48 mm tall with a 0.99 mm
stroke, and `0906-1-15-20-75-14-11-0`, 4.50 mm tall with a 1.40 mm stroke): a 1.07 mm tip, a
1.83 mm largest diameter, and a spring of 60 grams force. The check names what the sheets do not
state outright, in `figures_from`: the **barrel** is taken as the drawing's largest diameter, and
the **force** is taken at the mid-stroke, the maker's working travel, since the sheet gives
60 grams without naming a travel. These are small pins with a solder tail, not fixture
sockets, and the fixture's own checks show it: they are too short for a board with a tall
part under the plate.

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
that the plate rests on the nest without touching it, and that every pin's barrel
clears the plate and the parts. A hinged plate is also checked against the board,
since its catch hangs below it; a screwed plate is refused at the build if its
underside would come lower than the tallest part and a margin, so it is not. The
screws' preload and the catch's load are refused at the build when over a limit
you give, and recorded in the plan. It also refuses a part
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
| The pin tilting in its bore | The pin turning by two clearances over the bore's length, over the depth from the plate's underside to the tip: the thicker the plate, the less. |

A pin **can miss** if the total is more than its pad's **slack**, the pad's radius
less the tip's. The check then refuses the fixture and names the largest link,
and what to do: a larger pad or a finer tip, a thicker plate or a longer pin, or
locating by the mounting holes. For a 3 mm pad and a 0.6 mm tip the slack is
1.2 mm; the example fixture's worst point totals 1.01 mm, mostly the pin tilting
in its bore. With 1.5 mm pads it would total the same against 0.45 mm of slack,
and be refused.

This is a bound from tolerances the printer profile marks provisional. If it fits,
**nothing is proved**: a printed fixture is not verified until a trial has
measured it. If it does not fit, the fixture cannot be trusted to land.

## The closure

The pins push the plate up with their combined force, so two screws hold it
down. Each goes through a clearance hole in the plate into a heat-set insert in
an **ear** on the nest. The ears stand on the sides the finger notches are on, at
opposite ends and opposite sides, so the pair sit diagonally; they stand clear of
the dowel ears and the notches. An ear is wider than the dowels' if the insert's
pocket and the printer's minimum wall need it (an M4 insert does). The build
refuses a board too small to carry the ears, and a pocket the ear is too short
for.

The **preload** is the force of the pins with the plate closed: each pin's force
at the working travel, times the number of pins. A pin's force is given at one
travel, and the engine takes it as **proportional to the travel** from there, a
straight spring. That is an assumption, and a pin's force is often not linear
near the end of its travel: confirm it from the datasheet. The record gives the
preload, the load on one screw (all of it, should the plate lift at the other
end), and the screw's length: at least the plate's thickness plus the insert's
depth.

**The screw's strength is not in the catalog**, which carries a fastener's
dimensions and not its strength, and the engine does not supply one. Give your
own in the file, with where it came from:

```json
"screw": {"size": "M3", "tensile_limit_n": 500, "source": "my own pull test"}
```

With a limit the build refuses a preload over it and records the check. Without
one the preload is **reported and not checked**, and `fixture check` says so. The
engine does not check the plate bending between the screws, a printed ear pulling
off the nest, or an insert pulling out of printed plastic; the record lists them
as not checked. Whether the plate stays down is for a trial.

### The hinged closure

`"closure": "hinge"` hinges the plate on one of the nest's long walls and closes
it on a snap catch on the other, with no screws to fit or lose. It is the
enclosure's hinge and catch (see
[hinges and slides](../roadmaps/hinges-and-slides.md)), with the nest as its base
and the plate as its lid: knuckles alternate between them round a pin that is an
M3 screw and nut, or a threaded rod for a long wall, and the catch is a tongue
outside the other wall with a hook that snaps under a bump.

- **Which wall.** The hinge goes on the positive long wall unless a window is
  cut in it for an overhanging part, then on the negative one; the build refuses
  a board with a window in both, since the knuckles would close one over a part
  that must lift out. The catch goes on the wall opposite and keeps clear of any
  window there.
- **The finger notch moves.** The hinged closure has one notch, on the catch's
  wall and toward one end of it, so the catch has the rest of the wall. The
  hinge's wall has none.
- **The pins swing with the plate.** Each pin hangs from the plate down to its pad,
  ten millimetres or more below the pin's axis, so opening the plate swings every
  pin through an arc. The build sweeps the plate and the pins open in 10 degree
  steps to 100 degrees against the nest, the board and its parts, and refuses a
  fixture where anything meets, naming it: a tall part beside a pad on the side the
  pins swing toward is the usual cause. It also lifts the board out with the plate
  open. The answer is to close that board with screws.
- **A plain rectangular board only.** A rounded or polygon outline is refused,
  since the hinge and the catch are built round a straight wall.
- **The load.** The catch carries the share of the preload that a moment balance
  about the pin gives it: each pin's force taken as equal, from where it stands
  between the pin and the catch. The hinge carries the rest. The catch's **strain**
  is checked as the enclosure's catch is, against the same provisional limit, at
  build. Its **load** is checked only against a limit you give, as the screw's
  is:

```json
"hinge": {"pin": "M3", "catch_load_limit_n": 8, "source": "my own pull test"}
```

  Without one the load is reported and `fixture check` says it is not checked. The
  plate bending between the hinge and the catch, the knuckles and pin wearing, and
  the hook creeping under load are not checked, and the record says so.
- **Printing.** The nest prints on its floor. The plate prints on its top face with
  the catch's tongue pointing up, as an enclosure's hinged lid does. The barrels
  stand proud of the plate by about 2.5 mm, so the plate's edge strip may want
  support: **no print has shown whether it prints cleanly**, and the first trial is
  where to find out.

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
- A closure it cannot build: a board too small for the screw ears, a hinge on a
  board that is not a plain rectangle or has a window in both long walls, no room
  for the catch beside the notch and the windows, or a preload (screws) or a catch
  load (hinge) over a limit you gave. A plate and pins that cannot swing clear are
  refused at build.

It warns of a tip wider than half its pad, of a board with no prop under a point,
and of a board whose parts are one envelope.

## The build record

`fixture.json` names the fixture file and the board by hash, the pin and whose
figures they are, each point with its slack and its worst-case misalignment, the
plate's heights, the dowels or posts, the budget's links, and the closure's
screws, preload and limit (with what is not checked). It says `verified: false`
and `closure_built: true`. A build is never verified by its own record: trials
decide that, below.

## Trying a fixture

A printed fixture is unverified until a trial has measured it. A trial records one
print of exactly the nest and plate `fixture build` exported, with the board in
it and the plate closed.

```bash
zcad-validation fixture trial start --build-record exports/my-fixture/fixture.json
# print it, seat the board, close the plate, probe; fill in the two files it names
zcad-validation fixture trial complete \
  --trial-directory exports/my-fixture/trials/trial-001 --disposition pass
```

`trial start` writes `trials/trial-001/` beside the build record with two files:

- **`observations.json`**: a pass or fail for each of five checks (six for a hinged plate, which adds
  whether it swings free with its pins). Does the board
  seat in the nest and lift out of it? Does the plate seat on the rim? Does it
  stay down at the working travel with the screws fitted or the catch home? Does each pin travel
  freely with the plate off? The guidance for each is in the file.
- **`measurements.json`**: for each probed point, whether the pin **made contact**
  (a continuity check, or a program loading), and optionally where the tip's mark
  fell from the pad's centre, in the board's frame. A thin coat of marker on the
  pad, or a witness mark, shows where. Give an offset for a point that missed, to
  see how far, and for those that touched, to build a measured misalignment.

`trial complete` checks the printed STLs still match the build record, that every
check is answered, and that the measurements belong to this fixture's points, then
writes `fixture-trial.json` with each point's offset and the **share of its slack**
that used. A passing trial has no failed check and **every point in contact**;
offsets are optional. A failed or inconclusive trial may leave them unmeasured.
An offset beyond a point's slack, in a point that touched, is counted in the
summary rather than refused: the measurement and the pad cannot both be right,
and the record keeps both. A completed trial is never overwritten.

**A fixture is verified by two passing trials of the same build record.**

```bash
zcad-validation fixture status --build-record exports/my-fixture/fixture.json
```

exits 0 if it is verified and 1 if not, and lists the trials. A rebuilt fixture
has a new record and starts with none.

### A measured misalignment for the next build

The offsets from passing trials pool into a **fixture accuracy profile** for one
printer and one material:

```bash
zcad-validation fixture derive --evidence-root evidence \
  --printer-profile-id bambu-lab-a1-mini --material-profile petg
```

It needs at least two passing trials with at least one offset, and writes
`profiles/fixtures/bambu-lab-a1-mini-petg.json`: the mean, spread and largest
radial offset, the sample count, the mean offset in X and Y (a bias: all tips
landing one way mean the board's seat or the plate's turn is off), the largest
share of a pad's slack any tip used, and how many probed points made contact.
Deriving again writes the next version and keeps the old figures.

Give it to a build with `fixture build --accuracy-profile PATH`, with the same
printer and `--material-profile`. The build reports the measured figures with
their sample size next to each point's slack and its worst-case sum, **warns**
when the measured offsets are bigger than a pad's slack (the pin may miss, whatever
the sum said), and records the profile's id, version and hash. A profile for
another printer or material is refused. **The worst-case sum stays**: the profile
is evidence about the prints that were measured and how they were measured, and
the engine does not turn it into a promise for a new fixture.


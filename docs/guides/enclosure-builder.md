# Enclosure builder

`build_enclosure` turns catalogued hardware into a printable, screw-together
enclosure: a **base** and a **lid**, fastened with M3 (or M2, M2.5, M4)
screws into heat-set inserts. Use it from the command line or from Python.

## From the command line

```bash
zcad-validation enclosure hardware
```

lists the boards, displays, and fasteners in the catalog. Then:

```bash
zcad-validation enclosure build --board raspberry_pi_pico_2 \
  --display reference_oled_128x64 \
  --output-directory exports/pico2-enclosure --review
```

writes `<name>-base` and `<name>-lid` STEP, STL, and metadata files after
export validation against the printer profile passes, and with `--review`
a review package in `exports/pico2-enclosure/review/`. The command prints a
JSON summary and exits non-zero if the review fails a check. Every design
setting below has a matching flag, such as `--bottom-clearance-mm 3`.

## What it builds

| Part | Features |
| --- | --- |
| Base | Floor and walls; an insert boss in each corner; board supports; the cable opening |
| Lid | A screw clearance hole over each boss; a window over the display; a display retainer |

**Board supports.** A board with mounting holes sits on a standoff under
each hole, whether the holes form a rectangle (Pico 2, Feather RP2040) or
not (UNO R4 WiFi). A board without holes (XIAO ESP32-S3) sits in a snap-in
cradle: a ledge under its edges, a snap clip on each side edge, and a stop
behind the edge opposite its connector.

**Display mounting.** A display with mounting holes screws to posts that
hang from the lid over its holes: its face sits under the window and
`display_fastener` self-tapping screws (M2 by default,
`--display-fastener`) go up through its PCB into the posts. A display
without holes sits in a retainer instead: L-shaped posts at its corners
locate it and carry pads its face rests against, and a snap clip on each
side hooks under it, leaving the middle of the other two edges open for a
pin header or flex cable. Turn either off with `display_retainer=False`
(`--no-display-retainer`).

**Lid options.**

- `--countersunk` (`countersunk_screws`) sinks flat-head lid screws flush;
  an M3 head needs a lid at least 1.9 mm thick.
- `--locating-lip` (`locating_lip`) hangs a 2 mm skirt under a screwed lid,
  just inside the walls, so it keys onto the base before the screws go in.
  It is notched around the corner bosses and the wall openings.
- `--lid snap` (`lid_attachment="snap"`) replaces the screws and inserts
  with a 4.5 mm skirt that carries a ridge along each long side; the ridges
  click into grooves in the long walls, and the skirt is slit beside each
  ridge so that stretch flexes. With no bosses, the cavity only needs room
  for the skirt, so snap enclosures are often smaller.
- `--lid hinge` (`lid_attachment="hinge"`) hangs the lid from one long wall
  on a row of knuckles around a pin, and closes it with a catch on the
  opposite wall. The pin is an M3 screw and nut (`--hinge-pin` picks another
  size), and the build prints its length. There are no bosses or skirt, so
  the cavity can be smaller, but the hinge side grows by about 7 mm for its
  barrels and the catch side of the lid by 3 mm for its tongue. The hinge goes
  on a long wall with no opening, the back one if both are free. The catch
  is a tongue hanging outside the front wall, with a hook that snaps under a
  bump; pull its lip to open it. Its strain is checked like the DIN clip's
  latch. The catch needs a wall at least 11.7 mm tall (a hinged Pico 2 needs
  `--bottom-clearance-mm 6`), and the walls stand 3 mm off the hardware, not
  2, because a display's retainer swings toward the front wall as the lid
  opens. Before the build returns, the lid is swung open in 10 degree steps
  to 100 degrees, with a display swinging along with it, and the build is
  refused if the lid or display meets the base or any part. A hinged lid
  with a display pulls on whatever connects it to the board: leave slack.
  No cycle life is claimed; a printed PETG hinge wears, and a trial has to
  count openings.
- `--lid slide` (`lid_attachment="slide"`) makes the lid a plate that slides
  along grooves cut in the two long walls. The long walls are raised 3.4 mm
  above the cavity and thickened 1.6 mm outward, so the box grows by 3.2 mm
  across and 1.4 mm in height; a 45 degree slope under the thickening keeps
  it printable. The far short wall is raised too and is the lid's stop; the
  near one, the entry, is cut down to the groove's floor, and is one with no
  opening, the +Y or +X one if both are free. The gap around the lid is
  `--slide-clearance-mm` (`slide_clearance_mm`, 0.2 by default); the export
  checks it against the printer profile's `sliding_clearance_per_side` and
  warns when it is less. A tongue on each edge of the lid, cut in its plane so
  its stress runs along the layers, carries a rounded bump that clicks into a
  dimple in the groove to hold the lid shut; its strain is checked like the
  DIN clip's. Push the lid's end to open it. There are no bosses or skirt. Before the
  build returns, the lid is slid out in 5 mm steps and the build is refused if
  it meets the base or a part inside. Nothing may hang from a sliding lid
  below the entry wall, because it would hit that wall as the lid slides out,
  so a slide lid cannot hold a display: use a hinged or screwed lid for one.
  An opening in a long wall is refused if it would cut the groove's floor, and
  vents stay below the thickening, so the wall must be tall enough for them.
- `--vent-slots N` (`vent_slots`) cuts N vertical slots, 1.6 mm wide at a
  4 mm pitch, through each long wall that carries no opening, below the
  lid's skirt and clear of the corners.
- `--vent-area-mm2 A` with `--vent-pattern P` (`vent_area_mm2`,
  `vent_pattern`) cuts a pattern sized to a free area instead: `A` mm2 of
  inlets low in the long walls that carry no opening (shared between them),
  and outlets in the lid that are at least as large. `P` is `slots`, `hex`
  (a hex grid), `round` (round holes), or `louvers` (slanted slots in the
  walls, sloping down to the outside so a level look meets wall; the lid takes
  slots). Cells are 1.2 mm apart, the smallest that reach the target, taken
  from the middle of the zone outward. A cell is kept only where the plate is
  solid all round it and nothing hangs behind it, so none opens onto an
  opening, a screw hole, the display window, a boss, a standoff, a post, or
  the hinge's and slide's features. A hex has a flat top and a hole through a
  wall is a teardrop, so nothing overhangs past 45 degrees. The build prints
  the free areas under `vents`, and refuses a target the zone cannot pass, or
  walls too short for any cell, saying so. It is separate from `--vent-slots`:
  set one or the other. The temperature estimate credits no vents.

The builder refuses combinations that do not fit, such as more slots than
a wall holds, or vents on walls too low to fit them under a skirt.

**Mounting.** `--mount keyhole` (`mount="keyhole"`), `--mount vesa75`,
`--mount vesa100`, or `--mount din` adds four pads under
the floor, one at each corner of the footprint, and a third part, the
**mount plate**, that bolts to them. Each pad carries a heat-set insert
pocket (the pocket leaves 1 mm of floor above it, so it never opens into the
cavity), and the pads stand 4 mm off the floor for an M3. The plate takes
the enclosure's fastener, countersunk from its outer face, so it sits flat
against a wall; `--mount-plate-mm` (4 by default) must be thick enough for
the countersink. The keyhole plate has two keyholes on its centreline: a
9 mm hole for a wall screw's head and a 4.5 mm slot running 10 mm toward the
plate's -Y edge, so the enclosure hangs with +Y up and slides down onto the
screws. A wall screw's head sits in the gap between the plate and the floor.
The build prints the screw for the plate (M3 x 8 mm by default).

The VESA plates follow VESA MIS-D: four holes on a 75 x 75 or 100 x 100 mm
square, centred on the pads, for M4 screws that go through the plate from
the enclosure side into the device's threaded holes, their heads in the gap
under the floor. The plate grows to cover the pattern, so on a small
enclosure it is larger than the enclosure (87 x 87 mm for VESA 75 on a Pico
2). The build prints the M4 screw (plate thickness plus 8 mm of thread, 12
mm for a 4 mm plate) and is refused if a screw head would come within 2 mm
of a pad, which a footprint near the pattern's size cannot avoid; try the
other pattern.

The keyhole plate is refused if a keyhole would come within 2 mm of a screw
hole or an edge, which small enclosures cannot avoid; the plate then needs a
larger footprint.

The DIN plate clips onto a 35 mm TS35 rail that runs along X: a fixed hook at
the +Y edge reaches under the rail's top flange, and a latch at the -Y edge
snaps under the bottom one, so the enclosure hangs with +Y up. The hooks
take flanges 1.0 to 1.5 mm thick, and the plate rests on the flanges. The
latch is a 1.6 mm tongue cut from the plate by a U-shaped slot, so it is a
printed spring: it swings 2.8 mm to pass the flange, and the build reports
its strain (1.4 % against a 1.5 % limit). That limit is a provisional design
value for printed PETG, not a measurement. Print the plate enclosure-face
down with the hooks up, so the tongue bends along the layers; each lip
overhangs by 2.5 mm, inside the 3 mm limit. The exported STL has the hooks
down, as the plate sits on the rail, so flip it in the slicer. To release,
push a flat screwdriver into the latch slot and lever the tongue outward.
The enclosure's footprint must be about 67 mm or more in Y, the direction
across the rail; any width works, because the plate grows to hold the
tongue. A shallower one is refused, because the latch slot would meet a
pad's screw hole.

Every mount is part of the design, so a revision keeps it. No strength is
modelled: hang only what a printed plate can carry, and treat the plate as
unproven until a trial says otherwise. See the
[mounting roadmap](../roadmaps/mounting-systems.md).

**Active Cooler.** `--active-cooler` fits a Raspberry Pi 5's Active Cooler
(`get_raspberry_pi5().with_active_cooler()` from Python). The cooler joins
the board's parts, so the enclosure and any display are checked against
it. Its 30 mm fan draws air from above, so the lid gets six 2.4 mm slots at
a 5 mm pitch across the fan. A display over the fan would starve it, so
the builder refuses one there. The cooler's top is 12.5 mm above the board,
under the USB stacks, so it adds no height. The build record notes the
cooler, so a revision rebuilds with it.

**Cable opening.** The opening passes a cable's moulded plug body, not just
the connector, so the plug reaches the connector through the wall and the
gap inside it. The defaults (12.5 x 7.5 mm) fit common USB-C and micro-USB
cables.

## Fans

`--fan NAME` (`fan=`) fits a catalogued fan: the Sunon MF30100V1-1000U-A99
(30 x 30 x 10 mm), the Noctua NF-A4x10 5V (40 x 40 x 11), or the Noctua
NF-A6x25 5V (60 x 60 x 25); `enclosure hardware` lists them. The fan sits
inside the box, its frame flat against the lid (`--fan-position lid`, the
default) or against a long wall (`--fan-position wall`), and is screwed from
outside: each of four clearance holes in the plate takes a screw into a hole in
the frame, and the build prints the screw (M3 x 10 mm for the 40 mm fan). The
opening is round, 90 per cent of the frame, crossed by a guard of 5 mm hex
cells with 1.2 mm webs, so a finger cannot reach the blades. `--fan-offset-x-mm`
and `--fan-offset-y-mm` move it from the middle of the lid, or along and up the
wall. `--fan-direction in|out` records which way it blows; the geometry is the
same, so mount the fan with its airflow arrow pointing that way.

The build refuses a fan that does not fit, and says why: too big for the lid,
over the display, or hitting a part or the base. A lid fan hangs 11 mm or more
below the lid, so over a tall part, such as the Pi 5's USB stack, raise
`--top-clearance-mm`, and use a snap lid if the corner bosses are in the way. A
wall fan needs a wall the fan's size plus 3 mm either side. A hinged lid swings
the fan with it, and a sliding lid cannot carry one. Vents keep off the fan's
frame, and the wall a fan takes counts as having an opening.

The fan's heat is added to the temperature estimate; its airflow is not,
because the maker's free-air figure falls by a large and unknown amount in a
box. The build reports the airflow beside the guard's free area, and whether
the box's other openings pass at least as much, so the fan has somewhere to
draw from or push to. **The fans' figures were taken from search excerpts of
the makers' pages and have not been checked against the pages themselves;**
the build says so with `datasheet_read: false`.

## Temperature estimate

Every build prints an estimate of the air temperature inside the closed box,
under `thermal`, and records it in `enclosure.json`. It is a lumped balance:
the power the parts give off, divided by the box's outer surface times 8
W/m2K (still air, the pessimistic end), added to the room's temperature. It
credits no vents, ignores conduction and hot spots, and is off by half either
way; a thermocouple on a printed box is the only real answer.

The power comes from the catalog, each figure with its source. Only two parts
have one: the Pico 2 (62.1 mW typical, 71.3 mW peak, from its datasheet) and
the Pi 5 (3.0 W idle, a community measurement on the Raspberry Pi forums, with
no peak). Every other board, every display, and the Active Cooler's fan are
unknown, never zero, and the build names them; the estimate is then "at
least", a lower bound. Add what the catalog lacks with `--power-w`, such as a
hat or an SSD, and the room with `--ambient-c` (25).

The limit is the material profile's `max_service_c`: 60 degrees C for PETG, a
provisional design value, well under the 70 to 80 at which it softens
(`--material-profile` picks the profile). The status is `warn` from 85 per
cent of the limit in degrees C and `fail` above it. A failing box is refused
unless you pass `--allow-hot`, because you have measured and know better.

## Design settings

`EnclosureDesign` holds the settings, in millimetres:

- `wall_mm`, `floor_mm`, `lid_mm`: thicknesses (2 each).
- `fastener`: `M3` by default.
- `side_clearance_mm`: the gap between the hardware and the walls. Left
  unset, the builder starts at 2 mm and widens X and Y separately, in
  0.5 mm steps, to the smallest footprint where the corner bosses clear the
  hardware, its supports, the display retainer, and the cable opening.
  Usually only the long axis widens.
- `bottom_clearance_mm`: the standoff or cradle height under the board (2).
- `top_clearance_mm`: the gap between the display and the lid (2).
- `cable_plug_width_mm`, `cable_plug_height_mm`: the plug body the opening
  must pass.
- `mount`, `mount_plate_mm`: a mount plate and its thickness (none, 4).
- `fan`, `fan_position`, `fan_direction`, `fan_offset_x_mm`,
  `fan_offset_y_mm`: a catalogued fan and where it goes.
- `vent_slots`, `vent_pattern`, `vent_area_mm2`: a fixed set of slots, or a
  pattern sized to a free area.
- `declared_power_w`, `ambient_c`, `service_limit_c`, `allow_hot`: the
  temperature estimate's extra power, room, material limit, and override.
- `lid_attachment`, `hinge_pin`, `slide_clearance_mm`: how the lid is held
  (`screws`, `snap`, `hinge`, or `slide`), the hinge's pin (`M3`), and the
  gap around a sliding lid (0.2).
- `hole_compensation_mm`: how much wider than intended to model every hole
  and opening (screw holes, insert pockets, pilot holes, windows, cable
  openings, and the cradle and retainer fits), for a printer that prints
  them small (0 by default; -0.2 to 1.0). A revision sets it from a trial;
  `--compensation-profile profiles/compensation/<printer>-<material>.json`
  takes it from the pooled trials of that printer and material, and the
  build record notes the profile's version.

The builder refuses, with the part named, any enclosure whose base or lid
intersects the hardware, whose lid runs into the base, or whose cable
opening would cut a boss. It refuses a rotated board, because the cable
opening follows the board's own connector edge: rotate the finished
enclosure instead.

## From Python

```python
from zcad_core.assemblies import Placement, build_board_assembly
from zcad_core.features import EnclosureDesign, build_enclosure
from zcad_core.hardware import get_board

board = get_board("adafruit_feather_rp2040")
assembly = build_board_assembly(
    board=board, board_placement=Placement(), connector_access_clearance_mm=2.0
)
enclosure = build_enclosure(
    assembly, board=board, design=EnclosureDesign(bottom_clearance_mm=3.0)
)
```

`build_board_display_assembly` adds a display; see the
[engine example](engine-example.md) for the full flow, including export.

## Reviewing before printing

`export_enclosure_review` (or `--review`) writes:

- `enclosure-review.glb`: the base, the lid lifted clear of it, and the
  hardware, coloured by part. Open it in Preview on macOS.
- `enclosure-review.step`: the assembled enclosure and hardware.
- `enclosure-review-{top,front,right,isometric}.svg`: views of the exploded
  enclosure.
- `enclosure-review.json`: part sizes, the side clearances chosen, the gap
  and overlap between each part and each piece of hardware, the screws to
  buy (the longest standard length the lid and insert take, and for a
  screwed display the longest that its PCB and posts take), and five
  checks: no interference, one solid per part, open screw paths, a plug
  body that clears the floor, and contact only where expected (the board on
  its supports, the display on its pads).

## Printing and recording a trial

```bash
zcad-validation enclosure build --board raspberry_pi_pico_2 \
  --display adafruit_oled_128x64_1_3in \
  --output-directory exports/pico2-enclosure --review --slice
```

Every build writes `enclosure.json`, a build record of the hardware, the
design settings, each part's STL hash, the checks that apply, and the
nominal dimensions to measure. `--slice` then:

- writes print-oriented copies of the parts to `print/`: the base on its
  floor, the lid on its outer face so its posts or retainer point up;
- slices both onto one plate with Bambu Studio into `slice/`
  (`plate_1.gcode` and `slice-summary.json`), using the project slicer
  profile (`--slicer-profile`); a plate too small for both parts fails
  here; and
- opens `trials/trial-001/`.

**Is a slice still current?** The G-code keeps its geometry after the
code that made it has moved on, so a fix does nothing for a slice made
before it. `slice-summary.json` records the git commit it was sliced from
and whether `src/zcad_core` or `profiles/` had uncommitted changes. Before
printing an older slice, check it:

```bash
zcad-validation slice check exports/pico2-enclosure
```

It finds every `slice-summary.json` under the paths it is given and calls
each `current`, `stale` (the sources changed since; it lists the commits,
or the files after a rebase), or `unknown` (sliced before slices recorded
their source, or from uncommitted changes). It exits 1 unless all are
current. `enclosure trial start` reports the same for the slice beside its
build record.

After printing and assembling, fill in the trial's `observations.json`
(`pass` or `fail` for each check that applies: clean print, inserts, lid
closure, board seated and held, cable plugs in, other openings clear,
display aligned and held, nothing rattles) and `measurements.json` (caliper
values beside the nominals), then:

```bash
zcad-validation enclosure trial complete \
  --trial-directory exports/pico2-enclosure/trials/trial-001 \
  --disposition pass
```

`pass` needs every check to pass and at least one measurement (or a recorded
temperature, below); `revise` needs a measurement or a temperature; `fail`
needs neither. The record stores each measurement's deviation from nominal,
and it refuses parts whose STL no longer matches the build record. A completed
trial is never overwritten:
`zcad-validation enclosure trial start --build-record .../enclosure.json`
opens the next one.

### Recording a temperature

Every trial also opens a `thermal.json`. It shows what the build predicted, and
has blanks for what a thermocouple and a power meter say; leave it blank for a
fit-only trial. To fill it, run the board under steady load with the lid on, a
probe in the middle of the cavity away from the hottest part, and another probe a
metre from the box for the room. Log the input power with a USB meter. Wait
until the air temperature moves by less than 0.5 degrees C in 10 minutes, record
that settled value for at least 10 minutes, and say whether the plastic
deformed (`deformation_observed`, true or false).

Completing the trial then compares the measurement with the estimate: the rise,
the box's effective coefficient (power over surface times rise), and how much
hotter or cooler it ran than the estimate said it would at the measured power
(`estimate_error_ratio`, above 1 if hotter). It refuses a reading held for less
than 10 minutes, a power of zero or less, a box no warmer than the room, or a
build record that has no estimate.

### A measured coefficient

```bash
zcad-validation thermal derive --evidence-root exports --material-profile-id petg
```

pools the completed thermal trials into `profiles/thermal/petg.json`, as
compensation profiles pool fit trials, and moves to the next version each time
it is run. It needs at least two trials of **closed** boxes (no vent, fan, or lid
slot), because only a closed box measures the passive coefficient. From them it
keeps the mean, spread, and count of the effective coefficient; vented and
fanned trials are listed beside it with their measured conductance as a ratio of
the passive one, and not pooled, because each is one configuration. It also keeps
the highest air temperature at which no deformation was seen and the lowest at
which some was; these inform the material's `max_service_c` and never replace it.

`--thermal-profile profiles/thermal/petg.json` on `enclosure build` (and
`enclosure-group build`) then uses the measured coefficient in place of the 8
W/m2K the estimate assumes, says so in `coefficient_source`, and records the
profile's id, version, and hash in the build record. The repository holds no
such profile: nothing has been measured yet. Even with a profile the estimate
credits no vents or fan airflow; the ventilated entries are what a later change
would use to decide whether, and by how much, to.

### Revising from a trial

```bash
zcad-validation enclosure revise \
  --trial-directory exports/pico2-enclosure/trials/trial-001
```

reads a completed trial and proposes the next design:

- **Holes**: the trial measures the intended sizes of the insert pockets
  and lid screw holes, so the mean shortfall (intended minus measured) is
  added to `hole_compensation_mm`. Shortfalls under 0.05 mm are noise.
- **Cable**: a cable that would not plug in widens the plug allowance by
  1 mm each way.
- **Everything else**: a failed check no setting fixes becomes a note on
  what to look at, and a base that printed more than 0.5% off size is a
  note to calibrate the printer; the design is never scaled.

Add `--output-directory` to build the revised design there (named
`<design>-r2`, then `-r3`), with `--review` and `--slice` as for a build.
Its build record keeps the intended nominals, so the next trial measures the
same targets, and its `revision_of` records the build, trial, and changes it
came from.

Build an enclosure you will print and record under
`evidence/enclosures/<name>/`, beside the fixture evidence, so that
`scripts/backup-evidence.sh` backs up its build record, slice, and trials.
Scratch builds can go anywhere, such as `exports/`, which git ignores.

## Catalogued hardware

| Board | Support | Source |
| --- | --- | --- |
| `ADAFRUIT_FEATHER_RP2040` | Standoffs | Measured from the vendor STEP |
| `ARDUINO_UNO_R4_WIFI` | Standoffs | Provisional: outline, USB-C, and parts from the vendor STEP, holes from the UNO drawing |
| `RASPBERRY_PI_5` | Standoffs | Raspberry Pi's mechanical drawing (RP-008347); parts from the vendor STEP |
| `RASPBERRY_PI_PICO_2` | Standoffs | Datasheet; parts from the vendor STEP |
| `SEEED_XIAO_ESP32_S3` | Cradle | Provisional: DXF outline; thickness and parts from the vendor STEP |

Each board carries its PCB, its USB connector, and every other part as
boxes an enclosure must clear, extracted from the vendor model: headers,
buttons, battery connectors, shield cans, and the pins under the board. So:

- the cavity grows to fit the tallest part and the pins underneath;
- the display is raised above a tall part: `--display-height-mm` defaults
  to `auto`, which keeps the display 8 mm above the board's underside,
  leaving room for its wiring, unless a part under it needs more; then it
  takes the lowest height, in 0.5 mm steps, that clears every part by
  `--board-display-clearance-mm` (the UNO R4 WiFi's ICSP header takes it to
  11.5 mm). The height used is in the summary and the build record. A
  number sets it outright, and one too low is refused;
- standoffs are notched clear of pins under the board; and
- a part that overhangs an edge, like the UNO R4 WiFi's barrel jack, gets
  its own opening in that wall.

A board can also declare wall openings the vendor model cannot show. The
Pi 5's STEP leaves out its micro-HDMI bodies and its microSD card, so its
spec lists every port from Raspberry Pi's drawing, and the card under the
board. Each declared opening is 1.5 mm wider on each side and 1.5 mm taller
than its socket, so a plug's shell passes, and it takes in any part opening
it overlaps, such as the Ethernet jack's LED windows. The USB-C input is
the cable opening, as on every board.

Openings in one wall that would leave less than 2 mm of wall between them,
side by side or one above the other, merge into one opening over both, so
no thin web is left to snap (`--minimum-opening-web-mm`; 0 keeps every
opening apart). On the Pi 5 the Ethernet and both USB pairs, about 1 mm
apart, become one 54.7 mm opening across the back, and the microSD slot
and the power button above it one opening in the front. No other catalogued
board has openings that close.

`scripts/extract-board-components.py` writes the parts to
`src/zcad_core/hardware/data/board-components/`, recording the vendor
model's SHA-256. It merges parts of a similar height lying within 2 mm of
each other and ignores parts under 0.5 mm, so the boxes are slightly
generous. It never merges parts on either side of a mounting hole into one
box over it: the board keeps its holes clear, and such a box would notch or
collide with the standoff there. Re-run it after replacing a vendor model;
it needs the evidence checkout.

| Display | Mounting | Source |
| --- | --- | --- |
| `ADAFRUIT_OLED_128X64_1_3IN` | Screw posts | Adafruit 938 CAD model; active area from the panel datasheet |
| `ADAFRUIT_OLED_128X128_1_5IN` | Screw posts | Adafruit 4741 CAD model; active area from the panel datasheet |
| `ADAFRUIT_EINK_200X200_1_54IN` | Screw posts | Adafruit 4196 CAD model; active area from the panel drawing |
| `REFERENCE_OLED_128X64` | Retainer clips | Vendor-neutral reference with no holes |

The Adafruit displays are modelled in layers, face up: the parts behind the
PCB, the PCB, then the glass panel. So posts land on the PCB beside the
panel, and the window sits over the active area, which is off the panel
centre on all three, away from the panel's flex cable (placed from
Adafruit's board layouts for the OLEDs, and the panel drawing for the
e-ink). The vendor models are in `evidence/`, and a slow test
checks each spec's PCB outline, thickness, and hole spacing against them.
Solder a header on the back and the stack grows; raise the display height
and top clearance to suit.

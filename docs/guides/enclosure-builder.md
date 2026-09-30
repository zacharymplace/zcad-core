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
- `--vent-slots N` (`vent_slots`) cuts N vertical slots, 1.6 mm wide at a
  4 mm pitch, through each long wall that carries no opening, below the
  lid's skirt and clear of the corners.

The builder refuses combinations that do not fit, such as more slots than
a wall holds, or vents on walls too low to fit them under a skirt.

**Mounting.** `--mount keyhole` (`mount="keyhole"`) or `--mount vesa75` / `--mount vesa100` adds four pads under
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

`pass` needs every check to pass and at least one measurement; `revise`
needs a measurement; `fail` needs neither. The record stores each
measurement's deviation from nominal, and it refuses parts whose STL no
longer matches the build record. A completed trial is never overwritten:
`zcad-validation enclosure trial start --build-record .../enclosure.json`
opens the next one.

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

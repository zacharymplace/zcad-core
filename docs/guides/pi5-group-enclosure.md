# Raspberry Pi 5 group enclosure

One base and lid around a row of bays. Each bay holds a Raspberry Pi 5, holds
its place for one, or is an open shelf. Identical units bolt together, so the
row can outgrow the printer's bed.

```bash
zcad-validation enclosure-group build --bays pi5,pi5 \
  --output-directory exports/pi5-pair
```

writes `<name>-base` and `<name>-lid` STEP, STL, and metadata files after
export validation against the printer profile passes, plus a STEP review
model in `review/` (the lid lifted, each Pi as a green envelope). The JSON
summary lists the fit checks and the screws to buy. The command exits
non-zero if a check fails.

## Layout

Every Pi sits portrait:

| Edge | Faces |
| --- | --- |
| Ethernet and USB | the back wall, through one opening per port |
| microSD end | the front wall, through one opening |
| USB-C power and micro-HDMI | a 25 mm service gap on the Pi's right |
| 40-pin header | the previous bay's gap, or the left end |

A power or HDMI plug goes into the gap and its cable bends toward the front,
leaving through an opening at the end of the gap. Every bay repeats the same
slot-then-gap pattern, so any bay can take a Pi.

| Bay | Builds |
| --- | --- |
| `pi5` | Four M2.5 standoffs, port openings, vents. Envelope checked. |
| `reserved` | The same as `pi5`, with no Pi fitted yet. Drop one in later with no reprint. |
| `open` | A flat shelf, `--open-bay-width-mm` wide (40), for an SSD, a switch, or a power supply. Wall openings are cut only where you ask; see [Openings for open bays](#openings-for-open-bays). |

The Pi is held by four M2.5 self-tapping screws through its mounting holes
into the standoffs. The lid screws into six M3 heat-set inserts (corners and
the end of each gap but the last).

## Heights per bay

Each bay can set its own heights, written after its kind:

```bash
zcad-validation enclosure-group build \
  --bays "pi5:standoff=12,pi5:headroom=30" \
  --output-directory exports/mixed
```

- `standoff=<mm>` lifts a Pi off the floor, for a board mounted under it, such
  as an NVMe base. It must be at least 2.0 mm so the microSD card clears the
  floor. An `open` bay has no board and takes none.
- `headroom=<mm>` is the room the bay's parts need above the PCB, for a HAT.
  For an `open` bay it is the height of the shelf's usable space.

A bay that sets neither takes `--standoff-height-mm` and `--headroom-mm`. The
lid is flat, so the box is as tall as its tallest bay needs, and every other
bay gets spare room above its board. The JSON summary lists each bay's
standoff, board height, and `room_above_board_mm`. A bay's port openings and
cable exits follow its own board height. The lid check still applies per bay:
a Pi that reaches the lid fails `hardware_clear_of_lid`.

To leave one bay low and another tall in the same print, you need a stepped
lid; the builder does not make one.

## Openings for open bays

An `open` bay's shelf has solid walls until you ask for a hole, for the cables
of whatever sits on it:

```bash
zcad-validation enclosure-group build \
  --bays "pi5,open:back=20x10@-5/3:front=12x8" \
  --output-directory exports/shelf
```

An opening is `front=<width>x<height>` or `back=<width>x<height>`, optionally
followed by `@<offset>` and `/<bottom>`, all in millimetres:

- `offset` runs along the row from the middle of the shelf (negative is
  left); it defaults to 0.
- `bottom` is the opening's lower edge above the floor's top face; it defaults
  to 0.

So `back=20x10@-5/3` is 20 mm wide and 10 mm tall in the back wall, 5 mm left
of the shelf's middle, starting 3 mm up. In Python it is
`BayOpening("back", 20, 10, offset_mm=-5, bottom_mm=3)` in `Bay.openings`. A bay
can take several openings.

Only the front and back walls take openings; the ends are the join walls. The
builder refuses:

- an opening on a `pi5` or `reserved` bay, whose openings are set by its ports;
- one that leaves under 1 mm of wall to either end of the shelf, or under 1 mm
  under the lid (the box is as tall as its tallest bay needs, so raise
  `headroom` on a bay if the opening must be taller); and
- two openings in one wall that overlap.

## Dividers

A bay can have a divider on its left, between it and the bay before it. The
first bay has none.

```bash
zcad-validation enclosure-group build \
  --bays "pi5,pi5:divider=vents+notch+ties" \
  --output-directory exports/divided
```

A divider is a wall across the enclosure, front to back, 2 mm thick, standing
at the end of the previous bay's gap, 0.75 mm clear of its own bay's header
edge. The previous bay's gap boss sits against it and fuses to it. Tokens, joined by `+`:

| Token | Adds |
| --- | --- |
| `solid` | A plain full-height wall that runs to the lid. Also the default when you give only other tokens. |
| `vents` | Vertical slots near the top, so air passes between bays but line of sight does not. Full height only. |
| `notch` | A 20 x 10 mm pass-through at its own bay's header, rising from that board, for a ribbon or jumper wires. |
| `ties` | Two rows of slot pairs, 4.2 x 2 mm, for zip ties to strap what sits beside the divider. |
| `h12` | A low divider 12 mm tall instead: open at the top, for separating cables. |

In Python it is `Bay("pi5", divider=Divider(vents=True, notch=True))` with
`Divider` from `zcad_core.features.enclosure_group_dividers`. `height_mm` sets
a low divider.

- **What it costs:** each divider adds 2.75 mm to the row (0.75 clearance and
  its 2 mm). The default pair grows from 176 to 178.75 mm, which leaves
  1.25 mm of the A1 mini's 180 mm bed. Its service gap is unchanged, so plugs
  keep their 25 mm.
- **What it is for:** a full-height divider separates the heat of a bay's
  contents from the next bay, and `vents` lets air through while it does.
  A divider does not make a fireproof or electrical barrier: it is 2 mm of
  printed PETG. Do not rely on one to isolate a mains-powered item.
- **Features that crowd each other:** vent slots that would come within 3 mm
  of the notch or a tie slot are left out, so a divider with all three has
  fewer vents.
- **Refused:** a divider on the first bay; `vents` on a low divider; a divider
  as tall as the box (leave the height unset); a notch or tie slots that would
  not leave a millimetre of wall above them.

`GroupDesign` sets `divider_mm` (2), `divider_clearance_mm` (0.75),
`divider_notch_width_mm` (20), and `divider_notch_height_mm` (10).

## Room to grow

- **Within the unit:** build with `reserved` bays now, and give a bay the
  heights an upgrade will need before you print it.
- **Past the bed:** the default pair is 176 x 96 mm. A1 mini's bed is
  180 x 180 mm, so a third bay does not fit and the command says so. Build a
  second unit and bolt it to the first. Each unit's left wall carries two
  heat-set insert bosses and its right wall two clearance holes, so the next
  unit's left wall meets this one's right wall and an M3 x 8 screw crosses
  both walls into the insert. Turn the join features off with
  `--no-join-bolts`.

## Settings

`GroupDesign` (Python) and the matching flags:

- `headroom_mm` (`--headroom-mm`, 18): the default room above each Pi's PCB. It
  clears the 15.6 mm USB stack and the Active Cooler with about 2 mm to spare.
  Raise it for a HAT, and set it before printing: the check
  `hardware_clear_of_lid` fails when the lid meets a Pi. A `Bay` overrides it.
- `service_gap_mm` (25): the space for USB-C and micro-HDMI plugs. Right-angle
  plugs fit in less; under about 17 mm the command refuses.
- `standoff_height_mm` (`--standoff-height-mm`, 4): the default standoff
  height; a `Bay` overrides it.
- `lid_mm` (3), `wall_mm` (2), `floor_mm` (2).
- `vents`: five slots in the lid over each Pi's SoC and cooler.

## From Python

Every command-line option has a Python equivalent. A row is a tuple of bays,
each a kind (`"pi5"`, `"reserved"`, `"open"`) or a `Bay` that adds heights,
openings, or a divider:

```python
from zcad_core.features.enclosure_group import Bay, build_group_enclosure
from zcad_core.features.enclosure_group_dividers import Divider

group = build_group_enclosure(
    ("pi5", Bay("reserved", divider=Divider(vents=True, notch=True))),
)

assert group.passed, group.checks
group.base, group.lid  # CadQuery workplanes, ready to export
```

`examples/pi5_group_enclosure.py` goes on from there: it exports both parts
through the validated pipeline and writes the data for the 3D viewer. The gate
runs it, so it stays current.

## Printing

```bash
zcad-validation enclosure-group build --bays pi5,pi5 \
  --output-directory exports/pi5-pair --slice
```

`--slice` writes print-oriented STLs to `print/` (the base on its floor, the
lid on its outer face) and slices each with Bambu Studio into
`slice/base/` and `slice/lid/`, using the project slicer profile
(`--slicer-profile`). Each part gets a plate of its own: the pair's base and
lid are each 96 mm deep, so together they would not fit the A1 mini's
180 mm bed. The summary reports each plate's print time, filament, and any
slicer warning. Slicing is skipped if a fit check fails.

The default pair, on the A1 mini PETG profile, slices to about 2 h 11 min and
73 g for the base, and 1 h 14 min and 45 g for the lid: about 3.5 hours and
118 g in all. Existing slice output is never overwritten.

## Viewing in 3D

```bash
zcad-validation enclosure-group viewer --output-directory exports/viewer \
  --standalone
python3 -m http.server --directory exports/viewer
```

writes `index.html` and `enclosures.json` into the folder. Open
`http://localhost:8000` (a browser refuses to load the data file from
`file://`). The page shows five standard configurations: the default pair, a
divided pair, a low divider, a raised bay, and a pair with an open shelf. You
can rotate and zoom, set the lid to on, lifted, or off, hide the Pi envelopes,
cut the box open with a plane, and show dimensions: the overall size, and along
the front edge each bay's slot and service gap. It also shows whether the row
fits the A1 mini's bed.

- `--bays` shows your own rows instead, in the syntax of `build --bays`. Repeat
  it for several: `--bays "pi5,pi5:divider=notch" --bays "pi5,open"`.
- Every configuration is built and checked first. A row the builder refuses, or
  one that fails a fit check, stops the command and is named in the error.
- The command never overwrites `index.html` or `enclosures.json`.
- Without `--standalone`, the page is the fragment the Artifact tool wraps when
  you publish it, so publish `index.html` with `enclosures.json` as a
  supporting file. Regenerate the data after any design change: the viewer
  shows a snapshot of the code when you ran the command.
- The page loads its 3D library from cdnjs and jsDelivr, pinned to one version
  with integrity hashes, so it needs a network connection.

## First print checklist

Print the base first and test-fit before printing the lid. With a real Pi 5:

1. **Standoffs and holes:** the Pi drops onto four standoffs and each M2.5
   screw starts in its pilot hole without forcing.
2. **Ports:** Ethernet and both USB pairs line up with their back-wall
   openings, and a plug seats fully. Check the USB-C and micro-HDMI plugs in
   the gap.
3. **microSD:** the card goes in and out through the front opening.
4. **Height:** with an Active Cooler fitted, note the gap between it and where
   the lid will sit. This is the number most worth measuring.
5. **Header:** if you plan to use the 40-pin header, check for room, and for a
   divider notch.

Then print the lid, close it, and check the six screws and the vents. Record
what you measured against `RaspberryPi5Spec` (hole spacing, port centres,
cooler height); those are the numbers to correct in
`hardware/electronics/raspberry_pi.py`.

## What is assumed

The Pi 5 is `RaspberryPi5Spec`, built by hand from the published drawing,
not from a vendor model: the board, the 58 x 49 mm hole pattern, the port
envelopes, the header, the Active Cooler, and the microSD card. Port
positions and the cooler size are the least certain. Print the base, check a
Pi against it before printing the lid, and record it as a trial. If a port
opening is off, edit `BoardPortSpec` in `hardware/electronics/raspberry_pi.py`.

The checks are: the base and lid do not touch, each Pi's envelope clears both
parts, and each part is one solid. They do not check cable bend room or
airflow.

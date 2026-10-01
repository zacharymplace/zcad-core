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
| Ethernet and USB | the back wall, through one opening across all three (they sit about 1 mm apart, too little wall to print; `--minimum-opening-web-mm 0` cuts one per port) |
| microSD end | the front wall, through one opening |
| USB-C power and micro-HDMI | a 25 mm service gap on the Pi's right |
| 40-pin header | the previous bay's gap, or the left end |

A power or HDMI plug goes into the gap and its cable bends toward the front,
leaving through an opening at the end of the gap. Every bay repeats the same
slot-then-gap pattern, so any bay can take a Pi.

| Bay | Builds |
| --- | --- |
| `pi5` | Four M2.5 standoffs, port openings, vents. Envelope and every extracted part checked. |
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

## Hinged and sliding lids

By default the lid screws on. For a row you open often, the lid can hinge or
slide instead, with no screws to lose:

```bash
zcad-validation enclosure-group build --bays pi5,pi5 \
  --lid hinge --headroom-mm 20 --output-directory exports/pi5-hinged
zcad-validation enclosure-group build --bays pi5,pi5 \
  --lid slide --output-directory exports/pi5-slide
```

Neither has the six lid bosses, so the lid has no screw holes and the summary
lists no lid screw.

**Hinge.** The lid hangs from a row of knuckles along the **back wall** and
closes with a snap catch outside the **front wall**. It swings 100 degrees and
the build sweeps that swing through the base and every Pi. The pin is a
**threaded rod** cut to length, with a nut at each end: a row's hinge is longer
than any M3 screw (the summary gives the length, 175 mm for two bays). Two
things to know:

- The knuckles stand on the back wall's top edge, so the Ethernet and USB
  opening must stop 2.5 mm below it. The default headroom puts it 1.4 mm below,
  and the build says so and by how much; `--headroom-mm 20` clears it.
- The catch goes in the widest stretch of front wall clear of the microSD and
  cable-exit openings, so it never sits over one.

The hinge and catch grow the box by about 8 mm behind and 3 mm in front. A hinge
longer than a 250 mm rod (three bays) is refused.

**Slide.** The lid slides along the row in grooves in the front and back walls,
out over one end wall (`--slide-entry positive_x`, the right, by default, or
`negative_x`), and a detent on each edge holds it shut. The long walls are
raised 3.4 mm and thickened 1.6 mm. Know that:

- A row must be at least as wide as it is deep, so a lone bay cannot slide:
  add a bay, or hinge it.
- Dividers stop half a millimetre short of the lid so it rides clear of them.
- A row bolted to a neighbour cannot slide out over the end that meets it: pick
  the free end.
- Front and back wall openings that reach into the groove's wall are refused;
  the Pi's own stay open.

A rack-ear or underside mount works with either lid.

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

Before printing a slice made earlier, run `zcad-validation slice check
exports/pi5-pair`: it reports the slice `stale` if the geometry has changed
since, and `unknown` if it predates slices recording their source, as any
made before the Pi 5 was unmirrored do. Rebuild and slice again in either
case.

## Mounting

`--mount keyhole` (`GroupDesign(mount="keyhole")`) adds four mount pads under
the floor and a keyhole plate as a third part, as the
[enclosure builder](enclosure-builder.md) describes. The pads sit at the
corners of the whole footprint, not under the dividers, so any layout of
bays takes one. A row is one unit's width, so a row split across units
needs a plate for each unit.

`--mount rack` (`GroupDesign(mount="rack")`) builds rack ears instead: two
pads stacked at each end of the front wall, and two flat flanges, exported as
`mount-left` and `mount-right`, that screw to them and reach out to a 19 inch
rack's rails. The flanges are a 1U panel (43.66 mm tall) with three EIA-310
holes each, 465.1 mm apart, and the enclosure sits centred in the rack, 8 mm
behind its face. The pads stand out of the front, so the base is no wider
than before. A pair of bays (176 mm) gives 165 mm ears, which fit the A1
mini's bed. The build refuses an enclosure that is taller than 1U (41.7 mm
with the lid) or wider than the rack's 450.85 mm opening, a pad that would
cover an opening in the front wall, and ears longer than the printer's bed;
one bay is about 88 mm wide and its ears would be about 197 mm, so it needs
a bigger printer. Print each ear flat. No strength is modelled: the two pads
at each end hold the enclosure's weight, and a trial has to show that they
can.

## Vents

`--vent-pattern {slots,hex,round,louvers}` with `--vent-area-mm2 N` cuts the
same sized patterns as the [single-board builder](enclosure-builder.md), with
inlets low in the row's two side walls and outlets in the lid at least as large.
The front and back walls are the long ones here, and they carry the Pis' ports
and microSD openings, so the side walls take the inlets; the cells keep clear of
the row's join bosses and holes, and of the lid's slots over each Pi's fan. For
the pair, `--vent-area-mm2 400` gives 30 hex cells 4 mm across flats in each of
the inlet and outlet zones, about 416 mm2 each, and every check still passes.
The estimate credits no vents, and a group's lid always has slots over a fitted
Pi's fan, so the group is never a closed box for a trial's purposes. There are
no fans in the group enclosure yet, and no trial records for it: those need a
build record, which the group does not write.

## Temperature estimate

The build prints an estimate of the closed row's air temperature under
`thermal`, counting 3.0 W for each fitted Pi 5 (an idle figure from community
measurements; Raspberry Pi publishes none, and no load figure was found) and
nothing for a `reserved` or `open` bay. The pair, at 176 x 96 x 28.4 mm, is
about 0.049 m2, so its two Pis at idle raise the air by about 15 degrees: 40
degrees C from a 25 degree room, which is a minimum, because a loaded Pi
gives off more. Declare what you know with `--power-w` (an SSD, a switch) and
the room with `--ambient-c`. The estimate credits no vents and is off by half
either way; see the [builder guide](enclosure-builder.md#temperature-estimate).
A row estimated past PETG's 60 degree limit is refused unless `--allow-hot`.

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

Its orientation, which side each port and the header are on, is checked against
Raspberry Pi's STEP model, because an earlier version was mirrored left to
right and printing it would have put the USB-C and HDMI cables on the wrong
side. `tests/data/raspberry-pi-5-vendor-features.json` records where the
model puts the Ethernet jack, both USB stacks, the header, USB-C, and the
microSD slot. The test carries them through the one rotation that puts the
Ethernet on the spec's Ethernet edge and requires the enclosure's Pi envelope
to contain each, so a mirrored or turned spec fails. If you replace the model,
re-run `scripts/extract-pi5-vendor-features.py`; a slow test fails when the
recorded numbers no longer match it.

The hole pattern is not centred on the board: like a HAT's, it sits 3.5 mm
from the microSD end, so the holes are at y = -39 and +19 mm about the board
centre, where Raspberry Pi's STEP model has them. An earlier version centred
the pattern, which put every standoff 10 mm off its hole.

The checks are: the base and lid do not touch, each Pi's envelope clears both
parts, each of the Pi's 62 parts extracted from the vendor model clears both
(`parts_clear_of_base`, `parts_clear_of_lid`), and each part is one solid.
The summary's `part_collisions` names any part that fails, as
`bay-0 bottom-45 meets the base`. The parts are checked 0.1 mm smaller a side,
the rounding of the model's boxes. The checks do not cover cable bend room or
airflow.

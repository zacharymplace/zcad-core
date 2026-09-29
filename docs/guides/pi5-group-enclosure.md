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
| USB-C power and micro-HDMI | a 25 mm service gap on the Pi's left |
| 40-pin header | the next bay's gap, or the right end |

A power or HDMI plug goes into the gap and its cable bends toward the front,
leaving through an opening at the end of the gap. Every bay repeats the same
gap-then-slot pattern, so any bay can take a Pi.

| Bay | Builds |
| --- | --- |
| `pi5` | Four M2.5 standoffs, port openings, vents. Envelope checked. |
| `reserved` | The same as `pi5`, with no Pi fitted yet. Drop one in later with no reprint. |
| `open` | A flat shelf, `--open-bay-width-mm` wide (40), for an SSD, a switch, or a power supply. No openings are cut; add your own. |

The Pi is held by four M2.5 self-tapping screws through its mounting holes
into the standoffs. The lid screws into six M3 heat-set inserts (corners and
the start of each gap after the first).

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

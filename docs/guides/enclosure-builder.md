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

**Display retainer.** L-shaped posts at the display's corners locate it
and carry pads its face rests against; a snap clip on each side hooks under
it. The middle of the other two edges stays open for a pin header or flex
cable. Turn it off with `display_retainer=False` (`--no-display-retainer`).

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
  buy (the longest standard length the lid and insert take), and five
  checks: no interference, one solid per part, open screw paths, a plug
  body that clears the floor, and contact only where expected (the board on
  its supports, the display on its pads).

## Catalogued hardware

| Board | Support | Source |
| --- | --- | --- |
| `ADAFRUIT_FEATHER_RP2040` | Standoffs | Measured from the vendor STEP |
| `ARDUINO_UNO_R4_WIFI` | Standoffs | Provisional: outline, USB-C, and parts from the vendor STEP, holes from the UNO drawing |
| `RASPBERRY_PI_PICO_2` | Standoffs | Datasheet; parts from the vendor STEP |
| `SEEED_XIAO_ESP32_S3` | Cradle | Provisional: DXF outline; thickness and parts from the vendor STEP |

Each board carries its PCB, its USB connector, and every other part as
boxes an enclosure must clear, extracted from the vendor model: headers,
buttons, battery connectors, shield cans, and the pins under the board. So:

- the cavity grows to fit the tallest part and the pins underneath;
- a display too close to a tall part is refused (the UNO R4 WiFi's ICSP
  header reaches a display 8 mm above the board; 14 mm clears it);
- standoffs are notched clear of pins under the board; and
- a part that overhangs an edge, like the UNO R4 WiFi's barrel jack, gets
  its own opening in that wall.

`scripts/extract-board-components.py` writes the parts to
`src/zcad_core/hardware/data/board-components/`, recording the vendor
model's SHA-256. It merges parts of a similar height lying within 2 mm of
each other and ignores parts under 0.5 mm, so the boxes are slightly
generous. Re-run it after replacing a vendor model; it needs the evidence
checkout.

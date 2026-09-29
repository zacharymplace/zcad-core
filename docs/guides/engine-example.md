# Engine example

[`examples/pico2_oled_enclosure.py`](https://github.com/zacharymplace/zcad-core/blob/main/examples/pico2_oled_enclosure.py)
uses the core engine without the Validation Lab. It designs a two-part,
screw-together enclosure for a Raspberry Pi Pico 2 under a 128x64 OLED:

1. **Assemble** catalogued hardware with `build_board_display_assembly`,
   placing the display 8 mm above the board.
2. **Check** the assembly with `analyze_board_display_assembly` for
   interference and a 1 mm board-to-display clearance.
3. **Build** the enclosure with `build_enclosure`. It derives the cavity
   and cable opening from the assembly with `derive_enclosure_specification`
   and returns two parts:
    - the **base**: floor and walls, a standoff under each board mounting
      hole, an M3 heat-set insert boss in each corner, and the cable opening
      on the board's USB edge;
    - the **lid**: a plate with a screw clearance hole over each boss and a
      window over the display's active area.
4. **Export** both with `export_parts`, which writes STEP, STL, and per-part
   metadata only after geometry validation against the printer profile
   passes.

```bash
python examples/pico2_oled_enclosure.py exports/pico2-oled-enclosure
```

`EnclosureDesign` sets the wall, floor, and lid thickness, the fastener,
the boss wall, and three clearances between the hardware and the cavity:
`side_clearance_mm` for the walls and corner bosses, `bottom_clearance_mm`
for the standoff height, and `top_clearance_mm` for the gap under the lid.
The builder refuses an enclosure whose material intersects any part of the
assembly. At the default 2 mm side clearance the corner bosses would hit
the Pico 2, so the example uses 5 mm at the sides, 3 mm standoffs, and a
1 mm gap under the lid, giving a 42 x 67 x 18 mm base and a 2 mm lid.

The gate runs the example (`tests/test_examples.py`), so it stays in step
with the API. Start a new design by copying it and swapping the hardware,
placements, and design settings.

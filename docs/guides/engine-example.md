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
      hole, an M3 heat-set insert boss in each corner, and a cable opening
      sized for the plug on the board's USB edge;
    - the **lid**: a plate with a screw clearance hole over each boss, a
      window over the display's active area, and a retainer that holds the
      display under it.
4. **Export** both with `export_parts`, which writes STEP, STL, and per-part
   metadata only after geometry validation against the printer profile
   passes.
5. **Review** them with `export_enclosure_review`, which writes an exploded
   GLB, SVG views, and a report of clearances, checks, and screws to buy.

```bash
python examples/pico2_oled_enclosure.py exports/pico2-oled-enclosure
```

The example sets 3 mm standoffs and a 1 mm gap between the display and the
lid, and leaves the side clearance automatic: the builder widens the long
axis until the corner bosses clear the board and display, giving a
36 x 77 x 18 mm base and a 2 mm lid. The
[enclosure builder guide](enclosure-builder.md) covers every setting, the
other catalogued boards, and the same build from the command line.

The gate runs the example (`tests/test_examples.py`), so it stays in step
with the API. Start a new design by copying it and swapping the hardware,
placements, and design settings.

# Engine example

[`examples/pico2_oled_tray.py`](https://github.com/zacharymplace/zcad-core/blob/main/examples/pico2_oled_tray.py)
uses the core engine without the Validation Lab. It designs an open-top
enclosure tray for a Raspberry Pi Pico 2 under a 128x64 OLED:

1. **Assemble** catalogued hardware with `build_board_display_assembly`,
   placing the display 8 mm above the board.
2. **Check** the assembly with `analyze_board_display_assembly` for
   interference and a 1 mm board-to-display clearance.
3. **Derive** the enclosure with `derive_enclosure_specification`: a
   32 x 57 x 16 mm cavity and a 9.9 x 4.2 mm cable opening on the board's
   USB edge.
4. **Build** the tray: 2 mm walls and floor around the cavity, with the
   opening cut by `cut_connector_opening`.
5. **Export** it with `export_parts`, which writes STEP, STL, and per-part
   metadata only after geometry validation against the printer profile
   passes.

```bash
python examples/pico2_oled_tray.py exports/pico2-oled-tray
```

The gate runs the example (`tests/test_examples.py`), so it stays in step
with the API. Start a new design by copying it and swapping the hardware,
placements, and tray features.

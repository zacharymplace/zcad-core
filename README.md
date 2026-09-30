# zcad-core

The reusable CAD engine powering parametric design systems.

Responsibilities:

- Geometry generation
- Feature library
- Assemblies
- Validation
- Manufacturing profiles
- Metadata
- Export pipeline
- Hardware abstractions
- Board-retention strategies and the Validation Lab
- Printable enclosures built around catalogued hardware, including one box
  for a row of Raspberry Pi 5 boards
- Slicing and print-trial records
- An interactive 3D viewer of the enclosures

This repository intentionally contains no product-specific models.

## Getting started

- `zcad-validation enclosure build --board raspberry_pi_pico_2 --review
  --output-directory exports/pico2` builds a printable, screw-together
  enclosure; see `docs/guides/enclosure-builder.md`.
- `zcad-validation enclosure-group build --bays pi5,pi5 --slice
  --output-directory exports/pi5-pair` builds one enclosure around two
  Raspberry Pi 5 boards, with bays that hold a Pi, keep a place for one, or
  hold other hardware, and slices it; `enclosure-group viewer` writes a 3D
  viewer of it. See `docs/guides/pi5-group-enclosure.md`.
- `examples/pico2_oled_enclosure.py` designs, checks, and exports an
  enclosure with the core engine from Python.
- `docs/guides/validation-lab-workflow.md` takes a board from its vendor STEP
  model to a promoted, validated fixture candidate.

## Documentation

Generated API reference and architecture docs live in `docs/` (built with
[MkDocs](https://www.mkdocs.org/) + [mkdocstrings](https://mkdocstrings.github.io/)):

```bash
pip install -e ".[docs]"
mkdocs serve
```


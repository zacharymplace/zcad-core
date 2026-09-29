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

This repository intentionally contains no product-specific models.

## Getting started

- `examples/pico2_oled_enclosure.py` designs, checks, and exports a
  screw-together enclosure with the core engine.
- `docs/guides/validation-lab-workflow.md` takes a board from its vendor STEP
  model to a promoted, validated fixture candidate.

## Documentation

Generated API reference and architecture docs live in `docs/` (built with
[MkDocs](https://www.mkdocs.org/) + [mkdocstrings](https://mkdocstrings.github.io/)):

```bash
pip install -e ".[docs]"
mkdocs serve
```


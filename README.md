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
- Rendering
- Hardware abstractions

This repository intentionally contains no product-specific models.

## Documentation

Generated API reference and architecture docs live in `docs/` (built with
[MkDocs](https://www.mkdocs.org/) + [mkdocstrings](https://mkdocstrings.github.io/)):

```bash
pip install -e ".[docs]"
mkdocs serve
```


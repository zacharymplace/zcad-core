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

## Where to go next

- **[Architecture](architecture.md)** — package layout and the retention
  strategy's design history.
- **[Roadmaps](roadmaps/validation-lab.md)** — the Validation Lab
  evidence and revision-history subsystem: what it tracks, why, and
  what's implemented so far.
- **[API Reference](reference/index.md)** — generated from the source
  docstrings, organized by package.

## Installation

```bash
pip install -e ".[dev]"
```

## Command-line interface

The `zcad-validation` console script drives the Validation Lab
lifecycle - registering targets and candidates, running trials,
comparing revisions, and promoting a preferred one. See the
[`cli`](reference/cli.md) reference for every subcommand.

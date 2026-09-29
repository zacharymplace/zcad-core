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

## Where to go next

- **[Validation Lab workflow](guides/validation-lab-workflow.md)** — take a
  board from its vendor STEP model to a promoted fixture candidate, step by
  step.
- **[Engine example](guides/engine-example.md)** — design, check, and
  export an enclosure with the core engine.
- **[Architecture](architecture.md)** — package layout and the retention
  strategy's design history.
- **[Roadmaps](roadmaps/validation-lab.md)** — the Validation Lab
  evidence and revision-history subsystem: what it tracks, why, and
  what's implemented so far.
- **[API Reference](reference/index.md)** — generated from the source
  docstrings, organized by package.

## Installation

Development and CI use Python 3.11, the oldest version the package supports,
so the local gate matches CI:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Command-line interface

The `zcad-validation` console script drives the Validation Lab
lifecycle - registering targets and candidates, running trials,
comparing revisions, and promoting a preferred one. See the
[`cli`](reference/cli.md) reference for every subcommand.

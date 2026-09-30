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

## Where to go next

- **[Validation Lab workflow](guides/validation-lab-workflow.md)** — take a
  board from its vendor STEP model to a promoted fixture candidate, step by
  step.
- **[Enclosure builder](guides/enclosure-builder.md)** — build a
  screw-together enclosure for a catalogued board and display, slice it,
  and record how the print fitted, from the command line.
- **[Pi 5 group enclosure](guides/pi5-group-enclosure.md)** — build one
  enclosure around a row of Raspberry Pi 5 boards, with room to add more,
  slice it, view it in 3D, and check what to test on the first print.
- **[Engine example](guides/engine-example.md)** — design, check, and
  export an enclosure with the core engine from Python.
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

The `zcad-validation` console script drives two things. The Validation Lab
lifecycle: registering targets and candidates, running trials, comparing
revisions, and promoting a preferred one. And the enclosure builders: `enclosure`
builds, reviews, slices, and revises a single-board enclosure, and records how
its print fitted; `enclosure-group` builds, slices, and shows one enclosure
around a row of Raspberry Pi 5 boards. `compensation` derives print
compensation from trial measurements. See the [`cli`](reference/cli.md)
reference for every subcommand.

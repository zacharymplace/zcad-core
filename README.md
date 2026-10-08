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
- Boards of your own from a board file, and the guides, test fixtures,
  holding nests, insert jigs and stackable items built round them
- Wearables: caliper captures of sealed devices, the cradles and cases that
  hold them, and snap shells for the Dexcom G7 and Tandem Mobi
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
- `zcad-validation holder build` builds a cup that hangs an object on a wall, from
  a caliper capture of it or its STEP model, on screws, keyholes, a pegboard or an
  adhesive pad, with retaining tabs if it needs them; see
  `docs/guides/object-holder.md`.
- `zcad-validation gridfinity bin` and `gridfinity baseplate` build parts that
  keep to Gridfinity's published figures; see `docs/guides/gridfinity.md`.
- `examples/kicad_board.py` imports a KiCad board (its outline, holes, parts,
  cable connector and test points) and builds an enclosure and a test fixture
  for it; see `docs/guides/board-file.md`.
- `docs/guides/validation-lab-workflow.md` takes a board from its vendor STEP
  model to a promoted, validated fixture candidate.
- `zcad-validation coupon build --slice` builds a calibration coupon, a
  32-minute print whose measurements tell every build how this printer prints
  holes, gaps and bridges, and how far its plastic bends before it breaks; see
  `docs/guides/calibration-coupon.md`.
- `zcad-validation capture template` starts a caliper capture of a sealed
  device, and `zcad-validation housing build` builds something to wear it in;
  see `docs/guides/wearable-capture.md` and `docs/guides/wearable-housing.md`.

## Developing

```bash
pip install -e ".[dev,docs]" -c constraints.txt
git config core.hooksPath .githooks
scripts/check.sh
```

`constraints.txt` pins every package at the version the tests pass with, so
the environment the evidence was made with can be rebuilt; the test suite
fails if the installed versions drift from it. After upgrading a package on
purpose, run `scripts/lock-dependencies.py` and commit the new pins with
whatever the upgrade changed.

GitHub Actions is disabled for this account, so `scripts/check.sh` is the
gate: ruff format, ruff check, mypy over `src`, `scripts`, `tests` and
`examples`, and the full test suite. The pre-push hook runs it and blocks a
push that fails, and a branch or tag must be the checked-out commit, so the
gates test what is pushed; a tag on a commit already on GitHub, such as a
release tag on main, needs no gates. `scripts/check.sh --fast` skips the slow
tests for a quicker loop. The full gate takes five to eight minutes.

`evidence/` holds the Validation Lab's records, trials and vendor models. It
is ignored here and backed up to its own private repository with
`scripts/backup-evidence.sh`, which refuses a file that still has its
template's `needs_review` line, or a file over 95 MB that Git LFS does not
track, since GitHub refuses a file over 100 MB in git. The repository does not
use LFS yet; once it does, the script refuses to run without git-lfs. The
tests that read it skip without it, so in
a linked worktree, link it before running the suite:

```bash
ln -s "$(git rev-parse --path-format=absolute --git-common-dir)/../evidence" evidence
```

## Documentation

Generated API reference and architecture docs live in `docs/` (built with
[MkDocs](https://www.mkdocs.org/) + [mkdocstrings](https://mkdocstrings.github.io/)):

```bash
mkdocs serve
```

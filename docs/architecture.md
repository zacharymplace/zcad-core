# Architecture

```text
src/zcad_core/
├── assemblies    board, display, and connector assemblies; enclosure derivation
├── exporters     validated STEP/STL export with staged publication
├── features      enclosure features; the single-board and Pi 5 group enclosure
│                 builders, their reviews, print trials, and the 3D viewer
├── geometry      board-edge analysis and fail-closed solid intersection
├── hardware      catalogued boards (with vendor-model parts), displays, fasteners
├── metadata      per-part build records
├── printing      slicing parts for the printer (Bambu Studio)
├── profiles      printer, material, and slicer profile loading
├── retention     retention strategies and the Validation Lab
├── validation    design, geometry, and STL checks
└── cli/          the zcad-validation command, one module per command group
```

Product libraries live outside this repository.

## Two enclosure builders

`features.enclosure` builds a base and lid around one board and an optional
display, from a `DeviceAssembly` derived from the catalog.

`features.enclosure_group` builds one base and lid around a row of bays, each
holding a Raspberry Pi 5, keeping a place for one, or left open for other
hardware. It works from a hand-built `RaspberryPi5Spec` (from Raspberry Pi's
mechanical drawings, with its orientation taken from their STEP model) rather
than a derived assembly, and reuses the same insert-boss, standoff, and
wall-opening features. `enclosure_group` holds the builder and re-exports the
public names, so callers import from it alone. The rest is split by concern:

| Module | Holds |
| --- | --- |
| `enclosure_group_model` | the design, bay, layout, and result types |
| `enclosure_group_layout` | where each bay sits along the row and how tall it is |
| `enclosure_group_envelope` | a Pi 5 as boxes, and the box helpers |
| `enclosure_group_openings` | a Pi's wall openings, and an open bay's |
| `enclosure_group_dividers` | dividers between bays |
| `enclosure_group_viewer` | the data and page for the 3D viewer |

## Where data lives

- `hardware/data/board-components/`: each board's parts as boxes, extracted from
  its vendor STEP model by `scripts/extract-board-components.py`.
- `features/data/`: the page template for the 3D viewer.
- `tests/data/`: the Pi 5's orientation anchors from the vendor model (the
  Ethernet jack, USB stacks, header, USB-C, and microSD slot), recorded by
  `scripts/extract-pi5-vendor-features.py`. `tests/hardware/test_raspberry_pi5_orientation.py`
  checks the enclosure's Pi envelope against them, so a mirrored or turned spec
  fails; it runs without `evidence/`, and a slow test checks the anchors against
  the model where it is present.
- `evidence/`: vendor models and Validation Lab evidence, local to a checkout
  and not in this repository. The tests that need it are marked `slow` and skip
  where it is absent.

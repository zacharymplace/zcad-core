# Architecture

```text
src/zcad_core/
├── assemblies    board, display, and connector assemblies; enclosure derivation
├── exporters     validated STEP/STL export with staged publication
├── features      enclosure features, the enclosure builder, and its review
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

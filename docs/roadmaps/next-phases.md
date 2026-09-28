# Next Phases Roadmap

## Purpose

This roadmap sequences work after the completed Validation Lab phases and the
September 2026 export-validation work. It builds on both tracks rather than
adding new retention strategies or hardware families.

## Current position (2026-09-27)

### Track 1 — Validation Lab (complete in software)

- Target registry, immutable candidate revisions, and physical trials
- Revision lineage, comparison, and recommendation
- Promotion and publication gate
- `zcad-validation` CLI
- Corner-capture and edge-clip retention with installation-path analysis
- Snap-shell retention for wearables
- Targets: Feather RP2040, Pico 2, UNO R4 WiFi, XIAO ESP32-S3,
  Dexcom G7 (synthetic), Tandem Mobi (synthetic)

### Track 2 — Validated export pipeline

- Complete export-geometry inspection with structured checks
- Unified design validation reports, including XY build-volume orientation
- Application feature-check hook run before export
- STEP re-import with feature checks re-run on the imported geometry
- Whole-set staging with rollback on failed publication
- Strict binary STL topology validation
- STL vertical clearance and continuous material-coverage probes

### Gaps

1. **Physical evidence is the bottleneck.** All four recorded physical trials
   are `revise` with `pending-selection` printer and material profiles. No
   candidate has been promoted, so nothing is publication-eligible. Feather
   r003 has a complete design-review and slicing-readiness package but no
   trial.
2. **The tracks are disconnected.** Validation Lab fixture, retention STEP,
   and design-review outputs are written directly with `cq.exporters`, so
   candidate evidence does not receive the export pipeline's geometry, STEP
   round-trip, or STL checks.
3. **Gate drift.** Track 2 landed with ruff format, lint, and mypy failures,
   and `metadata/systems-builder-lifecycle.json` still describes the project
   as held at an earlier commit. Phase 0 resolves this.

## Operating principles

The Validation Lab principles continue to apply. In addition:

1. `main` stays green on format, lint, types, and tests.
2. Every artifact that becomes candidate evidence passes through the
   validated export pipeline.
3. New validation rules never rewrite historical evidence; they produce new,
   versioned re-validation records.
4. Software work does not outrun physical evidence by more than one phase.

## Phase 0 — Restore the gate

### Goal

Return `main` to a fully passing CI state and record the current lifecycle.

### Deliverables

- ruff format and lint clean, including justified handling of intentional
  fail-closed broad exception handlers
- mypy clean for `validation/stl_mesh.py` and `exporters/service.py`
- lifecycle metadata updated to the current commit with export-validation
  capabilities

### Exit criteria

- `ruff format --check`, `ruff check`, `mypy src`, and `pytest` all pass.
- Lifecycle metadata references the current commit and capabilities.

## Phase 1 — Route Validation Lab through the validated export pipeline

### Goal

Give every candidate the same automated guarantees as any other export.

### Deliverables

- fixture, retention STEP, and design-review exports produced via
  `export_parts`
- retention-specific feature and STL feature validators (for example,
  clip clearance and wall material probes)
- a versioned `export_validation` section in `automated-validation.json`
- promotion eligibility requires a passing export-validation record
- `zcad-validation candidate revalidate` producing an append-only
  re-validation record for existing candidates

### Status

Slice 1 complete:

- `ExportValidationRecord` contract with append-only `vNNN` runs, bound to
  the candidate's `output_sha256`
- `zcad-validation candidate revalidate`
- promotion requires a verified export-validation record; sources and
  outputs are re-hashed at promotion time
- `candidate promote` derives automated validation from the candidate's
  recorded decision; `--automated-validation-passed` is removed

Revalidating the existing candidates against the A1 mini profile passes all
of them except `seeed-xiao-esp32s3-corner-capture-r001`. The failure comes
from the vendor board, not the generated arms. Retention STEPs embed the PCB
solid from the source model. Seeed's XIAO PCB solid has six shells and a
0.01 mm sliver face beside a plated hole, so it meshes non-manifold. The
generated retention solids and the printable fixture both pass.

Slice 2 complete: `candidate revalidate --target-manifest` separates the
embedded PCB from the generated geometry by matching its volume and
bounding box. Face counts are not compared, because generation merges
coplanar board faces. The board is recorded as a non-gating
`reference_board` artifact (record schema 1.1.0; 1.0.0 records still load).
With the target supplied, all six board-embedding candidates pass, and
XIAO's board defect remains visible as a non-gating failure.

Slice 3 complete: export validation runs automatically when a candidate is
created, with its run written to `export-validation/` beside the manifest:

- `candidate register` now requires `--printer-profile`. The embedded
  board is separated out unless `--no-embedded-board` is passed.
- `register_artifact_backed_revision` requires `printer_profile` and returns
  the record.
- The wearable snap-shell build scripts validate the candidates they
  register.
- `candidate derive` requires the parent's `--retention-step` (checked
  against its hash before anything is written) and `--printer-profile`.
  It accepts `--target-manifest` to separate the embedded board.

A failing run blocks promotion, not registration.

Slice 4 complete: retention mesh probes run on every gating artifact's
exported STL:

- `retention_supported_bodies`: every connected body rests on the build
  plane
- `retention_board_top_clearance`: nothing within `board_clearance_mm`
  above the reference board's footprint
- `retention_board_capture`: some material lies above the board footprint,
  and the smallest vertical play is recorded

When no reference board is supplied, the two board checks report
`NOT_CHECKED`.

Finding: every corner-capture and edge-clip candidate fails
`retention_supported_bodies`. The generators build each ledge or clip as a
separate body that stops `board_clearance_mm / 2` short of its walls, so in
both the retention STEP and the printable fixture the ledges float
1.8–2.5 mm above the base. None of the recorded trials were printed, so no
physical run has hit this yet. Measured vertical play is 0.85–1.1 mm for
corner capture and 2.46 mm for the UNO R4 edge clip. The snap-shell
wearables pass.

### Exit criteria

- New candidates carry export-validation evidence.
- Existing candidates can be re-validated without modifying original
  evidence.
- A candidate with failing export validation cannot be promoted.

## Phase 2 — Close the physical loop on one target

### Goal

Produce the first promoted, publication-eligible candidate.

### Prerequisite

- Fix the corner-capture and edge-clip generators so ledges and clips are
  fused to their walls, then regenerate candidates that pass
  `retention_supported_bodies`. Do not print existing candidates first:
  their ledges are unsupported islands.

### Deliverables

- selected printer and material profiles replacing `pending-selection`
  (Bambu A1 mini slicing readiness already exists)
- Feather RP2040 r003 printed and recorded through `trial start` and
  `trial complete` with dimensional measurements
- a pass promotes r003; a revise derives r004 from measured deltas

### Exit criteria

- One candidate reaches `physically_verified`, `preferred`, and
  `publication_eligible` through supported commands only.

## Phase 3 — Measurement feedback

### Goal

Make revisions follow from measured evidence rather than manual tuning.

### Deliverables

- predicted-versus-measured reports for clearance, overhang, and wall
  dimensions across trials
- per printer/material compensation profiles derived from trial data
- candidate derivation that applies compensation and records it in the
  parameter delta

### Exit criteria

- Each revision's parameter delta traces to specific measurements.
- Compensation profiles are versioned and referenced by candidates.

## Phase 4 — Retention-strategy breadth

### Goal

Prove the physical loop for each retention strategy.

### Deliverables

- Phase 2 repeated for Pico 2 (corner capture), UNO R4 WiFi (edge clip),
  and XIAO ESP32-S3
- wearable targets moved from synthetic to measured or official models when
  source data is available

### Exit criteria

- At least one promoted candidate per retention strategy.

## Phase 5 — Publication and downstream integration

### Goal

Make promoted candidates consumable by product repositories.

### Deliverables

- governed evidence package format defining which records move from the
  local `evidence/` store into tracked, published form
- metadata publication for promoted candidates only
- documented integration contract for downstream product libraries

### Exit criteria

- A product repository consumes a published candidate using only the
  documented contract.

## Explicitly deferred

- additional retention strategies
- finite-element analysis
- automatic slicer integration
- image or photo analysis
- web dashboards

These remain downstream of the first promoted candidate.

# Next Phases Roadmap

## Purpose

This roadmap sequences work after the completed Validation Lab phases and the
September 2026 export-validation work. It builds on both tracks rather than
adding new retention strategies or hardware families.

## Current position (2026-09-28)

| Phase | Status |
|---|---|
| 0 — Restore the gate | Complete |
| 1 — Route Validation Lab through the export pipeline | Complete |
| 2 — Close the physical loop | Pre-print complete for four candidates; blocked on printer access |
| 3 — Measurement feedback | Not started; needs Phase 2 trial data |
| 4 — Retention-strategy breadth | Pre-print complete for Pico 2, XIAO, and UNO R4; prints pending |
| 5 — Publication and downstream integration | Not started |

Four candidates are ready to print. Each has passing export validation, a
passing design review, slicing readiness, a Bambu Studio slice, and an open
pending trial (see Phase 2):

- `adafruit-feather-rp2040-corner-capture-r004`
- `raspberry-pi-pico-2-corner-capture-r002`
- `seeed-xiao-esp32s3-corner-capture-r003`
- `arduino-uno-r4-wifi-edge-clip-r004`

No candidate has been printed or promoted yet, and nothing is
publication-eligible.

### Blockers and open items

1. **No printer access.** Phase 2 needs a print and test fit of each
   candidate, recorded with `zcad-validation trial complete`.
2. **Human visual reviews are outstanding** for all four candidates. The
   review of Feather r003 passed geometry whose ledges were floating, so these
   reviews should examine the fused ledges specifically.
3. **GitHub Actions is disabled for the account**, so CI never runs on
   GitHub. The same gates run locally: `scripts/check.sh`, enforced by the
   `.githooks/pre-push` hook (enable per checkout with
   `git config core.hooksPath .githooks`).

### Tracks

- **Validation Lab** (complete in software): target registry, immutable
  candidate revisions, physical trials with an explicit pending state,
  lineage, comparison, promotion and publication gating, and the
  `zcad-validation` CLI. It covers corner-capture, edge-clip, and snap-shell
  retention across the Feather RP2040, Pico 2, UNO R4 WiFi, XIAO ESP32-S3,
  Dexcom G7 (synthetic), and Tandem Mobi (synthetic) targets.
- **Validated export pipeline**: geometry inspection, design validation
  reports, STEP round-trip and STL topology checks, staged publication with
  rollback, and STL clearance and material probes. As of Phase 1, every
  Validation Lab candidate passes through it.

### Gaps closed since 2026-09-27

- The gate is green again, and a pre-push hook keeps it that way (Phase 0).
- Candidate evidence goes through the export pipeline, and promotion depends
  on a verified export-validation record rather than a CLI flag (Phase 1).
- Export validation and the design review found three fixture defects that
  would have failed on the first print: floating ledges, geometry built from
  the wrong board height, and through-hole pins passing into the fixture
  base. All three are fixed, and the candidates were regenerated (Phase 2
  prerequisite).

## Operating principles

The Validation Lab principles continue to apply. In addition:

1. `main` stays green on format, lint, types, and tests, enforced by the
   local pre-push hook while GitHub Actions is unavailable.
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

### Status

Complete. The lifecycle metadata was last updated for Phase 2.

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

Complete. All three exit criteria are met. The slice notes below record what
was found at each step.

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
wearables pass. The floating ledges, and the board-height bug behind the
larger play values, were fixed under the Phase 2 prerequisite.

### Exit criteria

- New candidates carry export-validation evidence.
- Existing candidates can be re-validated without modifying original
  evidence.
- A candidate with failing export validation cannot be promoted.

## Phase 2 — Close the physical loop on one target

### Goal

Produce the first promoted, publication-eligible candidate.

### Prerequisite (met)

Generators 1.1.0–1.3.0 fixed three fixture defects found by export
validation and the design review:

- 1.1.0 fuses ledges and clips to their walls, so they no longer print as
  floating islands.
- 1.2.0 builds capture geometry and the fixture base up from the PCB's
  underside. Vendor models place boards away from z = 0: the UNO R4 at
  z −1.6..0 and the XIAO at −0.25..1.0.
- 1.3.0 cuts clearance holes through the base under parts that reach more
  than 0.05 mm below the PCB, such as the UNO R4's through-hole headers and
  power jack.

The design review's interference check now fails closed: it takes the
largest overlap across several boolean formulations. The old check reported
0 mm³ for the XIAO's multi-shell vendor PCB, which actually overlapped its
base by 88.7 mm³. The review accepts bottom-side pads up to 0.05 mm proud of
the PCB as seating contact.

Print-ready candidates, each with passing export validation, design review,
and slicing readiness, a Bambu Studio slice, and an open trial-001:

| Candidate | Slice (A1 mini, PETG) | Vertical play |
|---|---|---|
| `adafruit-feather-rp2040-corner-capture-r004` | 9 min, 3.70 g | 0.90 mm |
| `raspberry-pi-pico-2-corner-capture-r002` | 8 min, 3.45 g | 0.85 mm |
| `seeed-xiao-esp32s3-corner-capture-r003` | 5 min, 1.44 g | 0.85 mm |
| `arduino-uno-r4-wifi-edge-clip-r004` | 17 min, 8.61 g | 0.85 mm |

Do not print superseded candidates. XIAO r002's unregistered placeholder
trial was removed.

### Deliverables

- [x] Printer and material profiles selected in place of `pending-selection`.
  Trials record `bambu-lab-a1-mini`, `petg`, and
  `bambu-studio-a1-mini-petg-validation`.
- [x] Pre-print packages from `scripts/prepare-candidate-for-print.py` and
  slices from `scripts/slice-candidate-fixture.py`
- [x] Trial records that cannot mislead: pending trials have an explicit
  pending state, and `trial complete` refuses a `pass` disposition unless
  every check passed.
- [ ] Human visual review of each candidate's design-review package
- [ ] Feather RP2040 r004 printed and recorded through `trial complete`,
  with dimensional measurements
- [ ] A pass promotes r004; a revise derives r005 from measured deltas.

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
  and XIAO ESP32-S3. Their pre-print packages are complete (Pico 2 r002,
  UNO R4 r004, and XIAO r003), so they can be printed in the same session as
  Feather r004.
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
- automatic slicer integration in the generation pipeline
  (`scripts/slice-candidate-fixture.py` is run by hand)
- image or photo analysis
- web dashboards

These remain downstream of the first promoted candidate.

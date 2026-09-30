# Next Phases Roadmap

## Purpose

This roadmap sequences work after the completed Validation Lab phases and the
September 2026 export-validation work. It builds on both tracks rather than
adding new retention strategies or hardware families.

## Current position (2026-09-29)

| Phase | Status |
|---|---|
| 0 — Restore the gate | Complete |
| 1 — Route Validation Lab through the export pipeline | Complete |
| 2 — Close the physical loop | Pre-print and visual review complete for four candidates; blocked on printer access |
| 3 — Measurement feedback | Built for fixtures and enclosures; needs Phase 2 trial data |
| 4 — Retention-strategy breadth | Pre-print and visual review complete for Pico 2, XIAO, and UNO R4; prints pending |
| 5 — Publication and downstream integration | Not started |

Four candidates are ready to print. Each has passing export validation, a
passing design review, a passing human visual review, slicing readiness, a
Bambu Studio slice, and an open pending trial (see Phase 2):

- `adafruit-feather-rp2040-corner-capture-r004`
- `raspberry-pi-pico-2-corner-capture-r002`
- `seeed-xiao-esp32s3-corner-capture-r003`
- `arduino-uno-r4-wifi-edge-clip-r005`

No candidate has been printed or promoted yet, and nothing is
publication-eligible.

### Blockers and open items

1. **No printer access.** Phase 2 needs a print and test fit of each
   candidate, recorded with `zcad-validation trial complete`. An enclosure
   should go on the same print run (see the enclosure builder below), and the
   Pi 5 group enclosure's base is the one worth printing first (see its section
   below).
2. **GitHub Actions is disabled for the account**, so CI never runs on
   GitHub. The same gates run locally: `scripts/check.sh`, enforced by the
   `.githooks/pre-push` hook (enable per checkout with
   `git config core.hooksPath .githooks`). The hook is also the only place
   the tests that load vendor STEP models from `evidence/` run, since they
   skip wherever `evidence/` is absent, as it is in a linked worktree; they
   are marked `slow`, and
   `scripts/check.sh --fast` skips them for a quicker local loop. Tests run
   in parallel with pytest-xdist: the full gate takes about a minute and
   `--fast` under 40 seconds (2026-09-29).

### Visual reviews (2026-09-28)

All four print-ready candidates passed a human visual review, recorded with
`zcad-validation review complete`, with reservations. Each review measured
the design-review STEP rather than relying on the rendered views alone.

The review of UNO R4 r004 recorded `revise`: its clip ended flush
(0.000 mm) against a header housing, which the design review missed because
flush faces overlap by zero volume. Generator 1.4.0 fixed the cause and
r005 replaced it (see Phase 2).

Each review's reservations are for its physical trial to settle:

| Candidate | Check when printed |
|---|---|
| Feather RP2040 r004 | USB-C plug seats past the base, which extends 0.85 mm beyond the receptacle face |
| Pico 2 r002 | Micro-USB plug seats past a 0.70 mm base lip that sits 0.20 mm below the receptacle; the likeliest plug interference |
| XIAO ESP32-S3 r003 | A diagonal push does not slide the board out (planar diagonal paths are collision-free and engagement is 0.3 mm); the 0.261 mm gap between a capture and the part beside USB-C; a 0.47 mm USB-C lip |
| UNO R4 WiFi r005 | The 0.25 mm clip-to-header gap; lift at the unclipped positive_y edge, which relies on pin friction; a 1.14 mm USB-C lip |

The base lip under an edge connector appears on all four boards: the
fixture's 2 mm perimeter margin runs under any connector that overhangs the
PCB edge. If the trials confirm it blocks plugs, fix it once in the
generator with a relief under overhanging connectors.

### Tracks

- **Validation Lab** (complete in software): target registry, immutable
  candidate revisions, physical trials with an explicit pending state,
  lineage, comparison, promotion and publication gating, and the
  `zcad-validation` CLI. It covers corner-capture, edge-clip, and snap-shell
  retention across the Feather RP2040, Pico 2, UNO R4 WiFi, XIAO ESP32-S3,
  Dexcom G7 (synthetic), and Tandem Mobi (synthetic) targets.
- **Enclosure builder** (new, 2026-09-29; see below): screw-together
  enclosures built from catalogued hardware, from Python or
  `zcad-validation enclosure build`.
- **Pi 5 group enclosure** (new, 2026-09-29; see below): one enclosure around
  a row of Raspberry Pi 5 boards, with bays that hold a Pi, keep a place for
  one, or hold other hardware, from `zcad-validation enclosure-group`.
- **Validated export pipeline**: geometry inspection, design validation
  reports, STEP round-trip and STL topology checks, staged publication with
  rollback, and STL clearance and material probes. As of Phase 1, every
  Validation Lab candidate passes through it.

### Enclosure builder (2026-09-29)

A second use of the engine, beside the Validation Lab: `build_enclosure`
turns a board, and optionally a display, into a printable base and lid.
Guide: `docs/guides/enclosure-builder.md`.

- **Base**: floor and walls, an M3 heat-set insert boss in each corner,
  board standoffs (rectangular or irregular hole patterns) or a snap-in
  cradle for a board without holes, and a wall opening sized for the
  cable's moulded plug, plus one for any part reached through a wall.
- **Lid**: screw holes over the bosses, a display window, and a retainer
  (corner posts, face pads, snap clips) that holds the display.
- **Automatic side clearance**: widens X and Y separately until the bosses
  clear the hardware; separate bottom and top clearances.
- **Board parts from vendor models**: `scripts/extract-board-components.py`
  turns each vendor STEP's parts into boxes the enclosure must clear, so
  cavities fit headers, buttons, jacks, and under-board pins, and a display
  too close to a part is refused.
- **Review package**: an exploded GLB, SVG views, and a report of
  clearances, five checks, and the screws to buy (`--review`).
- **Catalog**: Feather RP2040, Pico 2, UNO R4 WiFi (provisional holes), and
  XIAO ESP32-S3; Adafruit's 1.3" and 1.5" OLEDs and 1.54" e-ink, which
  screw to lid posts, and a vendor-neutral OLED held by clips.

Open items, in order:

1. **Print one enclosure** (Pico 2 or XIAO) with the fixture trials: the
   snap clips, the plug opening, the insert bosses, and the display
   mounts are unproven in plastic. `enclosure build --slice` produces the
   plate's G-code and opens trial-001; record the print with
   `enclosure trial complete`, then `enclosure revise` proposes and builds
   the next revision from its measurements.
2. **Lid options**: snap-fit lid, locating lip, countersunk holes, vents.

### Pi 5 group enclosure (2026-09-29)

One base and lid around a row of bays, from `build_group_enclosure` or
`zcad-validation enclosure-group build`. Guide:
`docs/guides/pi5-group-enclosure.md`.

- **Bays**: `pi5` (four M2.5 standoffs, port openings, vents), `reserved` (the
  same, with no Pi fitted, so one drops in later), and `open` (a flat shelf).
  Each Pi has a service gap on its right for its USB-C and micro-HDMI plugs,
  back-wall openings for Ethernet and USB, and a microSD opening.
- **Per bay**: its own standoff height and headroom (a board mounted under a
  Pi, a HAT), and wall openings for an `open` bay.
- **Dividers** between bays: solid, vented, low, with a header notch and
  zip-tie slots.
- **Growth**: identical units bolt together, so a row can pass the printer's
  bed. The default pair is 176 x 96 x 25.4 mm and fits the A1 mini.
- **Checks**: the base and lid do not touch, each Pi's envelope clears both,
  and each part is one solid. Slicing puts each part on its own plate: the
  default pair is about 3 h 24 min and 118 g of PETG on the A1 mini profile.
- **Viewer**: `enclosure-group viewer` writes an interactive 3D view with the
  lid, the Pi envelopes, a cut plane, and dimensions.
- **Pi 5 spec**: from Raspberry Pi's mechanical drawings, with its orientation
  taken from their STEP model. An earlier version was mirrored left to right,
  which put the USB-C and HDMI cables on the wrong side; it was corrected
  before anything was printed.

Open items, in order:

1. **Print the pair's base** and test-fit a real Pi 5 before printing the lid.
   The guide's checklist covers the standoffs, ports, microSD slot, and the
   Active Cooler's height, which is inferred from the drawing rather than
   dimensioned. Correct `RaspberryPi5Spec` from what fits.
2. **Trials and revisions**: `enclosure trial` and `enclosure revise` work on
   the single-board `Enclosure`; the group enclosure has no trial record yet,
   and needs print measurements to design one around.
3. **Joined units and HATs** are unproven in plastic: the join bolts, and the
   headroom and standoff heights for a HAT or an under-board drive.

### Gaps closed since 2026-09-27

- The gate is green again, and a pre-push hook keeps it that way (Phase 0).
- Candidate evidence goes through the export pipeline, and promotion depends
  on a verified export-validation record rather than a CLI flag (Phase 1).
- Export validation and the design review found three fixture defects that
  would have failed on the first print: floating ledges, geometry built from
  the wrong board height, and through-hole pins passing into the fixture
  base. All three are fixed, and the candidates were regenerated (Phase 2
  prerequisite).

### Repository audit (2026-09-28)

A whole-repository health check found the gate green but several gaps
around it, now closed:

- **Evidence has an offsite backup.** `evidence/` is its own git repository
  pushed to the private `zacharymplace/zcad-core-evidence`, alongside the
  existing Time Machine backup. `scripts/backup-evidence.sh` commits and
  pushes new evidence and does nothing when it is unchanged.
- **Scripts are gated.** Two Feather RP2040 scripts had drifted from the
  library and would have failed with `TypeError`; they are fixed, and
  `check.sh`, CI, and the pre-push hook now check `scripts/` as well.
- **Docs match the code.** The empty `generators`, `materials`, `rendering`,
  and `utils` packages are gone, and the README and architecture tree list
  the packages that exist.
- **Slow tests are marked.** Vendor-STEP tests carry a `slow` marker, and
  `check.sh --fast` runs the rest in about 40 seconds instead of two
  minutes.
- **One Python version.** The development venv runs Python 3.11, matching
  CI and `requires-python`, instead of 3.14.
- **mypy 2.3.** `src` and `scripts` type-check under mypy 2.3 with no code
  changes.
- **Tests are type-checked.** The gate runs mypy over `tests` too. Getting
  there cleared 354 errors, mostly cadquery's `Workplane.val()` union, now
  narrowed with `workplane_shape`, and exposed two typing bugs in `src`:
  the board and display spec protocols declared settable attributes that no
  frozen spec could satisfy, and the retention backend protocol's `object`
  parameters rejected every concrete backend, which `src` hid behind
  `type: ignore`.

### Pending upgrade: cadquery 2.9 and OCP 8

`cadquery-ocp` 8.0 is released, but the latest cadquery, 2.8.0, requires
`cadquery-ocp<8.0` and fails on import with OCP 8. cadquery's development
branch (2.9.0.dev0) already requires `cadquery-ocp==8.0.1.*`.

zcad-core is ready for it: against cadquery 2.9.0.dev0 and OCP 8.0.1 in a
throwaway venv (2026-09-28), all 672 tests pass, including the vendor-STEP
tests, and mypy is clean. When cadquery 2.9 is released, raise the pin in
`pyproject.toml` to `cadquery>=2.9,<3`, reinstall, and run the full gate.
Do not depend on cadquery's development branch in the meantime; fixtures
would rest on an unreleased geometry kernel.

### Docs toolchain (2026-09-29)

The docs build on MkDocs 1.6 with Material for MkDocs and mkdocstrings 1.0.
MkDocs 2.0, in pre-release, removes the plugin and theming systems, so
neither mkdocstrings nor Material can run on it; the Material team
recommends staying on MkDocs 1.x or moving to Zensical, their drop-in
successor. `pyproject.toml` pins `mkdocs<2` (Material 9.7.5 and later cap
it too). Revisit Zensical once it documents mkdocstrings support.

## Operating principles

The Validation Lab principles continue to apply. In addition:

1. `main` stays green on format, lint, types, and tests, enforced by the
   local pre-push hook while GitHub Actions is unavailable.
2. Every artifact that becomes candidate evidence passes through the
   validated export pipeline.
3. New validation rules never rewrite historical evidence; they produce new,
   versioned re-validation records.
4. Software work does not outrun physical evidence by more than one phase.
5. New evidence is backed up with `scripts/backup-evidence.sh` after each
   trial or candidate revision.

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
- 1.4.0 keeps `board_clearance_mm` between edge-clip spans and component
  footprints, so clips no longer end flush against a component (UNO R4
  r004's clip touched a header housing).

The design review's interference check now fails closed: it takes the
largest overlap across several boolean formulations. The old check reported
0 mm³ for the XIAO's multi-shell vendor PCB, which actually overlapped its
base by 88.7 mm³. The review accepts bottom-side pads up to 0.05 mm proud of
the PCB as seating contact. Since design-review schema 1.1.0 it also blocks
any component closer to the fixture than 0.1 mm, which catches faces that
touch with zero overlapping volume.
Schema 1.2.0 adds a `clearance` section with the measurements the first
visual reviews had to take by hand: the parts nearest the fixture and the
captures, the board-to-capture gap, the base lip under each part that
overhangs the PCB edge, and the hole clearance of parts reaching through
the base. Candidates reviewed before 1.2.0 do not carry it.

Installation-path analysis (report schema 1.1.0) now moves the board against
the printed fixture, base and clearance holes included, instead of the
capture geometry alone, counting only overlap beyond each part's seated
contact. Parts through base holes therefore block planar slides: rerun on
UNO R4 r005, the two collision-free planar paths its stored report shows are
blocked by its pins. XIAO r003's diagonal slide-out stays collision-free, so
that reservation is a real escape path.

Print-ready candidates, each with passing export validation, design review,
and slicing readiness, a Bambu Studio slice, and an open trial-001:

| Candidate | Slice (A1 mini, PETG) | Vertical play |
|---|---|---|
| `adafruit-feather-rp2040-corner-capture-r004` | 9 min, 3.70 g | 0.90 mm |
| `raspberry-pi-pico-2-corner-capture-r002` | 8 min, 3.45 g | 0.85 mm |
| `seeed-xiao-esp32s3-corner-capture-r003` | 5 min, 1.44 g | 0.85 mm |
| `arduino-uno-r4-wifi-edge-clip-r005` | 17 min, 8.61 g | 0.85 mm |

Do not print superseded candidates, including UNO R4 r004, whose visual
review recorded `revise`. XIAO r002's unregistered placeholder trial was
removed. `scripts/regenerate-candidate.py` rebuilds a candidate under a new
generator version with its policy unchanged, as it did for UNO R4 r005.
New candidates record the adapter settings that chose their capture
locations (`generation` in `automated-validation.json`), and regeneration
inherits them. Candidates generated before that record do not carry it: a
corner-capture regeneration from one refuses to guess, so pass
`--corner-keepout-mm` (4.0 for Feather and Pico 2, 2.1 for XIAO).
`regenerate-candidate.py --set KEY=VALUE --relationship <type>` builds a
revision from measured parameter changes, which is the path a `revise`
trial takes.

The generator version is `GENERATOR_VERSION` in
`src/zcad_core/retention/generator.py`, not a value typed per run: new
evidence records it, `candidate register` reads it from the evidence, and
regeneration always uses it. A test fingerprints the geometry-generating
modules, ignoring comments and formatting, and fails when their code changes
without the fingerprint (and, if geometry changed, the version) being updated.

### Deliverables

- [x] Printer and material profiles selected in place of `pending-selection`.
  Trials record `bambu-lab-a1-mini`, `petg`, and
  `bambu-studio-a1-mini-petg-validation`.
- [x] Pre-print packages from `scripts/prepare-candidate-for-print.py` and
  slices from `scripts/slice-candidate-fixture.py`
- [x] Trial records that cannot mislead: pending trials have an explicit
  pending state, and `trial complete` refuses a `pass` disposition unless
  every check passed.
- [x] Trials that measure: physical-validation schema 1.1.0 adds
  `board_resists_lateral_push` and `cables_seat_fully`, and `trial complete
  --measurements` records named measurements with their nominal and
  deviation. `pass` and `revise` need at least one measurement. Each open
  trial has a `measurements.json` template seeded with the candidate's
  nominal vertical play and board clearance.
- [x] Visual reviews that gate promotion: `zcad-validation review complete`
  records them (schema 1.1.0 adds the `retention_features_fused` check and
  refuses a passing disposition when any check failed or the design review's
  geometry checks did not pass), and `candidate promote` requires a passing
  current-schema review of the same candidate via `--visual-review`. `report`
  shows each candidate's review. The legacy 1.0.0 review of Feather r003
  still loads but cannot support a promotion.
- [x] Human visual review of each candidate's design-review package (all
  four pass with reservations; UNO R4 r004 was revised to r005 first)
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

### Status (2026-09-29)

Per-trial feedback is built for both kinds of print.
`zcad-validation revision propose` turns a fixture trial's measured side
gap and vertical play into `board_clearance_mm` and `vertical_overlap_mm`
changes, and `regenerate-candidate.py --from-trial` applies them, writing
`measurement-feedback.json` beside the revision so each parameter change
traces to its measurement. `zcad-validation enclosure revise` does the same
for enclosures through `hole_compensation_mm` and the plug allowance.

Compensation profiles pool every recorded trial for a printer and material:
`zcad-validation compensation derive` writes
`profiles/compensation/<printer>-<material>.json` with the mean, spread, and
count of the hole, side-gap, and vertical-play errors, the trial records it
read and their hashes, and each earlier version in its history. It refuses
until there are at least two trials. `enclosure build --compensation-profile`
and `regenerate-candidate.py --compensation-profile` apply one and record
its id, version, and hash (in the build record, and in `compensation.json`
beside the revision). The first profile waits on the first print runs.

### Exit criteria

- Each revision's parameter delta traces to specific measurements.
- Compensation profiles are versioned and referenced by candidates.

## Phase 4 — Retention-strategy breadth

### Goal

Prove the physical loop for each retention strategy.

### Deliverables

- Phase 2 repeated for Pico 2 (corner capture), UNO R4 WiFi (edge clip),
  and XIAO ESP32-S3. Their pre-print packages and visual reviews are
  complete (Pico 2 r002, UNO R4 r005, and XIAO r003), so they can be printed
  in the same session as Feather r004.
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

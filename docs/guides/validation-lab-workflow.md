# Validation Lab workflow

This guide takes one board from its vendor STEP model to a promoted,
publication-eligible fixture candidate. Each step writes evidence that the
next step checks, and promotion accepts a candidate only when every record
it cites is present and passing.

Run every command from the repository root with the project's Python 3.11
environment active. Paths below use `<target>` for a target's Validation
Lab directory, such as `evidence/raspberry-pi-pico-2/validation-lab`, and
`<candidate>` for one revision inside it, such as `<target>/candidates/r002`.

## How evidence is organised

```text
<target>/
├── target.json                         board identity and source model hash
└── candidates/<revision>/
    ├── candidate.json                  immutable revision manifest
    ├── automated-validation.json       fit, interference, manufacturing checks
    ├── retention.step, fixture.stl     generated geometry
    ├── relationship.json               lineage to the parent revision
    ├── parameter-delta.json            policy changes from the parent
    ├── export-validation/v001/         export pipeline run (append-only)
    ├── design-review.*                 review package (GLB, 3MF, STEP, SVG, JSON)
    ├── installation-path-analysis.json rigid insertion paths
    ├── slicing-readiness.json, slice/  Bambu Studio slice and summary
    ├── visual-review.json              human review
    ├── trials/trial-001/               physical trial
    └── promotion.json                  promotion decision
```

Records are append-only. Writers refuse to replace an existing record with
different content; the one exception is completing a pending trial record in
place. `evidence/` is ignored by this repository and backed up to its own
private repository with `scripts/backup-evidence.sh`; run it after every
step that writes evidence.

## 1. Register the target

```bash
zcad-validation target register \
  --target-id raspberry-pi-pico-2 --display-name "Raspberry Pi Pico 2" \
  --manufacturer "Raspberry Pi" --product-family "Pico" \
  --source-model-path evidence/raspberry-pi-pico-2/step/rpi_pico2.step \
  --pcb-solid-index 373 \
  --output evidence/raspberry-pi-pico-2/validation-lab/target.json
```

`--pcb-solid-index` names the solid in the vendor STEP that is the bare PCB;
every other solid is treated as a component. It is 1-based and varies by
vendor model (373 for the Pico 2, 37 for the XIAO ESP32-S3, 1 for most
others). A wrong index fails later with "no two component-clear diagonal
corners". To find it, list the solids and pick the one with the board's
outline and thickness:

```bash
python -c "import cadquery as cq, sys
for i, s in enumerate(cq.importers.importStep(sys.argv[1]).solids().vals(), 1):
    b = s.BoundingBox(); print(i, round(b.xlen, 2), round(b.ylen, 2), round(b.zlen, 2))" \
  evidence/raspberry-pi-pico-2/step/rpi_pico2.step
```

## 2. Generate the first candidate

Generate the retention geometry and its automated evidence, export a
printable fixture, then register the result as revision `r001`:

```bash
zcad-validation candidate create --strategy corner-capture \
  --source-step <source.step> --pcb-solid-index <index> \
  --output-step <candidate>/retention.step \
  --report-output <candidate>/automated-validation.json

zcad-validation fixture export --strategy corner-capture \
  --source-step <source.step> --pcb-solid-index <index> \
  --output-step <scratch>/retention.step --output <candidate>/fixture.stl

zcad-validation candidate register \
  --target-manifest <target>/target.json \
  --automated-evidence <candidate>/automated-validation.json \
  --retention-step <candidate>/retention.step --fixture <candidate>/fixture.stl \
  --revision r001 --strategy corner-capture --git-commit "$(git rev-parse HEAD)" \
  --printer-profile profiles/printers/bambu-lab-a1-mini.json \
  --output <candidate>/candidate.json
```

Use `--strategy edge-clip` for boards without two component-clear diagonal
corners, such as the Arduino UNO R4 WiFi. Registration runs the first
export validation into `<candidate>/export-validation/v001/`.

The candidate records the generator version and corner keepout that built
it. The corner keepout is the square at each PCB corner that must be clear
of components; it defaults to 4.0 mm. A small board may need less: the XIAO
ESP32-S3 needs `--corner-keepout-mm 2.1`. Pass the same value to
`candidate create` and `fixture export`, or the fixture could capture
different corners from the candidate.

## 3. Prepare it for printing

```bash
python scripts/prepare-candidate-for-print.py <candidate>
python scripts/slice-candidate-fixture.py <candidate>
```

The first script regenerates the geometry and checks it matches
`retention.step`, then writes:

- the **design review** package: a coloured GLB and 3MF of fixture, board,
  and components, orthographic SVG views, and `design-review.json`. The
  review blocks on any overlap and on any part closer than 0.1 mm to the
  fixture, and its `clearance` section lists the nearest parts, the gaps to
  the captures, the base lip under each part that overhangs the board edge,
  and the clearance of parts through base holes.
- the **installation-path analysis**: rigid insertion paths tested against
  the full printed fixture, including parts seated in base holes.
- **slicing readiness** and a pending **trial** in `trials/trial-001/`, with
  `observations.json` and `measurements.json` templates.

The second slices `fixture.stl` with the Bambu Studio CLI into `slice/`.

## 4. Review it visually

Open `<candidate>/design-review.glb` (Preview on macOS) and answer the eight
checks in an observations file:

```json
{
  "review_artifacts_open": {"passed": true, "notes": ""},
  "color_separation_clear": {"passed": true, "notes": ""},
  "board_alignment_plausible": {"passed": true, "notes": ""},
  "captures_component_clear": {"passed": true, "notes": ""},
  "connectors_accessible": {"passed": true, "notes": ""},
  "installation_limitations_recorded": {"passed": true, "notes": ""},
  "underside_assumptions_recorded": {"passed": true, "notes": ""},
  "retention_features_fused": {"passed": true, "notes": ""}
}
```

```bash
zcad-validation review complete \
  --candidate-manifest <candidate>/candidate.json \
  --design-review <candidate>/design-review.json \
  --installation-path-report <candidate>/installation-path-analysis.json \
  --observations answers.json --reviewer "Z$" \
  --disposition pass_with_reservations --reviewer-notes "..." \
  --output <candidate>/visual-review.json
```

Use the `clearance` section of `design-review.json` rather than judging gaps
by eye; a 1 mm gap and flush contact look alike in a render. Record what the
print must confirm as reservations in the notes. A pass is refused if any
check failed or the design review's own checks did not pass; a failed check
calls for `revise`.

## 5. Print and record the trial

Print `slice/plate_1.gcode`, fit the board, and fill in the trial's
`observations.json` (ten pass/fail checks, including a sideways push and a
real cable) and `measurements.json` (values in millimetres, with the
nominal already filled in):

```bash
zcad-validation trial complete \
  --candidate-report <candidate>/automated-validation.json \
  --fixture-stl <candidate>/fixture.stl \
  --printer-profile bambu-lab-a1-mini --material-profile petg \
  --slicer-profile bambu-studio-a1-mini-petg-validation \
  --observations <candidate>/trials/trial-001/observations.json \
  --measurements <candidate>/trials/trial-001/measurements.json \
  --disposition pass --output <candidate>/trials/trial-001/physical-validation.json

zcad-validation trial register \
  --candidate-manifest <candidate>/candidate.json \
  --physical-validation-record <candidate>/trials/trial-001/physical-validation.json \
  --fixture <candidate>/fixture.stl --trial-id trial-001 \
  --output <candidate>/trials/trial-001/trial.json
```

`pass` and `revise` need at least one measurement; a `pass` also needs every
check to pass. A completed trial is never overwritten: record another
attempt as `trial-002`.

## 6. Promote, or revise

A passing trial promotes the candidate. Promotion verifies the export
validation, the visual review, and the trial before writing anything:

```bash
zcad-validation candidate promote \
  --candidate-manifest <candidate>/candidate.json \
  --relationship-path <candidate>/relationship.json \
  --parameter-delta-path <candidate>/parameter-delta.json \
  --physical-trial-path <candidate>/trials/trial-001/trial.json \
  --export-validation <candidate>/export-validation/v001/export-validation.json \
  --visual-review <candidate>/visual-review.json \
  --physical-validation-passed \
  --target-root <target> --reviewer "Z$" --reason "..." \
  --output <candidate>/promotion.json
```

Omit the relationship and parameter-delta paths for a root candidate. When
another candidate is already preferred, add `--supersedes-candidate-id`.

A `revise` becomes a new revision with geometry rebuilt from the measured
change:

```bash
python scripts/regenerate-candidate.py <candidate> --revision r003 \
  --set board_clearance_mm=0.30 --relationship adjusts_clearance_from \
  --reason "Trial measured 0.15 mm clearance against 0.25 nominal."
```

The same script regenerates a candidate unchanged after a generator change
(no `--set`). It inherits the parent's recorded corner keepout; a parent
generated before keepouts were recorded needs `--corner-keepout-mm`. Then
return to step 3. `zcad-validation revision compare` reports what changed
between two revisions and their trials.

## Checking where a target stands

```bash
zcad-validation status --target-root <target>
zcad-validation report --target-root <target>
```

`status` names the preferred candidate and whether it is publication
eligible; `report` lists every candidate with its trials, visual review, and
promotion.

## Changing generator code

Candidates record `GENERATOR_VERSION` from
`src/zcad_core/retention/generator.py`. A test fingerprints the
geometry-generating modules and fails when their code changes. If generated
geometry changed, bump the version and add a history line; either way,
update `GENERATOR_FINGERPRINT` to the value the test reports.

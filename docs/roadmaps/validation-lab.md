# Validation Lab Roadmap

## Purpose

Validation Lab is the durable evidence and revision-history layer for
zcad-core production candidates.

Its purpose is to answer, for every supported hardware target:

- What candidate was generated?
- From which source model and policy?
- Which automated gates passed?
- What was printed?
- Which printer, material, and settings were used?
- What happened during physical validation?
- What changed between revisions?
- Which revision is currently preferred?
- Is publication supported by complete evidence?

Validation Lab does not replace the geometry, retention, manufacturing, or
physical-validation subsystems. It organizes their outputs into a traceable
engineering history.

## Operating principles

1. Evidence is append-only by default.
2. Generated candidates are immutable once assigned a revision identifier.
3. Physical outcomes never overwrite automated evidence.
4. Failed and rejected trials remain visible.
5. Promotion is explicit and fail-closed.
6. Publication requires traceable automated and physical evidence.
7. Repository code remains authoritative for contracts and policy.
8. Local evidence artifacts remain untracked unless intentionally promoted
   into a governed evidence package.

## Core lifecycle

Source model
    ↓
Candidate generation
    ↓
Automated validation
    ↓
Candidate revision
    ↓
Printable fixture
    ↓
Physical trial
    ↓
Observed outcome
    ↓
Revision comparison
    ↓
Preferred revision
    ↓
Publication eligibility

## Proposed domain model

### Validation target

A stable identity for the hardware being validated.

Required fields:

- target_id
- display_name
- manufacturer
- product_family
- source_model_path
- source_model_sha256
- pcb_solid_index
- created_at_utc

Example:

target_id: adafruit-feather-rp2040

### Candidate revision

An immutable generated retention candidate.

Required fields:

- candidate_id
- target_id
- revision
- source_sha256
- generator_version
- git_commit
- retention_policy
- derived_parameters
- selected_corners
- automated_decision
- created_at_utc

Example:

candidate_id:
  adafruit-feather-rp2040-corner-capture-r001

### Automated validation run

Evidence from computational gates.

Required sections:

- fit checks
- PCB interference
- component interference
- manufacturing checks
- output STEP hash
- decision
- validator versions

### Physical trial

One real print and fit attempt against one candidate revision.

Required fields:

- trial_id
- candidate_id
- fixture_artifact
- printer_profile
- material_profile
- slicer_profile
- print_started_at_utc
- print_completed_at_utc
- operator
- observations
- disposition
- notes

A candidate may have multiple trials.

### Revision relationship

A typed link between candidate revisions.

Initial relationship types:

- supersedes
- retries
- adjusts_clearance_from
- adjusts_overlap_from
- adjusts_wall_from
- derived_from
- invalidates

### Promotion record

An explicit decision identifying the preferred revision.

Required fields:

- target_id
- candidate_id
- promotion_status
- evidence_summary
- approved_by
- approved_at_utc

Initial statuses:

- candidate
- physically_verified
- preferred
- rejected
- superseded
- publication_eligible

## Proposed directory layout

validation/
  targets/
    adafruit-feather-rp2040/
      target.json

      candidates/
        r001/
          candidate.json
          automated-validation.json
          retention.step
          fixture.stl

          trials/
            trial-001/
              physical-validation.json
              print-profile.json
              measurements.json
              photos-manifest.json

        r002/
          candidate.json
          automated-validation.json
          retention.step
          fixture.stl

      revisions.json
      promotion.json
      summary.md

The exact storage root may remain outside Git during early development.
Contracts and validators belong in the repository regardless of whether
binary evidence is committed.

## Phase 1 — Validation identity and immutable revisions

### Goal

Establish stable target, candidate, and revision identities.

### Deliverables

- ValidationTarget contract
- CandidateRevision contract
- deterministic candidate identifiers
- revision number allocation
- source and output hashes
- candidate manifest writer
- duplicate-revision rejection
- unit tests for identity and immutability

### Exit criteria

- The same candidate input produces the same identity inputs.
- A revision cannot be silently overwritten.
- Candidate manifests record source hash, output hash, and Git commit.
- Existing Feather evidence can be represented as revision r001.

## Phase 2 — Physical trial registry

### Goal

Allow multiple physical trials against one candidate revision.

### Deliverables

- PhysicalTrial contract
- unique trial identifiers
- pending, pass, revise, and reject states
- printer and material profile references
- optional dimensional measurements
- trial-record writer and loader
- incomplete-trial fail-closed validation

### Exit criteria

- Multiple trials can coexist without overwriting one another.
- A passing disposition cannot pass with missing observations.
- Failed trials remain queryable.
- The current pending Feather record can be migrated into trial-001.

## Phase 3 — Revision lineage

### Goal

Explain why each new candidate exists and what changed.

### Deliverables

- RevisionRelationship contract
- typed revision links
- parameter-delta report
- human-readable revision summary
- cycle and self-reference rejection
- lineage query helpers

### Exit criteria

- Every revision after r001 identifies its predecessor or derivation source.
- Policy and derived-parameter changes are visible.
- The system can answer why one revision superseded another.

## Phase 4 — Comparison and recommendation

### Goal

Compare revisions using automated and physical evidence.

### Deliverables

- candidate comparison report
- automated-gate comparison
- trial-outcome comparison
- dimensional measurement comparison
- recommendation contract
- explicit uncertainty and missing-evidence reporting

### Exit criteria

- The system can compare two candidate revisions deterministically.
- Recommendations distinguish measured facts from policy judgment.
- Missing physical evidence blocks unsupported recommendations.

## Phase 5 — Promotion and publication gate

### Goal

Promote a physically verified candidate without editing evidence manually.

### Deliverables

- PromotionRecord contract
- preferred-revision selection
- publication-eligibility validator
- supersession handling
- promotion audit trail
- metadata-publication integration

### Publication prerequisites

- complete candidate manifest
- all automated gates passed
- at least one complete passing physical trial
- no unresolved rejecting trial designated as authoritative
- explicit preferred-revision promotion
- source and output hashes still match
- required evidence artifacts exist

### Exit criteria

- Metadata publication cannot be approved by changing a Boolean directly.
- Approval is derived from complete evidence and an explicit promotion record.
- Revoking or superseding a candidate leaves the historical decision intact.

## Phase 6 — Validation Lab CLI

### Goal

Make the workflow operable without manually editing JSON.

### Proposed commands

zcad validation target register
zcad validation candidate create
zcad validation candidate inspect
zcad validation fixture export
zcad validation trial start
zcad validation trial complete
zcad validation revision compare
zcad validation candidate promote
zcad validation status
zcad validation report

### Exit criteria

- Operators can complete the normal lifecycle through supported commands.
- Commands fail closed on missing evidence or invalid transitions.
- Every write produces an inspectable record.

## Phase 7 — Multi-board expansion

### Goal

Prove that Validation Lab generalizes beyond the Feather target.

### Initial sequence

1. Adafruit Feather RP2040
2. Raspberry Pi Pico 2
3. Arduino UNO R4 WiFi

### Exit criteria

- At least two board families have candidate revision histories.
- Shared contracts require no board-specific branching.
- Board-specific constraints remain represented as policy or target evidence.

## Near-term implementation order

The next implementation slice should remain narrow:

1. Add ValidationTarget and CandidateRevision contracts.
2. Add deterministic revision manifests.
3. Register the current Feather candidate as r001.
4. Add PhysicalTrial identity around the existing physical record.
5. Do not add comparison, promotion, CLI, or publication logic yet.

## Explicitly deferred

The following work should not begin during the first Validation Lab slice:

- additional retention strategies
- richer overhang simulation
- finite-element analysis
- automatic slicer integration
- image or photo analysis
- generalized database storage
- web dashboards
- automatic metadata publication
- broad multi-board migration

These remain downstream of stable identity, immutable revision history, and
structured physical trials.

## First milestone

Validation Lab v0.1

Definition of done:

- Feather target manifest exists.
- Feather corner-capture candidate is registered as revision r001.
- Candidate references current automated evidence and fixture artifacts.
- Candidate identity includes source hash, output hash, and Git commit.
- Existing pending physical validation is represented as trial-001.
- Records validate deterministically.
- No evidence artifact is overwritten.
- Publication remains blocked.

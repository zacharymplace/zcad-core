# Sweep plates

## Purpose

A Validation Lab candidate converges one revision per print day. A trial reads the fixture's clearance and play, measurement feedback proposes
the next revision, and that revision waits for the next print. Four boards at a revision a print day is a slow way to find out that a capture
wants 0.3 mm of clearance rather than 0.25.

A **sweep plate** prints several revisions of one candidate at once, each differing from the parent in one figure and nothing else, on one
plate. One print day then tries the figure at three to five values, and a stated rule picks the variant that becomes the next revision. The
lab learns in one print what it now learns in several.

**Status (2026-10-09): designed, not built.**

## What the engine does not claim

- **That the chosen variant is right.** It is the variant the rule picked from these trials. It still needs its visual review, and its
  promotion its own passing trial, as any candidate's does.
- **Anything about a value between two variants.** A sweep says which of the values it printed did best, not where the best value lies.
- **Two figures at once.** A sweep changes one figure; the variants differ in nothing else, so a difference between them is that figure's.

## What the engine already has

| Piece | Where | What a sweep takes from it |
| --- | --- | --- |
| Regeneration from a parent with one figure changed | `scripts/regenerate-candidate.py --set`, `retention/artifact_revision.py` | Each variant, a real candidate revision with its own export validation and lineage |
| Five overridable policy figures | `artifact_revision.py` | The figures a sweep may change (below) |
| Print preparation | `scripts/prepare-candidate-for-print.py` | Each variant's design review, slicing readiness and pending `trial-001`, its nominals already its own |
| Several STLs on one plate | `printing/bambu.py: slice_models` | The plate's one G-code |
| Recording a fixture trial | `record-print-day.py: record_fixture` | Each variant's trial, unchanged: one answer per candidate |
| Measurement feedback | `retention/measurement_feedback.py` | Where the next sweep is centred |

Corner-capture and edge-clip candidates regenerate; snap-shell candidates do not, and are not swept.

## Decision: every variant is a candidate revision

A variant is a revision like any other: `rNNN`, immutable, regenerated from the parent by the same code with one figure set, export-validated
and prepared for print on its own. Nothing about a variant is special except a new relationship, **`sweep_of`**, naming the parent, and its
place in a sweep record. So a chosen variant needs nothing more to be promoted than any revision does, and one not chosen stays in the lab's
history as what it was: a revision that was tried.

## Decision: what a sweep may change

| Figure | Values | Rule for the chosen variant |
| --- | --- | --- |
| `board_clearance_mm` | 3 to 5, each at least the manufacturing minimum, 0.20 mm | The **smallest** whose trial passes: the tightest the board still goes in and comes out of without force |
| `vertical_overlap_mm` | 3 to 5, each at least 0.40 mm | The **largest** whose trial passes: the most hold that still inserts and removes |
| `engagement_depth_mm` | 3 to 5 | The **largest** whose trial passes |

Arm width and minimum wall are structural rather than fit figures, and stay as the parent has them. The values are given in the command; the
parent's own value may be one of them, so a sweep can say the parent was already best. A value under the manufacturing minimum is refused
with the minimum, as `candidate register` refuses one.

Where no variant passes, none is chosen, and the sweep's result says which checks failed at which value: a sweep that missed is still
evidence about where the figure is not.

## Decision: the plate is laid out, not arranged

Variants a tenth of a millimetre apart look alike, and the slicer's arrange step moves and turns parts as it sees fit. So a sweep plate is laid
out by the engine: the variants left to right in the order of their values, each turned as its own slice would be, a fixed gap apart, and
sliced without arranging. The plate record names each variant's position. A combined check refuses a plate the bed cannot take, with the
widest set of variants it can.

The fixtures themselves are not marked: an emboss would change the geometry each variant's design review compares against its STEP. Instead
the plate record, the print-day page and the trial templates all say left to right, and the operator marks each part with a pen before lifting
it off the plate. A part lifted off unmarked is answered as not printed.

## Decision: a sweep record, and a result

`zcad-validation sweep build` writes `<target>/validation-lab/sweeps/<sweep-id>/sweep.json`: the parent, the figure, each value with its
variant's candidate id and position on the plate, the plate's STL copies and its slice. The z-cadalog lists it as a design of its own, beside
the variants, and treats `sweep_of` as a sibling's link to its parent, not as a revision replacing it.

Each variant is recorded as any candidate is, one answer per variant on the Fixture Fit Trials checklist. Once all are recorded,
`zcad-validation sweep choose` reads each variant's trial and writes `sweep-result.json`: the rule, every variant's disposition and its
measurements against its nominals, and the chosen variant, or why none is. It never promotes and never writes into a candidate's folder.

## Decision: the next sweep starts from what this one found

A sweep that chose a variant may still be off: the chosen variant's own trial measures how its clearance and play came out, and measurement
feedback proposes from that trial as it does from any. `sweep build --around <candidate>` centres the next sweep's values on the chosen
variant, or on feedback's proposal, a step apart. A sweep that chose none centres on the side of the range nearest a pass.

## The commands

```bash
zcad-validation sweep build --parent <candidate-dir> --figure board_clearance_mm --values 0.20,0.25,0.30,0.35 --slice
zcad-validation sweep status --sweep <sweep-dir>
zcad-validation sweep choose --sweep <sweep-dir>
```

`build` regenerates and prepares each variant, lays out the plate, checks the bed, and slices it. It refuses if any variant would fail export
validation or its design review, naming the variant, and writes nothing in that case.

## Not covered

- **Snap-shell candidates.** They are built by their own scripts and do not regenerate from a parent.
- **Products outside the Validation Lab.** Enclosures, stacks and the rest are tuned through joint coupons and their own revisions.
- **A grid of two figures.** Two figures at three values each is nine fixtures and a plate the A1 mini rarely takes; sweep one, then the other.

## Phases

1. **The sweep and its plate.** `sweep_of`; `sweep build` making each variant through the existing regeneration and print preparation, the
   laid-out plate and its combined bed check, `slice_models` without arranging, and `sweep.json`. The z-cadalog's lineage reads `sweep_of` as a
   sibling. Exit: a sweep of one board is on print day.
2. **Choosing.** `sweep status` and `sweep choose`, the rule per figure, `sweep-result.json`, and the checklist and the print-day pages showing a
   sweep's variants together, left to right.
3. **The next sweep.** `sweep build --around`, from a chosen variant or from feedback's proposal on its trial.

Each phase is one PR, and nothing about a candidate built without a sweep changes.

## Open questions

- **Pen marks or a mark in the geometry.** A mark outside the capture would make variants impossible to mix up, but every variant's design
  review would have to accept it; the proposal is the pen, until a mix-up happens.
- **Whether a variant not chosen should be closed.** A `REQUIRES_REVISION` record for each would say so in its folder; the proposal is to let
  the sweep's result say it, and write nothing into a candidate the operator did not choose to act on.
- **Whether `revision compare` should rank more than two.** `sweep choose` ranks a sweep's variants by its rule; a general N-way comparison is
  left until a second use for it appears.

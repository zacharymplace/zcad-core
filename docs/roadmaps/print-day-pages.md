# Generated print-day pages

## Purpose

Two pages carry a print day. The **Print Day Sheet** lists what to print, in what order, with each plate's time, filament and G-code; the
**Fixture Fit Trials** checklist takes each print's answers, which `record-print-day.py` records. Both are written by hand. Each time a part
goes on print day, both are edited by hand, its figures copied from a slice summary and its checks from a trial template; three times on
2026-10-09 alone. A copied figure can drift from the evidence, and a part built but never copied onto the pages is never printed.

The [z-cadalog](z-cadalog.md) solved the same problem for the catalogue: a script reads the build records and the page is regenerated, never
edited. This design does the same for print day: **every part whose trial is open and whose slice is ready is on the pages, with its figures
and its checks read from its records**, and the only hand-written content is what a person knows that no record does.

**Status (2026-10-12): designed, not built.**

## What a print is

A print is a design the z-cadalog calls **on print day**: a build record with an open trial and a slice. The generator finds them the way the
catalogue does, by record name, and reads, for each:

| On the pages | From |
| --- | --- |
| Name, kind, what it is, the commit it was built at | The build record (`candidate.json`, `enclosure.json`, `coupon.json`, `gridfinity.json`, `joint-coupon.json`, ...) |
| Minutes, grams, G-code path, slicer warning | The slice's `slice-summary.json`, a plate per part where a build slices more than one |
| The checks and what each asks | The open trial's `observations.json` |
| The measurements, their nominals and how to take each | The open trial's `measurements.json` |
| A joint coupon's rungs and what each is read for | The open trial's `observations.json` |
| What it was fitted with (Gridfinity) | The open trial's `fit.json` |
| The disposition choices | The kind: a fixture's pass, revise or reject; an enclosure's or a Gridfinity part's pass, revise or fail; a coupon's measured or fail |

A part whose slice or trial is missing is left off, and the generator says why, so a part built and not sliced is visible as such rather than
silently absent.

## Decision: what is written by hand, and where it lives

A record cannot say that the XIAO's back-right ledge is 0.261 mm from a part, that the Pi 5 group lid is worth printing only if the base passes,
or which plates are optional. That knowledge stays hand-written, in **`print-notes.json` beside each build record** under `evidence/`, so it is
versioned and backed up with the build it describes:

```json
{
  "watch": ["The back-right ledge is 0.261 mm from the small part beside USB-C."],
  "have": ["A USB-C cable"],
  "optional": false,
  "after": "pi5-group-2bay base passes"
}
```

Every field is optional. A print with no notes is shown with its records alone, and the generator lists the prints that have none.

## Decision: the order is a rule

Coupons first, since they tell every later plate how the printer fits; then the rest shortest first, so a capture that is too tight shows up
before a long print is committed; then, on a second side, anything over an hour. Optional prints follow the required ones on their side. A
print whose notes name an `after` follows the one it names.

## Decision: the pages read data; their templates are the engine's

`scripts/build-print-day.py` writes `print-day/print-day.json` and copies two templates from `scripts/print-day/`: `sheet.html` and
`trials.html`. Each page fetches `print-day.json`, as the z-cadalog's page fetches `catalog.json`. The checklist's per-kind controls (a
fixture's checks, a Gridfinity part's fit, a fit coupon's holes, a snap coupon's drawers) move into its template unchanged; what each card
holds comes from the data.

Each print's id on the checklist is its folder under `evidence/` (`joints/a1-mini-petg-fit-01`), so an answer saved against it stays with that
print however the page is regenerated, and `record-print-day.py` finds the print by the same path. The checklist's saved answers are empty on
2026-10-12, so the hand-written ids can be dropped without moving anything.

## Decision: published as the z-cadalog is

The two pages are republished to the same artifacts, with `print-day.json` beside each. `--mark-published` records which evidence each went up
with, and `--summary`, which `backup-evidence.sh` already runs for the catalogue, says whether the pages still match the evidence: a part built
and backed up but not yet on the published pages is the drift this design exists to stop.

## Not covered

- **Recording.** `record-print-day.py` is unchanged but for finding a print by its folder.
- **Which prints happen.** The pages list every print that is ready; the operator still chooses what goes on the bed, and an answer left
  unfinished is skipped as now.
- **Sweeps.** A [sweep plate](sweep-plates.md) is one plate of several candidates; it joins the pages when sweeps are built.

## Phases

1. **The data.** The catalogue's record reading moved where both scripts can use it; `build-print-day.py` writing `print-day.json`, with each
   print's figures, checks, measurements, rungs and notes, and the prints left off with why; `print-notes.json` read where present. Tests from
   a fixture evidence tree.
2. **The sheet.** `sheet.html` drawn from the data, the order by rule, and the Print Day Sheet republished from it, its hand-written notes
   moved into `print-notes.json`.
3. **The checklist.** `trials.html` drawn from the data with ids by folder, `record-print-day.py` finding prints by folder, and the Fixture Fit
   Trials page republished from it.
4. **Currency.** `--mark-published` for both pages and the line in `backup-evidence.sh`.

Each phase is one PR.

## Open questions

- **Whether the two pages should become one.** The sheet is read at the printer and the checklist at the bench; the proposal keeps them
  apart, generated from one file.
- **Whether `print-notes.json` belongs in the repository instead.** Notes describe a particular build, so they sit with it in `evidence/`; a
  note that should outlive a rebuild is copied forward by the next build's author.

# The z-cadalog

## Purpose

The engine has built a good deal by now: fixtures for six boards across 23 revisions, enclosures for the Pi 5 and the XIAO, a group enclosure, two
calibration coupons, and Gridfinity bins and baseplates. Each is recorded under `evidence/`, but finding one means knowing its folder, and nothing says in one
place which of them are current, which are waiting on a print, and which are superseded. The [Workbench](https://claude.ai/artifact/EUrzHLzx3CpXzd5jdx1fsn)
shows what the engine can do, from a handful of example models. It is not a record of what has been built.

The **z-cadalog** is that record: every design the engine has built, in one place, each with its views, its figures, its status, and how to build it again.

**Status (2026-10-08): all three phases are built.** `python scripts/build-catalog.py` and `python scripts/build-examples.py`, and
`backup-evidence.sh` keeps the catalog current; see [Phase 1](#phase-1-as-built), [Phase 2](#phase-2-as-built) and
[Phase 3, as built](#phase-3-as-built).

## What a design is

A design is a **build record** under `evidence/`, the file a build writes and a trial reads. The catalog finds them by name, not by folder:

| Record | Kind | Today |
| --- | --- | --- |
| `<target>/validation-lab/candidates/<revision>/candidate.json` | Validation Lab fixture | 23 revisions, six boards |
| `enclosures/<name>/enclosure.json` | Enclosure | 2 |
| `enclosures/<name>/enclosure-group.json` | Group enclosure | 1 |
| `coupons/<name>/coupon.json` | Calibration coupon | 2 |
| `gridfinity/<name>/gridfinity.json` | Gridfinity bin or baseplate | 5 |

Every other product (holders, nests, jigs, stackable items, housings, drill guides, PCB test fixtures) writes a build record too, under its own name, and is
catalogued the same way once one is built into `evidence/`. A record kind the catalog does not know is listed by its path and file name, not skipped, so a
new product shows up before the catalog learns its fields.

## Decision: status comes from the records, never from a field typed in

Each design's status is read from the files beside it, in this order, the first that holds:

1. **Superseded**: a later revision names this one as its parent (a candidate's `relationship.json`), or a later build records `revision_of` it.
2. **Promoted**: a candidate's `promotion.json` says so.
3. **Verified**: the kind's own rule holds (a Gridfinity part on two passing trials of its exact build record, as `gridfinity trial status` says; the
   same rule as the kind's `status` command, called, not copied).
4. **Trial recorded**: a completed trial, with its disposition (pass, revise, fail).
5. **On print day**: a trial opened and pending, with its slice.
6. **Reviewed**: a candidate with a current-schema visual review and no trial yet.
7. **Built**: a build record and nothing after it.

The catalog shows the evidence for each status (the file that settled it), so a reader can check it. It states nothing a record does not: no "ready", no
"works", and a design is never verified because it looks finished.

## Decision: what an entry shows

- **Name, kind and product**, the board or object it is for, when it was built, and from which commit and generator version.
- **Views**: the parts in a 3D viewer, from the STL files the build exported (the files a slicer is given); a candidate's design-review views as well.
- **Figures**: the size, the checks and whether each passed, any warnings, the nominal measurements a trial checks, and the slice's time and filament.
- **Status**, as above, with the file that settled it, and the lineage: the revision it replaced and the one that replaced it.
- **How to build it again**: the slice's rebuild recipe when there is one, the regeneration command for a candidate, or the build's own command line.
- **Where it lives**: its folder under `evidence/`.

The index groups designs by product and shows each one's status as a chip, so what is waiting on a print stands out; superseded revisions fold under the
one that replaced them.

## Decision: a script builds it, and the page is regenerated, never edited

`scripts/build-catalog.py` reads every build record under `evidence/` and writes `catalog/` (ignored by git, as `evidence/` is): `catalog.json`, one entry
per design, and a copy of each design's STL files and views beside it. The page is a template in the repository, `scripts/catalog/page.html`, that reads
`catalog.json` and shows it; publishing it with the files is the last step. Run again after any build or trial, the script writes the same catalog from the
same evidence, so the page is never edited by hand and never drifts from the records.

The catalog's page carries no evidence of its own: it is a view of `evidence/` at the commit it names. It is private, as the evidence is: vendor STEP models
stay out of it (only the engine's own STL exports and the review views go in).

## Decision: one example of each product not yet built

Seven products have no build in `evidence/`, so the catalog would show only half of what the engine makes. Phase 2 builds one of each from the example
inputs the repository already ships (`board template`, `capture template`, the guides' examples), into `evidence/examples/`, and the catalog marks them
**example**: built from example readings, never a real object, and never trialled. An example is replaced by a real build of the same product when there is
one.

## Not covered

- **Editing a design from the catalog.** It shows designs; builds happen on the command line.
- **The Workbench.** It stays the engine's showcase; the catalog links to it and it may link here.
- **Designs outside `evidence/`.** A build written elsewhere is not catalogued until it is moved or rebuilt there.

## Phases

1. **The catalog of recorded designs (built).** `scripts/build-catalog.py` for the five record kinds above, status from the records, the page template, and the
   catalog published as a private page with its STL files and views. A test builds a catalog from a scratch `evidence/` of each kind and status.
2. **Examples of the rest (built).** One build of each product not yet in `evidence/`, from the repository's example inputs, marked as examples.
3. **Kept current (built).** `backup-evidence.sh` rebuilds the catalog after a backup and says when the published page is behind the evidence.

Each phase is one PR.

### Phase 1, as built

`scripts/build-catalog.py` writes `catalog/` (ignored by git) with `catalog.json`, each design's STL parts under `models/` (as base64 in JSON, since a
published page serves only web file types and STL is not one), and the page, a copy of
`scripts/catalog/page.html`. Run against the evidence on 2026-10-08 it found 33 designs: 17 superseded, 14 on print day and 2 built, with 2.7 MB of
models. Publishing the catalog is the step after the script: the page and its files, as a private page.

- **Lineage from every relationship.** A candidate's parent is replaced by any recorded relationship (`supersedes`, `derived_from`), not only
  `supersedes`; one revision was derived rather than superseded.
- **A candidate's fixture** is the one its record names (`fixture_artifact_path`), which for the early revisions is not `fixture.stl` beside it. Paths a
  record writes from the repository (`evidence/...`) are read against the evidence root, so the script works from a worktree.
- **No design-review SVG views.** They are about a megabyte each, four to a reviewed candidate; every design with an STL has the 3D viewer instead, and the
  views stay in each candidate's folder. The snap-shell candidates were exported as STEP only and are listed without a model, saying so.
- **Rebuild lines** come from a slice's recorded recipe where there is one (the coupons and the Pi 5 enclosures); a candidate's is its regeneration from its parent, with
  the reason left for whoever runs it. Gridfinity builds record no recipe yet, so they show none.
- **Verification** is called only for Gridfinity, the one kind with a verification function; the others reach "trial recorded" at most until they
  have one. None is verified today.
- **The page** loads three.js and its STL loader from jsDelivr, pinned to 0.128.0 with integrity hashes, and fetches each design's parts only when it is
  opened.

### Phase 2, as built

`scripts/build-examples.py` builds one of each of the seven products into `evidence/examples/<product>/`, its inputs beside a `<product>-example/`
build, and refuses if `evidence/examples/` exists. The catalog gives everything under `evidence/examples/` the status **example**, ahead of every other
rule, so an example is never shown as built, on print day or trialled.

| Product | Built from |
| --- | --- |
| Object holder | `capture template`'s example capture, then `holder template` |
| Holding nest, insert jig, drill guide | The test suite's part, a 50 x 30 x 10 mm plate with 4 mm corners, as STEP, then each product's `template` |
| Stackable items | `stack template`'s example profile and stack: a 2 x 1 bin and a 2 x 2 baseplate |
| Wearable housing | `board template`'s example board, as a case |
| PCB test fixture | The KiCad example board, `examples/kicad/sensor-board.kicad_pcb`, as `examples/kicad_board.py` builds it |

- **The templates' guards.** Every build refuses a template's readings until a person replaces them: the capture's `needs_review` (and its unticked
  edge features), and the example sources of the jig's iron and the stack profile. The figures are kept exactly as the templates wrote them, and each
  guard is replaced by a source that begins "Template example values, unchanged and not measured". Those inputs exist only under `evidence/examples/`.
- **The PCB test fixture** comes from the KiCad example, not `board template`: that board is one envelope over the whole board, which every pin meets.
- **The catalog knows the seven products' build records** by name now (`holder.json`, `nest.json`, `jig.json`, `stack-build.json`, `layer-build.json`,
  `housing-build.json`, `guide.json`, `fixture.json`), with their trial records, and reads a stack build's parts from its `items`.

### Phase 3, as built

The page is published from claude.ai, which a script cannot read, so the checkout keeps its own note of what it published.

- **`--mark-published <url>`** writes `.catalog-published.json` beside `catalog/` (ignored by git): the URL, and the evidence and repository commits of
  the catalog that went up. It builds nothing; it is the last step of publishing.
- **Every build** compares its evidence commit with that note and says whether the published page is current, is behind (republish it, then mark it
  published), or was never published from this checkout. `--summary` says it in one line. Evidence that is not in git cannot be compared, and the line
  says so rather than guessing.
- **`backup-evidence.sh`**, after a successful push, rebuilds the catalog with the main checkout's virtual environment and prints that line. The backup
  has already succeeded by then, so a catalog that fails to build says so and does not fail the backup.

## Open questions

- **Whether the catalog should be a command (`zcad-validation catalog`) rather than a script.** It reads evidence the way `record-print-day.py` does,
  and is not part of building anything; the proposal is a script.
- **Whether superseded candidates need their 3D views.** They are small (a fixture is a few kilobytes) and show what changed; the proposal is to keep them.

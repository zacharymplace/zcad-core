# Publishing a promoted candidate

## Purpose

Phase 5 of the [next phases](next-phases.md) is to make promoted candidates consumable by product repositories. The gate for it already exists:
`evaluate_publication_eligibility` refuses a candidate without passing automated, export, visual and physical evidence, `register_candidate_promotion`
writes a `PROMOTED` decision only through that gate, and `build_publication_record` attaches an approved `publication` block to a part record only for
such a decision. What is missing is the other end: nothing writes a promoted candidate anywhere a product repository can read it, and nothing says
what such a repository may rely on.

A candidate's folder under `evidence/` is not that place. It is about 24 MB, most of it review files (the design-review STEP, GLB and SVG views) and
models derived from the vendor's STEP file; it lives in a private repository that is a backup, not a publication (Validation Lab principle 8); and
its layout has changed whenever a phase added a record.

This design adds a **publication package**: a small, fixed set of files copied out of one promoted candidate, with a manifest that names each file and
its hash, tracked in this repository and released with it.

**Status (2026-10-08): designed, not built.** No candidate is promoted yet, and the [exit criterion](next-phases.md#phase-5-publication-and-downstream-integration)
needs a real one consumed by a real product repository. The package format should be built against the first promoted candidate's evidence, not a
synthetic one, so the first build is phase 1 below.

## Decision: a package is one promoted candidate, never a target or a product

A package holds exactly one candidate revision, named by its `candidate_id`. A product repository asks for "the Feather RP2040 corner capture, r005",
never "the current Feather fixture": which revision is current is the index's job (below), and a consumer that pins a revision keeps getting the same
geometry after a newer one is promoted.

Only Validation Lab candidates are packaged at first, because only they have a promotion record. A Gridfinity part verified on two trials, or an
enclosure, has no promotion decision to gate on; see [Not covered](#not-covered).

## Decision: what goes in, and what stays in `evidence/`

| In the package | From | Why |
| --- | --- | --- |
| `retention.step`, `retention.stl` | `export-validation/v<NNN>/` | The geometry, as export validation checked it, round trip and topology included |
| `retention.metadata.json` | the same folder | The part record: bounds, mass, printer and material profiles |
| `fixture.stl` | the candidate | The printable fixture the trials printed |
| `candidate.json` | the candidate | Generator version, commit, parameters, source and output hashes |
| `promotion.json` | the candidate | The decision, its reviewer and reason |
| `export-validation.json`, `design-review.json`, `visual-review.json` | the candidate | The automated evidence and the visual review the gate read |
| `trials/<trial>/physical-validation.json`, `measurements.json` | each completed trial | The physical evidence: disposition, printer, material, measured figures |
| `relationship.json`, `parameter-delta.json` | the candidate | Lineage: what it replaced and what changed |

Left in `evidence/`: the design-review STEP, GLB, 3MF and SVG views (review aids, about 21 MB); the slice and its G-code (one printer's output, not the
design); `reference_board.*`, which is cut from the vendor's STEP model; and the vendor model itself. The package carries the source model's SHA-256
and its target's name and manufacturer, so a consumer can tell which board it fits, but never the vendor's geometry, which is not ours to redistribute.

A package for r005 would be about 130 KB.

## Decision: the manifest is the contract

Each package has a `package.json`:

- `schema_version` (`1.0.0`); a consumer refuses a major version it does not know.
- `candidate_id`, `target_id`, the target's `display_name` and `manufacturer`, `strategy`, and `source_model_sha256`.
- `publication`: the block `build_publication_record` writes (approved, reviewer, promoted at), so approval is never a Boolean typed in.
- `built_by`: the zcad-core version and commit that wrote the package, and the generator version and commit that built the candidate.
- `files`: every file in the package, by path, with its SHA-256 and its role (`geometry`, `printable`, `part_record`, `evidence`).
- `trials`: each completed trial's id, disposition, printer and material profile, so a consumer can see what it was proven on without parsing the
  evidence.

A product repository may rely only on what the manifest names: the files, their hashes and roles, and the fields above. The layout of `evidence/`,
the evidence records' own fields, and anything not in `files` can change without notice.

## Decision: packages live in this repository, under `published/`

`published/<target_id>/<candidate_id>/` is tracked in zcad-core and lands through a pull request like any other change, so a package is reviewed,
gated and released with the code that wrote it. A product repository pins a zcad-core tag and reads the package from it: by a git submodule or
sparse checkout, or from the release's source archive. Packages are small enough for plain git; if they ever are not, that is the time to reopen
Git LFS for this repository, not for `evidence/`.

A package is never edited once it lands. A correction is a new candidate revision, promoted and packaged in turn.

## Decision: the index says what is current, and nothing is deleted

`published/index.json` lists every package with its target, strategy and state:

- **current**: the latest promoted revision for its target and strategy;
- **superseded**: a later package for the same target and strategy names it as its parent, with that package's id;
- **withdrawn**: a `withdrawn.json` beside it says why (a field failure, a recall), written by a command, never by hand.

A superseded or withdrawn package stays in the tree and in the index, so a consumer pinned to it still builds and can see that it should move.

## Decision: a command writes it, and refuses what the gate refuses

`zcad-validation publish <candidate>` re-reads the candidate's evidence, runs `evaluate_publication_eligibility` again (promotion is not enough on its
own: the hashes and evidence must still match), builds the manifest, and writes the package through `publish_files`, which stages it and rolls back on
failure. It refuses a candidate that is not promoted, one whose output hash no longer matches its files, and a package that already exists. It writes
into a worktree checkout of `published/`, never into `evidence/`, and the package lands by pull request.

## Not covered

- **Products without a promotion record.** Gridfinity parts, enclosures, coupons and the other products have trials and, for some, a verified rule,
  but no promotion decision. Packaging them needs one first.
- **The wearable snap shells.** They stay provisional until a caliper capture replaces their published sizes; they cannot be promoted before that.
- **A package registry or download service.** Git tags and the tree are the distribution.
- **Signing.** The manifest's hashes catch a damaged file; they do not prove who wrote it. GitHub's tag and commit history are the provenance for now.

## Phases

### Phase 1 — the package and the command

`zcad-validation publish`, the manifest at schema 1.0.0, and the first package, from the first promoted candidate. Tests build a package from a
promoted candidate made in a temporary folder and check each refusal: not promoted, eligibility failure, changed output hash, existing package.

Exit: the first promoted candidate is packaged and lands under `published/` through a pull request.

### Phase 2 — the index, supersession and withdrawal

`published/index.json`, kept by the publish command; `zcad-validation publish withdraw <candidate> --reason`; and the z-cadalog shows a published
candidate's package and its state beside its status.

Exit: a second promoted revision of the same target supersedes the first in the index, and both packages remain.

### Phase 3 — the integration contract

A guide, `docs/guides/consuming-a-package.md`, stating the contract above for a product repository, and a short reader, `examples/read-package.py`,
that uses only the standard library to verify a package's hashes and load its manifest.

Exit: the phase's own exit criterion, a product repository consuming a published candidate using only the documented contract.

## Open questions

- **Which product repository is the first consumer.** The contract is written for one; the first real consumer should review it before phase 3 closes.
- **Whether the package should carry a STEP of the board envelope**, built from the target's measured outline rather than the vendor model, so a
  product repository can check its own clearances. The proposal is to wait until a consumer asks.
- **Whether `published/` belongs in this repository or its own.** The proposal is this one, released with the code that wrote it; a separate
  repository would let packages be released without a zcad-core release.

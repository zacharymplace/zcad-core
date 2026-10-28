# exporters

::: zcad_core.exporters

## Producer provenance

Export metadata retains `schema_version: "1.0"` and all existing fields, with
an additive `producer` object:

```json
{
  "name": "zcad-core",
  "distribution_version": "0.10.0",
  "git_commit": null,
  "tracked_worktree_state": "unknown"
}
```

`distribution_version` comes from installed distribution metadata (or is null).
It is not proof that edited source matches that release. Git identity is resolved
from the loaded core module, independently of the consumer's `repository_root`.
The existing top-level `git_commit` still identifies that consumer repository.

For a tracked source checkout, producer commit and tracked working-tree state
(`clean` or `dirty`) are recorded once per export request. Non-Git installations,
untracked module locations, missing Git or failed/timed-out lookups retain null
commit and `unknown` state. No absolute source paths or file contents are emitted.
Tracked state excludes untracked files and is not an input/dependency fingerprint,
runtime verification, or a reproducibility guarantee. Export metadata readers
should tolerate additive fields. Request/result APIs and artifact names are
unchanged; producer metadata is staged and published with the existing artifacts.

## Per-part artifact bindings

Metadata emitted by `export_parts` includes an additive `artifacts` object with
`step` and `stl` entries. Each contains `filename` (basename relative to the
metadata directory), `sha256` (lowercase hex), and `size_bytes` (integer). These
bind each part's metadata to the staged bytes published with it. Existing
`outputs` paths, validation reports, producer fields, schema version, APIs and
filenames remain unchanged. Round-trip hashes are reused when available; STEP
exports without a feature validator are hashed after staging.

Bindings remain usable when the whole export directory moves. They do not hash
the metadata itself, sign an export, or establish geometric correctness, print
suitability, or runtime compatibility. Verification is opt-in by the reader;
no automatic verification or consumer migration is added. The lower-level
`build_part_record` helper does not read artifact files or add these bindings.

## Read-only artifact-binding verification

`verify_artifact_bindings` is an opt-in check for an existing part's metadata
and sibling STEP/STL files. It does not call exporters, change metadata, or write
receipts. Existing export requests, results and metadata fields are unchanged.

```python
from pathlib import Path
from zcad_core.exporters import verify_artifact_bindings

for check in verify_artifact_bindings(Path("handoff/tamper.metadata.json")):
    print(check.kind, check.status, check.reason)
```

The returned tuple contains one immutable `ArtifactBindingCheck` for each of
`step` and `stl`. Each has a `status`, `reason`, and, when available, filename,
expected/actual SHA-256 and expected/actual byte counts. Statuses are:

- `matched`: both SHA-256 and byte size match the recorded binding.
- `missing`: a valid binding names an absent sibling file.
- `mismatched`: a readable regular file differs in hash or size.
- `not-verifiable`: metadata/binding is missing or malformed, or the file cannot
  be safely read. Legacy exports without bindings never pass implicitly.

Files are streamed read-only. Filenames must be sibling basenames; absolute
paths, path separators, drive syntax, traversal and artifact symlinks are refused.
The directory is the resolved metadata file's parent. Historical `outputs` paths
are never followed. Moving the entire sibling-file export directory is supported;
reorganized bundles with separate artifact directories are outside this contract
and need their own bundle verification. No consumer migration is required.

Results are independent per artifact, with no aggregate verdict. Observed file
changes during reading make the result not verifiable; this is not an atomic
filesystem snapshot or a guarantee against subsequent modification. Matching
bytes against editable metadata does not establish authenticity, geometric
correctness, print suitability, runtime compatibility or recipient acceptance.

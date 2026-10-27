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

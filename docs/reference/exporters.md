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

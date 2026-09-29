# cli

The `zcad-validation` console script. `main()` is the entry point;
`build_parser()` builds the command tree from one module per command group:

| Module | Commands |
| --- | --- |
| `zcad_core.cli.target` | `target register` |
| `zcad_core.cli.candidate` | `candidate create`, `register`, `derive`, `inspect`, `revalidate`, `promote` |
| `zcad_core.cli.fixture` | `fixture export` |
| `zcad_core.cli.trial` | `trial start`, `complete`, `register` |
| `zcad_core.cli.review` | `review complete` |
| `zcad_core.cli.revision` | `revision compare` |
| `zcad_core.cli.status` | `status`, `report` |

Each module defines its handlers and a `register()` that adds its commands
to the parser. The [Validation Lab workflow](../guides/validation-lab-workflow.md)
shows the commands in the order a candidate uses them.

::: zcad_core.cli
    options:
      show_source: true

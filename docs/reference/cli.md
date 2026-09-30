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
| `zcad_core.cli.revision` | `revision compare`, `propose` |
| `zcad_core.cli.status` | `status`, `report` |
| `zcad_core.cli.enclosure` | `enclosure hardware`, `build`, `revise`, `trial start`, `trial complete` |
| `zcad_core.cli.enclosure_group` | `enclosure-group build`, `viewer` |
| `zcad_core.cli.compensation` | `compensation derive` |

Each module defines its handlers and a `register()` that adds its commands
to the parser. The [Validation Lab workflow](../guides/validation-lab-workflow.md)
shows the commands in the order a candidate uses them; the
[enclosure builder](../guides/enclosure-builder.md) and the
[Pi 5 group enclosure](../guides/pi5-group-enclosure.md) guides cover `enclosure`
and `enclosure-group`.

::: zcad_core.cli
    options:
      show_source: true

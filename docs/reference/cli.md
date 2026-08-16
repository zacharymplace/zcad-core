# cli

The `zcad-validation` console script. `main()` is the entry point;
`build_parser()` constructs the full argparse command tree
(`target register`, `candidate create|register|derive|inspect|promote`,
`fixture export`, `trial start|complete|register`, `revision compare`,
`status`, `report`).

::: zcad_core.cli
    options:
      show_source: true

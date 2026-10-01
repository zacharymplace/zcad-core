# Catalogued board files

A board file here joins the board catalog when the package loads: no code. Only
boards that passed their trials belong here. Add one with

```bash
zcad-validation board promote my-board.json \
  --trial-record path/to/trial-001/enclosure-trial.json \
  --trial-record path/to/trial-002/enclosure-trial.json
```

which refuses a file with errors or warnings, an identifier the catalog already
holds, fewer than two passing trials, and a trial of any other version of the
file. It writes `<identifier, lower case, dashes>.json` here with a
`verified_by` field naming the trials; commit it and open a pull request.

The test suite loads every file here and fails if one is invalid, has warnings,
is not named for its board, or lacks `verified_by`.

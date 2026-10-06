# Calibrating a printer with a coupon

Every clearance the engine models is printed by a real printer, which prints holes
small, walls fat and bridges low. A compensation profile corrects for that, and it
is pooled from recorded trials. A calibration coupon gives it those figures from one
quick print, about 18 minutes and 8 g of PETG on the A1 mini, instead of waiting for
fixtures and enclosures to be printed and measured.

```bash
zcad-validation coupon build --output-directory evidence/coupons/a1-mini-petg-01 --slice
```

That writes the coupon's STL, its record (`coupon.json`), a slice in `slice/`, and
an open trial in `trials/trial-001/`. Build it under `evidence/coupons/` so the trial
is backed up with the rest of the evidence. Without `--slice`, start the trial with
`zcad-validation coupon trial start --build-record <folder>/coupon.json`.

## What it measures

The plate is 58 × 43 mm with a notch in its front-left corner. Lay it notch to your
front left: the rows run front to back, each left to right.

- **Front row, holes.** Three M3 insert pockets (4.6 mm) and three M3 screw holes
  (3.4 mm), the sizes an enclosure models. Measure each across its top with your
  calipers' inside jaws, twice at right angles, and record the smaller. They give
  `hole_shortfall_mm`, which sizes an enclosure's insert pockets and lid holes.
- **Middle row, pockets.** 6, 8 and 10 mm wide, cut 2 mm into the top. Measure each
  left to right with the inside jaws. A pocket narrows by a wall's growth on each
  side, so half its shortfall is `side_gap_shortfall_mm`, the per-side figure a
  fixture's gap beside a board reads.
- **Back row, slots.** 0.85, 0.9 and 1.0 mm high under a bridge, the heights a
  fixture's vertical play is modelled at. Record the thickest feeler gauge that
  slides through without forcing. They give `vertical_play_shortfall_mm`.

The coupon is built with no hole compensation, so it measures the printer itself.

## Recording it

Fill in `observations.json` (`printed_cleanly`, `features_open`: `pass` or `fail`)
and each measured `value_mm` in `measurements.json`, then:

```bash
zcad-validation coupon trial complete --trial-directory evidence/coupons/a1-mini-petg-01/trials/trial-001
zcad-validation compensation derive
scripts/backup-evidence.sh
```

On a print day, answer it on the Fixture Fit Trials checklist with the other prints
instead, as `measured`, or `fail` if it did not print; `record-print-day.py` records
it with them (see [the Validation Lab workflow](validation-lab-workflow.md)).

A coupon has no disposition: what it measured is the result. A feature left
unmeasured is left out. A profile needs at least two recorded trials, so print two
coupons, or one coupon and a fixture or enclosure trial, before deriving one. An
enclosure built with `--compensation-profile` then sizes its holes from it and
records which version it used, and a fixture's revision reads its gap and play
figures.

The engine states no limit for any of these readings. A large shortfall says the
printer prints that fit tight; the profile corrects for it, and a trial of the part
it corrected is what shows whether it was enough.

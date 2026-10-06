# Calibrating a printer with a coupon

Every clearance the engine models is printed by a real printer, which prints holes
small, walls fat and bridges low. A compensation profile corrects for that, and it
is pooled from recorded trials. A calibration coupon gives it those figures from one
quick print, about 32 minutes and 10 g of PETG on the A1 mini, instead of waiting for
fixtures and enclosures to be printed and measured. It also tests how far the
printed plastic bends before it breaks, the strain limit every flexure is checked
against.

```bash
zcad-validation coupon build --output-directory evidence/coupons/a1-mini-petg-01 --slice
```

That writes the coupon's STL, its record (`coupon.json`), a slice in `slice/`, and
an open trial in `trials/trial-001/`. Build it under `evidence/coupons/` so the trial
is backed up with the rest of the evidence. Without `--slice`, start the trial with
`zcad-validation coupon trial start --build-record <folder>/coupon.json`.

## What it measures

The plate is 58 × 55 mm with a notch in its front-left corner. Lay it notch to your
front left: the rows run front to back, each left to right.

- **Front row, holes.** Three M3 insert pockets (4.6 mm) and three M3 screw holes
  (3.4 mm), the sizes an enclosure models. Measure each across its top with your
  calipers' inside jaws, twice at right angles, and record the smaller. They give
  `hole_shortfall_mm`, which sizes an enclosure's insert pockets and lid holes.
- **Middle row, pockets.** 6, 8 and 10 mm wide, cut 2 mm into the top. Measure each
  left to right with the inside jaws. A pocket narrows by a wall's growth on each
  side, so half its shortfall is `side_gap_shortfall_mm`, the per-side figure a
  fixture's gap beside a board reads.
- **Third row, slots.** 0.85, 0.9 and 1.0 mm high under a bridge, the heights a
  fixture's vertical play is modelled at. Record the thickest feeler gauge that
  slides through without forcing. They give `vertical_play_shortfall_mm`.
- **Back row, tongues.** Five posts, 12 mm tall and 1 mm thick, each with a stop
  behind it. The gap to the stop is how far the post's top must swing to strain it
  to 1, 1.5, 2, 3 or 4 per cent, by the same cantilever formula every flexure check
  uses. Push each post's top back until it touches its stop, hold five seconds, and
  let go: it passes if it springs back upright with no crack or white mark, and
  fails if it cracks, whitens or stays bent. Start with the gentlest. They give the
  profile's `strain_limit`.

The coupon is built with no hole compensation, so it measures the printer itself.

The tongues bend across their printed layers, the weakest way printed plastic bends,
because a post prints with no overhang and a tongue lying in a layer would not. A
flexure bending along its layers is at least as strong, so the limit they give errs
on the safe side for it.

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
it with them (see [the Validation Lab workflow](validation-lab-workflow.md)), and
shows what the compensation profile would become.

The G7 and Mobi snap-shell scripts take `--compensation-profile` too, and their
candidate records the strain limit their clips were held to.

A coupon has no disposition: what it measured is the result. A tongue can be
`skipped` if you did not test it.

The strain limit is, in each coupon trial, the highest strain every tongue up to it
survived, stopping at the first that failed; across trials it is the lowest of
those, since a limit must hold on every print. A tongue that survived above one that
failed does not count. If any trial's gentlest tongue failed, the profile gives no
strain limit, because the true one is below everything tested.

A build uses the measured limit only when you ask: give `enclosure build`,
`enclosure-group build`, `housing`, `nest` or `stack` `check` or `build` the profile
with `--compensation-profile profiles/compensation/bambu-lab-a1-mini-petg.json`.
Every flexure in that build is then checked against the measured limit, and the
tongues that are sized from the limit (the DIN clip, the lid catches, the stack
detent and latch) are sized from it, so a higher limit gives shorter ones. A record
that states the limit also says where it came from (`strain_limit_source`). A build
without a profile, or with one that has no measured limit, keeps the provisional 1.5
per cent, so deriving a new profile never changes a build that did not ask for it. A feature left
unmeasured is left out. A profile needs at least two recorded trials, so print two
coupons, or one coupon and a fixture or enclosure trial, before deriving one. An
enclosure built with `--compensation-profile` then sizes its holes from it and
records which version it used, and a fixture's revision reads its gap and play
figures.

The engine states no limit for any of these readings. A large shortfall says the
printer prints that fit tight; the profile corrects for it, and a trial of the part
it corrected is what shows whether it was enough.

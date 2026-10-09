# Measuring fits with a joint coupon

Joint coupons measure the figures joints are built with: the **fit coupon**, below,
the clearances a metal part slides or presses into, and the
[snap coupon](#the-snap-coupon-a-drawers-detent) the engagement of a drawer's
detent.

A drill guide's bore, a jig's insert bore, a nest's pocket, a holder's mount and a
PCB fixture's pin bore are all sized from two clearances in the printer profile:
`sliding_clearance_per_side`, for a part that must slide in, and
`press_fit_clearance_per_side`, for one pressed in to stay. Both are marked
provisional: nobody has measured them on this printer. A **fit coupon** measures
them from one print, and a joint profile gives the measured values to every build
that asks for them. See [Joint coupons](../roadmaps/joint-coupons.md) for the design.

```bash
zcad-validation joint build fit --output-directory evidence/joints/a1-mini-petg-fit-01 --slice
```

That writes the coupon's STL, its record (`joint-coupon.json`), a slice in `slice/`,
and an open trial in `trials/trial-001/`. Build it under `evidence/joints/` so the
trial is backed up with the rest of the evidence. Without `--slice`, start the trial
with `zcad-validation joint trial start --build-record <folder>/joint-coupon.json`.

## What it is

Two rows of nine round holes, 0 to 0.4 mm of clearance a side in 0.05 mm steps, each
row running left to right from the tightest. Lay it with the notch at your front
left.

- **Front row, in a layer.** Holes through a block, their axes vertical, so each
  wall is printed perimeters.
- **Back row, across layers.** Holes through a standing wall, front to back, so each
  wall is layer lines and each top an overhang.

Every hole is sized as those products size a hole for a metal part: the reference's
diameter, twice the clearance, and the printer profile's `hole_oversize`. The
reference is a 6 mm drill's shank by default; measure yours with calipers and build
with `--reference-mm` if it is not 6.00, and say what it is with
`--reference-source`. The record keeps the `hole_oversize` the holes were built with,
since a fit measured on those holes says nothing about holes built with another.

## Reading it

Push the reference into each hole by hand, square to the face, and read the hole as:

- `wont_go`: it will not enter;
- `press`: it goes in only with firm pressure and stays put;
- `slides`: it goes in with light pressure and no play you can feel;
- `loose`: it rattles or tips;
- `skipped`: you did not try it.

Answer the two checks too: that it printed cleanly, and that the reference was
measured. Fill in `observations.json`, then:

```bash
zcad-validation joint trial complete --trial-directory evidence/joints/a1-mini-petg-fit-01/trials/trial-001
scripts/backup-evidence.sh
```

A coupon that failed a check is refused: its readings would not say how the printer
fits. On a print day, answer it on the Fixture Fit Trials checklist with the other
prints, giving each rung's reading in the answer's `fit` as
`{"readings": {"in_layer_0_15": "slides", ...}}`; `record-print-day.py` records it
with them (see [the Validation Lab workflow](validation-lab-workflow.md)).

## The profile

With two recorded trials:

```bash
zcad-validation joint derive
```

writes `profiles/joints/bambu-lab-a1-mini-petg.json`. Readings are never averaged;
each figure is the rung a rule picks, and the rule must hold in every trial:

- **sliding clearance**: the smallest rung that slides, in both orientations;
- **press-fit clearance**: the largest rung that is still a press, in both
  orientations.

A figure no rung meets is left out, with the reason, and the printer profile's own
figure stands. Trials built with different `hole_oversize` figures are refused, as
is a press at or above a slide. Deriving again writes the next version and keeps the
previous figures in its history. The profile is a file this repository tracks: derive
it in a worktree and land it through a pull request.

## Building with it

A build uses the measured fits only when you ask: give `guide`, `jig`, `nest`,
`holder`, `housing`, `stack` or `fixture` `check` or `build`, or `gridfinity fitted`,
the profile with `--joint-profile profiles/joints/bambu-lab-a1-mini-petg.json`. Every
clearance that build reads from the printer profile then comes from the joint
profile, and each exported part's metadata names the profile and the fits it gave. A
build without it is exactly what it was.

A build whose printer profile now has a different `hole_oversize` from the one the
coupon was built with is refused the profile: print a new fit coupon.

## The snap coupon: a drawer's detent

A drawer with a detent clicks shut on a bump in each side wall, and the engine
builds that bump to engage 0.4 mm, its own guess. The **snap coupon** builds the
detent at 0.3, 0.4, 0.5 and 0.6 mm, each as a short drawer in a small frame, by the
same code a stack's drawers and frames are built with:

```bash
zcad-validation joint build snap --output-directory evidence/joints/a1-mini-petg-snap-01 --slice
```

About 21 minutes and 8 g of PETG on the A1 mini. Each drawer and frame carry dots,
one for 0.3 mm up to four for 0.6 mm: try each drawer in the frame with the same
number. The tongue is sized from the strain limit the build is held to, so build it
with `--compensation-profile` if a stack would be, and the record keeps the limit.

The slicer warns of a floating cantilever on the drawers. It is the tongue's
underside, printed over the slit that frees it, and a stack's own drawers print the
same way; note whether it sagged.

For each rung, push the drawer shut and record, true or false:

- `clicks_shut`: it clicks home;
- `holds_shake`: held open side down and shaken lightly, the drawer stays in;
- `lets_go`: a fingertip in the pull draws it out without squeezing the frame;
- `whitened`: after ten openings, a white mark or crack on the tongue or bump;

and `pull_force_n`, a spring scale's pull to open it, if you have one. A rung not
tried is `skipped`. Complete it as the fit coupon is:

```bash
zcad-validation joint trial complete --trial-directory evidence/joints/a1-mini-petg-snap-01/trials/trial-001
```

With two recorded snap trials, `joint derive` adds `detent_engagement_mm`: the
smallest rung that clicks shut, holds, lets go and does not whiten, in every trial.
A fit and a snap coupon each need two trials of their own; a family with fewer is
left out of the profile. Snap trials built at different strain limits are refused.

Given `--joint-profile`, a `stack` `check` or `build` then builds every drawer
detent and stop at the measured engagement, unless its stack file sets one. A build
held to another strain limit than the coupon's is refused the profile: print a new
snap coupon at that limit.

The engine states no force for any of these readings. A fit that slides on the
coupon is a fit that slid on the coupon, and a detent that held on the coupon held
there; a trial of the part built with it is what shows it held.

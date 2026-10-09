# Joint coupons

## Purpose

Every product the engine builds is held together by a handful of joints: a sliding fit, a snap that clicks, a pocket an insert or a magnet is
pressed into. The figures that decide whether those joints work are almost all the engine's own guesses. The snap lid's 0.3 mm engagement, the
drawer's 0.2 mm clearance, the stack latch's 0.4 mm engagement, the cradle clip's 0.8 mm overhang and the boss's 1.8 mm wall are `unstated` or
`design_default` in the [figure register](../reference/figures.md). The printer profile's `sliding_clearance_per_side` (0.2 mm) and
`press_fit_clearance_per_side` (0.05 mm), which drill guides, nests, holders and PCB test fixtures all read, are marked provisional.

Today the only way to settle one is to print a whole product and judge it pass or fail: an enclosure's trial asks whether "the lid closes flush",
not at what engagement it stops closing. One print tests one design point of one joint, and a failure does not say which way to move.

The [calibration coupon](../guides/calibration-coupon.md) showed the other way. One 32-minute print measures holes, pockets, bridge play and the
strain limit, and `compensation derive` turns two such trials into a profile every product reads. **Joint coupons** do the same for joints: a small
print per joint family that sweeps the deciding figure across a ladder of rungs, so one trial shows where the joint starts to work and where it
stops, and two trials make a profile.

**Status (2026-10-09): designed, not built.**

## What the engine does not claim

- **A force.** A coupon records whether a joint clicked, held and let go, and a spring-scale reading where the user has one; it does not compute a
  holding force, as no product does.
- **Fatigue.** A rung is worked a stated number of times (ten), not to failure; a joint that wears out after a thousand cycles is not caught.
- **Another printer or material.** A profile is for one printer and one material, as the compensation profile is. A rung that held in PETG on the
  A1 mini says nothing about PLA.
- **A joint the coupon does not reproduce.** A figure moves from a guess to a measurement only for the joint geometry the coupon actually built;
  see the next decision.

## Decision: a coupon is built by the product's own code, not a copy of it

A rung is made by calling the function that builds the joint in a product (`plan_latch` and its solids for a latch, the lid's snap ridge and
groove for a snap, the insert boss for a boss), with only the swept figure changed. A coupon that drew its own hook would measure that hook, not
the product's. When a product's joint code changes, the coupon built from it changes with it, and a profile records the generator version its
rungs were built under, so a rung measured under old geometry is reported as stale rather than silently applied.

## Decision: four coupons, one per joint family

Joints that share a deciding figure share a coupon. Each fits the A1 mini's bed, prints in under 25 minutes, and lays its rungs out in a row
with the figure embossed beside each, as the calibration coupon does.

| Coupon | Swept figure, rungs | Joints it settles | Reading per rung |
| --- | --- | --- | --- |
| **Fit** | clearance per side, 0.0 to 0.4 mm in 0.05 mm steps, as pegs in slots both in a layer and across layers | sliding and press fits (the printer profile's two clearances), the slide lid's groove, drawer clearance, the hinge's knuckle and axis clearance, the locating lip's skirt fit, cradle and retainer clearance | won't go / press / slides / loose |
| **Snap** | engagement, 0.2 to 0.6 mm in 0.1 mm steps, each rung a hook and keeper at the product's reach and thickness | the snap lid's ridge, the stack latch, the slide lid and drawer detents, cradle and retainer clips | clicks on, holds a shake, lets go by hand, whitens; a spring-scale pull if measured |
| **Boss** | M3 insert pocket 4.4 to 4.8 mm, and boss wall 1.2 to 2.2 mm | heat-set insert bosses in enclosures, groups and mounts | seats square, boss splits or bulges, screw holds when tightened |
| **Pocket** | oversize, 0.0 to 0.25 mm in 0.05 mm steps, for a 6 × 2 mm magnet and the catalogued pogo pins and bushings | the printer profile's `magnet_pocket_oversize`, Gridfinity and stack magnet pockets, pogo and bushing seats | won't go / press / snug / falls out |

The fit coupon comes first: its two figures are read by four products today and are the most often used guesses in the engine.

## Decision: a rung is chosen by a stated rule, across every trial

A profile does not average the readings; it picks a rung by a rule written down for each figure, and the rule must hold in **every** trial:

- **Sliding clearance**: the smallest rung that slides, in both orientations.
- **Press-fit clearance**: the largest rung that is still a press.
- **Snap engagement**: the smallest rung that clicks on and holds a shake, provided it lets go by hand and does not whiten. A snap that must not
  let go (a stop) takes the largest rung that still clicks on without whitening.
- **Insert pocket and boss wall**: the pocket that seats square, and the thinnest wall that neither splits nor bulges.
- **Magnet and pin pockets**: the smallest rung that is snug.

Where no rung meets the rule (every snap whitened, say), the figure stays as it was and the profile says why. As with `compensation derive`,
two distinct trials are needed, a third is welcome, and the rung chosen is the one every trial agrees on.

## Decision: a joint profile, read the way the strain limit is

`zcad-validation joint derive` writes `profiles/joints/<printer>-<material>.json`, versioned with its history as the other profiles are, each
figure with the rung chosen, the rule, the trials it came from and the generator version that built them. It never replaces the compensation
profile: holes, pockets and the strain limit stay there.

A product reads it through the same path the strain limit takes: `--joint-profile` (and the same default lookup), applied for the whole command,
so a build without one is exactly what it is today. A figure taken from a profile is written into the build record with the profile's version,
so a trial can say which measured figure it tested.

The figure register gains a status, **measured**, for a figure a joint profile can supply: its note names the profile field, and the page shows
the figure's default beside the measured value when a profile exists.

## The command and the files

```bash
zcad-validation joint build fit --output-directory evidence/joints/a1-mini-petg-fit-01 --slice
zcad-validation joint trial complete --trial-directory evidence/joints/a1-mini-petg-fit-01/trials/trial-001
zcad-validation joint derive
```

Each coupon writes `joint-coupon.json` (the family, the rungs, the generator version, the STL hash) and a trial with one entry per rung in
`observations.json`; `record-print-day.py` records a joint coupon from the Fixture Fit Trials checklist like any other print, and the z-cadalog
lists each coupon as a design.

## Not covered

- **Pull-out and torque figures.** A boss is judged by whether the screw holds when tightened, not by a torque; a pull is recorded only from a
  spring scale the user already has.
- **Hinge swing and catch force.** The hinge's clearances are on the fit coupon; its catch is a snap. The swing and the full closure stay with
  the enclosure trial.
- **Gridfinity's base and lip.** Their figures are sourced from the published specification, and a bin's trial already reads its fit.
- **The Validation Lab's capture figures.** A candidate's clearance and overlap are tuned per board through its own revisions.

## Phases

1. **The fit coupon and the joint profile.** `joint build fit`, its trial, `joint derive` for the two printer-profile clearances, and the four
   products that read them taking the profile's figures when it exists. The register's **measured** status. Exit: a fit coupon is on print day.
2. **The snap coupon.** The hook-and-keeper rungs built from the products' own snap code, the engagement figures in the profile, and the snap
   lid, the stack latch and the detents reading them.
3. **The boss and pocket coupons.** The insert pocket and boss wall, the magnet and pin pockets, and the enclosure, stack, Gridfinity and fixture
   builds reading them.
4. **Stale rungs.** A profile figure whose rungs were built under an older generator than the product now builds is reported, not applied, and
   `joint status` lists what needs reprinting.

Each phase is one PR, and a build without a joint profile is unchanged in every phase.

## Open questions

- **Whether the snap coupon needs a rung per reach.** A latch's tongue and a lid's skirt bend over different lengths; engagement may not carry
  between them. The proposal is one reach per product family on the coupon, three hook-and-keeper pairs a rung, and to split the figure only if
  the first trials disagree.
- **Whether the fit coupon's two orientations should become two figures.** A peg in a layer and one across layers fit differently; the proposal is
  to record both and choose the larger clearance until a product needs them apart.
- **Whether the joint profile belongs inside the compensation profile.** They are derived and read the same way; the proposal is to keep them
  apart so a joint coupon never changes a hole.

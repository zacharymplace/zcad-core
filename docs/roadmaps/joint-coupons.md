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

**Status (2026-10-09): phases 1 and 2 are built.** `zcad-validation joint build fit` and `joint build snap`, `joint trial` and
`joint derive`; see [Phase 1, as built](#phase-1-as-built), [Phase 2, as built](#phase-2-as-built) and the guide, [Measuring fits with a joint coupon](../guides/joint-coupons.md).

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

1. **The fit coupon and the joint profile (built).** `joint build fit`, its trial, `joint derive` for the two printer-profile clearances, and the
   products that read them taking the profile's figures when it exists. Exit: a fit coupon is on print day.
2. **The snap coupon, for the drawer detent (built).** Detent rungs built by the stack's own detent code, the detent's engagement in the
   profile, stack builds reading it, and the register's **measured** status. Narrowed from every snap; see the as-built notes.
3. **The other snaps.** The snap lid, the slide lid and the cradle and retainer clips take their engagement as a parameter, the snap lid gains
   the flexure check the others have, and each gets a row on the snap coupon and a figure in the profile. The stack latch joins once its rungs
   are not capped by one profile's latch window.
4. **The boss and pocket coupons.** The insert pocket and boss wall, the magnet and pin pockets, and the enclosure, stack, Gridfinity and fixture
   builds reading them.
5. **Stale rungs.** A profile figure whose rungs were built under an older generator than the product now builds is reported, not applied, and
   `joint status` lists what needs reprinting.

Each phase is one PR, and a build without a joint profile is unchanged in every phase.

### Phase 1, as built

`features/joint_coupon.py`, `profiles/joints.py` and `cli/joint.py`.

- **The rungs.** Two rows of nine round holes, 0 to 0.4 mm a side: through a block (in a layer) and through a standing wall (across layers),
  96 x 28 x 13 mm. Each is sized by `fit_hole_diameter_mm`, the sum a guide's, a jig's and a fixture's bore are built from, and a test holds
  it equal to the jig's. It is tried with a metal reference, a 6 mm drill's shank by default, not a printed peg: the parts these fits hold are
  metal, and a printed peg would add its own error.
- **A longer print than designed.** It slices to about 38 minutes and 15 g of PETG on the A1 mini, not under 25: the rows need full-height
  walls round each hole. Thinner walls would test a different hole.
- **One place to apply it.** Every product reads its clearances through `printer_numbers`, so the profile is applied there:
  guides, jigs, nests, holders, PCB fixtures, housings, stacks and fitted Gridfinity bins take `--joint-profile`. A profile measured on
  holes built with another `hole_oversize` is refused, not skipped.
- **Recorded in the part metadata.** Each exported part's metadata names the profile and the fits it gave, under `manufacturing`; a build
  without one writes the metadata it always did.
- **The register's measured status moves to phase 2.** The two clearances are in the printer profile, a data file the register does not
  cover, so phase 1 has no registered figure to mark; the snap coupon's engagements are code constants and are.
- **Print day.** `record-print-day.py` records a joint coupon from the answer's `fit.readings`; the z-cadalog lists it as a joint coupon.

### Phase 2, as built

`features/snap_coupon.py`, with the snap family added to `profiles/joints.py` and `cli/joint.py`.

- **Narrowed to the drawer detent.** Built by each product's own code, as the design requires, only the detent took its engagement as a
  parameter across a useful range. The snap lid and the slide lid read theirs from module constants (the snap lid has no flexure check at
  all); the clips take theirs but no build sets it or records it; and the stack latch's planner caps the Gridfinity profile's latch at 0.4 mm.
  Those wait for phase 3 rather than a coupon that measures a copy of them.
- **Four rungs, not five.** 0.3, 0.4, 0.5 and 0.6 mm: the stack's planners refuse an engagement under 0.3 mm, so a 0.2 mm rung cannot be
  built by the product's code.
- **A rung is a drawer in a frame.** A hand-made frame plan (22 x 32 mm inside, a 2 mm wall) through `plan_detent`; the drawer from
  `drawer_solid`, `cut_tongues` and `add_bumps`; the dimples by `cut_dimples` in a box frame open at the front, which stands in for a
  product frame's foot and ledges, neither of which touches the detent. Tests show each shut drawer clears its frame and each bump would
  strike the wall without its dimple. Dots in each drawer's floor and frame's roof number the rungs. 122 x 78 x 13 mm on the bed, about 21 minutes and 8 g of PETG.
- **The tongue prints as a cantilever.** Bambu Studio warns of a floating cantilever on the drawers: the tongue's underside, about 8 mm
  long, printed over the slit that frees it. A stack's own drawers are built by the same code and print the same way; the coupon keeps it,
  so its trial says whether it sags, rather than the coupon testing a tongue the products do not print.
- **Held to a strain limit.** The tongue's length is solved from the limit the build is held to, so the record and the profile keep that
  limit, and a stack build held to another is refused the profile's engagement. The rungs are built with the printer's sliding clearance,
  which a joint profile's fit can supply.
- **The rule.** The detent's engagement is the smallest rung that clicks shut, holds a shake, lets go by hand and does not whiten, in every
  trial; a spring scale's pull is recorded where given. A family with fewer than two trials is left out of the profile, so a fit and a snap
  coupon each make their own figures.
- **Applied in `detent_engagement`.** A stack item's own `detent.engagement_mm` wins; else the applied profile's; else
  `DEFAULT_DETENT_ENGAGEMENT_MM`, 0.4 mm, now a constant of the detent's own and the register's first **measured** figure (its `measures`
  names the profile's `detent_engagement_mm`). The latch's shared 0.4 mm is left as it was.

## Open questions

- **Whether the snap coupon needs a rung per reach.** A latch's tongue and a lid's skirt bend over different lengths; engagement may not carry
  between them. Phase 2 measures the detent alone, as a figure of its own; phase 3 adds each snap as its own row and figure rather than
  carrying the detent's to them.
- **Whether the fit coupon's two orientations should become two figures.** A peg in a layer and one across layers fit differently; the proposal is
  to record both and choose the larger clearance until a product needs them apart.
- **Whether the joint profile belongs inside the compensation profile.** They are derived and read the same way; the proposal is to keep them
  apart so a joint coupon never changes a hole.

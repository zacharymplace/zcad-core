# Stackable latches

## Purpose

[Stackable items](stackable-items.md) hold a stack by the lip alone, or by a magnet or a bolt in a foot. The design asked for a fourth,
**latches**, and phase 2 left them out: a hook outside an item's outline strikes the next bin 0.5 mm away, and the lip's inside is taken
by the foot, so there was nowhere to put one. It left three things waiting on that design: a **snapping cap** for a tray, a **stop for
a drawer**, and the open question of where a keeper goes on a bin.

This is the design for one printed latch, a **snap detent between a foot and a lip**, and for the two items that adopt it after the
bin: a cap that snaps on, and a drawer that clicks shut. The enclosure lid's lip, `--stack-top`, is a separate and smaller piece and is
not in it.

## What the engine does not claim

The stance of the stackable items design carries over:

- **No holding force.** The engine does not say how hard a latch holds, how many times it will snap, or that a printed hook will not
  creep. It says a tongue's strain is under the provisional limit, that the hook has something to engage, and that the parts do not
  collide. A trial records a separation force and a count; the engine has no sourced figure to compare either with.
- **A latch here is a detent, not a lock.** It lets go to a pull. Nothing in the engine is built to keep a stack shut against a
  determined hand; a stack that must not come apart is bolted.
- **No figure it was not given.** The foot and lip sections come from the profile file with its source, and so may the engagement. A
  latch's own sizes (a hook's width, the slit, the flat on a hook's tip, the relief behind a tongue, the ramps) are the engine's design
  choices, listed under each decision and stated as such, and every one is provisional until a trial.

## What the engine already has

| Need | Where it is today |
| --- | --- |
| A foot and a lip as sections, and the check that one nests in the other with a clearance | `stack_profile.py`, `stack_solids.py` (`foot_solid`, the bin's lip, `truncated_lip`) |
| Bins, frames and caps on that foot and lip, and `check-stack` between them | `stack.py`, `stack_check.py`, `stack_file.py` |
| A drawer on ledges inside a frame, with its clearances | `stack_drawers.py` |
| A strain-checked in-plane tongue with a bump, and the refusal with the length it would need | `mounts.flexure_for`, `FLEXURE_STRAIN_LIMIT` (1.5 per cent); the slide lid's detent in `lid_slide.py`; the nest's lip tabs in `nest_features.py` |
| Holding kinds in a stack file, and a mismatch between two items named | `stack_holding.py`, `check-stack` |
| A build record and trials with readings | `stack-build.json`, `stack_trial.py` |

## Decision: where the hook and the keeper go

The foot of the upper item stands in the lip of the lower, and the only space between them is the nesting clearance (0.25 mm with the
example profile). A printed snap needs a hook that sticks out a few tenths of a millimetre into a recess, so the recess has to be cut
into material. There are three places, and the third works:

| Place | Why not, or why |
| --- | --- |
| Outside the item's outline | Bins stand `gap_mm` (0.5) apart. A hook there strikes the next bin. |
| Under the foot's bottom | Between two bins nothing lies under a foot's holding point, so a latch there meets nothing. |
| **On the foot's side, into the lip's inside face** | **The foot is a solid, so a tongue can be cut from it. The lip is solid too, 1.9 mm thick where its face is vertical on the example profile. A baseplate's pocket wall is solid, 3 to 4 mm thick at that height (the ridge narrows to 0.8 mm only at the mouth), so it takes a keeper too.** |

So the latch is a **foot tongue and a keeper**: a hook on the upper item's foot catches in a recess in the lip of the item below, or in
the pocket wall of a baseplate. It holds a bin on a bin, a cap on a bin or a frame, a frame on a bin, and a bin or frame on a baseplate.
A hook that meets no keeper strikes the lip or the pocket wall, so a latched item only stacks on one that has keepers.

### The tongue

A tongue cut from the foot's height cannot work. The foot is 4.75 mm tall; a tongue bending in that direction, 1.2 mm thick and
bending 0.4 mm, would strain 4.5 per cent over 4 mm and needs 6.9 mm for the 1.5 per cent limit. So the tongue lies **along the foot's
side, in plane**, as the slide lid's detent does: a strip of the foot's outer skin, 1.2 mm thick (the printer's minimum wall), freed
by a relief pocket cut up into the foot from its bottom, a slit at its free end and a slit along its top, and fixed at one end. Over
7 mm of reach the same tongue strains 1.47 per cent. The foot is solid inside its skin, so the relief pocket has room, and it opens to
the bed side when the item prints on its foot.

The build takes the least reach, to the next half millimetre, that keeps the strain under the limit for the hook's deflection, and
refuses a profile whose cell side is too short to carry it, saying how much it needs.

### The hook and the keeper

The hook is a wedge on the free end of the tongue with a 45 degree ramp on each side, so the unit goes on with a push and comes off with
a pull. Both ramps deflect the tongue by the same amount, so the strain is checked once.

- **Where.** On the part of the foot's face that is vertical, against the part of the lip's face that is vertical when the foot is
  seated. The build finds both from the profile's sections, and refuses a profile with no vertical run of at least 1.5 mm where the two
  overlap (the example profile has 1.7 mm, from 0.8 to 2.5 mm). Nothing about a face is assumed.
- **How far it engages.** `engagement_mm`, 0.4 by default, is how far the hook's tip reaches past the lip's face. The hook stands out of
  the foot's face by the gap across the wall (0.25 mm) plus the engagement.
- **The keeper.** It is the hook's section grown by the printer's sliding clearance (0.2 mm on the A1 mini) and cut into the face, so it
  is the engagement plus that clearance deep, and the hook seats with room at its tip.
- **Two limits on the engagement**, both from the profile:
  - *The hook's run.* The ramps take twice the hook's protrusion from the vertical run, and a flat of 0.4 mm (a nozzle's width) must
    remain. On the example profile that allows an engagement of **at most 0.4 mm**.
  - *The lip's backing.* The lip behind a keeper must still be a wall: the lip's thickness less the keeper's depth is at least the
    printer's minimum wall. On the example profile that allows at most 0.5 mm.
  The build refuses an engagement over either limit, or under 0.3 mm (the engine's choice), and says what the profile allows. 0.4 mm is
  twice the printer's sliding clearance, which is the honest weakness of this design: a hook that reaches 0.4 mm is a detent a trial must show works.
- **How wide.** A hook is 6 mm along the foot's side, and a slit is 0.8 mm. The keeper is the hook's width plus the clearance each end.

### On the item

`latch: {"sides": ["front", "back"], "engagement_mm": 0.4}` on a bin, frame or baseplate. `sides` are from `front` (-Y), `back` (+Y), `left` (-X)
and `right` (+X), and default to front and back; `engagement_mm` defaults to the profile's, else 0.4. It is a field of its own, not a kind of
`holding`, so an item can hold by magnets and by latches.

- A **bin or frame** gets a tongue and hook on each cell's foot on each named side that is on the item's outside, and a keeper cut in its
  own lip at the same place, so it takes the hooks of an item above and carries its own to the item below.
- A **baseplate** gets a keeper in the pocket wall of every cell on each named side.

A tongue is refused if it would come within the printer's minimum wall of a magnet or bolt pocket at a holding point (13 mm out on the
example profile), or if a cell's side is too short for it. A divider, a label tab or a scoop cannot meet a tongue or a keeper: they stand
inside the walls above the floor, and the tongue is in the foot below it and the keeper in the lip above it.

The keepers are cut in the item **below**, at the same side and cell, so two items must agree on the sides and on the engagement.
`check-stack` says so: hooks with no keeper on that side are refused, and keepers with no hooks only warn.

## Decision: a snapping cap

A cap is a flat lid on a foot, and it already sits in a bin's or a frame's lip. A snapping cap is the same foot tongue and hook on the
cap's foot, snapping into the keeper cut in the bin's or the frame's lip. Nothing about the cap's top changes. A cap needs its bin to
have been built with keepers at the same sides, and `check-stack` says so when it has not.

## Decision: a drawer that clicks shut

A drawer is held by nothing: it comes out when pulled. The stop here is a **closed detent**, the slide lid's detent again. A tongue is cut
in plane from each side wall of the drawer near its back end, with a bump on its outer face, and a dimple is cut into the inside face of
the frame's side wall at the closed position. The drawer clicks into the dimple when it is pushed shut and clicks out when pulled.
It does **not stop** the drawer coming out the front: a drawer leaves the frame when pulled far enough, and this design does not change that.

A frame's wall is the printer's minimum plus the dimple's depth thick, so the build refuses a wall that cannot take a dimple, and a
drawer whose side clearance (0.2 mm on the A1 mini) plus the bump is too small to push the tongue by what the strain check allows.

## Checks

| Check | What it refuses |
| --- | --- |
| Vertical run | A profile whose foot and lip have no vertical overlap of 1.5 mm to put a hook and a keeper in |
| Engagement | An engagement under 0.3 mm, over what the hook's run allows, or over what the lip can back |
| Tongue strain | A cell side too short for the reach the strain limit needs |
| Placement | A tongue within the printer's minimum wall of a holding pocket |
| Keepers agree | Two items in a stack whose latch sides or engagements differ, named by `check-stack` |
| Freed and open | On the built solid: each skin is solid with its relief void, each keeper's mouth void and its backing solid |
| Engages and passes | A hook seated in the lip overlaps what a plain lip would be, so it does engage, and a hook deflected by its tongue's travel passes the plain lip at every height from the lip's top down |
| Seats | The item laid on itself, and on a baseplate with keepers, with no overlap |
| One solid | Every item and every drawer, as before |
| A drawer's dimple | A frame wall too thin for the dimple, or a bump that does not fit the clearance |

## Phases

1. **The foot tongue and the keeper (built).** `latch` on a bin, a frame and a baseplate, the profile's own engagement, the tongue's strain
   and length, the hook, the keepers, the placement checks, the built-solid checks, in `stack_latch.py`; `check-stack` learns the sides.
2. **The snapping cap (built).** The cap's tongue and hook, and the keeper's agreement with a bin or a frame.
3. **The drawer's closed detent (built).** The drawer's side tongues, the frame's dimples, and the checks.
4. **Latch trials (built).** The stack build record carries the latch figures; stack trials gain a latch reading: whether it clicked on and
   off, the **separation force** by spring scale, and a **count of snaps** with whether anything wore. The engine states no limit for any.

Each phase is one PR, and no existing build changes unless an item asks for a latch.

## Not covered

- **A lock.** A latch here is a detent that lets go to a pull. A stack that must stay shut is bolted.
- **A stop that keeps a drawer in.** The closed detent clicks; it does not stop the drawer leaving the front.
- **A latch on an enclosure's lid.** The lid's lip, `--stack-top`, is its own piece.
- **A release tool or a button.** A tongue sits inside the foot and cannot be pressed from outside.

## Open questions

- **Whether a drawer needs a real stop.** A stop that keeps a drawer from leaving the frame needs the drawer lifted over it, and a
  drawer has 0.6 mm of air above it. The proposal is to ship the detent alone and say so; a lifting stop is a design of its own. It is: see [A stop that keeps a drawer in](drawer-stop.md), where lifting is ruled out and the stop is the detent's bump with a vertical face and a window in the frame.

### What phase 1 changed

See *Latches* in [Stackable items](../guides/stackable-items.md).

- **The design's arithmetic was wrong in two places, and phase 1 corrects it.** The keeper is cut the engagement plus the printer's clearance
  past the lip's face, not the gap as well: the hook is what bridges the gap. That lifts the lip's limit on the engagement from 0.45 to
  0.5 mm. But the hook's own 45 degree ramps take twice its protrusion from the 1.7 mm vertical run, which caps the engagement at 0.4 mm
  on the example profile, so 0.4 mm is the default and also the most. And a baseplate can take a keeper, which the design had ruled out.
- **Both halves of the open question were taken.** The engine builds the 0.4 mm default, and a profile can give its own figure:
  `latch: {"engagement_mm", "source"}`, refused without a source or with an example one. A profile with a thicker lip or a longer vertical
  run, which is a profile edit and not a new field, allows more.
- **A baseplate carries keepers.** Without them a latched bin could not sit on a baseplate: its hooks stand 0.4 mm into the pocket wall,
  and the build laid exactly that overlap. `latch` on a baseplate cuts a keeper in each cell's pocket wall on the named sides.
- **`latch` is its own field.** It is not a fifth `holding` kind, which is one choice per item and builds pockets in a foot's bottom.
- **The hook is 6 mm wide and the tongue's reach is 7 mm** (strain 1.47 per cent against 1.5), a tongue 10 mm long with its slit 0.8 mm
  more, on the A1 mini. A tongue is built on every cell along each named side.
- **Holding-pocket clashes are the only placement refusal.** The design also named dividers, label tabs and scoops; none can meet a tongue or
  a keeper, so none is checked.
- **The seat check is the stack's own.** Laying an item on itself and on a baseplate, already in the build, now covers a hook seated in a
  keeper with no overlap; four new checks per latched bin or frame cover the rest.
- **Not built yet:** the drawer's detent and the trial readings, as phases 3 and 4.

### What phase 2 changed

See *Latches* in [Stackable items](../guides/stackable-items.md).

- **A cap takes `latch` like a bin.** It has the same solid foot, so the tongue and hook are the bin's, cut and added by the same functions. It has no lip, so it has no
  keepers. Its `latch` field is the same: `sides` and `engagement_mm`.
- **A cap snaps into the lid bin the build lays it on.** The cap's seat check used a plain bin; it now uses one with keepers cut at the cap's sides, so a hook seated in a
  keeper overlaps nothing. The four latch checks (tongues freed, keepers open, hook engages, hook passes) run on a cap with that bin as the lower item, so `latch_checks`
  takes the lower item as an argument and a bin or frame passes itself.
- **`check-stack` treats a cap as hooks.** A latched cap on a bin or frame needs keepers on the same sides at the same engagement; a plain cap on a bin with keepers sits and warns.
- **A drawer takes no `latch`.** Its field is refused as unknown: a drawer's detent is a different thing, in phase 3.
- **The cap's top is unchanged.** Nothing stacks on it, hooks or none, and its overall height is the foot and its thickness.

### What phase 3 changed

See *A drawer that clicks shut* in [Stackable items](../guides/stackable-items.md).

- **The detent is a field of its own on a frame and a drawer.** `detent` on a frame cuts a dimple in each side wall at every slot; on a drawer it cuts the tongues and adds the bumps. A drawer
  with bumps needs a frame with dimples at the same engagement, as a latched cap needs keepers. It is not a `holding` kind and not a `latch`: a latch is a foot and a lip, and a drawer has neither.
- **The tongue is cut from the drawer's side wall with an open top.** The wall's rim is the tongue's free top, so only two slits free it, one under it and one at its free end, and nothing
  has to be cut behind it: the inside of a tray is open. Its thickness is the drawer's wall, so a thicker wall needs a longer tongue for the same strain.
- **The dimple's place does not depend on the drawer.** The frame is built without knowing its drawers' walls, so the bump is laid out from the back of the drawer (14 mm) and the rim (2 mm
  down), which a frame's own plan gives. Only the tongue's length, which the drawer's wall sets, moves, and it moves toward the back.
- **The frame's wall is the limit.** A dimple of the engagement plus the clearance leaves the wall behind it at least the printer's minimum only if the wall is 1.8 mm or more with the
  default 0.4 mm, so a frame with a detent needs `wall_mm` of 1.8, which the design had named as the check.
- **The slides check frees the bumps once they leave the dimple.** The drawer pulled out by half and nine tenths of its length would press the wall by the engagement, so those positions use
  the drawer without bumps; shut, the drawer with its bumps must clear the frame's dimples.
- **Not built yet:** the trial readings, phase 4.

### What phase 4 changed

See *The build record and stacking trials* in [Stackable items](../guides/stackable-items.md). All four phases are built.

- **The record already carried the latch figures.** Each item's settings (`latch_sides`, `latch_engagement_mm`, `detent`) are in its record entry and its summary holds the sizes, so phase 4 adds
  to the record only what a trial reads: checks for each snap and the sizes to measure. Both schema versions are 1.1.0.
- **Four checks.** `latch_clicks` for an item with hooks, `keepers_clean` for one with keepers, `detent_clicks` for a drawer and `dimples_clean` for a frame. A baseplate has keepers and nothing to
  click, so it is asked only that they are clean; a cap has hooks and no lip, so it is asked only that it clicks.
- **The readings are in their own file.** `latch.json`, beside `stacking.json` rather than inside it, because `stacking.json`'s separation force and count are for a stack sitting on its lip and
  a latch's are for hooks in keepers, and a drawer has no stacking entry. An entry is written for each item that carries hooks and each drawer with a detent, with the designed figures set in it.
  A stack with none writes no file.
- **The force is the same reading under another name.** `separation_force_n` for hooks and `pull_force_n` for a drawer are the highest force a spring scale reads. The engine compares neither
  with a figure: there is none sourced, and the roadmap's engagement figure is waiting on exactly these readings.
- **Not covered:** a rig for the force, a count to wear-out, and a drawer stop that keeps the drawer in, which stays a design of its own.

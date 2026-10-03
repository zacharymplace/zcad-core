# Stackable latches

## Purpose

[Stackable items](stackable-items.md) hold a stack by the lip alone, or by a magnet or a bolt in a foot. The design asked for a fourth,
**latches**, and phase 2 left them out: a hook outside an item's outline strikes the next bin 0.5 mm away, and the lip's inside is taken
by the foot, so there was nowhere to put one. It left three things waiting on that design: a **snapping cap** for a tray, a **stop for
a drawer**, and the open question of where a keeper goes on a bin.

This is the design for one printed latch, a **snap detent between a foot and a lip**, and for the two items that adopt it: a cap that
snaps on, and a drawer that clicks shut. The enclosure lid's lip, `--stack-top`, is a separate and smaller piece and is not in it.

## What the engine does not claim

The stance of the stackable items design carries over:

- **No holding force.** The engine does not say how hard a latch holds, how many times it will snap, or that a printed hook will not
  creep. It says a tongue's strain is under the provisional limit, that the hook has something to engage, and that the parts do not
  collide. A trial records a separation force and a count; the engine has no sourced figure to compare either with.
- **A latch here is a detent, not a lock.** It lets go to a pull. Nothing in the engine is built to keep a stack shut against a
  determined hand; a stack that must not come apart is bolted.
- **No figure it was not given.** The foot and lip sections come from the profile file with its source. A latch's own sizes (a tongue's
  width and thickness, a hook's height and ramps, the least engagement) are the engine's design choices, listed under each decision and
  stated as such, and every one is provisional until a trial.

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
into material. There are three places, and one works:

| Place | Why not, or why |
| --- | --- |
| Outside the item's outline | Bins stand `gap_mm` (0.5) apart. A hook there strikes the next bin. |
| Between the baseplate and a bin | The baseplate's pocket walls come to a ridge 0.8 mm wide at the mouth. There is nothing to cut a keeper in. A baseplate keeps its magnets and bolts. |
| **On the foot's side, into the lip's inside face** | **The foot is a solid, so a tongue can be cut from it. The lip is solid too, 1.9 mm thick where its face is vertical on the example profile.** |

So the latch is a **foot tongue and a lip keeper**: a hook on the upper item's foot catches in a recess in the lip of the item below.
It holds a bin on a bin, a cap on a bin or a frame, and a frame on a bin. It does not hold anything to a baseplate.

### The tongue

A tongue cut from the foot's height cannot work. The foot is 4.75 mm tall; a tongue bending in that direction, 1.2 mm thick and
bending 0.45 mm, would strain 5.1 per cent over 4 mm and needs 7.3 mm for the 1.5 per cent limit. So the tongue lies **along the foot's
side, in plane**, as the slide lid's detent does: a strip of the foot's outer skin, 1.2 mm thick (the printer's minimum wall), freed
by a U-shaped relief pocket cut up into the foot from its bottom and fixed at one end. Over 10 mm the same tongue strains 0.8 per cent.
The foot is solid inside its skin, so the relief pocket has room, and it opens to the bed side when the item prints on its foot.

The build takes the least tongue length that keeps the strain under the limit for the hook's deflection, and refuses a side that is
too short to carry it, saying how long it would need to be.

### The hook and the keeper

The hook is a wedge on the free end of the tongue with a ramp on each side, so the unit goes on with a push and comes off with a pull.
Both ramps deflect the tongue by the same amount, so the strain is checked once.

- **Where.** On the part of the foot's face that is vertical, against the part of the lip's face that is vertical when the foot is
  seated. The build finds both from the profile's sections, and refuses a profile that has no vertical run of at least 1.5 mm where
  the two overlap (the example profile has 1.7 mm). Nothing about a face is assumed.
- **How far it engages.** `engagement_mm`, 0.4 by default, is how far the hook reaches into the keeper past the lip's face. The hook
  stands out of the foot by the nesting clearance plus the engagement; the keeper is cut that deep into the lip.
- **What it leaves.** The lip behind a keeper must still be a wall: the lip's thickness less the keeper's depth is at least the
  printer's minimum wall. On the example profile (lip 1.9 mm, clearance 0.25 mm, wall 1.2 mm) the deepest keeper leaves **an engagement
  of at most 0.45 mm.** That is about twice the printer's sliding clearance of 0.2 mm, which is the honest weakness of this
  design: a printed hook that reaches 0.4 mm is a detent a trial must show works. The build refuses an engagement under 0.3 mm
  (the engine's choice) and one the lip cannot back, naming the lip's thickness and the most it allows.
- **How wide.** A tongue is 10 mm wide with 0.8 mm slits, the nest lip's proportions. The keeper is the hook's width plus the
  printer's sliding clearance each end, and its height is the hook's plus the same.

### Where on the item

`latch: {"sides": ["front", "back"], "engagement_mm": 0.4}` on an item that holds by latch puts one tongue at the middle of each
named side's first cell (0.5 mm in from the cell's edge, so it clears the corner radius). A tongue is refused if:

- it would meet a holding-point pocket (a magnet or a bolt at the cell's corner, 13 mm out on the example profile);
- it would meet a divider, a label tab or a scoop on the item above it, which are inside the walls;
- the side has no straight stretch long enough (a cell's side is 42 mm less the corner radii on either end).

The keepers are cut in the lip of the item **below**, at the same side and cell, so a stack's two items must agree on the sides.
`check-stack` already says whether two items agree on a holding kind; it learns to say whether their latch sides and engagements agree.

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
| Engagement | An engagement under 0.3 mm, or one the lip cannot back: the lip behind the keeper under the printer's minimum wall |
| Tongue strain | A tongue longer than its side allows, or strain over the provisional limit, with the length it would need |
| Placement | A tongue that meets a holding pocket, a divider, a label tab or a scoop, or a keeper that meets another keeper |
| Keepers agree | Two items in a stack whose latch sides or engagements differ, named by `check-stack` |
| Seats and releases | The hook is laid in its keeper and the tongue deflected both ways: the unit goes down with no collision and comes off with none |
| One solid | Every item and every drawer, as before |
| A drawer's dimple | A frame wall too thin for the dimple, or a bump that does not fit the clearance |

## Phases

1. **The foot tongue and the lip keeper.** Latch fields on a bin and a frame, the tongue's strain and length, the hook, the keeper, the
   placement checks and the seat-and-release check, in `stack_latch.py`; `check-stack` learns the latch sides.
2. **The snapping cap.** The cap's tongue and hook, and the keeper's agreement with a bin or a frame.
3. **The drawer's closed detent.** The drawer's side tongues, the frame's dimples, and the checks.
4. **Latch trials.** The stack build record carries the latch figures; stack trials gain a latch reading: whether it clicked on and
   off, the **separation force** by spring scale, and a **count of snaps** with whether anything wore. The engine states no limit for any.

Each phase is one PR, and no existing build changes unless an item asks for a latch.

## Not covered

- **A lock.** A latch here is a detent that lets go to a pull. A stack that must stay shut is bolted.
- **A latch between an item and a baseplate.** The baseplate has no room for a keeper; it holds by magnets or bolts.
- **A stop that keeps a drawer in.** The closed detent clicks; it does not stop the drawer leaving the front.
- **A latch on an enclosure's lid.** The lid's lip, `--stack-top`, is its own piece.
- **A release tool or a button.** A tongue sits inside the foot and cannot be pressed from outside.

## Open questions

- **Whether an engagement of at most 0.45 mm is worth building.** It is the most the example profile's lip backs, and the printed fit
  swamps it. The proposal is to build it with the 0.4 mm default and let the trial answer; the alternative is a profile field that
  gives the lip a thicker zone for a keeper, which would be the user's figure with a source.
- **Whether a drawer needs a real stop.** A stop that keeps a drawer from leaving the frame needs the drawer lifted over it, and a
  drawer has 0.6 mm of air above it. The proposal is to ship the detent alone and say so; a lifting stop is a design of its own.

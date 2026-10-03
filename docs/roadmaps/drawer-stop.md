# A stop that keeps a drawer in

## Purpose

A drawer is held by nothing. [Stackable latches](stackable-latches.md) gave it a **closed detent**: it clicks shut and clicks out, and a pulled drawer still comes
out of the front. That design set the real stop aside, saying only that it "needs the drawer lifted over it, and a drawer has 0.6 mm of air above it". This is the design for
it: a **stop** that keeps a drawer in the frame when it is pulled out, and lets go when it is released.

## What the engine does not claim

- **No holding force.** The engine does not say how hard the stop holds against a pull, or how many releases it takes. A trial reads a force and a count.
- **A stop is not a lock.** It keeps a drawer from leaving by being pulled; a determined hand squeezing the release takes it out, as intended.
- **No figure it was not given.** The sizes are the engine's own choices, provisional until a trial; the printer's clearance and minimums are the profile's.

## What the engine already has

| Need | Where it is today |
| --- | --- |
| A tongue cut from a drawer's side wall with a bump, strain-checked, and a dimple in the frame's wall | `stack_detent.py` (phase 3 of the latches) |
| A frame, its slots, its ledges and the drawer's clearances | `stack_drawers.py` |
| A drawer swept in every slot at three travels against the frame | `stack._drawer_slides` |
| Trial readings for a drawer's detent | `latch.json`, `stack_trial.py` |

## Decision: how a stop can work, and the ones that cannot

A drawer stands on two ledges, 0.6 mm under the next ledge or the roof, with 0.2 mm of clearance each side. Four ways of stopping it were weighed.

| Way | Why it works or does not |
| --- | --- |
| **Lift it over a lug** | The stop's height is at most the air above the drawer, 0.6 mm, minus the printer's clearance. That is smaller than the print can hold. And tipping the front up swings the drawer's rear *back* and down, away from a lug above it and into the ledge, so tilting does not help. |
| **A tab on the frame's front, pulled to release** | A tab that sticks out beyond the cell's outline strikes the next bin, which stands 0.5 mm away. Inside the outline, a tongue in the frame's wall moves *inward* when pressed from outside, which pushes its hook further in, not out of the way. |
| **A screw or pin** | It works and needs a tool, a hole through the roof over every drawer, and a catalogued insert in each. It is the fallback if the squeeze below fails. |
| **A window the bump drops into, squeezed to release** | **The only one that keeps to the grid, needs no tool and works with parts the engine already builds.** |

## Decision: the closed detent's bump, a vertical face and a window

The drawer already has a tongue with a bump on each side, near its back, clicking into a dimple in the frame's wall. A stop reuses it and changes two things.

- **The bump's front face is vertical.** Today the bump has a 45 degree ramp on each side so it clicks both ways. With a vertical face on the side the drawer moves toward when it is pulled
  out, the bump cannot cross a vertical edge, and it **stops** against it. Its rear face stays a 45 degree ramp.
- **The frame has a window** through each side wall, at the place the bump reaches when the drawer is pulled out the stop's distance. The window's front edge is a vertical wall, so the bump
  catches on it and the drawer stops. The bump sits in the window with its tip 0.4 mm into it, short of the outside of the wall.

**The closed detent still clicks.** The dimple is cut the same as now, with 45 degree walls, and a bump whose front face is vertical in a dimple whose front wall is a ramp still rides up it
and out, because the bump's corner meets the ramp. Only the window's front edge is a hard face.

**To release,** squeeze: a pin or a fingernail through each window pushes its bump in by the engagement, and the drawer comes out, with the tongues springing back after. The windows are on
both sides, so a thumb and a finger on the two outside faces of the frame push both at once. **To put the drawer back,** its rear goes in, the bump meets the frame's front edge with its rear face, a 45 degree
ramp, which pushes it in, and the bump drops into the window and stops, and a push shuts the drawer, clicking into the dimple.

### The sizes

- **Where the window is.** The bump sits 14 mm from the drawer's back, so with the drawer shut its front face is about 25 mm back from the frame's front edge. The window's front edge can be
  no nearer the frame's front edge than 3 mm, to keep a wall there. **The stop's travel is therefore about 22 mm of a 40 mm drawer, 56 per cent**, with the example profile. A drawer
  stopped there has more than half of its length inside the frame. A tongue moved as near the back as it can go, 10.2 mm, gives about 26 mm, 65 per cent; no tongue fits nearer, because its
  root must stand clear of the back wall.
- **The window** is as tall as the bump (3 mm) and 0.6 mm more each way, and as wide along the wall as the bump's base (1.6 mm) and 4 mm more, so a pin 2 mm across reaches the bump. It keeps the printer's minimum wall round it, which the frame's wall (1.8 mm) and
  the ledges below allow.
- **The drawer's wall** is at least 1.8 mm for the same reason the frame's is (a tongue needs the engagement and the clearance past a minimum wall), and the build says so.

## Checks

| Check | What it refuses |
| --- | --- |
| Stop in reach | A stop distance under a fifth or over two thirds of the drawer, or a window that leaves under a minimum wall at the front edge |
| Window | A window the frame's wall cannot take: under the printer's minimum wall round it |
| Bump | A bump that the tongue's strain does not allow, as the detent's is checked |
| The stop holds | The drawer pulled to the stop, with its bumps pushed in by nothing, is stopped by the window: its bump overlaps the window's front wall if pulled a millimetre more |
| The release works | A bump pushed in by the engagement passes the window and the whole of the travel after it |
| It goes back | A bump pushed in by the engagement passes the frame's front edge, the window and the closed dimple |
| The drawer slides | As now: shut, and at half and nine tenths out, with the bumps pushed in once out of their holes |
| One solid | The frame and the drawer |

## Phases

1. **The stop (built).** `stop` on a frame and a drawer beside `detent`: the vertical-faced bump, the window, the checks, the record's figures.
2. **Stop trials (built).** Readings in `latch.json` for a drawer with a stop: whether it stopped, the **force** a pull needed to take it past, whether it released and went back, and a count with
   whether anything wore. The engine states no limit for any.

Each phase is one PR, and no existing drawer changes unless it asks for a stop.

## Not covered

- **A stop with no release.** A drawer that cannot be taken out at all is a different part.
- **A stop on a drawer with no detent.** The stop reuses the detent's tongue, so a drawer with a stop has one.
- **A stop past two thirds of the drawer's length.** The tongue's root keeps the bump 10 mm from the back.
- **A tool-free release for a frame in a stack.** The windows are in the frame's side walls; a frame closed in on both sides by other items has no way in for a pin.

## Open questions

- **Whether a 56 per cent pull-out is enough.** It is what the example profile's drawer allows with the detent's tongue where it is; 65 per cent is the most. The proposal is to build 56 and let a trial say.
- **Whether both sides need a stop.** One side only is released with one pin, and lets a drawer hang by a single bump. The proposal is both sides.

### What phase 1 changed

See *A drawer that clicks shut* in [Stackable items](../guides/stackable-items.md).

- **No chamfer.** The design said a chamfer on the frame's front edge would push the bump in as the drawer goes back. A drawer going in leads with the bump's *rear* face, which is a 45 degree ramp, so
  the bump rides over the frame's front edge and the window's rear edge on its own, and the thin edge the chamfer would have left, with the 2.0 mm wall rule that came with it, is gone.
- **The dimple has a ramped front wall for a stop.** A vertical-faced bump does not fit the dimple the symmetric bump had: its square corner is outside the ramp. A stop's dimple is the bump grown by the
  clearance with its front wall a 45 degree ramp that starts the clearance ahead of the bump's face and climbs to the wall's face, so the bump's corner rides up it and the drawer still clicks out of its
  closed position. Only the window's front edge is a hard face.
- **The stop's travel is 21.5 mm, 54 per cent.** The window's front edge is 3 mm back from the frame's front edge, and the bump's face is 0.2 mm clear of it at the stop. The design said about 22 mm and
  56 per cent; the clearance and the bump's half-base account for the difference. A stop must come out between a fifth and two thirds of the drawer, and is refused outside that.
- **`stop` is an empty object on a frame and a drawer** and needs that item's `detent`: it reuses the detent's tongue, dimple and engagement. A drawer with a stop needs a frame with one. A frame with
  windows and a drawer with only a detent is fine: the drawer's symmetric bump rides in and out of a window like anywhere else, and nothing stops it.
- **The window** is 5.6 mm along the wall and 4.2 mm tall, through the wall, at every slot on both sides. Windows in slots closer than the printer's minimum wall plus the window's height are refused.
- **Three checks, two of them against the real frame.** `stop_holds`: the bump pulled out the stop's travel sits in its window, and a millimetre farther strikes the window's front wall. `stop_releases`: a bump pushed
  in by the engagement passes the whole travel of the frame with its dimples and windows. And the frame's `stop_windows_open`: each window void with the wall solid just ahead of its front edge.
- **Not built yet:** the trial readings, as phase 2.

### What phase 2 changed

See *Trying a print* and *The build record and stacking trials* in [Stackable items](../guides/stackable-items.md). Both phases are built.

- **The stop's readings join the drawer's in `latch.json`.** A drawer with a stop has the detent's readings (clicked shut and open, the pull force out of the dimple, a count and whether anything wore)
  and four more: `stopped`, `stop_force_n`, `released` and `went_back`. A plain detent drawer is read as before, and its entry has no stop fields.
- **Two checks and one for the frame.** `stop_holds` and `stop_releases` for the drawer, `windows_clean` for its frame, asked only of items that have a stop.
- **How far it stops out is a measurement.** The record's sizes to measure add `<drawer>_stop_travel_mm`, the designed 21.5 mm, and `<frame>_window_length_mm` and `_window_height_mm`; a trial's
  measurement of the travel is set beside it, so the question the design left open, whether 54 per cent is enough, gets a number from each print.
- **The force is a reading, not a limit.** The stop force and the pull force are the highest a spring scale read. The engine compares neither with a figure, and says nothing about whether a stop holds.
- **Not covered:** a rig for the force, and a drawer that stops past two thirds of its length.

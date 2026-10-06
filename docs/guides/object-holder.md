# A holder for an object

A holder is a cup on a back plate that hangs on a wall: a remote, a power brick or a torch drops into it from above and sits on its floor.
You measure the object with calipers, say which way up it stands, and say how the holder is fixed to the wall.

```bash
zcad-validation wearable template --device custom --output remote.json
# measure the object and fill it in, as for a wearable, then:
zcad-validation wearable check remote.json
zcad-validation holder template --capture remote.json --output remote-holder.json
# say how it stands and what it hangs on, then:
zcad-validation holder check remote-holder.json
zcad-validation holder build --holder-file remote-holder.json --output-directory exports/remote-holder
```

The object is a **custom capture**, the same file a wearable housing is built from: three caliper readings of its length, width and thickness, its
outline (a rectangle or a rounded rectangle), the features on its edges and its face, and its mass. [Measuring a wearable](wearable-capture.md)
says how to take one; a remote is measured the same way, buttons up. `holder template --capture` writes a holder file that names your capture and its
SHA-256, so a holder whose capture has changed is refused. `holder check` reads the capture and builds the holder, and exits 1 listing every problem.
`holder build` exports it as STEP and STL, checks it against the printer profile, and writes `holder.json`, a record of what was built from what, which
says the holder is **unverified**.

## The holder file

| Field | What it is |
| --- | --- |
| `object.capture`, `object.sha256` | The capture, relative to the holder file or absolute, and its hash. |
| `down_edge` | The capture's edge that sits on the floor: `north`, `south`, `east` or `west`. |
| `face` | `out`, the capture's top face toward the room, or `wall`. An object with `face_features` must face out. |
| `holder.front_mm` | How high the front and sides climb. Left out, a third of the object's height, at least 10 mm. It cannot be more than the object's height. |
| `holder.wall_mm`, `holder.floor_mm` | The walls and floor (2.0 each). Neither can be under the printer's minimum. |
| `holder.back_mm` | The back plate: 4.0 for screws, 6.0 for keyholes. |
| `fit` | `{"clearance_mm": x, "source": "why"}`, a clearance per side of your own. Left out, the printer's. |
| `mount` | `{"type": "screws", "head_diameter_mm", "shank_diameter_mm", "source"}`, or `{"type": "keyhole"}`. |

## How it stands

The object stands on its `down_edge`. Seen from the room, a capture on `south` stands with its north edge up and its east end on the right; on `west`, with
its east end up and its south edge on the right. Its length or width, whichever is not along the floor, is the holder's height. With `face: wall` the
object is turned round, so what was on the left is on the right.

The pocket is the object's outline seen from the room, with its rounded corners, grown by the clearance on every side but the floor it rests on, and
open at the top, so the object lifts straight out. The clearance is the printer profile's sliding clearance (0.2 mm on the A1 mini, provisional). With
`--compensation-profile`, the coupon's measured side-gap shortfall is added to it, and with `fit` in the file, your figure is used and the source recorded.

## What it leaves open

A **finger notch**, 20 mm wide, is cut down the front's middle to the floor, unless the pocket is too narrow for it and 5 mm of front each side.

Every feature the capture names that the holder would cover is left open, 1 mm past each end:

- an edge feature on the down edge (a charging port, so the object charges in its holder) gets a **slot through the floor**;
- an edge feature on a side, below the wall's top, gets a **notch down that side**, from the feature to the wall's top;
- a face feature below the front's top gets a **notch down the front**, the same way.

Notches run to the top so nothing overhangs. A floor slot as wide as the floor would cut the cup in two and is refused, and so is a face feature with
the face toward the wall.

## The mount

The fixings sit in the back plate behind the object, side by side if the pocket is wide enough for two a fixing's width apart, otherwise one above the
other, and clear of the plate's edges, the floor and the plate's top by 2 mm.

- **Screws.** Your screw's head and shank, with where the sizes came from. The hole is the shank plus the profile's hole oversize, and a 90-degree
  countersink on the pocket side takes the head flush, so the object never sits on a screw head. A plate too thin to sink the head is refused with the
  thickness it needs. An 82-degree wood-screw head seats on the countersink's rim, a little proud of flush; the 90-degree cone is what prints upright.
- **Keyholes.** The mounts' keyhole: a 9.0 mm head hole and a 4.5 mm slot running 10 mm up, with a channel in the plate's back face that a screw head
  standing 3.0 mm off the wall rides up as the holder drops onto it. A plate under 5.5 mm is refused.

## Printing it

The holder prints as it hangs, floor down, so its walls are vertical and nothing overhangs. Every hole through the back plate is horizontal, so each is
drawn as a teardrop pointed up, and a keyhole's slot and channel end in a 45-degree point. A holder taller than the printer's bed is refused.

## What is checked

The holder is **one solid**. The object, put in its pocket, shares no volume with it, and lifted straight up in 2 mm steps meets nothing on the way.
Every opening is clear of the holder over the feature's whole width, and every fixing's hole is open through the plate.

**The engine says nothing about the load a holder bears, whether its screws hold in your wall, or what a wall plug takes.** It says the object fits,
lifts out, and that what you named is left open. The capture's mass goes into the record so a trial can say what the holder carried. A holder is
unverified until it has been printed and used with the real object. Retaining tabs, pegboard and adhesive mounts, STEP models and trials are later
phases of [the design](../roadmaps/object-holders.md).

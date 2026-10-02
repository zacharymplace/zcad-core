# A housing for something you wear

A wearable housing holds a device or a board so you can carry it. This release builds
one you **hold**: how it attaches to a body (a strap, a band, a clip, an adhesive plate)
comes later. There are two styles:

- a **cradle** for a **sealed device** (a sensor, a pump, a tracker) that a
  [caliper capture](wearable-capture.md) describes: one printed tray it snaps into; and
- a **case** for a **board** that a [board file](board-file.md) describes: the
  single-board enclosure with a snap lid, thinner walls, and rounded outer corners.

```bash
zcad-validation housing template --style cradle --input-file my-device.json \
  --output my-housing.json
# edit the walls, then:
zcad-validation housing check my-housing.json
zcad-validation housing build --housing-file my-housing.json \
  --output-directory exports/my-housing
```

**The engine states no claim** about skin contact or biocompatibility, water or sweat,
comfort, or a device's function. PETG is not validated for skin by this engine, a
housing is not sealed, and whether a cradle that covers part of a device is safe to
wear it is yours to judge. The build says this in its output.

## The housing file

| Field | What it is |
| --- | --- |
| `style` | `cradle` or `case`. |
| `wearable.file`, `wearable.sha256` | A cradle's device: its capture file and hash. |
| `board.file`, `board.sha256` | A case's board: its board file and hash. |
| `wall_mm`, `floor_mm` | The walls and the floor (1.2 mm each by default). Each must meet the printer's minimum. |
| `clearance_mm` | A cradle's gap round the device (0.3 by default). |
| `retention_edges` | A cradle's edges that carry a tab (all four by default); at least three. |
| `lid_mm`, `corner_radius_mm` | A case's lid (2.0) and the radius of its outer vertical corners (1.0). |

The file names what it houses by hash, and the check and the build refuse a housing
whose device or board has changed since: change the housing file and its hash to say
you meant to.

## The cradle

The device lies in a pocket, face away from the body up, on a floor that closes the
skin side. A wall rises round it to the device's top face, and **the face is left
open**.

- **Tabs.** A snap tab on each chosen edge holds the device in. It is the top strip of
  the wall, cut free from the wall below by a slit along its underside and from the
  wall beside it by a slit at its free end, so it bends outward in the plane of the
  wall, like a diving board. Its hook stands 0.6 mm in over the device's top edge. A
  tab bending along the wall has the length it needs even on a thin device. The tab's
  strain, `3 t d / (2 L^2)`, is checked against the same provisional 1.5 per cent
  limit as the snap clips and the lid catch: the default 12 mm tab of a 1.2 mm wall
  strains 0.75 per cent. A thicker wall is refused, with the tab length it would need.
- **Edge features.** Each feature the capture lists on an edge (a port, a button, a
  contact) gets a notch through the wall, and a tab stands off it by 1 mm. Every tab is
  slid along its edge to the nearest place clear of its edge's features and of the
  corners; an edge with no clear place is refused, naming it, and you take it out of
  `retention_edges`.
- **Face features.** A button or a screen on the face is left open. The build refuses a
  tab whose hook would cover one, naming it and the edge.
- **Checks.** The tray is one solid, the device fits the pocket with nothing meeting
  it, and every edge feature's notch is open.

## The case

The case is the enclosure builder's own, round a board from a board file: its
openings for the connectors, its standoffs or its cradle, and a **snap lid** with
nothing to screw. The housing file sets the walls and the lid, and rounds the outer
vertical corners of both parts.

**The radius is limited by the wall.** The cavity's corners stay square, so rounding
the outside takes wall from the corner's diagonal. The build refuses a radius that
leaves the diagonal under the printer's minimum wall and says the most it can have:
1.2 mm on a 1.2 mm wall, 2.6 mm on a 1.6 mm one. Rounding the skin-side edges and a
rounded cavity come later.

## What is not built yet

A way of wearing it (the next release), a `shell` style that reaches the snap-shell
clips through the housing file, the skin side's rounded edges, a housing build record
and trials. A cradle for a catalog device without a caliper capture is not offered:
the capture is what the cradle is built round.

# A housing for something you wear

A wearable housing holds a device or a board so you can carry it, and can be worn: on a
strap, a band, a belt, an adhesive patch, or a lanyard. There are two styles:

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
| `skin_edge_radius_mm` | The radius of the skin face's outer edge (0.8, 0 to 5; 0 leaves it square). |
| `lid_mm`, `corner_radius_mm` | A case's lid (2.0) and the radius of its outer vertical corners (1.0). |
| `wear` | The ways of wearing it: a list, each with its figures and their source. See *Ways of wearing*. |

The file names what it houses by hash, and the check and the build refuse a housing
whose device or board has changed since: change the housing file and its hash to say
you meant to.

## The cradle

The device lies in a pocket, face away from the body up, on a floor that closes the
skin side. A wall rises round it to the device's top face, and **the face is left
open**.

Because the floor covers the skin side, a device whose skin side must stay open
against the body, such as the Dexcom G7 with its adhesive patch and sensor filament,
can sit in a cradle as a holder but cannot be worn in one: a G7 cradle with any `wear`
is refused, and the build record says `skin_side_covered: true`.

- **Tabs.** A snap tab on each chosen edge holds the device in. It is the top strip of
  the wall, cut free from the wall below by a slit along its underside and from the
  wall beside it by a slit at its free end, so it bends outward in the plane of the
  wall, like a diving board. Its hook stands 0.6 mm in over the device's top edge,
  measured from the device's edge, so a wider `clearance_mm` never shortens it. A
  tab bending along the wall has the length it needs even on a thin device. The tab's
  strain, `3 t d / (2 L^2)`, is checked against the same provisional 1.5 per cent
  limit as the snap clips and the lid catch: the default 12 mm tab of a 1.2 mm wall
  strains 0.75 per cent. A thicker wall is refused, with the tab length it would need.
- **Edge features.** Each feature the capture lists on an edge (a port, a button, a
  contact) gets a notch through the wall, and a tab stands off it by 1 mm. Every tab is
  slid along its edge to the nearest place clear of its edge's features and 2 mm short
  of where a rounded corner begins, as the snap shell's clips are; an edge with no clear place is refused, naming it, and you take it out of
  `retention_edges`.
- **Face features.** A button or a screen on the face is left open. The build refuses a
  tab whose hook would cover one, naming it and the edge.
- **Checks.** The tray is one solid, every edge feature's notch is open, and every tab's hook reaches over the
  device's top face.

## The case

The case is the enclosure builder's own, round a board from a board file: its
openings for the connectors, its standoffs or its cradle, and a **snap lid** with
nothing to screw. The housing file sets the walls and the lid, and rounds the outer
vertical corners of both parts.

**The radius is limited by the wall.** The cavity's corners stay square, so rounding
the outside takes wall from the corner's diagonal. The build refuses a radius that
leaves the diagonal under the printer's minimum wall and says the most it can have:
1.2 mm on a 1.2 mm wall, 2.6 mm on a 1.6 mm one. A rounded cavity comes later.

## Ways of wearing

`wear` is a list; each entry has a `kind`, **the figures that kind needs, and a `source`
that says where they came from**. The engine has no figure for a strap, a band, a belt, a
patch or a cord, so they are yours. `housing template --wear strap --wear lanyard` adds
examples to replace; a file whose `source` still says `EXAMPLE` is refused.

| Kind | You give | It builds |
| --- | --- | --- |
| `strap` | `strap_width_mm`, `bar_diameter_mm` | A lug at each end: a prong either side of the strap with a hole across them for a spring bar, and a web joining them to the body. |
| `band` | `band_width_mm`, `band_thickness_mm` | An ear at each end on the skin plane, each with a slot the band threads through. |
| `clip` | `belt_thickness_mm` | A spring arm under the back, fixed at one end and free at the other, with a nub that grips a belt slid between it and the back. |
| `adhesive` | `patch_mm` (`[width, depth]`), optional `corner_radius_mm` | A flat flange of the patch's outline on the skin plane, one piece with the housing. |
| `lanyard` | `cord_diameter_mm` | A flat tab on the +Y side with a hole a millimetre wider than the cord. |

```json
"wear": [
  {"kind": "strap", "strap_width_mm": 20, "bar_diameter_mm": 1.8,
   "source": "the strap I will use, measured with calipers"},
  {"kind": "lanyard", "cord_diameter_mm": 3,
   "source": "the cord I will use"}
]
```

- **Each is checked against the housing.** A strap needs lugs `strap + 4 mm` across, so it
  is refused if wider than the housing's width less 4 mm (23.1 mm on the cradle of a
  device the G7's size); the
  lugs must also be shorter than the housing is tall. A band needs ears `band + 3 mm` wide.
  An adhesive patch must hold the housing with 2 mm to spare. A belt clip's arm is as long as
  the housing allows, up to 18 mm, and is refused, with the length it would need, if its
  strain would pass the provisional 1.5 per cent limit. Every problem is listed at once.
- **Two that take the same place are refused:** a strap and a band (both stand on the two
  ends), and an adhesive plate with a clip or a band (all on the skin side). A strap and a
  lanyard, or a band and a clip, go together.
- **They are built on the housing's body** (a cradle's tray, a case's base) and are one solid
  with it. The cradle's pocket and the case's cavity are checked again afterwards.
- **The engine states no figure for how well any holds a body**, and no print has shown yet
  that any prints cleanly: a belt clip hangs below the floor, so the housing prints on
  supports under it, and a lug's hole prints across the layers. A trial measures both.
- **The constants are the engine's own, not yours:** the lug is 2.0 mm thick with 1.5 mm
  round its hole, the bar 3 mm out from the end, the band's ear 2.0 mm thick, the belt
  clip 12 mm wide with a 1.2 mm arm and a 1.0 mm nub, and the belt gap the belt's thickness
  and 0.4 mm. They are design choices to be tried, not sourced figures.

## The skin side

The skin side is the lowest face of the housing's body, the one a body touches.

- **Its outer edge is rounded** to `skin_edge_radius_mm` (0.8 mm by default). So is the
  free edge of each flat feature on the skin plane: a band's ear, an adhesive flange, a
  lanyard's tab. A slot's edge, where a band passes, is not rounded.
- **The radius is a comfort setting, not a medical figure.** The build says so; the engine
  states nothing about skin, comfort or contact.
- **The radius is limited** to the floor's or the wall's thickness, whichever is less, and
  to 0.1 mm under the housing's outer corner radius: a skin edge as round as the corner it
  turns leaves a sliver there. The build refuses a larger one and says why.
- **Nothing stands proud of the face** except a belt clip, which stands on the back where
  the belt goes. The build reports `skin_side` with how far anything stands below the face
  and which ways of wearing do, and checks that this matches what the ways report.

## The build record and wear trials

`housing build` writes `housing-build.json` beside the parts: the style, the housing file and
the file it houses by hash, each way of wearing with the figures and source you gave, the skin
side, each part's STL hash, the checks a trial asks, the dimensions it measures, and what the
engine does not claim. It refuses to replace one.

```bash
zcad-validation housing trial start --build-record exports/my-housing/housing-build.json
# print it, fit it, wear it; fill in observations.json, measurements.json and wear.json
zcad-validation housing trial complete --trial-directory exports/my-housing/trials/trial-001 \
  --disposition pass
```

`wear.json` holds the readings of wearing it, each left blank if not taken:

- **Retention force**: the highest force a spring scale read pulling the device out of a
  cradle, or lifting a case's lid, with the device's mass if the capture gave one.
- **A pull test** for each strap, band, lanyard and clip: the load reached and what gave, or
  that nothing did. An adhesive plate has none, since the patch holds it, not the housing.
- **A count of wears**, and whether anything wore or cracked. Both answers need the count.
- **Whether skin was irritated**: a person's observation, kept as written with its notes.
  The engine draws no conclusion from it.

**The engine states no limit for any reading** and no figure to compare one with. A
completed trial checks that the printed parts still match the record by hash, is never
overwritten, and a passing one cannot have a failed check.

## What is not built yet

The snap shell is not a
housing style: it is a frame and clips, with nothing to hang a strap from, and a cradle is the form
of it that can be worn. A cradle for a catalog device without a caliper capture is not offered:
the capture is what the cradle is built round.

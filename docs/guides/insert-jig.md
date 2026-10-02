# An insert jig for your part

An insert jig holds a part, and a heat-set insert square over its pocket, while a soldering iron presses the insert in. It is a **nest** round the part's
shadow with a **plate** on the part's top face, and a **bore** through the plate over each insert. The insert drops down the bore and is held square by
it; the iron's tip goes down the bore, and its **shoulder rests on the plate**, so the plate is the depth stop.

```bash
zcad-validation jig template --part bracket.step --output my-jig.json
# say what the part is, measure your iron, say where each insert goes, then:
zcad-validation jig check my-jig.json
zcad-validation jig build --jig-file my-jig.json --output-directory exports/my-jig
```

`jig template --part` writes a jig file that names your STEP model and its SHA-256. `jig check` reads the part and exits 1 if the jig cannot be built, listing
every problem at once. `jig build` exports the jig as STEP and STL, checks it against the printer profile, and writes `jig.json`, a record of what was built from
what, which says the jig is **unverified**.

## The jig file

| Field | What it is |
| --- | --- |
| `part.step`, `part.sha256`, `part.solid_index` | The part, as for a nest. A part that has changed since is refused. |
| `jig.depth_mm` | How far the nest climbs the part's side from its top. Left out, half the part's height, at least 3 mm. |
| `jig.wall_mm` | The wall round the pocket (2.0). It cannot be under the printer's minimum wall. |
| `jig.depth_below_face_mm` | How far below the part's top face the insert's top ends (0, flush). |
| `insert.size` | A catalogued fastener, such as `M3`. Its heat-set insert's diameter and length come from the catalogue. |
| `iron.tip_diameter_mm`, `iron.shoulder_diameter_mm`, `iron.tip_length_mm` | **Your iron's figures.** The tip that goes down the bore, the wider body above it, and how far the tip stands out below the shoulder. |
| `iron.source` | Where those figures came from. It is needed, and the template's placeholder is refused until you replace it. |
| `inserts` | Typed positions, one entry per insert: `id`, `x_mm`, `y_mm` in the part's frame, and optionally `pocket_diameter_mm` and `pocket_depth_mm` for the pocket the part already has. |
| `insert_holes` | `{"from_part": true, "holes": ["H01", "H03"]}`: take positions from the part's own holes. `holes` picks some; left out, every hole found is taken. |

A file needs `inserts`, `insert_holes`, or both. Typed and found positions can be mixed, and every name must be different.

The part's frame is its own: centred on its bounding box in X and Y, with +X right and +Y up the page seen from above, and its **top face at z = 0**. Everything is
in millimetres.

## The bore and the plate

A bore is the insert's catalogued diameter plus the printer's sliding clearance each side and its hole oversize (printers print holes small). The plate stands on the
part's top face, so the part needs a flat top, and its thickness is

> `iron.tip_length_mm − jig.depth_below_face_mm`

so that, with the shoulder on the plate, the tip's end is at the insert's top. An iron whose tip will not go down the bore with a clearance to spare, whose shoulder
is not wider than the bore by a minimum wall each side (so it has land to stand on), or whose length makes a plate thinner than the printer's minimum floor, is refused with
what it would need. Those clearances and the land are the engine's own choices.

Each bore must lie wholly in the part's shadow, and two bores keep at least a minimum wall of plate between them. An insert whose length, ending `depth_below_face_mm`
below the face, is more than the part's height is refused.

## Positions from the part's own holes

With `insert_holes.from_part` the jig reads the part's model for **round holes open at its top face**, blind pockets and through-holes alike: a cylinder about the
vertical axis, at least 1 mm across, whose upper end is at the top face and whose axis is in the void. A hole in the part's side, or a boss, is not one. They are named
`H01`, `H02` and so on in order of place (lowest Y first, then X), the same naming and order the drill-guide import uses, and `jig check` lists them in its errors when you
name one the part does not have. A part with none is refused.

Each found hole is a position, with its diameter and depth as the pocket's, so it gets the same checks as a typed pocket (below). Naming no `holes` takes every hole found,
so a hole that is too small for the insert, such as a clearance hole for the screw, is refused by name: pick the holes you mean. The positions come from the model, which is
the part as modelled, not as made; the record marks each bore's `origin` as `part` or `typed`.

## The pocket the part already has

If you give a pocket's size and depth the engine checks them against the catalogued insert: a pocket **smaller** than the insert's size by more than 0.3 mm is
refused (the insert could not be started), a pocket 0.3 mm or more **off** the catalogued size gets a warning, and a pocket shallower than the insert's length plus
`depth_below_face_mm` is refused. A pocket left out is not checked, and the check says so.

## What is checked

The jig is **one solid**. The part is put in its pocket and shares no volume with it, and the jig lifts straight off the part. Every bore is open through the plate.
The iron's tip reaches the insert's top when the shoulder rests on the plate. The jig must fit the printer's bed, and is printed plate down.

**The engine states no temperature, time or force for installing an insert, and nothing about whether an insert holds or a part survives the heat.** It says where
each insert is and how far the iron can go. A jig is unverified until a printed trial has passed.


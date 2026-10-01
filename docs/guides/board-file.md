# Your own board

The catalog holds a handful of boards. For any other rectangular board, describe
it in a JSON file and build an enclosure from that:

```bash
zcad-validation board template --output my-board.json
# edit every number, then:
zcad-validation board check my-board.json
zcad-validation enclosure build --board-file my-board.json \
  --output-directory exports/my-board --review
```

`board template` writes a valid example (every number in it is an example, and
its sources say so). `board check` refuses what cannot be right, lists what
probably is not, and exits 1 if the file cannot be used. `enclosure build`
takes exactly one of `--board` (the catalog) and `--board-file`.

The engine does not trust a board file. It checks it, builds from it, and says
in the build summary and in `enclosure.json` that the board came from a file,
with the file's path and SHA-256, and that it is **unverified**. A printed trial
is what tells you the numbers were right.

## Measuring a board

Look at the board from above, with its centre as the origin: **+X to the right,
+Y up the page**. The edge at +Y is `positive_y`. Width runs along X, length
along Y. Everything is in millimetres. The board is never rotated.

| Field | What to measure |
| --- | --- |
| `board.width_mm`, `length_mm`, `thickness_mm` | The PCB's outline and its thickness, with calipers. Typical thickness is 1.6 mm. |
| `mounting_holes.diameter_mm` | The hole diameter. |
| `mounting_holes.positions_mm` | Each hole's `[x, y]` from the board's centre, **or** `spacing_mm`, `[dx, dy]` between a rectangle of four holes. Give one, not both. Leave the section out and the board sits in a snap-in cradle held by its edges. |
| `standoff` | Optional `height_mm` (under the board) and `clearance_mm` (round it). |
| `cable_connector` | The connector the cable plugs into, which the wall is opened for. Its `edge`, `width_mm`, `height_mm`, `depth_mm`, `center_offset_mm` along the edge from the middle, and `bottom_offset_from_board_top_mm`. It sits inside the outline against its edge. Required. |
| `wall_openings` | Anything else the wall must be opened for, such as a barrel jack: `edge`, `width_mm`, `height_mm`, offsets. |

### Two levels of detail

- **Envelope.** Measure the height of the tallest part above the PCB and write
  `"envelope": {"top_mm": 12.0}`. The loader turns that into one box covering
  the whole board, so the enclosure is taller than it must be but never too
  short. Only the top is offered: a box under the whole board would cut the
  standoffs away, so list parts under the board as components.
- **Components.** A list of boxes: `identifier`, `center_x_mm` and
  `center_y_mm` (from the board's centre), `width_mm` (along X), `depth_mm`
  (along Y), `height_mm`, and `bottom_offset_from_board_top_mm` (0 for a part
  standing on the board, negative for one under it), with optional
  `access_edge` and `lid_vent`. A part lies wholly above or wholly below the
  board. If it reaches past an edge, mark `access_edge` so the wall is opened
  for it.

Give an envelope **or** components, not both.

## Power

```json
"power": {"typical_w": 0.5, "peak_w": 1.0, "source": "meter reading, 5 V, idle"}
```

feeds the [temperature estimate](enclosure-builder.md#temperature-estimate) as
a figure from you. A `source` is required: power with no source is not used.
Without a power figure the estimate says the board's power is unknown.

## What the check refuses and warns about

Refused (errors): wrong `schema_version` or `units`, an outline other than
`"rectangle"`, unknown fields, holes outside the board or given two ways, a
connector running off its edge, a part through the board, an envelope with a
bottom, power without a source, and any file still carrying a `needs_review`
note. All problems are listed at once.

Warned of: a board over 150 mm or a thickness outside 0.4 to 3.2 mm (usually
the wrong unit), a hole near the edge, holes closer than a standoff is wide, no
holes, a part overhanging an edge that is not marked `access_edge`, and a file
with no `source`.

## Revising

`enclosure revise` rebuilds from the same file. It refuses if the file is
missing or has changed since the build: a revision changes the design, not the
board. To change the board, build again from the changed file.

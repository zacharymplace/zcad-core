# Measuring a wearable

The Dexcom G7 and Tandem Mobi snap shells start from published sizes, so their
candidates are `provisional_synthetic_candidate` and no trial may use them. A
caliper capture replaces those sizes with your measurements of the real device.
A candidate built from it is a `verified_candidate`, ready for a printed trial.

```bash
zcad-validation wearable template --device tandem-mobi --output mobi.json
# measure, fill in, delete needs_review, then:
zcad-validation wearable check mobi.json
python scripts/build-tandem-mobi-snap-shell-candidate.py \
  --revision r003 --parent r002 --reason "Caliper capture of the pump" \
  --capture mobi.json
```

Use `--device dexcom-g7` and `scripts/build-dexcom-g7-snap-shell-candidate.py`
(with `--revision r002 --parent r001`) for the sensor.

## What you need

- A digital caliper reading to 0.01 mm, zeroed with its jaws closed.
- The device, clean and dry. A Dexcom G7 should be one not yet applied.
- About fifteen minutes.

## Lay the device down the same way every time

Lay it with the face that sits away from the body facing up. Its **length**
runs left to right (X) and its **width** front to back (Y); the length is the
longer side. The edges are named like a map:

| Edge | Where | Runs along |
| --- | --- | --- |
| `north` | the far side | the length |
| `south` | the near side | the length |
| `east` | the right end | the width |
| `west` | the left end | the width |

Write in `orientation` how you laid it ("buttons up, fill port at the east
end"), so the next capture lays it the same way. The shell's clips stand at the
middle of each edge it uses: north, south, and east on the G7, all four on the
Mobi.

## Body: three readings each

Take each dimension three times at different places, and enter all three. The
median is used, so one slip does not move it.

| Field | Measure |
| --- | --- |
| `length_mm` | West end to east end, near the north edge, through the middle, and near the south edge. |
| `width_mm` | South edge to north edge, near the west end, through the middle, and near the east end. |
| `thickness_mm` | Top face to bottom face, at three places away from any button or raised mark. |

Measure the body, not the adhesive patch, the sensor wire, or a belt clip.
Close the jaws until they just touch; squeezing a rounded edge reads small.

## Edge features: everything a clip must not cover

List every feature on an edge that a clip would cover or press: the Mobi's fill
port, buttons, and charging contacts, and anything else you find. Each gets:

- `identifier`: a name, such as `fill-port`.
- `edge`: the edge it is on.
- `width_mm`: how far it runs along that edge.
- `center_offset_mm`: where its middle is along the edge, from the edge's
  middle. Measure from the **start** of the edge (the west end of `north` and
  `south`, the south end of `east` and `west`) to the feature's middle, then
  subtract half the edge's length. A feature right of the middle on `north` is
  positive; one near the south end of `east` is negative.
- `notes`: how you measured it.

Then set `edge_features_checked` to `true`, to say you looked at all four edges.
An empty list with `true` means there was nothing there. Features on the top or
bottom face are not listed: the shell's clips each stand `clearance_mm` out
from their edge and hook `overhang_mm` (0.6 mm) over the top edge, clear of the
top face, and its frame holds the device by a ledge under its rim. The rim of the
frame, 1 mm up the device's sides, is notched at each edge feature.

## A device of your own

`--device custom` writes a capture for any sealed device, not only the two the
catalog knows:

```bash
zcad-validation wearable template --device custom --output tracker.json
```

Set `"device": "custom"` and give it a `name`. A custom device has **no published
size**, so the check has nothing to compare your readings with: the three readings
and your `source` are all that stand behind it. (A typo such as `dexcom-g8` is still
refused, because only `custom` is taken as your own.) Everything above applies to it
unchanged, and three optional sections, which a Dexcom or Mobi capture may also use:

- **`outline`**: the body seen from above, `"rectangle"` (the default) or
  `{"type": "rounded_rectangle", "radius_mm": 3.0}`. The radius is at least 0.1 mm
  and no more than half the body's width.
- **`face_features`**: the buttons, windows, screens and ports on the face away from
  the body, which a housing must leave open. Each has an `identifier` and a box in the
  same frame as the edge features: `center_x_mm` and `center_y_mm` from the device's
  centre (+X east, +Y north), and `width_mm` along X and `depth_mm` along Y. Every
  corner of the box must lie inside the outline, including a rounded corner. An empty
  list says there are none; a custom device with no `face_features` at all is
  questioned, since a sensor or tracker usually has something on its face.
- **`mass`**: `{"value_g": 18.5, "source": "a kitchen scale, one tracker"}`, between
  zero and 5000 g, with how it was found. Only a trial's readings use it.

A capture made before these existed is still valid, and loads with no outline radius,
no face features and no mass. `wearable check` prints the device's name, its outline,
its face features and its mass beside the sizes.

## What the check does

`wearable check` lists every problem at once and exits 1 if the capture cannot
be used.

Refused: a wrong `schema_version` or `units`, an unknown device or field, a
dimension without three positive readings, a size more than 25% from the
published one (usually a wrong unit or two dimensions swapped), a feature
running off the end of its edge, a device's expected feature (the Mobi's
`fill-port`, `button` and `charging-contacts`) missing from `edge_features`,
which a cradle would otherwise wall over, `edge_features_checked` not `true`, no
`measured_by`, `measured_on`, `caliper`, `orientation`, or `source`, and a file
still carrying `needs_review`.

Warned of: readings of one dimension more than 0.1 mm apart (measure it again),
and a size more than 2 mm from the published one (confirm it).

A valid capture prints the sizes the candidate will use and its SHA-256.

## What a candidate built from it records

- **Size:** the envelope is the median of each dimension.
- **Clips:** each clip moves along its edge to the nearest place that clears
  every feature there by 1 mm. It stays 2 mm from the corners. If no place on an
  edge is clear, nothing is written and the script names the edge.
- **Provenance:** the capture file is copied into the candidate's folder as
  `capture.json`. Its SHA-256, who measured, when, and with what go into
  `automated-validation.json`.
- **Fit:** the shell is measured against the captured envelope. No shell
  material may be inside it or within the clearance of its sides and top face,
  each clip's lip must reach `overhang_mm` in over the top face, the frame
  and clips must be one solid, and a clip bending out to let the device past
  must strain no more than the engine's provisional 1.5 per cent limit. A
  clip bends over its stem between the rim and the lip, so a thin device
  fails: on the 4.7 mm G7 it strains about 6 per cent, and the G7's shell is
  `rejected` until its clips are redesigned. The Mobi's, 14.2 mm, passes. `automated-validation.json` records each check
  and how much shell material is inside the envelope (`clips_into_device_mm3`).
- **Status:** when every check passes the decision is `verified_candidate` and
  the geometry is `caliper-verified`. A failed check makes it `rejected`. A
  printed trial on the real device is still what proves it.

The capture names whoever measured. It lives in `evidence/`, which is backed up
privately, not in the public repository.

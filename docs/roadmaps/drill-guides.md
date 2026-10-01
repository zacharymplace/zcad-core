# Drill guides and fixtures

## Purpose

Every product so far wraps a board. A fixture is the other half of a workshop:
a printed part that holds or guides something else while you work on it. The
commonest is the drill guide: a block that sits on a part, registers against
it, and keeps a drill on the right axis at the right place. Today that takes a
combination square, a pencil, and luck, or a CAD session per part.

The engine can already read a part from a STEP model, find its outline and its
round holes, offset a pocket to fit it, check printer fit, and sweep a moving
part through a design to see what it hits. This is the design for a fixture
that uses all of that: you give it a part and where the holes go, and it
builds the guide and refuses one that cannot work.

A holding nest (a pocket that cradles a part for sanding or gluing) and a PCB
test fixture are the same base with different parts on top. The nest is built
here as the guide's lower half; the test fixture has its own design,
[PCB test fixtures](pcb-test-fixtures.md).

This is a design, not built work. Nothing below exists in the code yet.

## What the engine already has

| Need | Where it is today |
| --- | --- |
| Read a part's solids from STEP, find the base plate and its round through-holes | `board_import`: `load_solids`, `find_pcb`, `through_holes`, in the model's own frame, +Z up |
| The part's outline as a polygon, simplified | `board_import.pcb_outline`, `board_outline` (point-in-polygon, distance to boundary, chords) |
| A pocket that follows a polygon, with a ledge, a wall, and snap clips | `board_cradle._local_outline_cradle`, built from offset prisms |
| Printer fit: `hole_oversize` 0.2 mm, `press_fit_clearance_per_side` 0.05 mm, `sliding_clearance_per_side` 0.2 mm, and minimum wall 1.2 mm | the printer profile, all marked provisional |
| Sweep a moving part through a design and name what it hits | `lid_hinge._require_free_swing`, `lid_slide._require_free_travel` |
| A part with sourced figures, each marked read or unread | `hardware/fans.py`, `hardware/thermal.py` |
| An unverified design that a printed trial verifies | board files, `enclosure trial`, `board promote` |
| Export, validation against the printer profile, and a slice check | `export_parts`, `slice_models` |

What it lacks is the fixture itself: a frame that places a part, a guide that
carries bores, and the checks between them.

## Decision: a guide is a nest below and a plate above

The guide has two parts that print as one:

- **The nest** is a pocket on the underside that the part sits in. It decides
  where the guide goes.
- **The plate** is above it. It carries the bores, each a hole or a seat for a
  steel bushing, and decides where the drill goes.

The nest follows the part's *silhouette*, not its whole solid. Looking down the
approach direction (+Z of the part's frame), the part's footprint is a polygon,
read the way `pcb_outline` reads a board's top face and widened by the sliding
clearance. A pocket that is that polygon extruded to the nest's depth lets the
part drop straight out, always, with no undercut to catch. The cost is a looser
fit where the part has an undercut or a taper, and the doc says so rather than
hiding it. A true offset of the whole solid is a later option; it is slower, and
the OpenCascade offset is fragile on real models.

The nest depth and the bearing face are the part's: the guide rests on the
part's top, or on a ledge of the nest when the part has no flat top. Which one
is a choice the user makes in the guide file, because only the user knows what
the guide must reference.

### The guide file

Like a board file, a guide is JSON the user writes and the engine checks before
building anything:

```
zcad-validation guide template --output my-guide.json
zcad-validation guide check my-guide.json
zcad-validation guide build --guide-file my-guide.json --output-directory out
```

It holds a `part` (a STEP path and its hash, and which solid is the part when the
model has several), the nest's `bearing` choice, and the `bores`: each has a
position on the part's top plane in millimetres from the part's centre, a
diameter, an optional tilt, and a `kind` of `printed` or `bushing`. Units are
millimetres, and positions are in the part's own frame, +X right and +Y up the
page, seen from above, as for a board.

### Bores

A printed bore is the drill's diameter plus the printer's `hole_oversize` and
`sliding_clearance_per_side`. It guides, and it wears: a printed bore opens up as
a bit cuts it, so the doc calls it a few-holes tool, not a production one.

A bushing bore is a pocket for a steel drill bushing, sized from the bushing's
outer diameter and the profile's `press_fit_clearance_per_side`. A bushing is a
catalogued part, like a fan: its inner and outer diameter, length, and flange,
each figure with its source and a `read` flag. The catalog starts empty. A
bushing's figures are a maker's datasheet, and no figure goes in until one is
read. Until then a bushing bore takes the user's own figures in the guide file
and says they are the user's.

The plate's thickness is set by what the bores need: at least the bushing's
length, or for a printed bore a default of 1.5 times the drill's diameter, which
is a design default and not a measured one. A trial replaces it.

### Tilt

A bore may tilt by up to 45 degrees about X or Y, for an angled hole. A tilted
bore makes the plate thicker where it leaves the bearing face, and the drill's
chuck, a cylinder wider than the bit, swings toward the plate. The chuck check
below is what refuses a tilt that the chuck cannot reach.

## Checks

A guide that fails a check is not built.

| Check | What it refuses |
| --- | --- |
| The part is where it says | The solid's hash differs from the file's, or the named solid is not found |
| Release | The part, moved up out of the nest in 2 mm steps, meets the guide |
| Bores on the part | A bore's axis, projected onto the part's top plane, falls outside its silhouette, or within a printed wall of its edge |
| Bore spacing | Two bores' walls are closer than the printer's minimum wall |
| Chuck clear | A cylinder of the chuck's diameter, along each bore's axis from the plate's top to the drill's depth, meets the guide or another bore's bushing |
| Drill exit | The drill's depth would go past the part's underside plus a margin, with nothing under it to take the bit |
| Bed | The guide fits the bed in its print orientation |

The drill's diameter, the chuck's diameter, and the depth are all inputs. The
engine does not look them up, because a drill is not a catalogued part here.

### Print orientation

The guide prints plate-down, so the bores print vertical, where a printed hole
is roundest. A tilted bore prints at an angle, and is the one that comes out
worst; the build says so for any bore tilted past 20 degrees.

## Decision: a guide is unverified until a trial measures it

A printed guide's accuracy is not something the engine can compute. The honest
position is the one the board files take: the build records the part's hash,
the file's hash, the profile's tolerances (all provisional), and
`verified: false`. It states no accuracy.

A trial measures what the engine cannot. For a guide it records, per bore, the
position a drilled hole came out at against its nominal, and for the bore and a
bushing seat their fit on a gauge. A guide that has passed two trials is
verified, and the offsets across trials are pooled into a measured positional
error, which the build then reports as a number with its sample size, the way
the pooled thermal coefficient is. Until there are trials it reports none.

## Phases

1. **Part, nest, and release.** `guide check` on the file's part and nest only;
   the part loader, the silhouette, the nest and plate shell, the release
   check, the build record with the part's hash, and `guide template`.
2. **Bores.** The bore schema and checks, printed bores and bushing seats, tilt,
   the chuck sweep, the drill-exit check, and the bushing spec with its sourcing.
   `guide build` exports a guide.
3. **From a part.** `guide import` reads a part's round through-holes and writes
   them as bores, so a guide can copy a hole pattern from a master part onto a
   part that has none. The bearing choice for a part with no flat top.
4. **Trials.** Guide trials in the Validation Lab, the pooled positional error,
   verification, and the guide's page in the docs on how to measure one.

Each phase is one PR. Phases 1 to 3 add a way in and change no existing build.

## Not covered

- **Production jigs.** A steel or hardened plate, a clamped fixture for a run of
  parts, and a guide for a power tool's feed. This is a bench guide for a few
  holes.
- **Curved or sloped faces.** The bearing face is flat or a nest ledge. A guide
  that finds a drilling normal on a curve is a later feature.
- **Metal, thick stock, and heat.** A printed guide is for wood, plastic, thin
  sheet, and a pilot in soft metal, with a bushing. The engine does not model
  cutting force, heat, or what material a part is.
- **Mesh models.** STL and OBJ parts have no solids to read; STEP only.
- **A drill and bushing catalog.** The engine takes a drill's size as an input,
  and a bushing is added when a datasheet has been read.

## Open questions

- **A silhouette pocket or a true offset.** The silhouette always releases and
  is simple; a true offset fits an undercut tighter and can fail on a real model.
  The silhouette is proposed for phase 1, with the offset a later option.
- **Where the nest's depth comes from.** A guide that sits on a part's top needs
  the nest to reach down only to the first fence, not the whole part. Proposed:
  the user names a depth in the file, with the part's height as the most.
- **Bushing seats before any bushing is catalogued.** The proposal is that the
  user's own figures are accepted and labelled, as a user's board power is.
- **Whether a guide also does a clamp.** A printed clip or a screw that holds
  the guide to the part is outside this first pass; the guide is held by hand.

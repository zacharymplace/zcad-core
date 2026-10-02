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
[PCB test fixtures](pcb-test-fixtures.md). A holding nest with a floor, notches and a label,
and an insert jig, are designed in [Nests and jigs](nests-and-jigs.md).

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

1. **Part, nest, and release (built).** `guide check` on the file's part and
   nest only; the part loader, the silhouette, the nest and plate shell, the
   release check, the build record with the part's hash, and `guide template`.
   See *What phase 1 changed* below, and the guide
   [A drill guide for your part](../guides/drill-guide.md).
2. **Bores (built).** The bore schema and checks, printed bores and bushing
   seats, tilt, the chuck sweep, the drill-exit check, and the bushing spec with
   its sourcing. `guide build` exports a guide. See *What phase 2 changed*
   below.
3. **From a part (built).** `guide import` reads a part's round through-holes
   and writes them as bores, so a guide can copy a hole pattern from a master
   part onto a part that has none. The bearing choice for a part with no flat
   top. See *What phase 3 changed* below.
4. **Trials (built).** Guide trials, the pooled positional error, verification,
   and the guide's page in the docs on how to measure one. See *What phase 4
   changed* below.

### What phase 1 changed

- **The shadow is a raster, not the top face's outline.** The design said to
  read it the way `pcb_outline` reads a board's top face. A top face is not a
  part's shadow: an undercut or a part that overhangs its plate casts a wider
  one, and a pocket cut to the top face would catch it. So the shadow is the
  union of every triangle seen along Z, drawn on a grid and traced
  (`geometry/silhouette.py`), dilated by a pixel so it is never smaller than
  the part. It uses numpy and scipy, which CadQuery already pulls in, and no
  boolean operations.
- **Most of a board model is never meshed.** Meshing is most of the time, so
  solids are drawn largest first and any whose bounding box already lies inside
  the shadow is skipped. The Pi 5's 2689 solids take about 30 s, not 170.
- **`guide build` exists already.** The design listed the build record under
  phase 1 without saying what was built, so phase 1 exports the nest and plate
  as a holding nest, with the record. There are no bores, and a file that lists
  any is refused with a message saying so.
- **The bearing is `top` only, and a flat top is required.** At least 10% of the
  shadow must be flat material at the part's top. The ledge for a part with no
  flat top is phase 3's.
- **The wall and plate are settable.** `nest.wall_mm` (2.0) and
  `plate.thickness_mm` (6.0) are in the file, checked against the printer
  profile's minimums. The plate's thickness is meant to follow the bores' needs
  in phase 2; until then it is the user's.

### What phase 2 changed

- **The bushing's figures are inline, not catalogued.** As the design proposed:
  a `bushing` section in the file with a required `source`, and a build record
  that says the figures are the user's own. No bushing type is added to the
  hardware catalog until a datasheet has been read.
- **The chuck is found by sliding it, not by sweeping a fixed cylinder.** The
  design's check sent a chuck-wide cylinder along the axis. What matters is how
  far up the axis the chuck must stand to clear the plate and any flange, which
  sets how much bit must stand out of it. The build slides a cylinder up each
  bore's axis until it clears (the plate and every flange, a neighbour's too),
  and reports `bit_needed_beyond_chuck_mm`. A `drill.stickout_mm` makes that a
  refusal; without one it is a reported figure. A vertical bore's standoff is 0,
  a tilt's is about the chuck's radius times the tangent, a flange's is its
  thickness.
- **The tilt is about X or Y, signed.** `tilt_about` and `tilt_deg` (up to 45
  either way): about X leans the drill's lower end toward +Y, about Y toward +X.
  A flanged bushing cannot tilt, since a flat flange will not seat on a plate it
  is not parallel to; use a printed bore or a flangeless bushing.
- **The plate's thickness follows the bores.** Left out of the file, it is the
  longest bore's length along the vertical, rounded up to half a millimetre; a
  printed bore is 1.5 drill diameters (at least 3 mm), a bushing bore its body
  without the flange. Both are defaults. A thickness in the file must be enough.
- **Both ends of a bore are checked.** The design checked a bore's axis on the
  part's top plane. A tilted bore's head sits across the plate from its foot,
  so the head must also stand inside the plate's outline.
- **Drill exit and break-out.** A drill that would come within 1 mm of the part's
  underside is refused unless the bore sets `allow_exit`; one whose tip would
  leave the part's side is refused too.
- **A printed hole is bigger than the drill by three terms.** The drill, the
  sliding clearance each side (the intended gap), and `hole_oversize` (what a
  printer takes off a hole). The bushing pocket is the same with the press-fit
  clearance.
- **Play is reported, as a bound.** For each bore the record gives the most the
  drill can sit off the axis from the clearances alone (the nest's, the bore's,
  and a bushing's), at the surface and at the hole's bottom. It is derived from
  the printer profile's provisional tolerances, is labelled so, and is not an
  accuracy. Phase 4 replaces it with what trials measure.
- **A guide check needs the printer profile** for the bores (their fits and
  walls), so `guide check` takes `--printer-profile`, defaulting to the A1 mini's.

### What phase 3 changed

- **The ledge is the part's own shoulder.** The design left "a ledge of the nest"
  open. Built: the nest follows the shadow of only the part's top `depth_mm`
  (cut by slicing the model), so the part widens under its rim and the guide
  rests on that shoulder. The plate stands `gap_mm` above the part's highest
  point, not on it. The check measures the part's area under the rim (at least
  25 mm², a default) and refuses a nest at a depth with no shoulder, such as a
  straight pipe. A part with a flat top still uses `top`.
- **A bore is measured from the part's highest plane.** On a dome the surface
  falls away from it, so a bore's depth and the drill-exit check count from the
  plane through the highest point, and `bit_needed_beyond_chuck_mm` adds the gap.
  The surface under an off-centre bore is lower than that plane; the guide does
  not model it.
- **Import copies a pattern between two parts, or re-drills one.** `guide import
  --holes-from MASTER [--part TARGET]` reuses the board importer's hole finder
  (round, through the whole height, +Z up; now with a settable minimum width).
  Both parts are centred on their own bounding boxes, so `--offset X,Y` moves
  the pattern when they do not share a centre, and holes that fall off the target
  are listed.
- **The chuck and depth are left for the user.** Like the board importer's
  connector, they cannot be guessed, so the file carries `needs_review` until the
  drill is set. A target with no flat top is written with a ledge nest and a
  `needs_review` note to set the depth at a shoulder.
- **Not built: a part with no shoulder and no flat top.** A dome on a plain
  pipe has nothing for the guide to rest on at all. That wants a printed
  support or a clamp, which is outside this feature (see *Open questions*).

### What phase 4 changed

- **Trials sit beside the build record, as enclosure trials do.** The design said
  "in the Validation Lab". The enclosure trials, which this follows, are not in
  the Lab's candidate-and-fixture workflow either: `guide trial start` writes
  `trials/trial-NNN/` beside `guide.json`, and `guide trial complete` writes
  `guide-trial.json`. The checks listed depend on the guide: seating, release,
  the drill passing, bushings seated (only with bushing bores), and the holes
  reaching depth.
- **A trial measures positions in the part's frame, and a printed hole against
  the model.** For each bore the offset of the drilled hole from its nominal
  (dx, dy, radial); optionally a pin-gauge reading of the printed bore, or a
  bushing pocket, against the diameter modelled. A passing trial measures every
  bore and cannot have a failed check.
- **Verified means two passing trials of the same build record.** `guide
  status` says so (exit 1 if not) and a rebuilt guide starts again at none, since
  its record's hash is new. The build record itself stays `verified: false`:
  verification is derived from trials, never written back into a record.
- **The pooled error is a profile, as the thermal coefficient is.** `guide
  derive` pools the passing trials of one printer and material into
  `profiles/guides/<printer>-<material>.json`, by bore kind (printed and bushing
  separately), with the sample count and the mean offset in X and Y as a bias.
  `guide build --accuracy-profile` reports those figures with their sample sizes
  beside the clearance bound it computes, records the profile's id, version and
  hash, and flags a measured error larger than the bound. A profile for another
  printer or material is refused. The bound is never replaced: the figures are
  evidence about those prints, and the build says so.
- **A printed hole's error is pooled too.** How far printed bores and bushing
  pockets came out against the model is what `hole_oversize` is meant to cancel,
  so a profile that shows a steady error says the printer profile's figure is
  off. Acting on it is left to a person.
- **Nothing is verified yet.** No guide has been printed, so no trial, no
  profile, and no verified guide exists in the repository; the tests use records
  made for them.

All four phases are built. A guide for a part that is neither flat-topped nor
shouldered, a printed clamp, and a bushing catalog remain as listed below.

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

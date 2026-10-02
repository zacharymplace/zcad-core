# Nests and jigs

## Purpose

The drill guide is a nest below and a plate above, and it already works as a holding nest when it has no bores: a pocket
cut to a part's shadow, for sanding, gluing or marking. That use is an accident of the guide. A nest that holds a part has
needs of its own (a floor, a way to lift the part out, a way to keep the nest still on a bench, a name on it), and the
guide's plate, which rests on the part's top face, is the wrong shape for them.

This is the design for one **nest core** and two products on it:

- a **holding nest**: a tray with a floor and a wall round a part's shadow, with finger notches, a retaining lip, strap slots and
  a label; and
- an **insert jig**: a nest with a plate that holds a part and a **heat-set insert** square over its pocket while an iron presses it
  in, with a depth stop, so the insert goes in straight and to a set depth.

The guide stays as it is. It becomes the third product on the core, with no change to what it builds.

## What the engine does not claim

The stance of the other designs carries over:

- **Nothing about the iron.** A soldering iron's temperature, the time to hold it, and the force to press with are the user's. The jig
  fixes where the insert is and how far it can go. It states no setting for installing one.
- **Nothing about a part's strength.** The engine says nothing about whether an insert holds, or whether a part survives heat. A trial
  records a depth and a squareness; it draws no limit from them.
- **No figure it was not given.** The iron's tip and shoulder, and a strap's width and thickness, come from the user with a
  `source`, and a figure sourced as an example is refused, as a drill's and a pogo pin's are.
- **No claim that a nest holds.** A retaining lip keeps a part in the nest against being knocked, not against a force. A trial
  can count how often the part stayed in.

## What the engine already has

| Need | Where it is today |
| --- | --- |
| A part from a STEP model, its shadow outline, its top, and a pocket that follows it with a clearance and a wall | `guide_file.nest_outline`, `guide_import`, `outline_prism`; see [Drill guides](drill-guides.md) |
| A guide's body: pocket, plate, and the release, fit and bed checks | `features/guide.py` (`build_guide`, `_lifts_out`, `_clear`, `require_fits_bed`) |
| The part's through-holes and their diameters, read from the model | `board_import.through_holes`, used by `guide import --holes-from` |
| Heat-set insert sizes by fastener (M2 3.2 x 3.0 mm, M2.5 3.9 x 4.0, M3 4.6 x 5.0, M4 6.3 x 6.0) | `hardware/fasteners.py` |
| A strain-checked flexure tab, with a provisional limit | `mounts.flexure_for`, `FLEXURE_STRAIN_LIMIT`; the cradle's snap tabs in `housing_cradle.py` |
| Embossed text on a flat top | `features/labels.add_embossed_label` |
| A build record that names its inputs by hash, and trials with readings and a disposition | `guide.json`, `guide_trial`, and the other trials |
| Printer fit and minimums | the printer profile: sliding and press-fit clearances, `hole_oversize`, minimum wall and floor |

The guide's build is one function that cuts a pocket and a plate and then its bores. It has no floor, no flange, and no
notion of a product other than a guide.

## Decision: one nest core, three products

The shared part is what turns a part into a pocket: read the part, find its shadow, widen it by the clearance, cut a pocket of a given
depth with a wall round it, and check that the part fits and lifts straight out. It moves to `features/nest_core.py`, and `build_guide`
calls it. **A guide is built the same after the change:** the existing guide tests are the check, and they run unchanged and must pass.

| Product | Frame | Adds to the core |
| --- | --- | --- |
| `guide` | The part's top is `z = 0`; the pocket runs down from it and the plate stands on the part's top | A plate and its bores (as today) |
| `nest` | The same frame; the part's **bottom** sits on a floor and the pocket runs up its side | A floor, a flange, and the features below |
| `jig` | The guide's frame | A plate with a bore over each insert, and a depth stop |

A part is read once the same way for all three, so one STEP file and one hash serve a guide, a nest and a jig for the same part.

## Decision: a holding nest is a tray

The holding nest has a **floor** under the part and a **wall** round its shadow, a pocket open at the top. `nest.depth_mm` is how far up
the part's side the wall climbs from its bottom (by default half its height, at least 3 mm), so the part stands proud to be sanded, glued
or marked. The part lifts straight up out of it, because the pocket is the shadow.

Four features, each optional and each its own check:

- **Finger notches.** `finger_notches` (0 to 4, default 2): scallops in the wall, each at least 12 mm wide and down to the floor, placed on the
  longest straight stretches of the outline. Refused where the wall has no such stretch, naming the one it has.
- **A retaining lip.** `lip: {tabs: n, overhang_mm}`: tabs cut from the wall, each bending outward on two slits like the cradle's snap tabs, with
  a hook that overhangs the part's top edge by `overhang_mm` (0.6 mm by default). The part presses past the hooks and is kept against being
  knocked. A tab's strain is the end-loaded cantilever's, checked against the provisional limit, and a part with no flat top edge to hold is refused.
  It states no holding force.
- **A flange and strap slots.** The floor reaches `flange_mm` (8.0 by default) past the wall on two opposite sides, and each flange takes a slot
  for a hook-and-loop strap or a clamp: `strap: {width_mm, thickness_mm, source}`. The slot is the strap's width and thickness plus the printer's sliding
  clearance, at least a minimum wall from the pocket and the flange's edge. The strap is the user's figure.
- **A label.** `label` (the file's `name` by default): embossed text on a flange's top, with a size the printer can take (the profile's text size
  and emboss height), refused if it does not fit the flange.

## Decision: an insert jig is a guide whose bore is an insert

A jig is built like a guide, a pocket round the part's shadow and a plate on its top face, and each **bore** is the way an insert goes down to its
pocket in the part. Four things set it:

- **The insert** is a catalogued fastener's heat-set insert (`"insert": "M3"`): its diameter and length come from the catalog, with the printer's
  hole compensation, as the mount pads' pockets do.
- **Where the inserts go** is given two ways, as the user chose: **typed** (`x_mm`, `y_mm` in the part's frame, with the pocket's
  depth) or **from the part's own holes** (`from_part: true` reads the through-holes the guide import already finds, and `holes: ["H1", "H3"]`
  picks which). A typed pocket and a found hole are both checked against the insert: a pocket more than 0.3 mm from the insert's pocket size is a
  warning, and one too small for the insert to enter is refused.
- **The bore** is the insert's diameter plus the printer's sliding clearance each side and its `hole_oversize`, through the plate, so the insert
  drops in, stands on the pocket's mouth, and is held square by the bore as the iron presses it down.
- **The depth stop is the plate.** The user gives the iron's tip: `iron: {tip_diameter_mm, shoulder_diameter_mm, tip_length_mm, source}`,
  the tip that goes down the bore, the wider body above it, and how far the tip stands out below the shoulder. When the shoulder rests on the
  plate's top, the tip's end is at the insert's top. So the plate's thickness is `tip_length_mm - depth_below_face_mm`, where
  `depth_below_face_mm` (0, flush, by default) is how far below the part's face the insert's top ends. The build refuses an iron whose tip does
  not fit the bore, whose shoulder would drop into it, or whose length makes a plate thinner than the printer's floor, and a pocket too shallow for the
  insert's length at that depth.

The jig then runs the guide's checks: it fits the part and lifts straight off it, every bore is open, the bores keep a wall between them, and the iron's
tip reaches the insert's top.

## The files and the commands

`nest` and `jig` are command groups of their own, each with `template`, `check` and `build`, then `trial start` and `complete`; a nest file or
a jig file names the part by hash as a guide file does, so a part changed since is refused. A build writes a record (`nest.json`, `jig.json`) that names its
inputs by hash and says it is unverified until a trial has passed.

```bash
zcad-validation nest template --part bracket.step --output my-nest.json
zcad-validation nest check my-nest.json
zcad-validation nest build --nest-file my-nest.json --output-directory exports/my-nest

zcad-validation jig template --part bracket.step --output my-jig.json
zcad-validation jig check my-jig.json
zcad-validation jig build --jig-file my-jig.json --output-directory exports/my-jig
```

## Checks

| Check | What it refuses |
| --- | --- |
| The part is where it says | The part file's hash differs from the file's |
| Part fits, lifts out | The pocket meets the part, or the part would catch lifting straight up |
| Walls and floors | Any wall, floor or plate under the printer's minimum |
| Notches, lip, slots, label | A feature that does not fit its wall or flange, a tab over its strain limit, a label that will not print |
| Insert fits its pocket | A pocket too small for the insert, a pocket too shallow for it at the depth asked |
| Iron fits the bore | A tip wider than the bore less a clearance, or a shoulder narrower than the bore |
| Stop | A plate thinner than the floor, or an iron too short to reach the insert's top |
| Bed | A nest or a jig larger than the printer's bed |

## Phases

1. **The nest core and the holding nest (built).** `nest_core.py` extracted from `build_guide` with no change to a guide; the `nest` file, `check` and
   `build` for a tray with its floor, flange and finger notches; the record.
2. **The lip, the strap slots and the label (built).** The retaining tabs with their strain check, the strap slots from the user's strap figures, and the
   label.
3. **The insert jig.** The `jig` file with typed positions, the bore, the iron's figures and the plate-as-stop, `check` and `build`, and the record.
4. **Inserts from the part's holes.** `from_part` and `holes`, reading the through-holes, and the checks of a found hole against the insert.
5. **Trials.** `nest trial` and `jig trial`, in the other trials' style: for a nest, whether the part seats, lifts out, stays in, and the strap holds
   it still, with a count of uses and whether anything wore; for a jig, whether each insert went in square and to what measured depth below the face,
   with the measured offset from the pocket's centre. The engine states no limit for any reading.

Each phase is one PR. The core's extraction is in phase 1 and is checked by the guide's own tests, so no existing build changes.

## Not covered

- **Installing the insert.** No temperature, time or force; no press, no ultrasonic or thread-forming insert.
- **Blind-pocket depth from the model.** The part's pocket depth is typed; the through-hole finder cannot read a blind one.
- **A nest for a part with no flat bottom.** The part's bottom must rest on the floor; a rounded or tilted part needs a cradle of its own.
- **Production tooling.** A bench nest and jig for a few parts, as the guide is.
- **Metal and other materials.** The engine does not model what the part is made of.

## Open questions

- **Whether the lip is tabs or a rim.** A rigid rim cannot be pressed past, so tabs. The proposal is tabs on the longest straight stretches only,
  and a part whose outline has none gets no lip, refused with a message.
- **Where a nest's label goes when the flange is small.** The proposal is to refuse a label that does not fit and say how wide the flange needs to be.
- **Whether `nest` should also build the part's lower half of a guide.** A guide is a nest inverted with a plate; a user who wants both for one part builds both
  from one STEP file. The proposal is to leave it at that.
- **The iron's tip as a cylinder.** A real tip tapers. The proposal is the cylinder of the figures the user gives, with the build saying so, and a trial
  measuring what the real tip does.

### What phase 1 changed

See [A holding nest for your part](../guides/holding-nest.md).

- **The core is the pocket and the release check, no more.** `nest_core.py` holds `pocketed` (a body round the outline grown by the clearance and the wall, with the pocket
  cut between two heights), `clear`, `lifts_off` (the guide lifted off its part) and `lifts_out` (a part lifted out of a nest). `build_guide` calls them with the same arguments
  it had inline, and every guide test runs unchanged and passes. The part is read by the guide's own `load_part_file`, which was already general.
- **The flange goes all round, not on two sides.** The design said the floor reaches past the wall on two opposite sides, for the strap slots. A rounded offset of the whole outline is
  one operation and a flange on every side is no worse for a tray; the slots in phase 2 choose their sides.
- **A notch is a rectangular cut, not a scallop.** 12 mm wide through the wall and down to the floor, centred on the middle of a long stretch. It is simpler to place on any outline and to
  check; a rounded one would not change what it does.
- **Notches take the longest stretches first.** The design said "the longest straight stretches"; ties go to the earlier edge, and a stretch needs 3 mm of margin past a notch's ends.
- **The pocket's depth defaults.** Half the part's height, at least 3 mm, never more than the part's height, which the design gave and the file now computes when `nest.depth_mm` is left out.
- **The part must stand on its bottom.** The floor's top is the part's bottom, so a part with a rounded or tilted bottom is not held by it, as the design said under *Not covered*.

### What phase 2 changed

See [A holding nest for your part](../guides/holding-nest.md).

- **Features are in `nest_features.py`.** Strap slots, the label and the lip's tab strain live there; `nest.py` places them and `nest_file.py` parses them. `nest_file.py` imports the
  feature planners inside one function, because they read its `NestSpec`.
- **The lip takes the part's whole height.** The wall must reach the part's top for a hook to overhang it, so `nest.depth_mm` is refused alongside a lip, and `pocket_depth_mm` gives the part's height.
- **A hook is a wedge on a raised tab.** Each tab rises 1.3 mm above the wall (a 0.3 mm gap over the part, a 1.0 mm hook), is 10 mm wide with a 0.8 mm slit each side, and keeps 2 mm of wall root below the slits. These
  are the engine's own sizes. The tab's strain is the cantilever's from `mounts.flexure_for`, over the wall's reach to the hook, against the provisional 1.5% limit.
- **The part is lifted out of the nest without its hooks.** They give way as the part goes by, so `part_lifts_out` is run on the body with the tab extensions but not the wedges. `lip_over_part` checks that the
  part's top lies under each hook.
- **Tabs take stretches the notches have not.** `stretch_sites` finds the straight stretches; notches take the longest, tabs the next.
- **Strap slots sit on the flange at the ends of the longer side**, on the X ends when the part is longer in X; `strap_slots_in_flange` checks them against the real solid. The strap's width, thickness and `source` are the user's.
- **The label goes on the side the slots are not on**, and is refused when it is longer than the side or the flange is narrower than the text.
- **Not covered:** how hard a lip grips and what a strap will bear. The record still says unverified until a printed trial (phase 5).

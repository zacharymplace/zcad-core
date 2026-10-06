# Object holders

## Purpose

Everything the engine builds so far holds a board, a wearable, or a part on a bench. The commonest printed thing in a house is none of those: it is a
**holder for an object**, a cup on the wall for a remote, a bracket under a desk for a power brick, a clip by the door for a torch. Each one is the
same problem: a pocket the object drops into and lifts out of, a way to fix it to something, and a fit that is neither loose nor stuck.

The engine already has every piece of that. A **caliper capture** measures a device to 0.01 mm, three readings a dimension, with its rounded corners,
the ports on its edges and the buttons on its face. The **calibration coupon** measures how this printer prints a fit and how far its plastic bends.
The **holding nest** cuts a pocket to a part's shadow and checks it lifts straight out. The **mounts** have keyhole slots and countersunk screws.
This is the design for putting them together into one new product: an **object holder**.

**Status (2026-10-06): phase 1 is built; phases 2 to 4 are design only.** `zcad-validation holder` builds a cup from a capture on screws or keyholes;
see [Phase 1, as built](#phase-1-as-built) and [A holder for an object](../guides/object-holder.md).

## What the engine does not claim

The stance of the other designs carries over, and a holder adds its own:

- **Nothing about load.** The engine says nothing about how much a holder bears, whether its screws hold in a wall, what a wall plug takes, or whether an
  adhesive pad stays stuck. The object's mass is recorded, from the capture, so a trial can say what the holder carried. Strength is a trial's.
- **Nothing about the wall.** The screw is the user's, with its head and shank sizes and where they came from. The engine sizes the hole and the
  countersink to it, and states no anchor, no pilot hole and no torque.
- **No size it was not given.** The object's size is a capture's medians or a STEP model's, never a name: a "TV remote" has no size.
- **An unverified holder.** A holder is unverified until a printed trial with the real object says it fits, comes out, and stays put.

## Decision: the object from a capture first, a model later

Most objects a holder is for have no STEP model, and everyone has calipers. So the first source is the **caliper capture** the wearable housings use, a
`"device": "custom"` capture, unchanged: its `length_mm`, `width_mm` and `thickness_mm` medians, its `outline` (a rectangle or a rounded rectangle),
its `edge_features` (what a wall must not cover: a charging port, a button, a cable), its `face_features`, and its `mass`. A capture is already
checked by `wearable check`, and a holder refuses one that check refuses. The name stays `wearable` for now; a capture is a capture, and renaming the
command is its own change.

A **STEP model** comes second (phase 3). Its pocket is the nest's: the model's shadow, seen along the way it goes in, so any shape releases.

Why not extend the nest: a nest is a tray on a bench with a floor under the part and a flange to clamp. A holder hangs, is loaded sideways by the
object's weight, goes in along one axis that is not always down, and carries a mount. The checks differ (which way it comes out, what holds it in,
where the screws go), so it is its own file and command, sharing the nest's shadow code, its lift-out sweep and its retaining tabs.

## Decision: a cup, inserted from above

The holder is a **cup**: a back plate against the wall, and a pocket in front of it with a floor, two sides and a front, open at the top. The object
goes in from above and sits on the floor, held by its weight; a cup needs no clip to hold a remote.

- **Which way up.** The holder file names the object's edge that sits on the floor (`down_edge`, one of the capture's `north`, `south`, `east` and
  `west`) and which face looks out (`face`: `out`, the capture's top face toward the room, or `wall`). That fixes the pocket's width, depth and height
  from the capture, so the same capture makes a remote stand on its end or lie on its side.
- **The fit.** The pocket is the object's outline grown by a sliding clearance on every side: the printer profile's `sliding_clearance_per_side`
  (0.2 mm on the A1 mini, provisional), or, given `--compensation-profile`, the clearance the coupon's measured side gap says this printer needs. A
  rounded object gets a rounded pocket, the same clearance all the way round.
- **How high the walls climb.** The front climbs a share of the object's height (`front_mm`, default a third, at least 10 mm), so the object's face
  and anything on it stay in reach; the sides climb the same; the back plate stands the whole height. A front higher than the object is refused: it
  could not be reached into.
- **A way in for a finger.** A **finger notch** is cut down the front's middle, 20 mm wide, unless the front is low enough not to need one or a face
  feature asks for the whole front.
- **Edge features stay open.** An edge feature on the down edge (a charging port, so the object charges in its holder) gets a slot through the floor
  the feature's width plus 2 mm, and one on a side edge below the wall's top gets a notch in that side. A feature the back plate would cover, with
  `face: wall`, is refused, naming it: the holder would wall over what the capture said must stay open.
- **Drainage, no.** The floor is solid unless a slot is cut for a feature. A cup that holds a wet brush is not this design.

## Decision: the mounts

The back plate carries the mount, and each mount is a figure the user gives or one the engine already has:

| Mount | What it is | Where the figures come from |
| --- | --- | --- |
| `screws` | Two countersunk holes through the back plate, above the pocket's floor and clear of it | The user's screw: `head_diameter_mm`, `shank_diameter_mm`, `head_angle_deg` (90 for most wood screws), and `source`. The hole is the shank plus the profile's `hole_oversize`; the countersink takes the head to flush |
| `keyhole` | Two keyhole slots, hung on screws already in the wall | The mounts' keyhole: a 9.0 mm head, 4.5 mm slot, 10 mm travel, the screw head 3.0 mm proud |
| `pegboard` | Two hooks off the back plate's top that hang in a pegboard's holes, and a foot at the bottom that rests on the board | The board is the user's: `pitch_mm` (25.4 on a common 1 inch board), `hole_diameter_mm` and `board_thickness_mm`, each with a `source`. The engine assumes no pegboard standard |
| `flat` | A plain back plate, for an adhesive pad or tape | The pad's size, with its `source`; the plate is at least as large. The engine says nothing about the adhesive |

Screws and keyholes sit in the back plate above the pocket's floor, so the object hides them, and at least two screw-head diameters apart. A plate
too narrow for two is refused, with the width two would need; a single screw lets a holder swing.

## Decision: printed upright

The holder prints as it hangs: the back plate standing on its bottom edge, the floor on the bed. Then the pocket's walls are vertical and the floor is
flat on the bed, so nothing overhangs, and the back plate's face against the wall is a side face, smooth and straight. The holes through the back
plate are then **horizontal**, so each is drawn as a **teardrop**, pointed up, as the wall vents are, and a countersink's cone is cut below a 45-degree
roof. A pegboard hook leaves the back plate's top horizontally, so it is drawn with a 45-degree underside. A holder taller than the printer's bed is
refused.

## Retention, when weight is not enough

An object that stands on its end in a shallow cup can be knocked out. `retention: tabs` adds the nest's retaining tabs to the side walls: a tab cut free
of the wall by two slits, with a hook that reaches `overhang_mm` over the object's top as it sits. A tab is a cantilever, and its bending strain as the
object pushes past is held to the flexure strain limit: the engine's provisional 1.5 per cent, or the coupon's measured limit under
`--compensation-profile`. A tab that would strain further is refused, with the reach it needs. With tabs, the sides climb the object's whole height.

## Checks

| Check | What it refuses |
| --- | --- |
| The capture | Anything `wearable check` refuses |
| Fit | Holder material inside the object, or within the clearance of its sides |
| Lift-out | The object, lifted straight up from its seat in 2 mm steps (tabs left out, as they give), meeting the holder before it is clear |
| Features open | A floor slot or side notch that does not leave its feature's whole width open; a feature the back plate covers |
| Mount | Holes closer to the pocket's floor, the plate's edge, or each other than the screw head needs; a pegboard hook off the pitch |
| One solid | A holder in pieces |
| Printable | A holder that does not fit the bed upright; a horizontal hole that is not a teardrop |
| Tabs | A tab straining past the limit; a hook with no object top under it |

Every check is made on the built solid, as the other products' are, and the holder passes through the export pipeline: STEP, STL, metadata, and
validation against the printer profile.

## Trials

A holder trial records, for the real object and the printed holder: whether it went in and came out by hand, whether it sat square, the gap the user
can feel or measure at each side, whether it stayed in when the holder was knocked, the mount used and what it was fixed to, and, after a time, whether
anything crept or cracked. The engine states no pass mark for force or time. Two trials that pass promote the holder file, as boards and housings are
promoted. A trial uses the capture's `mass`, so it says what the holder carried.

## The command and the files

```
zcad-validation holder template --capture remote.json --output remote-holder.json
zcad-validation holder check remote-holder.json
zcad-validation holder build --holder-file remote-holder.json --output-directory exports/remote-holder
```

The holder file names its capture (or model) and its SHA-256, so a holder whose object has changed is refused, as a fixture whose board has changed is.
It holds `down_edge`, `face`, `front_mm`, the `mount` with its figures and sources, `retention`, and an optional `label` embossed on the back plate's
front, above the pocket. `holder build` writes `holder.json`, a record of what was built from what, which says the holder is unverified.

## Phases

1. **A cup from a capture, on screws or keyholes.** The holder file, `holder template`, `check` and `build`; the pocket from a custom capture with its
   outline; `down_edge` and `face`; the front, the finger notch, the floor slots and side notches for edge features; the `screws` and `keyhole` mounts with
   teardrop holes; the fit, lift-out, features, mount, one-solid and print checks; the record; `--compensation-profile` for the clearance.
2. **Tabs and the other mounts.** `retention: tabs` with the strain check; the `pegboard` and `flat` mounts.
3. **A model for an object.** A STEP model in place of a capture, with the pocket cut to its shadow as the nest's is, and the lift-out sweep along the way in.
4. **Trials.** `holder trial start` and `complete`, and promotion on two passing trials.

Each phase is one PR, and nothing that exists changes.

### Phase 1, as built

`zcad-validation holder template`, `check` and `build`, in `features/holder_file.py` and `features/holder.py`. It differs from the design above in these ways:

- **The countersink is always 90 degrees.** The design took the screw's head angle. A 90-degree cone printed on its side has a 45-degree top and needs no
  support; any other angle does, or is not a countersink at all. So the file takes the head's diameter and the shank's, with their source, and the
  countersink is cut to the head's diameter plus the hole oversize at the plate's face. An 82-degree head seats on its rim, a little proud of flush.
- **Fixings stand side by side or one above the other.** The design refused a plate too narrow for two side by side. A pen or a torch is narrower than
  two screw heads, so the fixings stand one above the other on the centre line when the pocket is too narrow, at least two head diameters apart, and the
  holder is refused only when neither fits. They are always behind the object, 2 mm clear of the plate's edges, the floor and the plate's top.
- **Openings run to the top.** A notch for a side feature or a face feature runs from the feature to the wall's top instead of being a window, so it has
  no roof to overhang. A floor slot runs front to back across the pocket.
- **The fit.** `fit.clearance_mm` with a `source`, the open question's proposal, is built. Without it the clearance is the profile's sliding clearance, and
  `--compensation-profile` adds the coupon's measured side-gap shortfall, never bringing it under 0.05 mm.
- **No label.** The embossed label is left for a later phase.

## Not covered

- **Hooks, rails and racks for many objects.** A holder holds one object. A row of holders is a later design, as the modular bays grew from one board.
- **A desk stand that tilts, and an under-shelf slide.** A cup on a wall first; the other orientations follow if the cup proves out.
- **Strength.** Not modelled, as above.
- **Magnets.** The catalog has magnets, but a magnet mount needs a pull test no one has run, as the mounting systems already say.

## Open questions

- **Whether a third of the height is the right front.** It keeps a remote's buttons in reach and holds it against a knock from the side. The proposal is to
  build a third and let a trial say.
- **Whether the clearance should be looser than the sliding clearance.** An object dropped into a cup needs less precision than a lid sliding on a base. The
  proposal is the sliding clearance, which the coupon measures, and a `clearance_mm` in the holder file for anyone who wants it looser, with a source.
- **Whether the capture command should be renamed.** `wearable` reads oddly for a remote. The proposal is to leave it until a second product uses captures,
  which this is, then add `capture` as the name and keep `wearable` as an alias.

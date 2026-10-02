# Wearable housings

## Purpose

The engine has one wearable product: a snap shell for two sealed medical devices,
the Dexcom G7 and the Tandem Mobi. It is a set of clips at the device's edges, each
hooking 0.6 mm over the top edge, touching neither face. It is built from published
sizes, or from a caliper capture that raises it to a `verified_candidate`, and it
goes through the Validation Lab's retention pipeline. It does not house anything, and
nothing about it attaches to a body.

A wearable housing is the rest of that: something you can wear. It has two kinds of
input: a **sealed device** you cannot open (a sensor, a pump, a tracker), and a
**board** you can (any board a board file describes). It has one set of ways to be
worn: a strap, a band, a belt clip, an adhesive plate, a lanyard. This is the design
for both inputs and the wearing they share.

This is a design, not built work. Nothing below exists in the code yet.

## What the engine does not claim

A wearable touches skin, and two of the devices it starts from are medical. So,
before the design, what it will never say:

- **Nothing about biocompatibility.** PETG, and whatever else a profile names, is
  not validated for skin contact by this engine, and the build says it states no
  claim.
- **Nothing about water, sweat or ingress.** A housing is not sealed.
- **Nothing about comfort, a retention force, or a cycle life.** A trial measures a
  force and counts wears; the engine has no sourced figure to compare either with.
- **Nothing about a device's function.** A housing that covers a sensor's wire or a
  pump's port is the user's to check; the engine only refuses a housing that covers
  a feature the file lists.
- **No figure it was not given.** A strap's width, a spring bar's diameter, a band's
  thickness, a patch's outline, a device's mass: each comes from the user, with a
  source the file requires, as a pogo pin's and a screw's did.

## What the engine already has

| Need | Where it is today |
| --- | --- |
| A sealed device's size and edge features from a caliper, three readings each | `hardware/wearables/capture.py`, the capture file and `wearable check`; see [Measuring a wearable](../guides/wearable-capture.md) |
| A snap shell for it, registered as a Validation Lab candidate with provenance | `retention/snap_shell_candidate.py`, the two build scripts, `snap_shell_backend` |
| A flexure whose strain is checked against a provisional limit | `mounts.flexure_for`, `FLEXURE_STRAIN_LIMIT` (1.5 per cent), used by the DIN clip, the lid catch, the slide detent |
| A board from a file: outline, holes, parts, edge connectors, power | the board file and its checks; see [A board file](../guides/board-file.md) |
| A case around a board, with openings, standoffs or a cradle, a lid, vents | the single-board enclosure builder (`features/enclosure.py`) and the board cradle |
| A build record and trials with measurements, readings and a disposition | `enclosure_trial`, `guide_trial`, `pcb_fixture_trial`, `enclosure_group_trial` |

The enclosure builder has no rounding of its outer edges and nothing to attach it to a
body. Both are new.

## Decision: a wearable file for any sealed device

The capture file becomes a **wearable file** for any sealed device, not only the two
named ones. It keeps the capture's frame (the device lies face up, away from the body,
its length along X and its width along Y, centred) and its three readings per
dimension, whose median is used. It gains:

- **an outline**, a rectangle or a rounded rectangle with a radius, since a sensor or a
  pump is neither square-cornered nor a puck;
- **face features**, the buttons, windows, screens and ports on the face away from the
  body that a housing must leave open, as it has edge features today;
- **a mass**, optional, with its source, which only a trial's readings use; and
- **a device that is a catalog key or a name of the user's**: a catalog device keeps its
  published size and the check that a measurement is within 25 per cent of it; a named
  one has no published size, so that check is skipped and the file's `source` is what
  stands behind it.

The Dexcom G7 and Tandem Mobi stay in the catalog, with their candidates, their
scripts, and `capture.json` files working as they do now: the schema adds optional
fields and keeps its version, as `test_points` did for the board file.

A **board** as a wearable needs no new file: the board file already has what a case
needs. A wearable's own settings (how it is worn, its skin-side rounding) are in the
housing's own file, below, so one board file serves a wrist case and a desk case.

## Decision: a housing file, and three styles

A **housing file** names a wearable file or a board file by hash, a style, and a way of
wearing. `housing template`, `housing check` and `housing build` follow `fixture`'s
commands, and the record, as the fixture's does, names its inputs by hash.

| Style | For | Builds |
| --- | --- | --- |
| `shell` | A sealed device | What exists: clips at the edges. Not changed; reached through the housing file so a shell can be worn too. |
| `cradle` | A sealed device | A tray: a floor the device lies on, a wall round its outline, retention clips or a rim, left open on the face away from the body and closed on the skin side. |
| `case` | A board | The single-board enclosure's base and lid with a wearable's walls: thinner, and with the outer corners and the skin-side edges rounded. |

The cradle leaves each feature a file lists uncovered, as the shell's clips do, and
cuts a window over each face feature. A housing that cannot is refused, naming the
feature and the edge. A case takes the board's openings and standoffs or cradle from
the single-board builder unchanged, so a wearable case is that case with rounded
walls and a mount.

## Decision: how it is worn

One **wear** setting, a list, chooses what attaches to the housing. Each is a feature on
the housing's outside, on the edges or the skin side, and each is checked against the
housing's own size. The wear figures come from the user.

| Wear | Builds | The user supplies |
| --- | --- | --- |
| `strap` | Two lugs at opposite ends, each with a bar hole, for a watch-style strap | the strap's width, the bar's diameter, the source |
| `band` | Two slots through the housing's long sides for a woven or elastic band | the band's width and thickness, the source |
| `clip` | A flexure clip on the back for a belt or a pocket, its strain checked as the snap clips are | the belt's thickness, the source |
| `adhesive` | A flat plate on the skin side, larger than the housing, with a lip that holds it | the patch's outline, the source |
| `lanyard` | A hole through a tab | the cord's diameter, the source |

The templates carry marked **example** values (an example strap width and bar), the way
`fixture template`'s pin is `EXAMPLE ONLY`; a file with an example source is refused,
so no example becomes a figure by being left in. The catalog has none: the common
strap widths are conventions, and no source for them has been read.

Several can be worn at once (a lanyard hole on a strapped housing). Two that would
take the same place are refused.

## Decision: the skin side

The skin side is the face the body touches. It gets two things and no more:

- **A rounded edge.** Every edge round the skin-facing perimeter has at least a radius
  the housing sets (1.0 mm by default, marked a comfort setting and not a medical
  figure), and the build refuses a housing whose own geometry cannot hold it, such as a
  wall thinner than the radius.
- **No feature that stands off it** except the wear's: a strap's lugs and a clip's
  back are on the edges and the back, and the build says which face they stand on.

A curved skin side, a texture, a vent for the skin to breathe through, or an
antimicrobial anything is not built.

## Checks

- **Fit.** The device or board, with the printer's clearance, drops into the housing and
  lifts out of it, and nothing it carries meets the housing.
- **Features.** No clip, lug, slot or plate covers a feature the file lists; each face
  feature has its window.
- **Wear.** Each wear's figure fits the housing: a bar between the lugs, a band through
  its slots, a patch inside the plate.
- **Strain.** A clip's flexure within the provisional limit, as the snap clips are.
- **Skin side.** The rounded edge's radius, and the build's statement of what stands off
  the skin.
- **Bed.** The housing fits the bed.

## Phases

1. **The wearable file (built).** The capture file generalised: an outline, face features, an
   optional mass, a device of the user's own. `wearable check` for it; the Dexcom and
   Mobi checks and candidates unchanged.
2. **Housings (built).** The housing file with `template`, `check` and `build`; the
   `cradle` for a sealed device and the `case` for a board. No wear yet: a housing you
   hold. (`shell` through the housing file moved to phase 3.)
3. **Ways of wearing.** The strap lugs, the band slots, the belt clip, the adhesive
   plate and the lanyard hole, each from the user's figures with their source, and the
   checks on them. These are the five a wearer needs, built together.
4. **The skin side.** The rounded edges and their radius check, and the statement of
   what stands off the skin.
5. **The record and wear trials.** A housing's build record, and trials in the
   enclosure trials' style with wear readings: a retention force from a spring scale, a
   pull test of a lug or a loop, a count of wears and whether anything wore or cracked,
   and whether skin was irritated. The engine states no limit for any of them.

### What phase 1 changed

- **A custom device is `"device": "custom"` with a `name`, not any name.** The design
  said the device could be "a catalog key or a name of the user's". A free name would
  turn a typo of a catalog key (`dexcom-g8`) into a device with no published size to be
  checked against, silently. So `custom` is the one word that means "mine", it needs a
  `name`, and anything else unknown is still refused, with `custom` offered in the
  message. A catalog device takes no `name`.
- **A custom device skips only the published-size check.** It has no published size, so
  the 25 per cent test and the 2 mm question are not asked. The three readings, their
  spread warning, the `source`, the edge-feature check and every other rule apply.
- **Face features are boxes, checked against the outline's corners too.** Each corner of
  a feature's box must lie inside the body, so a feature in a rounded corner that a
  rectangle would accept is refused. They are optional, so a capture made before them is
  valid; only a custom device is questioned for leaving them out.
- **Only a rectangle and a rounded rectangle.** A polygon outline is not built, as the
  design said; the radius is bounded by half the body's width.
- **The mass is checked for sense and used by nothing yet.** Between zero and 5000 g with
  a source. Only trials' readings will use it.
- **The catalog devices did not move into files.** They stay in code with their
  published sizes, which the design allowed ("stay in the catalog"); the capture file for
  either is what a measurement replaces, as before. Their candidates, scripts and the
  retention pipeline are untouched.
- **The schema version stays 1.0.0,** since every addition is optional.

### What phase 2 changed

See the guide [A housing for something you wear](../guides/wearable-housing.md).

- **The cradle's retention is a tab that bends along the wall.** The design said "retention
  clips or a rim" and left it open. A vertical clip needs the wall's height for its
  length, and a thin device (the G7 is 4.7 mm) has none: a 1.2 mm tongue 5.7 mm long
  strains over 3 per cent against the 1.5 per cent limit. The tab is instead the top
  strip of the wall, cut free by a slit along its underside and one at its free end, a
  beam fixed at one end that bends outward in the plane of the wall. It can be 12 mm long
  whatever the device's thickness, and strains 0.75 per cent. The existing snap-shell
  clips are not reused: they are clip-only geometry for the Validation Lab's retention
  pipeline, with no wall or floor to hang a tab from.
- **The cradle's face is open, so a face feature needs no window.** The design said the
  cradle "cuts a window over each face feature". A cradle that leaves the face open has
  nothing over a feature to cut, so the build instead refuses a tab whose hook would cover
  one. A window belongs to a lid or cover over the face, which is not built.
- **Edge features get notches, and the tabs keep clear of them.** The wall is cut open at
  each feature a capture lists, a millimetre wider each side, and a tab is slid to the
  nearest place clear of every notch and of the corners, by the rule the shell candidate
  uses.
- **The case is the enclosure builder with a snap lid, and its rounding is limited by the
  wall.** The design said "thinner walls, and the outer corners and the skin-side edges
  rounded". The outer vertical corners are rounded by cutting each part to a rounded box.
  The cavity's corners stay square, so rounding takes wall off the corner's diagonal, and
  the build refuses a radius that leaves under the printer's minimum there, naming the most
  (1.2 mm on a 1.2 mm wall). Rounding the skin-side edges is phase 4, and a rounded cavity
  needs the enclosure builder to learn it.
- **`shell` through the housing file moved to phase 3.** A shell has nothing to attach until
  there is a way of wearing it, so reaching it through the housing file does nothing yet.
- **The build names its inputs by hash and writes no record.** The housing's own build record
  and trials are phase 5, as the design lists; the output says which style, which input hash,
  and each part's STL hash.
- **The build says what it does not claim.** Every build prints that the engine states no
  claim about skin, water, comfort or the device's function.

Each phase is one PR. The wearable file adds optional fields, so no existing capture
file changes, and the shell scripts keep their output.

## Not covered

- **Anything sealed, waterproof, or sterile.** A housing is open to air and water.
- **Any claim about skin, comfort, or medicine.** See above.
- **A housing for a device that has to be touched through it.** A glucose sensor's
  patch, a pump's infusion site, a screen that is read through a cover: the file lists a
  face feature and the housing leaves a window; the user checks that it works.
- **Straps, bands, and clips themselves.** The engine builds what they attach to.
- **A curved skin side, a textured one, or one with vents.**
- **A custom device without a caliper.** A wearable file needs the three readings; a
  model of the device, if there is one, is the board file's STEP route, not this.

## Open questions

- **Whether a trial's skin-irritation reading belongs in the engine at all.** It is a
  person's observation and records nothing about the housing; the proposal is a
  yes-or-no and notes, with a line saying the engine draws no conclusion from it.
- **Where a face feature's window sits for a device read through its face.** A window
  over a screen leaves the device's own face exposed to knocks; the proposal is the
  window only, with a rim round it, and a note.
- **The retention figure for a clip.** There is no figure to check a clip against, and
  a trial measures its force. The proposal is to record the measured force with the
  device's mass and say no more; whether a pooled set of them could support a limit is
  a later question.

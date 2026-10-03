# A holding nest for your part

A holding nest is a tray that holds a part while you sand it, glue it, or mark it. You give it a part as a STEP model. It builds a
**floor** under the part, and a **wall** round the part's shadow, with **finger notches** cut through the wall so the part lifts out by hand.

```bash
zcad-validation nest template --part bracket.step --output my-nest.json
# say what the part is, then:
zcad-validation nest check my-nest.json
zcad-validation nest build --nest-file my-nest.json --output-directory exports/my-nest
```

`nest template --part` writes a nest file that names your STEP model and its SHA-256. `nest check` reads the part and exits 1 if the nest
cannot be built, listing every problem at once. `nest build` exports the nest as STEP and STL, checks it against the printer profile, and writes
`nest.json`, a record of what was built from what, which says the nest is **unverified**.

A drill guide with no bores also holds a part, from above; this is a tray with a floor, for working on the part while it stands in it.

## The nest file

| Field | What it is |
| --- | --- |
| `part.step`, `part.sha256` | The STEP file and its hash. A part that has changed since is refused. |
| `part.solid_index` | Which solid is the part (from 1), if the model holds several. |
| `nest.depth_mm` | How far up the part's side the wall climbs. Left out, half the part's height, at least 3 mm. It cannot be more than the part's height. |
| `nest.wall_mm` | The wall round the pocket (2.0). It cannot be under the printer's minimum wall. |
| `nest.floor_mm` | The floor under the part (2.0). It cannot be under the printer's minimum floor. |
| `nest.flange_mm` | How far the floor reaches past the wall (8.0), all round. Zero leaves no flange. |
| `features.finger_notches` | 0 to 4 notches (2). |
| `features.lip` | `{"tabs": 1 to 4 (2), "overhang_mm": 0.3 to 2.0 (0.6)}`. A retaining lip; leave it out for none. |
| `features.strap` | `{"width_mm", "thickness_mm", "source"}`. Two strap slots. The size is your figure and `source` says where it came from. |
| `features.label` | Up to 24 printable characters, embossed on the flange. |

The part's frame is its own: centred on its bounding box in X and Y, with +X right and +Y up the page seen from above, and its **top face at z = 0**. The
model must have **+Z up**. Everything is in millimetres.

## How the nest fits

The pocket follows the part's **shadow**, its outline seen from above (undercuts and overhangs included), widened by the printer's sliding clearance
(0.2 mm on the A1 mini profile, which is provisional). A pocket cut to the shadow lets the part lift straight out whatever its shape beneath: a part
with a wide head on a narrow stem still releases. The price is a looser fit where the part narrows below its widest point. The shadow is found by drawing
the part's triangles onto a grid, so it is never smaller than the part and can be a pixel or so larger. A part whose shadow is several separate pieces is refused.

## Finger notches

A notch is 12 mm wide, cut through the wall from the floor's top up, at the middle of a straight stretch of the shadow's outline. It needs a stretch at least
18 mm long (12 mm and 3 mm of margin past each end), and the nest takes the longest stretches first. A part whose outline has fewer long stretches than the notches
asked for is refused, with the number it has: a round part, whose outline is many short segments, takes none. The width and the margin are the engine's own
choices.

## Strap slots

`features.strap` cuts two slots through the floor's flange, one at each end of the nest's longer side, each the strap's width and thickness with the printer's
sliding clearance round it. A hook-and-loop strap or a cord through them holds the nest to a table or a clamp. The flange must be as wide as the slot with a
minimum wall each side of it (the check says how wide), and every slot is verified on the built solid to lie wholly in the flange. The strap's size is your
figure: the engine takes it, requires a `source`, and says nothing about whether a strap of that kind holds.

## Label

`features.label` stands embossed text (the printer profile's text size and emboss height) on the flange's top, on the side the slots are not on. Text too long
for the nest's side, or a flange too narrow for it, is refused.

## Retaining lip

`features.lip` raises tabs from the wall. Each is 10 mm wide, cut free of the wall by a slit each side, and carries a hook that overhangs the part's top face
by `overhang_mm`. The part presses past the hooks as it is pushed down and is kept against being knocked sideways or tipped. The wall climbs the part's
**whole height**, so `nest.depth_mm` cannot be set with a lip. A tab takes the longest stretches the finger notches have not taken.

A tab is an end-loaded cantilever and its bending strain is checked against the provisional limit (1.5%); one that would strain further is refused with the
reach it needs. A part with no flat top (under 10% of its shadow flat at the top) is refused, since there is nothing for a hook to lie over. The part is checked to lift out
of the nest **without the hooks**, because they give way as it is lifted; what the hooks do is checked only as far as each one has the part's top face under it.

## What is checked

The nest is **one solid**. The part is put in its pocket and shares no volume with it, and is lifted straight up through the wall's height in 2 mm steps and
meets nothing on the way. Every notch is open at its middle, at the wall's top and just above the floor. The nest must fit the printer's bed.

Strap slots must lie in the flange, and each lip hook must have the part's top under it.

**The engine says nothing about how well the nest holds a part, how hard a lip grips, or what a strap will bear.** It says the part fits the pocket and lifts straight out. A nest is unverified until a printed
trial has passed.

## Trying a print

`nest build` writes `nest.json`, which lists the checks a trial asks (the lip, strap and label checks only when the nest has them) and the sizes to measure with calipers. After printing and using the nest on your part:

```bash
zcad-validation nest trial start --build-record exports/my-nest/nest.json
# fill in trials/trial-001/observations.json, measurements.json and use.json, then:
zcad-validation nest trial complete --trial-directory exports/my-nest/trials/trial-001 --disposition pass
```

`observations.json` takes pass or fail for each check: it printed cleanly, the part seats, the part lifts out, the part stays in (a lip), a strap holds the nest still (strap slots), the label
reads (a label). `measurements.json` takes the sizes you measured. `use.json` takes the **count of uses** and whether anything wore. The record, `nest-trial.json`, sets each measurement beside
what was designed. **The engine states no limit for any reading.** A passing trial cannot have a failed check, a pass or revise trial needs a measurement or a use reading, and a trial is checked
against the printed parts' hashes in the build record, so a print that has changed since is refused. A completed trial is never overwritten.

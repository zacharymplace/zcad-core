# Hinged and sliding lids

## Purpose

Today a lid is screwed on or snapped on, and either way it comes off as a
separate loose part. A hinge keeps the lid attached to the base and swings it
open, for a box that is opened often, such as a battery box, a field device,
or anything with a card or a switch inside. A slide lid opens by pushing it
along the box, with nothing to lose and no fasteners.

This is a design, not built work. Nothing below exists in the code yet.

## Where it fits

`EnclosureDesign.lid_attachment` already picks between `"screws"` and
`"snap"`. The lid options work from the cavity's plain dimensions
(`enclosure_lid.py`), and the builder decides what applies. Two new values,
`"hinge"` and `"slide"`, join them, each a module of the same kind beside
`enclosure_lid.py`. Both leave the lid's plate, the display window, the
display retainer, and the vents as they are. Neither needs the corner bosses,
so, like a snap lid, the cavity can be smaller.

## Decision: a hinge with a pin, not a printed one

There are three ways to make a hinge in a printer, and only one suits the
material the profiles name, PETG:

| Hinge | Verdict |
| --- | --- |
| Living hinge (a thin strip that bends) | Rejected. PETG cracks after a few bends; this is a polypropylene technique. |
| Print-in-place pin hinge | Rejected for now. The pin fuses to its knuckles unless the clearance is right, and the clearance needs a print trial no one has run. |
| Pin hinge, pin bought separately | **Chosen.** Knuckles on the base and the lid, a pin hole through them, and a pin that is an M3 screw or a length of 1.75 mm filament. |

The pin hinge keeps the export pipeline's two-part model: base and lid are
separate parts, as now, and the pin is hardware. The build prints the pin's
length, as it does the screws'.

### Hinge geometry

- The axis runs along the back of one long wall, at the lid's underside. A
  row of knuckles, three or five, alternates between the base and the lid.
  Each knuckle is a barrel whose wall is the same 1.8 mm the insert bosses
  use, around an M3 clearance hole grown by `hole_compensation_mm`.
- The barrels stand out of the back wall, so the box grows by about 3.5 mm in
  that direction. The export's bed check already refuses a part that no
  longer fits; the rack-ear work found that out the hard way, so the hinge
  height is counted in the footprint before export.
- The lid opens to about 100 degrees, held by a stop where the lid's plate
  meets the top of the back wall.
- The skirt is left off the hinge side, so it does not catch the wall as the
  lid swings.
- The closure is a snap catch on the opposite long wall, a tongue cut from
  the lid like the DIN clip's latch. It uses the same strain check
  (`flexure_for`) against the same provisional limit.

## Decision: a slide lid in a rebate, with a detent

A slide lid runs in grooves in the two long walls and enters from one short
end, whose wall stops short to let it in.

- **Where the groove goes.** A 2 mm wall is too thin to cut a groove into.
  The wall is thickened at the top, outward, for a band as tall as the
  groove, so the cavity is untouched. The footprint grows by about 1.6 mm on
  each side, counted in the bed check.
- **Fit.** The lid's clearance is the printer profile's
  `sliding_clearance_per_side` (0.2 mm on the A1 mini). The validation
  report already reads that profile entry as `lid_clearance`, so the slide
  lid's declared clearance is checked against it.
- **Retention.** A detent bump on a tongue cut from the lid's plate clicks
  into a notch in the base at the closed position, and a finger notch at the
  end lets a thumb push it. The tongue is the DIN latch's flexure again.
- **End stop.** The lid stops against the far short wall, so it cannot slide
  out the wrong way.

## Checks

- **Swing envelope** (hinge): sweep the lid from closed to its open angle in
  5 degree steps and require no shared volume with the base or the hardware.
  This is the check that would have caught a lid catching on a tall board.
- **Slide travel** (slide): the groove is longer than the lid by the travel,
  and the lid clears the hardware along its whole path.
- **Pin fit:** the pin hole exceeds the pin by the printer's hole oversize,
  and the pin is long enough to pass every knuckle and short enough to fit.
- **Flexure strain:** the snap catch and the detent tongue stay within the
  limit, as the DIN clip's does.
- **Footprint:** the bed check on the grown base, before export.
- **Display:** a display hangs from the lid, so a hinged lid pulls on
  whatever connects it to the board. The build says so and does not open the
  lid past the flex the cable allows, which it cannot know; the docs tell the
  user to leave slack.

The parts pass through the same export pipeline as the enclosure.

## Phases

1. **Pin hinge and snap catch**, single-board enclosure: the hinge module,
   the `"hinge"` lid attachment, the swing envelope check, the pin in the
   hardware output, `--lid hinge`.
2. **Slide lid**, single-board enclosure: the thickened band, the grooves,
   the detent, `--lid slide`.
3. **Pi 5 group enclosure**: a hinge along its back wall and a slide along
   its row, each with the group's dividers and cable openings in the way.
4. **Review and trials**: the hinge's swing and the slide's travel in the
   exploded review model, and trial measurements for pin fit and slide force
   in the Validation Lab.

Each phase is one PR. Phases 1 and 2 add lid attachments, so existing builds
and records are unchanged unless a design asks for them.

## Not covered

- Living hinges, and print-in-place hinges, until a trial gives a clearance.
- Gas struts, friction hinges, and lift-off hinges.
- A lock. A lid that must not open by itself is a screwed lid.
- Strength and cycle life. A printed PETG hinge wears; a trial has to count
  openings before the docs claim any.

## Open questions

- **Where the slide's rebate goes**, outward (the footprint grows 1.6 mm a
  side; the cavity is untouched) or inward (the footprint is unchanged; the
  cavity loses 2 mm a side, which the automatic clearance then buys back at
  the same cost). Outward is proposed.
- **Whether the group enclosure is part of this first pass.** Its lid is
  3 mm, its cavity is shared by several boards, and its bed margin is 4 mm.
  Phase 3 is proposed, after the single-board forms have been printed.

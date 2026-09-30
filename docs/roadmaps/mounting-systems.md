# Mounting systems

## Purpose

Every enclosure the engine builds sits on a desk. A mounting system is a
separate printable part that fixes any enclosure to something: a wall, a
monitor arm, a DIN rail, or a rack. One mount design then serves every
enclosure, including the Pi 5 group, instead of each product growing its own
brackets.

All four phases are built: the interface and the keyhole plate, the VESA
plates, the DIN clip, and the rack ears.

## Decision: one interface, many mounts

The enclosure gets a single **mount interface** on its underside, and each
mount is a plate that bolts to it. A mount never touches the enclosure's
inside, so it cannot disturb the board supports, the bosses, or the lid.

- **Mount pads.** Four raised pads under the floor, each with a heat-set
  insert pocket. The pads are the only change to the base. They add height
  below the floor, so the pocket can be deep enough for an insert without
  breaking through to the cavity.
- **Mount plate.** A printed part with four clearance holes on the pad
  pattern and the mount's own features on its other face.
- **Fasteners.** M3 screws up through the plate into the inserts. The
  catalog already has M3 and its insert dimensions.

Why not a dovetail slide or snap-on rail: a slide needs no hardware, but a
printed dovetail creeps under load and its fit depends on printer
compensation, which has no print data behind it yet. Screws into inserts are
the retention the engine already trusts for the lid.

Why pads and not screws through the floor: the floor is 2 mm, too thin to
hold an insert, and screw heads inside the cavity would collide with
standoffs and cradles.

## The pad pattern

Placement is the hard part, so it is fixed by rules rather than a per-board
choice:

1. Pads sit at the corners of a rectangle inset from the outer footprint by
   the wall thickness plus the pad radius.
2. A pad must not sit under a clearance hole, cable opening, or vent slot
   on the floor. The builder moves it along the diagonal or refuses, naming
   the conflict.
3. The pattern is recorded in the build record as `mount_pad_positions`, so
   a mount is built from the record and needs no access to the enclosure's
   CAD.

The single-board enclosure and the Pi 5 group both expose the same record
fields, so one mount generator reads either.

## Mounts

| Mount | What it is | Standard it follows | Notes |
| --- | --- | --- | --- |
| Keyhole plate | Flat plate with two keyhole slots, hung on wall screws | 8 mm head, 4 mm shank, slot travel at least 10 mm | Simplest; first to build |
| VESA plate | Plate with a 75 x 75 or 100 x 100 mm M4 hole pattern | VESA MIS-D | Plate grows to cover the pattern; a footprint whose pads sit near the pattern needs the other size |
| DIN clip | Plate with a fixed hook and a spring-latch hook | 35 mm rail, TS35 x 7.5 | The latch is a printed flexure; its thickness is the risk |
| Rack ears | Pair of flat flanges bolted to the front wall, with EIA hole spacing | 19 inch, 1U = 44.45 mm, holes at 6.35 / 22.225 / 38.1 mm | Group enclosures only; the enclosure must fit in 1U, and each ear must fit the bed |

Rack ears are the odd one out. They attach to the front wall, not the
underside, so they need their own pads there, and they only fit an enclosure
that is at most 1U tall. The design first put the pads on the side walls,
with an L-shaped ear. That grew the base by the pad height on each side: the
Pi 5 pair, 176 mm wide, would become 184 mm and stop fitting the 180 mm bed.
Front pads add depth instead, so the base keeps its width. The pads are two
stacked at each end, at the wall's corner where it is solid (the cable
openings are near the ends, lower down); the stack's height resists the
enclosure pitching forward off the ears. They are built for the group only,
because the single-board enclosure's walls carry openings that vary by board.

## Checks

Each mount is checked before it is returned, as the enclosure builder does
for its parts:

- No volume shared with the enclosure beyond the pad faces it seats on.
- Screw reach: the screw is long enough to engage the insert and short
  enough to stay inside the pad.
- Standard conformance: VESA and rack hole positions, DIN rail width, and
  keyhole travel are asserted against the published dimensions.
- Print orientation: the mount prints on its flat face, with no overhang
  beyond the manufacturing policy's limit.
- Load: the mount's own features (a keyhole, a DIN hook) keep the wall
  thickness the profile's minimum requires. Strength is not modelled; the
  docs say so.

The mount passes through the same export pipeline as the enclosure: STEP,
STL, metadata, and validation against the printer profile.

## Phases

1. **Interface and keyhole plate (built).** Mount pads on the single-board enclosure
   and the group; `mount_pad_positions` in the build record; the keyhole
   plate; `--mount keyhole` on `enclosure build` and `enclosure-group
   build`.
2. **VESA plate (built).** Reuses the interface; adds the hole-pattern checks.
3. **DIN clip (built).** Adds the flexure and its strain check. The latch is
   a 1.6 mm tongue cut from the plate, bending in the layer plane; its
   strain is 3 t d / (2 L^2) against a provisional 1.5 % limit for printed
   PETG, which no print has measured.
4. **Rack ears (built).** Adds front-wall pads, two flat ears exported as
   `mount-left` and `mount-right`, the 1U fit check, and a bed check for
   the ears' length. An ear reaches from the enclosure to the rack's edge,
   so a narrow enclosure needs a long ear: the 176 mm pair gives 165 mm
   ears, but a single 88 mm bay would need about 197 mm and is refused on
   a 180 mm bed.

Each phase is one PR. Phase 1 changes existing enclosure geometry, so it
also needs a version bump for the enclosure builder's records and revised
builds of anything already reviewed.

## Not covered

- Magnets and adhesive pads. The catalog has magnets, but a magnet mount
  needs a pull-force test no one has run.
- Hinged or tilting mounts.
- Strength claims. Printed plates under load need a physical trial, which
  the Validation Lab already models; a mount target would be added there
  once a printer is available.

## Decisions

- Pads always sit at the corners of the footprint. A mount with its own
  spacing (VESA 75 on a small enclosure) gets a plate larger than the
  enclosure rather than moved pads.
- The group enclosure's pads do not follow its dividers, so the bay layout
  is never constrained by the mount.

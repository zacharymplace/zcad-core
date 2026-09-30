# Thermal features

## Purpose

An enclosure holds heat in. A Pico 2 gives off a fraction of a watt and needs
nothing; a Raspberry Pi 5 under load gives off several, and a pair of them in
one closed PETG box can run the air inside toward the point where the plastic
softens. The engine has some cooling today, all of it fixed: wall slots 1.6 mm
wide at a 4 mm pitch (`--vent-slots`), lid slots 2.4 mm wide over a part the
catalog flags as drawing air from above, and the group's five lid slots over
each fan. It has no idea how much heat a design must shed, so it cannot say
whether it sheds enough.

Phase 1, the power figures and the temperature estimate, is built, and differs
from the first design in several ways (see *What phase 1 changed* below).
Phases 2 to 4 are design only.

## Decision: an estimate first, and the geometry second

Vents and fans are easy to draw and hard to justify. The first thing the
engine needs is a number to justify them with, so phase 1 adds no geometry at
all. It adds the data and the arithmetic.

- **Power.** Each board, display, and cooler in the catalog gets a typical and
  a peak dissipation, in watts, with its source beside it, as the Pi 5's
  dimensions cite Raspberry Pi's drawings. A part with no source has no
  number, and a design containing it reports the thermal estimate as
  unavailable rather than assuming zero. The builder also takes `--power-w` to
  declare a figure the catalog lacks, such as a hat or an SSD.
- **Material limit.** The material profile gets a `max_service_c`. PETG softens
  from about 70 to 80 degrees C, and the profile already says to keep it away
  from sustained heat, so the provisional limit is 60 degrees C of continuous
  air temperature. It is a design value, not a measurement, like the flexure
  strain limit.
- **The estimate.** A lumped steady-state balance: the heat a box sheds is its
  outer surface times a combined convection-and-radiation coefficient times
  the rise over ambient. For still air around a plastic box that coefficient
  is roughly 8 to 10 W/m2K, and the engine uses 8, the pessimistic end.
  Venting adds a chimney term from the free area and the height between inlet
  and outlet. The output is a rise in degrees C with the assumptions printed
  beside it, and `--ambient-c` (25 by default) turns it into a temperature.

A worked example shows why this comes first. The Pi 5 pair's outer surface is
about 0.049 m2, so a closed box sheds about 0.39 W for each degree of rise at
8 W/m2K. If each Pi gave off 8 W under load (an assumed figure, not a
sourced one), the air would rise by about 41 degrees: 66 degrees C from a 25
degree room, past the provisional limit, closed. That is the kind of result
the builder should print before anyone prints a box.

**It is an estimate, not a simulation.** It ignores conduction into the
plastic and whatever the box sits on, hot spots, and airflow past the box.
Expect it to be off by half either way, and treat a trial with a thermocouple
as the only real answer. The build says so whenever it prints the number.

## Decision: a vent pattern generator, not more slot counts

`--vent-slots N` cuts N fixed slots and nothing else. The pattern generator
replaces the fixed figures with a choice of pattern and a target, and
`--vent-slots` keeps working as a shorthand for the slot pattern.

| Pattern | Use |
| --- | --- |
| Slots | Today's vents. Simplest; good in a long wall. |
| Hex grid | The most free area for the least weakening of a flat face. Good in a lid or floor. |
| Round holes | Good where a fan's guard or a dust screen will sit behind them. |
| Louvers | Angled slats that block a straight line of sight in, for a box that sits under a drip or a light. Printable only as 45 degree slats. |

- **Target.** The builder takes a free area in mm2, or a fraction of a face,
  and sizes the pattern to it, rather than a slot count.
- **Inlet low, outlet high.** Natural convection needs a path. The builder
  assigns inlet zones to low wall and floor-edge positions and outlet zones
  to the lid and the top of the walls, and requires the outlet's free area to
  be at least the inlet's. A single vent zone on one face still counts, at a
  lower rate, because air can swirl in and out of it.
- **Floor vents need feet.** A floor vent on a desk breathes nothing. They
  are refused unless the box stands at least 5 mm clear, which the mount
  pads can provide, or a set of four feet that the builder adds.
- **Printability.** The profile's minimum wall and a minimum web of 1.2 mm
  between vents bound the pattern, and a horizontal round hole in a wall is
  drawn as a teardrop. Vents stay clear of the corner bosses, the wall
  openings, the display window, the standoffs, and the hinge and slide
  features, each of which already takes some wall.

## Decision: fan bays from a small catalog, with data from datasheets

A fan is hardware, so it goes in the catalog beside the boards:

- **Sizes.** 30, 40, and 60 mm, each in 10 and 15 mm thicknesses. The Pi 5's
  Active Cooler already has a 30 mm fan.
- **Data.** Mounting-hole spacing (24, 32, and 50 mm on a square), hole
  diameter, rated voltage, rated airflow, and the connector, each cited to the
  maker's datasheet. A fan with no airflow figure can be fitted but adds
  nothing to the estimate.
- **The bay.** A round opening 90 per cent of the fan's size, with a guard
  pattern across it so a finger cannot reach the blades, four mounting holes
  that take self-tapping screws or heat-set inserts, and a flag for which way
  it blows. A fan in the lid over a hot part is the Pi 5 case; a fan in a wall
  is the general one.
- **Checks.** The fan and its screws clear the board's parts, the fan's face
  is not covered by the display or the lid's vents, and its airflow pairs with
  a free-area outlet, so a fan that pushes air in has somewhere for it to go.
- **A duct**, printed, from a fan to a heatsink, for the case where the fan
  cannot sit over the part. It is the last thing in this phase and the most
  likely to be dropped.

## Checks

- **Temperature estimate** against the material's limit: a warning above 85 per
  cent of the limit, a failure above it.
- **Free area:** inlet and outlet areas, and that the outlet is not smaller.
- **Fan:** clear of parts, not covered, and its airflow counted in the budget.
- **Printability:** minimum wall, web, and overhang, through the same export
  pipeline as every part.
- **Unknowns stay unknown:** a design with a part of no declared power gets no
  estimate, and the output says which part is missing.

## Phases

1. **Power, limit, and the estimate (built)**: the catalog's dissipation figures with
   sources, `max_service_c` in the material profile, the lumped estimate and
   its report in the build output, `--power-w` and `--ambient-c`. No
   geometry.
2. **The vent pattern generator**: hex, round, slot, and louver patterns
   sized to a free area, inlet and outlet zones, feet for floor vents, and the
   printability checks. `--vent-slots` remains.
3. **Fan bays**: the fan catalog, the bay with its guard and mounting holes,
   and the clearance and airflow checks.
4. **The Pi 5 group, review, and trials**: the group's own vents and fans
   through the same machinery, the exploded review model showing the air path,
   and thermal trial records, so a measured temperature can correct the
   estimate's coefficient the way a measured hole corrects hole compensation.

### What phase 1 changed

- **Two sourced figures, and a lot of unknowns.** The Raspberry Pi Pico 2
  datasheet's own table gives 62.1 mW typical and 71.3 mW peak, so those are
  the catalog's first vendor figures. Raspberry Pi publishes no Pi 5
  dissipation, only its supply's 5 V at 5 A capability, and the
  measurements found were community posts on the Raspberry Pi forums: the
  catalog records 3.0 W idle, from the USB-C-input reading of 2.9 to 3.1 W
  posted on 17 April 2024, marked `community`, with no peak, because the load
  figures did not trace to a source that held up (one poster reported never
  seeing more than 7 W, from a board that was throttling). Every other board,
  every display, and the Active Cooler's fan have no figure.
- **Unknown gives a lower bound, not "unavailable".** The design said a design
  with an unsourced part reports no estimate. Since most parts have no figure,
  the estimate adds what is known and reports `at least` a temperature, with
  the unknown parts named. It can prove a box too hot and never that it is
  cool enough. A design with nothing known and nothing declared is
  `unavailable`.
- **A part with no peak lends its typical figure,** and the output says so, so
  the Pi 5 pair's 40 degrees C is labelled a minimum: it is idle.
- **The worked example changed.** The design's 66 degrees C used an assumed
  8 W a Pi. With the one sourced figure the pair, 0.049 m2 and 6 W at idle,
  rises 15 degrees to 40 degrees C; a load figure is the user's to declare
  with `--power-w`.
- **Thresholds are on the temperature.** The status is `warn` from 85 per cent
  of the limit in degrees C (51 for PETG's 60) and `fail` above it, and a
  failure refuses the build unless `--allow-hot`, as proposed.
- **Reserved bays count as empty.** Only fitted Pi bays add power to the
  group's estimate.
- **It is in the build record,** under `thermal`, so a later trial can compare
  a measured temperature with it. The record's schema version is unchanged,
  since the field is additive.

Each phase is one PR. Phase 1 changes no geometry, so nothing already
reviewed needs a revised build.

## Not covered

- Simulation. Computational fluid dynamics is out of scope; the estimate is a
  sanity check that makes a missing vent visible.
- Heatsinks and thermal pads beyond the Pi 5's Active Cooler, and anything
  that bonds to a chip.
- Forced-air design beyond a fan and a duct: no baffles, no pressure
  calculation.
- Waterproofing. A vented box is not sealed, and a louver keeps out drips at
  best.
- A claim of safety. A printed enclosure is not a rated product; the docs say
  so wherever they print a temperature.

## Open questions

- **Whether going over the limit is a warning or a failure.** A lumped
  estimate is wrong by half either way. Proposed: a warning above 85 per cent
  of the limit, and a failure only above it, with `--allow-hot` for someone who
  has measured and knows better.
- **Which fans to catalog first.** Proposed: 30, 40, and 60 mm, in 10 mm
  thickness, with the datasheets of one maker for each size rather than
  several makers' averages.

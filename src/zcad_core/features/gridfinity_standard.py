"""The Gridfinity figures the engine builds to, and where each comes from.

Gridfinity is a community standard. Its figures here come from two sources, named in every
build record:

- ``SPECIFICATION``: the unofficial specification's README and its two profile drawings;
- ``REBUILT``: Gridfinity Rebuilt's ``src/core/standard.scad`` and
  ``src/core/gridfinity-baseplate.scad`` at a pinned commit (MIT licence), whose constants say
  which follow the specification.

A figure the engine chose itself, where neither source gives one, is not here: it lives beside
the code that uses it and is registered as a design value. The tests check the built solids
against these figures, so a change that drifts from the standard fails the gate.
"""

from __future__ import annotations

SPECIFICATION = (
    "Unofficial Gridfinity specification, https://github.com/gridfinity-unofficial/"
    "specification, README.md and images/diagram-profiles-{blocks,baseplates}.jpeg"
)
REBUILT = (
    "Gridfinity Rebuilt, https://github.com/kennetek/gridfinity-rebuilt-openscad, "
    "src/core/standard.scad and src/core/gridfinity-baseplate.scad at commit "
    "910e22d8607fd7f5f51ad5e5cbc5287a76810bfd (MIT licence)"
)
# The half grid is Rebuilt's, not the specification's, which never mentions half units.
REBUILT_HALF_GRID = (
    "Gridfinity Rebuilt's half grid, https://github.com/kennetek/gridfinity-rebuilt-openscad, "
    "gridfinity-rebuilt-bins.scad (half_grid, grid_dimensions, only_corners) and "
    "src/core/base.scad at commit 910e22d8607fd7f5f51ad5e5cbc5287a76810bfd (MIT licence); "
    "not in the unofficial specification"
)

# The grid: a unit is 42 mm square and 7 mm tall. (SPECIFICATION)
GRID_MM = 42.0
HEIGHT_UNIT_MM = 7.0
# A bin's unit is 41.5 mm square at the top of its base, leaving 0.25 mm each side in its cell,
# with 3.75 mm corners; its base profile is 4.75 mm tall. (SPECIFICATION, REBUILT)
BASE_TOP_MM = 41.5
BASE_TOP_RADIUS_MM = 3.75
# The base profile from its bottom up, as (rise, run outward): 0.8 at 45 degrees, 1.8 straight
# up, 2.15 at 45 degrees. (REBUILT, which cites the specification)
BASE_PROFILE_STEPS_MM = ((0.8, 0.8), (1.8, 0.0), (2.15, 2.15))
# The base, the profile and the bridge that joins a bin's units above it. (REBUILT)
BASE_HEIGHT_MM = 7.0
# The stacking lip from its inner tip up, as (rise, run outward): 0.7 at 45 degrees, 1.8
# straight up, 1.9 at 45 degrees. (REBUILT, which cites the specification)
LIP_STEPS_MM = ((0.7, 0.7), (1.8, 0.0), (1.9, 1.9))
# Magnets 6 mm across and 2 mm thick, in all four corners of a unit (SPECIFICATION), in holes
# 6.5 mm across and 2.4 mm deep, 8 mm in from each side of the unit's 42 mm square. (REBUILT)
MAGNET_HOLE_MM = 6.5
MAGNET_HOLE_DEPTH_MM = 2.4
MAGNET_INSET_MM = 8.0
# An M3 screw hole, 3 mm across, at a unit's corners as the magnets are. (REBUILT,
# standard.scad SCREW_HOLE_RADIUS; gridfinity-rebuilt-holes.scad places it with the magnet)
SCREW_HOLE_MM = 3.0
# The half grid: bases on a 21 mm pitch, half the grid, each the full profile on a top the pitch
# less the full grid's 0.5 mm gap, so they still fit an ordinary baseplate. Its magnet and screw
# holes are at the bin's four outer corners only, 4.8 mm in from the edge of its bases' bottom.
# (REBUILT_HALF_GRID: gridfinity-rebuilt-bins.scad:115-117, base.scad:34 and 273-276,
# standard.scad:35 and 201-205)
HALF_GRID_MM = 21.0
HALF_GRID_HOLE_INSET_MM = 4.8
# A baseplate with magnets or screws stands on a floor under its cells: 1 mm, with the magnet
# hole's depth and a 45-degree countersink 2.5 mm deep added for each. (REBUILT,
# gridfinity-rebuilt-baseplate.scad calculate_offset_skeletonized, h_skel and
# BASEPLATE_SCREW_COUNTERSINK_ADDITIONAL_RADIUS)
BASEPLATE_FLOOR_MM = 1.0
BASEPLATE_COUNTERSINK_MM = 2.5
# A baseplate cell is 42 mm square with 8.0 mm corners (a 4.0 mm radius) and 5 mm tall.
# (SPECIFICATION, REBUILT)
BASEPLATE_CELL_RADIUS_MM = 4.0
BASEPLATE_HEIGHT_MM = 5.0
# The baseplate's own profile from its bottom up: 0.7 at 45 degrees, 1.8 straight up, 2.15 at
# 45 degrees, 4.65 mm in all; the plate's height over it is a straight clearance at the socket's
# bottom, so a base always meets the socket's slopes. (REBUILT, which cites the specification)
BASEPLATE_PROFILE_STEPS_MM = ((0.7, 0.7), (1.8, 0.0), (2.15, 2.15))


def profile_insets(steps: tuple[tuple[float, float], ...]) -> list[tuple[float, float]]:
    """A stepped profile as (height, inset) pairs from its bottom, the inset measured in from the
    widest point at its top."""

    total = sum(run for _, run in steps)
    points = [(0.0, total)]
    height, inset = 0.0, total

    for rise, run in steps:
        height += rise
        inset -= run
        points.append((round(height, 6), round(inset, 6)))

    return points


BASE_GAP_MM = GRID_MM - BASE_TOP_MM
BASE_PROFILE_HEIGHT_MM = sum(rise for rise, _ in BASE_PROFILE_STEPS_MM)
BASE_PROFILE_DEPTH_MM = sum(run for _, run in BASE_PROFILE_STEPS_MM)
LIP_HEIGHT_MM = sum(rise for rise, _ in LIP_STEPS_MM)
BASEPLATE_PROFILE_HEIGHT_MM = sum(rise for rise, _ in BASEPLATE_PROFILE_STEPS_MM)
BASEPLATE_PROFILE_DEPTH_MM = sum(run for _, run in BASEPLATE_PROFILE_STEPS_MM)
BASEPLATE_CLEARANCE_MM = BASEPLATE_HEIGHT_MM - BASEPLATE_PROFILE_HEIGHT_MM
LIP_DEPTH_MM = sum(run for _, run in LIP_STEPS_MM)

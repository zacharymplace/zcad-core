from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_group import GroupDesign, build_group_enclosure
from zcad_core.features.mounts import (
    DIN_FLANGE_THICKNESS_MM,
    DIN_FLANGE_WIDTH_MM,
    DIN_RAIL_WIDTH_MM,
    FLEXURE_STRAIN_LIMIT,
    FLEXURE_THICKNESS_MM,
    MountPads,
    build_mount,
    flexure_for,
    mount_pads,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import get_fastener

M3 = get_fastener("M3")
PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
# The printer profile's minimum wall, and the manufacturing policy's limit on
# unsupported overhang.
MINIMUM_WALL_MM = 1.2
MAXIMUM_OVERHANG_MM = 3.0


def pads_for(width: float = 33.0, depth: float = 77.0) -> MountPads:
    return mount_pads(
        x_span_mm=(0.0, width),
        y_span_mm=(0.0, depth),
        floor_underside_z_mm=0.0,
        floor_mm=2.0,
        wall_mm=2.0,
        fastener=M3,
    )


def solid(model: cq.Workplane) -> cq.Compound:
    return cq.Compound.makeCompound(
        [
            part
            for item in model.vals()
            if isinstance(item, cq.Shape)
            for part in item.Solids()
        ]
    )


def has_material(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    return bool(solid(model).isInside(cq.Vector(x, y, z)))


def centre(pads: MountPads) -> tuple[float, float]:
    xs = [x for x, _ in pads.positions]
    ys = [y for _, y in pads.positions]

    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def ts35_rail(cx: float, cy: float, top_z: float, thickness: float) -> cq.Shape:
    """The rail's two flanges along X, their upper face at ``top_z``; the web
    between them is left out, as it lies below the plate's reach."""

    flanges = []

    for low in (cy - DIN_RAIL_WIDTH_MM / 2, cy + DIN_RAIL_WIDTH_MM / 2 - 4.0):
        flanges.append(
            cq.Solid.makeBox(
                200.0,
                DIN_FLANGE_WIDTH_MM,
                thickness,
                pnt=cq.Vector(cx - 100.0, low, top_z - thickness),
            )
        )

    return cq.Compound.makeCompound(flanges)


@pytest.mark.parametrize("thickness", [1.0, DIN_FLANGE_THICKNESS_MM])
def test_plate_sits_on_a_ts35_rail_with_its_lips_under_the_flanges(
    thickness: float,
) -> None:
    pads = pads_for()
    mount = build_mount("din", pads, fastener=M3)
    cx, cy = centre(pads)
    bottom = pads.mating_z_mm - 4.0
    rail = ts35_rail(cx, cy, bottom, thickness)

    # Seated on both flanges without sharing any volume with them.
    assert intersection_volume(solid(mount.plate), rail) < 1e-6

    # A lip reaches under each flange: material under the flange's far half,
    # and none in the flange's own slot between plate and lip.
    under = bottom - DIN_FLANGE_THICKNESS_MM - 0.2 - 1.0
    in_slot = bottom - thickness / 2
    flange_mid = DIN_RAIL_WIDTH_MM / 2 - DIN_FLANGE_WIDTH_MM / 2

    for sign in (-1, 1):
        y = cy + sign * flange_mid
        assert has_material(mount.plate, cx - 10.0 if sign < 0 else cx, y, under)
        assert not has_material(mount.plate, cx, y, in_slot)
        # The wall stands outside the flange's edge.
        wall_y = cy + sign * (DIN_RAIL_WIDTH_MM / 2 + 0.3 + 0.8)
        assert has_material(
            mount.plate, cx - 10.0 if sign < 0 else cx, wall_y, bottom - 1.0
        )


def test_latch_lip_clears_the_flange_when_the_tongue_swings_out() -> None:
    pads = pads_for()
    mount = build_mount("din", pads, fastener=M3)
    assert mount.flexure is not None
    cx, cy = centre(pads)
    bottom = pads.mating_z_mm - 4.0
    # The latch lip runs from the wall's inner face 2.5 mm toward the rail's
    # centre; swung out by the tongue's deflection its tip is past the flange's
    # edge, so the plate presses on.
    lip_tip = cy - (DIN_RAIL_WIDTH_MM / 2 + 0.3) + 2.5
    flange_edge = cy - DIN_RAIL_WIDTH_MM / 2

    assert lip_tip - mount.flexure.deflection_mm < flange_edge
    # At rest the lip does reach under the flange.
    under = bottom - DIN_FLANGE_THICKNESS_MM - 0.2 - 1.0
    assert has_material(mount.plate, cx - 10.0, lip_tip - 0.3, under)


def test_the_latch_is_a_tongue_of_one_solid_that_moves_freely() -> None:
    pads = pads_for()
    mount = build_mount("din", pads, fastener=M3)
    cx, cy = centre(pads)
    mid = pads.mating_z_mm - 2.0

    # One printable piece, with slits either side of and beyond the tongue.
    assert len(mount.plate.solids().vals()) == 1
    tongue_y = cy - (DIN_RAIL_WIDTH_MM / 2 + 0.3) - FLEXURE_THICKNESS_MM / 2
    assert has_material(mount.plate, cx + 5.0, tongue_y, mid)  # the tongue
    assert not has_material(mount.plate, cx + 5.0, tongue_y - 3.0, mid)  # outer slit
    assert not has_material(mount.plate, cx + 5.0, tongue_y + 1.2, mid)  # inner slit
    # The tongue joins the plate at its root end.
    assert has_material(mount.plate, cx + 15.0, tongue_y, mid)


def test_flexure_strain_is_within_the_design_limit() -> None:
    mount = build_mount("din", pads_for(), fastener=M3)
    flexure = mount.flexure

    assert flexure is not None
    assert flexure.strain <= FLEXURE_STRAIN_LIMIT
    # Matches the cantilever formula for the numbers it reports.
    expected = 3 * flexure.thickness_mm * flexure.deflection_mm
    expected /= 2 * flexure.length_mm**2
    assert flexure.strain == pytest.approx(expected)
    # The tongue is thick enough to print, and bends in the layer plane, so
    # its thickness is a wall the printer profile has to honour.
    assert flexure.thickness_mm >= MINIMUM_WALL_MM


def test_a_shorter_tongue_strains_more() -> None:
    assert flexure_for(2.8, 15.0).strain > flexure_for(2.8, 22.0).strain
    assert flexure_for(2.8, 15.0).strain > FLEXURE_STRAIN_LIMIT


def test_lip_overhang_is_printable() -> None:
    # Each lip overhangs its wall by 2.5 mm, printed hooks up.
    from zcad_core.features import mounts

    assert mounts._DIN_LIP_WIDTH_MM <= MAXIMUM_OVERHANG_MM


def test_a_footprint_too_small_for_the_latch_slot_is_refused() -> None:
    with pytest.raises(ValueError, match="too small for a DIN clip"):
        build_mount("din", pads_for(width=40.0, depth=60.0), fastener=M3)


def test_a_plate_too_thin_for_the_tongue_is_refused() -> None:
    with pytest.raises(ValueError, match="too thin"):
        build_mount("din", pads_for(), fastener=M3, plate_mm=2.4)


def test_din_plate_reports_how_it_attaches() -> None:
    mount = build_mount("din", pads_for(), fastener=M3)

    assert mount.attachment is not None and "DIN rail" in mount.attachment
    assert mount.device_screws is None
    assert build_mount("keyhole", pads_for(), fastener=M3).flexure is None


def test_group_with_a_din_mount_keeps_every_check() -> None:
    group = build_group_enclosure(design=GroupDesign(mount="din"))

    assert group.passed
    assert group.mount is not None and group.mount.flexure is not None


def test_cli_reports_the_flexure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "enclosure",
            "build",
            "--board",
            "raspberry_pi_pico_2",
            "--mount",
            "din",
            "--output-directory",
            str(tmp_path),
            "--printer-profile",
            str(PRINTER_PROFILE),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert set(output["parts"]) == {"base", "lid", "mount"}
    assert output["mount"]["flexure"]["strain_percent"] <= 1.5
    assert output["mount"]["flexure"]["strain_limit_percent"] == 1.5
    assert "DIN rail" in output["mount"]["attachment"]

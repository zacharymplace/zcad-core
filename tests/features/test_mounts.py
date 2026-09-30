from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.assemblies import Placement, build_board_assembly
from zcad_core.cli import main
from zcad_core.features import EnclosureDesign, build_enclosure
from zcad_core.features.enclosure_group import GroupDesign, build_group_enclosure
from zcad_core.features.mounts import (
    KEYHOLE_HEAD_DIAMETER_MM,
    KEYHOLE_SLOT_WIDTH_MM,
    KEYHOLE_TRAVEL_MM,
    MINIMUM_PAD_HEIGHT_MM,
    POCKET_ROOF_MM,
    MountPads,
    add_mount_pads,
    build_mount,
    mount_pads,
    pad_height_mm,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.hardware import get_fastener, get_raspberry_pi_pico2

M3 = get_fastener("M3")
BOARD = get_raspberry_pi_pico2()
PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def pads_for(width: float = 60.0, depth: float = 100.0) -> MountPads:
    return mount_pads(
        x_span_mm=(0.0, width),
        y_span_mm=(0.0, depth),
        floor_underside_z_mm=0.0,
        floor_mm=2.0,
        wall_mm=2.0,
        fastener=M3,
    )


def has_material(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    shape = cq.Compound.makeCompound(
        [
            solid
            for item in model.vals()
            if isinstance(item, cq.Shape)
            for solid in item.Solids()
        ]
    )

    return bool(shape.isInside(cq.Vector(x, y, z)))


def test_pads_sit_at_the_four_corners_inside_the_footprint() -> None:
    pads = pads_for()
    xs = sorted({round(x, 6) for x, _ in pads.positions})
    ys = sorted({round(y, 6) for _, y in pads.positions})

    assert len(pads.positions) == 4
    assert len(xs) == 2 and len(ys) == 2
    assert xs[0] > 0 and xs[1] < 60
    assert ys[0] > 0 and ys[1] < 100
    # Each pad sits under the wall's inner face: inset by wall plus radius.
    assert xs[0] == pytest.approx(2.0 + pads.diameter_mm / 2)


def test_pad_leaves_a_roof_over_the_insert_pocket() -> None:
    pads = pads_for()

    # The pocket's top is this far below the floor's top face.
    top = pads.mating_z_mm + pads.pocket_depth_mm
    roof = 2.0 - top

    assert roof >= POCKET_ROOF_MM - 1e-9
    assert pads.height_mm >= MINIMUM_PAD_HEIGHT_MM
    assert pad_height_mm(M3, 2.0) == pads.height_mm


def test_pads_are_cut_with_pockets_that_stay_inside_the_floor() -> None:
    pads = pads_for()
    floor = cq.Workplane("XY").box(60.0, 100.0, 2.0, centered=False)
    base = add_mount_pads(floor, pads)
    x, y = pads.positions[0]

    assert has_material(base, x + 3.5, y, pads.mating_z_mm + 0.5)  # pad wall
    assert not has_material(base, x, y, pads.mating_z_mm + 1.0)  # pocket
    assert has_material(base, x, y, pads.mating_z_mm + pads.pocket_depth_mm + 0.3)
    assert workplane_shape(base).BoundingBox().zmax == pytest.approx(
        2.0
    )  # no breakthrough


def test_a_footprint_too_small_for_four_pads_is_refused() -> None:
    with pytest.raises(ValueError, match="too small for four mount pads"):
        pads_for(width=20.0)


def test_keyhole_plate_follows_the_published_dimensions() -> None:
    pads = pads_for()
    mount = build_mount("keyhole", pads, fastener=M3)
    plate = mount.plate
    bounds = workplane_shape(plate).BoundingBox()

    # Seated on the pads' bottom faces, and only touching them.
    assert bounds.zmax == pytest.approx(pads.mating_z_mm)
    assert bounds.zmin == pytest.approx(pads.mating_z_mm - 4.0)
    assert KEYHOLE_TRAVEL_MM >= 10.0
    assert KEYHOLE_HEAD_DIAMETER_MM > 8.0

    mid = pads.mating_z_mm - 2.0
    cx = (bounds.xmin + bounds.xmax) / 2
    cy = (bounds.ymin + bounds.ymax) / 2
    offset = min((pads.positions[1][0] - pads.positions[0][0]) / 2, 40.0) * 0.6
    below = KEYHOLE_TRAVEL_MM + KEYHOLE_SLOT_WIDTH_MM / 2
    hole_y = cy - (KEYHOLE_HEAD_DIAMETER_MM / 2 - below) / 2

    assert not has_material(plate, cx - offset, hole_y, mid)  # large hole
    assert not has_material(plate, cx - offset, hole_y - KEYHOLE_TRAVEL_MM, mid)
    assert has_material(plate, cx - offset + 4.0, hole_y - 6.0, mid)  # beside slot
    # Each pad's screw hole goes through, with a countersink on the outer face.
    x, y = pads.positions[0]
    assert not has_material(plate, x, y, mid)
    assert not has_material(plate, x + 2.5, y, pads.mating_z_mm - 4.0 + 0.3)
    assert has_material(plate, x + 2.5, y, pads.mating_z_mm - 0.3)
    assert mount.recommended_screw_mm == 8


def test_plate_too_thin_to_countersink_is_refused() -> None:
    with pytest.raises(ValueError, match="countersunk"):
        build_mount("keyhole", pads_for(), fastener=M3, plate_mm=2.0)


def test_unknown_mount_is_refused() -> None:
    with pytest.raises(ValueError, match="mount must be one of"):
        build_mount("suction-cup", pads_for(), fastener=M3)
    with pytest.raises(ValueError, match="mount must be one of"):
        EnclosureDesign(mount="suction-cup").validate()
    with pytest.raises(ValueError, match="mount must be one of"):
        GroupDesign(mount="suction-cup").validate()


def test_a_plate_with_no_room_for_keyholes_is_refused() -> None:
    with pytest.raises(ValueError, match="no room for a keyhole"):
        build_mount("keyhole", pads_for(width=50.0, depth=34.0), fastener=M3)


def test_enclosure_without_a_mount_is_unchanged() -> None:
    assembly = build_board_assembly(
        board=BOARD,
        board_placement=Placement(),
        connector_access_clearance_mm=2.0,
    )
    plain = build_enclosure(assembly, board=BOARD)

    assert plain.mount is None and plain.mount_pads is None


def test_enclosure_with_a_mount_adds_pads_and_a_seated_plate() -> None:
    assembly = build_board_assembly(
        board=BOARD,
        board_placement=Placement(),
        connector_access_clearance_mm=2.0,
    )
    plain = build_enclosure(assembly, board=BOARD)
    mounted = build_enclosure(
        assembly, board=BOARD, design=replace(plain.design, mount="keyhole")
    )

    assert mounted.mount is not None and mounted.mount_pads is not None
    assert len(mounted.mount_pads.positions) == 4
    assert workplane_shape(mounted.base).Volume() > workplane_shape(plain.base).Volume()
    # Only the floor's underside changed: the lid and the footprint are as before.
    assert workplane_shape(mounted.lid).Volume() == pytest.approx(
        workplane_shape(plain.lid).Volume()
    )
    base = workplane_shape(mounted.base).BoundingBox()
    base_plain = workplane_shape(plain.base).BoundingBox()
    assert base.xlen == pytest.approx(base_plain.xlen)
    assert base.zmin == pytest.approx(base_plain.zmin - mounted.mount_pads.height_mm)
    plate = workplane_shape(mounted.mount.plate).BoundingBox()
    assert plate.zmax == pytest.approx(base.zmin)
    assert plate.xlen == pytest.approx(mounted.mount.size_mm[0])


def test_group_with_a_mount_keeps_every_check() -> None:
    group = build_group_enclosure(design=GroupDesign(mount="keyhole"))

    assert group.passed
    assert group.mount is not None and group.mount_pads is not None
    assert workplane_shape(group.base).BoundingBox().zmin == pytest.approx(
        -group.mount_pads.height_mm
    )
    assert build_group_enclosure().mount is None


def test_cli_exports_the_mount_as_a_third_part(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "enclosure",
            "build",
            "--board",
            "raspberry_pi_pico_2",
            "--mount",
            "keyhole",
            "--output-directory",
            str(tmp_path),
            "--printer-profile",
            str(PRINTER_PROFILE),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert set(output["parts"]) == {"base", "lid", "mount"}
    assert output["mount"]["kind"] == "keyhole"
    assert output["mount"]["screws"].startswith("M3 countersunk x 8 mm")
    record = json.loads((tmp_path / "enclosure.json").read_text())
    assert record["design"]["mount"] == "keyhole"


@pytest.mark.parametrize(("kind", "spacing"), [("vesa75", 75.0), ("vesa100", 100.0)])
def test_vesa_plate_has_the_standard_square_pattern_of_m4_holes(
    kind: str, spacing: float
) -> None:
    pads = pads_for(width=33.0, depth=77.0)
    mount = build_mount(kind, pads, fastener=M3)
    mid = pads.mating_z_mm - 2.0
    xs = [x for x, _ in pads.positions]
    ys = [y for _, y in pads.positions]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    half = spacing / 2

    for dx in (-half, half):
        for dy in (-half, half):
            assert not has_material(mount.plate, cx + dx, cy + dy, mid)
            # M4 clearance is 4.5 mm: clear at 2.0 mm out, solid at 2.5 mm.
            assert not has_material(mount.plate, cx + dx + 2.0, cy + dy, mid)
            assert has_material(mount.plate, cx + dx + 2.5, cy + dy, mid)

    bounds = workplane_shape(mount.plate).BoundingBox()

    # The plate grows to cover the pattern, past a small enclosure's footprint.
    assert bounds.xlen > spacing and bounds.ylen > spacing
    assert (
        mount.device_screws
        == f"M4 x 12 mm, 4 on a {spacing:.0f} x {spacing:.0f} mm pattern"
    )
    # The pad screws still hold the plate on, countersunk on its outer face.
    x, y = pads.positions[0]
    assert not has_material(mount.plate, x, y, mid)


def test_vesa_screw_heads_clear_the_pads() -> None:
    pads = pads_for(width=90.0, depth=90.0)

    with pytest.raises(ValueError, match="mount pad"):
        build_mount("vesa75", pads, fastener=M3)
    # The larger pattern clears the same pads.
    assert build_mount("vesa100", pads, fastener=M3).device_screws is not None


def test_keyhole_plate_has_no_device_screws() -> None:
    assert build_mount("keyhole", pads_for(), fastener=M3).device_screws is None


def test_group_with_a_vesa_mount_keeps_every_check() -> None:
    group = build_group_enclosure(design=GroupDesign(mount="vesa75"))

    assert group.passed
    assert group.mount is not None
    assert group.mount.device_screws is not None

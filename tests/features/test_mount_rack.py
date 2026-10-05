from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features import EnclosureDesign
from zcad_core.features.enclosure_group import (
    GroupDesign,
    GroupEnclosure,
    build_group_enclosure,
)
from zcad_core.features.mount_rack import (
    RACK_HOLE_DIAMETER_MM,
    RACK_HOLE_PITCH_MM,
    RACK_HOLE_SPACING_MM,
    RACK_OPENING_MM,
    RACK_PANEL_HEIGHT_MM,
    RACK_PANEL_WIDTH_MM,
    RACK_UNIT_MM,
    FrontPads,
    add_front_pads,
    build_rack_ears,
    front_pads,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import get_fastener

M3 = get_fastener("M3")
PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


@cache
def pair() -> GroupEnclosure:
    return build_group_enclosure(design=GroupDesign(mount="rack"))


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


def test_ears_follow_the_eia_310_rack_dimensions() -> None:
    group = pair()
    assert group.mount is not None
    left, right = group.mount.parts["mount-left"], group.mount.parts["mount-right"]
    width = group.outer_size_mm[0]
    centre = width / 2
    height = group.cavity_top_z_mm + group.design.lid_mm
    zc = height / 2
    y = -group.mount_pads.height_mm - 2.0 if group.mount_pads else 0.0

    # A 1U panel: the ears' outer edges are 482.6 mm apart.
    bounds_l = solid(left).BoundingBox()
    bounds_r = solid(right).BoundingBox()
    assert bounds_r.xmax - bounds_l.xmin == pytest.approx(RACK_PANEL_WIDTH_MM)
    assert bounds_l.zlen == pytest.approx(RACK_PANEL_HEIGHT_MM)
    assert RACK_PANEL_HEIGHT_MM < RACK_UNIT_MM

    # Rail holes: 465.1 mm apart, three to a unit at 15.875 mm.
    offset = RACK_HOLE_SPACING_MM / 2

    for ear, x in ((left, centre - offset), (right, centre + offset)):
        for k in (-1, 0, 1):
            z = zc + k * RACK_HOLE_PITCH_MM
            assert not has_material(ear, x, y, z)
            assert not has_material(ear, x + RACK_HOLE_DIAMETER_MM / 2 - 0.3, y, z)
            assert has_material(ear, x + RACK_HOLE_DIAMETER_MM / 2 + 0.5, y, z)
        # Not between the holes.
        assert has_material(ear, x, y, zc + RACK_HOLE_PITCH_MM / 2)


def test_the_enclosure_sits_centred_and_its_width_is_unchanged() -> None:
    group = pair()
    bounds = solid(group.base).BoundingBox()
    assert group.mount_pads is not None

    # Pads stand out of the front only, so the base is no wider than before.
    assert bounds.xmin == pytest.approx(0.0)
    assert bounds.xmax == pytest.approx(group.outer_size_mm[0])
    assert bounds.ymin == pytest.approx(-group.mount_pads.height_mm)
    assert bounds.xmax - bounds.xmin <= 180.0
    plain = solid(build_group_enclosure().base).BoundingBox()
    assert plain.xlen == pytest.approx(bounds.xlen)


def test_two_pads_are_stacked_at_each_end_on_solid_wall() -> None:
    group = pair()
    pads = group.mount_pads
    assert isinstance(pads, FrontPads)

    assert len(pads.left) == len(pads.right) == 2
    # Stacked, so they resist the enclosure pitching forward off the ears.
    assert pads.left[0][0] == pads.left[1][0]
    assert abs(pads.left[0][1] - pads.left[1][1]) >= 8.0
    assert pads.right[0][0] == pytest.approx(group.outer_size_mm[0] - pads.left[0][0])
    # Each pocket opens on its pad's front face and stays inside the wall.
    x, z = pads.left[0]
    front = -pads.height_mm
    assert not has_material(group.base, x, front + 1.0, z)
    assert has_material(group.base, x + 3.5, front + 1.0, z)
    wall = group.design.wall_mm
    assert has_material(group.base, x, wall - 0.3, z)


def test_each_ear_is_screwed_to_its_pads_and_touches_only_them() -> None:
    group = pair()
    assert group.mount is not None and isinstance(group.mount_pads, FrontPads)
    pads = group.mount_pads
    base = solid(group.base)
    back = -pads.height_mm

    for name, ear in group.mount.parts.items():
        assert intersection_volume(base, solid(ear)) < 1e-6
        positions = pads.right if name == "mount-right" else pads.left

        for x, z in positions:
            assert not has_material(ear, x, back - 2.0, z)  # the screw hole
            assert has_material(ear, x + 2.5, back - 0.5, z)  # the flange round it
            # Countersunk on the front face, for a flat head.
            assert not has_material(ear, x + 2.5, back - 4.0 + 0.3, z)

    assert group.mount.recommended_screw_mm == 8


def test_ears_are_one_solid_each_and_fit_the_bed() -> None:
    group = pair()
    assert group.mount is not None

    for ear in group.mount.parts.values():
        assert len(ear.solids().vals()) == 1
        bounds = solid(ear).BoundingBox()
        assert bounds.xlen <= 180.0


def test_mount_is_several_named_parts() -> None:
    group = pair()
    assert group.mount is not None

    assert set(group.mount.parts) == {"mount-left", "mount-right"}
    assert group.passed
    assert "rack" in (group.mount.attachment or "")


def test_a_taller_enclosure_than_1u_is_refused() -> None:
    with pytest.raises(ValueError, match="only 1U is supported"):
        build_group_enclosure(design=GroupDesign(mount="rack", headroom_mm=40.0))


def test_a_hinges_knuckles_count_against_the_rack_unit() -> None:
    # The lid plate tops out at 41.6 mm, inside 1U, but the knuckles reach
    # 43.6 mm, past it; the check must see the knuckles.
    with pytest.raises(ValueError, match="43.6 mm tall"):
        build_group_enclosure(
            design=GroupDesign(mount="rack", lid_attachment="hinge", headroom_mm=31.2)
        )


def test_an_enclosure_wider_than_the_rack_is_refused() -> None:
    base = cq.Workplane("XY").box(460.0, 96.0, 25.4, centered=False)
    pads = front_pads(
        base,
        outer_size_mm=(RACK_OPENING_MM + 10.0, 96.0, 25.4),
        enclosure_height_mm=28.4,
        wall_mm=2.0,
        fastener=M3,
    )

    with pytest.raises(ValueError, match="19 inch rack opens"):
        build_rack_ears(pads, enclosure_height_mm=28.4, fastener=M3, plate_mm=4.0)


def test_pads_over_an_opening_in_the_front_wall_are_refused() -> None:
    base = cq.Workplane("XY").box(176.0, 96.0, 25.4, centered=False)
    # A slot through the wall under where the left pads go.
    slot = (
        cq.Workplane("XY")
        .box(12.0, 4.0, 30.0, centered=False)
        .translate((2.0, -1.0, 0.0))
    )

    with pytest.raises(ValueError, match="cover an opening"):
        front_pads(
            base.cut(slot),
            outer_size_mm=(176.0, 96.0, 25.4),
            enclosure_height_mm=28.4,
            wall_mm=2.0,
            fastener=M3,
        )


def test_a_narrow_enclosure_is_refused_for_its_pads() -> None:
    base = cq.Workplane("XY").box(12.0, 96.0, 25.4, centered=False)

    with pytest.raises(ValueError, match="too narrow"):
        front_pads(
            base,
            outer_size_mm=(12.0, 96.0, 25.4),
            enclosure_height_mm=28.4,
            wall_mm=2.0,
            fastener=M3,
        )


def test_add_front_pads_grows_the_front_only() -> None:
    base = cq.Workplane("XY").box(176.0, 96.0, 25.4, centered=False)
    pads = front_pads(
        base,
        outer_size_mm=(176.0, 96.0, 25.4),
        enclosure_height_mm=28.4,
        wall_mm=2.0,
        fastener=M3,
    )
    grown = solid(add_front_pads(base, pads)).BoundingBox()

    assert grown.ymin == pytest.approx(-pads.height_mm)
    assert grown.xlen == pytest.approx(176.0)


def test_rack_is_for_groups_only() -> None:
    GroupDesign(mount="rack").validate()

    with pytest.raises(ValueError, match="mount must be one of"):
        EnclosureDesign(mount="rack").validate()


def run_group(
    capsys: pytest.CaptureFixture[str], output: Path, *args: str
) -> tuple[int, dict[str, object], str]:
    exit_code = main(
        [
            "enclosure-group",
            "build",
            "--output-directory",
            str(output),
            "--printer-profile",
            str(PRINTER_PROFILE),
            *args,
        ]
    )
    captured = capsys.readouterr()

    return exit_code, json.loads(captured.out) if captured.out else {}, captured.err


def test_cli_exports_both_ears_as_parts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output, _ = run_group(
        capsys, tmp_path, "--bays", "pi5,pi5", "--mount", "rack"
    )

    assert exit_code == 0
    parts = output["parts"]
    assert isinstance(parts, dict)
    assert set(parts) == {"base", "lid", "mount-left", "mount-right"}
    screws = output["screws"]
    assert isinstance(screws, dict)
    assert screws["mount"] == "M3 countersunk x 8 mm, 2 per part"
    assert "19 inch rack" in screws["mount_attachment"]


def test_cli_refuses_ears_longer_than_the_bed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # One bay is about 88 mm wide, so each ear reaches about 197 mm.
    exit_code, _, err = run_group(capsys, tmp_path, "--bays", "pi5", "--mount", "rack")

    assert exit_code == 1
    assert "printer's bed" in err
    assert "mount-left" in err

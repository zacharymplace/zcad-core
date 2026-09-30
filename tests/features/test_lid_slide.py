from __future__ import annotations

import json
from dataclasses import replace
from functools import cache
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.assemblies import (
    Placement,
    build_board_assembly,
    build_board_display_assembly,
)
from zcad_core.cli import main
from zcad_core.features import Enclosure, EnclosureDesign, build_enclosure
from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.lid_slide import (
    BULGE_MM,
    GROOVE_DEPTH_MM,
    RETAINING_STRIP_MM,
    TONGUE_MM,
    add_slide,
    slide_entry,
)
from zcad_core.features.mounts import FLEXURE_STRAIN_LIMIT
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import get_raspberry_pi_pico2, get_reference_oled_128x64

BOARD = get_raspberry_pi_pico2()
DISPLAY = get_reference_oled_128x64()
PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
CLEARANCE = 0.2
LID_MM = 2.0
MINIMUM_WALL_MM = 1.2


def board_assembly():  # type: ignore[no-untyped-def]
    return build_board_assembly(
        board=BOARD,
        board_placement=Placement(),
        connector_access_clearance_mm=2.0,
    )


@cache
def slid() -> Enclosure:
    return build_enclosure(
        board_assembly(),
        board=BOARD,
        design=EnclosureDesign(lid_attachment="slide"),
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


def frame(enclosure: Enclosure) -> dict[str, float]:
    """The Pico's long walls face +-X, so the lid slides along Y and enters
    over the +Y wall."""

    spec = enclosure.specification
    slide = enclosure.slide
    assert slide is not None and slide.entry_edge == "positive_y"
    top = spec.bottom_z_mm + spec.inner_height_mm

    return {
        "cx": spec.center_x_mm,
        "cy": spec.center_y_mm,
        "half_c": spec.inner_width_mm / 2,
        "half_a": spec.inner_depth_mm / 2,
        "wall": enclosure.design.wall_mm,
        "top": top,
        "mid": top + LID_MM / 2,
    }


def test_slide_lid_has_no_screws_bosses_or_skirt() -> None:
    enclosure = slid()

    assert enclosure.fastener_positions == ()
    assert enclosure.design.skirt_depth_mm is None
    assert enclosure.slide is not None


def test_a_groove_runs_in_each_long_wall_under_a_retaining_strip() -> None:
    enclosure = slid()
    f = frame(enclosure)
    groove_x = GROOVE_DEPTH_MM / 2

    for side in (1, -1):
        x = f["cx"] + side * (f["half_c"] + groove_x)
        # Empty along the groove at the lid's height, from end to end.
        for y in (f["cy"] - f["half_a"] + 1.0, f["cy"], f["cy"] + f["half_a"] + 1.0):
            assert not has_material(enclosure.base, x, y, f["mid"])
        # Wall beyond the groove, and the strip above it that holds the lid.
        beyond = f["cx"] + side * (f["half_c"] + GROOVE_DEPTH_MM + 0.6)
        assert has_material(enclosure.base, beyond, f["cy"], f["mid"])
        strip = f["top"] + LID_MM + CLEARANCE + RETAINING_STRIP_MM / 2
        assert has_material(enclosure.base, x, f["cy"], strip)
        # Wall below the groove's floor.
        assert has_material(enclosure.base, x, f["cy"], f["top"] - CLEARANCE - 0.4)


def test_walls_rise_above_the_cavity_and_thicken_outward() -> None:
    enclosure = slid()
    f = frame(enclosure)
    base = workplane_shape(enclosure.base).BoundingBox()

    assert base.zmax == pytest.approx(
        f["top"] + LID_MM + CLEARANCE + RETAINING_STRIP_MM
    )
    assert enclosure.slide is not None
    assert enclosure.slide.wall_top_above_cavity_mm == pytest.approx(3.4)
    # Each long wall stands out by the bulge, beyond its own thickness.
    outer = f["half_c"] + f["wall"] + BULGE_MM
    assert base.xmax == pytest.approx(f["cx"] + outer)
    assert base.xmin == pytest.approx(f["cx"] - outer)
    # The bulge sits above a 45 degree slope, so nothing overhangs.
    assert has_material(enclosure.base, f["cx"] + outer - 0.2, f["cy"], f["top"] - 1.0)
    assert not has_material(
        enclosure.base, f["cx"] + outer - 0.2, f["cy"], f["top"] - 4.5
    )


def test_the_entry_wall_is_cut_down_and_the_far_wall_stands_as_a_stop() -> None:
    enclosure = slid()
    f = frame(enclosure)
    entry_y = f["cy"] + f["half_a"] + f["wall"] / 2
    far_y = f["cy"] - f["half_a"] - f["wall"] / 2

    # The entry wall's top is the groove's floor.
    assert has_material(enclosure.base, f["cx"], entry_y, f["top"] - CLEARANCE - 0.1)
    assert not has_material(
        enclosure.base, f["cx"], entry_y, f["top"] - CLEARANCE + 0.1
    )
    # The far wall rises to the top of the long walls.
    assert has_material(enclosure.base, f["cx"], far_y, f["top"] + LID_MM + 0.5)
    # The long walls stand at the entry end too, to hold the lid there.
    assert has_material(
        enclosure.base,
        f["cx"] + f["half_c"] + GROOVE_DEPTH_MM + 0.6,
        entry_y,
        f["top"] + LID_MM + 0.5,
    )


def test_the_lid_sits_in_the_grooves_with_the_clearance_all_round() -> None:
    enclosure = slid()
    f = frame(enclosure)
    lid = workplane_shape(enclosure.lid).BoundingBox()

    # Across: the cavity and two grooves, less a clearance each side, and the
    # detent bumps, which stand 0.7 mm beyond the plate's edge.
    assert lid.xlen == pytest.approx(2 * (f["half_c"] + GROOVE_DEPTH_MM + 0.5))
    # Along: from a clearance short of the far wall to the entry wall's face.
    assert lid.ymax == pytest.approx(f["cy"] + f["half_a"] + f["wall"])
    assert lid.ymin == pytest.approx(f["cy"] - f["half_a"] + CLEARANCE)
    assert lid.zmin == pytest.approx(f["top"])
    assert lid.zmax == pytest.approx(f["top"] + LID_MM)
    # The plate's edge is in the groove, and touches nothing.
    edge_x = f["cx"] + f["half_c"] + GROOVE_DEPTH_MM - CLEARANCE - 0.3
    assert has_material(enclosure.lid, edge_x, f["cy"] - f["half_a"] + 3.0, f["mid"])
    assert intersection_volume(solid(enclosure.base), solid(enclosure.lid)) < 1e-6
    assert len(enclosure.lid.solids().vals()) == 1


def test_each_edge_has_a_tongue_with_a_bump_that_clicks_into_a_dimple() -> None:
    enclosure = slid()
    slide = enclosure.slide
    assert slide is not None
    f = frame(enclosure)
    lid_far = f["cy"] - f["half_a"] + CLEARANCE
    entry = f["cy"] + f["half_a"] + f["wall"]
    mid = (lid_far + entry) / 2
    tongue_length = slide.detent.length_mm + 1.2
    bump_y = mid + tongue_length / 2 - 1.2

    for side in (1, -1):
        bump_x = f["cx"] + side * (f["half_c"] + 1.5)
        # The bump is on the lid, and a dimple in the groove's back wall takes it.
        assert has_material(enclosure.lid, bump_x, bump_y, f["mid"])
        dimple_x = f["cx"] + side * (f["half_c"] + 2.1)
        assert not has_material(enclosure.base, dimple_x, bump_y, f["mid"])
        assert has_material(enclosure.base, dimple_x, bump_y + 3.0, f["mid"])
        # The tongue has a slit on its inner side to bend into, and is joined
        # to the lid at its root.
        strip_x = f["cx"] + side * (f["half_c"] + 0.6)
        slit_x = f["cx"] + side * (f["half_c"] - 0.9)
        assert has_material(enclosure.lid, strip_x, mid, f["mid"])
        assert not has_material(enclosure.lid, slit_x, mid, f["mid"])
        assert has_material(enclosure.lid, slit_x, mid - tongue_length, f["mid"])


def test_detent_tongue_strain_is_within_the_limit() -> None:
    slide = slid().slide
    assert slide is not None
    detent = slide.detent

    assert detent.strain <= FLEXURE_STRAIN_LIMIT
    assert detent.thickness_mm == TONGUE_MM >= MINIMUM_WALL_MM
    expected = (
        3 * detent.thickness_mm * detent.deflection_mm / (2 * detent.length_mm**2)
    )
    assert detent.strain == pytest.approx(expected)


def test_the_lid_slides_out_clear_of_the_base_and_the_board() -> None:
    slide = slid().slide
    assert slide is not None

    # The travel check ran when the enclosure was built; the lid is one part
    # long, so a slide of its length takes it fully out.
    assert slide.travel_mm == slide.lid_length_mm > 50.0
    assert slide.clearance_mm == CLEARANCE


def test_a_lid_that_holds_a_display_is_refused() -> None:
    with_display = build_board_display_assembly(
        board=BOARD,
        display=DISPLAY,
        board_placement=Placement(),
        display_placement=Placement(z_mm=8.0),
        board_display_clearance_mm=1.0,
        connector_access_clearance_mm=2.0,
    )

    with pytest.raises(ValueError, match="a display needs a hinged or screwed lid"):
        build_enclosure(
            with_display,
            board=BOARD,
            display=DISPLAY,
            design=EnclosureDesign(lid_attachment="slide"),
        )


def cavity(width: float = 30.0, depth: float = 70.0) -> Cavity:
    return Cavity(
        center_x_mm=0.0,
        center_y_mm=0.0,
        width_mm=width,
        depth_mm=depth,
        floor_z_mm=2.0,
        top_z_mm=20.0,
        wall_mm=2.0,
    )


def opening(edge: str, top: float = 12.0) -> ConnectorCutoutParameters:
    return ConnectorCutoutParameters(
        edge=edge,  # type: ignore[arg-type]
        center_offset_mm=0.0,
        bottom_z_mm=top - 5.0,
        width_mm=10.0,
        height_mm=5.0,
    )


def plate_and_base(c: Cavity) -> tuple[cq.Workplane, cq.Workplane]:
    wall = c.wall_mm
    outer_w, outer_d = c.width_mm + 2 * wall, c.depth_mm + 2 * wall
    base = (
        cq.Workplane("XY")
        .box(outer_w, outer_d, c.top_z_mm, centered=(True, True, False))
        .cut(
            cq.Workplane("XY")
            .box(c.width_mm, c.depth_mm, c.top_z_mm, centered=(True, True, False))
            .translate((0, 0, c.floor_z_mm))
        )
    )
    lid = (
        cq.Workplane("XY")
        .box(outer_w, outer_d, LID_MM, centered=(True, True, False))
        .translate((0, 0, c.top_z_mm))
    )

    return base, lid


def slide_with(c: Cavity, **overrides):  # type: ignore[no-untyped-def]
    base, lid = plate_and_base(c)
    arguments = {
        "lid_mm": LID_MM,
        "clearance_mm": CLEARANCE,
        "hole_compensation_mm": 0.0,
        "openings": [],
        "hardware": {},
        **overrides,
    }

    return add_slide(base, lid, c, **arguments)


def test_the_entry_is_a_short_wall_with_no_opening() -> None:
    assert slide_entry(cavity(), []) == "positive_y"
    assert slide_entry(cavity(), [opening("positive_y")]) == "negative_y"
    # An opening in a long wall does not matter here.
    assert slide_entry(cavity(), [opening("positive_x")]) == "positive_y"

    with pytest.raises(ValueError, match="Both short walls carry an opening"):
        slide_entry(cavity(), [opening("positive_y"), opening("negative_y")])


def test_the_slide_runs_along_x_when_the_long_walls_face_y() -> None:
    wide = cavity(width=70.0, depth=30.0)
    *_, report = slide_with(wide)

    assert report.entry_edge == "positive_x"
    assert report.lid_length_mm == pytest.approx(70.0 + 2.0 - CLEARANCE)


def test_an_opening_that_would_cut_the_groove_is_refused() -> None:
    with pytest.raises(ValueError, match="would cut it"):
        slide_with(cavity(), openings=[opening("positive_x", top=19.5)])
    # Under the groove's floor it is fine, and on a short wall anything goes.
    slide_with(cavity(), openings=[opening("positive_x", top=12.0)])
    slide_with(cavity(), openings=[opening("negative_y", top=19.5)])


def test_a_lid_too_short_for_the_detent_tongues_is_refused() -> None:
    with pytest.raises(ValueError, match="detent tongues need"):
        slide_with(cavity(width=18.0, depth=16.0))


def test_a_part_in_the_lids_path_is_refused_by_name() -> None:
    post = cq.Solid.makeBox(8.0, 4.0, 7.0, pnt=cq.Vector(-4.0, 30.0, 14.0))

    with pytest.raises(ValueError, match="hits cap at"):
        slide_with(cavity(), hardware={"cap": post})


def test_clearance_is_limited_and_conflicting_options_refused() -> None:
    with pytest.raises(ValueError, match="slide_clearance_mm must be from 0 to 1 mm"):
        EnclosureDesign(lid_attachment="slide", slide_clearance_mm=0.0).validate()

    with pytest.raises(ValueError, match="slide_clearance_mm must be from 0 to 1 mm"):
        EnclosureDesign(lid_attachment="slide", slide_clearance_mm=1.5).validate()

    with pytest.raises(ValueError, match="no screws to countersink"):
        EnclosureDesign(lid_attachment="slide", countersunk_screws=True).validate()

    with pytest.raises(ValueError, match="no lip"):
        EnclosureDesign(lid_attachment="slide", locating_lip=True).validate()


def run_build(
    capsys: pytest.CaptureFixture[str], output: Path, *extra: str
) -> tuple[int, dict[str, object]]:
    exit_code = main(
        [
            "enclosure",
            "build",
            "--board",
            "raspberry_pi_pico_2",
            "--lid",
            "slide",
            "--review",
            "--output-directory",
            str(output),
            "--printer-profile",
            str(PRINTER_PROFILE),
            *extra,
        ]
    )

    return exit_code, json.loads(capsys.readouterr().out)


def test_cli_builds_a_sliding_lid_and_reports_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output = run_build(capsys, tmp_path)

    assert exit_code == 0
    parts = output["parts"]
    assert isinstance(parts, dict) and set(parts) == {"base", "lid"}
    slide = output["slide"]
    assert isinstance(slide, dict)
    assert slide["entry_wall"] == "positive_y"
    assert slide["detent"]["strain_percent"] <= 1.5
    assert output["validation_status"] == "PASS"
    record = json.loads((tmp_path / "enclosure.json").read_text())
    assert record["design"]["lid_attachment"] == "slide"
    assert record["design"]["slide_clearance_mm"] == 0.2
    review = output["review"]
    assert isinstance(review, dict) and review["passed"] is True
    fasteners = json.loads(Path(review["report"]).read_text())["fasteners"]
    assert fasteners["lid"] == "sliding"


def test_a_clearance_below_the_printers_recommendation_is_flagged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, _ = run_build(capsys, tmp_path, "--slide-clearance-mm", "0.1")

    assert exit_code == 0
    lid = json.loads(
        (tmp_path / "raspberry-pi-pico-2-enclosure-lid.metadata.json").read_text()
    )
    assert "lid_clearance_below_profile" in json.dumps(lid)


def test_vent_slots_stay_below_the_bulge_on_a_sliding_lid() -> None:
    tall = EnclosureDesign(lid_attachment="slide", bottom_clearance_mm=6.0)
    plain = build_enclosure(board_assembly(), board=BOARD, design=tall)
    vented = build_enclosure(
        board_assembly(), board=BOARD, design=replace(tall, vent_slots=2)
    )
    f = frame(vented)

    assert solid(vented.base).Volume() < solid(plain.base).Volume()
    # The wall is whole where the bulge and groove are.
    groove_wall = f["cx"] + f["half_c"] + GROOVE_DEPTH_MM + 0.6
    assert has_material(vented.base, groove_wall, f["cy"], f["top"] - 1.0)
    assert has_material(vented.base, groove_wall, f["cy"], f["mid"])

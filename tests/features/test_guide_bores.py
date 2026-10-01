"""A drill guide's bores: the file's sections, how the bores sit in the plate,
and what the built guide says about the chuck and the bit."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.features.guide import build_guide, guide_record
from zcad_core.features.guide_bores import MAXIMUM_BORES
from zcad_core.features.guide_file import (
    check_guide_data,
    guide_template,
    inspect_guide_file,
)
from zcad_core.profiles import load_printer_profile

PROFILE = load_printer_profile(
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
BUSHING = {
    "inner_diameter_mm": 4.2,
    "outer_diameter_mm": 8.0,
    "length_mm": 12.0,
    "source": "from my own bushings, measured with calipers",
}
FLANGED = {**BUSHING, "flange_diameter_mm": 11.0, "flange_thickness_mm": 3.0}


def block(
    width: float,
    depth: float,
    height: float,
    at: tuple[float, float, float] = (0, 0, 0),
) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(width, depth, height, centered=(True, True, False))
        .translate(at)
    )


@pytest.fixture(scope="module")
def slab(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 60 x 40 x 20 block with a flat top, to drill into."""

    path = tmp_path_factory.mktemp("slab") / "slab.step"
    cq.exporters.export(block(60, 40, 20), str(path))

    return path


def bore(
    identifier: str = "B1", x: float = 0.0, y: float = 0.0, **more: Any
) -> dict[str, Any]:
    return {"identifier": identifier, "x_mm": x, "y_mm": y, **more}


def data_for(slab: Path, *bores: dict[str, Any], **changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(guide_template(slab))
    data["bores"] = list(bores) if bores else [bore()]
    data["nest"]["depth_mm"] = 10.0
    data["plate"] = {}
    data.update(changes)

    return data


def inspect(directory: Path, data: dict[str, Any]) -> Any:
    path = directory / "guide.json"
    path.write_text(json.dumps(data))

    return inspect_guide_file(path, PROFILE)


def errors_of(directory: Path, data: dict[str, Any]) -> str:
    report, _, _ = inspect(directory, data)

    assert not report.valid, "expected errors"

    return "\n".join(report.errors)


def built(directory: Path, data: dict[str, Any]) -> Any:
    report, spec, part = inspect(directory, data)

    assert report.valid, report.errors
    assert spec is not None and part is not None

    return build_guide(spec, part, PROFILE), report


def inside(shape: cq.Shape, x: float, y: float, z: float) -> bool:
    return bool(cast(cq.Solid, shape).isInside(cq.Vector(x, y, z)))


# --- the sections --------------------------------------------------------------


def template() -> dict[str, Any]:
    return copy.deepcopy(guide_template())


def test_the_template_has_a_drill_and_a_bore_and_is_valid() -> None:
    data = template()

    assert data["drill"]["diameter_mm"] == 4.0
    assert [b["identifier"] for b in data["bores"]] == ["B1"]
    assert check_guide_data(data).valid


@pytest.mark.parametrize(
    ("change", "expect"),
    [
        (lambda d: d.pop("drill"), "drill is missing"),
        (lambda d: d["drill"].update(diameter_mm=0.1), "drill.diameter_mm"),
        (lambda d: d["drill"].update(chuck_diameter_mm=2.0), "wider than the bit"),
        (lambda d: d["drill"].update(depth_mm=0), "drill.depth_mm"),
        (lambda d: d["bores"][0].pop("identifier"), "bores[0].identifier"),
        (lambda d: d["bores"][0].pop("x_mm"), "bores[0].x_mm is missing"),
        (lambda d: d["bores"][0].update(kind="laser"), "kind must be one of"),
        (lambda d: d["bores"][0].update(tilt_about="x"), "tilt_about and tilt_deg"),
        (
            lambda d: d["bores"][0].update(tilt_about="z", tilt_deg=10),
            "tilt_about must be one of",
        ),
        (
            lambda d: d["bores"][0].update(tilt_about="x", tilt_deg=60),
            "tilt_deg is 60",
        ),
        (lambda d: d["bores"][0].update(allow_exit="yes"), "allow_exit"),
        (lambda d: d["bores"].append(bore("B1", 5, 5)), "identifiers must be unique"),
        (lambda d: d.update(bores="all"), "bores must be a list"),
        (
            lambda d: d.update(bores=[bore(f"B{i}") for i in range(MAXIMUM_BORES + 1)]),
            "at most",
        ),
        (lambda d: d["bores"][0].update(kind="bushing"), "bushing is missing"),
    ],
)
def test_a_bore_section_that_cannot_be_right_is_refused(
    change: Any, expect: str
) -> None:
    data = template()
    change(data)
    report = check_guide_data(data)

    assert not report.valid
    assert any(expect in error for error in report.errors), report.errors


@pytest.mark.parametrize(
    ("change", "expect"),
    [
        (lambda b: b.pop("source"), "bushing.source"),
        (lambda b: b.update(source=" "), "bushing.source"),
        (lambda b: b.update(outer_diameter_mm=4.0), "must exceed its inner"),
        (lambda b: b.update(flange_diameter_mm=11.0), "both flange_diameter_mm"),
        (
            lambda b: b.update(flange_diameter_mm=7.0, flange_thickness_mm=2.0),
            "wider than its outer",
        ),
        (lambda b: b.update(length_mm=1.0), "bushing.length_mm"),
    ],
)
def test_a_bushing_that_cannot_be_right_is_refused(change: Any, expect: str) -> None:
    data = template()
    bushing = copy.deepcopy(BUSHING)
    change(bushing)
    data["bushing"] = bushing
    data["bores"][0]["kind"] = "bushing"
    report = check_guide_data(data)

    assert any(expect in error for error in report.errors), report.errors


def test_a_drill_wider_than_the_bushing_is_refused() -> None:
    data = template()
    data["bushing"] = {**BUSHING, "inner_diameter_mm": 3.0}
    data["bores"][0]["kind"] = "bushing"

    assert any("will not pass" in e for e in check_guide_data(data).errors)


def test_a_tilted_flanged_bushing_is_refused() -> None:
    data = template()
    data["bushing"] = FLANGED
    data["bores"][0].update(kind="bushing", tilt_about="y", tilt_deg=15)

    assert any("flat seat" in e for e in check_guide_data(data).errors)


def test_a_tilted_bushing_without_a_flange_is_allowed() -> None:
    data = template()
    data["bushing"] = BUSHING
    data["bores"][0].update(kind="bushing", tilt_about="y", tilt_deg=15)

    assert check_guide_data(data).valid


def test_the_bores_need_a_printer_profile_to_be_checked(
    slab: Path, tmp_path: Path
) -> None:
    path = tmp_path / "guide.json"
    path.write_text(json.dumps(data_for(slab)))
    report, _, _ = inspect_guide_file(path)

    assert any("printer profile" in error for error in report.errors)


# --- placing the bores -----------------------------------------------------------


def test_a_bore_is_placed_and_sized_for_the_drill(slab: Path, tmp_path: Path) -> None:
    report, spec, part = inspect(tmp_path, data_for(slab, bore(x=10.0, y=-5.0)))

    assert report.valid, report.errors
    assert report.part is not None
    placed = report.part["bores"][0]

    assert placed["entry_mm"] == [10.0, -5.0]
    # The drill's 4 mm, the sliding clearance each side, and the profile's
    # allowance for a printer that prints holes small.
    assert placed["hole_diameter_mm"] == pytest.approx(4 + 2 * 0.2 + 0.2)
    assert placed["guide_length_mm"] == pytest.approx(6.0)
    assert spec is not None and part is not None


def test_a_bushing_pocket_is_sized_for_a_press_fit(slab: Path, tmp_path: Path) -> None:
    data = data_for(slab, bore(kind="bushing"), bushing=BUSHING)
    report, _, _ = inspect(tmp_path, data)

    assert report.valid, report.errors
    assert report.part is not None
    placed = report.part["bores"][0]

    assert placed["pocket_diameter_mm"] == pytest.approx(8.0 + 2 * 0.05 + 0.2)
    assert placed["hole_diameter_mm"] == pytest.approx(4.2 + 0.2)


def test_the_plate_is_sized_to_the_bores_when_the_file_leaves_it_out(
    slab: Path, tmp_path: Path
) -> None:
    printed, _, _ = inspect(tmp_path, data_for(slab))
    bushed, _, _ = inspect(
        tmp_path, data_for(slab, bore(kind="bushing"), bushing=FLANGED)
    )

    assert printed.part is not None and bushed.part is not None
    # 1.5 drill diameters of 4 mm; and a 12 mm bushing less its 3 mm flange.
    assert printed.part["plate_thickness_mm"] == pytest.approx(6.0)
    assert bushed.part["plate_thickness_mm"] == pytest.approx(9.0)


def test_a_tilted_bore_needs_less_plate_along_the_vertical(
    slab: Path, tmp_path: Path
) -> None:
    report, _, _ = inspect(
        tmp_path, data_for(slab, bore(tilt_about="y", tilt_deg=30.0))
    )

    assert report.part is not None
    assert report.part["plate_thickness_mm"] == pytest.approx(
        math.ceil(6.0 * math.cos(math.radians(30)) / 0.5) * 0.5
    )


def test_a_plate_too_thin_for_the_bores_is_refused(slab: Path, tmp_path: Path) -> None:
    data = data_for(slab)
    data["plate"] = {"thickness_mm": 4.0}

    assert "the bores need 6 mm" in errors_of(tmp_path, data)


def test_a_bore_near_the_edge_of_the_part_is_refused(
    slab: Path, tmp_path: Path
) -> None:
    message = errors_of(tmp_path, data_for(slab, bore(x=29.0)))

    assert "B1 stands at (29, 0)" in message
    assert "inside the part's edge" in message


def test_a_bore_off_the_part_is_refused(slab: Path, tmp_path: Path) -> None:
    assert "stands at (45, 0)" in errors_of(tmp_path, data_for(slab, bore(x=45.0)))


def test_a_tilt_that_throws_the_bores_head_off_the_plate_is_refused(
    slab: Path, tmp_path: Path
) -> None:
    """The head of a bore leans away from its foot across the plate: a steep
    tilt near an edge runs the head off it."""

    data = data_for(slab, bore(x=-26.0, tilt_about="y", tilt_deg=45.0))
    data["drill"]["depth_mm"] = 6.0
    message = errors_of(tmp_path, data)

    assert "top, at" in message and "plate's edge" in message


def test_a_drill_that_would_come_out_of_the_underside_is_refused(
    slab: Path, tmp_path: Path
) -> None:
    data = data_for(slab, bore())
    data["drill"]["depth_mm"] = 25.0

    assert "come out of the underside" in errors_of(tmp_path, data)

    data["bores"][0]["allow_exit"] = True
    report, _, _ = inspect(tmp_path, data)

    assert report.valid, report.errors


def test_a_tilted_drill_that_breaks_out_of_the_side_is_refused(
    slab: Path, tmp_path: Path
) -> None:
    data = data_for(slab, bore(x=20.0, tilt_about="y", tilt_deg=40.0))
    data["drill"]["depth_mm"] = 14.0

    assert "break out of the side" in errors_of(tmp_path, data)


def test_bores_too_close_leave_too_little_plate(slab: Path, tmp_path: Path) -> None:
    message = errors_of(tmp_path, data_for(slab, bore("B1", 0), bore("B2", 5.0)))

    assert "Bores B1 and B2 leave" in message
    assert "least wall" in message

    report, _, _ = inspect(tmp_path, data_for(slab, bore("B1", -10), bore("B2", 10)))

    assert report.valid, report.errors


def test_a_flange_must_clear_its_neighbour(slab: Path, tmp_path: Path) -> None:
    data = data_for(
        slab,
        bore("B1", -5, kind="bushing"),
        bore("B2", 5, kind="bushing"),
        bushing=FLANGED,
    )

    assert "Bores B1 and B2 leave" in errors_of(tmp_path, data)


def test_every_problem_is_reported_at_once(slab: Path, tmp_path: Path) -> None:
    message = errors_of(tmp_path, data_for(slab, bore("B1", 29.0), bore("B2", 45.0)))

    assert "B1" in message and "B2" in message


def test_a_steep_tilt_and_a_printed_bore_are_warned_of(
    slab: Path, tmp_path: Path
) -> None:
    report, _, _ = inspect(
        tmp_path, data_for(slab, bore(tilt_about="x", tilt_deg=25.0))
    )

    assert report.valid, report.errors
    assert any("roughest" in w for w in report.warnings)
    assert any("wears" in w for w in report.warnings)


# --- the built guide ----------------------------------------------------------------


def test_the_bore_is_cut_through_the_plate(slab: Path, tmp_path: Path) -> None:
    guide, _ = built(tmp_path, data_for(slab, bore(x=10.0)))
    solid = guide.body.val()

    assert guide.passed, (guide.checks, guide.problems)
    assert not inside(solid, 10.0, 0.0, 3.0)
    # The hole is 4.6 mm across: beside it, and well past it, the plate stands.
    assert not inside(solid, 12.2, 0.0, 3.0)
    assert inside(solid, 12.6, 0.0, 3.0)
    assert inside(solid, 14.0, 0.0, 3.0)


def test_a_tilted_bore_leans_across_the_plate(slab: Path, tmp_path: Path) -> None:
    """Tilted 30 degrees about Y, the drill's lower end leans toward +X, so up
    through the plate the bore sits toward -X."""

    guide, _ = built(tmp_path, data_for(slab, bore(tilt_about="y", tilt_deg=30.0)))
    solid = guide.body.val()
    thickness = guide.plate_thickness_mm
    shift = thickness * math.tan(math.radians(30))

    assert guide.passed, (guide.checks, guide.problems)
    assert not inside(solid, 0.0, 0.0, 0.2)
    assert not inside(solid, -shift, 0.0, thickness - 0.2)
    assert inside(solid, shift, 0.0, thickness - 0.2)


def test_a_vertical_bore_lets_the_chuck_stand_on_the_plate(
    slab: Path, tmp_path: Path
) -> None:
    guide, _ = built(tmp_path, data_for(slab))
    (planned,) = guide.bores

    assert planned.chuck_standoff_mm == 0.0
    # Up from the plate (0), through its 6 mm, and the 6 mm depth.
    assert planned.bit_needed_mm == pytest.approx(12.0)


def test_a_tilt_holds_the_chuck_up_by_its_radius_times_the_tangent(
    slab: Path, tmp_path: Path
) -> None:
    data = data_for(slab, bore(tilt_about="x", tilt_deg=30.0))
    data["drill"]["chuck_diameter_mm"] = 14.0
    guide, _ = built(tmp_path, data)
    (planned,) = guide.bores

    expected = 7.0 * math.tan(math.radians(30))

    assert planned.chuck_standoff_mm == pytest.approx(expected, abs=0.25)
    cosine = math.cos(math.radians(30))
    assert planned.bit_needed_mm == pytest.approx(
        planned.chuck_standoff_mm + guide.plate_thickness_mm / cosine + 6.0, abs=0.05
    )


def test_a_flange_holds_the_chuck_up_by_its_thickness(
    slab: Path, tmp_path: Path
) -> None:
    data = data_for(slab, bore(kind="bushing"), bushing=FLANGED)
    data["drill"]["chuck_diameter_mm"] = 20.0
    guide, _ = built(tmp_path, data)
    (planned,) = guide.bores

    assert planned.chuck_standoff_mm == pytest.approx(3.0, abs=0.15)


def test_a_neighbours_flange_holds_a_wide_chuck_up(slab: Path, tmp_path: Path) -> None:
    near = data_for(
        slab,
        bore("B1", -8, kind="bushing"),
        bore("B2", 8, kind="bushing"),
        bushing=FLANGED,
    )
    near["drill"]["chuck_diameter_mm"] = 20.0
    guide, _ = built(tmp_path, near)

    assert all(p.chuck_standoff_mm == pytest.approx(3.0, abs=0.15) for p in guide.bores)


def test_a_bit_that_does_not_stand_out_far_enough_is_refused(
    slab: Path, tmp_path: Path
) -> None:
    data = data_for(slab)
    data["drill"]["stickout_mm"] = 10.0
    guide, _ = built(tmp_path, data)

    assert not guide.passed
    assert guide.checks["bit_reaches_depth"] is False
    assert any("must stand 12 mm out of its chuck" in p for p in guide.problems)


def test_without_a_stickout_the_reach_is_reported_not_refused(
    slab: Path, tmp_path: Path
) -> None:
    data = data_for(slab)
    del data["drill"]["stickout_mm"]
    guide, _ = built(tmp_path, data)

    assert guide.passed
    assert guide.bores[0].bit_needed_mm == pytest.approx(12.0)


def test_the_play_is_a_bound_from_the_clearances(slab: Path, tmp_path: Path) -> None:
    printed, _ = built(tmp_path, data_for(slab))
    entry, tip = printed.play["B1"]

    # Nest clearance 0.2 + bore clearance 0.2; the tip adds the drill's tilt in
    # a 6 mm bore over a 6 mm depth.
    assert entry == pytest.approx(0.4)
    assert tip == pytest.approx(0.4 + 6.0 * 2 * 0.2 / 6.0)

    bushed, _ = built(tmp_path, data_for(slab, bore(kind="bushing"), bushing=BUSHING))
    entry, _ = bushed.play["B1"]

    # Nest 0.2, the press fit's 0.05, and the drill in the bushing (4.2 - 4) / 2.
    assert entry == pytest.approx(0.2 + 0.05 + 0.1)


def test_the_record_carries_the_bores_and_says_the_figures_are_the_users(
    slab: Path, tmp_path: Path
) -> None:
    guide, _ = built(tmp_path, data_for(slab, bore(kind="bushing"), bushing=BUSHING))
    record = guide_record(guide, {})

    assert record["bushing"]["figures_from"].startswith("the user's file")
    assert record["bushing"]["source"] == BUSHING["source"]
    assert (
        record["bores"][0]["worst_case_tip_play_mm"]
        >= record["bores"][0]["worst_case_entry_play_mm"]
    )
    assert record["plate"]["sized_by"] == "bores"
    assert record["verified"] is False


def test_a_part_with_a_hole_in_it_still_gets_a_clean_bore(
    tmp_path: Path,
) -> None:
    plate = block(60, 40, 20).faces(">Z").workplane().pushPoints([(-20, 0)]).hole(6)
    step = tmp_path / "plate.step"
    cq.exporters.export(plate, str(step))
    guide, _ = built(tmp_path, data_for(step, bore(x=10.0)))

    assert guide.passed, (guide.checks, guide.problems)

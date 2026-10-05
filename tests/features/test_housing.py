"""Wearable housings: the housing file, a cradle for a sealed device, a case for a
board."""

from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.housing import (
    build_housing,
    corner_radius_limit_mm,
    print_oriented,
    require_fits_bed,
)
from zcad_core.features.housing_file import (
    check_housing_data,
    check_housing_file,
    housing_template,
    load_housing,
)
from zcad_core.hardware import board_template
from zcad_core.hardware.wearables import capture_template
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PROFILE = load_printer_profile(PRINTER_PATH)


def capture_data(device: str = "dexcom-g7", **changes: Any) -> dict[str, Any]:
    data = capture_template(device)
    del data["needs_review"]
    data.update(
        measured_by="A. Tester",
        measured_on="2026-10-01",
        caliper="digital caliper, 0.01 mm",
        orientation="face up",
        source="one device, three passes",
        edge_features_checked=True,
    )

    for feature in data["edge_features"]:
        feature["notes"] = "measured"

    data.update(changes)

    return data


def write_housing(
    directory: Path, style: str, input_file: Path, **changes: Any
) -> Path:
    data = housing_template(style, input_file)
    data["source"] = "a housing for tests"
    data.update(changes)
    path = directory / "housing.json"
    path.write_text(json.dumps(data))

    return path


def write_capture(directory: Path, **changes: Any) -> Path:
    path = directory / "capture.json"
    path.write_text(json.dumps(capture_data(**changes)))

    return path


def write_board(directory: Path) -> Path:
    data = copy.deepcopy(board_template())
    path = directory / "board.json"
    path.write_text(json.dumps(data))

    return path


def inside(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    return any(
        solid.isInside(cq.Vector(x, y, z))
        for solid in cast(cq.Shape, model.val()).Solids()
    )


@pytest.fixture(scope="module")
def g7(tmp_path_factory: pytest.TempPathFactory) -> Any:
    directory = tmp_path_factory.mktemp("g7")
    capture = write_capture(
        directory, outline={"type": "rounded_rectangle", "radius_mm": 4.0}
    )

    return build_housing(
        load_housing(write_housing(directory, "cradle", capture)), PROFILE
    )


@pytest.fixture(scope="module")
def case(tmp_path_factory: pytest.TempPathFactory) -> Any:
    directory = tmp_path_factory.mktemp("case")
    board = write_board(directory)
    path = write_housing(
        directory, "case", board, wall_mm=1.6, floor_mm=1.6, corner_radius_mm=2.0
    )

    return build_housing(load_housing(path), PROFILE)


# --- the file -----------------------------------------------------------------------------------


@pytest.mark.parametrize("style", ["cradle", "case"])
def test_each_templates_data_is_valid(style: str) -> None:
    report = check_housing_data(housing_template(style))

    assert report.valid, report.errors


@pytest.mark.parametrize(
    ("change", "expect"),
    [
        (lambda d: d.update(schema_version="9.0.0"), "schema_version"),
        (lambda d: d.update(units="inch"), "units must be 'mm'"),
        (lambda d: d.update(identifier="has space"), "identifier"),
        (lambda d: d.update(style="shell"), "style must be one of"),
        (lambda d: d.update(bogus=1), "Unknown field"),
        (lambda d: d.update(needs_review=["wall"]), "not reviewed"),
        (
            lambda d: d.update(board={"file": "b.json", "sha256": "0" * 64}),
            "remove 'board'",
        ),
        (lambda d: d["wearable"].update(sha256="abc"), "wearable.sha256"),
        (lambda d: d["wearable"].update(file=""), "wearable.file"),
        (lambda d: d.update(wall_mm=0.1), "wall_mm"),
        (lambda d: d.update(clearance_mm=5.0), "clearance_mm"),
        (lambda d: d.update(retention_edges=["north", "south"]), "at least three"),
        (lambda d: d.update(retention_edges=["north", "up", "east"]), "drawn from"),
    ],
)
def test_what_cannot_be_right_is_refused(change: Any, expect: str) -> None:
    data = housing_template("cradle")
    change(data)
    report = check_housing_data(data)

    assert not report.valid
    assert any(expect in error for error in report.errors), report.errors


def test_retention_edges_are_for_a_cradle() -> None:
    data = housing_template("case")
    data["retention_edges"] = ["north", "south", "east"]

    assert any(
        "retention_edges is for a cradle" in e for e in check_housing_data(data).errors
    )


def test_a_housing_with_no_source_is_warned_of() -> None:
    data = housing_template("cradle")
    del data["source"]

    assert any("No source" in w for w in check_housing_data(data).warnings)


def test_the_check_reads_what_the_housing_houses(tmp_path: Path) -> None:
    capture = write_capture(tmp_path)
    report = check_housing_file(write_housing(tmp_path, "cradle", capture), PROFILE)

    assert report.valid, report.errors
    assert report.summary is not None
    assert report.summary["houses"] == "Dexcom G7 sensor"


def test_a_housed_file_that_has_changed_since_is_refused(tmp_path: Path) -> None:
    capture = write_capture(tmp_path)
    path = write_housing(tmp_path, "cradle", capture)
    capture.write_text(json.dumps(capture_data(source="a different source")))
    report = check_housing_file(path, PROFILE)

    assert any(
        "has changed since the housing file named it" in e for e in report.errors
    )


def test_a_missing_input_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "housing.json"
    path.write_text(json.dumps(housing_template("cradle")))

    assert any("is missing" in e for e in check_housing_file(path, PROFILE).errors)


def test_a_wall_under_the_printers_minimum_is_refused(tmp_path: Path) -> None:
    capture = write_capture(tmp_path)
    report = check_housing_file(
        write_housing(tmp_path, "cradle", capture, wall_mm=0.8), PROFILE
    )

    assert any("under the printer's 1.2 mm minimum wall" in e for e in report.errors)


def test_a_capture_that_cannot_be_used_is_refused_through_the_housing(
    tmp_path: Path,
) -> None:
    capture = write_capture(tmp_path, measured_by="")
    report = check_housing_file(write_housing(tmp_path, "cradle", capture), PROFILE)

    assert any("measured_by is required" in e for e in report.errors)


# --- a cradle -----------------------------------------------------------------------------------


def test_a_cradle_is_one_solid_that_leaves_room_for_the_device(g7: Any) -> None:
    assert g7.passed, g7.checks
    assert g7.checks == {
        "one_solid": True,
        "edge_features_open": True,
        "hooks_over_device": True,
        "nothing_proud_of_the_skin_face_unreported": True,
        "skin_edge_rounded": True,
    }
    assert set(g7.parts) == {"housing"}
    # A holder, not something worn: the floor covers the G7's skin side.
    assert g7.summary["skin_side_covered"] is True


@pytest.mark.parametrize("clearance", [0.8, 1.5])
def test_the_hook_holds_the_device_however_wide_the_clearance(
    tmp_path: Path, clearance: float
) -> None:
    # The hook is measured from the device's edge, so the clearance round the
    # device never eats into the 0.6 mm it stands in over the top face.
    capture = write_capture(tmp_path)
    housing = build_housing(
        load_housing(
            write_housing(tmp_path, "cradle", capture, clearance_mm=clearance)
        ),
        PROFILE,
    )

    assert housing.passed, housing.checks
    assert housing.checks["hooks_over_device"] is True
    # Just inside the device's north edge, under the hook's slope: solid.
    tab = next(t for t in housing.summary["tabs"] if t["edge"] == "north")
    tip_x = tab["offset_mm"] + 12.0 / 2 - 4.0 / 2
    assert inside(housing.parts["housing"], tip_x, 24.1 / 2 - 0.1, 4.7 + 0.15)


def test_a_device_whose_skin_side_must_stay_open_cannot_be_worn_in_a_cradle(
    tmp_path: Path,
) -> None:
    capture = write_capture(tmp_path)
    path = write_housing(
        tmp_path,
        "cradle",
        capture,
        wear=[{"kind": "lanyard", "cord_diameter_mm": 3.0, "source": "my cord"}],
    )

    with pytest.raises(ValueError, match="covers the skin side of a Dexcom G7"):
        build_housing(load_housing(path), PROFILE)


def test_the_skin_side_is_a_floor_and_the_face_is_left_open(g7: Any) -> None:
    tray = g7.parts["housing"]

    # Material under the device, none in the pocket, and nothing over the face.
    assert inside(tray, 0.0, 0.0, -0.6)
    assert not inside(tray, 0.0, 0.0, 2.0)
    assert not inside(tray, 0.0, 0.0, 6.5)
    # The wall stands at the device's edge, clear of it by the clearance.
    assert inside(tray, 13.7 + 0.3 + 0.6, 0.0, 2.0) or inside(
        tray, 0.0, 12.05 + 0.3 + 0.6, 2.0
    )


def test_each_tab_is_a_beam_fixed_at_one_end_with_a_hook_over_the_edge(g7: Any) -> None:
    tray = g7.parts["housing"]
    inner = 12.05 + 0.3

    # The north tab is 12 mm long about the middle, its free end at x = 6.
    assert inside(tray, 4.0, inner + 0.6, 4.7 + 0.1 + 0.5)
    # The hook stands in over the device's top edge, its underside above the face.
    assert inside(tray, 4.0, inner - 0.2, 4.7 + 0.1 + 0.2)
    assert not inside(tray, 4.0, inner - 0.2, 4.7 + 0.05)
    # The slit under the strip and the slit at the free end are open.
    assert not inside(tray, 0.0, inner + 0.6, 4.7 + 0.1 + 1.0 - 2.5 - 0.4)
    assert not inside(tray, 6.4, inner + 0.6, 4.5)


def test_the_tabs_strain_is_the_end_loaded_cantilevers_and_within_the_limit(
    g7: Any,
) -> None:
    tab = g7.summary["tab"]

    assert tab["length_mm"] == 12.0 and tab["thickness_mm"] == 1.2
    assert tab["strain_percent"] == pytest.approx(0.75)
    assert tab["strain_percent"] <= tab["strain_limit_percent"]
    assert [t["edge"] for t in g7.summary["tabs"]] == ["north", "south", "east", "west"]


def test_a_wall_too_thick_for_its_tab_is_refused_with_the_length_it_needs(
    tmp_path: Path,
) -> None:
    capture = write_capture(tmp_path)
    spec = load_housing(write_housing(tmp_path, "cradle", capture, wall_mm=3.0))

    with pytest.raises(ValueError, match=r"needs a tab \d+ mm long"):
        build_housing(spec, PROFILE)


def test_an_edge_feature_gets_a_notch_and_the_tab_keeps_clear_of_it(
    tmp_path: Path,
) -> None:
    mobi = capture_data("tandem-mobi")
    mobi["edge_features"] = [
        {
            "identifier": "fill-port",
            "edge": "north",
            "center_offset_mm": 0.0,
            "width_mm": 8.0,
            "notes": "measured",
        },
        # The others, which a Mobi capture must list, away from the north edge.
        *(
            {
                "identifier": name,
                "edge": "south",
                "center_offset_mm": offset,
                "width_mm": 5.0,
                "notes": "measured",
            }
            for name, offset in (("button", -18.0), ("charging-contacts", 18.0))
        ),
    ]
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(mobi))
    housing = build_housing(
        load_housing(write_housing(tmp_path, "cradle", path)), PROFILE
    )
    tray = housing.parts["housing"]
    inner = 37.3 / 2 + 0.3
    north = next(t for t in housing.summary["tabs"] if t["edge"] == "north")

    assert housing.passed, housing.checks
    # The notch is open through the wall at the port's middle; the tab stands off it.
    assert not inside(tray, 0.0, inner + 0.6, 7.0)
    assert abs(north["offset_mm"]) >= (12.8 + 8.0) / 2 + 1.0


def test_an_edge_with_no_clear_place_for_a_tab_is_refused(tmp_path: Path) -> None:
    mobi = capture_data("tandem-mobi")
    mobi["edge_features"] = [
        {
            "identifier": name,
            "edge": "east",
            "center_offset_mm": offset,
            "width_mm": 6.0,
            "notes": "measured",
        }
        for name, offset in (
            ("fill-port", -10.0),
            ("button", 0.0),
            ("charging-contacts", 10.0),
        )
    ]
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(mobi))

    with pytest.raises(
        ValueError,
        match="No place on the east edge clears fill-port, button, charging-contacts",
    ):
        build_housing(load_housing(write_housing(tmp_path, "cradle", path)), PROFILE)

    # Three edges are enough, so the answer the message gives works.
    housing = build_housing(
        load_housing(
            write_housing(
                tmp_path, "cradle", path, retention_edges=["north", "south", "west"]
            )
        ),
        PROFILE,
    )

    assert housing.passed


def test_a_tab_that_would_cover_a_face_feature_is_refused(tmp_path: Path) -> None:
    tracker = capture_data(
        "custom",
        name="Acme tracker",
        face_features=[
            {
                "identifier": "button",
                "center_x_mm": 4.0,
                "center_y_mm": 16.0,
                "width_mm": 3.0,
                "depth_mm": 0.8,
            }
        ],
        body_readings={
            "length_mm": [41.2] * 3,
            "width_mm": [33.0] * 3,
            "thickness_mm": [9.8] * 3,
        },
        edge_features=[],
        mass={"value_g": 18.5, "source": "a scale"},
    )
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(tracker))

    with pytest.raises(
        ValueError, match="north tab's hook would cover the face feature button"
    ):
        build_housing(load_housing(write_housing(tmp_path, "cradle", path)), PROFILE)

    housing = build_housing(
        load_housing(
            write_housing(
                tmp_path, "cradle", path, retention_edges=["south", "east", "west"]
            )
        ),
        PROFILE,
    )

    assert housing.summary["face_features_left_open"] == ["button"]


# --- a case -------------------------------------------------------------------------------------


def test_a_case_is_a_snap_lid_enclosure_with_thin_walls(case: Any) -> None:
    assert case.passed, case.checks
    assert set(case.parts) == {"base", "lid"}
    assert case.summary["lid"] == "snap"
    assert case.summary["wall_mm"] == 1.6


def test_the_cases_outer_corners_are_rounded(case: Any, tmp_path: Path) -> None:
    base = case.parts["base"]
    box = cast(cq.Shape, base.val()).BoundingBox()
    middle = (box.zmin + box.zmax) / 2

    # The square corner is gone, and the wall's flat sides are still there.
    assert not inside(base, box.xmin + 0.05, box.ymin + 0.05, middle)
    assert inside(base, box.xmin + 0.5, (box.ymin + box.ymax) / 2 + 3.0, middle) or (
        inside(base, box.xmin + 0.5, (box.ymin + box.ymax) / 2 - 3.0, middle)
    )

    square = build_housing(
        load_housing(
            write_housing(
                tmp_path,
                "case",
                write_board(tmp_path),
                wall_mm=1.6,
                floor_mm=1.6,
                corner_radius_mm=0.0,
            )
        ),
        PROFILE,
    )
    sq_box = cast(cq.Shape, square.parts["base"].val()).BoundingBox()

    assert inside(square.parts["base"], sq_box.xmin + 0.05, sq_box.ymin + 0.05, middle)


def test_a_corner_radius_the_wall_cannot_carry_is_refused() -> None:
    assert corner_radius_limit_mm(1.2, 1.2) == pytest.approx(1.2, abs=0.01)
    assert corner_radius_limit_mm(1.6, 1.2) > corner_radius_limit_mm(1.2, 1.2)


def test_a_case_over_the_limit_is_refused_with_the_most_it_can_have(
    tmp_path: Path,
) -> None:
    spec = load_housing(
        write_housing(tmp_path, "case", write_board(tmp_path), corner_radius_mm=3.0)
    )

    with pytest.raises(ValueError, match=r"the most is 1\.20 mm"):
        build_housing(spec, PROFILE)


# --- the bed and the orientation --------------------------------------------------------------


def test_each_part_lies_on_the_bed(g7: Any, case: Any) -> None:
    for housing in (g7, case):
        for model in print_oriented(housing).values():
            assert cast(cq.Shape, model.val()).BoundingBox().zmin == pytest.approx(0.0)


def test_a_part_too_big_for_the_bed_is_refused(g7: Any) -> None:
    with pytest.raises(ValueError, match="printer's bed"):
        require_fits_bed(g7, {"build_volume_mm": {"x": 10, "y": 10, "z": 10}})

    require_fits_bed(g7, dict(PROFILE))


# --- the commands -------------------------------------------------------------------------------


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


def test_the_commands_write_check_and_build_a_cradle(tmp_path: Path) -> None:
    capture = write_capture(tmp_path)
    housing = tmp_path / "housing.json"
    code, _ = run(
        "housing",
        "template",
        "--style",
        "cradle",
        "--input-file",
        str(capture),
        "--output",
        str(housing),
    )

    assert code == 0

    code, report = run("housing", "check", str(housing))

    assert code == 0 and report["valid"] is True
    assert report["housing"]["houses"] == "Dexcom G7 sensor"

    code, output = run(
        "housing",
        "build",
        "--housing-file",
        str(housing),
        "--output-directory",
        str(tmp_path / "out"),
    )

    assert code == 0
    assert output["validation_status"] == "PASS"
    assert all(output["checks"].values())
    assert "no claim about skin" in output["not_claimed"][0]
    assert Path(output["parts"]["housing"]["stl_path"]).is_file()
    assert output["housing"]["tab"]["strain_percent"] == 0.75


def test_the_commands_build_a_case(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    housing = write_housing(tmp_path, "case", board, wall_mm=1.6, floor_mm=1.6)
    code, output = run(
        "housing",
        "build",
        "--housing-file",
        str(housing),
        "--output-directory",
        str(tmp_path / "out"),
    )

    assert code == 0
    assert output["validation_status"] == "PASS"
    assert set(output["parts"]) == {"base", "lid"}


def test_the_check_command_exits_1_for_a_housing_it_cannot_build(
    tmp_path: Path,
) -> None:
    capture = write_capture(tmp_path)
    housing = write_housing(tmp_path, "cradle", capture, wall_mm=0.8)
    code, report = run("housing", "check", str(housing))

    assert code == 1 and report["valid"] is False

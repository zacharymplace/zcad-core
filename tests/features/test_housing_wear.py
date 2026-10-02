"""Ways of wearing a housing: a strap, a band, a belt clip, an adhesive plate, a
lanyard."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.housing import WEAR_NOT_CLAIMED, build_housing
from zcad_core.features.housing_file import (
    check_housing_data,
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

STRAP = {
    "kind": "strap",
    "strap_width_mm": 20.0,
    "bar_diameter_mm": 1.8,
    "source": "my strap, measured",
}
BAND = {
    "kind": "band",
    "band_width_mm": 20.0,
    "band_thickness_mm": 2.0,
    "source": "my band, measured",
}
CLIP = {"kind": "clip", "belt_thickness_mm": 4.0, "source": "my belt, measured"}
ADHESIVE = {"kind": "adhesive", "patch_mm": [60.0, 45.0], "source": "my patch"}
LANYARD = {"kind": "lanyard", "cord_diameter_mm": 3.0, "source": "my cord"}

# The G7's cradle: a 27.4 x 24.1 x 4.7 mm device, a 4 mm radius, 0.3 mm of clearance
# and a 1.2 mm wall, so a body 30.4 x 27.1 mm, from z = -1.2 to 5.8.
XMAX, YMAX, ZMIN, ZMAX = 15.2, 13.55, -1.2, 5.8
MID_Z = (ZMIN + ZMAX) / 2


def write_capture(directory: Path, **changes: Any) -> Path:
    data = capture_template("dexcom-g7")
    del data["needs_review"]
    data.update(
        measured_by="A. Tester",
        measured_on="2026-10-01",
        caliper="digital caliper, 0.01 mm",
        orientation="face up",
        source="one device",
        edge_features_checked=True,
        outline={"type": "rounded_rectangle", "radius_mm": 4.0},
    )
    data.update(changes)
    path = directory / "capture.json"
    path.write_text(json.dumps(data))

    return path


def write_housing(
    directory: Path, style: str, input_file: Path, wear: list[Any], **changes: Any
) -> Path:
    data = housing_template(style, input_file)
    data["source"] = "a housing for tests"
    data["wear"] = wear
    data.update(changes)
    path = directory / "housing.json"
    path.write_text(json.dumps(data))

    return path


def cradle(tmp_path: Path, wear: list[Any], **capture: Any) -> Any:
    path = write_housing(tmp_path, "cradle", write_capture(tmp_path, **capture), wear)

    return build_housing(load_housing(path), PROFILE)


def inside(housing: Any, x: float, y: float, z: float) -> bool:
    model = housing.parts[next(iter(housing.parts))]

    return any(
        solid.isInside(cq.Vector(x, y, z))
        for solid in cast(cq.Shape, model.val()).Solids()
    )


# --- the file -----------------------------------------------------------------------------------


def test_the_template_adds_examples_that_are_refused_until_replaced() -> None:
    data = housing_template("cradle", None, ("strap", "lanyard"))
    report = check_housing_data(data)

    assert [e["kind"] for e in data["wear"]] == ["strap", "lanyard"]
    assert not report.valid
    assert sum("still the template's example" in e for e in report.errors) == 2

    for entry in data["wear"]:
        entry["source"] = "my own figures"

    assert check_housing_data(data).valid


@pytest.mark.parametrize(
    ("wear", "message"),
    [
        ("strap", "wear must be a list"),
        (["strap"], "wear[0] must be an object"),
        ([{"kind": "wheel", "source": "x"}], "wear[0].kind must be one of"),
        ([STRAP, STRAP], "strap is listed twice"),
        ([{**STRAP, "colour": "red"}], "unknown fields: colour"),
        ([{**STRAP, "strap_width_mm": 5.0}], "strap_width_mm"),
        ([{**STRAP, "bar_diameter_mm": 9.0}], "bar_diameter_mm"),
        (
            [{k: v for k, v in STRAP.items() if k != "bar_diameter_mm"}],
            "bar_diameter_mm is missing",
        ),
        ([{**STRAP, "source": ""}], "source must say where the figures came from"),
        ([{**STRAP, "source": "Example: my strap"}], "still the template's example"),
        ([{**ADHESIVE, "patch_mm": [60]}], "patch_mm must be"),
        ([{**ADHESIVE, "patch_mm": [5, 45]}], "patch_mm must be"),
        ([STRAP, BAND], "strap and band cannot be worn together"),
        ([ADHESIVE, CLIP], "adhesive and clip cannot be worn together"),
        ([ADHESIVE, BAND], "adhesive and band cannot be worn together"),
    ],
)
def test_a_way_of_wearing_that_cannot_be_right_is_refused(
    wear: Any, message: str
) -> None:
    data = housing_template("cradle")
    data["wear"] = wear
    report = check_housing_data(data)

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


@pytest.mark.parametrize("kinds", [[STRAP, LANYARD], [BAND, CLIP], [ADHESIVE, LANYARD]])
def test_ways_that_do_not_share_a_place_are_allowed(kinds: list[Any]) -> None:
    data = housing_template("cradle")
    data["wear"] = kinds

    assert check_housing_data(data).valid


# --- a strap ------------------------------------------------------------------------------------


def test_a_strap_gets_a_lug_at_each_end_with_a_hole_across_it(tmp_path: Path) -> None:
    worn = cradle(tmp_path, [STRAP])

    assert worn.passed, worn.checks

    for sign in (1.0, -1.0):
        end = XMAX * sign
        # The prongs flank the strap, a hole runs across them, the strap's channel is
        # open and a web joins the prongs to the body.
        for y in (11.0, -11.0):
            assert inside(worn, end + sign * 1.5, y, MID_Z + 1.9)
            assert not inside(worn, end + sign * 3.0, y, MID_Z)
        assert not inside(worn, end + sign * 2.5, 0.0, MID_Z)
        assert inside(worn, end + sign * 0.3, 0.0, MID_Z)

    summary = worn.summary["wear"][0]

    assert summary["kind"] == "strap" and summary["source"] == "my strap, measured"
    assert summary["bar_hole_mm"] == pytest.approx(2.1)


def test_a_strap_wider_than_the_housing_allows_is_refused_with_the_widest(
    tmp_path: Path,
) -> None:
    wide = {**STRAP, "strap_width_mm": 26.0}

    with pytest.raises(ValueError, match=r"the widest strap is 23\.1 mm"):
        cradle(tmp_path, [wide])


def test_lugs_for_a_bar_too_big_for_the_housing_are_refused(tmp_path: Path) -> None:
    fat = {**STRAP, "bar_diameter_mm": 4.0}

    with pytest.raises(ValueError, match="too thin for them"):
        cradle(tmp_path, [fat])


# --- a band -------------------------------------------------------------------------------------


def test_a_band_gets_an_ear_with_a_slot_at_each_end(tmp_path: Path) -> None:
    worn = cradle(tmp_path, [BAND])

    assert worn.passed, worn.checks

    for sign in (1.0, -1.0):
        end = XMAX * sign
        # The ear is on the skin plane; its slot, 3 mm wide, is open through it.
        assert inside(worn, end + sign * 0.8, 0.0, ZMIN + 1.0)
        assert not inside(worn, end + sign * 2.5, 0.0, ZMIN + 1.0)
        assert inside(worn, end + sign * 5.0, 0.0, ZMIN + 1.0)

    assert worn.summary["wear"][0]["slot_mm"] == [3.0, 21.0]


def test_a_band_wider_than_the_housing_allows_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"the widest band is 24\.1 mm"):
        cradle(tmp_path, [{**BAND, "band_width_mm": 26.0}])


# --- a belt clip --------------------------------------------------------------------------------


def test_a_belt_clip_is_a_spring_arm_under_the_back_with_a_gap_for_the_belt(
    tmp_path: Path,
) -> None:
    worn = cradle(tmp_path, [CLIP])
    gap = 4.0 + 0.4
    top = ZMIN - gap

    assert worn.passed, worn.checks
    # The post hangs from the back at one end, the arm runs under it, the nub on the
    # arm's free end stands toward the belt, and the gap is open.
    assert inside(worn, XMAX - 1.5, 0.0, ZMIN - 2.0)
    assert inside(worn, 0.0, 0.0, top - 0.6)
    assert inside(worn, XMAX - 3.0 - 16.4 + 1.0, 0.0, top + 0.5)
    assert not inside(worn, 0.0, 0.0, top + 2.0)
    clip = worn.summary["wear"][0]

    assert clip["belt_gap_mm"] == pytest.approx(gap)
    # The arm is as long as the housing allows, up to 18 mm.
    assert clip["arm_length_mm"] == pytest.approx(16.4)
    assert clip["strain_percent"] <= clip["strain_limit_percent"]


def test_a_housing_too_short_for_a_belt_clips_arm_is_refused_with_the_length(
    tmp_path: Path,
) -> None:
    data = capture_template("custom")
    del data["needs_review"]
    data.update(
        name="Small tracker",
        measured_by="A. Tester",
        measured_on="2026-10-01",
        caliper="digital caliper, 0.01 mm",
        orientation="face up",
        source="one device",
        edge_features_checked=True,
        edge_features=[],
        face_features=[],
        body_readings={
            "length_mm": [9.0] * 3,
            "width_mm": [24.1] * 3,
            "thickness_mm": [4.7] * 3,
        },
        mass={"value_g": 9.0, "source": "a scale"},
    )
    capture = tmp_path / "small.json"
    capture.write_text(json.dumps(data))
    path = write_housing(tmp_path, "cradle", capture, [CLIP])

    with pytest.raises(ValueError, match=r"needs an arm \d+ mm long"):
        build_housing(load_housing(path), PROFILE)


# --- an adhesive plate ----------------------------------------------------------------------------


def test_an_adhesive_plate_is_a_flat_flange_of_the_patchs_outline(
    tmp_path: Path,
) -> None:
    worn = cradle(tmp_path, [ADHESIVE])

    assert worn.passed, worn.checks
    # The flange reaches far past the housing at the skin plane, and no further than
    # the patch, and it is only as thick as the floor.
    assert inside(worn, 25.0, 0.0, ZMIN + 0.6)
    assert not inside(worn, 31.0, 0.0, ZMIN + 0.6)
    assert not inside(worn, 25.0, 0.0, ZMIN + 1.6)
    assert worn.summary["wear"][0]["plate_thickness_mm"] == 1.2


def test_a_patch_that_does_not_hold_the_housing_is_refused_with_the_size_it_needs(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match=r"it needs 34\.4 x 31\.1 mm"):
        cradle(tmp_path, [{**ADHESIVE, "patch_mm": [30.0, 30.0]}])


# --- a lanyard ----------------------------------------------------------------------------------


def test_a_lanyard_tab_has_a_hole_for_the_cord(tmp_path: Path) -> None:
    worn = cradle(tmp_path, [LANYARD])

    assert worn.passed, worn.checks
    # The tab stands off the +Y side on the skin plane; its hole is the cord and a mm.
    assert inside(worn, 0.0, YMAX + 0.5, ZMIN + 1.0)
    assert not inside(worn, 0.0, YMAX + 1.5 + 2.0, ZMIN + 1.0)
    assert worn.summary["wear"][0]["hole_mm"] == 4.0


# --- together, and the notes ------------------------------------------------------------------------


def test_ways_of_wearing_together_are_one_solid_and_all_listed(tmp_path: Path) -> None:
    worn = cradle(tmp_path, [STRAP, LANYARD])

    assert worn.passed and worn.checks["one_solid"] is True
    assert [w["kind"] for w in worn.summary["wear"]] == ["strap", "lanyard"]
    assert WEAR_NOT_CLAIMED in worn.notes


def test_a_housing_with_no_way_of_wearing_does_not_note_what_it_does_not_hold(
    tmp_path: Path,
) -> None:
    held = cradle(tmp_path, [])

    assert held.summary["wear"] == []
    assert WEAR_NOT_CLAIMED not in held.notes


def test_every_problem_with_the_ways_of_wearing_is_listed_at_once(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError) as caught:
        cradle(
            tmp_path,
            [{**STRAP, "strap_width_mm": 30.0}, {**ADHESIVE, "patch_mm": [30.0, 30.0]}],
        )

    message = str(caught.value)

    assert "widest strap" in message and "does not hold the" in message


# --- a case -------------------------------------------------------------------------------------


def case(tmp_path: Path, wear: list[Any], **changes: Any) -> Any:
    board = tmp_path / "board.json"
    board.write_text(json.dumps(board_template()))
    path = write_housing(
        tmp_path,
        "case",
        board,
        wear,
        wall_mm=1.6,
        floor_mm=1.6,
        corner_radius_mm=1.5,
        **changes,
    )

    return build_housing(load_housing(path), PROFILE)


def test_a_case_takes_a_strap_on_its_base(tmp_path: Path) -> None:
    worn = case(tmp_path, [STRAP])

    assert worn.passed, worn.checks
    assert worn.summary["wear"][0]["kind"] == "strap"


def test_a_case_too_small_for_its_patch_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not hold the"):
        case(tmp_path, [ADHESIVE])


# --- the commands -------------------------------------------------------------------------------


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


def test_the_commands_add_examples_and_build_once_they_are_replaced(
    tmp_path: Path,
) -> None:
    capture = write_capture(tmp_path)
    housing = tmp_path / "housing.json"
    code, _ = run(
        "housing",
        "template",
        "--style",
        "cradle",
        "--input-file",
        str(capture),
        "--wear",
        "strap",
        "--wear",
        "lanyard",
        "--output",
        str(housing),
    )

    assert code == 0

    code, report = run("housing", "check", str(housing))

    assert code == 1 and any("example" in e for e in report["errors"])

    data = json.loads(housing.read_text())

    for entry in data["wear"]:
        entry["source"] = "figures I measured"

    housing.write_text(json.dumps(data))
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
    assert [w["kind"] for w in output["housing"]["wear"]] == ["strap", "lanyard"]
    assert len(output["not_claimed"]) == 2
    assert "no figure for how well any way of wearing holds" in output["not_claimed"][1]

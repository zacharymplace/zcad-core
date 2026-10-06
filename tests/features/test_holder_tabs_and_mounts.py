"""An object holder's retaining tabs, and its pegboard and flat mounts.

The tabs are tried on a power brick with square corners, which they can hold, and on a remote with
6 mm corners, which they cannot: a hook would have to reach past the rounding to the flat top
further than a hook printed upright may overhang.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.features.holder import build_holder, require_fits_bed
from zcad_core.features.holder_file import (
    check_holder_data,
    holder_template,
    load_holder,
    load_holder_capture,
)
from zcad_core.features.holder_mounts import MAXIMUM_PEG_REACH_MM
from zcad_core.features.mounts import measured_strain_limit
from zcad_core.profiles import load_printer_profile

PROFILE = load_printer_profile(
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
BRICK: dict[str, Any] = {
    "schema_version": "1.0.0",
    "units": "mm",
    "device": "custom",
    "name": "USB power brick",
    "measured_by": "Test",
    "measured_on": "2026-10-06",
    "caliper": "digital caliper, 0.01 mm",
    "orientation": "label up, cable at the south edge",
    "source": "one brick, measured three times across each face",
    "body_readings": {
        "length_mm": [80.0] * 3,
        "width_mm": [50.0] * 3,
        "thickness_mm": [30.0] * 3,
    },
    "outline": "rectangle",
    "edge_features": [],
    "edge_features_checked": True,
    "face_features": [],
    "mass": {"value_g": 210.0, "source": "kitchen scale"},
}
SCREW = {
    "type": "screws",
    "head_diameter_mm": 8.0,
    "shank_diameter_mm": 4.0,
    "source": "a 4 x 30 mm wood screw, measured",
}
PEGBOARD = {
    "type": "pegboard",
    "pitch_mm": 25.4,
    "hole_diameter_mm": 6.35,
    "board_thickness_mm": 3.2,
    "source": "the garage board, measured",
}
TABS = {"type": "tabs", "overhang_mm": 0.6}


def write_holder(
    tmp_path: Path, capture: dict[str, Any] | None = None, **changes: Any
) -> Path:
    capture_path = tmp_path / "object.json"
    capture_path.write_text(json.dumps(capture or BRICK), encoding="utf-8")
    data = holder_template(capture_path)
    data.update(
        {
            "identifier": "BRICK_HOLDER",
            "name": "Power brick holder",
            "source": "the desk's power brick",
            "down_edge": "south",
            "mount": SCREW,
        }
    )
    data.update(changes)
    path = tmp_path / "holder.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    return path


def build(tmp_path: Path, capture: dict[str, Any] | None = None, **changes: Any) -> Any:
    spec = load_holder(write_holder(tmp_path, capture, **changes))

    return build_holder(spec, load_holder_capture(spec), PROFILE)


def with_edge(feature: dict[str, Any]) -> dict[str, Any]:
    capture = copy.deepcopy(BRICK)
    capture["edge_features"] = [feature]

    return capture


def test_tabs_hold_a_square_object_and_the_sides_climb_its_height(
    tmp_path: Path,
) -> None:
    holder = build(tmp_path, retention=TABS)

    assert holder.passed, holder.checks
    assert holder.checks["hooks_over_object"]
    assert [tab.side for tab in holder.tabs] == [-1.0, 1.0]
    tab = holder.tabs[0]
    # 0.2 clearance and 0.6 overhang; the tab reaches from 2 mm up the 50 mm side to 0.3 above.
    assert tab.hook_mm == pytest.approx(0.8)
    assert tab.reach_mm == pytest.approx(48.3)
    assert tab.strain < 0.015
    # The hooks stand 0.3 + 1.0 mm above the object's top.
    assert holder.size_mm[2] == pytest.approx(2.0 + 50.0 + 1.3)


def test_tabs_cannot_hold_an_object_with_well_rounded_corners(tmp_path: Path) -> None:
    rounded = copy.deepcopy(BRICK)
    rounded["outline"] = {"type": "rounded_rectangle", "radius_mm": 6.0}

    with pytest.raises(ValueError, match=r"reach 6\.8 mm in from the wall"):
        build(tmp_path, rounded, retention=TABS)

    slight = copy.deepcopy(BRICK)
    slight["outline"] = {"type": "rounded_rectangle", "radius_mm": 1.0}
    holder = build(tmp_path, slight, retention=TABS)

    assert holder.tabs[0].hook_mm == pytest.approx(1.8)
    assert holder.passed, holder.checks


def test_a_side_with_a_notch_takes_no_tab(tmp_path: Path) -> None:
    # A cable on the brick's east end, low on the right as it stands on its south edge.
    cable = {
        "identifier": "cable",
        "edge": "east",
        "center_offset_mm": -15.0,
        "width_mm": 6.0,
    }
    holder = build(tmp_path, with_edge(cable), retention=TABS)

    assert [tab.side for tab in holder.tabs] == [-1.0]
    assert holder.passed, holder.checks

    both = copy.deepcopy(BRICK)
    both["edge_features"] = [
        cable,
        {
            "identifier": "switch",
            "edge": "west",
            "center_offset_mm": -15.0,
            "width_mm": 6.0,
        },
    ]

    with pytest.raises(ValueError, match="Both sides carry a notch"):
        build(tmp_path, both, retention=TABS)


def test_a_thin_object_or_a_short_stiff_tab_is_refused(tmp_path: Path) -> None:
    thin = copy.deepcopy(BRICK)
    thin["body_readings"]["thickness_mm"] = [8.0] * 3

    with pytest.raises(ValueError, match=r"at least 11\.2 mm thick takes tabs"):
        build(tmp_path, thin, retention=TABS)

    short = copy.deepcopy(BRICK)
    short["body_readings"]["width_mm"] = [20.0] * 3

    # A 2.2 mm hook on a tab 18.3 mm long strains about 2 per cent.
    with pytest.raises(ValueError, match="over the 1.50% limit"):
        build(tmp_path, short, retention={"type": "tabs", "overhang_mm": 2.0})


def test_a_measured_strain_limit_decides_a_tab_when_a_build_asks(
    tmp_path: Path,
) -> None:
    short = copy.deepcopy(BRICK)
    short["body_readings"]["width_mm"] = [20.0] * 3
    retention = {"type": "tabs", "overhang_mm": 2.0}

    with measured_strain_limit(0.025, "coupon profile, version 1"):
        holder = build(tmp_path, short, retention=retention)

    assert holder.passed, holder.checks
    assert (
        holder.tabs[0].to_dict()["strain_limit_source"] == "coupon profile, version 1"
    )


def test_pegs_hang_on_the_pitch_through_the_holes(tmp_path: Path) -> None:
    holder = build(tmp_path, mount=PEGBOARD)

    assert holder.passed, holder.checks
    assert holder.checks["pegs_on_pitch"]
    left, right = holder.fixings
    # The largest square whose diagonal clears a 6.35 mm hole by 0.2 mm each side.
    assert left.size_mm == 4.2
    # The brick is 80 mm wide: three pitches fit between the pegs.
    assert right.x_mm - left.x_mm == pytest.approx(3 * 25.4)
    assert holder.mount.details["reach_behind_plate_mm"] == pytest.approx(
        3.2 + 0.5 + 4.2
    )
    require_fits_bed(holder, PROFILE)


def test_a_narrow_object_gets_a_plate_wide_enough_for_one_pitch(tmp_path: Path) -> None:
    pen = copy.deepcopy(BRICK)
    pen["body_readings"] = {
        "length_mm": [14.0] * 3,
        "width_mm": [120.0] * 3,
        "thickness_mm": [14.0] * 3,
    }
    holder = build(tmp_path, pen, mount=PEGBOARD)

    left, right = holder.fixings
    assert right.x_mm - left.x_mm == pytest.approx(25.4)
    assert holder.size_mm[0] >= 25.4 + 4.2
    assert holder.passed, holder.checks


def test_a_peg_that_would_overhang_too_far_or_be_too_thin_is_refused(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match=f"more than the {MAXIMUM_PEG_REACH_MM:g} mm"):
        build(tmp_path, mount={**PEGBOARD, "board_thickness_mm": 10.0})

    with pytest.raises(ValueError, match="under the 2.5 mm least"):
        build(tmp_path, mount={**PEGBOARD, "hole_diameter_mm": 3.5})


def test_a_flat_plate_is_as_large_as_its_pad(tmp_path: Path) -> None:
    pad = {
        "type": "flat",
        "width_mm": 100.0,
        "height_mm": 40.0,
        "source": "the pad's box",
    }
    holder = build(tmp_path, mount=pad)

    assert holder.fixings == ()
    assert holder.size_mm[0] == pytest.approx(100.0)
    assert holder.passed, holder.checks

    with pytest.raises(
        ValueError, match="pad is 60 mm tall and the back plate only 52"
    ):
        build(tmp_path, mount={**pad, "height_mm": 60.0})


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"mount": {**PEGBOARD, "source": ""}}, "where the pegboard figures came from"),
        ({"mount": {**PEGBOARD, "pitch_mm": 5.0}}, "outside 10 to 100"),
        ({"mount": {"type": "flat", "width_mm": 50.0}}, "mount.height_mm is missing"),
        ({"mount": {"type": "keyhole", "source": "x"}}, "mount has no source"),
        ({"retention": {"type": "clips"}}, "retention.type must be 'tabs'"),
        ({"retention": {"type": "tabs", "overhang_mm": 3.0}}, "outside 0.3 to 2"),
    ],
)
def test_mount_and_retention_figures_that_cannot_be_right_are_refused(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    data = json.loads(write_holder(tmp_path).read_text())
    data.update(change)

    assert any(message in error for error in check_holder_data(data).errors)


def test_the_command_builds_a_pegboard_holder_with_tabs(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = write_holder(tmp_path, mount=PEGBOARD, retention=TABS)
    output = tmp_path / "out"
    code = main(
        [
            "holder",
            "build",
            "--holder-file",
            str(path),
            "--output-directory",
            str(output),
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["validation_status"] == "PASS"
    record = json.loads((output / "holder.json").read_text())
    assert record["settings"]["mount"]["type"] == "pegboard"
    assert record["settings"]["mount"]["peg_mm"] == 4.2
    assert record["settings"]["retention"] == TABS
    assert [tab["side"] for tab in record["tabs"]] == ["left", "right"]
    assert record["fit_checks"]["hooks_over_object"]

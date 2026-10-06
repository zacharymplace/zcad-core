"""An object holder: a cup on a back plate for an object measured by a caliper capture.

The object here is a remote, measured as a custom capture: 150 x 45 x 20 mm with 6 mm corners,
a USB-C port on its west end, a lanyard loop on its north edge near that end, and its buttons on
its face near the same end. It stands on its west end, face out, so the port is in the floor, the
loop low on the left side, and the buttons behind the front.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.features.holder import (
    build_holder,
    holder_clearance,
    require_fits_bed,
    to_holder,
)
from zcad_core.features.holder_file import (
    check_holder_data,
    holder_template,
    inspect_holder_file,
    load_holder,
    load_holder_capture,
)
from zcad_core.hardware.wearables.capture import load_capture
from zcad_core.profiles import load_printer_profile

PROFILE = load_printer_profile(
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
CAPTURE: dict[str, Any] = {
    "schema_version": "1.0.0",
    "units": "mm",
    "device": "custom",
    "name": "TV remote",
    "measured_by": "Test",
    "measured_on": "2026-10-06",
    "caliper": "digital caliper, 0.01 mm",
    "orientation": "buttons up, USB-C port at the west end",
    "source": "one remote, measured three times across each face",
    "body_readings": {
        "length_mm": [150.0, 150.02, 149.98],
        "width_mm": [45.0, 45.01, 44.99],
        "thickness_mm": [20.0, 20.0, 20.01],
    },
    "outline": {"type": "rounded_rectangle", "radius_mm": 6.0},
    "edge_features": [
        {
            "identifier": "usb-c",
            "edge": "west",
            "center_offset_mm": 0.0,
            "width_mm": 9.0,
        },
        {
            "identifier": "lanyard",
            "edge": "north",
            "center_offset_mm": -60.0,
            "width_mm": 4.0,
        },
    ],
    "edge_features_checked": True,
    "face_features": [
        {
            "identifier": "buttons",
            "center_x_mm": -60.0,
            "center_y_mm": 0.0,
            "width_mm": 10.0,
            "depth_mm": 20.0,
        }
    ],
    "mass": {"value_g": 95.0, "source": "kitchen scale"},
}
SCREW = {
    "type": "screws",
    "head_diameter_mm": 8.0,
    "shank_diameter_mm": 4.0,
    "source": "a 4 x 30 mm wood screw, measured",
}


def write_holder(
    tmp_path: Path,
    capture: dict[str, Any] | None = None,
    **changes: Any,
) -> Path:
    capture_path = tmp_path / "remote.json"
    capture_path.write_text(json.dumps(capture or CAPTURE), encoding="utf-8")
    data = holder_template(capture_path)
    data.update(
        {
            "identifier": "REMOTE_HOLDER",
            "name": "TV remote holder",
            "source": "the living-room remote",
            "down_edge": "west",
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


def test_a_remote_on_its_end_gets_a_cup_that_fits_and_leaves_its_features_open(
    tmp_path: Path,
) -> None:
    holder = build(tmp_path)

    assert holder.passed, holder.checks
    assert (holder.placed.width_mm, holder.placed.height_mm) == pytest.approx((45, 150))
    # A third of 150 mm.
    assert holder.front_mm == pytest.approx(50.0)
    assert {(o.identifier, o.kind) for o in holder.openings} == {
        ("usb-c", "floor_slot"),
        ("lanyard", "side_notch"),
        ("buttons", "front_window"),
    }
    assert [fixing.kind for fixing in holder.fixings] == ["countersunk_screw"] * 2
    assert holder.notch
    width, depth, height = holder.size_mm
    # 45 + 2 x 0.2 clearance + 2 x 2 walls; 4 back + 0.4 + 20 + 2 front; 2 floor + 150.
    assert (width, depth, height) == pytest.approx((49.4, 26.4, 152.0), abs=0.01)
    require_fits_bed(holder, PROFILE)


@pytest.mark.parametrize(
    ("down", "face", "expected"),
    [
        # The capture's north-east corner, (75, 22.5), seen from the room.
        ("south", "out", (75.0, 45.0)),
        ("north", "out", (-75.0, 0.0)),
        ("west", "out", (-22.5, 150.0)),
        ("east", "out", (22.5, 0.0)),
        ("west", "wall", (22.5, 150.0)),
    ],
)
def test_the_object_stands_on_its_down_edge_seen_from_the_room(
    down: str, face: str, expected: tuple[float, float]
) -> None:
    capture = load_capture_from(CAPTURE)

    assert to_holder(capture, down, face, (75.0, 22.5)) == pytest.approx(expected)


def load_capture_from(data: dict[str, Any], directory: Path | None = None) -> Any:
    import tempfile

    folder = Path(directory or tempfile.mkdtemp())
    path = folder / "capture.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    return load_capture(path)


def test_a_face_toward_the_wall_with_face_features_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="buttons is on the object's face"):
        build(tmp_path, face="wall")

    plain = copy.deepcopy(CAPTURE)
    plain["face_features"] = []
    holder = build(tmp_path, plain, face="wall")
    (notch,) = [o for o in holder.openings if o.identifier == "lanyard"]

    # Turned to face the wall, the loop is on the right.
    assert notch.probe[0] > 0
    assert holder.passed


def test_the_front_climbs_a_third_and_no_higher_than_the_object(tmp_path: Path) -> None:
    assert build(tmp_path, holder={"front_mm": 30.0}).front_mm == 30.0

    with pytest.raises(ValueError, match="higher than the object's"):
        build(tmp_path, holder={"front_mm": 160.0})

    short = copy.deepcopy(CAPTURE)
    short["body_readings"]["length_mm"] = [24.0] * 3
    short["edge_features"][1]["center_offset_mm"] = -8.0
    short["face_features"][0]["center_x_mm"] = -2.0

    # A third of 24 mm is under the 10 mm least.
    assert build(tmp_path, short).front_mm == 10.0


def test_the_clearance_is_the_printers_the_files_or_a_measured_one(
    tmp_path: Path,
) -> None:
    spec = load_holder(write_holder(tmp_path))

    assert holder_clearance(spec, PROFILE, None)[0] == 0.2
    assert holder_clearance(spec, PROFILE, 0.15)[0] == pytest.approx(0.35)
    assert holder_clearance(spec, PROFILE, -0.5)[0] == 0.05

    looser = load_holder(
        write_holder(tmp_path, fit={"clearance_mm": 0.5, "source": "drops in freely"})
    )

    assert holder_clearance(looser, PROFILE, 0.15) == (
        0.5,
        "holder file: drops in freely",
    )


def test_a_plate_too_thin_for_its_fixing_is_refused_with_what_it_needs(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="at least 3.2 mm thick"):
        build(tmp_path, holder={"back_mm": 3.0})

    with pytest.raises(ValueError, match="keyhole needs a back plate at least 5.5"):
        build(tmp_path, mount={"type": "keyhole"}, holder={"back_mm": 4.0})

    holder = build(tmp_path, mount={"type": "keyhole"})

    assert [fixing.kind for fixing in holder.fixings] == ["keyhole"] * 2
    assert holder.passed, holder.checks


def test_a_narrow_object_takes_its_screws_one_above_the_other(tmp_path: Path) -> None:
    pen = copy.deepcopy(CAPTURE)
    pen["body_readings"] = {
        "length_mm": [140.0] * 3,
        "width_mm": [14.0] * 3,
        "thickness_mm": [14.0] * 3,
    }
    pen["outline"] = "rectangle"
    pen["edge_features"] = []
    pen["face_features"] = []
    holder = build(tmp_path, pen)
    (low, high) = holder.fixings

    assert low.x_mm == high.x_mm == 0.0
    assert high.z_mm - low.z_mm >= 16.0
    assert not holder.notch
    assert holder.passed, holder.checks


def test_a_port_across_the_whole_floor_is_refused(tmp_path: Path) -> None:
    wide = copy.deepcopy(CAPTURE)
    wide["edge_features"][0]["width_mm"] = 44.0

    with pytest.raises(ValueError, match="usb-c runs the floor's whole width"):
        build(tmp_path, wide)


def test_a_holder_taller_than_the_bed_is_refused(tmp_path: Path) -> None:
    tall = copy.deepcopy(CAPTURE)
    tall["body_readings"]["length_mm"] = [185.0] * 3

    with pytest.raises(ValueError, match="larger than the printer's"):
        require_fits_bed(build(tmp_path, tall), PROFILE)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"down_edge": "up"}, "down_edge must be one of"),
        ({"face": "sideways"}, "face must be one of"),
        ({"mount": {**SCREW, "source": " "}}, "mount.source must say"),
        ({"mount": {**SCREW, "head_diameter_mm": 3.5}}, "must be wider than the shank"),
        ({"mount": {"type": "nails"}}, "mount.type must be one of"),
        ({"fit": {"clearance_mm": 0.4}}, "fit.source must say"),
        ({"needs_review": "fill in"}, "still carries needs_review"),
        ({"colour": "red"}, "Unknown field"),
    ],
)
def test_a_holder_file_that_cannot_be_right_is_refused(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    data = json.loads(write_holder(tmp_path).read_text())
    data.update(change)

    assert any(message in error for error in check_holder_data(data).errors)


def test_a_capture_changed_or_not_custom_is_refused(tmp_path: Path) -> None:
    path = write_holder(tmp_path)
    (tmp_path / "remote.json").write_text(
        json.dumps({**CAPTURE, "name": "another remote"}), encoding="utf-8"
    )
    report, _, capture = inspect_holder_file(path)

    assert capture is None
    assert any("has changed since" in error for error in report.errors)

    other = {**CAPTURE, "device": "dexcom-g7"}
    other["body_readings"] = {
        "length_mm": [27.8] * 3,
        "width_mm": [23.0] * 3,
        "thickness_mm": [4.6] * 3,
    }
    other["edge_features"] = []
    other["face_features"] = []
    other["outline"] = "rectangle"
    del other["name"]
    path = write_holder(tmp_path, other)
    report, _, capture = inspect_holder_file(path)

    assert capture is None
    assert any("takes a custom device's capture" in e for e in report.errors), report


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, Any]:
    code = main(list(args))
    out = capsys.readouterr().out

    return code, json.loads(out) if out else None


def test_the_commands_write_check_and_build_a_holder(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    capture = tmp_path / "remote.json"
    capture.write_text(json.dumps(CAPTURE), encoding="utf-8")
    template = tmp_path / "template.json"
    code, report = run(
        capsys,
        "holder",
        "template",
        "--capture",
        str(capture),
        "--output",
        str(template),
    )

    assert code == 0
    named = json.loads(template.read_text())["object"]
    assert named["sha256"] == hashlib.sha256(capture.read_bytes()).hexdigest()

    path = write_holder(tmp_path)
    code, report = run(capsys, "holder", "check", str(path))

    assert code == 0, report
    assert report["object"]["name"] == "TV remote"
    assert report["holder"]["openings"] == ["usb-c", "lanyard", "buttons"]

    output = tmp_path / "out"
    code, report = run(
        capsys,
        "holder",
        "build",
        "--holder-file",
        str(path),
        "--output-directory",
        str(output),
    )

    assert code == 0
    assert report["validation_status"] == "PASS"
    record = json.loads((output / "holder.json").read_text())
    assert record["verified"] is False
    assert record["object"]["mass_g"] == 95.0
    assert record["settings"]["clearance_from"] == "printer profile sliding clearance"
    assert (output / "remote-holder-holder.stl").is_file()


def test_the_check_names_what_stops_a_build(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = write_holder(tmp_path, holder={"back_mm": 3.0})
    code, report = run(capsys, "holder", "check", str(path))

    assert code == 1
    assert any("at least 3.2 mm thick" in error for error in report["errors"])

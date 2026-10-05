"""Caliper captures of wearable devices: what the check refuses and allows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.hardware.wearables import (
    capture_template,
    check_capture_data,
    load_capture,
)


def filled(template: str = "tandem-mobi", **changes: Any) -> dict[str, Any]:
    """A template with its example values replaced, as a person would."""

    data = capture_template(template)
    del data["needs_review"]
    data.update(
        measured_by="A. Tester",
        measured_on="2026-10-01",
        caliper="digital caliper, 0.01 mm",
        orientation="buttons up, fill port at the east end",
        source="one device, three passes",
        edge_features_checked=True,
    )
    for feature in data["edge_features"]:
        feature["notes"] = "measured from the south end"
    data["edge_features"] = [
        {**feature, "center_offset_mm": offset}
        for feature, offset in zip(
            data["edge_features"], (-10.0, 0.0, 10.0), strict=False
        )
    ]
    data.update(changes)
    return data


def test_the_template_is_refused_until_its_examples_are_replaced() -> None:
    check = check_capture_data(capture_template("tandem-mobi"))

    assert not check.valid
    assert any("needs_review" in error for error in check.errors)
    assert any("edge_features_checked" in error for error in check.errors)


def test_a_filled_capture_is_valid_and_uses_the_median_reading(tmp_path: Path) -> None:
    data = filled(
        body_readings={
            "length_mm": [51.20, 51.24, 51.90],
            "width_mm": [37.30, 37.31, 37.28],
            "thickness_mm": [14.20, 14.22, 14.21],
        }
    )
    path = tmp_path / "mobi.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    check = check_capture_data(data)
    capture = load_capture(path)

    assert check.valid
    # The 51.90 slip moves nothing, but the spread is called out.
    assert capture.length_mm == pytest.approx(51.24)
    assert any("length_mm readings spread 0.70 mm" in w for w in check.warnings)
    assert [f.identifier for f in capture.edge_features] == [
        "fill-port",
        "button",
        "charging-contacts",
    ]


def test_a_size_far_from_the_published_one_is_refused_or_questioned() -> None:
    swapped = filled(
        body_readings={
            "length_mm": [37.3] * 3,
            "width_mm": [51.3] * 3,
            "thickness_mm": [14.2] * 3,
        }
    )
    off = filled(
        body_readings={
            "length_mm": [54.0] * 3,
            "width_mm": [37.3] * 3,
            "thickness_mm": [14.2] * 3,
        }
    )

    assert any("swapped" in error for error in check_capture_data(swapped).errors)
    off_check = check_capture_data(off)
    assert off_check.valid
    assert any("+2.7 mm: confirm it" in w for w in off_check.warnings)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"units": "in"}, 'units must be "mm"'),
        ({"device": "omnipod"}, "device must be one of"),
        ({"colour": "grey"}, "unknown fields: colour"),
        ({"measured_by": ""}, "measured_by is required"),
        ({"edge_features_checked": False}, "edge_features_checked must be true"),
        (
            {
                "body_readings": {
                    "length_mm": [51.3],
                    "width_mm": [37.3] * 3,
                    "thickness_mm": [14.2] * 3,
                }
            },
            "body_readings.length_mm must be 3 positive readings",
        ),
        (
            {
                "edge_features": [
                    {
                        "identifier": "port",
                        "edge": "north",
                        "center_offset_mm": 24.0,
                        "width_mm": 6.0,
                    }
                ]
            },
            "runs off the end of the north edge",
        ),
        (
            {
                "edge_features": [
                    {
                        "identifier": "port",
                        "edge": "up",
                        "center_offset_mm": 0.0,
                        "width_mm": 6.0,
                    }
                ]
            },
            "edge must be one of",
        ),
    ],
)
def test_what_cannot_be_right_is_refused(changes: dict[str, Any], message: str) -> None:
    check = check_capture_data(filled(**changes))

    assert not check.valid
    assert any(message in error for error in check.errors), check.errors


def test_a_mobi_capture_with_no_edge_features_is_refused() -> None:
    check = check_capture_data(filled(edge_features=[]))

    assert not check.valid
    assert any(
        "leaves out fill-port, button, charging-contacts" in e for e in check.errors
    ), check.errors


def test_a_mobi_capture_missing_one_expected_feature_is_refused() -> None:
    # A cradle notches only what is listed, so it would wall over the port.
    features = [
        feature
        for feature in filled()["edge_features"]
        if feature["identifier"] != "fill-port"
    ]
    check = check_capture_data(filled(edge_features=features))

    assert not check.valid
    assert any("leaves out fill-port:" in e for e in check.errors), check.errors


def test_the_cli_writes_a_template_and_checks_a_capture(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    template = tmp_path / "g7.json"
    assert (
        main(
            ["wearable", "template", "--device", "dexcom-g7", "--output", str(template)]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["wearable", "check", str(template)]) == 1
    assert not json.loads(capsys.readouterr().out)["valid"]

    template.write_text(json.dumps(filled("dexcom-g7")), encoding="utf-8")
    assert main(["wearable", "check", str(template)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["device"] == "dexcom-g7"
    assert output["body_mm"]["length"] == pytest.approx(27.4)


# --- the wearable file: a device of the user's own, an outline, face features, a mass ----------


def custom(**changes: Any) -> dict[str, Any]:
    """The custom template with its examples replaced, as a person would."""

    data = capture_template("custom")
    del data["needs_review"]
    data.update(
        name="Acme tracker",
        measured_by="A. Tester",
        measured_on="2026-10-01",
        caliper="digital caliper, 0.01 mm",
        orientation="screen up, charging pins at the east end",
        source="one tracker, three passes",
        edge_features_checked=True,
        body_readings={
            "length_mm": [41.2, 41.3, 41.25],
            "width_mm": [33.0, 33.05, 33.0],
            "thickness_mm": [9.8, 9.9, 9.8],
        },
        edge_features=[
            {
                "identifier": "charging-pins",
                "edge": "east",
                "center_offset_mm": 0.0,
                "width_mm": 8.0,
                "notes": "measured from the south end",
            }
        ],
        face_features=[
            {
                "identifier": "screen",
                "center_x_mm": 0.0,
                "center_y_mm": 2.0,
                "width_mm": 24.0,
                "depth_mm": 18.0,
                "notes": "the active area",
            }
        ],
        mass={"value_g": 18.5, "source": "a kitchen scale, one tracker"},
    )
    data.update(changes)

    return data


def test_the_custom_template_is_refused_until_its_examples_are_replaced() -> None:
    check = check_capture_data(capture_template("custom"))

    assert not check.valid
    assert any("needs_review" in error for error in check.errors)


def test_a_custom_device_is_valid_and_loads_with_everything_it_lists(
    tmp_path: Path,
) -> None:
    data = custom()
    path = tmp_path / "tracker.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    check = check_capture_data(data)
    capture = load_capture(path)

    assert check.valid, check.errors
    assert capture.device == "custom" and capture.name == "Acme tracker"
    # No published size, so the readings are all there is: the median is used.
    assert capture.length_mm == pytest.approx(41.25)
    assert capture.outline_radius_mm == 3.0
    assert [f.identifier for f in capture.face_features] == ["screen"]
    assert capture.face_features[0].width_mm == 24.0
    assert capture.mass_g == 18.5 and "kitchen scale" in capture.mass_source
    assert [f.identifier for f in capture.edge_features] == ["charging-pins"]


def test_a_custom_device_needs_a_name_and_a_catalog_one_takes_none() -> None:
    assert any("needs a name" in e for e in check_capture_data(custom(name=" ")).errors)
    named = check_capture_data(filled(name="Acme"))

    assert any("name is for a custom device" in e for e in named.errors)


def test_an_unknown_device_is_still_refused_and_the_message_offers_custom() -> None:
    check = check_capture_data(filled(device="omnipod"))

    assert any("device must be one of" in e and "custom" in e for e in check.errors)


def test_a_custom_device_with_no_face_features_listed_is_questioned() -> None:
    absent = custom()
    del absent["face_features"]

    assert any(
        "no face_features listed" in w for w in check_capture_data(absent).warnings
    )
    # An empty list says there are none.
    assert check_capture_data(custom(face_features=[])).warnings == ()


def test_a_capture_made_before_these_fields_loads_with_their_defaults(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mobi.json"
    path.write_text(json.dumps(filled()), encoding="utf-8")
    capture = load_capture(path)

    assert capture.name == "Tandem Mobi pump"
    assert capture.outline_radius_mm is None
    assert capture.face_features == () and capture.mass_g is None


@pytest.mark.parametrize(
    ("outline", "message"),
    [
        ("oval", "outline must be 'rectangle' or"),
        ({"type": "oval"}, "outline must be 'rectangle' or"),
        ({"type": "rounded_rectangle"}, "outline.radius_mm must be a number"),
        ({"type": "rounded_rectangle", "radius_mm": 0.05}, "at least 0.1"),
        ({"type": "rounded_rectangle", "radius_mm": 20.0}, "more than half"),
        (
            {"type": "rounded_rectangle", "radius_mm": 3.0, "colour": "red"},
            "outline has unknown fields",
        ),
    ],
)
def test_an_outline_that_cannot_be_right_is_refused(outline: Any, message: str) -> None:
    check = check_capture_data(custom(outline=outline))

    assert any(message in e for e in check.errors), check.errors


def test_a_rectangle_outline_is_allowed_and_so_is_one_on_a_catalog_device() -> None:
    assert check_capture_data(custom(outline="rectangle")).valid
    assert check_capture_data(
        filled(outline={"type": "rounded_rectangle", "radius_mm": 4.0})
    ).valid


def feature(**changes: Any) -> dict[str, Any]:
    return {
        "identifier": "button",
        "center_x_mm": 0.0,
        "center_y_mm": 0.0,
        "width_mm": 6.0,
        "depth_mm": 6.0,
        **changes,
    }


@pytest.mark.parametrize(
    ("features", "message"),
    [
        ("screen", "face_features must be a list"),
        (["screen"], "face_features[0] must be an object"),
        ([feature(colour="red")], "unknown fields: colour"),
        ([feature(identifier="")], "needs an identifier"),
        ([feature(), feature()], "button is listed twice"),
        ([feature(width_mm=0)], "positive width_mm and depth_mm"),
        ([feature(center_x_mm="left")], "needs center_x_mm"),
        ([feature(center_x_mm=19.0)], "does not lie inside the device's outline"),
        # Inside the bounding rectangle, but past the 3 mm rounded corner.
        (
            [feature(center_x_mm=19.4, center_y_mm=15.3, width_mm=2.0, depth_mm=2.0)],
            "does not lie inside the device's outline",
        ),
    ],
)
def test_a_face_feature_that_cannot_be_right_is_refused(
    features: Any, message: str
) -> None:
    check = check_capture_data(custom(face_features=features))

    assert any(message in e for e in check.errors), check.errors


def test_a_face_feature_in_a_rounded_corner_fits_if_the_corner_is_square() -> None:
    corner = [feature(center_x_mm=19.4, center_y_mm=15.3, width_mm=2.0, depth_mm=2.0)]

    assert not check_capture_data(custom(face_features=corner)).valid
    assert check_capture_data(custom(face_features=corner, outline="rectangle")).valid


@pytest.mark.parametrize(
    ("mass", "message"),
    [
        ("heavy", "mass must be an object"),
        ({"value_g": 0, "source": "scale"}, "mass.value_g must be a number above zero"),
        ({"value_g": 9000, "source": "scale"}, "at most 5000"),
        ({"value_g": 18.5}, "mass.source is required"),
        ({"value_g": 18.5, "source": "scale", "unit": "g"}, "mass has unknown fields"),
    ],
)
def test_a_mass_that_cannot_be_right_is_refused(mass: Any, message: str) -> None:
    check = check_capture_data(custom(mass=mass))

    assert any(message in e for e in check.errors), check.errors


def test_the_cli_writes_a_custom_template_and_checks_a_custom_capture(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    template = tmp_path / "tracker.json"

    assert (
        main(["wearable", "template", "--device", "custom", "--output", str(template)])
        == 0
    )
    capsys.readouterr()
    assert main(["wearable", "check", str(template)]) == 1

    template.write_text(json.dumps(custom()), encoding="utf-8")
    capsys.readouterr()

    assert main(["wearable", "check", str(template)]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["name"] == "Acme tracker"
    assert output["outline"] == "rounded rectangle, 3 mm corners"
    assert output["face_features"] == ["screen (24 x 18 mm)"]
    assert output["mass_g"] == 18.5

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


def test_a_mobi_capture_with_no_edge_features_is_questioned() -> None:
    check = check_capture_data(filled(edge_features=[]))

    assert check.valid
    assert any("no edge features listed" in w for w in check.warnings)


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

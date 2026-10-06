"""The calibration coupon: its features, its record, its trial, and the profile."""

from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.calibration_coupon import (
    BUILD_RECORD,
    HOLE,
    PLATE_MM,
    POCKET,
    POCKET_DEPTH_MM,
    POCKET_LENGTH_MM,
    SLOT,
    SLOT_DEPTH_MM,
    SLOT_SPAN_MM,
    Coupon,
    CouponFeature,
    build_coupon,
    complete_coupon_trial,
    coupon_checks,
    start_coupon_trial,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import get_fastener
from zcad_core.profiles.compensation import collect_samples

PRINTER = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
# A probe this far inside a feature's modelled size finds no plastic; this far
# outside it, it finds the feature's wall.
INSIDE_MM = 0.02
OUTSIDE_MM = 0.1


@pytest.fixture(scope="module")
def coupon() -> Coupon:
    return build_coupon(get_fastener("M3"))


def plastic(coupon: Coupon, probe: cq.Solid) -> float:
    return intersection_volume(workplane_shape(coupon.solid), probe)


def test_the_holes_are_the_sizes_an_enclosure_models(coupon: Coupon) -> None:
    m3 = get_fastener("M3")
    holes = {f.name: f.nominal_mm for f in coupon.features if f.kind == HOLE}

    assert holes == {
        **{
            f"insert_pocket_{n}_diameter_mm": m3.heat_set_insert_diameter_mm
            for n in (1, 2, 3)
        },
        **{f"screw_hole_{n}_diameter_mm": m3.clearance_hole_mm for n in (1, 2, 3)},
    }
    assert {f.figure for f in coupon.features} == {
        "hole_shortfall_mm",
        "side_gap_shortfall_mm",
        "vertical_play_shortfall_mm",
    }


def test_each_hole_is_open_through_at_its_size_and_no_wider(coupon: Coupon) -> None:
    for feature in (f for f in coupon.features if f.kind == HOLE):
        radius = feature.nominal_mm / 2
        centre = cq.Vector(feature.x_mm, feature.y_mm, -1.0)
        clear = cq.Solid.makeCylinder(radius - INSIDE_MM, PLATE_MM + 2.0, centre)
        wall = cq.Solid.makeCylinder(radius + OUTSIDE_MM, PLATE_MM + 2.0, centre)

        assert plastic(coupon, clear) == 0.0, feature.name
        assert plastic(coupon, wall) > 0.0, feature.name


def test_each_pocket_is_its_width_and_leaves_a_floor(coupon: Coupon) -> None:
    for feature in (f for f in coupon.features if f.kind == POCKET):

        def across(
            width: float, bottom: float, feature: CouponFeature = feature
        ) -> cq.Solid:
            return cq.Solid.makeBox(
                width,
                POCKET_LENGTH_MM - 1.0,
                PLATE_MM + 1.0 - bottom,
                pnt=cq.Vector(
                    feature.x_mm - width / 2,
                    feature.y_mm - (POCKET_LENGTH_MM - 1.0) / 2,
                    bottom,
                ),
            )

        floor = PLATE_MM - POCKET_DEPTH_MM

        assert (
            plastic(coupon, across(feature.nominal_mm - INSIDE_MM, floor + 0.01)) == 0.0
        )
        assert (
            plastic(coupon, across(feature.nominal_mm + OUTSIDE_MM, floor + 0.01)) > 0.0
        )
        # Below the pocket, the plate is still there.
        assert plastic(coupon, across(feature.nominal_mm - INSIDE_MM, 0.0)) > 0.0


def test_each_slot_is_open_to_its_height_under_a_roof(coupon: Coupon) -> None:
    for feature in (f for f in coupon.features if f.kind == SLOT):

        def through(height: float, feature: CouponFeature = feature) -> cq.Solid:
            return cq.Solid.makeBox(
                SLOT_SPAN_MM - 0.2,
                SLOT_DEPTH_MM + 2.0,
                height,
                pnt=cq.Vector(
                    feature.x_mm - (SLOT_SPAN_MM - 0.2) / 2,
                    feature.y_mm - SLOT_DEPTH_MM / 2 - 1.0,
                    PLATE_MM,
                ),
            )

        assert plastic(coupon, through(feature.nominal_mm - INSIDE_MM)) == 0.0
        assert plastic(coupon, through(feature.nominal_mm + OUTSIDE_MM)) > 0.0


def test_the_coupon_passes_its_checks_and_a_small_bed_refuses_it(
    coupon: Coupon,
) -> None:
    checks = coupon_checks(coupon, {"x": 180, "y": 180, "z": 180})

    assert all(check["passed"] for check in checks.values())
    assert not coupon_checks(coupon, {"x": 40, "y": 40, "z": 40})["fits_bed"]["passed"]


def build(tmp_path: Path) -> Path:
    output = tmp_path / "evidence" / "coupons" / "c1"
    assert (
        main(
            [
                "coupon",
                "build",
                "--output-directory",
                str(output),
                "--printer-profile",
                str(PRINTER),
                "--print-copies",
            ]
        )
        == 0
    )
    return output / BUILD_RECORD


def fill(trial: Path, readings: dict[str, float], result: str = "pass") -> None:
    observations = json.loads((trial / "observations.json").read_text("utf-8"))
    for entry in observations.values():
        entry["result"] = result
    (trial / "observations.json").write_text(json.dumps(observations), "utf-8")
    measurements = json.loads((trial / "measurements.json").read_text("utf-8"))
    for name, value in readings.items():
        measurements[name]["value_mm"] = value
    (trial / "measurements.json").write_text(json.dumps(measurements), "utf-8")


def test_the_build_writes_its_record_and_will_not_build_over_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    record_path = build(tmp_path)
    record = json.loads(record_path.read_text("utf-8"))

    assert record["hole_compensation_mm"] == 0.0
    assert len(record["features"]) == 12
    assert (record_path.parent / "print" / "calibration-coupon-coupon.stl").is_file()
    capsys.readouterr()
    again = main(
        [
            "coupon",
            "build",
            "--output-directory",
            str(record_path.parent),
            "--printer-profile",
            str(PRINTER),
        ]
    )

    assert again == 1
    assert "already built" in capsys.readouterr().err


def test_a_trial_records_what_was_measured_and_feeds_the_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    trial = start_coupon_trial(build(tmp_path))
    fill(
        trial,
        {
            "insert_pocket_1_diameter_mm": 4.45,
            "screw_hole_1_diameter_mm": 3.30,
            "pocket_8_width_mm": 7.70,
            "slot_085_height_mm": 0.70,
        },
    )

    record = json.loads(
        complete_coupon_trial(trial, material_profile_id="petg").read_text("utf-8")
    )

    assert [entry["name"] for entry in record["measurements"]] == [
        "insert_pocket_1_diameter_mm",
        "screw_hole_1_diameter_mm",
        "pocket_8_width_mm",
        "slot_085_height_mm",
    ]
    samples = {
        (sample.figure, round(sample.shortfall_mm, 3))
        for sample in collect_samples(
            tmp_path / "evidence",
            printer_profile_id="bambu-lab-a1-mini",
            material_profile_id="petg",
        )
    }
    # Holes: modelled less measured. A pocket narrows on both sides, so half.
    assert samples == {
        ("hole_shortfall_mm", 0.15),
        ("hole_shortfall_mm", 0.1),
        ("side_gap_shortfall_mm", 0.15),
        ("vertical_play_shortfall_mm", 0.15),
    }
    # Another material's coupon is another profile's.
    assert not collect_samples(
        tmp_path / "evidence",
        printer_profile_id="bambu-lab-a1-mini",
        material_profile_id="pla",
    )
    with pytest.raises(FileExistsError, match="already completed"):
        complete_coupon_trial(trial, material_profile_id="petg")


def test_a_trial_refuses_what_it_cannot_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    record_path = build(tmp_path)
    trial = start_coupon_trial(record_path)

    with pytest.raises(ValueError, match="must be pass or fail"):
        complete_coupon_trial(trial, material_profile_id="petg")

    fill(trial, {})
    with pytest.raises(ValueError, match="at least one measured feature"):
        complete_coupon_trial(trial, material_profile_id="petg")

    fill(trial, {"slot_1_height_mm": 0.9})
    stl = Path(
        json.loads(record_path.read_text("utf-8"))["parts"]["coupon"]["stl_path"]
    )
    stl.write_bytes(stl.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="no longer matches"):
        complete_coupon_trial(trial, material_profile_id="petg")

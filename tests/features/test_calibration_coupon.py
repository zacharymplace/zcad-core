"""The calibration coupon: its features, its record, its trial, and the profile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    TONGUE_LENGTH_MM,
    TONGUE_STOP_MM,
    TONGUE_THICKNESS_MM,
    TONGUE_WIDTH_MM,
    Coupon,
    CouponFeature,
    Tongue,
    build_coupon,
    complete_coupon_trial,
    coupon_checks,
    start_coupon_trial,
)
from zcad_core.features.mounts import flexure_for
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import get_fastener
from zcad_core.profiles.compensation import (
    collect_samples,
    derive_strain_limit,
    load_compensation_profile,
)

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


def fill(
    trial: Path,
    readings: dict[str, float],
    result: str = "pass",
    tongues: dict[str, str] | None = None,
) -> None:
    """Answer the checks with ``result``, each tongue as ``tongues`` says
    (skipped if unnamed), and record ``readings``."""

    observations = json.loads((trial / "observations.json").read_text("utf-8"))
    for name, entry in observations.items():
        if "strain" in entry:
            entry["result"] = (tongues or {}).get(name, "skipped")
        else:
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


def test_each_tongue_swings_exactly_its_strain_before_its_stop(coupon: Coupon) -> None:
    assert [round(t.strain, 3) for t in coupon.tongues] == [
        0.01,
        0.015,
        0.02,
        0.03,
        0.04,
    ]

    for tongue in coupon.tongues:
        # The engine's own cantilever formula agrees with the strain it is for.
        assert flexure_for(
            tongue.deflection_mm, TONGUE_LENGTH_MM, TONGUE_THICKNESS_MM
        ).strain == pytest.approx(tongue.strain)
        back = tongue.y_mm + TONGUE_THICKNESS_MM / 2

        def behind(
            depth: float, tongue: Tongue = tongue, back: float = back
        ) -> cq.Solid:
            return cq.Solid.makeBox(
                TONGUE_WIDTH_MM - 0.2,
                depth,
                TONGUE_LENGTH_MM - 1.0,
                pnt=cq.Vector(
                    tongue.x_mm - (TONGUE_WIDTH_MM - 0.2) / 2,
                    back + 0.01,
                    PLATE_MM + 0.5,
                ),
            )

        # Open behind the post for its whole swing, and solid just past it.
        assert plastic(coupon, behind(tongue.deflection_mm - INSIDE_MM)) == 0.0
        assert plastic(coupon, behind(tongue.deflection_mm + OUTSIDE_MM)) > 0.0
        # The stop stands as tall as the post, so the post's tip meets it.
        stop_top = cq.Solid.makeBox(
            0.5,
            TONGUE_STOP_MM - 0.2,
            0.5,
            pnt=cq.Vector(
                tongue.x_mm - 0.25,
                back + tongue.deflection_mm + 0.1,
                PLATE_MM + TONGUE_LENGTH_MM - 0.6,
            ),
        )
        assert plastic(coupon, stop_top) > 0.0


def test_a_trial_records_each_tongue_tested_and_refuses_an_unanswered_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    trial = start_coupon_trial(build(tmp_path))
    observations = json.loads((trial / "observations.json").read_text("utf-8"))
    for entry in observations.values():
        entry["result"] = "pending" if "strain" in entry else "pass"
    (trial / "observations.json").write_text(json.dumps(observations), "utf-8")

    with pytest.raises(
        ValueError, match="tongue_1_percent must be pass, fail or skipped"
    ):
        complete_coupon_trial(trial, material_profile_id="petg")

    fill(
        trial,
        {},
        tongues={
            "tongue_1_percent": "pass",
            "tongue_1_5_percent": "pass",
            "tongue_2_percent": "fail",
        },
    )
    record = json.loads(
        complete_coupon_trial(trial, material_profile_id="petg").read_text("utf-8")
    )

    assert record["tongue_orientation"] == "across_layers"
    assert [(t["name"], t["survived"]) for t in record["tongues"]] == [
        ("tongue_1_percent", True),
        ("tongue_1_5_percent", True),
        ("tongue_2_percent", False),
    ]


def coupon_trial(root: Path, name: str, results: dict[float, bool]) -> None:
    trial = root / "coupons" / name / "trials" / "trial-001"
    trial.mkdir(parents=True)
    (trial / "calibration-coupon-trial.json").write_text(
        json.dumps(
            {
                "printer_profile_id": "bambu-lab-a1-mini",
                "material_profile_id": "petg",
                "tongue_orientation": "across_layers",
                "measurements": [],
                "tongues": [
                    {"name": f"t{strain}", "strain": strain, "survived": survived}
                    for strain, survived in results.items()
                ],
            }
        ),
        "utf-8",
    )


def limit(root: Path) -> dict[str, Any] | None:
    return derive_strain_limit(
        root, printer_profile_id="bambu-lab-a1-mini", material_profile_id="petg"
    )


def test_the_strain_limit_is_the_lowest_every_print_held(tmp_path: Path) -> None:
    assert limit(tmp_path) is None

    # Held to 2 per cent, failed at 3; a pass at 4 above that failure is luck.
    coupon_trial(
        tmp_path, "a", {0.01: True, 0.015: True, 0.02: True, 0.03: False, 0.04: True}
    )
    coupon_trial(
        tmp_path, "b", {0.01: True, 0.015: True, 0.02: True, 0.03: True, 0.04: False}
    )
    derived = limit(tmp_path)

    assert derived is not None
    assert derived["value"] == 0.02
    assert derived["trials"] == 2
    assert [t["first_failure"] for t in derived["per_trial"]] == [0.03, 0.04]

    # One print whose gentlest tongue failed: the limit is below all it tested.
    coupon_trial(tmp_path, "c", {0.01: False, 0.015: True})
    again = limit(tmp_path)
    assert again is not None
    assert again["value"] is None


def test_a_profile_reads_its_strain_limit(tmp_path: Path) -> None:
    def profile(strain_limit: object) -> float | None:
        path = tmp_path / "profile.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "profile_id": "p",
                    "version": 1,
                    "figures": {},
                    "strain_limit": strain_limit,
                }
            ),
            "utf-8",
        )
        return load_compensation_profile(path).strain_limit()

    assert profile({"value": 0.02}) == 0.02
    assert profile({"value": None}) is None
    assert profile(None) is None

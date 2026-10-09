"""The fit coupon: its holes, its record, its trial, and the joint profile it feeds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.cli._common import applied_joint_profile as applied_from_path
from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.jig import bore_diameter_mm
from zcad_core.features.joint_coupon import (
    BORE_LENGTH_MM,
    BUILD_RECORD,
    FIT_CLEARANCES_MM,
    FitCoupon,
    build_fit_coupon,
    complete_joint_trial,
    fit_coupon_checks,
    fit_hole_diameter_mm,
    start_joint_trial,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.metadata.build_record import build_part_record
from zcad_core.profiles import load_printer_profile
from zcad_core.profiles.joints import (
    JOINT_TRIAL_RECORD,
    PRESS_FIT,
    SLIDING,
    applied_joint_profile,
    derive_joint_profile,
    load_joint_profile,
    measured_fits,
    write_joint_profile,
)

PRINTER = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
# A probe this far inside a hole's modelled size finds no plastic; this far
# outside it, it finds the hole's wall.
INSIDE_MM = 0.02
OUTSIDE_MM = 0.1


@pytest.fixture(scope="module")
def coupon() -> FitCoupon:
    return build_fit_coupon(6.0, 0.2)


def plastic(coupon: FitCoupon, probe: cq.Solid) -> float:
    return intersection_volume(workplane_shape(coupon.solid), probe)


def test_each_hole_is_sized_as_a_jig_sizes_a_bore_for_a_metal_part() -> None:
    for clearance in FIT_CLEARANCES_MM:
        fits = {"sliding_clearance_per_side": clearance, "hole_oversize": 0.2}

        assert fit_hole_diameter_mm(6.0, clearance, 0.2) == pytest.approx(
            bore_diameter_mm(6.0, fits)
        )


def test_each_hole_is_open_at_its_size_and_no_wider(coupon: FitCoupon) -> None:
    assert len(coupon.rungs) == 2 * len(FIT_CLEARANCES_MM)

    for rung in coupon.rungs:
        radius = rung.hole_diameter_mm / 2

        if rung.orientation == "in_layer":
            start, axis = cq.Vector(rung.x_mm, rung.y_mm, -1.0), cq.Vector(0, 0, 1)
        else:
            front = rung.y_mm - BORE_LENGTH_MM / 2 - 1.0
            start, axis = cq.Vector(rung.x_mm, front, rung.z_mm), cq.Vector(0, 1, 0)

        clear = cq.Solid.makeCylinder(
            radius - INSIDE_MM, BORE_LENGTH_MM + 2.0, start, axis
        )
        wall = cq.Solid.makeCylinder(
            radius + OUTSIDE_MM, BORE_LENGTH_MM + 2.0, start, axis
        )

        assert plastic(coupon, clear) == 0.0, rung.name
        assert plastic(coupon, wall) > 0.0, rung.name


def test_the_coupon_passes_its_checks_and_a_small_bed_refuses_it(
    coupon: FitCoupon,
) -> None:
    checks = fit_coupon_checks(coupon, {"x": 180, "y": 180, "z": 180})

    assert all(check["passed"] for check in checks.values()), checks
    assert not fit_coupon_checks(coupon, {"x": 80, "y": 180, "z": 180})["fits_bed"][
        "passed"
    ]


def build(tmp_path: Path, name: str = "fit-01") -> Path:
    output = tmp_path / "evidence" / "joints" / name
    command = [
        "joint",
        "build",
        "fit",
        "--output-directory",
        str(output),
        "--printer-profile",
        str(PRINTER),
        "--print-copies",
    ]

    assert main(command) == 0

    return output / BUILD_RECORD


def test_the_build_records_the_oversize_it_was_built_with_and_will_not_build_over_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    record_path = build(tmp_path)
    record = json.loads(record_path.read_text("utf-8"))
    oversize = load_printer_profile(PRINTER)["tolerances_mm"]["hole_oversize"]

    assert record["family"] == "fit"
    assert record["hole_oversize_mm"] == oversize
    assert record["reference"]["diameter_mm"] == 6.0
    assert len(record["rungs"]) == 18
    capsys.readouterr()

    assert (
        main(
            [
                "joint",
                "build",
                "fit",
                "--output-directory",
                str(record_path.parent),
                "--printer-profile",
                str(PRINTER),
            ]
        )
        == 1
    )
    assert "already built" in capsys.readouterr().err


def fill(trial: Path, readings: dict[float, str], result: str = "pass") -> None:
    """Answer both checks with ``result`` and read every rung at a clearance as
    ``readings`` says, in both orientations; a clearance not named is skipped."""

    observations = json.loads((trial / "observations.json").read_text("utf-8"))

    for entry in observations.values():
        if "reading" in entry:
            entry["reading"] = readings.get(entry["clearance_per_side_mm"], "skipped")
        else:
            entry["result"] = result

    (trial / "observations.json").write_text(json.dumps(observations), "utf-8")


LADDER = {
    0.0: "wont_go",
    0.05: "press",
    0.1: "press",
    0.15: "slides",
    0.2: "slides",
    0.25: "loose",
}


def test_a_trial_records_each_rung_read_and_refuses_what_it_cannot_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    trial = start_joint_trial(build(tmp_path))
    fill(trial, {0.1: "sideways"})

    with pytest.raises(ValueError, match="must be one of"):
        complete_joint_trial(trial, material_profile_id="petg")

    fill(trial, {})

    with pytest.raises(ValueError, match="at least one rung"):
        complete_joint_trial(trial, material_profile_id="petg")

    fill(trial, LADDER, result="fail")

    with pytest.raises(ValueError, match="Print another"):
        complete_joint_trial(trial, material_profile_id="petg")

    fill(trial, LADDER)
    record = json.loads(
        complete_joint_trial(trial, material_profile_id="petg").read_text("utf-8")
    )

    assert record["family"] == "fit"
    assert len(record["readings"]) == 12
    assert {entry["orientation"] for entry in record["readings"]} == {
        "in_layer",
        "across_layers",
    }

    with pytest.raises(FileExistsError, match="already completed"):
        complete_joint_trial(trial, material_profile_id="petg")


def trial_record(
    evidence: Path,
    name: str,
    readings: dict[float, str],
    *,
    oversize: float = 0.2,
    across: dict[float, str] | None = None,
) -> None:
    """A recorded fit trial, read as ``readings`` in a layer and as ``across``
    (the same, unless given) across layers."""

    folder = evidence / "joints" / name / "trials" / "trial-001"
    folder.mkdir(parents=True)
    entries: list[dict[str, Any]] = []

    for orientation, ladder in (
        ("in_layer", readings),
        ("across_layers", across if across is not None else readings),
    ):
        entries += [
            {
                "name": f"{orientation}_{clearance}",
                "orientation": orientation,
                "clearance_per_side_mm": clearance,
                "reading": reading,
            }
            for clearance, reading in ladder.items()
        ]

    (folder / JOINT_TRIAL_RECORD).write_text(
        json.dumps(
            {
                "family": "fit",
                "trial_id": name,
                "generator_version": "1.0.0",
                "printer_profile_id": "bambu-lab-a1-mini",
                "material_profile_id": "petg",
                "hole_oversize_mm": oversize,
                "readings": entries,
            }
        ),
        "utf-8",
    )


def derive(evidence: Path, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    return derive_joint_profile(
        evidence,
        printer_profile_id="bambu-lab-a1-mini",
        material_profile_id="petg",
        previous=previous,
    )


def test_each_fit_is_the_rung_its_rule_chooses_in_every_trial(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    trial_record(evidence, "a", LADDER)

    with pytest.raises(ValueError, match="at least 2"):
        derive(evidence)

    # The second print is a step tighter across layers: there 0.15 still presses.
    trial_record(evidence, "b", LADDER, across={**LADDER, 0.15: "press"})
    profile = derive(evidence)

    assert profile["figures"][SLIDING]["value_mm"] == 0.2
    assert profile["figures"][PRESS_FIT]["value_mm"] == 0.1
    assert profile["hole_oversize_mm"] == 0.2
    assert len(profile["sources"]) == 2


def test_a_fit_no_rung_meets_is_left_to_the_printer_profile(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    trial_record(evidence, "a", {0.1: "slides", 0.2: "slides"})
    trial_record(evidence, "b", {0.1: "slides", 0.2: "loose"})
    figures = derive(evidence)["figures"]

    assert figures[SLIDING]["value_mm"] == 0.1
    assert figures[PRESS_FIT]["value_mm"] is None
    assert "printer profile's figure stands" in figures[PRESS_FIT]["reason"]


def test_trials_that_cannot_be_pooled_are_refused(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    trial_record(evidence, "a", LADDER)
    trial_record(evidence, "b", LADDER, oversize=0.1)

    with pytest.raises(ValueError, match="different hole_oversize"):
        derive(evidence)

    backwards = tmp_path / "backwards"
    trial_record(backwards, "a", {0.1: "slides", 0.2: "press"})
    trial_record(backwards, "b", {0.1: "slides", 0.2: "press"})

    with pytest.raises(ValueError, match="check the readings"):
        derive(backwards)


def test_a_profile_only_moves_to_its_next_version(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    trial_record(evidence, "a", LADDER)
    trial_record(evidence, "b", LADDER)
    path = tmp_path / "profiles" / "joints" / "a1-petg.json"
    first = derive(evidence)
    write_joint_profile(first, path)
    second = derive(evidence, previous=first)

    assert second["version"] == 2
    assert second["history"][0]["figures"] == first["figures"]

    with pytest.raises(FileExistsError, match="next version"):
        write_joint_profile(first, path)

    write_joint_profile(second, path)


def profile_file(tmp_path: Path, oversize: float = 0.2) -> Path:
    evidence = tmp_path / f"evidence-{oversize}"
    trial_record(evidence, "a", LADDER, oversize=oversize)
    trial_record(evidence, "b", LADDER, oversize=oversize)
    path = tmp_path / f"joints-{oversize}.json"
    write_joint_profile(derive(evidence), path)

    return path


def test_a_build_given_a_profile_builds_with_its_fits_and_says_so(
    tmp_path: Path,
) -> None:
    printer = load_printer_profile(PRINTER)
    provisional, _, _ = printer_numbers(printer)
    profile = load_joint_profile(profile_file(tmp_path))

    def part_metadata() -> dict[str, Any]:
        return build_part_record(
            design_name="x",
            design_type="jig",
            part_name="jig",
            valid_solid=True,
            volume_mm3=1.0,
            bounds_mm=(1.0, 1.0, 1.0),
            step_path=tmp_path / "x.step",
            stl_path=tmp_path / "x.stl",
            printer_profile=None,
            material_profile=None,
            repository_root=tmp_path,
        )

    assert "joint_profile" not in part_metadata()["manufacturing"]

    with measured_fits(profile):
        fits, _, _ = printer_numbers(printer)
        metadata = part_metadata()

    assert fits == {**provisional, SLIDING: 0.15, PRESS_FIT: 0.1}
    assert metadata["manufacturing"]["joint_profile"]["fits_mm"] == {
        SLIDING: 0.15,
        PRESS_FIT: 0.1,
    }
    # Applied for one command only.
    assert printer_numbers(printer)[0] == provisional
    assert applied_joint_profile() is None


def test_a_profile_measured_on_other_holes_is_refused(tmp_path: Path) -> None:
    printer = load_printer_profile(PRINTER)

    with (
        applied_from_path(profile_file(tmp_path, oversize=0.1)),
        pytest.raises(ValueError, match="print a new fit coupon"),
    ):
        printer_numbers(printer)

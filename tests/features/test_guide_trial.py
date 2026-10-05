"""Print records for drill guides: starting and completing a trial, and what a
build needs to be verified."""

from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.guide_file import guide_template
from zcad_core.features.guide_trial import (
    GuideTrialDisposition,
    applicable_checks,
    complete_guide_trial,
    guide_verification,
    start_guide_trial,
)

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
BUSHING = {
    "inner_diameter_mm": 4.2,
    "outer_diameter_mm": 8.0,
    "length_mm": 12.0,
    "source": "calipers",
}


@pytest.fixture(scope="module")
def slab(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("slab") / "slab.step"
    cq.exporters.export(
        cq.Workplane("XY").box(60, 40, 20, centered=(True, True, False)), str(path)
    )

    return path


def build(directory: Path, slab: Path, *, bushing: bool = False) -> Path:
    """Build a guide with two printed bores, and a bushing bore if asked, and
    give back its build record."""

    data = copy.deepcopy(guide_template(slab))
    data["nest"]["depth_mm"] = 10.0
    data["plate"] = {}
    data["bores"] = [
        {"identifier": "B1", "x_mm": -15.0, "y_mm": 0.0},
        {"identifier": "B2", "x_mm": 15.0, "y_mm": 0.0},
    ]

    if bushing:
        data["bushing"] = BUSHING
        data["bores"].append(
            {"identifier": "B3", "x_mm": 0.0, "y_mm": 12.0, "kind": "bushing"}
        )

    path = directory / "guide.json"
    path.write_text(json.dumps(data))
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(
            [
                "guide",
                "build",
                "--guide-file",
                str(path),
                "--output-directory",
                str(directory / "out"),
                "--printer-profile",
                str(PRINTER_PROFILE),
            ]
        )

    assert code == 0

    return Path(json.loads(out.getvalue())["build_record"])


def record_of(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def fill(
    trial: Path,
    *,
    result: str = "pass",
    offsets: dict[str, tuple[float, float]] | None = None,
    tolerance: float | None = 0.5,
) -> None:
    """Fill a trial's templates: every check ``result``, each bore found
    ``offsets`` from where it was meant to be (a quarter millimetre by default),
    and the position tolerance a pass is judged by."""

    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = result

    (trial / "observations.json").write_text(json.dumps(observations))
    measurements = json.loads((trial / "measurements.json").read_text())

    for name, entry in measurements["bores"].items():
        dx, dy = (offsets or {}).get(name, (0.25, -0.1))
        entry["measured_x_mm"] = entry["nominal_x_mm"] + dx
        entry["measured_y_mm"] = entry["nominal_y_mm"] + dy

    measurements["position_tolerance_mm"] = tolerance
    (trial / "measurements.json").write_text(json.dumps(measurements))


# --- starting a trial -----------------------------------------------------------


def test_a_trial_lists_only_the_checks_that_apply(slab: Path, tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    printed = build(tmp_path / "a", slab)
    trial = start_guide_trial(printed)
    names = set(json.loads((trial / "observations.json").read_text()))

    assert names == {
        "guide_seats_on_part",
        "part_releases",
        "drill_passes_bores",
        "holes_reach_depth",
    }

    (tmp_path / "b").mkdir()
    bushed = build(tmp_path / "b", slab, bushing=True)
    names = set(
        json.loads((start_guide_trial(bushed) / "observations.json").read_text())
    )

    assert "bushings_seated" in names
    assert [c.value for c in applicable_checks(record_of(bushed))][
        -2
    ] == "bushings_seated"


def test_the_measurement_template_has_each_bore_with_its_nominal(
    slab: Path, tmp_path: Path
) -> None:
    record = build(tmp_path, slab, bushing=True)
    trial = start_guide_trial(record)
    template = json.loads((trial / "measurements.json").read_text())

    assert template["part_size_mm"] == pytest.approx([60, 40], abs=0.1)
    assert "bounding box" in template["frame"]
    assert set(template["bores"]) == {"B1", "B2", "B3"}
    assert template["bores"]["B1"]["nominal_x_mm"] == -15.0
    assert template["bores"]["B1"]["measured_x_mm"] is None
    assert template["bores"]["B1"]["modelled_bore_mm"] == pytest.approx(4.6)
    assert "modelled_seat_mm" in template["bores"]["B3"]
    assert "modelled_bore_mm" not in template["bores"]["B3"]


def test_each_trial_gets_the_next_number(slab: Path, tmp_path: Path) -> None:
    record = build(tmp_path, slab)

    assert start_guide_trial(record).name == "trial-001"
    assert start_guide_trial(record).name == "trial-002"


# --- completing it -----------------------------------------------------------------


def passing(slab: Path, directory: Path) -> tuple[Path, Path]:
    directory.mkdir()
    record = build(directory, slab)
    trial = start_guide_trial(record)
    fill(trial)

    return record, trial


def test_a_filled_in_trial_is_recorded_with_each_bores_offset(
    slab: Path, tmp_path: Path
) -> None:
    _, trial = passing(slab, tmp_path / "t")
    path = complete_guide_trial(
        trial,
        disposition=GuideTrialDisposition.PASS,
        material_profile_id="petg",
        notes="first print",
    )
    record = record_of(path)
    b1 = next(b for b in record["bores"] if b["identifier"] == "B1")

    assert record["passed"] is True
    assert record["material_profile_id"] == "petg"
    assert record["printer_profile_id"] == "bambu-lab-a1-mini"
    assert b1["offset_mm"] == {"dx": 0.25, "dy": -0.1, "radial": 0.269}
    assert record["summary"] == {
        "bores": 2,
        "bores_measured": 2,
        "max_radial_mm": 0.269,
        "mean_radial_mm": 0.269,
    }
    assert record["notes"] == "first print"


def test_a_completed_trial_is_never_overwritten(slab: Path, tmp_path: Path) -> None:
    _, trial = passing(slab, tmp_path / "t")
    complete_guide_trial(
        trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
    )

    with pytest.raises(FileExistsError):
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
        )


def test_a_trial_of_a_changed_print_is_refused(slab: Path, tmp_path: Path) -> None:
    record, trial = passing(slab, tmp_path / "t")
    stl = Path(record_of(record)["parts"]["guide"]["stl_path"])
    stl.write_bytes(stl.read_bytes() + b" ")

    with pytest.raises(ValueError, match="no longer matches the build record"):
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
        )


def test_an_observation_left_pending_is_refused(slab: Path, tmp_path: Path) -> None:
    record = build(tmp_path, slab)
    trial = start_guide_trial(record)

    with pytest.raises(ValueError, match="must be pass or fail"):
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.FAIL, material_profile_id="petg"
        )


def test_observations_must_cover_exactly_the_guides_checks(
    slab: Path, tmp_path: Path
) -> None:
    _, trial = passing(slab, tmp_path / "t")
    observations = json.loads((trial / "observations.json").read_text())
    del observations["part_releases"]
    observations["invented"] = {"result": "pass"}
    (trial / "observations.json").write_text(json.dumps(observations))

    with pytest.raises(ValueError, match="missing.*part_releases"):
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
        )


def test_a_passing_trial_cannot_have_a_failed_check(slab: Path, tmp_path: Path) -> None:
    _, trial = passing(slab, tmp_path / "t")
    observations = json.loads((trial / "observations.json").read_text())
    observations["part_releases"]["result"] = "fail"
    (trial / "observations.json").write_text(json.dumps(observations))

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
        )


def test_a_passing_trial_measures_every_bore(slab: Path, tmp_path: Path) -> None:
    _, trial = passing(slab, tmp_path / "t")
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["bores"]["B2"]["measured_x_mm"] = None
    measurements["bores"]["B2"]["measured_y_mm"] = None
    (trial / "measurements.json").write_text(json.dumps(measurements))

    with pytest.raises(ValueError, match="not measured: \\['B2'\\]"):
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
        )


def test_half_a_position_is_refused(slab: Path, tmp_path: Path) -> None:
    _, trial = passing(slab, tmp_path / "t")
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["bores"]["B1"]["measured_y_mm"] = None
    (trial / "measurements.json").write_text(json.dumps(measurements))

    with pytest.raises(ValueError, match="both measured_x_mm and measured_y_mm"):
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
        )


def test_a_bore_the_guide_does_not_have_is_refused(slab: Path, tmp_path: Path) -> None:
    _, trial = passing(slab, tmp_path / "t")
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["bores"]["B9"] = {"measured_x_mm": 1, "measured_y_mm": 1}
    (trial / "measurements.json").write_text(json.dumps(measurements))

    with pytest.raises(ValueError, match="does not have: \\['B9'\\]"):
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
        )


def test_a_failed_trial_is_recorded_without_measurements(
    slab: Path, tmp_path: Path
) -> None:
    (tmp_path / "t").mkdir()
    record = build(tmp_path / "t", slab)
    trial = start_guide_trial(record)
    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = "pass"

    observations["guide_seats_on_part"]["result"] = "fail"
    (trial / "observations.json").write_text(json.dumps(observations))
    path = complete_guide_trial(
        trial, disposition=GuideTrialDisposition.FAIL, material_profile_id="petg"
    )
    recorded = record_of(path)

    assert recorded["passed"] is False
    assert recorded["failed_checks"] == ["guide_seats_on_part"]
    assert recorded["summary"]["max_radial_mm"] is None


def test_an_inconclusive_trial_needs_something_to_say(
    slab: Path, tmp_path: Path
) -> None:
    (tmp_path / "t").mkdir()
    record = build(tmp_path / "t", slab)
    trial = start_guide_trial(record)
    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = "pass"

    (trial / "observations.json").write_text(json.dumps(observations))

    with pytest.raises(ValueError, match="at least one measurement"):
        complete_guide_trial(
            trial,
            disposition=GuideTrialDisposition.INCONCLUSIVE,
            material_profile_id="petg",
        )


def test_the_printed_holes_are_compared_with_the_model(
    slab: Path, tmp_path: Path
) -> None:
    (tmp_path / "t").mkdir()
    record = build(tmp_path / "t", slab, bushing=True)
    trial = start_guide_trial(record)
    fill(trial)
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["bores"]["B1"]["measured_bore_mm"] = 4.45
    measurements["bores"]["B3"]["measured_seat_mm"] = 8.1
    (trial / "measurements.json").write_text(json.dumps(measurements))
    path = complete_guide_trial(
        trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
    )
    bores = {b["identifier"]: b for b in record_of(path)["bores"]}

    # Modelled 4.6 mm and measured 4.45: the printer made it 0.15 smaller. The
    # pocket was modelled 8.3 (8 + 2 x 0.05 + 0.2).
    assert bores["B1"]["bore_error_mm"] == pytest.approx(-0.15)
    assert bores["B3"]["seat_error_mm"] == pytest.approx(8.1 - 8.3)
    assert "bore_error_mm" not in bores["B2"]


# --- verification ----------------------------------------------------------------------


def test_two_passing_trials_of_the_same_build_verify_it(
    slab: Path, tmp_path: Path
) -> None:
    (tmp_path / "t").mkdir()
    record = build(tmp_path / "t", slab)

    assert guide_verification(record)["verified"] is False

    for _ in range(2):
        trial = start_guide_trial(record)
        fill(trial)
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
        )
        status = guide_verification(record)

    assert status["verified"] is True
    assert status["passing_trials"] == 2
    assert status["needed"] == 2


def test_one_trial_does_not_verify_and_a_failed_one_does_not_count(
    slab: Path, tmp_path: Path
) -> None:
    (tmp_path / "t").mkdir()
    record = build(tmp_path / "t", slab)
    trial = start_guide_trial(record)
    fill(trial)
    complete_guide_trial(
        trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
    )
    failing = start_guide_trial(record)
    fill(failing, result="fail")
    complete_guide_trial(
        failing, disposition=GuideTrialDisposition.FAIL, material_profile_id="petg"
    )
    status = guide_verification(record)

    assert status["verified"] is False
    assert status["passing_trials"] == 1
    assert [t["disposition"] for t in status["trials"]] == ["pass", "fail"]


def test_trials_of_an_earlier_build_do_not_verify_a_changed_record(
    slab: Path, tmp_path: Path
) -> None:
    (tmp_path / "t").mkdir()
    record = build(tmp_path / "t", slab)

    for _ in range(2):
        trial = start_guide_trial(record)
        fill(trial)
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
        )

    assert guide_verification(record)["verified"] is True

    changed = record_of(record)
    changed["identifier"] = "SOMETHING_ELSE"
    record.write_text(json.dumps(changed))
    status = guide_verification(record)

    assert status["verified"] is False
    assert not any(t["of_this_build"] for t in status["trials"])


def test_a_pass_needs_a_stated_tolerance_and_every_bore_within_it(
    slab: Path, tmp_path: Path
) -> None:
    # Before, both bores 5 mm off still passed and verified the guide.
    (tmp_path / "a").mkdir()
    printed = build(tmp_path / "a", slab)
    trial = start_guide_trial(printed)
    template = json.loads((trial / "measurements.json").read_text())

    assert template["position_tolerance_mm"] is None
    assert all(
        bore["predicted_play_mm"] is not None for bore in template["bores"].values()
    )

    fill(trial, offsets={"B1": (5.0, 0.0), "B2": (0.0, 5.0)})

    with pytest.raises(ValueError, match=r"within 0.5 mm; these are farther off: B1"):
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
        )

    fill(trial, tolerance=None)

    with pytest.raises(ValueError, match="states position_tolerance_mm"):
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.PASS, material_profile_id="petg"
        )

    # A failed trial records how far off it was, with no tolerance needed.
    fill(trial, result="fail", offsets={"B1": (5.0, 0.0)}, tolerance=None)
    record = json.loads(
        complete_guide_trial(
            trial, disposition=GuideTrialDisposition.FAIL, material_profile_id="petg"
        ).read_text()
    )

    assert record["passed"] is False
    assert record["summary"]["max_radial_mm"] == pytest.approx(5.0)

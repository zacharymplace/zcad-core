"""Fixture revisions proposed from trial measurements."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zcad_core.cli import main
from zcad_core.retention import (
    PhysicalValidationCheck,
    PhysicalValidationDisposition,
    PhysicalValidationObservation,
    RevisionRelationshipType,
    complete_physical_validation_record,
    propose_fixture_revision,
    write_measurement_feedback,
    write_physical_validation_record,
)
from zcad_core.validation.measurements import PhysicalMeasurement

POLICY = {
    "arm_width_mm": 3.0,
    "board_clearance_mm": 0.25,
    "engagement_depth_mm": 2.0,
    "minimum_wall_mm": 1.2,
    "vertical_overlap_mm": 0.6,
}


def candidate(
    tmp_path: Path,
    measurements: dict[str, tuple[float, float]],
    *,
    failed: tuple[PhysicalValidationCheck, ...] = (),
    policy: dict[str, float] | None = None,
) -> Path:
    """A registered candidate with trial-001 recorded."""

    directory = tmp_path / "r001"
    trial = directory / "trials" / "trial-001"
    trial.mkdir(parents=True)
    (directory / "candidate.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "candidate_id": "board-corner-capture-r001",
                "target_id": "board",
                "revision": "r001",
                "source_sha256": "a" * 64,
                "output_sha256": "b" * 64,
                "git_commit": "c" * 40,
                "generator_version": "1.4.0",
                "retention_policy": policy or POLICY,
                "derived_parameters": {**(policy or POLICY), "board_thickness_mm": 1.6},
                "selected_corners": ["negative_x_negative_y", "positive_x_positive_y"],
                "automated_decision": "verified_candidate",
                "automated_evidence_path": "automated-validation.json",
                "fixture_artifact_path": "fixture.stl",
                "created_at_utc": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    record = complete_physical_validation_record(
        candidate_report_path=directory / "automated-validation.json",
        fixture_stl_path=directory / "fixture.stl",
        printer_profile="bambu-lab-a1-mini",
        material_profile="petg",
        slicer_profile="bambu-studio-a1-mini-petg-validation",
        observations=tuple(
            PhysicalValidationObservation(check=check, passed=check not in failed)
            for check in PhysicalValidationCheck
        ),
        disposition=PhysicalValidationDisposition.REVISE,
        operator_notes="",
        measurements=tuple(
            PhysicalMeasurement(name=name, value_mm=value, nominal_mm=nominal)
            for name, (nominal, value) in measurements.items()
        ),
    )
    write_physical_validation_record(
        record, output_path=trial / "physical-validation.json"
    )

    return directory


def test_a_tight_side_gap_loosens_the_clearance_and_holds_the_play(
    tmp_path: Path,
) -> None:
    proposal = propose_fixture_revision(
        candidate(tmp_path, {"board_clearance": (0.25, 0.15)})
    )

    assert proposal.updates == {
        "board_clearance_mm": 0.35,
        # The ledge would rise 0.10 mm with the clearance; the overlap drops
        # by as much, since vertical play was not measured.
        "vertical_overlap_mm": 0.5,
    }
    assert proposal.relationship is RevisionRelationshipType.ADJUSTS_CLEARANCE_FROM
    assert proposal.reason == (
        "trial-001 of board-corner-capture-r001: board_clearance measured 0.15 mm "
        "against 0.25 nominal."
    )


def test_vertical_play_is_aimed_back_at_its_nominal(tmp_path: Path) -> None:
    proposal = propose_fixture_revision(
        candidate(
            tmp_path,
            {"board_clearance": (0.25, 0.15), "vertical_play": (0.85, 1.05)},
        )
    )

    # Play printed 0.20 mm loose, so the modelled play drops to 0.65 mm;
    # with the clearance at 0.35 mm that leaves a 0.30 mm overlap, which the
    # 0.40 mm manufacturing minimum raises.
    assert proposal.updates == {
        "board_clearance_mm": 0.35,
        "vertical_overlap_mm": 0.4,
    }
    (_, overlap) = proposal.changes
    assert overlap.measurement == "vertical_play"
    assert "0.20 mm loose" in overlap.reason


def test_changes_respect_the_manufacturing_minimums(tmp_path: Path) -> None:
    proposal = propose_fixture_revision(
        candidate(
            tmp_path,
            {"board_clearance": (0.25, 0.45), "vertical_play": (0.85, 1.4)},
        )
    )

    assert proposal.updates["board_clearance_mm"] == 0.2
    assert proposal.updates["vertical_overlap_mm"] == 0.4


def test_one_revision_moves_a_fit_at_most_half_a_millimetre(tmp_path: Path) -> None:
    proposal = propose_fixture_revision(
        candidate(tmp_path, {"board_clearance": (0.25, -0.75)})
    )

    assert proposal.updates["board_clearance_mm"] == 0.75


def test_gauge_noise_changes_nothing(tmp_path: Path) -> None:
    proposal = propose_fixture_revision(
        candidate(
            tmp_path, {"board_clearance": (0.25, 0.23), "vertical_play": (0.85, 0.87)}
        )
    )

    assert proposal.changes == ()
    assert proposal.notes == ("The trial found nothing to change.",)


def test_failed_checks_and_closed_part_gaps_become_notes(tmp_path: Path) -> None:
    proposal = propose_fixture_revision(
        candidate(
            tmp_path,
            {"clip_to_header_gap": (0.25, 0.0)},
            failed=(PhysicalValidationCheck.COMPONENTS_REMAIN_CLEAR,),
        )
    )

    assert proposal.changes == ()
    assert [note.split(":")[0] for note in proposal.notes] == [
        "components_remain_clear",
        "clip_to_header_gap",
    ]


def test_refuses_a_pending_trial(tmp_path: Path) -> None:
    directory = candidate(tmp_path, {"board_clearance": (0.25, 0.15)})
    trial = directory / "trials" / "trial-001" / "physical-validation.json"
    payload = json.loads(trial.read_text("utf-8"))
    payload.update(disposition="pending", completed_at_utc="", measurements=[])
    payload["observations"] = [
        {**entry, "passed": False} for entry in payload["observations"]
    ]
    trial.write_text(json.dumps(payload), "utf-8")

    with pytest.raises(ValueError, match="has not been recorded yet"):
        propose_fixture_revision(directory)


def test_feedback_traces_each_change_to_its_measurement(tmp_path: Path) -> None:
    proposal = propose_fixture_revision(
        candidate(tmp_path, {"board_clearance": (0.25, 0.15)})
    )
    revision = tmp_path / "r002"
    revision.mkdir()

    path = write_measurement_feedback(proposal, revision)
    record = json.loads(path.read_text("utf-8"))

    assert record["parent_candidate_id"] == "board-corner-capture-r001"
    assert record["changes"][0] == {
        "parameter": "board_clearance_mm",
        "previous_value": 0.25,
        "current_value": 0.35,
        "measurement": "board_clearance",
        "nominal_mm": 0.25,
        "measured_mm": 0.15,
        "reason": "The side gap printed 0.10 mm tight.",
    }
    assert len(record["physical_validation_sha256"]) == 64
    with pytest.raises(FileExistsError):
        write_measurement_feedback(proposal, revision)


def test_cli_proposes_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = candidate(tmp_path, {"board_clearance": (0.25, 0.15)})
    before = sorted(path.name for path in directory.rglob("*"))

    exit_code = main(["revision", "propose", "--candidate-directory", str(directory)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert [change["parameter"] for change in output["changes"]] == [
        "board_clearance_mm",
        "vertical_overlap_mm",
    ]
    assert "--from-trial trial-001" in output["regenerate"]
    assert sorted(path.name for path in directory.rglob("*")) == before

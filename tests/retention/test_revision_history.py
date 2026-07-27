from __future__ import annotations

import json
from pathlib import Path

import pytest

from zcad_core.retention.revision_history import (
    ParameterDelta,
    RevisionDeltaReport,
    RevisionRelationship,
    RevisionRelationshipType,
    compare_candidate_parameters,
    write_revision_delta_report,
    write_revision_relationship,
)


def valid_relationship() -> RevisionRelationship:
    return RevisionRelationship(
        schema_version="1.0.0",
        target_id="adafruit-feather-rp2040",
        source_candidate_id=("adafruit-feather-rp2040-corner-capture-r002"),
        target_candidate_id=("adafruit-feather-rp2040-corner-capture-r001"),
        relationship=(RevisionRelationshipType.SUPERSEDES),
        reason="Increased board clearance.",
        created_at_utc=("2026-07-27T04:00:00+00:00"),
    )


def test_relationship_accepts_distinct_candidates() -> None:
    relationship = valid_relationship()

    assert relationship.relationship is (RevisionRelationshipType.SUPERSEDES)


def test_relationship_rejects_self_reference() -> None:
    candidate_id = "adafruit-feather-rp2040-corner-capture-r001"

    with pytest.raises(
        ValueError,
        match="cannot reference itself",
    ):
        RevisionRelationship(
            schema_version="1.0.0",
            target_id="adafruit-feather-rp2040",
            source_candidate_id=candidate_id,
            target_candidate_id=candidate_id,
            relationship=(RevisionRelationshipType.RETRIES),
            reason="Retry.",
            created_at_utc=("2026-07-27T04:00:00+00:00"),
        )


def test_parameter_delta_reports_change() -> None:
    delta = ParameterDelta(
        parameter="board_clearance_mm",
        previous_value=0.20,
        current_value=0.25,
    )

    assert delta.change == pytest.approx(0.05)


def test_parameter_comparison_is_sorted() -> None:
    report = compare_candidate_parameters(
        source_candidate_id="candidate-r001",
        target_candidate_id="candidate-r002",
        source_parameters={
            "vertical_overlap_mm": 0.4,
            "board_clearance_mm": 0.2,
            "minimum_wall_mm": 1.2,
        },
        target_parameters={
            "vertical_overlap_mm": 0.6,
            "board_clearance_mm": 0.25,
            "minimum_wall_mm": 1.2,
        },
    )

    assert report.changed is True
    assert tuple(change.parameter for change in report.changes) == (
        "board_clearance_mm",
        "vertical_overlap_mm",
    )


def test_unchanged_parameters_are_omitted() -> None:
    report = compare_candidate_parameters(
        source_candidate_id="candidate-r001",
        target_candidate_id="candidate-r002",
        source_parameters={
            "minimum_wall_mm": 1.2,
        },
        target_parameters={
            "minimum_wall_mm": 1.2,
        },
    )

    assert report == RevisionDeltaReport(
        source_candidate_id="candidate-r001",
        target_candidate_id="candidate-r002",
        changes=(),
    )
    assert report.changed is False


def test_non_shared_parameters_are_ignored() -> None:
    report = compare_candidate_parameters(
        source_candidate_id="candidate-r001",
        target_candidate_id="candidate-r002",
        source_parameters={
            "board_clearance_mm": 0.2,
            "legacy_parameter_mm": 1.0,
        },
        target_parameters={
            "board_clearance_mm": 0.25,
            "new_parameter_mm": 2.0,
        },
    )

    assert tuple(change.parameter for change in report.changes) == (
        "board_clearance_mm",
    )


def test_relationship_write_is_idempotent(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "relationship.json"

    write_revision_relationship(
        valid_relationship(),
        output_path=output_path,
    )
    write_revision_relationship(
        valid_relationship(),
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["relationship"] == "supersedes"


def test_relationship_write_rejects_conflict(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "relationship.json"

    write_revision_relationship(
        valid_relationship(),
        output_path=output_path,
    )

    changed = RevisionRelationship(
        schema_version="1.0.0",
        target_id="adafruit-feather-rp2040",
        source_candidate_id=("adafruit-feather-rp2040-corner-capture-r002"),
        target_candidate_id=("adafruit-feather-rp2040-corner-capture-r001"),
        relationship=(RevisionRelationshipType.SUPERSEDES),
        reason="Different reason.",
        created_at_utc=("2026-07-27T04:00:00+00:00"),
    )

    with pytest.raises(
        FileExistsError,
        match="immutable revision record",
    ):
        write_revision_relationship(
            changed,
            output_path=output_path,
        )


def changed_report() -> RevisionDeltaReport:
    return compare_candidate_parameters(
        source_candidate_id="candidate-r001",
        target_candidate_id="candidate-r002",
        source_parameters={
            "board_clearance_mm": 0.20,
            "vertical_overlap_mm": 0.40,
        },
        target_parameters={
            "board_clearance_mm": 0.25,
            "vertical_overlap_mm": 0.60,
        },
    )


def test_delta_report_write_is_idempotent(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "parameter-delta.json"

    write_revision_delta_report(
        changed_report(),
        output_path=output_path,
    )
    write_revision_delta_report(
        changed_report(),
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["changed"] is True
    assert tuple(item["parameter"] for item in payload["changes"]) == (
        "board_clearance_mm",
        "vertical_overlap_mm",
    )


def test_delta_report_records_signed_change(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "parameter-delta.json"

    write_revision_delta_report(
        changed_report(),
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    changes = {item["parameter"]: item for item in payload["changes"]}

    assert changes["board_clearance_mm"]["change"] == pytest.approx(0.05)

    assert changes["vertical_overlap_mm"]["change"] == pytest.approx(0.20)

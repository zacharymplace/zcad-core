from pathlib import Path

from zcad_core.retention import (
    RevisionRegistrationResult,
    RevisionRelationshipType,
)
from zcad_core.retention.revision_history import (
    RevisionDeltaReport,
    RevisionRelationship,
)
from zcad_core.retention.validation_lab import (
    CandidateRevision,
)


def test_registration_result_fields() -> None:
    candidate = CandidateRevision(
        schema_version="1.0.0",
        candidate_id=("synthetic-target-corner-capture-r001"),
        target_id="synthetic-target",
        revision="r001",
        source_sha256="a" * 64,
        output_sha256="b" * 64,
        git_commit="c" * 40,
        generator_version="1.0.0",
        retention_policy={
            "arm_width_mm": 3.0,
            "board_clearance_mm": 0.25,
            "engagement_depth_mm": 2.0,
            "minimum_wall_mm": 1.2,
            "vertical_overlap_mm": 0.6,
        },
        derived_parameters={
            "arm_width_mm": 3.0,
            "board_clearance_mm": 0.25,
            "board_thickness_mm": 1.57,
            "engagement_depth_mm": 2.0,
            "minimum_wall_mm": 1.2,
            "vertical_overlap_mm": 0.6,
        },
        selected_corners=(
            "negative_x_negative_y",
            "positive_x_positive_y",
        ),
        automated_decision="synthetic",
        automated_evidence_path="evidence.json",
        fixture_artifact_path="fixture.stl",
        created_at_utc="2026-01-01T00:00:00+00:00",
    )

    relationship = RevisionRelationship(
        schema_version="1.0.0",
        target_id="synthetic-target",
        source_candidate_id=("synthetic-target-corner-capture-r002"),
        target_candidate_id=candidate.candidate_id,
        relationship=(RevisionRelationshipType.SUPERSEDES),
        reason="Synthetic test revision.",
        created_at_utc="2026-01-01T00:00:00+00:00",
    )

    delta_report = RevisionDeltaReport(
        source_candidate_id=candidate.candidate_id,
        target_candidate_id=("synthetic-target-corner-capture-r002"),
        changes=(),
    )

    result = RevisionRegistrationResult(
        candidate=candidate,
        relationship=relationship,
        delta_report=delta_report,
        candidate_path=Path("candidate.json"),
        relationship_path=Path("relationship.json"),
        delta_report_path=Path("parameter-delta.json"),
    )

    assert result.candidate is candidate
    assert result.relationship is relationship
    assert result.delta_report is delta_report
    assert result.candidate_path.name == "candidate.json"
    assert result.relationship_path.name == "relationship.json"
    assert result.delta_report_path.name == "parameter-delta.json"


def valid_candidate_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "candidate_id": ("synthetic-target-corner-capture-r001"),
        "target_id": "synthetic-target",
        "revision": "r001",
        "source_sha256": "a" * 64,
        "output_sha256": "b" * 64,
        "git_commit": "c" * 40,
        "generator_version": "1.0.0",
        "retention_policy": {
            "arm_width_mm": 3.0,
            "board_clearance_mm": 0.25,
            "engagement_depth_mm": 2.0,
            "minimum_wall_mm": 1.2,
            "vertical_overlap_mm": 0.6,
        },
        "derived_parameters": {
            "arm_width_mm": 3.0,
            "board_clearance_mm": 0.25,
            "board_thickness_mm": 1.57,
            "engagement_depth_mm": 2.0,
            "minimum_wall_mm": 1.2,
            "vertical_overlap_mm": 0.6,
        },
        "selected_corners": [
            "negative_x_negative_y",
            "positive_x_positive_y",
        ],
        "automated_decision": "synthetic",
        "automated_evidence_path": ("evidence.json"),
        "fixture_artifact_path": ("fixture.stl"),
        "created_at_utc": ("2026-01-01T00:00:00+00:00"),
    }


def write_candidate_payload(
    path: Path,
    payload: dict[str, object],
) -> None:
    import json

    path.write_text(
        json.dumps(
            payload,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_load_candidate_revision(
    tmp_path: Path,
) -> None:
    from zcad_core.retention import (
        load_candidate_revision,
    )

    path = tmp_path / "candidate.json"
    write_candidate_payload(
        path,
        valid_candidate_payload(),
    )

    candidate = load_candidate_revision(path)

    assert candidate.candidate_id == "synthetic-target-corner-capture-r001"
    assert candidate.retention_policy["board_clearance_mm"] == 0.25
    assert candidate.selected_corners == (
        "negative_x_negative_y",
        "positive_x_positive_y",
    )
    # valid_candidate_payload() has no "strategy" key, so this also
    # confirms loading legacy candidate.json files (written before the
    # strategy field existed) defaults it to "corner-capture".
    assert candidate.strategy == "corner-capture"


def test_load_candidate_revision_rejects_selected_corners(
    tmp_path: Path,
) -> None:
    import pytest

    from zcad_core.retention import (
        load_candidate_revision,
    )

    payload = valid_candidate_payload()
    payload["selected_corners"] = "invalid"

    path = tmp_path / "candidate.json"
    write_candidate_payload(
        path,
        payload,
    )

    with pytest.raises(
        TypeError,
        match=("selected_corners must be a list"),
    ):
        load_candidate_revision(path)


def test_load_candidate_revision_rejects_retention_policy(
    tmp_path: Path,
) -> None:
    import pytest

    from zcad_core.retention import (
        load_candidate_revision,
    )

    payload = valid_candidate_payload()
    payload["retention_policy"] = []

    path = tmp_path / "candidate.json"
    write_candidate_payload(
        path,
        payload,
    )

    with pytest.raises(
        TypeError,
        match=("retention_policy must be an object"),
    ):
        load_candidate_revision(path)


def test_load_candidate_revision_rejects_derived_parameters(
    tmp_path: Path,
) -> None:
    import pytest

    from zcad_core.retention import (
        load_candidate_revision,
    )

    payload = valid_candidate_payload()
    payload["derived_parameters"] = []

    path = tmp_path / "candidate.json"
    write_candidate_payload(
        path,
        payload,
    )

    with pytest.raises(
        TypeError,
        match=("derived_parameters must be an object"),
    ):
        load_candidate_revision(path)


def test_derive_candidate_revision(
    tmp_path: Path,
) -> None:
    from zcad_core.retention import (
        derive_candidate_revision,
        load_candidate_revision,
    )

    path = tmp_path / "candidate.json"
    write_candidate_payload(
        path,
        valid_candidate_payload(),
    )
    parent = load_candidate_revision(path)

    candidate = derive_candidate_revision(
        parent_candidate=parent,
        revision="r002",
        parameter_updates={
            "board_clearance_mm": 0.30,
        },
        automated_decision=("synthetic_revision_candidate"),
    )

    assert candidate.candidate_id == "synthetic-target-corner-capture-r002"
    assert candidate.revision == "r002"
    assert candidate.retention_policy["board_clearance_mm"] == 0.30
    assert candidate.derived_parameters["board_clearance_mm"] == 0.30
    assert candidate.retention_policy["arm_width_mm"] == 3.0
    assert candidate.created_at_utc == (parent.created_at_utc)

    assert parent.retention_policy["board_clearance_mm"] == 0.25
    assert parent.derived_parameters["board_clearance_mm"] == 0.25


def test_derive_candidate_revision_preserves_parent_strategy(
    tmp_path: Path,
) -> None:
    """Regression test: deriving used to hardcode "corner-capture" for the
    child's candidate_id regardless of the parent's actual strategy."""

    from dataclasses import replace

    from zcad_core.retention import (
        derive_candidate_revision,
        load_candidate_revision,
    )

    path = tmp_path / "candidate.json"
    write_candidate_payload(
        path,
        valid_candidate_payload(),
    )
    parent = replace(
        load_candidate_revision(path),
        candidate_id="synthetic-target-edge-clip-r001",
        strategy="edge-clip",
    )

    candidate = derive_candidate_revision(
        parent_candidate=parent,
        revision="r002",
        parameter_updates={
            "board_clearance_mm": 0.30,
        },
        automated_decision=("synthetic_revision_candidate"),
    )

    assert candidate.strategy == "edge-clip"
    assert candidate.candidate_id == "synthetic-target-edge-clip-r002"


def test_derive_candidate_revision_rejects_empty_updates(
    tmp_path: Path,
) -> None:
    import pytest

    from zcad_core.retention import (
        derive_candidate_revision,
        load_candidate_revision,
    )

    path = tmp_path / "candidate.json"
    write_candidate_payload(
        path,
        valid_candidate_payload(),
    )
    parent = load_candidate_revision(path)

    with pytest.raises(
        ValueError,
        match=("parameter_updates cannot be empty"),
    ):
        derive_candidate_revision(
            parent_candidate=parent,
            revision="r002",
            parameter_updates={},
            automated_decision="synthetic",
        )


def test_derive_candidate_revision_rejects_unshared_parameter(
    tmp_path: Path,
) -> None:
    import pytest

    from zcad_core.retention import (
        derive_candidate_revision,
        load_candidate_revision,
    )

    path = tmp_path / "candidate.json"
    write_candidate_payload(
        path,
        valid_candidate_payload(),
    )
    parent = load_candidate_revision(path)

    with pytest.raises(
        ValueError,
        match=(
            "parameter_updates must reference "
            "parameters present in retention_policy "
            "and derived_parameters: "
            "board_thickness_mm"
        ),
    ):
        derive_candidate_revision(
            parent_candidate=parent,
            revision="r002",
            parameter_updates={
                "board_thickness_mm": 1.60,
            },
            automated_decision="synthetic",
        )


def test_register_candidate_revision_is_idempotent(
    tmp_path: Path,
) -> None:
    import json

    from zcad_core.retention import (
        RevisionRelationshipType,
        load_candidate_revision,
        register_candidate_revision,
    )

    parent_path = tmp_path / "r001" / "candidate.json"
    parent_path.parent.mkdir(
        parents=True,
    )
    write_candidate_payload(
        parent_path,
        valid_candidate_payload(),
    )

    parent = load_candidate_revision(parent_path)
    output_directory = tmp_path / "r002"

    first = register_candidate_revision(
        parent_candidate=parent,
        revision="r002",
        parameter_updates={
            "board_clearance_mm": 0.30,
        },
        relationship=(RevisionRelationshipType.SUPERSEDES),
        reason=("Synthetic revision increases board clearance."),
        output_directory=output_directory,
        automated_decision=("synthetic_revision_candidate"),
    )

    second = register_candidate_revision(
        parent_candidate=parent,
        revision="r002",
        parameter_updates={
            "board_clearance_mm": 0.30,
        },
        relationship=(RevisionRelationshipType.SUPERSEDES),
        reason=("Synthetic revision increases board clearance."),
        output_directory=output_directory,
        automated_decision=("synthetic_revision_candidate"),
    )

    assert first == second
    assert first.candidate_path.is_file()
    assert first.relationship_path.is_file()
    assert first.delta_report_path.is_file()

    candidate_payload = json.loads(first.candidate_path.read_text(encoding="utf-8"))
    relationship_payload = json.loads(
        first.relationship_path.read_text(encoding="utf-8")
    )
    delta_payload = json.loads(first.delta_report_path.read_text(encoding="utf-8"))

    assert candidate_payload["candidate_id"] == "synthetic-target-corner-capture-r002"
    assert candidate_payload["derived_parameters"]["board_clearance_mm"] == 0.30
    assert relationship_payload["relationship"] == "supersedes"
    assert relationship_payload["target_candidate_id"] == parent.candidate_id
    assert delta_payload["changed"] is True
    assert delta_payload["changes"][0]["parameter"] == "board_clearance_mm"

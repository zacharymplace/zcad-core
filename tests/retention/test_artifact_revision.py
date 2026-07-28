from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention import (
    CandidateRevision,
    RevisionRelationshipType,
    load_candidate_revision,
    register_artifact_backed_revision,
    sha256_file,
)


def export_clear_board(
    path: Path,
) -> None:
    pcb = (
        cq.Workplane("XY")
        .box(
            40.0,
            30.0,
            1.6,
        )
        .translate(
            (
                0.0,
                0.0,
                0.8,
            )
        )
    )

    assembly = cq.Assembly()
    assembly.add(
        pcb,
        name="pcb",
    )
    assembly.save(
        str(path),
        exportType="STEP",
    )


def parent_candidate() -> CandidateRevision:
    return CandidateRevision(
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
            "board_thickness_mm": 1.6,
            "engagement_depth_mm": 2.0,
            "minimum_wall_mm": 1.2,
            "vertical_overlap_mm": 0.6,
        },
        selected_corners=(
            "negative_x_negative_y",
            "positive_x_positive_y",
        ),
        automated_decision="synthetic",
        automated_evidence_path="r001/evidence.json",
        fixture_artifact_path="r001/fixture.stl",
        created_at_utc="2026-01-01T00:00:00+00:00",
    )


def test_registers_artifact_backed_revision(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    output_directory = tmp_path / "r002"

    export_clear_board(source_step)

    result = register_artifact_backed_revision(
        parent_candidate=parent_candidate(),
        revision="r002",
        parameter_updates={
            "board_clearance_mm": 0.30,
        },
        relationship=(RevisionRelationshipType.ADJUSTS_CLEARANCE_FROM),
        reason=("Increase board clearance after physical fit review."),
        output_directory=output_directory,
        source_step=source_step,
        pcb_solid_index=1,
        git_commit="d" * 40,
        generator_version="1.1.0",
        created_at_utc=("2026-01-02T00:00:00+00:00"),
    )

    candidate = result.candidate

    assert candidate.revision == "r002"
    assert candidate.automated_decision == ("verified_candidate")
    assert candidate.output_sha256 != (parent_candidate().output_sha256)
    assert candidate.output_sha256 == sha256_file(output_directory / "retention.step")
    assert candidate.source_sha256 == sha256_file(source_step)
    assert candidate.retention_policy["board_clearance_mm"] == 0.30
    assert candidate.derived_parameters["board_clearance_mm"] == 0.30

    for name in (
        "retention.step",
        "automated-validation.json",
        "fixture.stl",
        "candidate.json",
        "relationship.json",
        "parameter-delta.json",
    ):
        artifact = output_directory / name
        assert artifact.is_file()
        assert artifact.stat().st_size > 0

    persisted = load_candidate_revision(output_directory / "candidate.json")

    assert persisted == candidate

    report = json.loads(
        (output_directory / "automated-validation.json").read_text(
            encoding="utf-8",
        )
    )

    assert report["decision"] == ("verified_candidate")
    assert report["policy"]["board_clearance_mm"] == 0.30


def test_refuses_existing_revision_outputs(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    output_directory = tmp_path / "r002"

    export_clear_board(source_step)
    output_directory.mkdir()
    existing = output_directory / "candidate.json"
    existing.write_text(
        "{}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        FileExistsError,
        match=("Refusing to overwrite artifact-backed revision outputs"),
    ):
        register_artifact_backed_revision(
            parent_candidate=parent_candidate(),
            revision="r002",
            parameter_updates={
                "board_clearance_mm": 0.30,
            },
            relationship=(RevisionRelationshipType.ADJUSTS_CLEARANCE_FROM),
            reason="Synthetic test.",
            output_directory=output_directory,
            source_step=source_step,
            pcb_solid_index=1,
            git_commit="d" * 40,
            generator_version="1.1.0",
            created_at_utc=("2026-01-02T00:00:00+00:00"),
        )

    assert (
        existing.read_text(
            encoding="utf-8",
        )
        == "{}\n"
    )
    assert not (output_directory / "retention.step").exists()

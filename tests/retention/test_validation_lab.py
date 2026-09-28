from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from zcad_core.retention import (
    CandidateRevision,
    PhysicalTrialManifest,
    ValidationTarget,
    candidate_identifier,
    load_manifest,
    sha256_file,
    write_immutable_manifest,
)

SHA256_A = "a" * 64
SHA256_B = "b" * 64


def valid_target() -> ValidationTarget:
    return ValidationTarget(
        schema_version="1.0.0",
        target_id="adafruit-feather-rp2040",
        display_name="Adafruit Feather RP2040",
        manufacturer="Adafruit",
        product_family="Feather",
        source_model_path=("evidence/adafruit-feather-rp2040/4884 Feather RP2040.step"),
        source_model_sha256=SHA256_A,
        pcb_solid_index=1,
        created_at_utc="2026-07-27T00:00:00+00:00",
    )


def valid_candidate() -> CandidateRevision:
    return CandidateRevision(
        schema_version="1.0.0",
        candidate_id=("adafruit-feather-rp2040-corner-capture-r001"),
        target_id="adafruit-feather-rp2040",
        revision="r001",
        source_sha256=SHA256_A,
        output_sha256=SHA256_B,
        git_commit="abc123",
        generator_version="1.0.0",
        retention_policy={
            "arm_width_mm": 3.0,
            "board_clearance_mm": 0.25,
        },
        derived_parameters={
            "board_thickness_mm": 1.6,
            "vertical_overlap_mm": 0.6,
        },
        selected_corners=(
            "negative_x_negative_y",
            "positive_x_positive_y",
        ),
        automated_decision="verified_candidate",
        automated_evidence_path="automated-validation.json",
        fixture_artifact_path="fixture.stl",
        created_at_utc="2026-07-27T00:00:00+00:00",
    )


def valid_trial() -> PhysicalTrialManifest:
    return PhysicalTrialManifest(
        schema_version="1.0.0",
        trial_id="trial-001",
        candidate_id=("adafruit-feather-rp2040-corner-capture-r001"),
        physical_validation_path="physical-validation.json",
        fixture_artifact_path="fixture.stl",
        printer_profile="pending-selection",
        material_profile="pending-selection",
        slicer_profile="pending-selection",
        disposition="revise",
        complete=True,
        passed=False,
        created_at_utc="2026-07-27T00:00:00+00:00",
    )


def test_candidate_identifier_is_deterministic() -> None:
    result = candidate_identifier(
        target_id="adafruit-feather-rp2040",
        strategy="corner-capture",
        revision="r001",
    )

    assert result == ("adafruit-feather-rp2040-corner-capture-r001")


@pytest.mark.parametrize(
    ("revision", "expected_valid"),
    (
        ("r001", True),
        ("r999", True),
        ("1", False),
        ("r1", False),
        ("R001", False),
        ("r1000", False),
    ),
)
def test_revision_format(
    revision: str,
    expected_valid: bool,
) -> None:
    if expected_valid:
        candidate = replace(
            valid_candidate(),
            revision=revision,
            candidate_id=(f"adafruit-feather-rp2040-corner-capture-{revision}"),
        )

        assert candidate.revision == revision
        return

    with pytest.raises(
        ValueError,
        match="revision",
    ):
        replace(
            valid_candidate(),
            revision=revision,
        )


def test_target_rejects_invalid_sha256() -> None:
    with pytest.raises(
        ValueError,
        match="source_model_sha256",
    ):
        replace(
            valid_target(),
            source_model_sha256="invalid",
        )


def test_candidate_identity_must_match_revision() -> None:
    with pytest.raises(
        ValueError,
        match="candidate_id",
    ):
        replace(
            valid_candidate(),
            candidate_id="incorrect-r001",
        )


def test_candidate_defaults_to_corner_capture_strategy() -> None:
    assert valid_candidate().strategy == "corner-capture"


def test_candidate_identity_reflects_a_different_strategy() -> None:
    """A candidate_id must match its own declared strategy, not a fixed one.

    Regression test: CandidateRevision.__post_init__ used to hardcode
    "corner-capture" when recomputing the expected candidate_id, so no
    other retention strategy (e.g. edge-clip) could ever construct a
    self-consistent candidate.
    """

    candidate = replace(
        valid_candidate(),
        candidate_id="adafruit-feather-rp2040-edge-clip-r001",
        strategy="edge-clip",
    )

    assert candidate.strategy == "edge-clip"


def test_candidate_rejects_strategy_mismatched_with_id() -> None:
    with pytest.raises(
        ValueError,
        match="candidate_id",
    ):
        replace(
            valid_candidate(),
            strategy="edge-clip",
        )


def test_candidate_rejects_non_kebab_case_strategy() -> None:
    with pytest.raises(
        ValueError,
        match="strategy must be lowercase kebab-case",
    ):
        replace(
            valid_candidate(),
            candidate_id="adafruit-feather-rp2040-Edge_Clip-r001",
            strategy="Edge_Clip",
        )


def test_incomplete_trial_cannot_pass() -> None:
    with pytest.raises(
        ValueError,
        match="Incomplete",
    ):
        replace(
            valid_trial(),
            complete=False,
            passed=True,
            disposition="pass",
        )


def test_passing_trial_requires_pass_disposition() -> None:
    with pytest.raises(
        ValueError,
        match="pass disposition",
    ):
        replace(
            valid_trial(),
            passed=True,
            disposition="revise",
        )


def test_pending_trial_cannot_be_complete() -> None:
    with pytest.raises(
        ValueError,
        match="Pending physical trial cannot be complete",
    ):
        replace(
            valid_trial(),
            disposition="pending",
            complete=True,
        )

    pending = replace(valid_trial(), disposition="pending", complete=False)

    assert pending.pending is True
    assert pending.passed is False


def test_manifest_write_is_idempotent(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "target.json"

    write_immutable_manifest(
        valid_target(),
        output_path=output_path,
    )
    write_immutable_manifest(
        valid_target(),
        output_path=output_path,
    )

    payload = load_manifest(output_path)

    assert payload["target_id"] == ("adafruit-feather-rp2040")


def test_manifest_refuses_different_overwrite(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "target.json"

    write_immutable_manifest(
        valid_target(),
        output_path=output_path,
    )

    with pytest.raises(
        FileExistsError,
        match="immutable",
    ):
        write_immutable_manifest(
            replace(
                valid_target(),
                display_name="Changed",
            ),
            output_path=output_path,
        )


def test_sha256_file_is_deterministic(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"zcad-core")

    first = sha256_file(path)
    second = sha256_file(path)

    assert first == second
    assert len(first) == 64

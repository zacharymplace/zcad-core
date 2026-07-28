from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_TARGET_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REVISION_PATTERN = re.compile(r"^r[0-9]{3}$")
_TRIAL_PATTERN = re.compile(r"^trial-[0-9]{3}$")


@dataclass(frozen=True)
class ValidationTarget:
    schema_version: str
    target_id: str
    display_name: str
    manufacturer: str
    product_family: str
    source_model_path: str
    source_model_sha256: str
    pcb_solid_index: int
    created_at_utc: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("Unsupported validation target schema")

        if not _TARGET_ID_PATTERN.fullmatch(self.target_id):
            raise ValueError("target_id must be lowercase kebab-case")

        for field_name, value in (
            ("display_name", self.display_name),
            ("manufacturer", self.manufacturer),
            ("product_family", self.product_family),
            (
                "source_model_path",
                self.source_model_path,
            ),
            ("created_at_utc", self.created_at_utc),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

        _validate_sha256(
            self.source_model_sha256,
            field_name="source_model_sha256",
        )

        if self.pcb_solid_index < 0:
            raise ValueError("pcb_solid_index cannot be negative")


@dataclass(frozen=True)
class CandidateRevision:
    schema_version: str
    candidate_id: str
    target_id: str
    revision: str
    source_sha256: str
    output_sha256: str
    git_commit: str
    generator_version: str
    retention_policy: dict[str, float]
    derived_parameters: dict[str, Any]
    selected_corners: tuple[str, ...]
    automated_decision: str
    automated_evidence_path: str
    fixture_artifact_path: str
    created_at_utc: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("Unsupported candidate revision schema")

        if not _TARGET_ID_PATTERN.fullmatch(self.target_id):
            raise ValueError("target_id must be lowercase kebab-case")

        if not _REVISION_PATTERN.fullmatch(self.revision):
            raise ValueError("revision must match rNNN")

        expected_candidate_id = candidate_identifier(
            target_id=self.target_id,
            strategy="corner-capture",
            revision=self.revision,
        )

        if self.candidate_id != expected_candidate_id:
            raise ValueError(
                "candidate_id does not match target, strategy, and revision"
            )

        _validate_sha256(
            self.source_sha256,
            field_name="source_sha256",
        )
        _validate_sha256(
            self.output_sha256,
            field_name="output_sha256",
        )

        required_text = (
            ("git_commit", self.git_commit),
            (
                "generator_version",
                self.generator_version,
            ),
            (
                "automated_decision",
                self.automated_decision,
            ),
            (
                "automated_evidence_path",
                self.automated_evidence_path,
            ),
            (
                "fixture_artifact_path",
                self.fixture_artifact_path,
            ),
            (
                "created_at_utc",
                self.created_at_utc,
            ),
        )

        for field_name, value in required_text:
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

        if not self.retention_policy:
            raise ValueError("retention_policy cannot be empty")

        if not self.derived_parameters:
            raise ValueError("derived_parameters cannot be empty")

        if not self.selected_corners:
            raise ValueError("selected_corners cannot be empty")


@dataclass(frozen=True)
class PhysicalTrialManifest:
    schema_version: str
    trial_id: str
    candidate_id: str
    physical_validation_path: str
    fixture_artifact_path: str
    printer_profile: str
    material_profile: str
    slicer_profile: str
    disposition: str
    complete: bool
    passed: bool
    created_at_utc: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("Unsupported physical trial schema")

        if not _TRIAL_PATTERN.fullmatch(self.trial_id):
            raise ValueError("trial_id must match trial-NNN")

        required_text = (
            ("candidate_id", self.candidate_id),
            (
                "physical_validation_path",
                self.physical_validation_path,
            ),
            (
                "fixture_artifact_path",
                self.fixture_artifact_path,
            ),
            ("printer_profile", self.printer_profile),
            ("material_profile", self.material_profile),
            ("slicer_profile", self.slicer_profile),
            ("disposition", self.disposition),
            ("created_at_utc", self.created_at_utc),
        )

        for field_name, value in required_text:
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

        if self.passed and not self.complete:
            raise ValueError("Incomplete physical trial cannot pass")

        if self.passed and self.disposition != "pass":
            raise ValueError("Passing physical trial requires pass disposition")


def candidate_identifier(
    *,
    target_id: str,
    strategy: str,
    revision: str,
) -> str:
    if not _TARGET_ID_PATTERN.fullmatch(target_id):
        raise ValueError("target_id must be lowercase kebab-case")

    if not _TARGET_ID_PATTERN.fullmatch(strategy):
        raise ValueError("strategy must be lowercase kebab-case")

    if not _REVISION_PATTERN.fullmatch(revision):
        raise ValueError("revision must match rNNN")

    return f"{target_id}-{strategy}-{revision}"


def sha256_file(
    path: Path,
) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def write_immutable_manifest(
    value: ValidationTarget | CandidateRevision | PhysicalTrialManifest,
    *,
    output_path: Path,
) -> None:
    payload = asdict(value)
    serialized = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")

        if existing == serialized:
            return

        raise FileExistsError(
            f"Refusing to overwrite immutable manifest: {output_path}"
        )

    output_path.write_text(
        serialized,
        encoding="utf-8",
    )


def load_manifest(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)

    value = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(value, dict):
        raise TypeError("Manifest root must be an object")

    return value


def _validate_sha256(
    value: str,
    *,
    field_name: str,
) -> None:
    if len(value) != 64:
        raise ValueError(f"{field_name} must contain 64 hexadecimal characters")

    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"{field_name} must be hexadecimal") from error

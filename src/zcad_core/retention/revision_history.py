from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class RevisionRelationshipType(str, Enum):
    """Supported relationships between candidate revisions."""

    SUPERSEDES = "supersedes"
    RETRIES = "retries"
    ADJUSTS_CLEARANCE_FROM = "adjusts_clearance_from"
    ADJUSTS_OVERLAP_FROM = "adjusts_overlap_from"
    ADJUSTS_WALL_FROM = "adjusts_wall_from"
    DERIVED_FROM = "derived_from"
    INVALIDATES = "invalidates"


@dataclass(frozen=True)
class RevisionRelationship:
    """Immutable typed relationship between two revisions."""

    schema_version: str
    target_id: str
    source_candidate_id: str
    target_candidate_id: str
    relationship: RevisionRelationshipType
    reason: str
    created_at_utc: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("Unsupported revision relationship schema")

        if self.source_candidate_id == self.target_candidate_id:
            raise ValueError("Revision relationship cannot reference itself")

        for field_name, value in (
            ("target_id", self.target_id),
            ("source_candidate_id", self.source_candidate_id),
            ("target_candidate_id", self.target_candidate_id),
            ("reason", self.reason),
            ("created_at_utc", self.created_at_utc),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")


@dataclass(frozen=True)
class ParameterDelta:
    """One measured parameter change between revisions."""

    parameter: str
    previous_value: float
    current_value: float

    @property
    def change(self) -> float:
        return self.current_value - self.previous_value


@dataclass(frozen=True)
class RevisionDeltaReport:
    """Deterministic parameter comparison between revisions."""

    source_candidate_id: str
    target_candidate_id: str
    changes: tuple[ParameterDelta, ...]

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def compare_candidate_parameters(
    *,
    source_candidate_id: str,
    target_candidate_id: str,
    source_parameters: dict[str, float],
    target_parameters: dict[str, float],
) -> RevisionDeltaReport:
    """Compare shared numeric parameters deterministically."""

    shared_parameters = sorted(set(source_parameters) & set(target_parameters))

    changes = tuple(
        ParameterDelta(
            parameter=parameter,
            previous_value=float(source_parameters[parameter]),
            current_value=float(target_parameters[parameter]),
        )
        for parameter in shared_parameters
        if float(source_parameters[parameter]) != float(target_parameters[parameter])
    )

    return RevisionDeltaReport(
        source_candidate_id=source_candidate_id,
        target_candidate_id=target_candidate_id,
        changes=changes,
    )


def write_revision_relationship(
    relationship: RevisionRelationship,
    *,
    output_path: Path,
) -> None:
    """Write one immutable revision relationship."""

    payload = {
        "schema_version": relationship.schema_version,
        "target_id": relationship.target_id,
        "source_candidate_id": (relationship.source_candidate_id),
        "target_candidate_id": (relationship.target_candidate_id),
        "relationship": relationship.relationship.value,
        "reason": relationship.reason,
        "created_at_utc": relationship.created_at_utc,
    }

    _write_immutable_json(
        payload,
        output_path=output_path,
    )


def write_revision_delta_report(
    report: RevisionDeltaReport,
    *,
    output_path: Path,
) -> None:
    """Write one immutable parameter-delta report."""

    payload = {
        "schema_version": "1.0.0",
        "source_candidate_id": (report.source_candidate_id),
        "target_candidate_id": (report.target_candidate_id),
        "changed": report.changed,
        "changes": [
            {
                "parameter": change.parameter,
                "previous_value": (change.previous_value),
                "current_value": (change.current_value),
                "change": change.change,
            }
            for change in report.changes
        ],
    }

    _write_immutable_json(
        payload,
        output_path=output_path,
    )


def _write_immutable_json(
    payload: dict[str, object],
    *,
    output_path: Path,
) -> None:
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
            f"Refusing to overwrite immutable revision record: {output_path}"
        )

    output_path.write_text(
        serialized,
        encoding="utf-8",
    )

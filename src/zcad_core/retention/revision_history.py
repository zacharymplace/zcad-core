from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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

"""Bind Validation Lab candidates to the validated export pipeline.

An export-validation run re-exports a candidate's retention STEP through
:func:`zcad_core.exporters.export_parts` and checks its fixture artifact,
producing an append-only record bound to the candidate's ``output_sha256``.
Earlier candidate evidence is never modified: each run gets its own
``vNNN`` directory, and a failing run is recorded rather than discarded.

Retention STEPs embed the target's PCB solid for fit reference. When a
reference board is supplied, it is separated out: the generated
geometry gates the record, while the vendor board is reported as a
non-gating ``reference_board`` artifact.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.validation.design_report import DesignValidationError
from zcad_core.validation.stl_mesh import read_stl

from .production_board import import_production_board_model
from .validation_lab import (
    CandidateRevision,
    ValidationTarget,
    _validate_sha256,
    load_manifest,
    sha256_file,
)

EXPORT_VALIDATION_SCHEMA_VERSION = "1.1.0"
_SUPPORTED_SCHEMA_VERSIONS = ("1.0.0", EXPORT_VALIDATION_SCHEMA_VERSION)
EXPORT_VALIDATION_RECORD_NAME = "export-validation.json"

_RUN_PATTERN = re.compile(r"^v[0-9]{3}$")
_GATING_ROLES = ("retention", "fixture")
_REFERENCE_ROLES = ("reference_board",)
_BOARD_MATCH_TOLERANCE_MM = 1e-6
_STATUSES = ("PASS", "FAIL")
_STEP_SUFFIXES = (".step", ".stp")


@dataclass(frozen=True)
class ReferenceBoard:
    """Source model and PCB solid embedded in a candidate's retention STEP."""

    source_step: Path
    pcb_solid_index: int

    @classmethod
    def from_target(cls, target: ValidationTarget) -> ReferenceBoard:
        return cls(
            source_step=Path(target.source_model_path),
            pcb_solid_index=target.pcb_solid_index,
        )


@dataclass(frozen=True)
class ExportValidationArtifact:
    """Validation outcome for one candidate artifact."""

    role: str
    source_path: str
    source_sha256: str
    evaluated_status: str
    report: dict[str, Any]
    outputs: dict[str, str]
    gating: bool = True

    def __post_init__(self) -> None:
        if self.role in _GATING_ROLES:
            if not self.gating:
                raise ValueError(f"{self.role} artifacts must gate the record")
        elif self.role in _REFERENCE_ROLES:
            if self.gating:
                raise ValueError(f"{self.role} artifacts cannot gate the record")
        else:
            raise ValueError(f"Unsupported export-validation role: {self.role}")

        if self.evaluated_status not in _STATUSES:
            raise ValueError("evaluated_status must be PASS or FAIL")

        if not self.source_path.strip():
            raise ValueError("source_path cannot be empty")

        _validate_sha256(self.source_sha256, field_name="source_sha256")

        for path, digest in self.outputs.items():
            if not path.strip():
                raise ValueError("Output paths cannot be empty")
            _validate_sha256(digest, field_name="output sha256")

        if self.evaluated_status == "FAIL" and self.outputs:
            raise ValueError("A failed artifact cannot publish outputs")


@dataclass(frozen=True)
class ExportValidationRecord:
    """Append-only export-validation evidence for one candidate revision."""

    schema_version: str
    candidate_id: str
    run_id: str
    printer_profile_id: str
    validated_at_utc: str
    evaluated_status: str
    artifacts: tuple[ExportValidationArtifact, ...]

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("Unsupported export-validation schema")

        if not _RUN_PATTERN.fullmatch(self.run_id):
            raise ValueError("run_id must match vNNN")

        for field_name, value in (
            ("candidate_id", self.candidate_id),
            ("printer_profile_id", self.printer_profile_id),
            ("validated_at_utc", self.validated_at_utc),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

        roles = [artifact.role for artifact in self.artifacts]

        if len(roles) != len(set(roles)):
            raise ValueError("Export-validation roles must be unique")

        if "retention" not in roles:
            raise ValueError("Export validation requires a retention artifact")

        expected = (
            "PASS"
            if all(a.evaluated_status == "PASS" for a in self.artifacts if a.gating)
            else "FAIL"
        )

        if self.evaluated_status != expected:
            raise ValueError("evaluated_status must summarize artifact statuses")

    def artifact(self, role: str) -> ExportValidationArtifact:
        for artifact in self.artifacts:
            if artifact.role == role:
                return artifact

        raise KeyError(role)


def _failure_report(code: str, error: BaseException) -> dict[str, Any]:
    return {
        "evaluated_status": "FAIL",
        "checks": [
            {
                "code": code,
                "status": "FAIL",
                "message": f"{type(error).__name__}: {error}",
            }
        ],
    }


def _validate_step_artifact(
    *,
    role: str,
    path: Path,
    output_directory: Path,
    repository_root: Path,
    printer_profile: dict[str, Any],
    solids: list[cq.Solid] | None = None,
    source_sha256: str | None = None,
    gating: bool = True,
) -> ExportValidationArtifact:
    """Export ``path`` (or the given ``solids`` taken from it) and record it."""

    if source_sha256 is None:
        source_sha256 = sha256_file(path)

    try:
        model = (
            cq.importers.importStep(str(path))
            if solids is None
            else cq.Workplane("XY").newObject(solids)
        )
        result = export_parts(
            ExportRequest(
                design_name=role,
                design_type="retention-candidate",
                parts={"main": model},
                output_directory=output_directory,
                repository_root=repository_root,
                printer_profile=printer_profile,
            )
        )
    except DesignValidationError as error:
        report = error.report
        outputs: dict[str, str] = {}
    # OCC import and geometry inspection surface as varied exception types.
    except Exception as error:  # noqa: BLE001
        report = _failure_report("step_export", error)
        outputs = {}
    else:
        report = result.validation_report or {}
        outputs = {
            str(output): sha256_file(output)
            for part in result.parts
            for output in (part.step_path, part.stl_path, part.metadata_path)
        }

    return ExportValidationArtifact(
        role=role,
        source_path=str(path),
        source_sha256=source_sha256,
        evaluated_status=(
            "PASS" if outputs and report.get("evaluated_status") == "PASS" else "FAIL"
        ),
        report=report,
        outputs=outputs,
        gating=gating,
    )


def _matches_board(solid: cq.Solid, board: cq.Solid) -> bool:
    """Match on volume and bounds; generation merges coplanar board faces."""

    a, b = solid.BoundingBox(), board.BoundingBox()
    bounds_match = all(
        abs(x - y) <= _BOARD_MATCH_TOLERANCE_MM
        for x, y in zip(
            (a.xmin, a.ymin, a.zmin, a.xmax, a.ymax, a.zmax),
            (b.xmin, b.ymin, b.zmin, b.xmax, b.ymax, b.zmax),
            strict=True,
        )
    )
    volume_tolerance = _BOARD_MATCH_TOLERANCE_MM * max(1.0, abs(board.Volume()))

    return bounds_match and abs(solid.Volume() - board.Volume()) <= volume_tolerance


def _separate_reference_board(
    *,
    retention_step: Path,
    reference_board: ReferenceBoard,
) -> tuple[list[cq.Solid], cq.Solid]:
    """Split the embedded target PCB from generated retention solids."""

    board = import_production_board_model(
        source_step=reference_board.source_step,
        pcb_solid_index=reference_board.pcb_solid_index,
    ).pcb
    solids = [
        solid
        for solid in cq.importers.importStep(str(retention_step)).solids().vals()
        if isinstance(solid, cq.Solid)
    ]
    matches = [solid for solid in solids if _matches_board(solid, board)]

    if len(matches) != 1:
        raise ValueError(
            f"Expected one embedded reference board in {retention_step}, "
            f"found {len(matches)}; omit the reference board for candidates "
            "that do not embed one"
        )

    generated = [solid for solid in solids if solid is not matches[0]]

    if not generated:
        raise ValueError(f"No generated retention geometry in {retention_step}")

    return generated, board


def _validate_stl_artifact(*, role: str, path: Path) -> ExportValidationArtifact:
    source_sha256 = sha256_file(path)

    report: dict[str, Any]

    try:
        _, check = read_stl(path.read_bytes())
        report = {"evaluated_status": "PASS", "checks": [check]}
    except ValueError as error:
        report = _failure_report("stl_topology", error)

    return ExportValidationArtifact(
        role=role,
        source_path=str(path),
        source_sha256=source_sha256,
        evaluated_status=str(report["evaluated_status"]),
        report=report,
        outputs={},
    )


def _allocate_run_directory(validation_root: Path) -> tuple[str, Path]:
    validation_root.mkdir(parents=True, exist_ok=True)
    existing = sorted(
        path.name
        for path in validation_root.iterdir()
        if path.is_dir() and _RUN_PATTERN.fullmatch(path.name)
    )
    number = int(existing[-1][1:]) + 1 if existing else 1

    if number > 999:
        raise ValueError("Export-validation run numbers are exhausted")

    run_id = f"v{number:03d}"
    run_directory = validation_root / run_id
    # exist_ok=False keeps concurrent runs from sharing a directory.
    run_directory.mkdir()

    return run_id, run_directory


def run_candidate_export_validation(
    *,
    candidate: CandidateRevision,
    retention_step: Path,
    validation_root: Path,
    printer_profile: dict[str, Any],
    repository_root: Path,
    validated_at_utc: str,
    reference_board: ReferenceBoard | None = None,
) -> tuple[ExportValidationRecord, Path]:
    """Validate a candidate's artifacts and write a new, immutable run record.

    The retention STEP must be the exact file the candidate was registered
    with. Failing runs are still written, so rejected evidence stays visible.
    With ``reference_board``, the embedded board is validated separately and
    does not gate the record; without it, the whole retention STEP must pass.
    """

    if sha256_file(retention_step) != candidate.output_sha256:
        raise ValueError(
            f"Retention STEP does not match candidate output_sha256: {retention_step}"
        )

    profile_id = printer_profile.get("profile_id")

    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("Printer profile requires a profile_id")

    generated: list[cq.Solid] | None = None
    board: cq.Solid | None = None

    if reference_board is not None:
        if sha256_file(reference_board.source_step) != candidate.source_sha256:
            raise ValueError(
                "Reference board source does not match candidate source_sha256: "
                f"{reference_board.source_step}"
            )

        generated, board = _separate_reference_board(
            retention_step=retention_step,
            reference_board=reference_board,
        )

    fixture = Path(candidate.fixture_artifact_path)
    run_id, run_directory = _allocate_run_directory(validation_root)

    artifacts = [
        _validate_step_artifact(
            role="retention",
            path=retention_step,
            output_directory=run_directory,
            repository_root=repository_root,
            printer_profile=printer_profile,
            solids=generated,
        )
    ]

    if reference_board is not None and board is not None:
        artifacts.append(
            _validate_step_artifact(
                role="reference_board",
                path=reference_board.source_step,
                output_directory=run_directory,
                repository_root=repository_root,
                printer_profile=printer_profile,
                solids=[board],
                source_sha256=candidate.source_sha256,
                gating=False,
            )
        )

    if fixture.suffix.lower() == ".stl":
        artifacts.append(_validate_stl_artifact(role="fixture", path=fixture))
    elif fixture.suffix.lower() in _STEP_SUFFIXES:
        artifacts.append(
            _validate_step_artifact(
                role="fixture",
                path=fixture,
                output_directory=run_directory,
                repository_root=repository_root,
                printer_profile=printer_profile,
            )
        )
    else:
        artifacts.append(
            ExportValidationArtifact(
                role="fixture",
                source_path=str(fixture),
                source_sha256=sha256_file(fixture),
                evaluated_status="FAIL",
                report=_failure_report(
                    "fixture_format",
                    ValueError(f"Unsupported fixture format: {fixture.suffix}"),
                ),
                outputs={},
            )
        )

    record = ExportValidationRecord(
        schema_version=EXPORT_VALIDATION_SCHEMA_VERSION,
        candidate_id=candidate.candidate_id,
        run_id=run_id,
        printer_profile_id=profile_id,
        validated_at_utc=validated_at_utc,
        evaluated_status=(
            "PASS"
            if all(a.evaluated_status == "PASS" for a in artifacts if a.gating)
            else "FAIL"
        ),
        artifacts=tuple(artifacts),
    )

    record_path = run_directory / EXPORT_VALIDATION_RECORD_NAME

    with record_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), indent=2, sort_keys=True) + "\n")

    return record, record_path


def load_export_validation_record(path: Path) -> ExportValidationRecord:
    payload = load_manifest(path)
    artifacts = payload["artifacts"]

    if not isinstance(artifacts, list):
        raise TypeError("artifacts must be a list")

    return ExportValidationRecord(
        schema_version=str(payload["schema_version"]),
        candidate_id=str(payload["candidate_id"]),
        run_id=str(payload["run_id"]),
        printer_profile_id=str(payload["printer_profile_id"]),
        validated_at_utc=str(payload["validated_at_utc"]),
        evaluated_status=str(payload["evaluated_status"]),
        artifacts=tuple(
            ExportValidationArtifact(
                role=str(artifact["role"]),
                source_path=str(artifact["source_path"]),
                source_sha256=str(artifact["source_sha256"]),
                evaluated_status=str(artifact["evaluated_status"]),
                report=dict(artifact["report"]),
                outputs={
                    str(path): str(digest)
                    for path, digest in dict(artifact["outputs"]).items()
                },
                gating=bool(artifact.get("gating", True)),
            )
            for artifact in artifacts
        ),
    )


def _unchanged(path: str, expected_sha256: str) -> bool:
    try:
        return sha256_file(Path(path)) == expected_sha256
    except FileNotFoundError:
        return False


def verify_export_validation(
    record: ExportValidationRecord,
    *,
    candidate: CandidateRevision,
) -> tuple[str, ...]:
    """Return failures preventing ``record`` from supporting ``candidate``.

    Re-hashes every source and output so evidence edited or replaced after
    the run no longer counts.
    """

    failures: list[str] = []

    if record.candidate_id != candidate.candidate_id:
        failures.append("export_validation_candidate_mismatch")

    if record.evaluated_status != "PASS":
        failures.append("export_validation_failed")

    if record.artifact("retention").source_sha256 != candidate.output_sha256:
        failures.append("export_validation_output_hash_mismatch")

    for artifact in record.artifacts:
        if not _unchanged(artifact.source_path, artifact.source_sha256):
            failures.append(f"export_validation_source_changed:{artifact.role}")

        if not all(
            _unchanged(path, digest) for path, digest in artifact.outputs.items()
        ):
            failures.append(f"export_validation_output_changed:{artifact.role}")

    return tuple(failures)

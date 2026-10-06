"""Helpers shared by the zcad-validation command modules."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zcad_core.features.mounts import measured_strain_limit
from zcad_core.profiles import load_compensation_profile
from zcad_core.retention import (
    UNRECORDED_SLICER_PROFILE,
    CornerCapturePolicy,
    EdgeCapturePolicy,
    PhysicalTrialManifest,
    PhysicalValidationDisposition,
    PromotionDecision,
    PromotionRecord,
    ValidationTarget,
    load_manifest,
    load_physical_validation_record,
)

STRATEGIES = ("corner-capture", "edge-clip")


def now() -> str:
    return datetime.now(UTC).isoformat()


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def load_validation_target(path: Path) -> ValidationTarget:
    payload = load_manifest(path)

    return ValidationTarget(
        schema_version=str(payload["schema_version"]),
        target_id=str(payload["target_id"]),
        display_name=str(payload["display_name"]),
        manufacturer=str(payload["manufacturer"]),
        product_family=str(payload["product_family"]),
        source_model_path=str(payload["source_model_path"]),
        source_model_sha256=str(payload["source_model_sha256"]),
        pcb_solid_index=int(payload["pcb_solid_index"]),
        created_at_utc=str(payload["created_at_utc"]),
    )


def load_physical_trial_manifest(path: Path) -> PhysicalTrialManifest:
    payload = load_manifest(path)

    disposition = str(payload["disposition"])
    complete = bool(payload["complete"])
    passed = bool(payload["passed"])

    # Trials registered before the explicit pending disposition copied a
    # placeholder "revise" from an unprinted record. The manifest is
    # immutable, so read the referenced record to tell them apart.
    if (
        disposition == PhysicalValidationDisposition.REVISE.value
        and references_pending_record(
            manifest_path=path,
            record_path=Path(str(payload["physical_validation_path"])),
        )
    ):
        disposition = PhysicalValidationDisposition.PENDING.value
        complete = False
        passed = False

    return PhysicalTrialManifest(
        schema_version=str(payload["schema_version"]),
        trial_id=str(payload["trial_id"]),
        candidate_id=str(payload["candidate_id"]),
        physical_validation_path=str(payload["physical_validation_path"]),
        fixture_artifact_path=str(payload["fixture_artifact_path"]),
        printer_profile=str(payload["printer_profile"]),
        material_profile=str(payload["material_profile"]),
        slicer_profile=str(payload.get("slicer_profile", UNRECORDED_SLICER_PROFILE)),
        disposition=disposition,
        complete=complete,
        passed=passed,
        created_at_utc=str(payload["created_at_utc"]),
    )


def references_pending_record(*, manifest_path: Path, record_path: Path) -> bool:
    """Whether a trial manifest points at a still-pending validation record.

    Recorded paths are repository-relative, so when the working directory
    is not the repository root, resolve against the manifest's ancestors.
    A record that cannot be found leaves the manifest as recorded.
    """

    candidates = [record_path]

    if not record_path.is_absolute():
        candidates.extend(
            parent / record_path for parent in manifest_path.resolve().parents
        )

    for candidate in candidates:
        if candidate.is_file():
            return load_physical_validation_record(candidate).pending

    return False


def optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)

    return str(value) if value is not None else None


def load_promotion_record(path: Path) -> PromotionRecord:
    payload = load_manifest(path)

    return PromotionRecord(
        schema_version=str(payload["schema_version"]),
        target_id=str(payload["target_id"]),
        candidate_id=str(payload["candidate_id"]),
        decision=PromotionDecision(payload["decision"]),
        reason=str(payload["reason"]),
        reviewer=str(payload["reviewer"]),
        automated_validation_passed=bool(payload["automated_validation_passed"]),
        physical_validation_passed=bool(payload["physical_validation_passed"]),
        candidate_manifest_path=str(payload["candidate_manifest_path"]),
        physical_trial_path=str(payload["physical_trial_path"]),
        created_at_utc=str(payload["created_at_utc"]),
        relationship_path=optional_str(payload, "relationship_path"),
        parameter_delta_path=optional_str(payload, "parameter_delta_path"),
        supersedes_candidate_id=optional_str(payload, "supersedes_candidate_id"),
        export_validation_path=optional_str(payload, "export_validation_path"),
        visual_review_path=optional_str(payload, "visual_review_path"),
    )


def scan_target_promotions(
    target_root: Path,
) -> tuple[PromotionRecord, ...]:
    """Discover existing promotion records under a target root.

    Deliberately does not look at ``relationship.json`` files: those record
    derive-time revision lineage, not promotion supersession. See
    ``PromotionRecord.supersedes_candidate_id`` and
    ``select_preferred_revision`` in ``zcad_core.retention.promotion``.
    """

    candidates_root = target_root / "candidates"

    if not candidates_root.is_dir():
        return ()

    return tuple(
        load_promotion_record(path)
        for path in sorted(candidates_root.glob("*/promotion.json"))
    )


def build_capture_policy(
    args: argparse.Namespace,
) -> CornerCapturePolicy | EdgeCapturePolicy:
    """Build the geometry policy for whichever strategy was requested.

    CornerCapturePolicy and EdgeCapturePolicy share the same five field
    names by design (see edge_capture.py), so both strategies read from
    one set of CLI flags rather than needing strategy-specific ones.
    """

    fields = {
        "arm_width_mm": args.arm_width_mm,
        "engagement_depth_mm": args.engagement_depth_mm,
        "board_clearance_mm": args.board_clearance_mm,
        "vertical_overlap_mm": args.vertical_overlap_mm,
        "minimum_wall_mm": args.minimum_wall_mm,
    }
    fields = {key: value for key, value in fields.items() if value is not None}

    if args.strategy == "corner-capture":
        return CornerCapturePolicy(**fields)

    return EdgeCapturePolicy(**fields)


def corner_keepout(args: argparse.Namespace) -> dict[str, float]:
    """The request option for ``--corner-keepout-mm``, if one was given.

    It only affects corner selection, so it is refused for edge clips
    rather than silently ignored.
    """

    if args.corner_keepout_mm is None:
        return {}

    if args.strategy != "corner-capture":
        raise ValueError(
            "--corner-keepout-mm applies only to --strategy corner-capture"
        )

    return {"corner_keepout_mm": args.corner_keepout_mm}


def add_capture_policy_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """Add the flags shared by ``candidate create`` and ``fixture export``.

    CornerCapturePolicy and EdgeCapturePolicy share these five field
    names; the target strategy decides which dataclass they build. All
    default to None so omitting a flag falls back to that policy's own
    default rather than a CLI-level duplicate of it.
    """

    parser.add_argument(
        "--strategy",
        default="corner-capture",
        choices=STRATEGIES,
    )
    parser.add_argument("--source-step", required=True, type=Path)
    parser.add_argument("--pcb-solid-index", required=True, type=int)
    parser.add_argument("--output-step", required=True, type=Path)
    parser.add_argument("--arm-width-mm", type=float)
    parser.add_argument("--engagement-depth-mm", type=float)
    parser.add_argument("--board-clearance-mm", type=float)
    parser.add_argument("--vertical-overlap-mm", type=float)
    parser.add_argument("--minimum-wall-mm", type=float)
    parser.add_argument(
        "--corner-keepout-mm",
        type=float,
        help=(
            "Corner-capture only: the square at each PCB corner that must be "
            "clear of components (default 4.0; the XIAO ESP32-S3 needs 2.1)."
        ),
    )


COMPENSATION_PROFILE_HELP = (
    "use this printer and material's compensation profile: its measured strain "
    "limit, if it has one, replaces the provisional 1.5 per cent every flexure "
    "is checked and sized against"
)


def add_compensation_profile_argument(parser: argparse.ArgumentParser) -> None:
    """The option that lets a build use measured figures instead of the
    provisional ones; without it, nothing changes."""

    parser.add_argument(
        "--compensation-profile", type=Path, help=COMPENSATION_PROFILE_HELP
    )


@contextmanager
def applied_strain_limit(profile_path: Path | None) -> Iterator[None]:
    """For one command, hold flexures to the strain limit the profile measured,
    if the command was given a profile that has one."""

    if profile_path is None:
        yield
        return

    profile = load_compensation_profile(profile_path)
    limit = profile.strain_limit()

    if limit is None:
        yield
        return

    source = f"{profile.payload['profile_id']} version {profile.payload['version']}"

    with measured_strain_limit(limit, source):
        yield

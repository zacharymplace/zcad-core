"""Register a wearable device's snap-shell Validation Lab candidate.

The Dexcom G7 and Tandem Mobi scripts share this. A candidate's body is an
envelope, a rectangle or the rounded rectangle a capture gives: from the device's published dimensions, which makes
it a ``provisional_synthetic_candidate`` that no trial may use, or from a
caliper capture (:mod:`zcad_core.hardware.wearables.capture`), which makes
it a ``verified_candidate`` when the shell's fit checks pass. A capture's
file is copied beside the candidate and its SHA-256 recorded, and each clip
slides along its edge to stand clear of every edge feature the capture
lists, with its hook clear of every face feature.

The shell (see :class:`SyntheticSnapShellBackend`) is a frame the device
rests on and a clip on each chosen edge, built against the envelope: each
clip stands the clearance out from the device's edge and hooks over its top
edge. The checks measure that against the envelope: no shell material
inside it or within the clearance of its sides and top face, each lip over
the top face, the clips joined to the frame, and each clip's strain as it
bends to let the device in. A device as thin as the G7 has no height for a
post to bend over, so its target asks for tabs, which bend along the edge.
The record keeps how much shell material is inside the envelope
(``clips_into_device_mm3``).

The first revision registers the target as well. A later one names its
parent and why, writes its own envelope beside the earlier ones so their
pinned files never change, and records its relationship to the parent.
Nothing is written when the revision exists, its parent or target is
missing, or a clip cannot clear a feature.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import cadquery as cq

from zcad_core.features.mounts import flexure_strain_limit, strain_limit_source
from zcad_core.hardware.wearables import (
    EdgeFeature,
    FaceFeature,
    WearableCapture,
    load_capture,
)
from zcad_core.hardware.wearables.edge_placement import (
    clear_offset,
    edge_reach_mm,
    face_keepouts,
)
from zcad_core.retention.engine import RetentionEngine, RetentionStrategy
from zcad_core.retention.export_validation import run_candidate_export_validation
from zcad_core.retention.revision_history import RevisionRelationshipType
from zcad_core.retention.revision_registration import (
    load_candidate_revision,
    persist_candidate_revision,
)
from zcad_core.retention.snap_shell import (
    TAB_LENGTH_MM,
    SnapShellLocation,
    SnapShellParameters,
    SnapShellPolicy,
)
from zcad_core.retention.snap_shell_backend import (
    SnapShellRequest,
    as_snap_shell_fit_report,
)
from zcad_core.retention.synthetic_snap_shell_backend import SyntheticSnapShellBackend
from zcad_core.retention.validation_lab import (
    CandidateRevision,
    ValidationTarget,
    candidate_identifier,
    load_manifest,
    sha256_file,
    write_immutable_manifest,
)

FIRST_REVISION = "r001"
STRATEGY = "snap-shell"
PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")
_EDGE_ROTATION = {"north": 270.0, "south": 90.0, "east": 180.0, "west": 0.0}


@dataclass(frozen=True)
class WearableTarget:
    """One device's Validation Lab target and how its shell is held."""

    target_id: str
    device: str
    display_name: str
    manufacturer: str
    product_family: str
    file_stem: str
    clip_edges: tuple[str, ...]
    heading: str
    placeholder_reason: str
    # Tabs that bend along the edge, for a device too thin for posts to bend
    # up its sides (see SnapShellPolicy).
    tabs: bool = False

    @property
    def policy(self) -> SnapShellPolicy:
        """The shell's policy: the defaults, with tabs if the target has them."""

        return SnapShellPolicy(tab_length_mm=TAB_LENGTH_MM if self.tabs else None)


@dataclass(frozen=True)
class Body:
    """The envelope's size, and where it came from."""

    length_mm: float
    width_mm: float
    thickness_mm: float
    evidence_status: str
    source: str
    features: tuple[EdgeFeature, ...] = ()
    capture: WearableCapture | None = None
    face_features: tuple[FaceFeature, ...] = ()


@dataclass(frozen=True)
class RevisionPaths:
    """Where one revision's files go, under a repository root."""

    root: Path
    target: WearableTarget
    revision: str
    from_capture: bool

    @property
    def lab(self) -> Path:
        return self.root / "evidence" / self.target.target_id / "validation-lab"

    @property
    def source_step(self) -> Path:
        kind = "caliper" if self.from_capture else "placeholder"
        # The first revision keeps the name it was registered with.
        suffix = "" if self.revision == FIRST_REVISION else f"-{self.revision}"
        return (
            self.root
            / "evidence"
            / self.target.target_id
            / "step"
            / f"{self.target.file_stem}-{kind}-envelope{suffix}.step"
        )

    @property
    def target_manifest(self) -> Path:
        return self.lab / "target.json"

    @property
    def candidate_root(self) -> Path:
        return self.lab / "candidates" / self.revision

    @property
    def automated_report(self) -> Path:
        return self.candidate_root / "automated-validation.json"

    @property
    def retention_step(self) -> Path:
        return self.candidate_root / "retention.step"

    @property
    def candidate_manifest(self) -> Path:
        return self.candidate_root / "candidate.json"

    @property
    def capture_copy(self) -> Path:
        return self.candidate_root / "capture.json"

    def relative(self, path: Path) -> str:
        return str(path.relative_to(self.root))


def parse_arguments(argv: Sequence[str] | None, description: str) -> argparse.Namespace:
    """The options every wearable snap-shell script takes."""

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--revision", default=FIRST_REVISION)
    parser.add_argument("--parent", help="the revision this one follows, as r001")
    parser.add_argument(
        "--relationship",
        choices=[kind.value for kind in RevisionRelationshipType],
        default=RevisionRelationshipType.SUPERSEDES.value,
    )
    parser.add_argument("--reason", help="why this revision exists; needs --parent")
    parser.add_argument(
        "--capture",
        type=Path,
        help="a caliper capture to build from; see docs/guides/wearable-capture.md",
    )
    parser.add_argument(
        "--compensation-profile",
        type=Path,
        help=(
            "hold the clips to this printer and material profile's measured strain "
            "limit, if it has one, instead of the provisional 1.5 per cent"
        ),
    )
    args = parser.parse_args(argv)

    if args.revision == FIRST_REVISION and args.parent:
        parser.error(f"{FIRST_REVISION} is the first revision and has no parent")

    if args.revision != FIRST_REVISION and not (args.parent and args.reason):
        parser.error(f"{args.revision} needs --parent and --reason")

    return args


def body_from(
    target: WearableTarget,
    *,
    published: tuple[float, float, float],
    evidence_status: str,
    source: str,
    capture_path: Path | None,
) -> Body:
    """The published body, or the captured one when a capture is given."""

    if capture_path is None:
        length, width, thickness = published
        return Body(length, width, thickness, evidence_status, source)

    capture = load_capture(capture_path)

    if capture.device != target.device:
        raise SystemExit(
            f"{capture_path} captures a {capture.device}, not a {target.device}"
        )

    return Body(
        length_mm=capture.length_mm,
        width_mm=capture.width_mm,
        thickness_mm=capture.thickness_mm,
        evidence_status="caliper-verified",
        source=(
            f"Caliper capture {capture_path.name} (SHA-256 {capture.sha256}), "
            f"measured by {capture.measured_by} on {capture.measured_on} with "
            f"{capture.caliper}: {capture.source}"
        ),
        features=capture.edge_features,
        capture=capture,
        face_features=capture.face_features,
    )


def clip_locations(
    body: Body, edges: Sequence[str], policy: SnapShellPolicy
) -> tuple[SnapShellLocation, ...]:
    """A clip at the middle of each edge, slid along it to the nearest place
    clear of every feature there and off a rounded corner, as the cradle's tabs
    are, and where its hook covers no face feature. Raises ``ValueError``
    naming the edge and what blocks it when no place along it is clear."""

    locations = []
    radius = (body.capture.outline_radius_mm if body.capture else None) or 0.0
    half_length, half_width = body.length_mm / 2, body.width_mm / 2

    for edge in edges:
        along = body.length_mm if edge in ("north", "south") else body.width_mm
        reach = edge_reach_mm(along, policy.span_mm, radius)
        blocked = [feature for feature in body.features if feature.edge == edge]
        # A tab's hook is at its free end, half a tab along the edge from its
        # middle: +X on the north edge, +Y on the west, back the other way on
        # the south and east (see SnapShellPolicy and _EDGE_ROTATION).
        hook_offset = (policy.tab_length_mm or 0.0) / 2
        covered = face_keepouts(
            body.face_features,
            edge,
            half_length_mm=half_length,
            half_width_mm=half_width,
            overhang_mm=policy.overhang_mm,
            hook_width_mm=policy.clip_width_mm,
            hook_offset_mm=hook_offset if edge in ("north", "west") else -hook_offset,
        )
        offset = clear_offset(
            blocked, reach, policy.span_mm, [keepout for _, keepout in covered]
        )

        if offset is None:
            names = ", ".join(
                [feature.identifier for feature in blocked]
                + [feature.identifier for feature, _ in covered]
            )
            raise ValueError(
                f"No place on the {edge} edge clears {names} for a "
                f"{policy.span_mm:g} mm clip; the shell cannot hold there"
            )

        x, y = {
            "north": (offset, half_width),
            "south": (offset, -half_width),
            "east": (half_length, offset),
            "west": (-half_length, offset),
        }[edge]
        locations.append(
            SnapShellLocation(
                label=edge, x_mm=x, y_mm=y, rotation_degrees=_EDGE_ROTATION[edge]
            )
        )

    return tuple(locations)


def register_snap_shell_candidate(
    target: WearableTarget,
    body: Body,
    args: argparse.Namespace,
    *,
    root: Path,
    git_commit: str,
) -> None:
    """Build, check, and register one revision; see the module docstring."""

    from_capture = body.capture is not None
    paths = RevisionPaths(root, target, args.revision, from_capture)
    parent = (
        RevisionPaths(root, target, args.parent, from_capture) if args.parent else None
    )
    policy = target.policy

    try:
        locations = clip_locations(body, target.clip_edges, policy)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    _require_new(paths, parent)

    backend = SyntheticSnapShellBackend()
    request = SnapShellRequest(
        device_thickness_mm=body.thickness_mm,
        device_length_mm=body.length_mm,
        device_width_mm=body.width_mm,
        locations=locations,
        policy=policy,
        edge_features=body.features,
        face_features=body.face_features,
        device_corner_radius_mm=(
            body.capture.outline_radius_mm if body.capture else None
        )
        or 0.0,
    )
    # The envelope the shell is built and checked against, as its source.
    envelope = backend.device_envelope(backend.derive(request))
    paths.source_step.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(envelope, str(paths.source_step))

    engine = RetentionEngine()
    engine.register(RetentionStrategy.SNAP_SHELL, backend)
    execution = engine.execute(
        strategy=RetentionStrategy.SNAP_SHELL,
        request=request,
        model=envelope,
    )

    if not isinstance(execution.model, cq.Workplane):
        raise TypeError("Retention execution did not produce a cadquery Workplane")

    if not isinstance(execution.parameters, SnapShellParameters):
        raise TypeError("Retention execution did not produce snap-shell parameters")

    clips_into_device = backend.clips_into_device_mm3(execution.parameters)

    fit_report = as_snap_shell_fit_report(execution.report)
    paths.retention_step.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(execution.model, str(paths.retention_step))

    if body.capture is not None:
        shutil.copyfile(body.capture.path, paths.capture_copy)

    created_at = datetime.now(UTC).isoformat()
    source_sha256 = sha256_file(paths.source_step)
    output_sha256 = sha256_file(paths.retention_step)

    if not execution.passed:
        decision = "rejected"
    elif from_capture:
        decision = "verified_candidate"
    else:
        decision = "provisional_synthetic_candidate"

    retention_policy = {
        "clip_width_mm": policy.clip_width_mm,
        "wall_mm": policy.wall_mm,
        "clip_height_mm": policy.clip_height_mm,
        "overhang_mm": policy.overhang_mm,
        "clearance_mm": policy.clearance_mm,
        "compliant_span_mm": policy.compliant_span_mm,
        "ledge_mm": policy.ledge_mm,
        "rim_height_mm": policy.rim_height_mm,
    }

    if policy.tab_length_mm is not None:
        retention_policy["tab_length_mm"] = policy.tab_length_mm
        retention_policy["tab_slit_mm"] = policy.tab_slit_mm
    fit_results = {
        result.check.value: {"passed": result.passed, "detail": result.detail}
        for result in fit_report.results
    }
    report = _report(
        target,
        body,
        paths,
        locations,
        retention_policy,
        fit_results,
        decision,
        created_at=created_at,
        source_sha256=source_sha256,
        output_sha256=output_sha256,
        clips_into_device_mm3=clips_into_device,
    )
    paths.automated_report.parent.mkdir(parents=True, exist_ok=True)
    paths.automated_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if parent is None:
        write_immutable_manifest(
            ValidationTarget(
                schema_version="1.0.0",
                target_id=target.target_id,
                display_name=target.display_name,
                manufacturer=target.manufacturer,
                product_family=target.product_family,
                source_model_path=paths.relative(paths.source_step),
                source_model_sha256=source_sha256,
                pcb_solid_index=1,
                created_at_utc=created_at,
            ),
            output_path=paths.target_manifest,
        )

    candidate = CandidateRevision(
        schema_version="1.0.0",
        candidate_id=candidate_identifier(
            target_id=target.target_id, strategy=STRATEGY, revision=args.revision
        ),
        target_id=target.target_id,
        revision=args.revision,
        source_sha256=source_sha256,
        output_sha256=output_sha256,
        git_commit=git_commit,
        generator_version="1.0.0",
        retention_policy=retention_policy,
        derived_parameters={
            "device_thickness_mm": body.thickness_mm,
            **retention_policy,
        },
        selected_corners=tuple(location.label for location in locations),
        automated_decision=decision,
        automated_evidence_path=paths.relative(paths.automated_report),
        fixture_artifact_path=paths.relative(paths.retention_step),
        created_at_utc=created_at,
        strategy=STRATEGY,
    )

    if parent is None:
        write_immutable_manifest(candidate, output_path=paths.candidate_manifest)
    else:
        persist_candidate_revision(
            parent_candidate=load_candidate_revision(parent.candidate_manifest),
            candidate=candidate,
            relationship=RevisionRelationshipType(args.relationship),
            reason=args.reason,
            output_directory=paths.candidate_root,
        )

    # The shell does not embed the envelope, so no reference board.
    export_validation, export_validation_path = run_candidate_export_validation(
        candidate=candidate,
        retention_step=paths.retention_step,
        validation_root=paths.candidate_root / "export-validation",
        printer_profile=load_manifest(root / PRINTER_PROFILE),
        repository_root=root,
        validated_at_utc=created_at,
    )

    kind = "caliper capture" if from_capture else "synthetic, placeholder geometry"
    print(f"=== {target.heading} SNAP-SHELL CANDIDATE ({kind}) ===")
    print(
        f"Revision: {args.revision}"
        + (f" ({args.relationship} {args.parent})" if parent else "")
    )
    print(f"Passed: {execution.passed}")
    print(f"Decision: {decision}")
    print(
        "Locations: "
        + ", ".join(
            location.label
            + (
                ""
                if (location.x_mm, location.y_mm) == _middle(body, location.label)
                else " (moved clear of a feature)"
            )
            for location in locations
        )
    )
    print(f"Target manifest: {paths.target_manifest}")
    print(f"Candidate manifest: {paths.candidate_manifest}")
    print(f"Retention STEP: {paths.retention_step}")
    print(f"Export validation: {export_validation.evaluated_status}")
    print(f"Export-validation record: {export_validation_path}")

    if not execution.passed:
        failed = ", ".join(
            result.check.value for result in fit_report.results if not result.passed
        )
        raise SystemExit(f"Snap-shell verification failed: {failed}")


def _middle(body: Body, edge: str) -> tuple[float, float]:
    return {
        "north": (0.0, body.width_mm / 2),
        "south": (0.0, -body.width_mm / 2),
        "east": (body.length_mm / 2, 0.0),
        "west": (-body.length_mm / 2, 0.0),
    }[edge]


def _require_new(paths: RevisionPaths, parent: RevisionPaths | None) -> None:
    """Refuse before exporting anything: the STEP files and report are
    written before the immutable manifests, so a rerun against an existing
    revision would clobber its pinned artifacts and only then fail."""

    pinned = [paths.candidate_manifest, paths.source_step, paths.retention_step]

    if parent is None:
        pinned.append(paths.target_manifest)

    existing = [path for path in pinned if path.exists()]

    if existing:
        raise SystemExit(
            "Refusing to regenerate over pinned files: "
            + ", ".join(paths.relative(path) for path in existing)
        )

    if parent is not None:
        missing = [
            path
            for path in (paths.target_manifest, parent.candidate_manifest)
            if not path.exists()
        ]

        if missing:
            raise SystemExit(
                "A revision needs its target and parent registered first: "
                + ", ".join(paths.relative(path) for path in missing)
            )


def _report(
    target: WearableTarget,
    body: Body,
    paths: RevisionPaths,
    locations: Sequence[SnapShellLocation],
    retention_policy: dict[str, float],
    fit_results: dict[str, dict[str, object]],
    decision: str,
    *,
    created_at: str,
    source_sha256: str,
    output_sha256: str,
    clips_into_device_mm3: float,
) -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": "1.0.0",
        "generated_at_utc": created_at,
        "decision": decision,
        "geometry_evidence_status": body.evidence_status,
        "geometry_source": body.source,
        "source": {
            "step_path": paths.relative(paths.source_step),
            "step_sha256": source_sha256,
            "pcb_solid_index": 1,
        },
        "output": {
            "step_path": paths.relative(paths.retention_step),
            "step_sha256": output_sha256,
        },
        "device": {
            "body_length_mm": body.length_mm,
            "body_width_mm": body.width_mm,
            "body_thickness_mm": body.thickness_mm,
            "body_corner_radius_mm": (
                body.capture.outline_radius_mm if body.capture else None
            )
            or 0.0,
        },
        "selected_corners": [location.label for location in locations],
        "snap_shell_locations": [
            {
                "label": location.label,
                "x_mm": location.x_mm,
                "y_mm": location.y_mm,
                "rotation_degrees": location.rotation_degrees,
            }
            for location in locations
        ],
        "policy": retention_policy,
        "fit_checks": fit_results,
        # Which limit the clip strain check held them to, and where it came from.
        "strain_limit": {
            "percent": round(100 * flexure_strain_limit(), 3),
            "source": strain_limit_source(),
        },
        "clips_into_device_mm3": round(clips_into_device_mm3, 3),
        "metadata_publication": (
            {
                "approved": decision == "verified_candidate",
                "reason": (
                    f"Built from caliper capture {paths.relative(paths.capture_copy)}; "
                    "a printed trial on the real device is still required."
                    if decision == "verified_candidate"
                    else f"Built from caliper capture "
                    f"{paths.relative(paths.capture_copy)}, but its fit checks "
                    "failed; not for publication or a trial."
                ),
            }
            if body.capture is not None
            else {"approved": False, "reason": target.placeholder_reason}
        ),
    }

    if body.capture is not None:
        report["capture"] = {
            "path": paths.relative(paths.capture_copy),
            "sha256": body.capture.sha256,
            "measured_by": body.capture.measured_by,
            "measured_on": body.capture.measured_on,
            "caliper": body.capture.caliper,
            "edge_features": [
                {
                    "identifier": feature.identifier,
                    "edge": feature.edge,
                    "center_offset_mm": feature.center_offset_mm,
                    "width_mm": feature.width_mm,
                }
                for feature in body.features
            ],
            "face_features": [
                {
                    "identifier": feature.identifier,
                    "center_x_mm": feature.center_x_mm,
                    "center_y_mm": feature.center_y_mm,
                    "width_mm": feature.width_mm,
                    "depth_mm": feature.depth_mm,
                }
                for feature in body.face_features
            ],
        }

    return report

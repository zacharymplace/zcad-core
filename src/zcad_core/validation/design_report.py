"""Design-level checks with explicit scope and incomplete coverage."""

import math
from typing import Any

import cadquery as cq

from zcad_core.validation.export_geometry import (
    GeometryValidationError,
    InspectedGeometry,
    inspect_export_geometry,
)
from zcad_core.validation.profile_rules import validate_design_parameters


class DesignValidationError(ValueError):
    """Failed profile checks with a reusable design report."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(
            "Design validation failed: "
            + "; ".join(
                f"{c['code']}: {c['message']}"
                for c in report["checks"]
                if c["status"] == "FAIL"
            )
        )


_PROFILE_RULE_PARAMETERS = frozenset(
    {"wall", "floor", "label_height", "label_size", "lid_clearance"}
)
_OUT_OF_SCOPE = (
    "solid_intersections",
    "manufacturing",
    "physical_fit",
    "artifact_integrity",
)


def _check(code: str, status: str, message: str, **details: Any) -> dict[str, Any]:
    return dict(code=code, status=status, message=message, **details)


def _is_finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and math.isfinite(value)
    )


def _build_volume_limits(
    printer_profile: dict[str, Any],
) -> tuple[float, float, float] | None:
    """The profile's XYZ build limits, or None when any is not finite and positive."""

    raw = printer_profile.get("build_volume_mm")

    if isinstance(raw, dict) and all(
        _is_finite_number(raw.get(axis)) and raw[axis] > 0 for axis in "xyz"
    ):
        return (raw["x"], raw["y"], raw["z"])

    return None


def _build_volume_check(
    name: str,
    bounds: tuple[float, float, float] | None,
    limits: tuple[float, float, float] | None,
    orientation: str,
) -> dict[str, Any]:
    if limits is None or bounds is None:
        return _check(
            "build_volume",
            "NOT_CHECKED",
            "Printer limits or valid geometry unavailable",
            part_name=name,
            orientation_policy=orientation,
        )

    generated_fits = all(a <= b for a, b in zip(bounds, limits))
    rotated = (bounds[1], bounds[0], bounds[2])
    rotated_fits = all(a <= b for a, b in zip(rotated, limits))
    fits = generated_fits or (orientation == "xy_90" and rotated_fits)

    return _check(
        "build_volume",
        "PASS" if fits else "FAIL",
        "Per-part bounding-box fit under explicit orientation policy; "
        "no packing, brim, support or printability assessment",
        part_name=name,
        actual_mm=list(bounds),
        limits_mm=list(limits),
        orientation_policy=orientation,
        generated_status="PASS" if generated_fits else "FAIL",
        xy_90_status="PASS" if rotated_fits else "FAIL",
        xy_90_bounds_mm=list(rotated),
        selected_rotation_z_degrees=(0 if generated_fits else 90 if fits else None),
    )


def _profile_threshold_location(parameter: str) -> tuple[str, str]:
    """Where the printer profile keeps the threshold for a design parameter."""

    if parameter == "lid_clearance":
        return ("tolerances_mm", "sliding_clearance_per_side")

    field = {"label_height": "emboss_height", "label_size": "text_size"}.get(
        parameter, parameter
    )

    return ("minimums_mm", field)


def _declared_parameters_check(
    design_type: str,
    printer_profile: dict[str, Any] | None,
    parameters: dict[str, Any] | None,
) -> dict[str, Any]:
    if printer_profile is None or parameters is None:
        return _check(
            "declared_parameters",
            "NOT_CHECKED",
            "Printer profile or design parameters not supplied",
        )

    selected = {
        key: parameters[key]
        for key in _PROFILE_RULE_PARAMETERS.intersection(parameters)
    }

    if not selected:
        return _check(
            "declared_parameters",
            "NOT_CHECKED",
            "No parameters covered by existing profile rules",
        )

    try:
        if not all(_is_finite_number(value) for value in selected.values()):
            raise ValueError("Declared dimensions must be finite numbers")

        # Existing rules own thresholds and warning semantics; validate their inputs.
        for key in selected:
            section, field = _profile_threshold_location(key)
            threshold = printer_profile.get(section, {}).get(field)

            if not _is_finite_number(threshold) or threshold <= 0:
                raise ValueError(f"Invalid profile threshold: {section}.{field}")

        issues = validate_design_parameters(
            design_type=design_type,
            parameters=selected,
            printer_profile=printer_profile,
        )
    except (TypeError, ValueError, AttributeError) as error:
        return _check("declared_parameters", "FAIL", str(error))

    return _check(
        "declared_parameters",
        "FAIL" if any(issue.severity == "error" for issue in issues) else "PASS",
        "Declared values only; not measured wall thickness",
        checked_parameters=sorted(selected),
        issues=[issue.to_dict() for issue in issues],
    )


def report_from_geometry(
    *,
    design_name: str,
    design_type: str,
    geometry: dict[str, InspectedGeometry],
    printer_profile: dict[str, Any] | None,
    parameters: dict[str, Any] | None,
    failures: dict[str, dict[str, Any]] | None = None,
    build_volume_orientation: str = "generated",
) -> dict[str, Any]:
    """Combine owned geometry measurements and actual profile checks."""
    if build_volume_orientation not in ("generated", "xy_90"):
        raise ValueError("Unsupported build_volume_orientation")

    failures = failures or {}
    names = sorted(set(geometry) | set(failures))
    checks: list[dict[str, Any]] = []

    for name in names:
        source = geometry[name].report if name in geometry else failures[name]
        checks.extend({**check, "part_name": name} for check in source["checks"][:5])

    if not names:
        checks.append(_check("parts_present", "FAIL", "Design contains no parts"))

    limits = None

    if printer_profile is not None:
        limits = _build_volume_limits(printer_profile)

        if limits is None:
            checks.append(
                _check(
                    "printer_profile_build_volume",
                    "FAIL",
                    "Expected finite positive XYZ build limits",
                )
            )

    checks.extend(
        _build_volume_check(
            name,
            geometry[name].bounds_mm if name in geometry else None,
            limits,
            build_volume_orientation,
        )
        for name in names
    )
    checks.append(_declared_parameters_check(design_type, printer_profile, parameters))
    checks.extend(
        _check(code, "NOT_CHECKED", "Outside this pre-export validation scope")
        for code in _OUT_OF_SCOPE
    )

    return {
        "schema_version": "1.0",
        "design": {"name": design_name, "type": design_type},
        "scope": "pre-export geometry and declared printer-profile rules; not product readiness",
        "evaluated_status": "FAIL"
        if any(c["status"] == "FAIL" for c in checks)
        else "PASS",
        "coverage": "PARTIAL",
        "checks": checks,
        "warning_count": sum(
            i["severity"] == "warning" for c in checks for i in c.get("issues", [])
        ),
    }


def validate_design(
    *,
    design_name: str,
    design_type: str,
    parts: dict[str, cq.Workplane],
    printer_profile: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
    build_volume_orientation: str = "generated",
) -> dict[str, Any]:
    """Read-only assessment, including known geometry failures; writes no artifacts."""
    geometry = {}
    failures = {}
    for name, model in parts.items():
        try:
            geometry[name] = inspect_export_geometry(model, name)
        except GeometryValidationError as error:
            failures[name] = error.report
    return report_from_geometry(
        design_name=design_name,
        design_type=design_type,
        geometry=geometry,
        failures=failures,
        printer_profile=printer_profile,
        parameters=parameters,
        build_volume_orientation=build_volume_orientation,
    )

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


def report_from_geometry(
    *,
    design_name: str,
    design_type: str,
    geometry: dict[str, InspectedGeometry],
    printer_profile: dict[str, Any] | None,
    parameters: dict[str, Any] | None,
    failures: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Combine owned geometry measurements and actual profile checks."""
    checks: list[dict[str, Any]] = []

    def add(code: str, status: str, message: str, **details: Any) -> None:
        checks.append(dict(code=code, status=status, message=message, **details))

    failures = failures or {}
    for name in sorted(set(geometry) | set(failures)):
        source = geometry[name].report if name in geometry else failures[name]
        for check in source["checks"][:5]:
            checks.append({**check, "part_name": name})
    if not geometry and not failures:
        add("parts_present", "FAIL", "Design contains no parts")
    limits = None
    if printer_profile is not None:
        raw = printer_profile.get("build_volume_mm")
        if isinstance(raw, dict) and all(
            isinstance(raw.get(a), (int, float))
            and not isinstance(raw[a], bool)
            and math.isfinite(raw[a])
            and raw[a] > 0
            for a in "xyz"
        ):
            limits = tuple(raw[a] for a in "xyz")
        else:
            add(
                "printer_profile_build_volume",
                "FAIL",
                "Expected finite positive XYZ build limits",
            )
    for name in sorted(set(geometry) | set(failures)):
        if limits is None or name not in geometry:
            add(
                "build_volume",
                "NOT_CHECKED",
                "Printer limits or valid geometry unavailable",
                part_name=name,
            )
        else:
            actual = geometry[name].bounds_mm
            add(
                "build_volume",
                "PASS" if all(a <= b for a, b in zip(actual, limits)) else "FAIL",
                "Axis-aligned dimensions in generated orientation; no packing or rotation search",
                part_name=name,
                actual_mm=list(actual),
                limits_mm=list(limits),
            )
    applicable = {"wall", "floor", "label_height", "label_size", "lid_clearance"}
    if printer_profile is None or parameters is None:
        add(
            "declared_parameters",
            "NOT_CHECKED",
            "Printer profile or design parameters not supplied",
        )
    elif not applicable.intersection(parameters):
        add(
            "declared_parameters",
            "NOT_CHECKED",
            "No parameters covered by existing profile rules",
        )
    else:
        selected = {k: parameters[k] for k in applicable.intersection(parameters)}
        try:
            for value in selected.values():
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError("Declared dimensions must be finite numbers")
            # Existing rules own thresholds and warning semantics; validate their inputs.
            for key, value in selected.items():
                section, field = (
                    ("tolerances_mm", "sliding_clearance_per_side")
                    if key == "lid_clearance"
                    else (
                        "minimums_mm",
                        {
                            "label_height": "emboss_height",
                            "label_size": "text_size",
                        }.get(key, key),
                    )
                )
                threshold = printer_profile.get(section, {}).get(field)
                if (
                    isinstance(threshold, bool)
                    or not isinstance(threshold, (int, float))
                    or not math.isfinite(threshold)
                    or threshold <= 0
                ):
                    raise ValueError(f"Invalid profile threshold: {section}.{field}")
            issues = validate_design_parameters(
                design_type=design_type,
                parameters=selected,
                printer_profile=printer_profile,
            )
            status = "FAIL" if any(i.severity == "error" for i in issues) else "PASS"
            add(
                "declared_parameters",
                status,
                "Declared values only; not measured wall thickness",
                checked_parameters=sorted(selected),
                issues=[i.to_dict() for i in issues],
            )
        except (TypeError, ValueError, AttributeError) as error:
            add("declared_parameters", "FAIL", str(error))
    for code in (
        "solid_intersections",
        "manufacturing",
        "physical_fit",
        "artifact_integrity",
    ):
        add(code, "NOT_CHECKED", "Outside this pre-export validation scope")
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
    )

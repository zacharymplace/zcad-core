"""Validate generated parts and design parameters against profiles."""

from dataclasses import dataclass
from typing import Any

import cadquery as cq

from zcad_core.validation.export_geometry import inspect_export_geometry


@dataclass(frozen=True)
class ValidationIssue:
    """One profile-aware validation result."""

    severity: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable representation."""
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


def _require_positive_profile_number(
    *,
    profile: dict[str, Any],
    section: str,
    key: str,
) -> float:
    """Read a required positive numeric profile value."""
    section_data = profile.get(section)

    if not isinstance(section_data, dict):
        raise TypeError(f"Printer profile section '{section}' must be an object")

    value = section_data.get(key)

    if not isinstance(value, int | float):
        raise TypeError(f"Printer profile value '{section}.{key}' must be numeric")

    if value <= 0:
        raise ValueError(
            f"Printer profile value '{section}.{key}' must be greater than zero"
        )

    return float(value)


def validate_build_volume(
    *,
    part_name: str,
    model: cq.Workplane,
    printer_profile: dict[str, Any],
) -> list[ValidationIssue]:
    """Validate a part bounding box against printer build volume."""
    build_x = _require_positive_profile_number(
        profile=printer_profile,
        section="build_volume_mm",
        key="x",
    )
    build_y = _require_positive_profile_number(
        profile=printer_profile,
        section="build_volume_mm",
        key="y",
    )
    build_z = _require_positive_profile_number(
        profile=printer_profile,
        section="build_volume_mm",
        key="z",
    )

    bounds = inspect_export_geometry(model, part_name).bounds_mm

    issues: list[ValidationIssue] = []

    dimensions = {
        "x": (bounds[0], build_x),
        "y": (bounds[1], build_y),
        "z": (bounds[2], build_z),
    }

    for axis, (
        actual,
        maximum,
    ) in dimensions.items():
        if actual > maximum:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code=(f"build_volume_{axis}_exceeded"),
                    message=(
                        f"Part '{part_name}' measures "
                        f"{actual:.3f} mm on {axis.upper()}, "
                        f"exceeding the printer limit of "
                        f"{maximum:.3f} mm."
                    ),
                )
            )

    return issues


def validate_design_parameters(
    *,
    design_type: str,
    parameters: dict[str, Any],
    printer_profile: dict[str, Any],
) -> list[ValidationIssue]:
    """Validate declared dimensions against printer minimums."""
    minimums = printer_profile.get("minimums_mm")

    if not isinstance(minimums, dict):
        raise TypeError("Printer profile section 'minimums_mm' must be an object")

    issues: list[ValidationIssue] = []

    checks = {
        "wall": "wall",
        "floor": "floor",
        "label_height": "emboss_height",
        "label_size": "text_size",
    }

    for parameter_name, minimum_name in checks.items():
        if parameter_name not in parameters:
            continue

        value = parameters[parameter_name]
        minimum = minimums.get(minimum_name)

        if not isinstance(
            minimum,
            int | float,
        ):
            raise TypeError(
                f"Printer profile value 'minimums_mm.{minimum_name}' must be numeric"
            )

        if not isinstance(
            value,
            int | float,
        ):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code=(f"invalid_parameter_{parameter_name}"),
                    message=(f"Design parameter '{parameter_name}' must be numeric."),
                )
            )
            continue

        if value < minimum:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code=(f"minimum_{parameter_name}_violated"),
                    message=(
                        f"Design type '{design_type}' declares "
                        f"{parameter_name}={value:.3f} mm, "
                        f"below the printer minimum of "
                        f"{minimum:.3f} mm."
                    ),
                )
            )
        elif value < minimum * 1.25:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code=(f"minimum_{parameter_name}_near_limit"),
                    message=(
                        f"Design parameter "
                        f"'{parameter_name}' is "
                        f"{value:.3f} mm, close to the "
                        f"printer minimum of "
                        f"{minimum:.3f} mm."
                    ),
                )
            )

    tolerances = printer_profile.get("tolerances_mm")

    if not isinstance(tolerances, dict):
        raise TypeError("Printer profile section 'tolerances_mm' must be an object")

    if "lid_clearance" in parameters:
        clearance = parameters["lid_clearance"]
        recommended = tolerances.get("sliding_clearance_per_side")

        if not isinstance(
            recommended,
            int | float,
        ):
            raise ValueError(
                "Printer profile value "
                "'tolerances_mm."
                "sliding_clearance_per_side' "
                "must be numeric"
            )

        if not isinstance(
            clearance,
            int | float,
        ):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code=("invalid_parameter_lid_clearance"),
                    message=("Design parameter 'lid_clearance' must be numeric."),
                )
            )
        elif clearance < recommended:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="lid_clearance_below_profile",
                    message=(
                        f"Declared lid clearance is "
                        f"{clearance:.3f} mm per side, "
                        f"below the profile recommendation "
                        f"of {recommended:.3f} mm."
                    ),
                )
            )

    return issues


def validate_design_and_parts(
    *,
    design_type: str,
    parameters: dict[str, Any],
    parts: dict[str, cq.Workplane],
    printer_profile: dict[str, Any],
) -> list[ValidationIssue]:
    """Run all profile-aware validation rules."""
    issues = validate_design_parameters(
        design_type=design_type,
        parameters=parameters,
        printer_profile=printer_profile,
    )

    for part_name, model in parts.items():
        issues.extend(
            validate_build_volume(
                part_name=part_name,
                model=model,
                printer_profile=printer_profile,
            )
        )

    return issues


def raise_for_validation_errors(
    issues: list[ValidationIssue],
) -> None:
    """Raise a summarized exception when hard errors exist."""
    errors = [issue for issue in issues if issue.severity == "error"]

    if not errors:
        return

    messages = "\n".join(f"- [{issue.code}] {issue.message}" for issue in errors)

    raise ValueError(f"Profile-aware validation failed:\n{messages}")

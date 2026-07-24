"""Tests for profile-aware CAD validation."""

import cadquery as cq
import pytest

from zcad.validation.profile_rules import (
    raise_for_validation_errors,
    validate_build_volume,
    validate_design_and_parts,
    validate_design_parameters,
)


@pytest.fixture
def printer_profile() -> dict:
    """Return a compact test printer profile."""
    return {
        "build_volume_mm": {
            "x": 100,
            "y": 100,
            "z": 100,
        },
        "minimums_mm": {
            "wall": 1.2,
            "floor": 1.2,
            "emboss_height": 0.4,
            "text_size": 3.0,
        },
        "tolerances_mm": {
            "sliding_clearance_per_side": 0.2,
        },
    }


def test_valid_part_and_parameters_pass(
    printer_profile: dict,
) -> None:
    parts = {"main": (cq.Workplane("XY").box(50, 40, 20))}

    issues = validate_design_and_parts(
        design_type="tray",
        parameters={
            "wall": 2.0,
            "floor": 2.0,
        },
        parts=parts,
        printer_profile=printer_profile,
    )

    assert issues == []


def test_build_volume_violation_is_error(
    printer_profile: dict,
) -> None:
    model = cq.Workplane("XY").box(120, 40, 20)

    issues = validate_build_volume(
        part_name="oversized",
        model=model,
        printer_profile=printer_profile,
    )

    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].code == "build_volume_x_exceeded"


def test_minimum_wall_violation_is_error(
    printer_profile: dict,
) -> None:
    issues = validate_design_parameters(
        design_type="tray",
        parameters={
            "wall": 0.8,
        },
        printer_profile=printer_profile,
    )

    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].code == "minimum_wall_violated"


def test_near_minimum_creates_warning(
    printer_profile: dict,
) -> None:
    issues = validate_design_parameters(
        design_type="tray",
        parameters={
            "wall": 1.4,
        },
        printer_profile=printer_profile,
    )

    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].code == "minimum_wall_near_limit"


def test_tight_lid_clearance_creates_warning(
    printer_profile: dict,
) -> None:
    issues = validate_design_parameters(
        design_type="enclosure",
        parameters={
            "lid_clearance": 0.1,
        },
        printer_profile=printer_profile,
    )

    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].code == "lid_clearance_below_profile"


def test_validation_errors_raise(
    printer_profile: dict,
) -> None:
    issues = validate_design_parameters(
        design_type="tray",
        parameters={
            "wall": 0.8,
        },
        printer_profile=printer_profile,
    )

    with pytest.raises(
        ValueError,
        match="Profile-aware validation failed",
    ):
        raise_for_validation_errors(issues)


def test_warnings_do_not_raise(
    printer_profile: dict,
) -> None:
    issues = validate_design_parameters(
        design_type="tray",
        parameters={
            "wall": 1.4,
        },
        printer_profile=printer_profile,
    )

    raise_for_validation_errors(issues)

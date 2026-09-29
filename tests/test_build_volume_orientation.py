from typing import Any

import cadquery as cq
import pytest

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.validation.design_report import validate_design


@pytest.mark.parametrize("profile", [None, {"build_volume_mm": {"x": 0}}])
def test_unavailable_limits_never_produce_orientation_pass(
    profile: dict[str, Any] | None,
) -> None:
    report = validate_design(
        design_name="a",
        design_type="test",
        parts={"main": cq.Workplane().box(1, 2, 3)},
        printer_profile=profile,
        build_volume_orientation="xy_90",
    )
    check = next(c for c in report["checks"] if c["code"] == "build_volume")
    assert check["status"] == "NOT_CHECKED"
    assert "selected_rotation_z_degrees" not in check


def test_each_part_checked_independently_and_input_unchanged() -> None:
    model = cq.Workplane().box(170, 215, 10)
    before = workplane_shape(model).BoundingBox().ylen
    report = validate_design(
        design_name="a",
        design_type="test",
        parts={"fits": model, "too_tall": cq.Workplane().box(1, 1, 211)},
        printer_profile={"build_volume_mm": {"x": 250, "y": 210, "z": 210}},
        build_volume_orientation="xy_90",
    )
    checks = {
        c["part_name"]: c for c in report["checks"] if c["code"] == "build_volume"
    }
    assert checks["fits"]["status"] == "PASS"
    assert checks["too_tall"]["status"] == "FAIL"
    assert report["evaluated_status"] == "FAIL"
    assert workplane_shape(model).BoundingBox().ylen == before


def test_invalid_mode_rejected() -> None:
    with pytest.raises(ValueError, match="orientation"):
        validate_design(
            design_name="a",
            design_type="test",
            parts={},
            build_volume_orientation="xyz",
        )

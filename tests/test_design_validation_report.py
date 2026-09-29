import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.validation.design_report import DesignValidationError, validate_design


def assess(
    profile: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
    parts: dict[str, cq.Workplane] | None = None,
) -> dict[str, Any]:
    return validate_design(
        design_name="test",
        design_type="test",
        parts={"main": cq.Workplane().box(10, 10, 10)} if parts is None else parts,
        printer_profile=profile,
        parameters=parameters,
    )


def profile() -> dict[str, Any]:
    return {
        "build_volume_mm": {"x": 100, "y": 100, "z": 100},
        "minimums_mm": {"wall": 1.2},
        "tolerances_mm": {},
    }


def check(report: dict[str, Any], code: str) -> dict[str, Any]:
    return next(c for c in report["checks"] if c["code"] == code)


def test_missing_inputs_are_not_passes() -> None:
    report = assess()
    assert report["coverage"] == "PARTIAL"
    assert check(report, "build_volume")["status"] == "NOT_CHECKED"
    assert check(report, "declared_parameters")["status"] == "NOT_CHECKED"
    assert check(report, "physical_fit")["status"] == "NOT_CHECKED"


def test_pass_warning_and_failure_are_distinct() -> None:
    report = assess(profile(), {"wall": 1.3})
    assert report["evaluated_status"] == "PASS"
    assert report["warning_count"] == 1
    assert check(report, "build_volume")["status"] == "PASS"
    assert assess(profile(), {"wall": 0.5})["evaluated_status"] == "FAIL"
    assert (
        check(assess(profile(), {}), "declared_parameters")["status"] == "NOT_CHECKED"
    )


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1, 0])
def test_invalid_profile_limits_fail(bad: object) -> None:
    p = profile()
    p["build_volume_mm"]["x"] = bad
    assert assess(p)["evaluated_status"] == "FAIL"


def test_failed_geometry_and_empty_design() -> None:
    report = assess(parts={"bad": cq.Workplane().rect(10, 10)})
    assert report["evaluated_status"] == "FAIL"
    assert check(report, "build_volume")["status"] == "NOT_CHECKED"
    assert assess(parts={})["evaluated_status"] == "FAIL"


def test_export_embeds_report_and_rejects_profile_failure_before_writes(
    tmp_path: Path,
) -> None:
    result = export_parts(
        ExportRequest(
            "test",
            "test",
            {"main": cq.Workplane().box(10, 10, 10)},
            tmp_path / "good",
            tmp_path,
            printer_profile=profile(),
            parameters={"wall": 2},
        )
    )
    data = json.loads(result.parts[0].metadata_path.read_text())
    assert data["design_validation"] == result.validation_report
    p = profile()
    p["build_volume_mm"]["x"] = 5
    with pytest.raises(DesignValidationError) as error:
        export_parts(
            ExportRequest(
                "bad",
                "test",
                {"main": cq.Workplane().box(10, 10, 10)},
                tmp_path / "bad",
                tmp_path,
                printer_profile=p,
            )
        )
    assert error.value.report["evaluated_status"] == "FAIL"
    assert not (tmp_path / "bad").exists()

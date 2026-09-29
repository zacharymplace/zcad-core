"""Application validation is fail-closed and cannot modify exported geometry."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.validation.design_report import DesignValidationError


def test_hook_uses_isolated_snapshot(tmp_path: Path) -> None:
    def check(**kwargs: Any) -> list[dict[str, str]]:
        kwargs["parts"]["main"].objects.clear()
        return [{"code": "custom", "status": "PASS", "message": "checked"}]

    req = ExportRequest(
        "box",
        "box",
        {"main": cq.Workplane().box(2, 3, 4)},
        tmp_path / "out",
        tmp_path,
        feature_validator=check,
    )
    result = export_parts(req)
    assert result.parts[0].volume_mm3 == pytest.approx(24)
    assert workplane_shape(
        cq.importers.importStep(str(result.parts[0].step_path))
    ).Volume() == pytest.approx(24)


@pytest.mark.parametrize(
    "value", [None, [], [{"code": "x", "status": "UNKNOWN", "message": "bad"}]]
)
def test_malformed_hook_blocks_writes(tmp_path: Path, value: object) -> None:
    req = ExportRequest(
        "box", "box", {"main": cq.Workplane().box(2, 3, 4)}, tmp_path / "out", tmp_path
    )
    with pytest.raises(DesignValidationError):
        # A malformed hook result is the input under test.
        export_parts(replace(req, feature_validator=lambda **kw: value))  # type: ignore[arg-type]
    assert not req.output_directory.exists()


def test_hook_exception_blocks_writes(tmp_path: Path) -> None:
    def broken(**kwargs: Any) -> list[dict[str, str]]:
        raise RuntimeError("check failed")

    req = ExportRequest(
        "box",
        "box",
        {"main": cq.Workplane().box(2, 3, 4)},
        tmp_path / "out",
        tmp_path,
        feature_validator=broken,
    )
    with pytest.raises(DesignValidationError):
        export_parts(req)
    assert not req.output_directory.exists()

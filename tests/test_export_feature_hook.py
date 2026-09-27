"""Application validation is fail-closed and cannot modify exported geometry."""

from dataclasses import replace

import cadquery as cq
import pytest

from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.validation.design_report import DesignValidationError


def test_hook_uses_isolated_snapshot(tmp_path):
    def check(**kwargs):
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
    assert cq.importers.importStep(
        str(result.parts[0].step_path)
    ).val().Volume() == pytest.approx(24)


@pytest.mark.parametrize(
    "value", [None, [], [{"code": "x", "status": "UNKNOWN", "message": "bad"}]]
)
def test_malformed_hook_blocks_writes(tmp_path, value):
    req = ExportRequest(
        "box", "box", {"main": cq.Workplane().box(2, 3, 4)}, tmp_path / "out", tmp_path
    )
    with pytest.raises(DesignValidationError):
        export_parts(replace(req, feature_validator=lambda **kw: value))
    assert not req.output_directory.exists()


def test_hook_exception_blocks_writes(tmp_path):
    def broken(**kwargs):
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

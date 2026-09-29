from __future__ import annotations

from pathlib import Path

import pytest

from zcad_core.retention import (
    CornerCapturePolicy,
    ProductionBoardCornerAdapter,
)

# The vendor STEP file has the board lying in the XZ plane (Y = thickness
# axis); this is a Z-up copy produced once with a 90deg rotation about X.
# See scripts/generate-seeed-xiao-esp32s3-retention-evidence.py.
pytestmark = pytest.mark.slow

XIAO_ESP32S3_STEP = Path("evidence/seeed-xiao-esp32s3/step/xiao_esp32s3_z_up.step")

# At only 21 x 17.8mm, the default 3.0mm arm / 2.0mm engagement / 4.0mm
# keepout leaves no clear diagonal corner pair on this board - every corner
# has an interfering component within that footprint. 1.8mm arm / 0.3mm
# engagement (2.1mm keepout) is the smallest change that clears both
# derivation and manufacturing validation (see the generation script for
# the full explanation).
POLICY = CornerCapturePolicy(
    arm_width_mm=1.8,
    engagement_depth_mm=0.3,
    board_clearance_mm=0.25,
)

CORNER_KEEPOUT_MM = 2.1


@pytest.mark.skipif(
    not XIAO_ESP32S3_STEP.is_file(),
    reason=("Official Seeed XIAO ESP32-S3 STEP evidence is not available locally"),
)
def test_xiao_esp32s3_corner_derivation() -> None:
    adapter = ProductionBoardCornerAdapter(
        corner_keepout_mm=CORNER_KEEPOUT_MM,
    )
    model = adapter.import_model(
        source_step=XIAO_ESP32S3_STEP,
        pcb_solid_index=37,
    )

    derivation = adapter.derive(
        model=model,
        policy=POLICY,
    )

    assert derivation.request.board_thickness_mm == pytest.approx(
        1.25,
        abs=0.05,
    )
    assert len(derivation.selected_corners) == 2


@pytest.mark.skipif(
    not XIAO_ESP32S3_STEP.is_file(),
    reason=("Official Seeed XIAO ESP32-S3 STEP evidence is not available locally"),
)
def test_xiao_esp32s3_default_policy_has_no_clear_diagonal_corners() -> None:
    """Regression/documentation test: default policy does not fit this board.

    Confirms the finding behind the non-default POLICY/CORNER_KEEPOUT_MM
    used above and in the generation scripts, so a future change to
    CornerCapturePolicy's defaults doesn't silently make this board's
    evidence non-reproducible without anyone noticing why.
    """

    adapter = ProductionBoardCornerAdapter(corner_keepout_mm=4.0)
    model = adapter.import_model(
        source_step=XIAO_ESP32S3_STEP,
        pcb_solid_index=37,
    )

    with pytest.raises(
        ValueError,
        match="does not have two component-clear diagonal corners",
    ):
        adapter.derive(
            model=model,
            policy=CornerCapturePolicy(),
        )

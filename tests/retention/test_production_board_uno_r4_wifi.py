from __future__ import annotations

from pathlib import Path

import pytest

from zcad_core.retention import (
    CornerCapturePolicy,
    ProductionBoardCornerAdapter,
)

pytestmark = pytest.mark.slow

UNO_R4_WIFI_STEP = Path("evidence/arduino-uno-r4-wifi/step/UNO_R4_WIFI.step")


@pytest.mark.skipif(
    not UNO_R4_WIFI_STEP.is_file(),
    reason=("Official Arduino UNO R4 WiFi STEP evidence is not available locally"),
)
def test_uno_r4_wifi_has_no_clear_diagonal_corners() -> None:
    """Corner-capture retention does not fit this board's component layout.

    Three of the four board corners each have a tall (8-11mm) component
    within a keepout region sized to the default capture geometry's real
    footprint (arm_width_mm + engagement_depth_mm), most likely the USB-C
    connector, DC barrel jack, and a reset button or header assembly. The
    remaining corner's diagonal opposite is also blocked, so no diagonal
    pair is ever free regardless of arm_width_mm/engagement_depth_mm
    tuning (swept down to 2.0/1.2mm; still NO_CLEAR_CORNERS at every
    keepout matching that footprint).

    This documents a genuine per-board finding, not a code defect: the
    corner-capture strategy (see docs/roadmaps/validation-lab.md, "Explicitly
    deferred: additional retention strategies") does not generalize to every
    board layout. Edge capture (see
    test_production_edge_execution_uno_r4.py) generates real, validated
    retention geometry for this exact board via its negative-Y edge, which
    corner capture never considers.
    """

    adapter = ProductionBoardCornerAdapter(corner_keepout_mm=4.2)
    model = adapter.import_model(
        source_step=UNO_R4_WIFI_STEP,
        pcb_solid_index=1,
    )

    with pytest.raises(
        ValueError,
        match="does not have two component-clear diagonal corners",
    ):
        adapter.derive(
            model=model,
            policy=CornerCapturePolicy(),
        )

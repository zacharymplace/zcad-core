from __future__ import annotations

from pathlib import Path

import pytest

from zcad_core.retention import (
    CornerCapturePolicy,
    ProductionBoardCornerAdapter,
)

FEATHER_STEP = Path("evidence/adafruit-feather-rp2040/4884 Feather RP2040.step")


@pytest.mark.skipif(
    not FEATHER_STEP.is_file(),
    reason=("Official Feather RP2040 STEP evidence is not available locally"),
)
def test_feather_rp2040_corner_derivation() -> None:
    adapter = ProductionBoardCornerAdapter(
        corner_keepout_mm=4.0,
    )
    model = adapter.import_model(
        source_step=FEATHER_STEP,
        pcb_solid_index=1,
    )

    derivation = adapter.derive(
        model=model,
        policy=CornerCapturePolicy(),
    )

    assert derivation.request.board_thickness_mm == pytest.approx(
        1.57,
        abs=0.02,
    )
    assert len(derivation.selected_corners) == 2

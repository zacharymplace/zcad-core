from __future__ import annotations

from pathlib import Path

import pytest

from zcad_core.retention import (
    CornerCapturePolicy,
    ProductionBoardCornerAdapter,
)

PICO2_STEP = Path("evidence/raspberry-pi-pico-2/step/rpi_pico2.step")


@pytest.mark.skipif(
    not PICO2_STEP.is_file(),
    reason=("Official Raspberry Pi Pico 2 STEP evidence is not available locally"),
)
def test_pico2_corner_derivation() -> None:
    adapter = ProductionBoardCornerAdapter(
        corner_keepout_mm=4.0,
    )
    model = adapter.import_model(
        source_step=PICO2_STEP,
        pcb_solid_index=373,
    )

    derivation = adapter.derive(
        model=model,
        policy=CornerCapturePolicy(),
    )

    assert derivation.request.board_thickness_mm == pytest.approx(
        0.91,
        abs=0.02,
    )
    assert len(derivation.selected_corners) == 2
